#!/usr/bin/env python3
"""
tema.py — theme engine for the report kit.

A theme is a JSON file (see temas/*.json and TEMA.md). The report spec field `theme` accepts:
    None / omitted            -> temas/neutro.json (the default)
    "corporativo"             -> a preset name from temas/
    "minha-marca.json"        -> a path to a theme JSON (may contain "extends": "<preset or path>")
    {...}                     -> inline overrides merged on top of the default (or of "extends")
Inline overrides also accept briefing-card shorthands:
    {"primary": "#0057FF", "accent": "#7AA7FF", "font": "Inter", "heading": "Fraunces",
     "mono": "JetBrains Mono", "logo": "logo.svg", "brand": "Acme"}

resolve(theme_spec, base_dir) -> Theme with .css (custom properties + @font-face), .cfg (for the
JS: hero style, motion, logo, brand), .warnings (validation + contrast notes), .data (merged JSON).

Fonts: {"family": "Inter", "source": "google"|"bundled"|"file"|"system", "weights": [400, 500],
        "files": {"400": "fonts/x.woff2"}, "fallback": "sans"|"serif"|"mono"}
       or a string shorthand: "Inter" (= Google Fonts, falls back to system), "google:Inter",
       "system:Georgia", "file:fonts/MarcaSans.woff2", "bundled:Geist".
Google fonts are downloaded once (latin + latin-ext woff2), cached in vendor/fonts-cache/ and
inlined as base64, so the report still opens offline.
"""
from __future__ import annotations

import base64
import copy
import json
import mimetypes
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRESETS = HERE / "temas"
VENDOR = HERE / "vendor"
FONT_CACHE = VENDOR / "fonts-cache"
DEFAULT = "neutro"
BUNDLED = {"geist": "Geist", "geist mono": "Geist Mono"}
FALLBACK = {
    "sans": 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    "serif": 'ui-serif, Georgia, Cambria, "Times New Roman", serif',
    "mono": 'ui-monospace, "SFMono-Regular", Menlo, Consolas, "Liberation Mono", monospace',
}
TOP_KEYS = {"name", "description", "mode", "brand", "fonts", "colors", "palette", "shape", "space", "type",
            "hero", "motion", "layout", "extends"}
SHORTHANDS = {"primary", "accent", "font", "heading", "body", "mono", "logo", "brand"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")


# --------------------------------------------------------------------------- #
# Color math (WCAG 2.x)                                                        #
# --------------------------------------------------------------------------- #
HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def is_hex(c) -> bool:
    return isinstance(c, str) and bool(HEX.match(c.strip()))


def rgb(c: str) -> tuple[float, float, float]:
    h = c.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def hexof(t) -> str:
    return "#" + "".join(f"{max(0, min(255, round(v * 255))):02X}" for v in t)


def lum(c: str) -> float:
    def ch(v):
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(v) for v in rgb(c))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """t=0 -> a, t=1 -> b (sRGB)"""
    ra, rb_ = rgb(a), rgb(b)
    return hexof(tuple(x + (y - x) * t for x, y in zip(ra, rb_)))


def best_ink(bg: str, prefer: str | None = None, dark="#000000", light="#FFFFFF") -> str:
    if prefer and is_hex(prefer) and contrast(prefer, bg) >= 4.5:
        return prefer
    return dark if contrast(dark, bg) >= contrast(light, bg) else light


def text_variant(color: str, bg, ink: str, target=4.5) -> str:
    """the closest shade of `color` (mixed toward `ink`) that reads as text on `bg` —
    `bg` may be a list (page, card, hover row): the shade must pass on the hardest of them"""
    bgs = [bg] if isinstance(bg, str) else list(bg)
    for i in range(0, 41):
        c = mix(color, ink, i / 40)
        if min(contrast(c, b) for b in bgs) >= target:
            return c
    return ink


def muted_on(bg: str, ink: str, start=0.6, target=4.5) -> str:
    """solid 'muted' text color on a colored block: ink faded toward bg, but never below target contrast"""
    for a in [start + i * 0.04 for i in range(0, 12)]:
        c = mix(bg, ink, min(1, a))
        if contrast(c, bg) >= target:
            return c
    return ink


def spread(colors: list[str], n: int) -> list[str]:
    """resample a color ramp to n stops"""
    if len(colors) == n:
        return list(colors)
    out = []
    for i in range(n):
        x = i / (n - 1) * (len(colors) - 1)
        j = min(int(x), len(colors) - 2)
        out.append(mix(colors[j], colors[j + 1], x - j))
    return out


# --------------------------------------------------------------------------- #
# Loading + merging                                                            #
# --------------------------------------------------------------------------- #
def deep_merge(a: dict, b: dict) -> dict:
    out = copy.deepcopy(a)
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def presets() -> list[str]:
    return sorted(p.stem for p in PRESETS.glob("*.json"))


ALIASES = {"editorial": "destaque"}      # old preset name (before "neutro" became the default)


def _load_ref(ref: str, base_dir: Path, seen: set) -> dict:
    ref = ALIASES.get(ref, ref)
    p = PRESETS / f"{ref}.json"
    if not p.exists():
        p = Path(ref)
        if not p.is_absolute():
            p = (base_dir / p) if (base_dir / p).exists() else Path.cwd() / p
    if not p.exists():
        raise ValueError(f"theme '{ref}' not found (presets: {', '.join(presets())}; or pass a path to a .json)")
    key = str(p.resolve())
    if key in seen:
        raise ValueError(f"theme 'extends' loop at {p}")
    seen.add(key)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["_dir"] = str(p.parent)
    if p.parent.resolve() == PRESETS.resolve():
        data["_preset"] = p.stem
    return _with_parent(data, p.parent, seen)


def _with_parent(data: dict, base_dir: Path, seen: set) -> dict:
    parent = data.get("extends")
    is_default_file = Path(data.get("_dir", "")) == PRESETS and data.get("_preset") == DEFAULT
    if parent:
        return deep_merge(_load_ref(parent, base_dir, seen), {k: v for k, v in data.items() if k != "extends"})
    if is_default_file:
        return data
    return deep_merge(_load_ref(DEFAULT, base_dir, seen), data)


def expand_shorthands(o: dict) -> dict:
    o = dict(o)
    out: dict = {}
    if "primary" in o:
        out.setdefault("colors", {})["primary"] = o.pop("primary")
    if "accent" in o:
        acc = o.pop("accent")
        out.setdefault("colors", {})["accent"] = acc
        out.setdefault("palette", {})["positive"] = acc
    font = o.pop("font", None)
    for role in ("heading", "body", "mono"):
        v = o.pop(role, None) or (font if role != "mono" and font else None)
        if v:
            out.setdefault("fonts", {})[role] = v
    if "logo" in o:
        out.setdefault("brand", {})["logo"] = o.pop("logo")
    if isinstance(o.get("brand"), str):
        out.setdefault("brand", {})["name"] = o.pop("brand")
    return deep_merge(o, out)


def load(theme_spec=None, base_dir: str | Path | None = None) -> dict:
    base = Path(base_dir or Path.cwd())
    seen: set = set()
    if theme_spec is None or theme_spec == "":
        data = _load_ref(DEFAULT, base, seen)
    elif isinstance(theme_spec, str):
        data = _load_ref(theme_spec, base, seen)
    elif isinstance(theme_spec, dict):
        o = expand_shorthands(theme_spec)
        data = _with_parent(o, base, seen) if o.get("extends") else deep_merge(_load_ref(DEFAULT, base, seen), o)
    else:
        raise ValueError("theme must be a preset name, a path, or a dict of overrides")
    data.setdefault("_dir", str(base))
    # a dark/light block may override the shared primary/accent per mode
    return data


# --------------------------------------------------------------------------- #
# Fonts                                                                        #
# --------------------------------------------------------------------------- #
def _norm_font(v, role: str) -> dict:
    if isinstance(v, dict):
        f = dict(v)
    else:
        s = str(v).strip()
        m = re.match(r"^(google|system|file|bundled):(.*)$", s, re.I)
        if m:
            src, val = m.group(1).lower(), m.group(2).strip()
            f = {"source": src}
            if src == "file":
                f["files"] = {"400": val}
                f["family"] = Path(val).stem.split("-")[0]
            else:
                f["family"] = val
        else:
            f = {"family": s, "source": "bundled" if s.lower() in BUNDLED else "auto"}
    f.setdefault("fallback", "mono" if role == "mono" else "sans")
    f.setdefault("weights", [400, 500] if role != "mono" else [400])
    if f.get("files"):
        f["source"] = "file"
    if str(f.get("family", "")).lower() in BUNDLED and f.get("source") in (None, "auto"):
        f["source"] = "bundled"
    return f


def _google_css(family: str, weights: list[int], warnings: list[str]) -> str:
    FONT_CACHE.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-") + "-" + "-".join(map(str, sorted(set(weights))))
    cached = FONT_CACHE / f"{slug}.css"
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    fam = urllib.parse.quote_plus(family)
    urls = [f"https://fonts.googleapis.com/css2?family={fam}:wght@{';'.join(map(str, sorted(set(weights))))}&display=swap",
            f"https://fonts.googleapis.com/css2?family={fam}&display=swap"]
    css = None
    for u in urls:
        try:
            css = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=30).read().decode("utf-8")
            break
        except Exception as e:  # noqa: BLE001
            last = e
    if css is None:
        warnings.append(f"font '{family}': Google Fonts download failed ({last}); using the system fallback stack")
        return ""
    # keep latin + latin-ext only (pt-BR needs both); everything else is dead weight
    blocks = re.findall(r"/\*\s*([\w-]+)\s*\*/\s*(@font-face\s*{[^}]*})", css)
    if not blocks:
        blocks = [("latin", b) for b in re.findall(r"@font-face\s*{[^}]*}", css)]
    # variable fonts: Google repeats the same file once per weight -> one face with a weight range
    groups: dict = {}
    for subset, block in blocks:
        if subset not in ("latin", "latin-ext"):
            continue
        url = re.search(r"url\(([^)]+)\)", block).group(1)
        w = int(re.search(r"font-weight:\s*(\d+)", block).group(1))
        st = re.search(r"font-style:\s*(\w+)", block).group(1)
        ur = re.search(r"unicode-range:\s*([^;]+);", block)
        g = groups.setdefault(url, {"subset": subset, "style": st, "w": [], "ur": ur.group(1) if ur else None})
        g["w"].append(w)
    out = []
    for url, g in groups.items():
        data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60).read()
        wt = f"{min(g['w'])} {max(g['w'])}" if len(set(g["w"])) > 1 else str(g["w"][0])
        out.append(f"/* {family} {g['subset']} */\n@font-face{{font-family:'{family}';font-style:{g['style']};font-weight:{wt};font-display:swap;"
                   f"src:url(data:font/woff2;base64,{base64.b64encode(data).decode()}) format('woff2');"
                   + (f"unicode-range:{g['ur']};" if g["ur"] else "") + "}")
    text = "\n".join(out)
    cached.write_text(text, encoding="utf-8")
    return text


def _file_css(f: dict, base_dir: Path, warnings: list[str]) -> str:
    out = []
    fmts = {".woff2": "woff2", ".woff": "woff", ".ttf": "truetype", ".otf": "opentype"}
    for w, path in (f.get("files") or {}).items():
        p = Path(path)
        if not p.is_absolute():
            p = base_dir / p
        if not p.exists():
            warnings.append(f"font file not found: {p}")
            continue
        fmt = fmts.get(p.suffix.lower())
        if not fmt:
            warnings.append(f"font file {p.name}: unsupported extension (use .woff2, .woff, .ttf or .otf)")
            continue
        mime = "font/" + ("woff2" if fmt == "woff2" else "woff" if fmt == "woff" else "ttf" if fmt == "truetype" else "otf")
        b64 = base64.b64encode(p.read_bytes()).decode()
        weight = "100 900" if str(w).lower() in ("var", "variable") else str(w)
        style = "italic" if "italic" in p.stem.lower() else "normal"
        out.append(f"@font-face{{font-family:'{f['family']}';font-style:{style};font-weight:{weight};font-display:swap;"
                   f"src:url(data:{mime};base64,{b64}) format('{fmt}');}}")
    return "\n".join(out)


def fonts_css(fonts: dict, base_dir: Path, warnings: list[str]) -> tuple[dict, str]:
    """-> ({role: css font-family stack}, @font-face css)"""
    stacks, faces, done = {}, [], set()
    need_bundled = False
    for role in ("heading", "body", "mono"):
        f = _norm_font(fonts.get(role) or ("Geist Mono" if role == "mono" else "Geist"), role)
        fam = f["family"]
        src = f["source"]
        if src == "bundled" and fam.lower() not in BUNDLED:
            warnings.append(f"font '{fam}' is not bundled (only Geist / Geist Mono); trying Google Fonts")
            src = "auto"
        key = (fam.lower(), src, tuple(sorted(f["weights"])))
        if src == "bundled":
            need_bundled = True
        elif key not in done:
            done.add(key)
            if src in ("google", "auto"):
                css = _google_css(fam, f["weights"], warnings)
                if not css and src == "auto":
                    warnings[-1] = f"font '{fam}': not found on Google Fonts / offline; assuming it is installed locally (system font)"
                faces.append(css)
            elif src == "file":
                faces.append(_file_css(f, base_dir, warnings))
        stacks[role] = f'"{fam}", {FALLBACK.get(f["fallback"], FALLBACK["sans"])}'
    if need_bundled:
        p = VENDOR / "fonts.css"
        faces.insert(0, p.read_text(encoding="utf-8") if p.exists() else "")
    return stacks, "\n".join(x for x in faces if x)


# --------------------------------------------------------------------------- #
# Logo                                                                         #
# --------------------------------------------------------------------------- #
def logo_uri(src, base_dir: Path, warnings: list[str]) -> str | None:
    if not src:
        return None
    s = str(src)
    if s.startswith("data:"):
        return s
    try:
        if re.match(r"^https?://", s):
            data = urllib.request.urlopen(urllib.request.Request(s, headers={"User-Agent": UA}), timeout=30).read()
            mime = mimetypes.guess_type(urllib.parse.urlparse(s).path)[0] or ("image/svg+xml" if data.lstrip()[:5] in (b"<?xml", b"<svg ") else "image/png")
        else:
            p = Path(s)
            if not p.is_absolute():
                p = base_dir / p
            data = p.read_bytes()
            mime = mimetypes.guess_type(p.name)[0] or "image/png"
    except Exception as e:  # noqa: BLE001
        warnings.append(f"logo '{s}' could not be read ({e}); showing the brand name instead")
        return None
    if len(data) > 300_000:
        warnings.append(f"logo is {len(data) / 1e3:.0f} KB; prefer an SVG or a PNG under ~100 KB")
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


# --------------------------------------------------------------------------- #
# Resolve                                                                      #
# --------------------------------------------------------------------------- #
@dataclass
class Theme:
    data: dict
    css: str = ""
    fonts_css: str = ""
    cfg: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    problems: list = field(default_factory=list)


def _num(d: dict, k: str, default, lo, hi, probs: list, where: str):
    v = d.get(k, default)
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not (lo <= v <= hi):
        probs.append(f"theme {where}.{k} = {v!r} must be a number in [{lo}, {hi}]")
        return default
    return v


def validate(data: dict) -> list[str]:
    probs = []
    for k in data:
        if not k.startswith("_") and k not in TOP_KEYS:
            probs.append(f"theme: unknown key '{k}' (valid: {sorted(TOP_KEYS)})")
    if data.get("mode", "auto") not in ("auto", "light", "dark"):
        probs.append("theme.mode must be auto | light | dark")
    cols = data.get("colors", {})
    for k in ("primary", "accent"):
        if not is_hex(cols.get(k)):
            probs.append(f"theme.colors.{k} must be a hex color like #FE7445 (got {cols.get(k)!r})")
    for mode in ("light", "dark"):
        for k, v in (cols.get(mode) or {}).items():
            if not is_hex(v):
                probs.append(f"theme.colors.{mode}.{k} must be a hex color (got {v!r})")
    pal = data.get("palette", {})
    for k in ("categorical", "sequential", "sequentialDark", "diverging", "categoricalDark"):
        v = pal.get(k)
        if v is None:
            continue
        if not isinstance(v, list) or not all(is_hex(c) for c in v):
            probs.append(f"theme.palette.{k} must be a list of hex colors")
    if len(pal.get("categorical", [])) < 3:
        probs.append("theme.palette.categorical needs at least 3 colors (8 recommended)")
    if pal.get("diverging") is not None and len(pal["diverging"]) < 3:
        probs.append("theme.palette.diverging needs at least 3 colors (5 recommended: strong neg … neutral … strong pos)")
    for k in ("positive", "negative"):
        if pal.get(k) is not None and not is_hex(pal[k]):
            probs.append(f"theme.palette.{k} must be a hex color")
    if (data.get("layout") or {}).get("style", "clean") not in ("clean", "blocks"):
        probs.append("theme.layout.style must be 'clean' (plain header, KPI cards, light footer) or 'blocks' (full-bleed color hero + KPI band)")
    g = (data.get("layout") or {}).get("grid")
    if g is not None:
        if not isinstance(g, dict):
            probs.append("theme.layout.grid must be an object {maxWidth, rail, railGap, gutter, pad}")
        else:
            for k in g:
                if not k.startswith("_") and k not in ("maxWidth", "rail", "railGap", "gutter", "pad"):
                    probs.append(f"theme.layout.grid: unknown key '{k}' (valid: maxWidth, rail, railGap, gutter, pad)")
    if data.get("hero", {}).get("style", "block") not in ("block", "plain"):
        probs.append("theme.hero.style must be 'block' (full-bleed color) or 'plain'")
    return probs


def resolve(theme_spec=None, base_dir: str | Path | None = None, *, legacy_meta: dict | None = None) -> Theme:
    data = load(theme_spec, base_dir)
    legacy_meta = legacy_meta or {}
    # backward compatibility: meta.accent / meta.hero
    if legacy_meta.get("accent"):
        data = deep_merge(data, {"colors": {"accent": legacy_meta["accent"]}, "palette": {"positive": legacy_meta["accent"]}})
        cat = list(data["palette"]["categorical"]); cat[0] = legacy_meta["accent"]; data["palette"]["categorical"] = cat
    if legacy_meta.get("hero"):
        data = deep_merge(data, {"colors": {"primary": legacy_meta["hero"]}, "palette": {"negative": legacy_meta["hero"]}})
    th = Theme(data=data)
    th.problems = validate(data)
    if th.problems:
        return th
    W = th.warnings
    tdir = Path(data.get("_dir") or base_dir or Path.cwd())

    stacks, faces = fonts_css(data.get("fonts", {}), tdir, W)
    th.fonts_css = faces

    cols, pal = data["colors"], data["palette"]
    shape, space, typ, motion, hero = (data.get(k, {}) for k in ("shape", "space", "type", "motion", "hero"))
    P = th.problems
    root = {
        "--sans": stacks["body"], "--heading": stacks["heading"], "--mono": stacks["mono"],
        "--hw": str(int(_num(typ, "headingWeight", 500, 100, 900, P, "type"))),
        "--track": str(_num(typ, "tracking", 1, 0, 2, P, "type")),
        "--lh-hero": str(_num(typ, "heroLineHeight", 0.95, 0.8, 1.4, P, "type")),
        "--fs-hero": str(_num(typ, "hero", 120, 40, 200, P, "type")),
        "--fs-h2": str(_num(typ, "h2", 40, 20, 80, P, "type")),
        "--fs-chart": str(_num(typ, "chartTitle", 24, 14, 48, P, "type")),
        "--fs-kpi": str(_num(typ, "kpi", 85, 32, 140, P, "type")),
        "--fs-label": str(_num(typ, "kpiLabel", 24, 12, 40, P, "type")),
        "--fs-dek": str(_num(typ, "dek", 32, 16, 56, P, "type")),
        "--fs-body": str(_num(typ, "body", 16, 13, 20, P, "type")),
        "--sp-section": str(_num(space, "section", 120, 32, 240, P, "space")),
        "--sp-chart": str(_num(space, "chartGap", 88, 24, 160, P, "space")),
        "--sp-band": str(_num(space, "band", 56, 16, 120, P, "space")),
        "--radius": f"{_num(shape, 'radius', 0, 0, 24, P, 'shape')}px",
        "--rule-w": f"{_num(shape, 'rule', 1, 0, 4, P, 'shape')}px",
        "--rule-strong-w": f"{_num(shape, 'ruleStrong', 2, 0, 6, P, 'shape')}px",
        "--rule-section-w": f"{_num(shape, 'ruleSection', 1, 0, 8, P, 'shape')}px",
        "--mk": str(_num(motion, "speed", 1, 0.25, 4, P, "motion")),
    }
    layout = data.get("layout") or {}
    area_l = _num(layout, "areaOpacity", 0.6, 0.05, 1, P, "layout")
    area_d = _num(layout, "areaOpacityDark", max(area_l, min(1, area_l * 1.4)), 0.05, 1, P, "layout")
    # layout grid: page max width · reserved menu rail · gap rail→content · 12-column gutter · outer padding.
    # Content column max = maxWidth − 2·pad − rail − railGap (1440 − 64 − 200 − 48 = 1128 px by default).
    grid = layout.get("grid") or {}
    root.update({
        "--maxw": f"{_num(grid, 'maxWidth', 1440, 1024, 1920, P, 'layout.grid')}px",
        "--rail": f"{_num(grid, 'rail', 200, 140, 280, P, 'layout.grid')}px",
        "--rail-gap": f"{_num(grid, 'railGap', 48, 16, 120, P, 'layout.grid')}px",
        "--gutter": f"{_num(grid, 'gutter', 32, 12, 64, P, 'layout.grid')}px",
        "--pad-d": f"{_num(grid, 'pad', 32, 12, 64, P, 'layout.grid')}px",
    })

    def mode_vars(mode: str) -> dict:
        m = dict(cols[mode])
        bg, ink = m["bg"], m["ink"]
        surface, surface2 = m.get("surface", bg), m.get("surface2", mix(bg, ink, 0.04))
        muted, faint = m.get("muted", mix(bg, ink, 0.6)), m.get("faint", mix(bg, ink, 0.4))
        primary = m.get("primary", cols["primary"])
        accent = m.get("accent", cols["accent"])
        pos = m.get("positive", pal.get("positive", accent))
        neg = m.get("negative", pal.get("negative", primary))
        label = f"{mode} theme"
        for name, c in (("ink", ink), ("muted", muted)):
            r = contrast(c, bg)
            if r < 4.5:
                W.append(f"contrast: {label} {name} {c} on bg {bg} is {r:.2f}:1 (< 4.5:1) — body text will be hard to read")
        r = contrast(muted, surface2)
        if r < 4.5 and contrast(muted, bg) >= 4.5:
            W.append(f"contrast: {label} muted {muted} on surface2 {surface2} is {r:.2f}:1 (table hover rows)")

        def auto_ink(block_name, block, declared=None):
            ink2 = best_ink(block, declared)
            if declared and ink2 != declared:
                W.append(f"contrast: {label} text on {block_name} {block}: {declared} is {contrast(declared, block):.2f}:1 → auto-adjusted to {ink2} ({contrast(ink2, block):.2f}:1)")
            elif contrast(ink2, block) < 4.5:
                W.append(f"contrast: {label} {block_name} {block} can't reach 4.5:1 with black or white text (best {contrast(ink2, block):.2f}:1) — pick a lighter or darker color")
            return ink2

        hero_ink = auto_ink("primary block", primary, m.get("heroInk") or ("#000000" if lum(primary) > 0.18 else None))
        footer_bg = m.get("footerBg", "#000000")
        footer_ink = auto_ink("footer", footer_bg, m.get("footerInk"))
        brand_bg = m.get("brandBg", footer_bg)
        brand_ink = auto_ink("brand block", brand_bg, m.get("brandInk"))
        tip_bg = m.get("tipBg", ink)
        tip_ink = auto_ink("tooltip", tip_bg, m.get("tipInk", bg))
        accent_ink = auto_ink("accent chip", accent, m.get("accentInk"))
        art_bg = m.get("artBg", footer_bg)
        seq = pal.get("sequential")
        if mode == "dark":
            seq = pal.get("sequentialDark") or [surface2, seq[-1], seq[len(seq) // 2]]
        seq = spread(seq, 3)
        cat = list(pal.get("categoricalDark") if mode == "dark" and pal.get("categoricalDark") else pal["categorical"])
        cat = [c if contrast(c, bg) >= 1.35 else ink for c in cat]       # a near-bg color vanishes: swap for ink
        while len(cat) < 8:
            cat.append(mix(cat[len(cat) % max(1, len(pal["categorical"]))], bg, 0.45))
        div = spread(pal.get("diverging") or [neg, mix(neg, bg, 0.55), m.get("context", mix(bg, ink, 0.12)), mix(pos, bg, 0.4), pos], 5)
        v = {
            "--bg": bg, "--surface": surface, "--surface-2": surface2, "--ink": ink, "--ink-2": m.get("ink2", mix(ink, bg, 0.07)),
            "--muted": muted, "--faint": faint, "--rule": m.get("rule", mix(bg, ink, 0.12)), "--rule-strong": m.get("ruleStrong", ink),
            "--primary": primary, "--primary-text": text_variant(primary, bg, ink),
            "--hero-ink": hero_ink, "--hero-muted": muted_on(primary, hero_ink), "--hero-rule": mix(primary, hero_ink, 0.85),
            "--accent": accent, "--accent-deep": text_variant(accent, bg, ink), "--accent-ink": accent_ink,
            "--pos": pos, "--pos-ink": text_variant(pos, [bg, surface, surface2], ink), "--neg": neg, "--neg-ink": text_variant(neg, [bg, surface, surface2], ink),
            # good/bad deltas on the colored hero block (blocks layout) — light tints that still pass 4.5:1 there
            "--hero-pos": text_variant(m.get("heroPos", pos), primary, hero_ink), "--hero-neg": text_variant(m.get("heroNeg", neg), primary, hero_ink),
            "--context": m.get("context", mix(bg, ink, 0.1)), "--line": m.get("line", ink),
            "--tip-bg": tip_bg, "--tip-ink": tip_ink,
            "--heat-lo": seq[0], "--heat-mid": seq[1], "--heat-hi": seq[2], "--heat-ink-hi": best_ink(seq[2]),
            "--footer-bg": footer_bg, "--footer-ink": footer_ink, "--brand-bg": brand_bg, "--brand-ink": brand_ink,
            "--art-bg": art_bg, "--art-ink": best_ink(art_bg, "#FFFFFF"),
            "--area-op": str(area_d if mode == "dark" else area_l),
        }
        for i, c in enumerate(cat[:8], 1):
            v[f"--c{i}"] = c
        for i, c in enumerate(div, 1):
            v[f"--dv{i}"] = c
        for i, c in enumerate(div, 1):
            v[f"--dv{i}-ink"] = best_ink(c)
        return v

    light, dark = mode_vars("light"), mode_vars("dark")
    decl = lambda d: ";".join(f"{k}:{v}" for k, v in d.items())  # noqa: E731
    th.css = f":root{{{decl(root)};{decl(light)}}}\n[data-theme=\"dark\"]{{{decl(dark)}}}"

    brand = data.get("brand") or {}
    th.cfg = {
        "name": data.get("name"), "mode": data.get("mode", "auto"),
        "layout": layout.get("style", "clean"),
        "hero": hero.get("style", "block"), "art": bool(hero.get("art", True)),
        "motion": bool(motion.get("enabled", True)), "speed": root["--mk"] and float(root["--mk"]),
        "brand": brand.get("name"), "logo": logo_uri(brand.get("logo"), tdir, W),
        "logoHeight": brand.get("logoHeight", 26),
    }
    return th


def main():
    import argparse
    ap = argparse.ArgumentParser(description="resolve a theme and print warnings / generated CSS variables")
    ap.add_argument("theme", nargs="?", help=f"preset ({', '.join(presets())}) or path to JSON")
    ap.add_argument("--css", action="store_true", help="print the generated custom properties")
    a = ap.parse_args()
    th = resolve(a.theme)
    for p in th.problems:
        print("✗", p)
    for w in th.warnings:
        print("!", w)
    if a.css:
        print(th.css)
    print(json.dumps({k: (v[:40] + "…" if isinstance(v, str) and len(v) > 60 else v) for k, v in th.cfg.items()}, ensure_ascii=False))
    sys.exit(1 if th.problems else 0)


if __name__ == "__main__":
    main()
