#!/usr/bin/env python3
"""
Worked example — post-service CX survey (CSAT, CES, NPS) on FICTIONAL data ("Pulsar Fibra").

    1. load the raw export (messy pt-BR column names)            ../profile.py via cx.load
    2. detect score / date / comment / segment columns           cx.detect + cx.briefing (→ mapeamento.md)
    3. prepare the response-level fact with indicator columns    cx.prepare (+ invitations → response rate)
    4. comment themes offline (TF-IDF + bisecting k-means)       cx.comment_themes (PII scrubbed)
    5. compute the highlights with the SAME stats the browser uses (CIs, tests, Holm) and word them from the tests
    6. write the spec + build                                    ../build.py → relatorio.html

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


def kit(name):
    spec = importlib.util.spec_from_file_location(f"kit_{name}", KIT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                 # cx uses dataclasses → must be registered
    spec.loader.exec_module(mod)
    return mod


cx, rb = kit("cx"), kit("build")

# ---------------------------------------------------------------- 1–2. load + detect
_ensure(HERE / "pesquisa_pulsar_EXEMPLO.csv")
raw = cx.load(HERE / "pesquisa_pulsar_EXEMPLO.csv")
disparos = cx.load(HERE / "disparos_pulsar_EXEMPLO.csv")
mapping = cx.detect(raw)
(HERE / "mapeamento.md").write_text(cx.briefing(mapping) + "\n", encoding="utf-8")
print(cx.briefing(mapping), "\n")
# the user confirmed the defaults in the briefing card (CSAT top-2 box, CES 1–7 "fácil" ≥ 5, NPS 0–10)

# ---------------------------------------------------------------- 3. prepare
SEGMENTS = {"Canal de atendimento ": "canal", "Região": "regiao", "UF": "uf", "Plano contratado": "plano",
            "Motivo do contato": "motivo", "Resolvido no 1º contato?": "resolvido", "Cliente há quanto tempo?": "tempo_cliente"}
prep = cx.prepare(raw, mapping, segments=SEGMENTS, min_n=30)
for d in prep.dims:   # short labels for plain field names only
    if d["key"] == "canal":
        d["label"] = "Canal"
    if d["key"] == "plano":
        d["label"] = "Plano"
    if d["key"] == "motivo":
        d["label"] = "Motivo"
    # columns whose header is a question ("Resolvido no 1º contato?", "Cliente há quanto tempo?") keep it verbatim

# ---------------------------------------------------------------- 4. comment themes (before invitations: same row index)
NAMES = [  # human names for the auto themes, picked by their top terms (auto label kept when nothing matches)
    (("fatura", "cobrança", "valor", "indevida"), "Cobrança e fatura"),
    (("técnico", "visita", "instalação"), "Visita técnica"),
    (("internet", "conexão", "velocidade", "caindo", "roteador", "sinal"), "Conexão e velocidade"),
    (("fila", "espera", "aguardando", "minutos", "longa", "tempo", "atendido"), "Tempo de espera"),
    (("resolver", "resolvido", "resolveram", "solicitação", "chamado", "problema"), "Resolução do problema"),
    (("atendente", "educado", "atencioso", "transferiu", "despreparado", "grosso", "paciência", "educação"), "Atendente"),
    (("aplicativo", "app"), "Aplicativo"),
    (("preço", "caro", "mensalidade", "serviço", "custo"), "Preço"),
]


def name_theme(auto, terms):
    for keys, name in NAMES:
        if terms and terms[0] in keys:          # the strongest term decides
            return name
    return None                                 # keep the auto label ("Demora · abri · chamado")


th = cx.comment_themes(prep.comments, band=prep.fact["faixa_nps"], keep={"Pulsar"}, labels=name_theme)
prep.fact["tema"] = th.labels
prep.dims.append({"key": "tema", "label": "Tema do comentário"})
print("themes:", th.method, "k =", th.k, "silhouette =", round(th.silhouette or 0, 3))
for s in th.summary:
    print(f"  {s['n']:5d}  {s['tema']:<26} {' · '.join(s['terms'])}")

prep = cx.add_invitations(prep, disparos, date="Data do disparo", count="Qtd. pesquisas enviadas",
                          keys={"Canal": "canal", "Região": "regiao"})
fact = prep.fact
M = {m["key"]: m for m in prep.measures}

# ---------------------------------------------------------------- 5. highlights (same windows + stats as the HTML)
# default view = last 12 months; comparison = META.compare "previous" (the same length right before)
mx = fact["data"].max()
cur = (mx - pd.DateOffset(months=12) + pd.Timedelta(days=1), mx)
prev = (cur[0] - (cur[1] - cur[0]) - pd.Timedelta(days=1), cur[0] - pd.Timedelta(days=1))
win = lambda d, w: d[(d["data"] >= w[0]) & (d["data"] <= w[1])]  # noqa: E731
C, P = win(fact, cur), win(fact, prev)
S = lambda d, k: cx.measure_stat(d, M[k])  # noqa: E731
csat_c, csat_p, nps_c, nps_p, ces_c = S(C, "csat"), S(P, "csat"), S(C, "nps"), S(P, "nps"), S(C, "ces")
rate_c, rate_p = S(C, "taxa_resposta"), S(P, "taxa_resposta")
csat_txt = cx.say_change(csat_c, csat_p, M["csat"], "vs. os 12 meses anteriores")
nps_txt = cx.say_change(nps_c, nps_p, M["nps"], "vs. os 12 meses anteriores")
drv = cx.drivers(C, M["csat"], ["canal", "motivo", "regiao", "plano", "resolvido"])
worst = drv[(drv["sig"]) & (drv["impact"] < 0)].head(2)
seg_uf = cx.segment_table(C, M["csat"], "uf")
small_ufs = seg_uf[seg_uf["small"]]["grupo"].tolist()
canal = cx.segment_table(C, M["nps"], "canal")
# themes among detractors in the window (comment rows only)
det = C[(C["faixa_nps"] == "Detratores") & C["tema"].notna() & (C["tema"] != "Sem tema específico")]
top_det = det["tema"].value_counts(normalize=True).head(1)
# Norte trend: last 6 months vs the 6 before (tested, worded from the test)
r6 = (mx - pd.DateOffset(months=6) + pd.Timedelta(days=1), mx)
p6 = (r6[0] - (r6[1] - r6[0]) - pd.Timedelta(days=1), r6[0] - pd.Timedelta(days=1))
norte_c, norte_p = S(win(fact[fact["regiao"] == "Norte"], r6), "csat"), S(win(fact[fact["regiao"] == "Norte"], p6), "csat")
norte_t = cx.diff_test(norte_c, norte_p)

v = lambda s, k: cx.fmt_value(s.v, M[k])  # noqa: E731
ci = lambda s, k: cx.fmt_ci(s, M[k])  # noqa: E731
insights = [
    {"title": f"CSAT de **{v(csat_c, 'csat')}**", "text": f"{csat_txt}. {ci(csat_c, 'csat')}, n = {cx._br(csat_c.n, 0)}."},
    {"title": f"NPS **{v(nps_c, 'nps')}**", "text": f"{nps_txt}. {ci(nps_c, 'nps')}."},
]
if len(worst):
    w0 = worst.iloc[0]
    lbl = {d["key"]: d["label"] for d in prep.dims}
    insights.append({"title": f"**{lbl[w0['dim']]}: {w0['grupo']}** é o grupo que mais reduz o CSAT geral",
                     "text": f"impacto de {cx.fmt_diff(w0['impact'], M['csat'])} no geral (CSAT {v(cx.Stat(w0['v'], w0['n']), 'csat')} vs. {v(cx.Stat(w0['rest'], 0), 'csat')} no restante; diferença significativa após correção de Holm, {cx.fmt_p(w0['padj'])})."})
if norte_t:
    word = (f"cai {cx.fmt_diff(-norte_t['d'], M['csat']).lstrip('+')} — queda significativa ({cx.fmt_p(norte_t['p'])})" if norte_t["sig"] and norte_t["d"] < 0
            else f"sobe {cx.fmt_diff(norte_t['d'], M['csat'])} ({cx.fmt_p(norte_t['p'])})" if norte_t["sig"]
            else f"varia {cx.fmt_diff(norte_t['d'], M['csat'])}, dentro da margem de erro")
    insights.append({"title": f"No **Norte**, o CSAT dos últimos 6 meses {word.split(' — ')[0]}",
                     "text": f"{v(norte_c, 'csat')} contra {v(norte_p, 'csat')} nos 6 meses anteriores{' — ' + word.split(' — ')[1] if ' — ' in word else ''}."})
if len(top_det):
    insights.append({"title": f"**{top_det.index[0]}** é o tema mais citado por detratores",
                     "text": f"{cx._br(top_det.iloc[0] * 100)}% dos comentários de quem deu 0 a 6 (temas agrupados automaticamente a partir do texto)."})
if small_ufs:
    insights.append({"title": f"{len(small_ufs)} UFs com menos de 30 respostas",
                     "text": f"{', '.join(small_ufs)}: aparecem nos gráficos marcadas como **amostra pequena**; leia como indicação, não como resultado."})

# ---------------------------------------------------------------- 6. spec
t_all = cx.diff_test(csat_c, csat_p) or {}
trend = "sobe" if t_all.get("sig") and t_all["d"] > 0 else "cai" if t_all.get("sig") else "fica estável"
chat = canal[canal["grupo"] == "Chat"]
chat_low = bool(len(chat) and chat["sig"].iloc[0] and chat["v"].iloc[0] < chat["rest"].iloc[0])
title = f"Pulsar Fibra: a satisfação {trend}" + (", mas o chat continua abaixo dos outros canais" if chat_low else "")
spec = {
    # Passo 0 (SKILL.md): answers approved in the proposal; shown in the footer because exibir is true
    "contexto": {
        "objetivo": "Saber se a satisfação melhorou e quais canais e motivos reduzem a nota",
        "publico": "Time de atendimento e liderança de CX",
        "pontos_chave": ["Chat ainda abaixo dos outros canais?", "O que os detratores mais citam"],
        "linguagem": {"idioma": "pt-BR", "tom": "direto", "nivel": "técnico moderado"},
        "periodo": "Últimos 12 meses vs. os 12 anteriores",
        "exibir": True,
    },
    "meta": {
        "title": title,
        "kicker": "Pesquisa pós-atendimento · CSAT, CES e NPS",
        "subtitle": f"**{cx._br(len(raw), 0)} respostas** em 24 meses. Todo número traz seu intervalo de confiança de 95%; uma diferença só é chamada de alta ou queda quando o teste estatístico confirma.",
        "brand": "Pulsar Fibra", "source": "pesquisa_pulsar_EXEMPLO.csv + disparos (gerados)", "sample": "Dados de exemplo · fictícios",
        "lang": "pt-BR", "compare": "previous", "minGrain": "day", "slug": "pulsar-cx", "grain": None,
    },
    "stats": prep.stats,
    "fields": {"date": "data", "dims": prep.dims, "measures": prep.measures},
    "filters": {"datePresets": ["12m", "24m", "90d", "all"], "defaultPreset": "12m",
                "categorical": ["canal", "regiao", "uf", "motivo", "plano", "faixa_nps", "tema"]},
    "kpis": [{"measure": "csat"}, {"measure": "nps"}, {"measure": "ces"}, {"measure": "respostas"}, {"measure": "taxa_resposta"}, {"measure": "ces_facil"}],
    "insights": insights,
    "insightsScope": "os últimos 12 meses (até 31 out 2026) vs. os 12 meses anteriores",
    "sections": [
        {"id": "satisfacao", "kicker": "Satisfação", "toc": "Satisfação", "title": "Como evolui a satisfação",
         "question": "A nota mudou além da margem de erro? A faixa mostra o intervalo de confiança de 95% de cada mês.",
         "charts": [
             {"type": "trendci", "measure": "csat", "width": "half", "title": "CSAT mensal", "subtitle": "% de notas 4–5 · faixa = IC 95% · ponto vazado = amostra pequena"},
             {"type": "trendci", "measure": "nps", "width": "half", "title": "NPS mensal", "subtitle": "pontos (−100 a +100) · faixa = IC 95%"},
             {"type": "likert", "field": "csat_nota", "scale": [1, 5], "dim": "canal", "title": "Distribuição das notas de CSAT por canal",
              "subtitle": "Notas 1–2 à esquerda do eixo, 4–5 à direita, 3 dividida ao meio. % nas pontas = insatisfeitos e satisfeitos.",
              "labels": {"1": "1 · Muito insatisfeito", "2": "2", "3": "3 · Neutro", "4": "4", "5": "5 · Muito satisfeito"}},
         ]},
        {"id": "recomendacao", "kicker": "Recomendação", "toc": "NPS", "title": "Quem recomenda a Pulsar",
         "question": "Composição do NPS: detratores, neutros e promotores, por canal e por motivo do contato.",
         "charts": [
             {"type": "nps", "measure": "nps", "dim": "canal", "width": "half", "title": "NPS por canal", "subtitle": "▲/▼ = diferente do restante da base (teste z, correção de Holm); ≈ = sem diferença significativa"},
             {"type": "nps", "measure": "nps", "dim": "motivo", "width": "half", "title": "NPS por motivo do contato", "subtitle": "Ordenado pelo NPS"},
         ]},
        {"id": "onde", "kicker": "Diagnóstico", "toc": "Diagnóstico", "title": "Grupos com CSAT abaixo do restante",
         "question": "Quais grupos têm CSAT abaixo do restante, e quanto cada um reduz a nota geral?",
         "lede": "Cada ponto traz o IC de 95% e o tamanho da amostra. Grupos com menos de 30 respostas **aparecem**, vazados e tracejados: com intervalo largo, a leitura é só indicativa.",
         "charts": [
             {"type": "drivers", "measure": "csat", "dims": ["canal", "motivo", "regiao", "plano", "resolvido"], "top": 12,
              "title": "Grupos que mais reduzem o CSAT geral", "subtitle": "Impacto = participação nas respostas × (CSAT do grupo − CSAT do restante), em p.p. do CSAT geral"},
             {"type": "ci", "measure": "csat", "dim": "motivo", "width": "half", "title": "CSAT por motivo do contato", "subtitle": "Ponto = CSAT · barra = IC 95% · faixa = geral"},
             {"type": "ci", "measure": "csat", "dim": "uf", "width": "half", "top": 27, "title": "CSAT por UF", "subtitle": "UFs pequenas ficam vazadas: amostra pequena"},
             {"type": "likert", "field": "ces_nota", "scale": [1, 7], "dim": "resolvido", "title": "Distribuição das notas de esforço (CES) por resolução no 1º contato",
              "subtitle": "Escala 1–7. Notas 1–3 à esquerda do eixo, 5–7 à direita, 4 dividida ao meio.",
              "labels": {"1": "1 · Discordo totalmente", "4": "4 · Neutro", "7": "7 · Concordo totalmente"}},
         ]},
        {"id": "comentarios", "kicker": "Comentários", "toc": "Comentários", "title": "O que os clientes escrevem",
         "question": f"{cx._br(int(prep.comments.notna().sum()), 0)} comentários abertos agrupados em temas, sem API externa.",
         "lede": "Temas encontrados por TF-IDF + k-means no próprio texto; o nome de cada tema vem dos termos mais característicos. A barra colorida mostra quem comentou (perfil NPS), e o NPS à direita compara quem cita o tema com quem não cita.",
         "charts": [
             {"type": "themes", "dim": "tema", "band": "faixa_nps", "bands": ["Detratores", "Neutros", "Promotores"], "measure": "nps",
              "exclude": ["Sem tema específico"], "verbatims": th.verbatims(), "terms": th.terms(), "quotes": 2,
              "title": "Temas dos comentários", "subtitle": "Temas agrupados automaticamente a partir do texto; barra = perfil NPS de quem comentou"},
         ]},
        {"id": "volume", "kicker": "Operação", "toc": "Volume", "title": "Volume e taxa de resposta",
         "question": "Quantas pessoas respondem, e quantas das convidadas?",
         "charts": [
             {"type": "line", "measure": "respostas", "width": "half", "title": "Respostas por mês", "subtitle": "respostas recebidas"},
             {"type": "trendci", "measure": "taxa_resposta", "width": "half", "title": "Taxa de resposta", "subtitle": "respostas ÷ pesquisas enviadas · IC 95%"},
             {"type": "bars", "dim": "canal", "measure": "respostas", "width": "third", "title": "Respostas por canal", "subtitle": "respostas no período · tique = período anterior"},
             {"type": "bars", "dim": "regiao", "measure": "respostas", "width": "third", "title": "Respostas por região", "subtitle": "respostas no período · tique = período anterior"},
             {"type": "bars", "dim": "plano", "measure": "respostas", "width": "third", "title": "Respostas por plano", "subtitle": "respostas no período · tique = período anterior"},
         ]},
    ],
    "table": {"groupBy": ["canal", "motivo", "uf", "regiao", "plano", "tema"], "measures": ["respostas", "csat", "ces", "nps", "taxa_resposta"], "raw": False, "pageSize": 12},
    "methodology": {
        "cleaning": [
            "Uma linha por resposta. Notas em texto (\"5 - Muito satisfeito\") convertidas para número; respostas em branco contam só no total de respostas, não no denominador da métrica.",
            *prep.log,
            f"Colunas pessoais e identificadores **não** foram enviados ao HTML: {', '.join(mapping['pii'] + mapping['ids'])}.",
            "Comentários: o texto completo **não** está no arquivo; só o tema de cada resposta e alguns exemplos com e-mails, telefones, documentos, números longos e nomes mascarados.",
            "Taxa de resposta = Σ respostas ÷ Σ pesquisas enviadas (base de disparos por dia × canal × região); filtros por UF, plano, motivo ou tema deixam a taxa indefinida (—).",
        ],
        "quality": [
            f"IC de {round(prep.stats['level'] * 100)}%: Wilson para proporções (CSAT, % fácil, taxa), variância para o NPS (√((P + D − (P − D)²)/n)), t para a média do CES.",
            "Diferenças: teste z bilateral entre amostras independentes (grupo vs. restante, ou período vs. período anterior), α = 5%, correção de Holm quando vários grupos são testados juntos. Sem significância, o texto diz \"dentro da margem\".",
            f"Grupos com n < {prep.stats['minN']} são sempre exibidos e marcados como amostra pequena.",
            "Temas automáticos são aproximados: um comentário recebe um único tema; comentários muito curtos (\"ok\") ficam em \"Sem tema específico\".",
        ],
        "colophon": "Dados **fictícios**, gerados por gerar_dados.py. Relatório gerado pelo kit relatorio-html.",
    },
    "checks": {"values": cx.expected_values(fact, prep.measures, prep.stats["level"], prep.stats["minN"])},
}
spec["meta"].pop("grain")
nums = prep.nums + ["convites"]
fact["data"] = pd.to_datetime(fact["data"])
spec["data"] = rb.encode_columnar(fact, date="data", dims=[d["key"] for d in prep.dims], nums=nums,
                                  decimals={k: 0 for k in nums})
(HERE / "spec_resumo.json").write_text(json.dumps({k: v for k, v in spec.items() if k != "data"}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
theme = sys.argv[1] if len(sys.argv) > 1 else None
out = HERE / (f"relatorio-{theme}.html" if theme else "relatorio.html")
rb.build(spec, out, theme=theme)
for i in insights:
    print("•", i["title"], "—", i["text"])
