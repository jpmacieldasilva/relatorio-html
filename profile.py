#!/usr/bin/env python3
"""
profile.py — load (almost) any tabular file, clean it conservatively, and profile it.

CLI
    python profile.py data.csv                         # prints a readable summary, writes data.profile.json
    python profile.py book.xlsx --sheet Vendas --out p.json
    python profile.py dump.sql --table pedidos --clean-out clean.parquet
    python profile.py data.csv --no-clean              # profile the raw file as-is

Python
    import importlib.util, os
    kit = os.environ.get("RELATORIO_KIT", "caminho/para/relatorio-html")
    spec = importlib.util.spec_from_file_location("rp", os.path.join(kit, "profile.py"))
    rp = importlib.util.module_from_spec(spec); spec.loader.exec_module(rp)
    df = rp.load_any("data.csv"); df, notes = rp.clean(df); summary = rp.profile(df, notes)
    (`import profile` would hit the stdlib module of the same name — load it by path.)

Supported inputs
    .csv .tsv .txt (encoding + delimiter + decimal-comma sniffing), .xlsx .xlsm .xls, .json (records,
    {"data": [...]}, nested -> json_normalize), .jsonl/.ndjson, .parquet, .feather, .sqlite/.db,
    .sql (SQLite-compatible dumps; MySQL/Postgres dumps: convert first or load into duckdb/sqlite).

What `clean` does (and records in notes — surface them in the report's methodology):
    strips column names and string cells, drops fully-empty rows/columns, turns numeric-looking text
    (incl. pt-BR "1.234,56", "R$ 1.234", "12,5%") into numbers, parses date-like text (detects
    day-first), standardises null tokens ("", "-", "NA", "null", "n/a"), reports — but does not drop —
    exact duplicate rows and case/spacing variants of the same category.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

NULL_TOKENS = {"", "-", "--", "—", "na", "n/a", "nan", "null", "none", "nil", "#n/d", "#n/a", "s/d", "sem dado"}
ID_HINT = re.compile(r"(^|_|\b)(id|uuid|guid|cod|codigo|código|code|sku|cpf|cnpj|cep|zip|phone|telefone|email|e-mail|pedido_id|order_id)($|_|\b)", re.I)
MEAN_HINT = re.compile(r"(pre[cç]o|price|taxa|rate|ratio|pct|percent|%|nota|score|rating|idade|age|m[eé]dia|avg|mean|temperatura|temp|lat|lon|nps)", re.I)
SUM_HINT = re.compile(r"(valor|receita|revenue|venda|sales|faturamento|custo|cost|lucro|profit|margem_bruta|quantidade|qtd|qty|quantity|units|unidades|itens|items|pedidos|orders|total|amount|montante|despesa|spend|sal[aá]rio|salary|wage|clicks|cliques|impress|sessions|visitas|users|usuarios)", re.I)


# =========================================================================== #
# Loading                                                                     #
# =========================================================================== #
def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _sniff_csv(text: str) -> dict:
    sample = text[:50_000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        sep = dialect.delimiter
    except csv.Error:
        counts = {d: sample.count(d) for d in [",", ";", "\t", "|"]}
        sep = max(counts, key=counts.get)
    # decimal comma when ';' separates and numbers look like 1.234,56 or 12,5
    decimal = "," if sep == ";" and re.search(r"\d,\d{1,3}(?:[;\n\r]|$)", sample) else "."
    return {"sep": sep, "decimal": decimal}


def load_any(path: str | Path, sheet: str | int | None = None, table: str | None = None) -> pd.DataFrame:
    """Load a file into a DataFrame. Raises ValueError with a helpful message when unsure."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".csv", ".tsv", ".txt"):
        text = _read_text(path)
        opts = _sniff_csv(text)
        if ext == ".tsv":
            opts["sep"] = "\t"
        thousands = "." if opts["decimal"] == "," else None
        return pd.read_csv(io.StringIO(text), sep=opts["sep"], decimal=opts["decimal"], thousands=thousands,
                           dtype_backend="numpy_nullable", low_memory=False)
    if ext in (".xlsx", ".xlsm", ".xls"):
        xl = pd.ExcelFile(path)
        if sheet is None:
            # pick the sheet with the most cells
            sizes = {s: xl.parse(s, nrows=2000).size for s in xl.sheet_names}
            sheet = max(sizes, key=sizes.get)
            if len(xl.sheet_names) > 1:
                print(f"[profile] sheets: {xl.sheet_names} -> using '{sheet}' (pass --sheet to choose)", file=sys.stderr)
        return xl.parse(sheet)
    if ext in (".json",):
        obj = json.loads(_read_text(path))
        if isinstance(obj, dict):
            lists = {k: v for k, v in obj.items() if isinstance(v, list)}
            if not lists:
                return pd.json_normalize(obj)
            obj = lists[table] if table else max(lists.values(), key=len)
        return pd.json_normalize(obj)
    if ext in (".jsonl", ".ndjson"):
        return pd.read_json(path, lines=True)
    if ext == ".parquet":
        return pd.read_parquet(path)
    if ext == ".feather":
        return pd.read_feather(path)
    if ext in (".sqlite", ".db", ".sqlite3"):
        return _from_sqlite(sqlite3.connect(path), table)
    if ext == ".sql":
        con = sqlite3.connect(":memory:")
        try:
            con.executescript(_read_text(path))
        except sqlite3.Error as e:
            raise ValueError(f"could not load SQL dump into SQLite ({e}). For MySQL/Postgres dumps, restore into a "
                             "real database or convert (e.g. `pip install duckdb` and use its readers), then export CSV/Parquet.")
        return _from_sqlite(con, table)
    raise ValueError(f"unsupported extension '{ext}'. Export to CSV/XLSX/Parquet/JSON first.")


def _from_sqlite(con, table: str | None) -> pd.DataFrame:
    tables = [r[0] for r in con.execute("select name from sqlite_master where type in ('table','view')")]
    if not tables:
        raise ValueError("no tables found")
    if table is None:
        counts = {t: con.execute(f'select count(*) from "{t}"').fetchone()[0] for t in tables}
        table = max(counts, key=counts.get)
        if len(tables) > 1:
            print(f"[profile] tables: {counts} -> using '{table}' (pass --table to choose; joins: do them in SQL first)", file=sys.stderr)
    return pd.read_sql_query(f'select * from "{table}"', con)


# =========================================================================== #
# Cleaning                                                                    #
# =========================================================================== #
_NUM_RE = re.compile(r"^\s*[-+]?\s*(R\$|US\$|\$|€|£)?\s*[-+]?[\d.,\s]+\s*%?\s*$")


def _to_number(s: pd.Series) -> pd.Series | None:
    """Parse numeric-looking text incl. pt-BR formats. Returns None if the column isn't numeric text."""
    v = s.dropna().astype(str).str.strip()
    if v.empty or v.map(lambda x: bool(_NUM_RE.match(x))).mean() < 0.97:
        return None
    pct = v.str.endswith("%").mean() > 0.9
    t = s.astype("string").str.replace(r"R\$|US\$|\$|€|£|%|\s", "", regex=True)
    sample = t.dropna().head(5000)
    # decide the decimal separator: last separator in the string with 1-2 digits after it
    comma_dec = sample.str.contains(r",\d{1,2}$").mean()
    dot_dec = sample.str.contains(r"\.\d{1,2}$").mean()
    if comma_dec > dot_dec or sample.str.contains(r"^\d{1,3}(\.\d{3})+$").mean() > 0.3:
        t = t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        t = t.str.replace(",", "", regex=False)
    out = pd.to_numeric(t, errors="coerce")
    if out.notna().sum() < 0.97 * s.notna().sum():
        return None
    return out / 100 if pct else out


def _to_date(s: pd.Series) -> tuple[pd.Series, str] | None:
    v = s.dropna().astype(str).str.strip()
    if v.empty:
        return None
    looks = v.head(2000).str.match(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}([ T]\d{1,2}:\d{2}(:\d{2})?)?")
    if looks.mean() < 0.9:
        return None
    first = v.head(2000)
    iso = first.str.match(r"^\d{4}-\d{2}-\d{2}").mean() > 0.9
    if iso:
        out = pd.to_datetime(s, errors="coerce", format="mixed")
        how = "ISO"
    else:
        # day-first if any first component > 12, or the user writes pt/es/fr (default dd/mm for '/')
        parts = first.str.extract(r"^(\d{1,2})[-/.](\d{1,2})")
        a, b = pd.to_numeric(parts[0], errors="coerce"), pd.to_numeric(parts[1], errors="coerce")
        dayfirst = not ((b > 12).any() and not (a > 12).any())
        out = pd.to_datetime(s, errors="coerce", dayfirst=dayfirst, format="mixed")
        how = "dd/mm/aaaa" if dayfirst else "mm/dd/yyyy"
    if out.notna().sum() < 0.95 * s.notna().sum():
        return None
    return out, how


def _norm_key(x: str) -> str:
    x = unicodedata.normalize("NFKD", str(x)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", x).strip().lower()


def clean(df: pd.DataFrame, drop_duplicates: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """Conservative cleaning. Returns (df, notes). Notes are human-readable, pt-BR-agnostic English;
    translate when writing the report's methodology section."""
    notes: list[str] = []
    df = df.copy()
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    if df.columns.duplicated().any():
        seen: dict[str, int] = {}
        cols = []
        for c in df.columns:
            seen[c] = seen.get(c, 0) + 1
            cols.append(c if seen[c] == 1 else f"{c}_{seen[c]}")
        df.columns = cols
        notes.append("renamed duplicated column names with _2, _3 suffixes")
    n0 = len(df)
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        df = df.drop(columns=empty_cols)
        notes.append(f"dropped {len(empty_cols)} fully empty column(s): {', '.join(empty_cols[:8])}")
    df = df.dropna(how="all")
    if len(df) < n0:
        notes.append(f"dropped {n0 - len(df)} fully empty row(s)")

    for c in df.columns:
        s = df[c]
        if s.dtype == object or str(s.dtype).startswith("string"):
            st = s.astype("string").str.strip()
            st = st.mask(st.str.lower().isin(NULL_TOKENS))
            changed = int((st.fillna("\0") != s.astype("string").fillna("\0")).sum())
            num = _to_number(st)
            if num is not None:
                df[c] = num
                notes.append(f"'{c}': text converted to numbers ({num.notna().sum()} values)")
                continue
            dt = _to_date(st)
            if dt is not None:
                df[c] = dt[0]
                notes.append(f"'{c}': text parsed as dates ({dt[1]})")
                continue
            df[c] = st
            if changed:
                notes.append(f"'{c}': trimmed whitespace / normalised null tokens in {changed} cell(s)")
            # category variants (same value differing only by case/accents/spacing)
            vc = st.dropna().value_counts()
            if 1 < len(vc) <= 5000:
                groups: dict[str, list[str]] = {}
                for val in vc.index:
                    groups.setdefault(_norm_key(val), []).append(val)
                variants = [g for g in groups.values() if len(g) > 1]
                if variants:
                    ex = "; ".join(" / ".join(map(repr, g[:3])) for g in variants[:3])
                    notes.append(f"'{c}': {len(variants)} value(s) with case/accent/spacing variants (e.g. {ex}) — consider merging")

    dups = int(df.duplicated().sum())
    if dups:
        if drop_duplicates:
            df = df.drop_duplicates()
            notes.append(f"dropped {dups} exact duplicate row(s)")
        else:
            notes.append(f"{dups} exact duplicate row(s) found (kept — confirm whether they are real repeats)")
    return df.reset_index(drop=True), notes


# =========================================================================== #
# Profiling                                                                   #
# =========================================================================== #
def _py(v):
    """JSON-safe python scalar."""
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        return None if math.isnan(v) or math.isinf(v) else round(float(v), 6)
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v if isinstance(v, (int, str, bool)) else str(v)


def _date_profile(s: pd.Series) -> dict:
    d = pd.to_datetime(s, errors="coerce").dropna()
    if d.empty:
        return {}
    u = pd.Series(sorted(d.dt.normalize().unique()))
    diffs = u.diff().dt.days.dropna()
    step = float(diffs.median()) if len(diffs) else None
    freq = None
    if step is not None:
        freq = "daily" if step <= 1 else "weekly" if 6 <= step <= 8 else "monthly" if 27 <= step <= 32 else \
            "quarterly" if 88 <= step <= 93 else "yearly" if 360 <= step <= 370 else f"~{step:.0f} days"
    span = (d.max() - d.min()).days
    grain = "day" if span <= 75 else "week" if span <= 400 else "month" if span <= 1800 else "quarter"
    expected = {"daily": 1, "weekly": 7, "monthly": 30.4, "quarterly": 91, "yearly": 365}.get(freq)
    gaps = int((diffs > expected * 1.5).sum()) if expected else None
    today = pd.Timestamp.today().normalize()
    last = d.max()
    return {
        "min": d.min().isoformat(), "max": last.isoformat(), "span_days": int(span), "distinct_dates": int(len(u)),
        "frequency": freq, "suggested_grain": grain, "gaps": gaps,
        "future_dates": int((d > today + pd.Timedelta(days=1)).sum()),
        "has_time": bool((d.dt.hour + d.dt.minute + d.dt.second).any()),
        "last_period_partial": bool(freq in ("daily",) and last.day < 28),
        "weekday_share": {k: round(float(v), 4) for k, v in d.dt.dayofweek.value_counts(normalize=True).sort_index().items()},
    }


def _num_profile(s: pd.Series) -> dict:
    x = pd.to_numeric(s, errors="coerce").dropna().astype(float)
    if x.empty:
        return {}
    q1, q3 = x.quantile([0.25, 0.75])
    iqr = q3 - q1
    lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
    out_mask = (x < lo) | (x > hi) if iqr > 0 else pd.Series(False, index=x.index)
    return {
        "min": _py(x.min()), "p01": _py(x.quantile(0.01)), "p25": _py(q1), "median": _py(x.median()),
        "mean": _py(x.mean()), "p75": _py(q3), "p99": _py(x.quantile(0.99)), "max": _py(x.max()),
        "std": _py(x.std()), "sum": _py(x.sum()),
        "zeros": int((x == 0).sum()), "negatives": int((x < 0).sum()),
        "is_integer": bool((x % 1 == 0).all()),
        "outliers_iqr3": int(out_mask.sum()),
        "outlier_examples": [_py(v) for v in x[out_mask].sort_values(key=abs, ascending=False).head(5)],
        "skew": _py(x.skew()) if len(x) > 2 else None,
    }


def _role(name: str, s: pd.Series, n: int) -> tuple[str, str]:
    """Infer (role, reason). role ∈ date | measure | dimension | id | text | constant | boolean"""
    nn = s.notna().sum()
    uniq = s.nunique(dropna=True)
    if uniq <= 1:
        return "constant", "one distinct value"
    if pd.api.types.is_bool_dtype(s):
        return "boolean", "true/false"
    if pd.api.types.is_datetime64_any_dtype(s):
        return "date", "datetime type"
    if pd.api.types.is_numeric_dtype(s):
        integer = bool((pd.to_numeric(s, errors="coerce").dropna() % 1 == 0).all())
        if ID_HINT.search(name) and integer:
            return "id", "name looks like an identifier"
        if integer and uniq / max(nn, 1) > 0.98 and nn > 50 and not SUM_HINT.search(name):
            x = pd.to_numeric(s, errors="coerce").dropna().to_numpy()
            sequential = x.size > 1 and ((np.diff(np.sort(x)) == 1).mean() > 0.8 or bool((np.diff(x) > 0).all()))
            if sequential:
                return "id", "unique, sequential integers"
        if re.search(r"(ano|year|mes|month|trimestre|quarter|semana|week|dia|day)$", name, re.I) and integer and uniq <= 60:
            return "dimension", "time-part integer (treat as ordinal dimension)"
        if integer and uniq <= 12 and not SUM_HINT.search(name):
            return "dimension", f"integer with only {uniq} distinct values (code/rating?) — confirm"
        return "measure", "numeric"
    # text
    st = s.dropna().astype(str)
    avg_len = st.str.len().mean() if len(st) else 0
    if ID_HINT.search(name) or (uniq / max(nn, 1) > 0.9 and nn > 50 and avg_len < 40):
        return "id", "mostly unique short text"
    if avg_len > 40 and uniq / max(nn, 1) > 0.5:
        return "text", "long free text"
    return "dimension", f"{uniq} categories"


def _suggest_agg(name: str, prof: dict) -> str:
    if MEAN_HINT.search(name):
        return "mean (or a ratio of sums if a numerator/denominator exist)"
    if SUM_HINT.search(name) or (prof.get("negatives", 0) == 0 and prof.get("is_integer")):
        return "sum"
    return "sum or mean — decide from meaning"


def profile(df: pd.DataFrame, notes: list[str] | None = None, top: int = 8) -> dict:
    n = len(df)
    cols = []
    for c in df.columns:
        s = df[c]
        role, why = _role(str(c), s, n)
        nulls = int(s.isna().sum())
        uniq = int(s.nunique(dropna=True))
        col = {"name": str(c), "dtype": str(s.dtype), "role": role, "role_reason": why,
               "nulls": nulls, "null_pct": round(nulls / n, 4) if n else 0,
               "unique": uniq, "unique_pct": round(uniq / n, 4) if n else 0}
        if role == "date":
            col["date"] = _date_profile(s)
        elif pd.api.types.is_numeric_dtype(s) and role != "boolean":
            col["stats"] = _num_profile(s)
            if role == "measure":
                col["suggested_agg"] = _suggest_agg(str(c), col["stats"])
        if role in ("dimension", "boolean", "id", "text", "constant") or uniq <= 30:
            vc = s.value_counts(dropna=True).head(top)
            col["top_values"] = [{"value": _py(k), "count": int(v), "share": round(v / n, 4)} for k, v in vc.items()]
            if role == "dimension":
                col["long_tail"] = bool(uniq > 15)
                col["top5_share"] = round(float(s.value_counts(normalize=True).head(5).sum()), 4)
        cols.append(col)

    by = lambda r: [c["name"] for c in cols if c["role"] == r]
    dates = [c for c in cols if c["role"] == "date"]
    primary_date = max(dates, key=lambda c: (1 - c["null_pct"], c["date"].get("distinct_dates", 0)))["name"] if dates else None
    dims = sorted((c for c in cols if c["role"] in ("dimension", "boolean")), key=lambda c: c["unique"])
    measures = by("measure")

    warnings = []
    for c in cols:
        if c["null_pct"] > 0.2:
            warnings.append(f"'{c['name']}' is {c['null_pct']:.0%} null")
        st = c.get("stats") or {}
        if st.get("outliers_iqr3"):
            warnings.append(f"'{c['name']}': {st['outliers_iqr3']} extreme value(s) beyond 3×IQR (e.g. {st['outlier_examples'][:3]})")
        if c["role"] == "measure" and st.get("negatives"):
            warnings.append(f"'{c['name']}': {st['negatives']} negative value(s) — returns/refunds/adjustments?")
        d = c.get("date") or {}
        if d.get("future_dates"):
            warnings.append(f"'{c['name']}': {d['future_dates']} date(s) in the future")
        if d.get("gaps"):
            warnings.append(f"'{c['name']}': {d['gaps']} gap(s) in the {d['frequency']} sequence")
        if c["role"] == "dimension" and c["unique"] > 50:
            warnings.append(f"'{c['name']}': high cardinality ({c['unique']}) — use top-N + 'outros' or search filter")

    return {
        "rows": n, "columns": len(df.columns),
        "memory_mb": round(df.memory_usage(deep=True).sum() / 1e6, 2),
        "duplicate_rows": int(df.duplicated().sum()),
        "candidates": {
            "date": primary_date, "other_dates": [c["name"] for c in dates if c["name"] != primary_date],
            "dimensions": [c["name"] for c in dims], "measures": measures,
            "ids": by("id"), "text": by("text"), "constant": by("constant"),
            "suggested_grain": (next(c for c in dates if c["name"] == primary_date)["date"].get("suggested_grain") if primary_date else None),
        },
        "cleaning_notes": notes or [],
        "warnings": warnings,
        "columns_detail": cols,
    }


def print_summary(p: dict) -> None:
    c = p["candidates"]
    print(f"rows: {p['rows']:,}  cols: {p['columns']}  dup rows: {p['duplicate_rows']}  mem: {p['memory_mb']} MB")
    print(f"date: {c['date']}  grain: {c['suggested_grain']}  other dates: {c['other_dates']}")
    print(f"dimensions: {c['dimensions']}")
    print(f"measures:   {c['measures']}")
    if c["ids"] or c["text"] or c["constant"]:
        print(f"ids: {c['ids']}  text: {c['text']}  constant: {c['constant']}")
    print("\ncolumns:")
    for col in p["columns_detail"]:
        extra = ""
        if col.get("date"):
            d = col["date"]
            extra = f"{d['min'][:10]} → {d['max'][:10]} · {d['frequency']}"
        elif col.get("stats"):
            s = col["stats"]
            extra = f"min {s['min']} · med {s['median']} · max {s['max']} · {col.get('suggested_agg', '')}"
        elif col.get("top_values"):
            extra = ", ".join(f"{t['value']} ({t['share']:.0%})" for t in col["top_values"][:4])
        print(f"  {col['name'][:28]:<28} {col['role']:<10} null {col['null_pct']:>5.1%}  uniq {col['unique']:>7,}  {extra}")
    for title, items in (("cleaning notes", p["cleaning_notes"]), ("warnings", p["warnings"])):
        if items:
            print(f"\n{title}:")
            for x in items:
                print("  -", x)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--sheet")
    ap.add_argument("--table")
    ap.add_argument("--out", help="profile JSON path (default: <file>.profile.json)")
    ap.add_argument("--clean-out", help="write the cleaned table (.parquet or .csv)")
    ap.add_argument("--no-clean", action="store_true")
    ap.add_argument("--drop-duplicates", action="store_true")
    a = ap.parse_args()
    df = load_any(a.path, sheet=a.sheet, table=a.table)
    notes: list[str] = []
    if not a.no_clean:
        df, notes = clean(df, drop_duplicates=a.drop_duplicates)
    p = profile(df, notes)
    out = Path(a.out or (str(a.path) + ".profile.json"))
    out.write_text(json.dumps(p, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print_summary(p)
    print(f"\nprofile → {out}")
    if a.clean_out:
        co = Path(a.clean_out)
        df.to_parquet(co, index=False) if co.suffix == ".parquet" else df.to_csv(co, index=False)
        print(f"clean table → {co}")


if __name__ == "__main__":
    main()
