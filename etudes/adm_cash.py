#!/usr/bin/env python3
"""
etudes/adm_cash.py — Accelerating Dual Momentum : que se passe-t-il si la poche
défensive est du cash (compte épargne) au lieu d'obligations ?

Compare 4 replis défensifs, en dollars et vu d'un investisseur en euros :
  TLT          la version originale (obligations d'État longues)
  TLT ou TIP   la variante du site (la meilleure des deux sur 1 mois)
  Cash         compte épargne : T-bills en dollars / taux de dépôt BCE en euros
  TLT ou cash, TIP ou cash, TLT/TIP/cash : le meilleur sur 1 mois (règles ajoutées a posteriori !)

Lancement, depuis la racine du projet :
  python3 etudes/adm_cash.py
Utilise data/monthly_returns.csv (avec les colonnes EURUSD et ECBDEP pour la vue en euros).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import engine  # noqa: E402
from engine import CASH, Strategy  # noqa: E402
from metrics import stats  # noqa: E402
from strategies_momentum import adm, adm_tip, trailing  # noqa: E402

COST = 0.001
START = "2008-07"


def score(hist):
    return (trailing(hist, 1) + trailing(hist, 3) + trailing(hist, 6)) / 3


def adm_cash(hist):
    s = score(hist)
    best = "SPY" if s["SPY"] >= s["SCZ"] else "SCZ"
    return {best: 1.0} if s[best] > 0 else {CASH: 1.0}


def adm_tlt_or_cash(hist):
    s = score(hist)
    best = "SPY" if s["SPY"] >= s["SCZ"] else "SCZ"
    if s[best] > 0:
        return {best: 1.0}
    r1 = trailing(hist, 1)
    return {"TLT": 1.0} if r1["TLT"] > r1[CASH] else {CASH: 1.0}


def best_1m(defensive):
    """En défensif : l'actif (ou le cash) au meilleur rendement du dernier mois."""
    def w(hist):
        s = score(hist)
        best = "SPY" if s["SPY"] >= s["SCZ"] else "SCZ"
        if s[best] > 0:
            return {best: 1.0}
        r1 = trailing(hist, 1)
        return {max(defensive, key=lambda d: r1[d]): 1.0}
    return w


VARIANTES = [
    ("TLT (originale)", Strategy(id="tlt", name="", assets=["SPY", "SCZ", "TLT"], weights=adm(), lookback=6, family="")),
    ("TLT ou TIP (site)", Strategy(id="tip", name="", assets=["SPY", "SCZ", "TLT", "TIP"], weights=adm_tip(), lookback=6, family="")),
    ("Cash", Strategy(id="cash", name="", assets=["SPY", "SCZ"], weights=adm_cash, lookback=6, family="", uses_cash=True)),
    ("TLT ou cash", Strategy(id="mix", name="", assets=["SPY", "SCZ", "TLT"], weights=adm_tlt_or_cash, lookback=6,
                             family="", uses_cash=True)),
    ("TIP ou cash", Strategy(id="tipc", name="", assets=["SPY", "SCZ", "TIP"], weights=best_1m(["TIP", CASH]), lookback=6,
                             family="", uses_cash=True)),
    ("TLT, TIP ou cash", Strategy(id="all", name="", assets=["SPY", "SCZ", "TLT", "TIP"],
                                  weights=best_1m(["TLT", "TIP", CASH]), lookback=6, family="", uses_cash=True)),
    ("S&P 500", Strategy(id="spy", name="", assets=["SPY"], weights=lambda h: {"SPY": 1.0}, lookback=0, family="")),
]


def main():
    R = engine.load_returns(ROOT / "data" / "monthly_returns.csv")
    rf = engine.cash_series(R)
    fx = R["EURUSD"] if "EURUSD" in R else None
    eur_col = next((c for c in ("ECBDEP", "EUR3M") if c in R), None)
    rf_eur = R[eur_col] if eur_col else pd.Series(0.0, index=R.index)

    def to_eur(res):
        w = res.weights
        idx = w.index.intersection(fx.dropna().index)
        w, f = w.loc[idx], fx.loc[idx]
        assets = [c for c in w.columns if c != CASH]
        risky = (w[assets] * ((1 + R.loc[idx, assets].fillna(0)).div(1 + f, axis=0) - 1)).sum(axis=1)
        return risky + w[CASH] * rf_eur.reindex(idx).fillna(0) - res.costs.loc[idx]

    runs = {n: engine.run(s, R, cost=COST) for n, s in VARIANTES}
    end = min(r.returns.index[-1] for r in runs.values())
    views = [("EN DOLLARS (cash : T-bills américains)", {n: r.returns for n, r in runs.items()}, rf)]
    if fx is not None:
        views.append((f"EN EUROS (cash : compte épargne au taux {eur_col or '0 %'})",
                      {n: to_eur(r) for n, r in runs.items()}, rf_eur))
    for title, series, cash in views:
        rows = []
        for n, r in series.items():
            r = r.loc[START:end]
            st = stats(r, cash)
            y = (1 + r).groupby(r.index.year).prod() - 1
            rows.append({"Variante": n, "CAGR": st["cagr"], "Pire baisse": st["max_dd"], "Sharpe": st["sharpe"],
                         "Sous l'eau (mois)": st["underwater_months"], "Pire année": st["worst_year"],
                         "2008 (dès juil.)": y.get(2008), "2022": y.get(2022)})
        df = pd.DataFrame(rows)
        for c in ("CAGR", "Pire baisse", "Pire année", "2008 (dès juil.)", "2022"):
            df[c] = df[c].map(lambda v: f"{v * 100:+.1f} %" if pd.notna(v) else "—")
        df["Sharpe"] = df["Sharpe"].map(lambda v: f"{v:.2f}")
        print(f"\n{title} — {START} → {end}, frais {COST:.2%}\n")
        print(df.to_string(index=False))
        print("\nCAGR par sous-période :")
        for a, b in [("2008-07", "2014-12"), ("2015-01", "2020-12"), ("2021-01", str(end))]:
            parts = []
            for n, r in series.items():
                x = r.loc[a:b]
                parts.append(f"{n} {((1 + x).prod() ** (12 / len(x)) - 1) * 100:+.1f} %")
            print(f"  {a} → {b} : " + " · ".join(parts))
    w = runs["TLT (originale)"].weights.loc[START:]
    print(f"\nADM passe {(w['TLT'] > 0.5).mean():.0%} des mois en défensif.")


if __name__ == "__main__":
    main()
