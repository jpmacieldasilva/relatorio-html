---
name: relatorio-html
description: Turn any dataset (CSV, XLSX, JSON, Parquet, SQLite/SQL dump, Sheets export) into a beautiful, interactive, single-file HTML report with editorial data viz — a mandatory context step (goal, audience, key points → proposal of filters, language and sections approved before building), pandas profiling, computed insights, cross-filtering charts, data table, Playwright QA. Also CX survey reports (CSAT, CES, NPS) with confidence intervals, significance tests and comment themes. Fully themeable (fonts, colors, logo). Use when the user wants a report, dashboard, or "something better than Looker" from their data.
---

# Relatório HTML — editorial, interactive reports from any dataset

The output is one self-contained `.html` file that reads like a well-edited data story (FT / The Economist / Our World in Data), not a dashboard. It has a headline that states the finding, computed highlights, KPIs with deltas and sparklines, sections that each answer one question, a searchable table and an honest methodology note. Everything cross-filters. The look comes from a **theme** (`TEMA.md`). The default "Neutro" theme is calm and neutral: off-white page, grey ink, one deep-blue primary, a colorblind-safe palette, KPI cards and subtle motion. Fonts, colors, logo, layout, shapes and motion are all configurable.

Kit: every path below is relative to **this skill's folder** (the directory that contains this `SKILL.md`; call it `$KIT`, e.g. `~/.cursor/skills/relatorio-html` or wherever the repo was cloned). Scripts locate their own files via `Path(__file__)`, so they run from any working directory; `RELATORIO_KIT=/path/to/kit` overrides the location for the snippets below. Reuse the kit; never rewrite it per report.

| File | Role |
|---|---|
| `profile.py` | load any file → conservative cleaning → profile JSON (roles, nulls, cardinality, dates, outliers, warnings) |
| `template.html` | the report shell: themeable design system (CSS custom properties), light/dark, filter bar, KPI band with count-ups, 16 chart types (incl. survey charts), scroll choreography, TOC + chapter menu, table, print CSS, cross-filter engine, CI / significance engine |
| `build.py` | validates the spec, resolves the theme (`tema.py`), encodes data, inlines d3 + Observable Plot + fonts + logo → final HTML |
| `verify.py` | headless Chromium QA + screenshots (+ PDF) |
| `exemplos/vendas/preparar.py` | complete worked example (read it before your first report; copy its structure) |
| `tema.py` + `temas/*.json` + `TEMA.md` | theme engine and presets (`neutro` default, `corporativo`, `jornal`, `noturno`, `destaque`): fonts (Google → inlined woff2, local files, system), colors, data palette, radius, rules, spacing, type scale, hero, motion, logo. Validates and checks contrast. Read `TEMA.md` before customizing |
| `cx.py` | survey kit: detect CSAT / CES / NPS / date / comment / PII columns, briefing text, response-level indicator columns, Wilson / NPS-variance / t intervals, z-tests + Holm, drivers, response rate, PII scrubbing, offline comment themes |
| `exemplos/cx/preparar.py` | worked survey example (fictional ISP, messy pt-BR export + invitation file) → `relatorio.html` |
| `vendor/` | pinned d3 7.9.0, @observablehq/plot 0.6.17, Geist + Geist Mono (OFL, optional bundled fonts); `fonts-cache/` holds the Google Fonts the presets use (Inter, IBM Plex, Newsreader, Space Grotesk, JetBrains Mono, Archivo) so builds work offline |

Import the Python helpers by path (the name `profile` clashes with the stdlib):
```python
import importlib.util, os, sys
KIT = os.environ.get("RELATORIO_KIT", "/path/to/relatorio-html")   # this skill's folder
def kit(name):
    s = importlib.util.spec_from_file_location("kit_" + name, os.path.join(KIT, f"{name}.py"))
    m = importlib.util.module_from_spec(s); sys.modules["kit_" + name] = m; s.loader.exec_module(m); return m
rp, rb, cx = kit("profile"), kit("build"), kit("cx")      # cx only for surveys
```
Setup if missing: `pip install -r $KIT/requirements.txt && python3 -m playwright install chromium` (on externally-managed Pythons add `--user --break-system-packages`, or use a venv).

## 0. Contextualização — mandatory, before anything is built

Nothing gets built (no `build.py`, no charts, no HTML) until the user has approved a short proposal. The step has three moves: ask, propose, wait.

**a) Ask a few questions, in one message or card, with options where possible.** Skip anything the conversation or the data already answers.

1. **Objetivo**: which decision will this report support? Offer 2–3 options drawn from the data ("onde investir / cortar", "acompanhar a meta do mês", "explicar uma queda").
2. **Público**: who reads it? Options: diretoria / executivo, time operacional, cliente externo, só você. Also ask how technical they are (leigo, intermediário, técnico).
3. **Pontos-chave**: the questions, hypotheses or numbers they want to see ("o Nordeste caiu mesmo?", "o chat é pior que o telefone?"). This one is optional, and "nenhum, me surpreenda" is a valid answer.
4. **Período e recorte**: propose a default window and comparison (e.g. last 12 months vs. the previous 12) plus any subset (a region, a product line, only paid orders).

The language is inferred, not asked: a user writing Portuguese gets pt-BR copy and pt-BR number formatting (`R$ 1,2 mi`, `12,5%`, `1.234`). Business rules hidden in the data (cancelled orders? refunds? test accounts? duplicates?) go into the proposal as "vou assumir X, a menos que você diga o contrário".

**b) Profile, then propose.** Run `profile.py` (step 2, it takes seconds), ideally before you send the questions so they are informed. From the profile and the answers, write one short **proposal** for approval covering:
- **Filtros**: the columns for cross-filter (3–7 low/medium-cardinality dims) plus the date presets.
- **Linguagem e tom**: formal or direto, técnico or leigo, and the language.
- **Seções / capítulos**, in reading order. For each: the question it answers and the planned chart. Order the sections by the objetivo and pontos-chave, so the reader's main question comes first.
- **KPIs**, with how each is computed (sum, ratio of sums). For surveys, the CX mapping from `cx.briefing(cx.detect(df))`: which column is CSAT / CES / NPS, its scale and threshold, plus the date and comment columns. Ask the user to confirm it.
- **Tema**: a preset (Neutro default, Corporativo, Jornal, Noturno, Destaque) or the brand look (main hex color, font, logo; light/dark/auto). Map the answers with the table in `TEMA.md`.
- **Suposições**: the defaults and business rules you assumed.

**c) Wait.** End the turn after sending the proposal, then apply the approval or the changes the user asks for. A short "ok", "pode seguir" or "aprovado" is approval. If the user asks to skip ("pula", "faz do seu jeito", "tanto faz"), go ahead with the proposal as written. Record every assumption in `contexto.suposicoes` and list them in the delivery message. Never ask the same thing twice: one proposal round, plus one more only if the changes are big.

**d) Store it in the spec.** Put the approved answers in `spec["contexto"]` and let them drive the build. The title and highlights should answer the objetivo, depth and vocabulary should follow público and linguagem, each pontos-chave item should be answered by an insight or a section (or explicitly marked as not supported by the data), and the section order should follow the proposal.
```python
spec["contexto"] = {
  "objetivo": "Decidir onde investir e onde cortar desconto no próximo trimestre",
  "publico": "Diretoria comercial; leitura rápida, pouco técnica",
  "pontos_chave": ["Crescimento por região", "Margem perdida com desconto"],
  "linguagem": {"idioma": "pt-BR", "tom": "direto", "nivel": "leigo"},   # or a plain string
  "periodo": "Últimos 12 meses vs. os 12 anteriores", "recorte": "Só pedidos pagos",
  "suposicoes": ["Pedidos cancelados ficam fora"],
  "aprovado": True,        # False when the user skipped approval
  "exibir": False,         # True adds a discreet "Sobre este relatório" column (objetivo, público, pontos-chave, suposições) to the footer
}
```
`build.py` validates the keys (a typo fails the build), and `verify.py` checks that the footer column shows up only when `exibir` is true.

Proposal template (pt-BR; fill it in, cut the lines that don't apply, keep it under ~20 lines):

```
Antes de montar, confirma se o plano faz sentido:

**Objetivo:** <decisão que o relatório apoia>
**Público:** <quem lê> · linguagem <direta | formal>, <leiga | técnica>, pt-BR
**Período:** <últimos 12 meses vs. 12 anteriores> · recorte: <tudo | …> · granularidade: <mês> em todos os gráficos de tempo

**Filtros:** <Região>, <Canal>, <Categoria>, <UF> + período (12m, ano até hoje, tudo)
**KPIs:** <Receita (soma)>, <Margem % (Σ margem ÷ Σ receita)>, <Pedidos>, <Ticket médio (Σ receita ÷ Σ pedidos)>
<só pesquisa: **Métricas:** CSAT = % notas 4–5 em <coluna> (1–5) · CES = média de <coluna> (1–7) · NPS = <coluna> (0–10)>

**Seções:**
1. <Tendência>: <a receita está crescendo?> → linha mensal
2. <Geografia>: <onde cresce e onde cai?> → barras por região + mapa de UF
3. <Mix>: <quais categorias têm a margem mais baixa?> → barras + dispersão desconto × margem
4. Tabela detalhada + metodologia

**Pontos-chave que vou responder:** <…> (<sem dados para X; fica de fora>)
**Tema:** <Neutro (padrão) | Corporativo | sua marca: cor #…, fonte …, logo>
**Vou assumir:** <pedidos cancelados fora>; <devoluções descontadas da receita>

Posso seguir assim? Se quiser, mude qualquer item, ou diga "segue" e eu monto com isso.
```

## 2. Profile and clean (pandas)

```bash
python3 $KIT/profile.py data.xlsx --sheet Vendas --out perfil.json --clean-out clean.parquet
```
- `load_any` handles CSV/TSV (encoding, delimiter and decimal-comma sniffing), XLSX (largest sheet by default), JSON/JSONL (nested → normalized), Parquet/Feather, SQLite and SQLite-compatible `.sql` dumps (largest table by default; MySQL/Postgres dumps: restore or convert first). Google Sheets: export as XLSX or CSV.
- `clean` is conservative and logs every action. It trims, normalizes null tokens, turns numeric-looking text into numbers (`R$ 1.234,56`, `12%`), parses dates (detects dd/mm vs mm/dd), and drops fully empty rows and columns. It **reports but does not fix** duplicates and category variants (`"MODA "` vs `"Moda"`). You decide in step 3 and write the decision into the methodology.
- Read `perfil.json`: `candidates.date`, `dimensions`, `measures`, `ids`, `suggested_grain`, each column's `role_reason`, `suggested_agg`, `warnings` (high-null columns, extreme values beyond 3×IQR, negatives, future dates, gaps, high cardinality). Do not guess what you can read here.
- Many files have more than one table (orders + customers). Join in pandas or SQL first, and check that row counts survive the join.

## 3. Model the data (in Python, before any HTML)

- Apply business rules (exclude cancelled orders, merge variants, map codes to labels). Each rule becomes one methodology bullet.
- **Measures** are defined once in the spec and reused everywhere:
  `{"key","label","agg": sum|mean|count|distinct|min|max|ratio, "field"|"num"+"den", "format": currency|number|decimal|percent, "good": "up"|"down", "description"}`.
  Rates (margin, conversion, ticket, CTR) are **always `ratio` = sum(num)/sum(den)**, never an average of row-level ratios. Pre-compute the numerator columns (e.g. `lucro = receita - custo`, `pedidos = 1`).
- **Pre-aggregate** to the finest grain the report needs: `df.groupby([date, *dims])[nums].sum()`. Keep only dims that filters and charts use. Encode with `rb.encode_columnar(fact, date=..., dims=[...], nums=[...], decimals=0)`, which is 3–6× smaller than row objects.
- **Size budget**: the final file should stay under ~5 MB (hard ceiling ~10 MB). Above ~150k fact rows: coarsen the date grain (day → week), drop rarely used dims, round values, or keep the long tail as "Outros". If row-level detail matters, embed a sample for the table and say so in the methodology.
- Set `meta.minGrain` to the fact grain (e.g. `"week"`), so charts never pretend to have daily data.

## 4. Narrative first — compute the story, then write it

Write for the approved `contexto` (step 0). The headline answers the objetivo, the vocabulary fits the público, and every pontos-chave item gets an insight or a section, or an honest "os dados não permitem dizer".

Structure, top to bottom (the template renders it in this order):
1. **Masthead**: a kicker, a **title that states the main finding** (it is a sentence, not "Sales report"), a 1–2 sentence dek, and the source, period and generation date. Set `meta.sample` whenever the data is synthetic.
2. **Highlights** (`insights`, 3–5 items): each is a computed fact with its number in bold, plus one line of context. The template shows `insightsScope`, so readers know which window they describe (they don't re-compute on filter).
3. **KPI row** (3–6 `kpis`): value, delta vs. comparison window (▲▼ colored by `good` direction; rates in **p.p.**), sparkline at the report's time grain.
4. **Sections**: each one has a `kicker` ("02 · Geografia"), a `title` that answers its `question`, an optional `lede`, and 1–4 charts.
5. **Data table**: group by any dim, search, sort, paginate, and two CSV exports (the table view and the raw filtered rows).
6. **Methodology and data quality**: always the **last** block and **collapsed by default** (an accessible `<details>` accordion that opens smoothly; print/PDF and the TOC link expand it). It holds measure definitions (from `description`, plus the verbatim survey question), cleaning steps, quality limits, the colophon and, when `contexto.exibir` is true, a "Sobre este relatório" column.

**Never invent a number or a direction.** Every sentence with a number or a claim ("grows", "falls", "peak at Black Friday") is generated from pandas results in the same script, with the wording derived from the sign. Example: `"cai" if g < 0 else "cresce menos"`. Name an event ("Black Friday") only if the computed peak really contains its date. Compute insights with the **same windows the HTML uses**: the `12m` preset = (max date − 12 months + 1 day … max date), and `yoy` compares the same dates one year earlier. Then check that your text matches the KPI row in the screenshot. If the data doesn't support a strong headline, write a neutral one.

**Literal language — no analogies or metaphors.** This holds for titles, highlights, ledes, chart subtitles, notes, methodology and the delivery message. Use the plainest literal terms: "caiu 3 pontos", not "esfriou"; "o grupo que mais reduz o CSAT", not "quem puxa a nota para baixo"; "cresce menos", not "fica para trás"; "grupos com CSAT abaixo do restante", not "onde a experiência quebra". Banned in generated copy: temperature, motion, body, war, sports and weather images ("esfria", "aquece", "decola", "despenca", "freia", "puxa", "segura", "fôlego", "termômetro", "raio-x", "vilão", "campeão", "tempestade"…). Statistical terms such as "margem de erro" are literal and fine. Verbs: `sobe`, `cai`, `cresce`, `fica estável`, `fica acima/abaixo de`, `reduz`, `aumenta`.

**Survey questions are shown verbatim.** Whenever a chart, KPI or definition refers to a survey question, the report shows the **complete question exactly as it is in the data** (the column header or question text, outer whitespace trimmed only, including prefixes like "Q2."). Never generate a shortened, paraphrased or "cleaned" version unless the user asks for one. `cx.prepare` stores it as `measure["question"]`. The template prints it under the chart title ("Pergunta …") for every chart that reads that score, puts it in the methodology definitions and in the KPI label tooltip, and wraps long text (no "…"). Chart titles may describe the chart, but must not restate the question in other words. Columns whose header is itself a question (e.g. "Resolvido no 1º contato?") keep it as their label. Use `c.question` for an explicit text, or `false` to hide it on one chart.

## 5. Chart selection rules

Pick the chart by the question, not by variety:

| Question | Type (`spec.type`) | Notes |
|---|---|---|
| How does it evolve? | `line` | the report's single time grain; `series` (≤5) gets direct end labels, never a legend; `annotations` for events; the peak is auto-annotated |
| How do categories rank? | `bars` | HTML bars, sorted, zero-based, value + share labels, comparison tick for the previous period; top N + "outros" |
| How do a few categories (≤ 6) compare, as a headline? | `columns` | tall flat columns with big numbers on top; `top` (5), `share`, `height`; best full-width |
| What share does each part have? | `share` | 100% strip with direct labels; replaces pie charts; slices < 2% are folded |
| Who grew or shrank? (scales differ) | `change` | diverging bars of % or p.p. change, theme positive ↑ / negative ↓ |
| Who grew or shrank? (similar scales, show levels) | `dumbbell` | Cleveland dot plot: previous ○ → current ● |
| Same trend across many groups? | `multiples` | small multiples, others in grey as context; `scale: "shared"` for magnitudes (default), `"independent"` for shapes (say so in the subtitle) |
| Two dimensions or seasonality? | `heatmap` | cat × cat, or `$month` / `$weekday` / `$year` time parts; sequential single hue |
| Relationship between two measures? | `scatter` | per category, direct labels with collision removal, average line, `r` for size, `logX` for power-law sizes |
| Distribution? | `histogram` | row-level numeric field, median marked |
| Survey: how are answers distributed? | `likert` | diverging stacked bars per group (bad left, good right, neutral split); `field` (a `*_nota` column), `scale`, `dim`, `labels` |
| Survey: NPS composition? | `nps` | detractors / passives / promoters 100% bar per group + NPS ± CI, ▲▼≈ vs. the rest (Holm) |
| Survey: which group is above / below? | `ci` | ranked dots with CI whiskers and n; overall band; small groups hollow + dashed |
| Survey: what drives the score down? | `drivers` | impact = share × (group − rest) across several `dims`; n.s. in grey |
| Survey: is the trend real? | `trendci` | metric per period with the CI band; small periods hollow |
| Survey: what do comments say? | `themes` | offline themes (cx.py) with count, band mix, metric vs. the rest and scrubbed quotes |

Principles (Tufte, Few, Cleveland), already built into the template. Don't fight them:
- Position and length beat color and angle. **No pies with more than 3 slices** (use `share` or `bars`). **No 3D. No dual axes**: use two charts, or index both series to 100. Bars always start at zero. Lines may skip zero only for non-additive measures (`zero` is automatic).
- Sort categorical bars by value. Use top N + "outros" past ~10–12 items.
- **Label directly** (end-of-line labels, value labels) instead of legends. Annotate notable points (peaks, launches, outages) with `annotations`.
- Prefer **small multiples over spaghetti**: past 4–5 lines, switch to `multiples`.
- Use color for meaning only: the theme's accent for data, its `context` grey for context. The ↑/↓ pair is the theme's positive/negative colors and every delta also carries ▲/▼ or a sign. Text contrast is ≥ 4.5:1 in both themes (data colors are fills, never small text).
- Format numbers in the report's locale (`Intl`, from `meta.lang` + `meta.currency`): compact on axes (`R$ 1,2 mi`), full in tooltips and the table. Changes are % for amounts and **p.p.** for rates.
- Chart titles state the takeaway when it holds under filtering, otherwise they describe the content. Subtitles give the unit and how to read the chart. Use `note` for caveats **specific to that chart**. Never write "clique para filtrar", "Shift+clique…" or other interaction instructions in a chart: they live in ONE place, the "Como filtrar" (?) help in the filter bar.
- **One time grain per report.** `spec["time_grain"]` (`day|week|month|quarter|year`, or `"auto"`, the default) applies to every time chart (`line`, `multiples`, `trendci`), KPI sparkline, tooltip, annotation bucket and the table's "Período" grouping. Changing the date filter does not change it. `build.py` resolves `auto` from the data span: ≤ 92 days → day, ≤ ~18 months → week, ≤ 6 years → month, otherwise quarter. It never goes finer than the data (`meta.minGrain`, or a fact that is already monthly or weekly), and it prints the choice. A chart with a different `"grain"` **fails the build** unless it also has `"grainOverride": true` (use it rarely, and say so in the subtitle). Write the copy in the same grain ("mês de maior receita", "Respostas por mês"). Compute the Python insights with the same buckets.
- **No empty charts.** At build time, a chart whose measure, dim or field has no data at all is omitted with a `spec: warning`. A section left without charts goes too, along with its TOC and menu entry, and so does a KPI with no data. In the browser, a chart that a filter empties collapses to one quiet line ("Sem dados para os filtros atuais"), and its subtitle, legend and notes fold away. Periods and categories with **n = 0** are dropped from series and bars. Groups with **n > 0** always show, and small samples (n < minN) are flagged, never hidden.

## 6. Interactivity (provided by the template)

- **Global filters**: date presets (`12m`, `ytd`, `24m`, `90d`, `30d`, `all`) plus a custom range popover, multi-select dropdowns with search and live counts, active-filter chips, "Limpar filtros", and an "N / total" counter.
- **Cross-filtering**: every component re-renders from the filtered rows. Clicking a bar, a share segment, a scatter dot, a heatmap cell, a change or dumbbell row, or a small-multiple title filters the whole report (Shift-click adds to the selection). How to interact is explained once, in the filter bar's "Como filtrar" (?) popover (`T.helpItems`). Charts carry no per-chart hint. A chart ignores its own dimension's filter, so the selection is shown as a highlight and the alternatives stay visible.
- Tooltips on every mark, and a hover crosshair on time series.
- Responsive layout: 1440 grid (section text in a 688 px main column; charts in the main column, or the wide column when a section has `half`/`third` charts, `columns`, or `"wide": true`); `span: full|half|third|twothirds`; halves stack under 1240 px, everything is one column under 1100 px. On phones the filter bar scrolls horizontally and the KPIs sit in two columns.
- **Motion** (theme `motion.speed` scales every duration — the default theme runs at 0.65×; off with `motion.enabled: false`, `prefers-reduced-motion` or `?static=1`):
  - On load: title, meta and KPI cards fade up with a short stagger (clean layout). The blocks layout instead opens the hero taller and lets it settle, and the optional art strip wipes in.
  - On scroll: blocks fade up once. Bars and columns grow with a 60 ms stagger (`cubic-bezier(.22,1,.36,1)`) and their values fade in after. Lines and areas draw left → right, dots pop and heatmap cells cascade.
  - KPI numbers count up when they enter and tween from the old value on every filter change. Bars and columns animate from their previous size when filters change.
  - Navigation: the header hides on scroll down and returns on scroll up. The sticky left TOC marks the active chapter with a primary-color bar on a hairline rail. The chapter menu slides in as a side drawer.
- Light/dark: toggle, `prefers-color-scheme`, and persistence; `?theme=dark` forces a theme for screenshots. Charts re-render with resolved theme colors.
- **Print / PDF**: the PDF button or Ctrl+P re-renders at A4 width in light theme, hides the controls, prints a summary of the applied filters, and avoids breaks inside charts.
- Hooks for QA and debugging: `window.__report.{state, setCats, toggleCat, setRange, preset, reset, revealAll, preparePrint, endPrint, stat, statFiltered, checks, grain, chartGrains, questions}`.

## 7. The spec (what you write in Python)

```python
spec = {
  "meta": {"title": ..., "kicker": ..., "subtitle": ..., "brand": ..., "source": ..., "sample": False,
           "lang": "pt-BR", "currency": "BRL", "compare": "yoy",  # or "previous"
           "theme": "auto", "minGrain": "day", "slug": "nome-arquivo",  # theme here = light/dark/auto
           "numberSections": True},  # h2 gets "1. ", "2. "…
  "time_grain": "auto",                    # ONE grain for every time chart / KPI / table period: auto | day | week | month | quarter | year
  "fields": {"date": "data", "dims": [{"key": "regiao", "label": "Região"}, ...], "measures": [...]},
  "filters": {"datePresets": ["12m", "ytd", "all"], "defaultPreset": "12m", "categorical": ["regiao", "canal"]},
  "kpis": [{"measure": "receita"}, {"measure": "margem"}],
  "insights": [{"title": "**Nordeste** cresce +30%", "text": "..."}], "insightsScope": "os últimos 12 meses ...",
  "sections": [{"id": "onde", "kicker": "Geografia", "toc": "Geografia", "title": ..., "question": ..., "lede": ...,
                "charts": [{"type": "bars", "dim": "regiao", "measure": "receita", "span": "half", "title": ..., "subtitle": ...}]}],
  "table": {"groupBy": ["uf", "canal"], "measures": [...], "columns": [...raw columns...], "pageSize": 12},
  "labels": {"col": "Label"}, "formats": {"col": "currency"},
  "methodology": {"cleaning": [...], "quality": [...], "colophon": "..."},
  "contexto": {"objetivo": ..., "publico": ..., "pontos_chave": [...], "linguagem": ..., "exibir": False},  # Passo 0
  "theme": "corporativo",                  # preset | "marca.json" | {...overrides}; see TEMA.md (omit = Neutro)
  "stats": {"minN": 30, "level": 0.95},    # surveys only (cx.prepare fills it)
  "data": rb.encode_columnar(fact, date="data", dims=[...], nums=[...], decimals=0),
}
rb.build(spec, "relatorio.html")          # validates spec + theme; fails loudly on unknown fields or chart types
# CLI: python3 $KIT/build.py spec.json relatorio.html --theme jornal
```
Text fields accept `**bold**` and `_italic_`. Chart-specific options are documented above each renderer in `template.html` (§7). For a chart type that doesn't exist, add a renderer to `CHARTS` in the template (it must read `filterRows()` and call `toggleCat` on click) and register it in `build.py` `CHART_TYPES`. Keep it generic.

Design system: the default **Neutro** theme (`temas/neutro.json`; every value below is a theme key, see `TEMA.md`):
- **Type**: Inter for text and headings (600 for headings, slight negative tracking): title 52 px / 1.1, section titles 30 px, chart titles 18 px, KPI values 40 px (auto-fit), body 16 px / 1.4. **IBM Plex Mono** 12 px uppercase for kickers, filter labels, table headers and hints. Tabular figures for every number.
- **Color**:
  - Page and ink: off-white page `#FAFAF9` with white cards, grey ink scale (`#1B1F24` ink, `#59616C` muted), light hairlines `#E3E5E8`, chart-title rules `#C8CDD3`.
  - Primary: deep blue `#1F4E79`, used for kickers, the active TOC bar and single-series lines.
  - Data: `#3A78B5` with a light area fill. The categorical palette is colorblind-safe (blue, orange, teal, rose, purple, olive, grey, tan). Good/bad is blue ↔ orange, plus ▲/▼.
  - Dark mode: graphite page `#111418` with lighter blues.
  - Contrast: ink on any colored surface is picked automatically for ≥ 4.5:1.
- **Layout** (`layout.style: "clean"`):
  - Header and hero: a plain header bar with a hairline (brand or logo plus a "dados de exemplo" pill, "Sumário +", theme, PDF). The hero sits on the page color: kicker, title, meta on the left.
  - Band: the subtitle as a lead paragraph, KPI cards in one row (up to 6; 2 per row on phones), then the highlights in three columns with a thin left rule.
  - Body: sections opened by a hairline, a colored mono kicker on the left and a numbered title. The footer is light and holds the methodology.
  - The other layout, `blocks` (presets `corporativo`, `noturno`, `destaque`), puts the hero and KPI band on full-bleed primary color with big type and a dark footer.
- **Charts**: flat, radius from the theme (10 px in Neutro: bar ends, cards, tooltips), no shadows, no gridline noise. Bar lists put the label above a 16 px bar with the value riding its end and a muted delta next to the label.
- Copy: short, declarative, in the reader's language. No "Dashboard" in the title, no emoji.
- Brand: put the user's look in `spec["theme"]` (shorthands `primary`, `accent`, `font`, `heading`, `mono`, `logo`, `brand`). `build.py` prints `theme:` warnings, which include contrast below 4.5:1 and fonts falling back to system fonts. Read them and fix or mention them.

## Pesquisas de satisfação (CSAT, CES, NPS)

Use `cx.py` whenever the data is survey answers (one row per response). Follow `exemplos/cx/preparar.py`.

**1. Detect and confirm.** `m = cx.detect(df)` finds each metric by column name, then confirms it by the values.
- Names: `csat|satisf` → CSAT; `ces|esforço|effort|facil` → CES; `nps|recomend|indicaria` → NPS; generic `nota|score|avalia` columns are assigned by scale.
- Values: scale 1–5, 1–7, 1–10 or 0–10. Text answers like "5 - Muito satisfeito" or "Muito satisfeito" are converted to numbers.
- It also finds the date column, the open comment column, an invitations / sent column, segment columns (with small-group counts), and PII / ID columns (e-mail, phone, CPF, name, protocol). PII and IDs **never** go to the HTML.
- `cx.briefing(m)` writes the mapping card. Show it to the user, apply corrections to `m`, and save it (`mapeamento.md`).

**2. Prepare.** `prep = cx.prepare(df, m, segments={"Coluna original": "chave"}, min_n=30)` builds a response-level fact with indicator columns:
- `csat_n`, `csat_top`; `ces_n`, `ces_sum`, `ces_sq`, `ces_facil`; `nps_n`, `nps_pro`, `nps_det`.
- Score-band dims: `faixa_nps` (Detratores / Neutros / Promotores), `faixa_csat`, `faixa_ces`.
- `prep.measures`, `prep.dims`, `prep.stats` and `prep.log`; the log lists out-of-scale answers and merged case variants and goes into the methodology.
- Each score measure carries `question`: the column header, verbatim. Don't rename it, and don't relabel question-type segment columns either. Short labels are fine only for plain field names ("Plano contratado" → "Plano").
- Blank answers count in `respostas` but never in a metric's denominator.

Every metric is a ratio of sums, so it stays exact under any filter:

| Metric | Default | Formula (spec measure) | CI |
|---|---|---|---|
| CSAT | 1–5, top-2 box (≥ 4) | Σ`csat_top` ÷ Σ`csat_n` (`ratio`, `percent`) | Wilson |
| CES | 1–7 (or 1–5), higher = easier unless the wording says "esforço" | mean = Σ`ces_sum` ÷ Σ`ces_n` (`mean` + `sumsq`), and % fácil (≥ 5 on 1–7, ≥ 4 on 1–5) | t-interval on the mean; Wilson for % fácil |
| NPS | 0–10; promoters 9–10, detractors 0–6 | (Σpro − Σdet) ÷ Σn (`agg: "nps"`, `format: "nps"` → −100…+100) | normal, SE = √((P + D − (P − D)²) / n) |
| Response rate | when invitations exist | Σrespostas ÷ Σconvites (`cx.add_invitations`) | Wilson |

Scale, threshold and direction are arguments of `cx.prepare` (read from the confirmed mapping). Write the definitions into each measure's `description`.

**3. Statistical honesty (built into the template and `cx.py`; never bypass it).**
- Every survey number carries its **95% CI and n**: KPI cards, tooltips, the `ci` / `nps` / `trendci` charts and the table ("IC 95%", "n" and "Amostra" columns). `stats.level` changes the level.
- **Small groups are always shown, never hidden.** A group or period with n below `stats.minN` (default 30, configurable through `cx.prepare(min_n=…)` or `spec["stats"]["minN"]`) is drawn lighter and hatched. It also gets a hollow dot, dashed whiskers, the "◌ amostra pequena" badge, a tooltip note ("leitura indicativa") and an "Amostra" flag in the table. In text, call it "indicativo".
- **Differences are tested before they are worded.** The test is a two-sided z-test on independent samples: period vs. previous period, and group vs. the rest of the base (the rest is computed by subtraction, so the samples don't overlap). Use α = 0.05. When a chart compares many groups, apply Holm correction within that chart.
- A KPI delta gets ▲/▼ and color **only if it is significant**. Otherwise it reads "≈ … · dentro da margem".
- Highlights use `cx.say_change`, `cx.diff_test` and `cx.drivers`, and the wording comes from the test result: "sobe 5,2 p.p. — melhora significativa (p < 0,001)" vs. "fica estável (+0,6 p.p., dentro da margem de erro)". **Never write "caiu", "melhorou" or "pior que" for a non-significant difference**, and never rank small groups as winners or losers.
- Embed `spec["checks"] = {"values": cx.expected_values(fact, prep.measures)}`. `verify.py` then proves that the browser computes the same values, CIs and n as Python.
- Drivers: impact = group share × (group − rest), in points of the overall metric. It describes association, not cause. Say so.

**4. Response rate.** `cx.add_invitations(prep, disparos, date=…, count=…, keys={"Canal": "canal"})` appends invitation rows with `respostas = 0`. Filters on dims the invitation file doesn't have (UF, plano, tema) make the rate undefined ("—"), never wrong. Say so in the methodology.

**5. Comments (offline, no API).**
- `th = cx.comment_themes(prep.comments, band=prep.fact["faixa_nps"], keep={"MarcaX"})` clusters the comments. It uses TF-IDF (unigrams plus down-weighted bigrams, pt-BR stopwords and light stemming) and bisecting spherical k-means, with k chosen by silhouette (5–12).
- Pass `keywords={"Cobrança": ["fatura", "cobrança"], …}` instead for deterministic rules.
- Read `th.summary` (theme, n, top terms, quotes), then rename with `labels={auto: "Nome"}` or a function of the terms. Themes renamed to the same name are merged.
- Assign `fact["tema"] = th.labels` **before** `add_invitations` and add the dim. Then use the `themes` chart with `verbatims=th.verbatims()` and `terms=th.terms()`.
- Quotes are scrubbed: e-mails, URLs, CPF/CNPJ, phones, long numbers, and names after cues ("atendente Maria") or capitalized words never seen in lowercase. The brand words in `keep` stay. Near-duplicates are skipped and quotes are truncated. The raw comment text **never** ships to the HTML.
- Themes are approximate (one theme per comment, short comments go to "Sem tema específico"). Say so in the lede.

**6. Charts for a survey report** (typical order):
1. `trendci` for CSAT / NPS.
2. `likert` by channel.
3. `nps` by channel and by contact reason.
4. `drivers` across 4–6 dims.
5. `ci` by reason and by UF (small UFs flagged).
6. `likert` for CES.
7. `themes`.
8. Volume `line` plus `trendci` for the response rate.

Table measures: `respostas`, `csat`, `ces`, `nps`, `taxa_resposta`. KPIs: CSAT, NPS, CES, respostas, taxa de resposta.

## 8. Verify before delivering (mandatory)

```bash
python3 $KIT/verify.py relatorio.html --pdf
```
It checks for zero console, page or request errors; that every chart rendered; bar, dropdown, custom-range, preset and Plot-mark clicks all change state and KPIs; that chips appear and reset works; table search, sort and CSV download; the dark toggle; no horizontal overflow on a 390 px phone (the layout viewport must stay 390); that charts below the fold wait for the scroll and a bar list grows in when reached; and that `prefers-reduced-motion` renders everything final. It also checks the report rules: the methodology is the last block, collapsed by default, opens and closes, and expands for print; interaction help appears once (no per-chart "clique para filtrar"); every time chart uses the single report grain; survey questions are shown verbatim and never cut with "…"; a filter with no data collapses every chart to one line and the charts return on reset; the TOC matches the sections on the page; and `build.py` omits charts, sections and KPIs without data. On survey reports it also checks that the browser's metric values, CIs and n equal `spec["checks"]`, that KPI cards show the CI, that Likert / NPS / theme rows filter on click and have tooltips, that CI-dot and driver-bar clicks filter, and that small samples are present and flagged. Full-page screenshots are taken with every reveal forced to its final state. It writes `-desktop-light`, `-desktop-dark`, `-mobile` (full page), `-hero-*` (first viewport) PNGs and a PDF.
Then **look at the screenshots** (crop tall pages into chunks) and fix what a picky designer would notice: misalignment, clipped or colliding labels, a title that contradicts a KPI, empty charts, a legend where direct labels fit, an unreadable dark mode. Rebuild and re-run until it is clean. Never deliver on a failing `verify.py`.

## 9. Delivery

- Send the `.html` file plus the hero screenshot (and mobile or dark if useful). Write 3–5 lines: what the report answers (tie it back to the approved objetivo and pontos-chave), the defaults you assumed (`contexto.suposicoes`), the data caveats, and how to use the filters.
- The file opens offline and works by double-click: fonts and libraries are inlined. `build.py --cdn` trades that for a smaller file (it loads the pinned jsDelivr builds; requires internet).
- Offer next steps (another cut, a brand theme, a monthly refresh as a routine). **Deploy to Vercel or share a link only if the user asks.**

## Limits to keep in mind

- All data ships to the browser. Never embed secrets or PII the audience shouldn't see; aggregate or drop those columns first.
- Highlights are static (computed for the default view); KPIs and charts are live.
- Client-side filtering is comfortable up to ~150–200k fact rows. Beyond that, pre-aggregate harder.
- Native date pickers follow the browser's locale; the visible range label always follows `meta.lang`.
