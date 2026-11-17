#!/usr/bin/env python3
"""
End-to-end example of the skill's pipeline on SAMPLE data (fictional retailer "Casa Aurora").

    1. load + clean + profile      (../profile.py)
    2. business rules              (exclude cancelled/returned orders, merge category variants)
    3. pre-aggregate               (day × UF × categoria × canal  → ~25k rows instead of 29k orders)
    4. compute insights in pandas  (same windows the HTML uses: last 12 months vs same period a year before)
    5. write the spec + build      (../build.py)  → relatorio.html

Run:  python gerar_dados.py && python preparar.py
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
KIT = Path(os.environ.get("RELATORIO_KIT") or HERE.parents[1])   # repo root (override with $RELATORIO_KIT)


def _ensure(csv: Path):
    """the sample CSVs are not committed: generate them on first run"""
    if not csv.exists():
        import runpy
        runpy.run_path(str(HERE / "gerar_dados.py"), run_name="__main__")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rp, rb = _load("profile"), _load("build")

# ---------------------------------------------------------------- 1. load, clean, profile
_ensure(HERE / "vendas_casa_aurora_EXEMPLO.csv")
raw = rp.load_any(HERE / "vendas_casa_aurora_EXEMPLO.csv")
df, notes = rp.clean(raw)
prof = rp.profile(df, notes)
(HERE / "perfil.json").write_text(json.dumps(prof, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

# ---------------------------------------------------------------- 2. business rules
n_raw = len(df)
dups = int(df.duplicated().sum())
df = df.drop_duplicates()
df["categoria"] = df["categoria"].str.strip().str.title().str.replace("&", "&", regex=False)
df["categoria"] = df["categoria"].replace({"Casa & Cozinha": "Casa & Cozinha"})
canal_null = int(df["canal"].isna().sum())
df["canal"] = df["canal"].fillna("Não informado")
status = df["status"].value_counts()
df = df[df["status"] == "Entregue"].copy()
df["lucro"] = df["receita"] - df["custo"]
df["pedidos"] = 1

# ---------------------------------------------------------------- 3. pre-aggregate
DIMS = ["regiao", "uf", "categoria", "canal"]
NUMS = ["receita", "custo", "lucro", "desconto", "valor_bruto", "pedidos", "itens"]
EMBED = ["receita", "lucro", "desconto", "valor_bruto", "pedidos", "itens"]   # custo is implied by lucro
fact = df.groupby(["data", *DIMS], as_index=False, observed=True)[NUMS].sum()

# ---------------------------------------------------------------- 4. insights (same windows as the HTML)
mx = fact["data"].max()
cur = (mx - pd.DateOffset(months=12) + pd.Timedelta(days=1), mx)
prev = (cur[0] - pd.DateOffset(months=12), cur[1] - pd.DateOffset(months=12))
win = lambda d, w: d[(d["data"] >= w[0]) & (d["data"] <= w[1])]
C, P = win(fact, cur), win(fact, prev)


def brl(v, compact=True):
    if compact and abs(v) >= 1e6:
        return f"R$ {v / 1e6:.1f} mi".replace(".", ",")
    if compact and abs(v) >= 1e3:
        return f"R$ {v / 1e3:.0f} mil"
    return f"R$ {v:,.0f}".replace(",", ".")


num = lambda v: f"{v:,.0f}".replace(",", ".")
dec = lambda v: f"{v:.1f}".replace(".", ",")
pct = lambda v, s=True: (f"{v:+.1%}" if s else f"{v:.1%}").replace(".", ",")
pp = lambda v, s=True: (f"{v * 100:+.1f}" if s else f"{abs(v) * 100:.1f}").replace(".", ",") + " p.p."

rec_c, rec_p = C.receita.sum(), P.receita.sum()
reg = pd.DataFrame({"c": C.groupby("regiao").receita.sum(), "p": P.groupby("regiao").receita.sum()})
reg["g"] = reg.c / reg.p - 1
best, worst = reg.g.idxmax(), reg.g.idxmin()
cat = pd.DataFrame({
    "mc": C.groupby("categoria").lucro.sum() / C.groupby("categoria").receita.sum(),
    "mp": P.groupby("categoria").lucro.sum() / P.groupby("categoria").receita.sum(),
    "dc": C.groupby("categoria").desconto.sum() / C.groupby("categoria").valor_bruto.sum(),
    "dp": P.groupby("categoria").desconto.sum() / P.groupby("categoria").valor_bruto.sum(),
})
cat["dm"] = cat.mc - cat.mp
mcat = cat.dm.idxmin()
m_c, m_p = C.lucro.sum() / rec_c, P.lucro.sum() / rec_p
ch = pd.DataFrame({"c": C.groupby("canal").receita.sum() / rec_c, "p": P.groupby("canal").receita.sum() / rec_p})
ch["d"] = ch.c - ch.p
up_ch, dn_ch = ch.d.idxmax(), ch.d.idxmin()
# the report uses ONE time grain (build.py picks "month" for 24 months of daily data), so the peak is a month too
mo = C.set_index("data").receita.resample("MS").sum()
pk = mo.idxmax()
pk_ratio = mo.max() / mo.median()
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
pk_name = f"{MESES[pk.month - 1]} de {pk.year}"
pk_note = " (mês da Black Friday)" if pk.month == 11 else " (mês do Natal)" if pk.month == 12 else ""

insights = [
    {"title": f"Receita de **{brl(rec_c)}** nos últimos 12 meses, **{pct(rec_c / rec_p - 1)}** sobre o mesmo período anterior",
     "text": f"Foram **{num(C.pedidos.sum())}** pedidos entregues, com ticket médio de **{brl(rec_c / C.pedidos.sum(), False)}**."},
    {"title": f"**{best}** é a região que mais cresce ({pct(reg.g[best])}); **{worst}** "
              + ("cai" if reg.g[worst] < 0 else "cresce menos") + f" ({pct(reg.g[worst])})",
     "text": (f"{worst} perdeu **{brl(reg.p[worst] - reg.c[worst])}** de receita em um ano." if reg.g[worst] < 0 else
              f"{worst} ganhou só **{brl(reg.c[worst] - reg.p[worst])}** em um ano; {best} ganhou **{brl(reg.c[best] - reg.p[best])}**.")},
    {"title": f"A margem de **{mcat}** caiu **{pp(cat.dm[mcat], False)}**",
     "text": f"O desconto médio da categoria foi de **{pct(cat.dp[mcat], False)}** para **{pct(cat.dc[mcat], False)}** do valor bruto. Margem total: **{pct(m_c, False)}** ({pp(m_c - m_p)})."},
    {"title": f"**{up_ch}** ganha participação ({pp(ch.d[up_ch])}); **{dn_ch}** perde ({pp(ch.d[dn_ch])})",
     "text": f"{up_ch} responde agora por **{pct(ch.c[up_ch], False)}** da receita."},
    {"title": f"O mês de maior receita foi **{pk_name}**{pk_note}: **{dec(pk_ratio)}×** a mediana mensal",
     "text": f"Receita de **{brl(mo.max())}** no mês, contra mediana mensal de **{brl(mo.median())}** nos últimos 12 meses."},
]

# headline copy derived from the numbers above (never hand-typed claims)
cat_rev = pd.DataFrame({"c": C.groupby("categoria").receita.sum(), "p": P.groupby("categoria").receita.sum()})
cat_rev["g"] = cat_rev.c / cat_rev.p - 1
top_cat = cat_rev.c.idxmax()
fast_ch = (C.groupby("canal").receita.sum() / P.groupby("canal").receita.sum() - 1).drop("Não informado", errors="ignore").idxmax()
# literal wording only (no metaphors): "cresce", "cai", "sobe" — derived from the sign
verb = "cresce" if rec_c >= rec_p else "cai"
title = f"Casa Aurora: receita {verb} {pct(abs(rec_c / rec_p - 1), False)}, margem {'cai' if m_c < m_p else 'sobe'} {pp(m_c - m_p, False)}"
subtitle = (f"Nos últimos 12 meses a receita {verb} **{pct(rec_c / rec_p - 1)}**. O maior crescimento foi em {best} e no canal {fast_ch}. "
            f"Em {mcat}, o desconto maior reduziu a margem em **{pp(cat.dm[mcat], False)}**.")
sec_trend = f"A receita {verb} {pct(abs(rec_c / rec_p - 1), False)} em 12 meses; o mês de maior receita foi {pk_name}"
sec_geo = f"{best} cresce {pct(reg.g[best], False)}; {worst} " + ("cai" if reg.g[worst] < 0 else "cresce menos") + f" ({pct(reg.g[worst])})"
sec_mix = f"{mcat} vende {pct(cat_rev.c[mcat] / rec_c, False)} da receita e perdeu {pp(cat.dm[mcat], False)} de margem"
ch_title = f"{fast_ch} cresce mais rápido que os outros canais"

# ---------------------------------------------------------------- 5. spec + build
spec = {
    # Passo 0 (SKILL.md): answers approved in the proposal; drive copy and section order
    "contexto": {
        "objetivo": "Decidir onde investir e onde cortar desconto no próximo trimestre",
        "publico": "Diretoria comercial; leitura rápida, pouco técnica",
        "pontos_chave": ["Crescimento por região", "Margem perdida com desconto", "Canal que mais cresce"],
        "linguagem": {"idioma": "pt-BR", "tom": "direto", "nivel": "leigo"},
        "periodo": "Últimos 12 meses vs. os 12 anteriores",
        "exibir": False,
    },
    "meta": {
        "title": title,
        "kicker": "Relatório de vendas · Omnichannel",
        "subtitle": subtitle,
        "brand": "Casa Aurora",
        "sample": "Dados de exemplo · fictícios",
        "source": "vendas_casa_aurora_EXEMPLO.csv (gerado)",
        "lang": "pt-BR", "currency": "BRL", "compare": "yoy", "slug": "casa-aurora",
    },
    "fields": {
        "date": "data", "dateLabel": "Data",
        "dims": [{"key": "regiao", "label": "Região"}, {"key": "uf", "label": "UF"},
                 {"key": "categoria", "label": "Categoria"}, {"key": "canal", "label": "Canal"}],
        "measures": [
            {"key": "receita", "label": "Receita", "agg": "sum", "format": "currency",
             "description": "Valor pago pelo cliente após descontos, sem frete. Somente pedidos entregues."},
            {"key": "pedidos", "label": "Pedidos", "agg": "sum", "format": "number",
             "description": "Pedidos entregues (cancelados e devolvidos excluídos)."},
            {"key": "ticket", "label": "Ticket médio", "agg": "ratio", "num": "receita", "den": "pedidos", "format": "currency",
             "description": "Receita ÷ pedidos, calculado sobre as somas do recorte."},
            {"key": "margem", "label": "Margem bruta", "agg": "ratio", "num": "lucro", "den": "receita", "format": "percent",
             "description": "(Receita − custo) ÷ receita. Variações em pontos percentuais (p.p.)."},
            {"key": "desconto_pct", "label": "Desconto médio", "agg": "ratio", "num": "desconto", "den": "valor_bruto", "format": "percent", "good": "down",
             "description": "Desconto ÷ valor bruto. Aqui, subir é ruim."},
            {"key": "lucro", "label": "Lucro bruto", "agg": "sum", "format": "currency"},
        ],
    },
    "filters": {"datePresets": ["12m", "ytd", "24m", "all"], "defaultPreset": "12m",
                "categorical": ["regiao", "uf", "categoria", "canal"]},
    "kpis": [{"measure": "receita"}, {"measure": "pedidos"}, {"measure": "ticket"},
             {"measure": "margem"}, {"measure": "desconto_pct"}],
    "insights": insights,
    "insightsScope": f"os últimos 12 meses ({cur[0]:%d/%m/%Y} a {cur[1]:%d/%m/%Y}) comparados ao mesmo período do ano anterior, sem filtros",
    "sections": [
        {"id": "tendencia", "kicker": "Tendência", "toc": "Tendência", "title": sec_trend,
         "question": "O negócio está crescendo, e em que ritmo?",
         "lede": f"Mês de maior receita: **{brl(mo.max())}**, {dec(pk_ratio)}× a mediana mensal. A Black Friday aparece marcada; troque o período no topo para ver a série completa.",
         "charts": [
             {"type": "line", "measure": "receita", "title": "Receita por período",
              "subtitle": "Receita mensal.",
              "annotations": [{"date": "2024-11-29", "label": "Black Friday"}, {"date": "2025-11-28", "label": "Black Friday"}]},
             {"type": "line", "measure": "receita", "series": "canal", "top": 4, "span": "half", "height": 260,
              "title": ch_title, "subtitle": "Receita mensal por canal."},
             {"type": "share", "dim": "canal", "measure": "receita", "span": "half",
              "title": "Participação de cada canal na receita", "subtitle": "Participação de cada canal na receita total do período."},
         ]},
        {"id": "onde", "kicker": "Geografia", "toc": "Geografia", "title": sec_geo,
         "question": "Quais regiões e estados crescem, e quais caem?",
         "charts": [
             {"type": "columns", "dim": "regiao", "measure": "receita",
              "title": "Receita por região", "subtitle": "Participação de cada região na receita do período."},
             {"type": "change", "dim": "uf", "measure": "receita", "top": 12,
              "title": "Variação da receita por UF", "subtitle": "As 12 maiores UFs, contra o mesmo período do ano anterior."},
             {"type": "scatter", "dim": "uf", "x": "receita", "y": "margem", "r": "pedidos", "labelTop": 14, "logX": True,
              "title": "Receita versus margem por UF", "subtitle": "Cada círculo é uma UF; área proporcional aos pedidos.",
              "note": "Margem calculada como soma do lucro ÷ soma da receita de cada UF."},
         ]},
        {"id": "mix", "kicker": "Mix e margem", "toc": "Mix e margem", "title": sec_mix,
         "question": "Quais categorias crescem, e quanto isso custa em margem?",
         "charts": [
             {"type": "bars", "dim": "categoria", "measure": "receita", "span": "half", "title": "Receita por categoria"},
             {"type": "dumbbell", "dim": "categoria", "measure": "margem", "span": "half", "marginLeft": 104, "sort": "value",
              "title": "Margem bruta por categoria", "subtitle": "Variação em p.p. contra o ano anterior."},
             {"type": "multiples", "dim": "categoria", "measure": "receita",
              "scale": "independent",
              "title": "Evolução mensal de cada categoria", "subtitle": "Escala própria em cada painel: compare formas, não tamanhos. As demais categorias em cinza, como contexto."},
         ]},
        {"id": "quando", "kicker": "Sazonalidade", "toc": "Sazonalidade", "title": "Quando cada categoria vende",
         "question": "Em quais meses cada categoria vende mais?",
         "charts": [
             {"type": "heatmap", "x": "$month", "y": "categoria", "measure": "receita", "marginLeft": 112,
              "title": "Receita por mês e categoria", "subtitle": "Receita em R$; quanto mais escuro, maior. Repare em Beleza em maio (Dia das Mães)."},
             {"type": "heatmap", "x": "$weekday", "y": "canal", "measure": "pedidos", "span": "half", "marginLeft": 96, "cellHeight": 30,
              "title": "Pedidos por dia da semana e canal"},
             {"type": "bars", "dim": "uf", "measure": "ticket", "top": 10, "span": "half", "share": False,
              "title": "Ticket médio por UF, 10 maiores", "subtitle": "Receita ÷ pedidos."},
         ]},
    ],
    "table": {"groupBy": ["uf", "categoria", "canal", "regiao"],
              "measures": ["receita", "pedidos", "ticket", "margem", "desconto_pct", "lucro"],
              "columns": ["data", "regiao", "uf", "categoria", "canal", "receita", "pedidos", "itens", "desconto", "lucro"],
              "pageSize": 12},
    "labels": {"receita": "Receita", "pedidos": "Pedidos", "itens": "Itens", "desconto": "Desconto (R$)", "lucro": "Lucro bruto", "data": "Data"},
    "formats": {"desconto": "currency", "itens": "number", "pedidos": "number"},
    "methodology": {
        "cleaning": [
            f"Arquivo original com {n_raw:,} linhas; {dups} linhas duplicadas removidas.".replace(",", "."),
            "Datas lidas no formato dd/mm/aaaa; valores com vírgula decimal convertidos.",
            "Categorias com grafias diferentes (ex.: “MODA ” e “Moda”) unificadas.",
            f"{canal_null} pedidos sem canal agrupados como “Não informado”.",
            f"Considerados só pedidos entregues: {status.get('Cancelado', 0):,} cancelados e {status.get('Devolvido', 0):,} devolvidos ficaram de fora.".replace(",", "."),
            f"Dados agregados por dia × UF × categoria × canal ({len(fact):,} linhas).".replace(",", "."),
        ],
        "quality": [
            "**Dados de exemplo, gerados por script.** Não representam nenhuma empresa real.",
            "Comparações usam o mesmo intervalo do ano anterior. Sem base completa, o indicador mostra “sem base de comparação”.",
            "Taxas (margem, desconto, ticket) são sempre razões de somas, nunca médias de médias.",
            "Valores extremos (pedidos acima de R$ 10 mil) foram mantidos: são compras reais de Eletrônicos.",
        ],
        "colophon": "Gerado com a skill _relatório HTML_: perfil em pandas, gráficos em Observable Plot e d3, arquivo único e autocontido.",
    },
    "data": rb.encode_columnar(fact, date="data", dims=DIMS, nums=EMBED, decimals=0),  # whole reais are enough for a report
}
theme = sys.argv[1] if len(sys.argv) > 1 else None      # python preparar.py corporativo → relatorio-corporativo.html
rb.build(spec, HERE / (f"relatorio-{theme}.html" if theme else "relatorio.html"), theme=theme)
