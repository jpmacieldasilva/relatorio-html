#!/usr/bin/env python3
"""
SAMPLE DATA — generates a fictional order-level sales file for "Casa Aurora" (a made-up Brazilian
omnichannel retailer). Nothing here is real. The file deliberately mimics a messy pt-BR export
(';' separator, decimal comma, dd/mm/aaaa dates, stray spaces, a few nulls and duplicates)
so the profiler/cleaner gets exercised.

    python gerar_dados.py  ->  exemplos/vendas/vendas_casa_aurora_EXEMPLO.csv
"""
import numpy as np
import pandas as pd
from pathlib import Path

rng = np.random.default_rng(42)
OUT = Path(__file__).with_name("vendas_casa_aurora_EXEMPLO.csv")

UF = {  # uf: (região, peso)
    "SP": ("Sudeste", .22), "RJ": ("Sudeste", .09), "MG": ("Sudeste", .10), "ES": ("Sudeste", .02),
    "PR": ("Sul", .06), "RS": ("Sul", .06), "SC": ("Sul", .045),
    "BA": ("Nordeste", .07), "PE": ("Nordeste", .045), "CE": ("Nordeste", .045), "MA": ("Nordeste", .02),
    "PB": ("Nordeste", .015), "RN": ("Nordeste", .015), "AL": ("Nordeste", .012), "PI": ("Nordeste", .012), "SE": ("Nordeste", .01),
    "GO": ("Centro-Oeste", .035), "DF": ("Centro-Oeste", .03), "MT": ("Centro-Oeste", .017), "MS": ("Centro-Oeste", .014),
    "PA": ("Norte", .035), "AM": ("Norte", .02), "RO": ("Norte", .008), "TO": ("Norte", .008), "AC": ("Norte", .004), "AP": ("Norte", .004), "RR": ("Norte", .003),
}
REG_GROWTH = {"Sudeste": .12, "Sul": -.03, "Nordeste": .34, "Centro-Oeste": .16, "Norte": .22}  # yearly
CAT = {  # categoria: (ticket médio, margem base, peso)
    "Eletrônicos": (1350, .16, .17), "Casa & Cozinha": (260, .33, .24), "Moda": (175, .46, .22),
    "Beleza": (115, .52, .16), "Esportes": (310, .31, .12), "Livros": (72, .28, .09),
}
CANAL = ["Site", "App", "Marketplace", "Loja física"]

days = pd.date_range("2024-01-01", "2026-10-31", freq="D")
rows = []
order_id = 100000
for d in days:
    t = (d - days[0]).days / 365.25
    season = 1 + .10 * np.cos((d.dayofyear - 350) / 365.25 * 2 * np.pi)      # stronger in Dec
    if d.month == 11 and 20 <= d.day <= 30: season *= 2.4 if d.weekday() == 4 and d.day >= 22 else 1.55   # Black Friday
    if d.month == 12 and d.day <= 23: season *= 1.35                               # Natal
    if d.month == 1: season *= .82
    weekday = [1.0, .97, .96, .98, 1.05, 1.12, 1.02][d.weekday()]
    # each region grows at its own pace; total orders = sum of regional demand
    w = np.array([wt * (1 + REG_GROWTH[r]) ** t for r, wt in UF.values()])
    n = rng.poisson(22 * season * weekday * w.sum() / sum(wt for _, wt in UF.values()))
    if n == 0:
        continue
    ufs = rng.choice(list(UF), size=n, p=w / w.sum())
    cw = np.array([c[2] for c in CAT.values()])
    if d.month == 5 and d.day <= 12: cw = cw * np.array([1, 1, 1.2, 2.2, 1, 1])     # Dia das Mães → Beleza
    cats = rng.choice(list(CAT), size=len(ufs), p=cw / cw.sum())
    app_share = .18 + .14 * t / 3
    mkt_share = .15 + .10 * t / 3
    pw = np.array([1 - app_share - mkt_share - .14, app_share, mkt_share, .14])
    chans = rng.choice(CANAL, size=len(ufs), p=pw / pw.sum())
    for u, c, ch in zip(ufs, cats, chans):
        ticket, margin, _ = CAT[c]
        qty = int(rng.choice([1, 1, 1, 2, 2, 3, 4]))
        price = float(rng.lognormal(np.log(ticket / 1.4), .45))
        disc = rng.beta(1.4, 14)
        if d.month == 11 and d.day >= 20: disc += .12
        if ch == "Marketplace": disc += .03
        if c == "Eletrônicos" and d.year == 2026: disc += .05                    # price war in 2026
        disc = min(disc, .6)
        gross = qty * price
        receita = gross * (1 - disc)
        custo = gross * (1 - margin)
        frete = 0 if receita > 199 else round(float(rng.uniform(12, 29)), 2)
        status = rng.choice(["Entregue", "Cancelado", "Devolvido"], p=[.935, .045, .02])
        order_id += 1
        rows.append((order_id, d, u, UF[u][0], c, ch, qty, round(gross, 2), round(gross - receita, 2),
                     round(receita, 2), round(custo, 2), frete, status))

df = pd.DataFrame(rows, columns=["pedido_id", "data", "uf", "regiao", "categoria", "canal", "itens",
                                 "valor_bruto", "desconto", "receita", "custo", "frete", "status"])
# --- deliberate mess (typical of real exports) -------------------------------------------------
idx = rng.choice(len(df), 40, replace=False); df.loc[idx, "categoria"] = df.loc[idx, "categoria"].str.upper() + " "
idx = rng.choice(len(df), 25, replace=False); df.loc[idx, "canal"] = None
idx = rng.choice(len(df), 12, replace=False); df.loc[idx, "frete"] = None
df = pd.concat([df, df.sample(9, random_state=1)])                               # duplicated rows
df["data"] = df["data"].dt.strftime("%d/%m/%Y")
for c in ["valor_bruto", "desconto", "receita", "custo", "frete"]:
    df[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:.2f}".replace(".", ","))
df.to_csv(OUT, sep=";", index=False, encoding="utf-8")
print(f"{len(df):,} linhas → {OUT}")
