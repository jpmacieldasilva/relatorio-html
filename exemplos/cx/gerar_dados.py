#!/usr/bin/env python3
"""
Gera DADOS FICTÍCIOS de pesquisa de satisfação pós-atendimento da "Pulsar Fibra", uma provedora de
internet que NÃO EXISTE. Nomes, e-mails, telefones e protocolos são inventados.

Saídas (com nomes de coluna bagunçados de propósito, como num export real de Google Forms/SurveyMonkey):
    pesquisa_pulsar_EXEMPLO.csv   uma linha por resposta (separador ";", datas dd/mm/aaaa hh:mm:ss)
    disparos_pulsar_EXEMPLO.csv   pesquisas enviadas por dia × canal × região (para a taxa de resposta)

Padrões embutidos para o relatório encontrar (e para testar a honestidade estatística):
    • melhora lenta ao longo de 24 meses; chat pior que os demais canais; loja e app melhores
    • "Cobrança/fatura" e "Cancelamento" puxam a nota para baixo; não resolver no 1º contato derruba tudo
    • o Norte piora a partir de mai/2026 (instabilidade de rede)
    • UFs pequenas (AC, AP, RR, TO) com poucas respostas → devem aparecer marcadas como amostra pequena
"""
from __future__ import annotations

import datetime as dt
import random
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(20261116)
random.seed(20261116)
OUT = Path(__file__).resolve().parent
START, END = dt.date(2024, 11, 1), dt.date(2026, 10, 31)

REGIOES = {
    "Sudeste": (["SP", "RJ", "MG", "ES"], [0.55, 0.22, 0.19, 0.04], 0.44),
    "Sul": (["PR", "SC", "RS"], [0.38, 0.27, 0.35], 0.17),
    "Nordeste": (["BA", "PE", "CE", "RN", "PB", "AL", "SE", "MA", "PI"], [0.26, 0.2, 0.18, 0.07, 0.07, 0.06, 0.05, 0.07, 0.04], 0.21),
    "Centro-Oeste": (["DF", "GO", "MT", "MS"], [0.34, 0.36, 0.17, 0.13], 0.09),
    "Norte": (["PA", "AM", "RO", "TO", "AC", "AP", "RR"], [0.44, 0.33, 0.12, 0.05, 0.025, 0.02, 0.015], 0.09),
}
CANAIS = {  # peso no volume de disparos, taxa de resposta base, efeito na satisfação, prob. de resolver no 1º contato
    "Telefone": (0.30, 0.11, -0.20, 0.70),
    "Chat": (0.24, 0.21, -0.55, 0.60),
    "WhatsApp": (0.26, 0.24, 0.05, 0.72),
    "App": (0.12, 0.27, 0.25, 0.80),
    "Loja": (0.08, 0.15, 0.40, 0.84),
}
MOTIVOS = {  # peso, efeito, prob. extra de não resolver
    "Sem conexão": (0.22, -0.55, 0.10), "Lentidão": (0.18, -0.35, 0.10), "Cobrança/fatura": (0.17, -0.80, 0.08),
    "Mudança de endereço": (0.09, -0.10, 0.05), "Upgrade de plano": (0.10, 0.55, -0.10), "Cancelamento": (0.07, -1.00, 0.15),
    "Dúvida técnica": (0.17, 0.20, -0.05),
}
PLANOS = {"Fibra 300 Mega": (0.36, -0.05), "Fibra 500 Mega": (0.33, 0.05), "Fibra 1 Giga": (0.21, 0.15), "Empresarial": (0.10, -0.10)}
TEMPO_CLIENTE = {"Menos de 1 ano": 0.3, "1 a 3 anos": 0.42, "Mais de 3 anos": 0.28}
NOMES = ["Carlos", "Juliana", "Marcos", "Fernanda", "Rafael", "Patrícia", "Thiago", "Aline", "Bruno", "Camila", "Diego", "Larissa"]
SOBRENOMES = ["Souza", "Lima", "Ferreira", "Almeida", "Costa", "Ribeiro", "Martins", "Barbosa"]

TEMAS = {
    "espera": {
        "neg": ["Demorei {m} minutos na fila para ser atendido", "Espera muito longa no {canal}, fiquei mais de {m} minutos aguardando",
                "Muita demora para alguém responder no {canal}", "Fila de espera enorme, um absurdo", "Tempo de espera muito longo até falar com alguém",
                "Fiquei esperando na linha por {m} minutos e a ligação caiu"],
        "pos": ["Fui atendido rápido, quase sem espera", "Atendimento ágil, sem fila nenhuma", "Pouco tempo de espera, gostei"],
    },
    "resolucao": {
        "neg": ["Problema não foi resolvido, vou ter que ligar de novo", "Já é a terceira vez que entro em contato e nada foi resolvido",
                "Continuam sem resolver minha solicitação", "Prometeram resolver e não resolveram", "Abri chamado de novo porque o problema voltou"],
        "pos": ["Resolveram meu problema na hora", "Problema resolvido no primeiro contato", "Resolveram tudo de forma rápida e simples",
                "Solicitação resolvida sem complicação"],
    },
    "atendente": {
        "neg": ["O atendente foi grosso e sem paciência", "Atendente despreparado, não sabia responder minhas dúvidas", "Falta de educação do atendente",
                "A atendente me transferiu várias vezes sem explicar nada"],
        "pos": ["Atendente muito educado e atencioso", "A atendente foi super simpática e paciente", "Atendimento cordial, atendente prestativo",
                "Atendente atencioso, explicou tudo com calma"],
    },
    "cobranca": {
        "neg": ["Cobrança indevida na fatura deste mês", "Valor da fatura veio errado de novo", "Me cobraram um serviço que não contratei",
                "Fatura com valor maior do que o combinado", "Cobraram multa indevida na fatura"],
        "pos": ["Corrigiram o valor da fatura rapidinho", "Estornaram a cobrança indevida sem burocracia"],
    },
    "conexao": {
        "neg": ["Internet cai toda noite", "Conexão instável, velocidade muito abaixo do contratado", "Sinal do wi-fi fraco e a internet oscila muito",
                "A internet fica caindo várias vezes por dia", "Velocidade muito baixa no horário de pico"],
        "pos": ["Depois da troca do roteador a internet ficou ótima", "Velocidade excelente desde a instalação", "Conexão estável, nunca mais caiu"],
    },
    "tecnico": {
        "neg": ["O técnico não apareceu no dia agendado", "Remarcaram a visita técnica três vezes", "A visita técnica demorou uma semana para acontecer",
                "Técnico chegou atrasado e não resolveu"],
        "pos": ["Técnico pontual e resolveu tudo na visita", "Visita técnica rápida e caprichada", "O técnico foi muito cuidadoso na instalação"],
    },
    "app": {
        "neg": ["O aplicativo trava na hora de pagar a fatura", "O app não mostra a segunda via da fatura", "Aplicativo muito lento e confuso"],
        "pos": ["App muito fácil de usar, resolvi tudo sozinho", "Pelo aplicativo foi tudo muito simples", "Consegui resolver pelo app em poucos minutos"],
    },
    "preco": {
        "neg": ["Preço alto pelo que entregam", "Reajuste muito caro, estou pensando em cancelar", "Mensalidade cara comparada com a concorrência"],
        "pos": ["Preço justo pelo serviço", "Bom custo-benefício"],
    },
}
GENERICOS = ["ok", "Bom", "nada a declarar", "Tudo certo", "Ótimo", "ruim", "regular", "Satisfeito", "nenhum", "."]
PREFIX = ["", "", "", "Sinceramente, ", "Olha, ", "Bom, "]
SUFFIX = {"pos": [""] * 12 + [" Obrigado.", " Recomendo.", "!!", " Parabéns."],
          "neg": [""] * 12 + [" Espero que melhorem.", " Fica a dica.", "!!", " Decepcionado."]}


def theme_weights(canal, motivo, resolvido):
    w = {"espera": 1.2, "resolucao": 1.0, "atendente": 1.0, "cobranca": 0.3, "conexao": 0.6, "tecnico": 0.4, "app": 0.25, "preco": 0.3}
    if canal in ("Telefone", "Chat"):
        w["espera"] += 1.3
    if canal == "App":
        w["app"] += 1.6
    if motivo == "Cobrança/fatura":
        w["cobranca"] += 3.0
    if motivo in ("Sem conexão", "Lentidão"):
        w["conexao"] += 1.6; w["tecnico"] += 0.8
    if motivo == "Mudança de endereço":
        w["tecnico"] += 1.8
    if motivo == "Cancelamento":
        w["preco"] += 2.0
    if resolvido == "Não":
        w["resolucao"] += 2.2
    k = list(w); p = np.array([w[x] for x in k]); return k[rng.choice(len(k), p=p / p.sum())]


def comment(canal, motivo, resolvido, nps):
    if rng.random() < 0.09:
        return random.choice(GENERICOS)
    tema = theme_weights(canal, motivo, resolvido)
    tone = "neg" if nps <= 6 else "pos" if nps >= 9 else ("neg" if rng.random() < 0.55 else "pos")
    if tone == "pos" and not TEMAS[tema]["pos"]:
        tone = "neg"
    t = random.choice(TEMAS[tema][tone]).format(m=int(rng.integers(15, 90)), canal=canal.lower() if canal != "WhatsApp" else "WhatsApp")
    if rng.random() < 0.25:   # second sentence from another theme
        t2 = theme_weights(canal, motivo, resolvido)
        if t2 != tema and TEMAS[t2][tone]:
            t += ". " + random.choice(TEMAS[t2][tone]).format(m=int(rng.integers(15, 90)), canal=canal.lower())
    if random.random() < 0.3:
        t = random.choice(PREFIX) + t[0].lower() + t[1:]
    suf = random.choice(SUFFIX[tone])
    t += ("" if suf.startswith("!") else ".") + suf if suf else ("." if random.random() < 0.6 else "")
    r = rng.random()   # PII that people really type into survey boxes
    if r < 0.04:
        n = random.choice(NOMES); t += f" Fui atendido pelo {n} {random.choice(SOBRENOMES)}." if n[-1] != "a" else f" A atendente {n} foi quem me ajudou."
    elif r < 0.06:
        t += f" Meu e-mail é {random.choice(NOMES).lower()}.{random.choice(SOBRENOMES).lower()}{rng.integers(10, 99)}@gmail.com, podem me retornar."
    elif r < 0.08:
        t += f" Liguem no (11) 9{rng.integers(1000, 9999)}-{rng.integers(1000, 9999)}."
    elif r < 0.10:
        t += f" Protocolo {rng.integers(10**10, 10**11 - 1)}."
    if random.random() < 0.15:
        t = t.lower()
    if random.random() < 0.1:
        t = t.replace("ã", "a").replace("ç", "c").replace("é", "e")
    return t


def main():
    days = pd.date_range(START, END, freq="D")
    resp, disp = [], []
    for day in days:
        t = (day - pd.Timestamp(START)).days / (END - START).days
        season = 1 + 0.18 * np.sin(2 * np.pi * (day.dayofyear / 365.25 - 0.1)) + (0.25 if day.month in (1, 12) else 0)
        weekday = 0.65 if day.dayofweek == 6 else 0.85 if day.dayofweek == 5 else 1.0
        for reg, (ufs, ufw, rw) in REGIOES.items():
            for canal, (cw, rate, ceff, pres) in CANAIS.items():
                lam = 120 * rw * cw * season * weekday * (1 + 0.25 * t)
                inv = int(rng.poisson(lam))
                if not inv:
                    continue
                r_rate = rate * (1 + 0.15 * t) * (0.9 if canal == "Telefone" and t > 0.5 else 1)
                k = int(rng.binomial(inv, min(0.9, r_rate)))
                disp.append({"Data do disparo": day.strftime("%Y-%m-%d"), "Canal": canal, "Região": reg, "Qtd. pesquisas enviadas": inv})
                for _ in range(k):
                    uf = ufs[rng.choice(len(ufs), p=np.array(ufw) / sum(ufw))]
                    mot = list(MOTIVOS)[rng.choice(len(MOTIVOS), p=np.array([v[0] for v in MOTIVOS.values()]) / sum(v[0] for v in MOTIVOS.values()))]
                    plano = list(PLANOS)[rng.choice(len(PLANOS), p=[v[0] for v in PLANOS.values()])]
                    tc = list(TEMPO_CLIENTE)[rng.choice(3, p=list(TEMPO_CLIENTE.values()))]
                    resolvido = "Sim" if rng.random() < pres - MOTIVOS[mot][2] + 0.06 * t else "Não"
                    espera = max(0, int(rng.gamma(2.0, 6 if canal in ("Telefone", "Chat") else 2.5)))
                    lat = (0.55 + 0.45 * t + ceff + MOTIVOS[mot][1] + PLANOS[plano][1] + (-1.35 if resolvido == "Não" else 0)
                           - 0.012 * espera + (-0.75 if reg == "Norte" and day >= pd.Timestamp("2026-05-01") else 0) + rng.normal(0, 1.05))
                    csat = int(np.clip(np.round(3.4 + 1.05 * lat + rng.normal(0, 0.45)), 1, 5))
                    nps = int(np.clip(np.round(7.3 + 1.9 * lat + rng.normal(0, 1.0)), 0, 10))
                    ces = int(np.clip(np.round(4.9 + 1.4 * lat + rng.normal(0, 0.9)), 1, 7))
                    ts = day + pd.Timedelta(seconds=int(rng.integers(7 * 3600, 22 * 3600)))
                    labels5 = {1: "1 - Muito insatisfeito", 2: "2 - Insatisfeito", 3: "3 - Neutro", 4: "4 - Satisfeito", 5: "5 - Muito satisfeito"}
                    resp.append({
                        "Carimbo de data/hora": ts.strftime("%d/%m/%Y %H:%M:%S"),
                        "Nº do protocolo": str(rng.integers(10**10, 10**11 - 1)),
                        "Canal de atendimento ": canal if rng.random() > 0.01 else canal.upper(),
                        "Região": reg, "UF": uf, "Plano contratado": plano, "Motivo do contato": mot,
                        "Cliente há quanto tempo?": tc, "Resolvido no 1º contato?": resolvido, "Tempo de espera (min)": espera,
                        "Q1. Em uma escala de 1 a 5, qual a sua satisfação com o atendimento recebido?": labels5[csat] if rng.random() < 0.12 else str(csat),
                        "Q2. A Pulsar facilitou a resolução da sua solicitação? (1 = discordo totalmente, 7 = concordo totalmente)": ces if rng.random() > 0.22 else None,
                        "Q3. Numa escala de 0 a 10, o quanto você recomendaria a Pulsar a um amigo ou familiar?": nps if rng.random() > 0.015 else None,
                        "Q4. Quer contar o motivo da sua nota? (opcional)": comment(canal, mot, resolvido, nps) if rng.random() < 0.38 else None,
                        "E-mail (opcional)": f"{random.choice(NOMES).lower()}{rng.integers(1, 999)}@exemplo.com" if rng.random() < 0.3 else None,
                    })
    df = pd.DataFrame(resp).sample(frac=1, random_state=7)
    df.to_csv(OUT / "pesquisa_pulsar_EXEMPLO.csv", sep=";", index=False, encoding="utf-8-sig")
    pd.DataFrame(disp).to_csv(OUT / "disparos_pulsar_EXEMPLO.csv", sep=";", index=False, encoding="utf-8-sig")
    print(f"{len(df)} respostas, {len(disp)} linhas de disparos, {df.iloc[:, 13].notna().mean():.0%} com comentário")


if __name__ == "__main__":
    main()
