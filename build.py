#!/usr/bin/env python3
"""
build.py — turn a report spec (+ data) into ONE self-contained HTML file.

Usage (CLI)
    python build.py spec.json out.html                  # spec already contains "data"
    python build.py spec.json out.html --data fact.csv  # encode a CSV/Parquet/XLSX as the data
    python build.py spec.json out.html --cdn            # load d3/Plot from pinned CDN instead of inlining
    python build.py spec.json out.html --theme corporativo   # override spec["theme"] (preset, path or JSON)

Usage (Python)
    import os, sys; sys.path.insert(0, os.environ.get("RELATORIO_KIT", "caminho/para/relatorio-html"))
    from build import build, encode_columnar
    spec["data"] = encode_columnar(df, date="data", dims=["regiao"], nums=["receita"])
    build(spec, "relatorio.html")

What it does
    1. validates the spec (fields referenced by KPIs/charts/filters exist, chart types are known)
    2. resolves the theme (spec["theme"]: preset name | path | inline overrides — see tema.py / TEMA.md),
       validates it, checks text contrast (warns < 4.5:1, auto-fixes ink on colored blocks)
    3. inlines Observable Plot + d3 (vendor/ or pinned CDN download) and the theme fonts
    4. escapes the JSON for safe embedding in <script type="application/json">
    5. writes the file and prints its size (warns above 8 MB)

The spec format is documented in SKILL.md ("Report spec").
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "template.html"
VENDOR = HERE / "vendor"
D3_VERSION = "7.9.0"
PLOT_VERSION = "0.6.17"
CDN = {
    "d3.min.js": f"https://cdn.jsdelivr.net/npm/d3@{D3_VERSION}/dist/d3.min.js",
    "plot.umd.min.js": f"https://cdn.jsdelivr.net/npm/@observablehq/plot@{PLOT_VERSION}/dist/plot.umd.min.js",
}
CHART_TYPES = {"line", "bars", "columns", "share", "multiples", "heatmap", "scatter", "dumbbell", "change", "histogram",
               # survey / CX charts (see cx.py and SKILL.md "Pesquisas de satisfação")
               "likert", "nps", "ci", "drivers", "trendci", "themes"}
AGGS = {"sum", "mean", "count", "distinct", "min", "max", "ratio", "nps"}
CI_KINDS = {"wilson", "nps", "mean"}
TIMEPARTS = {"$month", "$weekday", "$year"}
# layout grid: every chart spans 100 / 50 / 33 % of the 12-column content area (12 / 6 / 4 columns)
WIDTHS = {"full": 12, "half": 6, "third": 4}
DENSE = {"heatmap", "multiples"}            # many cells/panels: never narrower than half (third → half)
LONG = {"line", "trendci", "scatter"}       # long time axis or point cloud: warn at third


# --------------------------------------------------------------------------- #
# Data encoding                                                               #
# --------------------------------------------------------------------------- #
def encode_columnar(df, date: str | None = None, dims: list[str] | None = None,
                    nums: list[str] | None = None, decimals: int | dict = 2) -> dict:
    """Encode a pandas DataFrame in the template's compact columnar format.

    - date  -> integer days since 1970-01-01 (UTC)
    - dims  -> dictionary-encoded ints (null -> -1)
    - nums  -> rounded floats (null -> None). `decimals` may be a per-column dict.
    Typically 3–6x smaller than a list of row objects.
    """
    import pandas as pd

    dims = dims or []
    nums = nums or []
    cols = []
    if date:
        d = pd.to_datetime(df[date], errors="coerce")
        days = ((d - pd.Timestamp("1970-01-01")) // pd.Timedelta(days=1))
        cols.append({"key": date, "type": "date",
                     "values": [None if pd.isna(x) else int(x) for x in days]})
    for k in dims:
        s = df[k].astype("object").where(df[k].notna(), None)
        dict_ = sorted({str(v) for v in s if v is not None})
        idx = {v: i for i, v in enumerate(dict_)}
        cols.append({"key": k, "type": "cat", "dict": dict_,
                     "values": [-1 if v is None else idx[str(v)] for v in s]})
    for k in nums:
        nd = decimals.get(k, 2) if isinstance(decimals, dict) else decimals
        vals = []
        for v in pd.to_numeric(df[k], errors="coerce"):
            if v is None or (isinstance(v, float) and math.isnan(v)):
                vals.append(None)
            else:
                r = round(float(v), nd)
                vals.append(int(r) if r.is_integer() else r)
        cols.append({"key": k, "type": "num", "values": vals})
    return {"n": int(len(df)), "columns": cols}


def _load_table(path: str):
    """Small loader for --data (CSV/TSV/Parquet/XLSX/JSON). For messy files use profile.load_any."""
    return load_profile_module().load_any(path)


def load_profile_module():
    """Import the sibling profile.py by path (the name clashes with the stdlib `profile` module)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("report_profile", HERE / "profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #
# Step-0 briefing answers, stored so copy and section order can be traced back to them (see SKILL.md, Passo 0)
CONTEXT_KEYS = {"objetivo", "publico", "pontos_chave", "linguagem", "periodo", "recorte", "suposicoes", "exibir", "aprovado"}


def validate(spec: dict) -> list[str]:
    """Return a list of problems (empty = OK). Fatal issues raise ValueError."""
    problems: list[str] = []
    fields = spec.get("fields", {})
    dims = {d["key"] for d in fields.get("dims", [])}
    meas = {m["key"]: m for m in fields.get("measures", [])}
    data = spec.get("data")
    if data is None:
        raise ValueError("spec has no 'data' (pass --data or set spec['data'])")
    if isinstance(data, dict):
        keys = {c["key"] for c in data["columns"]}
    else:
        keys = set(data[0].keys()) if data else set()

    ctx = spec.get("contexto")
    if ctx is not None:
        if not isinstance(ctx, dict):
            problems.append("contexto must be a dict: {objetivo, publico, pontos_chave, linguagem, periodo, recorte, suposicoes, exibir}")
        else:
            for k, v in ctx.items():
                if k not in CONTEXT_KEYS:
                    problems.append(f"contexto.{k}: unknown key (valid: {sorted(CONTEXT_KEYS)})")
                elif k == "exibir" and not isinstance(v, bool):
                    problems.append("contexto.exibir must be true/false")
                elif k in ("pontos_chave", "suposicoes") and not isinstance(v, (str, list)):
                    problems.append(f"contexto.{k} must be a string or a list of strings")
                elif k == "linguagem" and not isinstance(v, (str, dict)):
                    problems.append("contexto.linguagem must be a string or {idioma, tom, nivel}")
    date = fields.get("date")
    if date and date not in keys:
        problems.append(f"fields.date '{date}' not in data columns")
    for d in dims:
        if d not in keys:
            problems.append(f"dim '{d}' not in data columns")
    for k, m in meas.items():
        agg = m.get("agg", "sum")
        if agg not in AGGS:
            problems.append(f"measure '{k}': agg '{agg}' unknown (valid: {sorted(AGGS)})")
        if m.get("ci") and m["ci"] not in CI_KINDS:
            problems.append(f"measure '{k}': ci '{m['ci']}' unknown (valid: {sorted(CI_KINDS)})")
        if agg == "ratio":
            need = [m["num"], m["den"]] + ([m["sumsq"]] if m.get("ci") == "mean" else [])
            if m.get("ci") == "mean" and not m.get("sumsq"):
                problems.append(f"measure '{k}': ci 'mean' needs 'sumsq' (column with score²)")
        elif agg == "nps":
            need = [m.get("pos"), m.get("neg"), m.get("den")]
        elif agg == "count":
            need = [m["field"]] if m.get("field") else []
        else:
            need = [m.get("field", k)]
        for f in need:
            if f not in keys:
                problems.append(f"measure '{k}' needs column '{f}' which is not in data")
        if "format" not in m:
            problems.append(f"measure '{k}' has no format (currency|number|decimal|percent|nps)")

    for k in spec.get("kpis", []):
        if k.get("measure") not in meas:
            problems.append(f"kpi measure '{k.get('measure')}' not defined in fields.measures")
    for f in spec.get("filters", {}).get("categorical", []):
        key = f["field"] if isinstance(f, dict) else f
        if key not in dims:
            problems.append(f"filter field '{key}' is not a declared dim")
    for s in spec.get("sections", []):
        for c in s.get("charts", []):
            t = c.get("type")
            if t not in CHART_TYPES:
                problems.append(f"chart type '{t}' unknown (valid: {sorted(CHART_TYPES)})")
            w = c.get("width")
            if w is not None and w not in WIDTHS:
                problems.append(f"chart '{c.get('title', t)}': width '{w}' unknown (valid: full | half | third — 100 / 50 / 33 % of the content grid)")
            sp = c.get("span")
            if w is None and sp is not None and sp not in WIDTHS:
                problems.append(f"chart '{c.get('title', t)}': span '{sp}' is not supported — use width: full | half | third")
            for key in ("measure", "x", "y", "r"):
                v = c.get(key)
                if v and key in ("x", "y") and t == "heatmap":
                    if v not in dims and v not in TIMEPARTS:
                        problems.append(f"heatmap axis '{v}' is neither a dim nor one of {sorted(TIMEPARTS)}")
                elif v and v not in meas:
                    problems.append(f"chart '{c.get('title', t)}': measure '{v}' not defined")
            for key in ("dim", "series"):
                v = c.get(key)
                if v and v not in dims:
                    problems.append(f"chart '{c.get('title', t)}': dim '{v}' not declared")
            for v in c.get("dims", []) or []:
                if v not in dims:
                    problems.append(f"chart '{c.get('title', t)}': dim '{v}' (in dims) not declared")
            if t == "likert" and c.get("field") not in keys:
                problems.append(f"likert chart '{c.get('title', t)}': field '{c.get('field')}' not in data")
            if t in ("ci", "drivers", "trendci", "nps") and c.get("measure") in meas and not meas[c["measure"]].get("ci"):
                problems.append(f"chart '{c.get('title', t)}' ({t}) needs a measure with 'ci' (wilson|nps|mean)")
            if t == "nps" and c.get("measure") in meas and meas[c["measure"]].get("agg") != "nps":
                problems.append(f"nps chart '{c.get('title', t)}': measure must have agg 'nps'")
            if t in ("line", "multiples", "dumbbell", "change", "trendci") and not date:
                problems.append(f"chart type '{t}' needs fields.date")
    return problems


# --------------------------------------------------------------------------- #
# One time grain per report + charts without data                             #
# --------------------------------------------------------------------------- #
GRAINS = ["day", "week", "month", "quarter", "year"]
TIME_CHARTS = {"line", "multiples", "trendci"}


def _columns(spec: dict) -> dict:
    """{key: list of python values} for either data format (columnar or list of row dicts). Dates → day numbers."""
    data = spec.get("data")
    if isinstance(data, dict):
        out = {}
        for c in data["columns"]:
            if c["type"] == "cat":
                d = c["dict"]
                out[c["key"]] = [None if i is None or i < 0 else d[i] for i in c["values"]]
            else:
                out[c["key"]] = c["values"]
        return out
    rows = data or []
    keys = {k for r in rows[:1000] for k in r}
    out = {k: [r.get(k) for r in rows] for k in keys}
    date = spec.get("fields", {}).get("date")
    if date in out:
        def day(v):
            if v is None or v == "":
                return None
            if isinstance(v, (int, float)):
                return int(v)
            try:
                return (dt.date.fromisoformat(str(v)[:10]) - dt.date(1970, 1, 1)).days
            except ValueError:
                return None
        out[date] = [day(v) for v in out[date]]
    return out


def resolve_time_grain(spec: dict, cols: dict) -> tuple[str | None, str]:
    """The single grain every time chart, KPI sparkline and the table's period grouping use.
    spec["time_grain"] (or legacy meta.grain) wins; "auto"/missing → from the data span, never finer than the data."""
    date = spec.get("fields", {}).get("date")
    meta = spec.get("meta", {})
    explicit = spec.get("time_grain") or meta.get("grain")
    if explicit and explicit != "auto":
        return explicit, "set in the spec"
    days = sorted({v for v in cols.get(date, []) if v is not None}) if date else []
    if not days:
        return None, "no date column"
    span = days[-1] - days[0]
    g = "day" if span <= 92 else "week" if span <= 550 else "month" if span <= 6 * 366 else "quarter"
    ds = [dt.date(1970, 1, 1) + dt.timedelta(days=d) for d in days]
    native = ("quarter" if all(x.day == 1 and x.month in (1, 4, 7, 10) for x in ds) and len(ds) > 1 else
              "month" if all(x.day == 1 for x in ds) else
              "week" if len({x.weekday() for x in ds}) == 1 and len(ds) > 1 else "day")
    floor = max(GRAINS.index(native), GRAINS.index(meta.get("minGrain") or "day"))
    g = GRAINS[max(GRAINS.index(g), floor)]
    return g, f"auto: {span + 1} days of data, finest grain in the data = {GRAINS[floor]}"


def _has(vals) -> bool:
    return any(v is not None and v != 0 for v in vals or [])


def measure_has_data(m: dict, cols: dict, n: int) -> bool:
    agg = m.get("agg", "sum")
    if agg in ("ratio", "nps"):
        return _has(cols.get(m.get("den")))
    if agg == "count":
        return _has(cols.get(m["field"])) if m.get("field") else n > 0
    vals = cols.get(m.get("field", m["key"]), [])
    return any(v is not None for v in vals) if agg in ("mean", "min", "max", "distinct") else _has(vals)


def chart_empty_reason(c: dict, meas: dict, dims: set, cols: dict, n: int) -> str | None:
    """why a chart would draw nothing for the whole data (None = it has data)"""
    if not n:
        return "the data has no rows"
    for key in ("measure", "r") + (("x", "y") if c.get("type") == "scatter" else ()):
        k = c.get(key)
        if k in meas and not measure_has_data(meas[k], cols, n):
            return f"measure '{k}' has no values"
    for key in ("dim", "series", "x", "y"):
        k = c.get(key)
        if k in dims and not any(v is not None for v in cols.get(k, [])):
            return f"dim '{k}' has no values"
    if c.get("dims") and not any(any(v is not None for v in cols.get(d, [])) for d in c["dims"]):
        return "none of its dims has values"
    if c.get("type") == "likert" and not any(v is not None for v in cols.get(c.get("field"), [])):
        return f"field '{c.get('field')}' has no answers"
    return None


def prune_empty(spec: dict, cols: dict) -> list[str]:
    """Drop charts (and then sections and KPIs) that have no data at all; return warnings. n > 0 groups are never dropped."""
    f = spec.get("fields", {})
    meas = {m["key"]: m for m in f.get("measures", [])}
    dims = {d["key"] for d in f.get("dims", [])}
    n = max((len(v) for v in cols.values()), default=0)
    warns, secs = [], []
    for s in spec.get("sections", []):
        charts = []
        for c in s.get("charts", []):
            why = chart_empty_reason(c, meas, dims, cols, n)
            if why:
                warns.append(f"chart '{c.get('title') or c.get('type')}' omitted: no data ({why})")
            else:
                charts.append(c)
        if s.get("charts") and not charts:
            warns.append(f"section '{s.get('toc') or s.get('title') or s.get('id')}' omitted: none of its charts has data (its menu/TOC entry goes too)")
            continue
        secs.append(dict(s, charts=charts))
    if "sections" in spec:
        spec["sections"] = secs
    kpis = []
    for k in spec.get("kpis", []):
        m = meas.get(k.get("measure"))
        if m and not measure_has_data(m, cols, n):
            warns.append(f"KPI '{k.get('label') or m.get('label')}' omitted: no data")
        else:
            kpis.append(k)
    if "kpis" in spec:
        spec["kpis"] = kpis
    return warns


def pack_widths(widths: list[str]) -> list[tuple[int, int, str, str]]:
    """Split a section's chart widths into rows → [(start, end, asked, final)]. A row holds one width only
    (3 thirds, 2 halves or 1 full); an incomplete row widens: 1 half/third → full, 2 thirds → 2 halves."""
    rows, i = [], 0
    while i < len(widths):
        w = widths[i]; per = 12 // WIDTHS[w]; j = i
        while j < len(widths) and j - i < per and widths[j] == w:
            j += 1
        k = j - i
        final = w if k == per else {1: "full", 2: "half"}[k]
        rows.append((i, j, w, final))
        i = j
    return rows


def layout_rows(spec: dict) -> list[str]:
    """Resolve every chart's width (legacy span → width, default full), pack rows, widen orphans; return warnings."""
    warns = []
    for s in spec.get("sections", []):
        charts = [dict(c) for c in s.get("charts", [])]
        for c in charts:
            name = c.get("title") or c.get("type")
            if "width" not in c and c.get("span") in WIDTHS:
                c["width"] = c["span"]
                warns.append(f"chart '{name}': 'span' is deprecated — read as width '{c['span']}'")
            c.pop("span", None)
            if c.pop("wide", None) is not None:
                warns.append(f"chart '{name}': 'wide' is ignored — every chart sits in the same content grid")
            c.setdefault("width", "full")
            if c["type"] in DENSE and c["width"] == "third":
                warns.append(f"chart '{name}' ({c['type']}) at width 'third' → half: a dense chart needs at least 50 %")
                c["width"] = "half"
            if c["type"] in LONG and c["width"] == "third":
                warns.append(f"chart '{name}' ({c['type']}) at width 'third': check that the axis still reads — half or full is safer")
        for a, b, asked, final in pack_widths([c["width"] for c in charts]):
            if final != asked:
                names = ", ".join(f"'{charts[q].get('title') or charts[q].get('type')}'" for q in range(a, b))
                warns.append(f"section '{s.get('toc') or s.get('title') or s.get('id')}': incomplete row of {b - a} × {asked} ({names}) → {final}")
                for q in range(a, b):
                    charts[q]["width"] = final
        s["charts"] = charts
    return warns


# --------------------------------------------------------------------------- #
# Assets                                                                      #
# --------------------------------------------------------------------------- #
def _asset(name: str) -> str:
    p = VENDOR / name
    if not p.exists():
        if name not in CDN:
            return ""
        VENDOR.mkdir(exist_ok=True)
        print(f"downloading {CDN[name]}", file=sys.stderr)
        p.write_bytes(urllib.request.urlopen(CDN[name], timeout=60).read())
    return p.read_text(encoding="utf-8")


def _safe_script(js: str) -> str:
    return js.replace("</script", "<\\/script")


def _json_for_script(obj) -> str:
    s = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), allow_nan=False, default=_default)
    return s.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def _default(o):
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if hasattr(o, "item"):  # numpy scalars
        return o.item()
    raise TypeError(f"not JSON serialisable: {type(o)}")


# --------------------------------------------------------------------------- #
# Build                                                                       #
# --------------------------------------------------------------------------- #
def load_tema_module():
    import importlib.util
    if "report_tema" in sys.modules:
        return sys.modules["report_tema"]
    spec = importlib.util.spec_from_file_location("report_tema", HERE / "tema.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["report_tema"] = mod          # dataclasses need the module registered
    spec.loader.exec_module(mod)
    return mod


def build(spec: dict, out: str | Path, *, cdn: bool = False, fonts: bool = True, strict: bool = True,
          theme=None, base_dir: str | Path | None = None) -> Path:
    """theme= overrides spec["theme"] (preset name, path to JSON, or dict of overrides).
    base_dir resolves relative theme/logo/font paths (default: current directory)."""
    problems = validate(spec)
    spec = dict(spec)
    cols = _columns(spec) if spec.get("data") is not None else {}
    grain, why = resolve_time_grain(spec, cols)
    if grain and grain not in GRAINS:
        problems.append(f"time_grain '{grain}' unknown (valid: {GRAINS} or 'auto')")
    for s in spec.get("sections", []):
        for c in s.get("charts", []):
            g = c.get("grain")
            if g and g not in GRAINS:
                problems.append(f"chart '{c.get('title', c.get('type'))}': grain '{g}' unknown (valid: {GRAINS})")
            elif g and g != grain and not c.get("grainOverride"):
                problems.append(f"chart '{c.get('title', c.get('type'))}': grain '{g}' differs from the report's time_grain '{grain}' — "
                                "every time chart uses one grain; drop 'grain', change spec['time_grain'], or set grainOverride: true on purpose")
            elif g and c.get("grainOverride"):
                print(f"spec: warning: chart '{c.get('title', c.get('type'))}' overrides the report grain ({grain} → {g})", file=sys.stderr)
    tm = load_tema_module()
    theme_spec = theme if theme is not None else spec.get("theme")
    th = tm.resolve(theme_spec, base_dir or Path.cwd(), legacy_meta=spec.get("meta", {}))
    problems += th.problems
    for w in th.warnings:
        print("theme:", w, file=sys.stderr)
    for p in problems:
        print("spec:", p, file=sys.stderr)
    if problems and strict:
        raise ValueError(f"{len(problems)} spec problem(s); fix them or call build(..., strict=False)")
    if grain:
        spec["time_grain"] = grain
        spec["meta"] = dict(spec.get("meta", {}), grain=grain)
        print(f"time grain: {grain} ({why})", file=sys.stderr)
    for w in prune_empty(spec, cols):
        print("spec: warning:", w, file=sys.stderr)
    spec["sections"] = [dict(s) for s in spec.get("sections", [])]
    for w in layout_rows(spec):
        print("spec: warning:", w, file=sys.stderr)
    spec.pop("theme", None)            # resolved below; the browser only needs the cfg
    spec["_theme"] = th.cfg

    spec.setdefault("meta", {}).setdefault("generated", dt.date.today().strftime("%d/%m/%Y") if str(spec["meta"].get("lang", "pt-BR")).startswith("pt") else dt.date.today().isoformat())
    html = TEMPLATE.read_text(encoding="utf-8")
    if cdn:
        d3_tag = f'</script><script src="{CDN["d3.min.js"]}"></script><script>'
        plot_tag = f'</script><script src="{CDN["plot.umd.min.js"]}"></script><script>'
        repl_d3, repl_plot = d3_tag, plot_tag
    else:
        repl_d3, repl_plot = _safe_script(_asset("d3.min.js")), _safe_script(_asset("plot.umd.min.js"))
    meta = spec["meta"]
    repl = {
        "/*__FONTS__*/": th.fonts_css if fonts else "",
        "/*__THEME__*/": th.css,
        "/*__D3__*/": repl_d3,
        "/*__PLOT__*/": repl_plot,
        "__REPORT_JSON__": _json_for_script(spec),
        "__TITLE__": _html_escape(meta.get("title", "Relatório")),
        "__LANG__": _html_escape(meta.get("lang", "pt-BR")),
    }
    # single pass so inserted content can never be re-substituted
    pattern = re.compile("|".join(re.escape(k) for k in repl))
    html = pattern.sub(lambda m: repl[m.group(0)], html)

    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    mb = out.stat().st_size / 1e6
    print(f"wrote {out} ({mb:.2f} MB, theme: {th.cfg.get('name') or 'custom'})")
    if mb > 8:
        print("warning: file > 8 MB — pre-aggregate further or sample the table rows", file=sys.stderr)
    return out


def _html_escape(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("out")
    ap.add_argument("--data", help="CSV/Parquet/XLSX/JSON fact table; encoded with spec.fields")
    ap.add_argument("--cdn", action="store_true", help="reference pinned CDN builds instead of inlining")
    ap.add_argument("--no-fonts", action="store_true", help="skip embedded fonts (system fallbacks are used)")
    ap.add_argument("--theme", help="preset name (temas/*.json), path to a theme JSON, or inline JSON overrides")
    ap.add_argument("--loose", action="store_true", help="write even if validation finds problems")
    ap.add_argument("--time-grain", choices=["auto", "day", "week", "month", "quarter", "year"], help="one grain for every time chart (default: spec or auto)")
    a = ap.parse_args()
    spec = json.loads(Path(a.spec).read_text(encoding="utf-8"))
    if a.data:
        df = _load_table(a.data)
        f = spec.get("fields", {})
        dims = [d["key"] for d in f.get("dims", [])]
        nums = [c for c in df.columns if c not in dims and c != f.get("date") and str(df[c].dtype) != "object"]
        spec["data"] = encode_columnar(df, date=f.get("date"), dims=dims, nums=nums)
    theme = None
    if a.theme:
        theme = json.loads(a.theme) if a.theme.strip().startswith("{") else a.theme
    if a.time_grain:
        spec["time_grain"] = a.time_grain
    build(spec, a.out, cdn=a.cdn, fonts=not a.no_fonts, strict=not a.loose, theme=theme,
          base_dir=Path(a.spec).resolve().parent)


if __name__ == "__main__":
    main()
