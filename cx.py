#!/usr/bin/env python3
"""
cx.py — customer-survey metrics (CSAT, CES, NPS) for the report kit, computed from RESPONSE-LEVEL rows.

Everything is expressed as sums of row-level indicator columns, so every metric is a ratio of sums
and stays exact under any cross-filter in the browser (the template recomputes the same formulas,
confidence intervals and tests from the filtered rows; see SKILL.md "Pesquisas de satisfação").

    import cx
    df = cx.load("respostas.xlsx")                    # or profile.load_any
    m = cx.detect(df)                                 # guess score / date / comment / segment columns
    print(cx.briefing(m))                             # paste into the briefing card, ask the user to confirm
    prep = cx.prepare(df, m, segments={"Canal": "canal", "UF": "uf"})
    prep = cx.add_invitations(prep, disparos, date="Data", count="Enviadas", keys={"Canal": "canal"})  # optional
    th = cx.comment_themes(prep.comments, band=prep.fact["faixa_nps"])                                  # optional
    prep.fact["tema"] = th.labels

Formulas (defaults; all configurable in the mapping):
    CSAT  = Σ[score ≥ threshold] / Σ[answered]          1–5 scale, threshold 4 (top-2 box)
    CES   = Σscore / Σ[answered]  (mean)  and  %fácil = Σ[easy] / Σ[answered]
            1–7: easy ≥ 5 (higher_easier) or ≤ 3 (lower_easier); 1–5: easy ≥ 4 or ≤ 2
    NPS   = (Σ[9–10] − Σ[0–6]) / Σ[answered]            shown ×100 as points (−100…+100)
Statistics (95% by default):
    proportions -> Wilson score interval;  NPS -> variance-based  se = √((P + D − (P − D)²) / n);
    CES mean -> t interval (Cornish–Fisher t quantile);  differences -> two-sided z test on
    independent samples (group vs. rest of the base, or period vs. previous period),
    Holm correction when several groups are tested together.  n < min_n (default 30) is FLAGGED
    ("amostra pequena"), never hidden.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LEVEL = 0.95
ALPHA = 0.05
MIN_N = 30


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def slug(s) -> str:
    return norm(s).replace(" ", "_")[:40] or "col"



def to_dates(s: pd.Series) -> pd.Series:
    """Parse survey timestamps safely: ISO (2026-10-12[ 10:00]) is never read day-first; dd/mm vs mm/dd is
    decided from the data (a first field > 12 means day-first); defaults to day-first (pt-BR exports)."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    t = s.astype("string").str.strip().str.slice(0, 19)
    iso = t.str.match(r"^\d{4}-\d{2}-\d{2}").fillna(False)
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    if iso.any():
        out[iso] = pd.to_datetime(t[iso], errors="coerce", format="mixed")
    rest = ~iso & t.notna()
    if rest.any():
        parts = t[rest].str.extract(r"^(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}").astype("float")
        a, b = parts[0], parts[1]
        dayfirst = not ((b > 12).any() and not (a > 12).any())
        out[rest] = pd.to_datetime(t[rest], errors="coerce", dayfirst=dayfirst, format="mixed")
    return out

def load(path, **kw):
    """load any table via profile.load_any (CSV encodings/delimiters, XLSX, Parquet, JSON, SQLite)."""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("report_profile", Path(__file__).with_name("profile.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.load_any(path, **kw)


# --------------------------------------------------------------------------- #
# statistics (the template mirrors these exactly)                              #
# --------------------------------------------------------------------------- #
def norm_inv(p: float) -> float:
    """inverse standard normal CDF (Acklam, |rel err| < 1.2e-9)"""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > 1 - pl:
        return -norm_inv(1 - p)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def z_crit(level=LEVEL) -> float:
    return norm_inv(1 - (1 - level) / 2)


def t_crit(df: float, level=LEVEL) -> float:
    """two-sided t critical value (Cornish–Fisher expansion; < 0.5% error for df ≥ 3)"""
    z = z_crit(level)
    if df <= 0:
        return float("nan")
    if df > 1e6:
        return z
    g1 = (z ** 3 + z) / 4
    g2 = (5 * z ** 5 + 16 * z ** 3 + 3 * z) / 96
    g3 = (3 * z ** 7 + 19 * z ** 5 + 17 * z ** 3 - 15 * z) / 384
    g4 = (79 * z ** 9 + 776 * z ** 7 + 1482 * z ** 5 - 1920 * z ** 3 - 945 * z) / 92160
    return z + g1 / df + g2 / df ** 2 + g3 / df ** 3 + g4 / df ** 4


@dataclass
class Stat:
    v: float | None
    n: float
    lo: float | None = None
    hi: float | None = None
    se: float | None = None
    small: bool = False
    kind: str = ""

    def as_dict(self):
        return {k: getattr(self, k) for k in ("v", "lo", "hi", "n", "se", "small")}


def wilson(k: float, n: float, level=LEVEL, min_n=MIN_N) -> Stat:
    if not n:
        return Stat(None, 0, kind="wilson", small=True)
    z, p = z_crit(level), k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return Stat(p, n, c - h, c + h, math.sqrt(p * (1 - p) / n), n < min_n, "wilson")


def nps_stat(pro: float, det: float, n: float, level=LEVEL, min_n=MIN_N) -> Stat:
    if not n:
        return Stat(None, 0, kind="nps", small=True)
    P, D = pro / n, det / n
    v = P - D
    se = math.sqrt(max(0.0, P + D - v * v) / n)
    z = z_crit(level)
    return Stat(v, n, max(-1.0, v - z * se), min(1.0, v + z * se), se, n < min_n, "nps")


def mean_stat(s: float, ss: float, n: float, level=LEVEL, min_n=MIN_N) -> Stat:
    if not n:
        return Stat(None, 0, kind="mean", small=True)
    m = s / n
    var = (ss - s * s / n) / (n - 1) if n > 1 else 0.0
    se = math.sqrt(max(0.0, var) / n)
    t = t_crit(n - 1, level) if n > 1 else float("nan")
    return Stat(m, n, m - t * se if n > 1 else None, m + t * se if n > 1 else None, se, n < min_n, "mean")


def nps_bootstrap(scores, B=2000, level=LEVEL, seed=7):
    """percentile bootstrap CI for NPS (cross-check for the variance-based interval)"""
    x = np.asarray(pd.Series(scores).dropna(), dtype=float)
    rng = np.random.default_rng(seed)
    vals = ((x >= 9).astype(float) - (x <= 6).astype(float))
    boots = vals[rng.integers(0, len(x), (B, len(x)))].mean(axis=1)
    a = (1 - level) / 2
    return float(np.quantile(boots, a)), float(np.quantile(boots, 1 - a))


def measure_stat(df: pd.DataFrame, m: dict, level=LEVEL, min_n=MIN_N) -> Stat:
    """same result as the template's stat(rows, measure)"""
    S = lambda c: float(pd.to_numeric(df[c], errors="coerce").fillna(0).sum())  # noqa: E731
    if m.get("agg") == "nps":
        return nps_stat(S(m["pos"]), S(m["neg"]), S(m["den"]), level, min_n)
    if m.get("ci") == "mean":
        return mean_stat(S(m["num"]), S(m["sumsq"]), S(m["den"]), level, min_n)
    if m.get("ci") == "wilson":
        return wilson(S(m["num"]), S(m["den"]), level, min_n)
    if m.get("agg") == "ratio":
        d = S(m["den"])
        return Stat(S(m["num"]) / d if d else None, d)
    return Stat(S(m.get("field", m["key"])), len(df))


def diff_test(a: Stat, b: Stat, alpha=ALPHA) -> dict | None:
    if a.v is None or b.v is None or not (a.se or b.se):
        return None
    d = a.v - b.v
    se = math.sqrt((a.se or 0) ** 2 + (b.se or 0) ** 2)
    if not se:
        return None
    z = d / se
    p = 2 * (1 - norm_cdf(abs(z)))
    return {"d": d, "z": z, "p": p, "padj": p, "sig": p < alpha}


def holm(tests: list, alpha=ALPHA) -> list:
    idx = sorted([(t["p"], i) for i, t in enumerate(tests) if t], key=lambda x: x[0])
    m, run = len(idx), 0.0
    for j, (p, i) in enumerate(idx):
        run = max(run, min(1.0, (m - j) * p))
        tests[i]["padj"] = run
        tests[i]["sig"] = run < alpha
    return tests


# --------------------------------------------------------------------------- #
# wording (pt-BR) — never claim a difference the test does not support          #
# --------------------------------------------------------------------------- #
def _br(x: float, nd=1) -> str:
    t = f"{x:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return "−" + t[1:] if t.startswith("-") and t.strip("-0,") else t.lstrip("-")


def fmt_value(v, m: dict) -> str:
    if v is None:
        return "—"
    f = m.get("format")
    if f == "percent":
        return _br(v * 100) + "%"
    if f == "nps":
        return _br(v * 100, 0)
    if f == "decimal":
        return _br(v, 2)
    return _br(v, 0)


def fmt_diff(d: float, m: dict) -> str:
    sign = "+" if d > 0 else "−" if d < 0 else "±"
    f = m.get("format")
    if f == "percent":
        return f"{sign}{_br(abs(d) * 100)} p.p."
    if f == "nps":
        return f"{sign}{_br(abs(d) * 100)} pts"
    return f"{sign}{_br(abs(d), 2)}"


def fmt_ci(s: Stat, m: dict, level=LEVEL) -> str:
    if s.lo is None:
        return ""
    lo, hi = fmt_value(s.lo, m), fmt_value(s.hi, m)
    sep = (" a ", "de ") if "−" in lo + hi else ("–", "")
    return f"IC {round(level * 100)}%: {sep[1]}{lo}{sep[0]}{hi}"


def fmt_p(p: float) -> str:
    return "p < 0,001" if p < 0.001 else f"p = {_br(p, 3)}"


def say_change(cur: Stat, prev: Stat, m: dict, what="vs. o período anterior", alpha=ALPHA) -> str:
    """'sobe +3,2 p.p. vs. … (significativo, p = 0,004)' or 'fica estável … (+0,6 p.p., dentro da margem de erro)'"""
    t = diff_test(cur, prev, alpha)
    if t is None:
        return f"sem base de comparação {what}"
    good_up = m.get("good", "up") == "up"
    if not t["sig"]:
        return f"fica estável {what} ({fmt_diff(t['d'], m)}, dentro da margem de erro; {fmt_p(t['p'])})"
    verb = "sobe" if t["d"] > 0 else "cai"
    tone = "melhora" if (t["d"] > 0) == good_up else "piora"
    return f"{verb} {fmt_diff(abs(t['d']), m).lstrip('+')} {what} — {tone} significativa ({fmt_p(t['p'])})"


# --------------------------------------------------------------------------- #
# detection                                                                    #
# --------------------------------------------------------------------------- #
NAME_RULES = {
    "nps": r"\bnps\b|recomend|indicaria|indicar a|likel|promot|net promoter",
    "csat": r"\bcsat\b|satisf",
    "ces": r"\bces\b|esforc|effort|facil|facilidade|dificil|dificuldade|\beasy\b",
}
GENERIC = r"\bnota\b|\bscore\b|avalia|rating|\bnps\b|\bpontua"
TEXT_LABELS = {
    # longest first; values on the canonical scale of each family
    "csat": [("muito insatisfeito", 1), ("totalmente insatisfeito", 1), ("nem satisfeito nem insatisfeito", 3), ("insatisfeito", 2),
             ("indiferente", 3), ("neutro", 3), ("muito satisfeito", 5), ("totalmente satisfeito", 5), ("satisfeito", 4),
             ("pessimo", 1), ("ruim", 2), ("regular", 3), ("bom", 4), ("otimo", 5), ("excelente", 5)],
    "ces": [("muito dificil", 1), ("nem facil nem dificil", 3), ("dificil", 2), ("neutro", 3), ("muito facil", 5), ("facil", 4),
            ("discordo totalmente", 1), ("discordo parcialmente", 3), ("discordo", 2), ("nem concordo nem discordo", 4),
            ("concordo parcialmente", 5), ("concordo totalmente", 7), ("concordo", 6)],
}
DATE_RULE = r"\bdata\b|\bdate\b|carimbo|hora|timestamp|respond|criad|created|enviad em|submitted|dt "
COMMENT_RULE = r"coment|feedback|texto|observ|sugest|motivo|por que|porque|justific|opini|elogio|reclama|\bobs\b|verbat|contar|conte |descrev|explique|deixe"
INVITE_RULE = r"convite|convidad|enviad|disparad|disparo|invit|\bsent\b|pesquisas enviadas|amostra enviada"
PII_RULE = r"e ?mail|telefone|celular|whats|\bcpf\b|\bcnpj\b|\bnome\b|\bname\b|endereco|\brg\b"
ID_RULE = r"\bid\b|protocolo|ticket|chamado|pedido|\bcodigo\b|\bcod\b|numero"


def to_score(s: pd.Series, family: str | None = None) -> pd.Series:
    """numbers, numeric text ('5', '5 - Muito satisfeito', '(9)', '10 – extremamente provável') or pt-BR labels -> float"""
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").astype(float)
    labels = TEXT_LABELS.get(family or "", []) or (TEXT_LABELS["csat"] + TEXT_LABELS["ces"])

    def one(x):
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return np.nan
        t = str(x).strip()
        if not t:
            return np.nan
        m = re.match(r"^\(?\s*(\d{1,2})(?:[.,]0+)?\s*\)?(?:\s*[-–—:=.)]\s*.*|\s+.*)?$", t)
        if m:
            return float(m.group(1))
        m = re.search(r"\((\d{1,2})\)\s*$", t)
        if m:
            return float(m.group(1))
        nt = norm(t)
        for lab, v in labels:
            if nt == lab or nt.startswith(lab + " "):
                return float(v)
        return np.nan
    return s.map(one).astype(float)


def _scale_of(x: pd.Series, family: str | None) -> tuple[list[int] | None, str]:
    v = x.dropna()
    if not len(v):
        return None, "sem valores"
    if (v.round() != v).mean() > 0.02:
        return None, "valores não inteiros"
    lo, hi = int(v.min()), int(v.max())
    if lo < 0 or hi > 10:
        return None, f"faixa {lo}–{hi} fora de escalas de pesquisa"
    if family == "nps" or (hi > 7 and lo == 0):
        return [0, 10], f"valores {lo}–{hi}"
    if hi > 7:
        return [1, 10], f"valores {lo}–{hi} (escala 1–10: NPS exige 0–10)"
    if hi > 5:
        return [1, 7], f"valores {lo}–{hi}"
    if hi >= 3 and lo >= 0:
        return [lo if lo == 0 else 1, 5], f"valores {lo}–{hi}"
    return None, f"valores {lo}–{hi} (poucas categorias)"


def _ces_direction(name: str) -> str:
    n = norm(name)
    m = re.search(r"\b1\s*(?:=|e|eh|é)?\s*(muito\s+)?(facil|dificil|baixo esforco|alto esforco|pouco esforco|muito esforco)", n)
    if m:
        w = m.group(2)
        return "lower_easier" if ("facil" in w or "baixo" in w or "pouco" in w) else "higher_easier"
    if re.search(r"esforc|effort", n) and not re.search(r"facil|easy", n):
        return "lower_easier"
    return "higher_easier"


def _is_texty(s: pd.Series) -> bool:
    return s.dtype == object or pd.api.types.is_string_dtype(s) or str(s.dtype) == "category"


def detect(df: pd.DataFrame, min_n=MIN_N) -> dict:
    """Guess CSAT / CES / NPS score columns (name + value scale), the date, the comment, the invitations
    count, segment candidates, IDs and PII columns. Returns a mapping the user confirms in the briefing."""
    cands = []
    nonnull = {c: int(df[c].notna().sum()) for c in df.columns}
    for col in df.columns:
        n = norm(col)
        fam_name = next((f for f, rx in NAME_RULES.items() if re.search(rx, n)), None)
        generic = bool(re.search(GENERIC, n))
        if not fam_name and not generic and not pd.api.types.is_numeric_dtype(df[col]):
            # still try: text Likert answers in an unnamed column
            pass
        if re.search(ID_RULE + "|" + PII_RULE, n) and not fam_name:
            continue
        sc = to_score(df[col], fam_name)
        parsed = sc.notna().sum() / max(1, nonnull[col])
        if nonnull[col] < 5 or parsed < 0.85:
            continue
        scale, why = _scale_of(sc, fam_name)
        if not scale:
            continue
        fam = fam_name
        if not fam:
            fam = "nps" if scale == [0, 10] else "csat" if scale == [1, 5] else "ces" if scale == [1, 7] else None
            if not fam or not (generic or pd.api.types.is_numeric_dtype(df[col]) or parsed > 0.95):
                continue
        conf = "alta" if fam_name and ((fam == "nps") == (scale[1] == 10)) else "média" if fam_name or generic else "baixa"
        if fam == "nps" and scale != [0, 10]:
            conf = "baixa"
        reason = (f"nome sugere {fam.upper()}" if fam_name else "nome genérico de nota" if generic else "só pela escala") + f"; {why}; {parsed:.0%} das respostas legíveis"
        cands.append({"metric": fam, "column": col, "scale": scale, "confidence": conf, "reason": reason,
                      "answered": int(sc.notna().sum()), "score": (3 if fam_name else 1 if generic else 0) + parsed})
    out: dict = {"candidates": cands}
    for fam in ("csat", "ces", "nps"):
        best = sorted([c for c in cands if c["metric"] == fam], key=lambda c: -c["score"])
        if not best:
            continue
        b = dict(best[0])
        if fam == "csat":
            b["threshold"] = b["scale"][1] - 1               # top-2 box
        if fam == "ces":
            b["direction"] = _ces_direction(b["column"])
            hi = b["scale"][1]
            b["easy"] = (hi - 2 if hi == 7 else hi - 1) if b["direction"] == "higher_easier" else (3 if hi == 7 else 2)
        out[fam] = b
    used = {out[f]["column"] for f in ("csat", "ces", "nps") if f in out}

    def first(rule, pred):
        for col in df.columns:
            if col in used:
                continue
            if re.search(rule, norm(col)) and pred(df[col]):
                return col
        return None

    def is_date(s):
        if pd.api.types.is_datetime64_any_dtype(s):
            return True
        d = to_dates(s)
        return d.notna().mean() > 0.9

    def is_text(s):
        t = s.dropna().astype(str)
        return len(t) > 0 and t.str.len().mean() >= 12 and t.nunique() / len(t) > 0.4

    out["date"] = first(DATE_RULE, is_date) or next((c for c in df.columns if c not in used and pd.api.types.is_datetime64_any_dtype(df[c])), None)
    out["comment"] = first(COMMENT_RULE, is_text) or next((c for c in df.columns if c not in used and _is_texty(df[c]) and is_text(df[c]) and df[c].dropna().astype(str).str.len().mean() > 30), None)
    out["invitations"] = first(INVITE_RULE, lambda s: pd.api.types.is_numeric_dtype(s))
    out["pii"] = [c for c in df.columns if re.search(PII_RULE, norm(c)) and c not in used]
    out["ids"] = [c for c in df.columns if c not in used and re.search(ID_RULE, norm(c)) and df[c].nunique() > 0.5 * len(df)]
    skip = used | {out["date"], out["comment"], out["invitations"]} | set(out["pii"]) | set(out["ids"])
    segs = []
    for c in df.columns:
        if c in skip:
            continue
        s = df[c]
        k = s.nunique(dropna=True)
        if 2 <= k <= 60 and (_is_texty(s) or (pd.api.types.is_integer_dtype(s) and k <= 12)):
            if _is_texty(s) and s.dropna().astype(str).str.len().mean() > 40:
                continue
            vc = s.value_counts()
            segs.append({"column": c, "levels": int(k), "small_groups": int((vc < min_n).sum()), "nulls": float(s.isna().mean())})
    out["segments"] = segs
    out["rows"] = int(len(df))
    return out


def briefing(m: dict, min_n=MIN_N) -> str:
    """pt-BR lines for the briefing card: what was detected and the defaults that will be used"""
    L = ["**Mapeamento das colunas da pesquisa** (confirme ou corrija):"]
    names = {"csat": "CSAT", "ces": "CES", "nps": "NPS"}
    for f in ("csat", "ces", "nps"):
        if f not in m:
            L.append(f"- {names[f]}: não encontrado")
            continue
        b = m[f]
        extra = ""
        if f == "csat":
            extra = f" · satisfeito = nota ≥ {b['threshold']} (top-2 box)"
        if f == "ces":
            d = "maior = mais fácil" if b["direction"] == "higher_easier" else "menor = mais fácil (escala de esforço)"
            extra = f" · {d} · \"fácil\" = nota {'≥' if b['direction'] == 'higher_easier' else '≤'} {b['easy']}"
        if f == "nps":
            extra = " · promotores 9–10, detratores 0–6"
        L.append(f"- {names[f]}: **{b['column']}** — escala {b['scale'][0]}–{b['scale'][1]}{extra} (confiança {b['confidence']}: {b['reason']})")
    alt = [c for c in m.get("candidates", []) if all(c["column"] != m.get(f, {}).get("column") for f in ("csat", "ces", "nps"))]
    if alt:
        L.append("- Outras colunas com cara de nota: " + "; ".join(f"{c['column']} ({c['metric'].upper()}?, {c['scale'][0]}–{c['scale'][1]})" for c in alt[:4]))
    L.append(f"- Data da resposta: **{m.get('date') or 'não encontrada'}** · Comentário aberto: **{m.get('comment') or 'nenhum'}** · Convites/enviadas: **{m.get('invitations') or 'não há (taxa de resposta só com a base de disparos)'}**")
    if m.get("segments"):
        L.append("- Recortes possíveis: " + ", ".join(f"{s['column']} ({s['levels']})" for s in m["segments"][:10]))
    if m.get("pii") or m.get("ids"):
        L.append(f"- Colunas que **não** vão para o HTML (dados pessoais / identificadores): {', '.join(m.get('pii', []) + m.get('ids', []))}")
    L.append(f"- Regras: IC de 95%; grupos com n < {min_n} aparecem marcados como **amostra pequena** (nunca escondidos); diferenças só são chamadas de queda/alta quando o teste é significativo.")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# prepare: indicator columns + measures                                        #
# --------------------------------------------------------------------------- #
BANDS = {
    "nps": ["Detratores", "Neutros", "Promotores"],
    "csat": ["Insatisfeitos", "Neutros", "Satisfeitos"],
    "ces": ["Difícil", "Neutro", "Fácil"],
}


@dataclass
class Prepared:
    fact: pd.DataFrame
    measures: list
    dims: list
    nums: list
    metrics: dict
    comments: pd.Series | None = None
    date: str = "data"
    stats: dict = field(default_factory=dict)
    log: list = field(default_factory=list)          # cleaning actions, for the methodology

    def measure(self, key):
        return next(m for m in self.measures if m["key"] == key)


def merge_variants(s: pd.Series) -> tuple[pd.Series, dict]:
    """'CHAT', 'chat ', 'Chat' -> the most frequent spelling. Returns (series, {variant: canonical})."""
    vc = s.dropna().astype(str).str.strip().value_counts()
    canon, mapping = {}, {}
    for v in vc.index:                       # most frequent first
        key = norm(v)
        if key in canon:
            if v != canon[key]:
                mapping[v] = canon[key]
        else:
            canon[key] = v
    return s.map(lambda x: mapping.get(str(x).strip(), str(x).strip()) if x is not None else None), mapping


def prepare(df: pd.DataFrame, mapping: dict, *, segments: dict | list | None = None, date: str | None = None,
            min_n=MIN_N, level=LEVEL, missing_label="Não informado", merge_case_variants=True) -> Prepared:
    """Build the fact table (one row per response) with indicator columns and the measure definitions.
    segments: {"Source column": "key"} or ["Source column", ...] — the dims for filters and charts."""
    date = date or mapping.get("date")
    out = pd.DataFrame(index=df.index)
    if date:
        d = df[date]
        if not pd.api.types.is_datetime64_any_dtype(d):
            d = to_dates(d)
        out["data"] = d.dt.normalize()
    if isinstance(segments, list):
        segments = {c: slug(c) for c in segments}
    segments = segments or {s["column"]: slug(s["column"]) for s in mapping.get("segments", [])[:6]}
    dims, log = [], []
    if date:
        bad = int(out["data"].isna().sum())
        if bad:
            log.append(f"{bad} respostas sem data legível em '{date}' ficam fora dos filtros de período")
    for col, key in segments.items():
        s = df[col].astype("object").where(df[col].notna(), None)
        s = s.map(lambda v: missing_label if v is None or str(v).strip() == "" else re.sub(r"\s+", " ", str(v)).strip())
        if merge_case_variants:
            s, mp = merge_variants(s)
            if mp:
                log.append(f"'{str(col).strip()}': variantes de grafia unificadas ({', '.join(f'{a} → {b}' for a, b in list(mp.items())[:6])}{'…' if len(mp) > 6 else ''})")
        out[key] = s
        dims.append({"key": key, "label": re.sub(r"\s+", " ", str(col)).strip()})
    out["respostas"] = 1
    measures = [{"key": "respostas", "label": "Respostas", "agg": "sum", "field": "respostas", "format": "number",
                 "description": "Número de respostas recebidas (uma linha por resposta)."}]
    nums = ["respostas"]
    metrics = {}
    for fam in ("csat", "ces", "nps"):
        b = mapping.get(fam)
        if not b:
            continue
        sc = to_score(df[b["column"]], fam)
        lo, hi = b["scale"]
        raw_n = int(df[b["column"]].notna().sum())
        out_of = int(((sc < lo) | (sc > hi)).sum())
        sc = sc.where((sc >= lo) & (sc <= hi))
        unread = raw_n - int(sc.notna().sum()) - out_of
        if out_of or unread:
            log.append(f"{fam.upper()}: {out_of} notas fora da escala {lo}–{hi} e {unread} respostas ilegíveis tratadas como não respondidas")
        ans = sc.notna()
        out[f"{fam}_nota"] = sc
        out[f"{fam}_n"] = ans.astype(int)
        nums += [f"{fam}_nota", f"{fam}_n"]
        metrics[fam] = dict(b, answered=int(ans.sum()))
        if fam == "csat":
            thr = b.get("threshold", hi - 1)
            out["csat_top"] = (sc >= thr).astype(int)
            nums.append("csat_top")
            neutral_hi = thr - 1
            out["faixa_csat"] = np.where(~ans, None, np.where(sc >= thr, BANDS["csat"][2], np.where(sc >= neutral_hi, BANDS["csat"][1], BANDS["csat"][0])))
            measures.append({"key": "csat", "label": "CSAT", "agg": "ratio", "num": "csat_top", "den": "csat_n", "ci": "wilson",
                             "format": "percent", "good": "up", "field_score": "csat_nota", "scale": [lo, hi],
                             "description": f"% de respostas com nota ≥ {thr} numa escala {lo}–{hi} (top-{hi - thr + 1} box) = Σ satisfeitos ÷ Σ respondentes da pergunta. IC de Wilson."})
        elif fam == "ces":
            direction = b.get("direction", "higher_easier")
            easy = b.get("easy", (hi - 2 if hi == 7 else hi - 1) if direction == "higher_easier" else (3 if hi == 7 else 2))
            is_easy = (sc >= easy) if direction == "higher_easier" else (sc <= easy)
            mid = (lo + hi) / 2
            is_hard = (sc < mid) if direction == "higher_easier" else (sc > mid)
            out["ces_sum"] = sc.fillna(0)
            out["ces_sq"] = (sc ** 2).fillna(0)
            out["ces_facil"] = is_easy.astype(int)
            nums += ["ces_sum", "ces_sq", "ces_facil"]
            out["faixa_ces"] = np.where(~ans, None, np.where(is_easy, BANDS["ces"][2], np.where(is_hard, BANDS["ces"][0], BANDS["ces"][1])))
            good = "up" if direction == "higher_easier" else "down"
            measures.append({"key": "ces", "label": "CES (média)", "agg": "ratio", "num": "ces_sum", "den": "ces_n", "sumsq": "ces_sq",
                             "ci": "mean", "format": "decimal", "change": "abs", "good": good, "field_score": "ces_nota", "scale": [lo, hi],
                             "description": f"Média da nota de esforço ({lo}–{hi}; {'maior = mais fácil' if good == 'up' else 'menor = mais fácil'}) = Σ notas ÷ Σ respondentes. Intervalo t."})
            measures.append({"key": "ces_facil", "label": "% fácil (CES)", "agg": "ratio", "num": "ces_facil", "den": "ces_n", "ci": "wilson",
                             "format": "percent", "good": "up",
                             "description": f"% de respostas \"fácil\" (nota {'≥' if direction == 'higher_easier' else '≤'} {easy}). IC de Wilson."})
            metrics[fam].update(direction=direction, easy=easy)
        elif fam == "nps":
            out["nps_pro"] = (sc >= 9).astype(int)
            out["nps_det"] = (sc <= 6).astype(int)
            out["nps_neu"] = ((sc >= 7) & (sc <= 8)).astype(int)
            nums += ["nps_pro", "nps_det", "nps_neu"]
            out["faixa_nps"] = np.where(~ans, None, np.where(sc >= 9, BANDS["nps"][2], np.where(sc >= 7, BANDS["nps"][1], BANDS["nps"][0])))
            measures.append({"key": "nps", "label": "NPS", "agg": "nps", "pos": "nps_pro", "neg": "nps_det", "den": "nps_n", "ci": "nps",
                             "format": "nps", "good": "up", "field_score": "nps_nota", "scale": [0, 10],
                             "description": "% promotores (9–10) − % detratores (0–6), em pontos (−100 a +100) = (Σ promotores − Σ detratores) ÷ Σ respondentes. IC pela variância: √((P + D − (P − D)²)/n)."})
            measures.append({"key": "promotores", "label": "% promotores", "agg": "ratio", "num": "nps_pro", "den": "nps_n", "ci": "wilson", "format": "percent", "good": "up",
                             "description": "Notas 9–10 ÷ respondentes do NPS."})
            measures.append({"key": "detratores", "label": "% detratores", "agg": "ratio", "num": "nps_det", "den": "nps_n", "ci": "wilson", "format": "percent", "good": "down",
                             "description": "Notas 0–6 ÷ respondentes do NPS."})
    for fam in ("csat", "ces", "nps"):
        if f"faixa_{fam}" in out:
            dims.append({"key": f"faixa_{fam}", "label": {"nps": "Perfil NPS", "csat": "Faixa CSAT", "ces": "Faixa de esforço"}[fam], "order": BANDS[fam]})
    comments = None
    if mapping.get("comment"):
        raw = df[mapping["comment"]].astype("object")
        comments = raw.where(raw.notna() & (raw.astype(str).str.strip().str.len() > 0), None)
        out["comentarios"] = comments.notna().astype(int)
        nums.append("comentarios")
        measures.append({"key": "comentarios", "label": "Comentários", "agg": "sum", "field": "comentarios", "format": "number",
                         "description": "Respostas com comentário aberto preenchido."})
    return Prepared(fact=out, measures=measures, dims=dims, nums=nums, metrics=metrics, comments=comments,
                    stats={"minN": min_n, "level": level, "alpha": ALPHA, "adjust": "holm"}, log=log)


def add_invitations(prep: Prepared, inv: pd.DataFrame, *, date: str, count: str, keys: dict | None = None) -> Prepared:
    """Append invitation rows (aggregated by date and the shared keys) so that the response rate is a
    ratio of sums: Σrespostas ÷ Σconvites. Rows get respostas = 0 and empty scores. Filters on dims that
    the invitations table does not have make the rate undefined (shown as "—"), never wrong."""
    keys = keys or {}
    d = inv[date]
    if not pd.api.types.is_datetime64_any_dtype(d):
        d = to_dates(d)
    add = pd.DataFrame({"data": d.dt.normalize(), "convites": pd.to_numeric(inv[count], errors="coerce").fillna(0)})
    for src, key in keys.items():
        add[key] = inv[src].astype(str).str.strip()
    add = add.groupby(["data", *keys.values()], as_index=False)["convites"].sum()
    fact = prep.fact.copy()
    fact["convites"] = 0
    for c in fact.columns:
        if c not in add.columns:
            add[c] = 0 if c in prep.nums else None
    for c in [c for c in prep.nums if c.endswith("_nota")]:
        add[c] = np.nan
    prep.fact = pd.concat([fact, add[fact.columns]], ignore_index=True)
    if "convites" not in prep.nums:
        prep.nums.append("convites")
        prep.measures.append({"key": "convites", "label": "Convites enviados", "agg": "sum", "field": "convites", "format": "number",
                              "description": "Pesquisas enviadas (base de disparos)."})
        prep.measures.append({"key": "taxa_resposta", "label": "Taxa de resposta", "agg": "ratio", "num": "respostas", "den": "convites", "ci": "wilson",
                              "format": "percent", "good": "up",
                              "description": f"Σ respostas ÷ Σ convites. Só definida nos recortes que a base de disparos tem ({', '.join(['data', *keys.values()])})."})
    return prep


# --------------------------------------------------------------------------- #
# segment analysis (mirrors the ci / drivers charts)                           #
# --------------------------------------------------------------------------- #
def segment_table(fact: pd.DataFrame, m: dict, dim: str, level=LEVEL, min_n=MIN_N, alpha=ALPHA) -> pd.DataFrame:
    overall = measure_stat(fact, m, level, min_n)
    rows, tests = [], []
    for g, part in fact.groupby(dim, dropna=True):
        s = measure_stat(part, m, level, min_n)
        if not s.n:
            continue
        rest = measure_stat(fact[fact[dim] != g], m, level, min_n)
        t = diff_test(s, rest, alpha)
        tests.append(t)
        rows.append({"grupo": g, "v": s.v, "lo": s.lo, "hi": s.hi, "n": s.n, "small": s.small, "rest": rest.v,
                     "share": s.n / overall.n if overall.n else 0})
    holm(tests, alpha)
    for r, t in zip(rows, tests):
        r.update(p=t["p"] if t else None, padj=t["padj"] if t else None, sig=bool(t and t["sig"]),
                 impact=r["share"] * (r["v"] - r["rest"]) if r["rest"] is not None and r["v"] is not None else None)
    return pd.DataFrame(rows).sort_values("v", ascending=False).reset_index(drop=True)


def drivers(fact: pd.DataFrame, m: dict, dims: list, level=LEVEL, min_n=MIN_N, alpha=ALPHA) -> pd.DataFrame:
    """impact_g = share_g × (metric_g − metric_rest): how much group g moves the overall metric
    (if g scored like everyone else, the overall would change by −impact_g). Holm across all groups."""
    parts = []
    for dmn in dims:
        t = segment_table(fact, m, dmn, level, min_n, alpha).assign(dim=dmn)
        parts.append(t)
    out = pd.concat(parts, ignore_index=True)
    # one Holm family across every tested group
    tests = [{"p": p} if p is not None and not pd.isna(p) else None for p in out["p"]]
    holm(tests, alpha)
    out["padj"] = [t["padj"] if t else None for t in tests]
    out["sig"] = [bool(t and t["sig"]) for t in tests]
    return out.sort_values("impact").reset_index(drop=True)


def expected_values(fact: pd.DataFrame, measures: list, level=LEVEL, min_n=MIN_N) -> dict:
    """values over ALL rows, embedded as spec["checks"] so verify.py proves the browser computes the same"""
    out = {}
    for m in measures:
        if m.get("ci"):
            s = measure_stat(fact, m, level, min_n)
            out[m["key"]] = {"v": s.v, "lo": s.lo, "hi": s.hi, "n": s.n}
    return out


# --------------------------------------------------------------------------- #
# open-text comments: PII scrubbing + offline themes                           #
# --------------------------------------------------------------------------- #
STOP = set("""a o e é de do da dos das em no na nos nas um uma uns umas para pra pro por pelo pela pelos pelas com sem
que se ao aos à às ou mas mais menos muito muita muitos muitas pouco pouca bem já não nao sim só so também tambem
foi ser sou era está esta estão estao estava estou tem têm ter tive teve tinha há ha vai vou fazer feito fez faz
me meu minha meus minhas eu ele ela eles elas você voce vocês voces nós nos lhe isso isto esse essa este aquele aquela
qual quando onde como porque pois então entao ainda depois antes até ate sobre entre todo toda todos todas tudo nada
algum alguma outro outra outros outras mesmo mesma seu sua seus suas dele dela deles cada vez vezes aqui ali lá la
q pq vc vcs tb tbm ok sei acho achei gostaria quero queria poderia deveria precisa preciso ficou fica fiquei estar
the and to of is it in for on was with dia dias hoje ontem agora sempre nunca empresa pesquisa nota
fui foram vez vezes novo nova nenhum nenhuma varias vários varios espero melhorem recomendo obrigado obrigada dica olha
sinceramente gostei quase coisa coisas gente pessoal favor bom boa ótimo otimo ruim parabéns parabens""".split())
CUES = r"(?:atendente|atendida|atendido|tecnico|técnico|técnica|tecnica|consultor|consultora|moça|moca|moço|moco|rapaz|sr\.?|sra\.?|senhor|senhora|falei com|chamo|me chamo|nome é|nome e|pelo|pela)"
WEAK_CUES = r"(?:[Cc]om o|[Cc]om a|\b[OoAa])"
NAME_TOKEN = r"[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõçü]{2,}"
KEEP_DEFAULT = set("""Brasil São Paulo Rio Janeiro Minas Gerais Bahia Paraná Pernambuco Ceará Pará Goiás Amazonas Maranhão Santa Catarina
Espírito Santo Paraíba Piauí Alagoas Sergipe Tocantins Rondônia Acre Amapá Roraima Mato Grosso Sul Norte Nordeste Sudeste Centro Oeste
Distrito Federal Brasília Salvador Fortaleza Recife Manaus Belém Curitiba Porto Alegre Goiânia Florianópolis Natal Vitória Campinas
Janeiro Fevereiro Março Abril Maio Junho Julho Agosto Setembro Outubro Novembro Dezembro Segunda Terça Quarta Quinta Sexta Sábado Domingo
WhatsApp Whatsapp Pix Google Android iPhone Netflix Wi-Fi Wifi App Black Friday Natal Procon""".split())


def scrub_pii(text: str, keep: set | None = None, lower_vocab: set | None = None) -> str:
    """mask e-mails, URLs, phones, CPF/CNPJ, long numbers (protocols, cards), and name-looking tokens"""
    if text is None:
        return text
    t = str(text)
    t = re.sub(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", "[e-mail]", t)
    t = re.sub(r"(?:https?://|www\.)\S+", "[link]", t)
    t = re.sub(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b", "[documento]", t)
    t = re.sub(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "[documento]", t)
    t = re.sub(r"(?:\+?55\s?)?\(?\b\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b", "[telefone]", t)
    t = re.sub(r"\b\d{6,}\b", "[número]", t)
    keep = KEEP_DEFAULT | set(keep or ())
    # names after cue words: "fui atendido pelo Carlos Souza", "a atendente Juliana"
    t = re.sub(rf"(\b{CUES}\s+)({NAME_TOKEN}(?:\s+{NAME_TOKEN})?)",
               lambda m: m.group(1) + ("[nome]" if m.group(2).split()[0] not in keep else m.group(2)), t)
    lv = lower_vocab or set()
    t = re.sub(rf"({WEAK_CUES}\s+)({NAME_TOKEN}(?:\s+{NAME_TOKEN})?)",
               lambda m: m.group(1) + ("[nome]" if m.group(2).split()[0] not in keep and m.group(2).split()[0].lower() not in lv else m.group(2)), t)
    # capitalised token mid-sentence that never appears in lower case anywhere in the corpus
    if lower_vocab is not None:
        def mid(m):
            w = m.group(2)
            if w in keep or w.lower() in lower_vocab or w.isupper():
                return m.group(0)
            return m.group(1) + "[nome]"
        t = re.sub(rf"([^.!?\s]\s+)({NAME_TOKEN})", mid, t)
    t = re.sub(r"\[nome\](?:\s+\[nome\])+", "[nome]", t)
    return t


def _stem(w: str) -> str:
    for a, b in (("ções", "cao"), ("coes", "cao"), ("ões", "ao"), ("ais", "al"), ("eis", "el"), ("ns", "m")):
        if w.endswith(a) and len(w) > len(a) + 2:
            return w[: -len(a)] + b
    if w.endswith("s") and not w.endswith("ss") and len(w) > 4:
        return w[:-1]
    return w


def _tokens(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", str(text).lower()).encode("ascii", "ignore").decode()
    stop = {norm(s) for s in STOP}
    return [w for w in re.findall(r"[a-z]{3,}", t) if w not in stop]


@dataclass
class Themes:
    labels: pd.Series                   # theme label per row (None where no comment)
    summary: list                       # [{tema, n, share, terms, verbatims:[{text, band}]}]
    method: str = "tfidf-kmeans"
    k: int = 0
    silhouette: float | None = None

    def verbatims(self) -> dict:
        return {s["tema"]: s["verbatims"] for s in self.summary}

    def terms(self) -> dict:
        return {s["tema"]: s["terms"] for s in self.summary}


def _kmeans(X: np.ndarray, k: int, seed: int, iters=40) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = X.shape[0]
    C = [X[rng.integers(n)]]
    d = 1 - X @ C[0]
    for _ in range(1, k):                                   # k-means++ on cosine distance
        p = np.clip(d, 0, None) ** 2
        p = p / p.sum() if p.sum() else np.full(n, 1 / n)
        C.append(X[rng.choice(n, p=p)])
        d = np.minimum(d, 1 - X @ C[-1])
    C = np.array(C)
    lab = np.zeros(n, dtype=int)
    for _ in range(iters):
        new = np.argmax(X @ C.T, axis=1)
        if _ and (new == lab).all():
            break
        lab = new
        for j in range(k):
            pts = X[lab == j]
            if len(pts):
                c = pts.sum(axis=0)
                C[j] = c / (np.linalg.norm(c) or 1)
    return lab, C


def _bisect(X: np.ndarray, k: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """bisecting spherical k-means: keep splitting the least coherent big cluster in two.
    Gives balanced, interpretable themes on short texts where plain k-means makes one giant cluster."""
    lab = np.zeros(len(X), dtype=int)
    def centroid(idx):
        c = X[idx].sum(axis=0)
        return c / (np.linalg.norm(c) or 1)
    while lab.max() + 1 < k:
        best, cost = None, -1
        for j in range(lab.max() + 1):
            idx = np.where(lab == j)[0]
            if len(idx) < 20:
                continue
            spread_ = len(idx) * (1 - float((X[idx] @ centroid(idx)).mean()))
            if spread_ > cost:
                best, cost = j, spread_
        if best is None:
            break
        idx = np.where(lab == best)[0]
        trials = [_kmeans(X[idx], 2, seed + t) for t in range(3)]
        sub, _ = max(trials, key=lambda tc: sum(float((X[idx][tc[0] == q] @ tc[1][q]).sum()) for q in (0, 1)))
        if min((sub == 0).sum(), (sub == 1).sum()) < 5:
            break
        lab[idx[sub == 1]] = lab.max() + 1
    C = np.vstack([centroid(np.where(lab == j)[0]) for j in range(lab.max() + 1)])
    return lab, C


def _silhouette(X: np.ndarray, lab: np.ndarray, sample=1500, seed=1) -> float:
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(X), min(sample, len(X)), replace=False)
    Xs, ls = X[idx], lab[idx]
    D = 1 - Xs @ Xs.T
    s = []
    for i in range(len(Xs)):
        same = ls == ls[i]
        if same.sum() < 2:
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, ls == j].mean() for j in set(ls) if j != ls[i] and (ls == j).any())
        s.append((b - a) / max(a, b))
    return float(np.mean(s)) if s else -1


def comment_themes(comments: pd.Series, band: pd.Series | None = None, *, k: int | None = None,
                   keywords: dict | None = None, labels: dict | None = None, keep: set | None = None,
                   generic_label="Sem tema específico", min_tokens=2, max_fit=6000, seed=7,
                   n_verbatims=3) -> Themes:
    """Group comments into themes OFFLINE.
    - keywords={"Entrega": ["entrega", "atraso"], ...}  -> deterministic rules (stems match), rest = "Outros"
    - otherwise TF-IDF (unigrams + down-weighted bigrams) + bisecting spherical k-means; k picked by silhouette (5–12)
    Comments with < min_tokens meaningful words ("ok", "bom") go to `generic_label`.
    Verbatims are PII-scrubbed, truncated, and picked near each theme's centroid, mixing score bands.
    labels={"Auto · label": "Nice name"} or labels=fn(auto_label, terms) -> name|None renames themes after you read
    them; themes renamed to the same name are merged. Near-duplicate quotes (template answers) are skipped."""
    s = comments.copy()
    has = s.notna()
    texts = s[has].astype(str)
    lower_vocab = {w for t in texts for w in re.findall(r"\b[a-záéíóúâêôãõçü]{3,}\b", t)}
    toks = texts.map(lambda t: [_stem(w) for w in _tokens(t)])
    surface: dict = {}
    for t in texts:
        for w in re.findall(r"[a-zà-öø-ÿ]{3,}", str(t).lower()):
            st = _stem(norm(w))
            surface.setdefault(st, {}).setdefault(w, 0)
            surface[st][w] += 1
    disp = lambda st: max(surface.get(st, {st: 1}).items(), key=lambda kv: kv[1])[0]  # noqa: E731
    out = pd.Series([None] * len(s), index=s.index, dtype=object)
    generic = toks.map(len) < min_tokens
    out.loc[texts.index[generic.values]] = generic_label
    work = toks[~generic]
    method, sil, kk = "keywords" if keywords else "tfidf-kmeans", None, 0
    centroids, vocab, X, lab = None, None, None, None
    clusters_of: dict = {}
    term_map: dict = {}
    if keywords:
        rules = {th: {_stem(norm(w)) for w in ws} for th, ws in keywords.items()}
        def pick(ts):
            best = max(rules.items(), key=lambda kv: sum(t in kv[1] for t in ts))
            return best[0] if sum(t in best[1] for t in ts) else "Outros"
        out.loc[work.index] = work.map(pick)
    elif len(work) >= 40:
        docs = [ts + [f"{a}_{b}" for a, b in zip(ts, ts[1:])] for ts in work]
        bigram_w = 0.5
        dfreq: dict = {}
        for d in docs:
            for w in set(d):
                dfreq[w] = dfreq.get(w, 0) + 1
        N = len(docs)
        min_df = max(3, int(0.003 * N))
        vocab = sorted([w for w, c in dfreq.items() if min_df <= c <= 0.5 * N], key=lambda w: -dfreq[w])[:2500]
        vi = {w: i for i, w in enumerate(vocab)}
        idf = np.array([math.log((1 + N) / (1 + dfreq[w])) + 1 for w in vocab], dtype=np.float32)
        wvec = np.array([bigram_w if "_" in w else 1.0 for w in vocab], dtype=np.float32)

        def vec(d):
            v = np.zeros(len(vocab), dtype=np.float32)
            for w in d:
                if w in vi:
                    v[vi[w]] += 1
            v = np.where(v > 0, 1 + np.log(np.maximum(v, 1)), 0) * idf * wvec
            nn = np.linalg.norm(v)
            return v / nn if nn else v
        rng = np.random.default_rng(seed)
        fit_idx = np.arange(N) if N <= max_fit else np.sort(rng.choice(N, max_fit, replace=False))
        Xf = np.vstack([vec(docs[i]) for i in fit_idx])
        ok = np.linalg.norm(Xf, axis=1) > 0
        Xf = Xf[ok]
        ks = [k] if k else [kk_ for kk_ in range(5, 13) if kk_ * 25 <= len(Xf)]
        best = None
        for kk_ in ks or [max(2, min(4, len(Xf) // 10))]:
            lab_, C_ = _bisect(Xf, kk_, seed)
            sc_ = _silhouette(Xf, lab_) if len(ks) > 1 else None
            if best is None or (sc_ is not None and sc_ > best[0]):
                best = (sc_, kk_, lab_, C_)
        sil, kk, _, centroids = best
        # assign every doc (incl. the ones not used for fitting) to its nearest centroid
        assign = []
        X = np.zeros((N, len(vocab)), dtype=np.float32) if N * len(vocab) < 6e7 else None
        names = {}
        for j in range(kk):
            order = np.argsort(-centroids[j])
            terms, seen = [], set()
            for i in order[:12]:
                w = vocab[i]
                parts = w.split("_")
                if any(p in seen for p in parts) and len(parts) == 1:
                    continue
                terms.append(" ".join(disp(p) for p in parts))
                seen.update(parts)
                if len(terms) == 3:
                    break
            names[j] = terms
        for i, d in enumerate(docs):
            v = vec(d)
            if X is not None:
                X[i] = v
            assign.append(int(np.argmax(centroids @ v)) if v.any() else -1)
        lab = np.array(assign)
        label_of = {}
        for j, terms in names.items():
            auto = " · ".join(terms).capitalize()
            name = (labels(auto, terms) if callable(labels) else (labels or {}).get(auto)) or auto
            label_of[j] = name
            clusters_of.setdefault(name, []).append(j)
            term_map.setdefault(name, [])
            term_map[name] += [t for t in terms if t not in term_map[name]]
        out.loc[work.index] = [label_of.get(j, generic_label) if j >= 0 else generic_label for j in lab]
    else:
        out.loc[work.index] = "Comentários"
    if labels and not clusters_of:
        out = out.map(lambda v: (labels(v, []) if callable(labels) else labels.get(v)) or v if v else v)
    # summary + verbatims
    total = int(has.sum())
    summary = []
    band = band if band is not None else pd.Series([None] * len(s), index=s.index)
    for th, idx in out.dropna().groupby(out.dropna()).groups.items():
        idx = list(idx)
        cand = [i for i in idx if 25 <= len(str(s[i])) <= 260] or idx
        if centroids is not None and X is not None and clusters_of.get(th):
            pos = {ix: p for p, ix in enumerate(work.index)}
            Cs = centroids[clusters_of[th]]
            cand = sorted(cand, key=lambda i: -float((Cs @ X[pos[i]]).max()) if i in pos else 0)
        picked, bands_seen = [], set()
        bc = band.reindex(idx).value_counts()
        rank = {b: r for r, b in enumerate(bc.index)}
        cand = sorted(cand, key=lambda i: rank.get(band.get(i), 9)) if len(cand) <= 40 else (
            sorted(cand[:40], key=lambda i: rank.get(band.get(i), 9)) + cand[40:])
        for i in cand:                     # prefer one quote per score band, closest to the theme first
            b = band.get(i)
            if b in bands_seen and len(bands_seen) < 3 and len(cand) > 10:
                continue
            txt = scrub_pii(s[i], keep, lower_vocab).strip()
            txt = txt if len(txt) <= 220 else txt[:217].rsplit(" ", 1)[0] + "…"
            sig = set(re.findall(r"\w{4,}", txt.lower()))
            near = lambda q: len(sig & q) / max(1, len(sig | q)) >= 0.5  # noqa: E731
            if txt and not any(near(p["_sig"]) for p in picked):
                picked.append({"text": txt, "band": None if b is None or (isinstance(b, float) and math.isnan(b)) else str(b), "_sig": sig})
                bands_seen.add(b)
            if len(picked) >= n_verbatims:
                break
        summary.append({"tema": th, "n": len(idx), "share": len(idx) / total if total else 0,
                        "terms": term_map.get(th, []), "verbatims": [{k: v for k, v in q.items() if k != "_sig"} for q in picked]})
    summary.sort(key=lambda x: -x["n"])
    return Themes(labels=out, summary=summary, method=method, k=kk, silhouette=sil)
