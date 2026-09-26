#!/usr/bin/env python3
"""
run_backtests.py — lance toutes les stratégies et produit les résultats.

  python3 run_backtests.py                 # frais 0,10 % par défaut
  python3 run_backtests.py --cost 0        # sans frais
  python3 run_backtests.py --start 2008-06 # impose le début de la fenêtre commune

Sorties (dossier results/) :
  summary_common.csv   métriques sur la fenêtre commune (comparables entre elles)
  summary_full.csv     métriques sur l'historique complet de chaque stratégie
  strategies.json      tout ce qu'il faut au site (courbes, poids, métriques)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

import engine
from metrics import drawdown, stats
from strategies_keller import KELLER
from strategies_momentum import MOMENTUM
from strategies_other import OTHER
from strategies_static import STATIC

ROOT = Path(__file__).resolve().parent
ALL = STATIC + MOMENTUM + KELLER + OTHER  # les autres familles viendront s'ajouter ici


def clean(obj):
    """JSON strict (lu par le navigateur) : NaN/inf deviennent null."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    if isinstance(obj, float) and (obj != obj or obj in (float("inf"), float("-inf"))):
        return None
    return obj


def fmt_table(df: pd.DataFrame) -> str:
    show = df[["name", "cagr", "vol", "sharpe", "max_dd", "worst_year", "roll10_min"]].copy()
    for c in ("cagr", "vol", "max_dd", "worst_year", "roll10_min"):
        show[c] = show[c].map(lambda v: f"{v:+.1%}" if pd.notna(v) else "—")
    show["sharpe"] = show["sharpe"].map(lambda v: f"{v:.2f}")
    show.columns = ["Stratégie", "CAGR", "Volat.", "Sharpe", "Max DD", "Pire année", "Pire 10 ans"]
    return show.to_string(index=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data" / "monthly_returns.csv"))
    ap.add_argument("--cost", type=float, default=0.001, help="frais par unité échangée")
    ap.add_argument("--start", help="1er mois de la fenêtre commune (AAAA-MM)")
    ap.add_argument("--only", nargs="+")
    a = ap.parse_args(argv)

    returns = engine.load_returns(a.data)
    rf = engine.cash_series(returns)
    strategies = [s for s in ALL if not a.only or s.id in a.only]
    missing = {s.id: [x for x in s.assets if x not in returns] for s in strategies}
    for sid, m in missing.items():
        if m:
            print(f"⚠️  {sid} ignorée : ETF absents des données {m} "
                  f"(lance : python3 fetch_data.py --only {' '.join(m)})", file=sys.stderr)
    strategies = [s for s in strategies if not missing[s.id]]

    full = {s.id: engine.run(s, returns, cost=a.cost) for s in strategies}
    common_start = (pd.Period(a.start, "M") if a.start
                    else max(r.returns.index[0] for r in full.values()))
    common_end = min(r.returns.index[-1] for r in full.values())

    rows_full, rows_common, site = [], [], []
    for s in strategies:
        r = full[s.id]
        st_full = stats(r.returns, rf)
        st_common = stats(r.returns.loc[common_start:common_end], rf)
        rows_full.append({"id": s.id, "name": s.name, **st_full})
        rows_common.append({"id": s.id, "name": s.name, **st_common})
        eq = r.equity
        site.append({
            "id": s.id, "name": s.name, "family": s.family, "assets": s.assets,
            "rebalance": s.rebalance, "lookback": s.lookback, **s.meta,
            "stats_full": st_full, "stats_common": st_common,
            "equity": {str(k): round(float(v), 5) for k, v in eq.items()},
            "drawdown": {str(k): round(float(v), 5) for k, v in drawdown(r.returns).items()},
            "current_weights": {k: round(float(v), 4)
                                for k, v in r.weights.iloc[-1].items() if abs(v) > 1e-6},
            # signal pour le mois qui commence, calculé sur la dernière clôture mensuelle
            "next_signal": {"for_month": str(returns.index[-1] + 1),
                            "weights": {k: round(float(v), 4)
                                        for k, v in s.weights(returns[s.assets]).items() if v > 1e-6}},
            "avg_turnover_year": float(r.turnover.sum() / (len(r.returns) / 12)),
        })

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    pd.DataFrame(rows_common).to_csv(out / "summary_common.csv", index=False)
    pd.DataFrame(rows_full).to_csv(out / "summary_full.csv", index=False)
    (out / "strategies.json").write_text(json.dumps(clean({
        "common_window": [str(common_start), str(common_end)],
        "cost_per_trade": a.cost,
        "data_end": str(returns.index[-1]),
        "etf_names": {k: v["name"] for k, v in json.loads(
            (ROOT / "universe.json").read_text(encoding="utf-8")).items() if not k.startswith("_")},
        "strategies": site,
    }), ensure_ascii=False, allow_nan=False, default=str), encoding="utf-8")

    site_dir = ROOT / "site"
    if site_dir.exists():  # le site lit sa copie à côté de index.html
        (site_dir / "strategies.json").write_text(
            (out / "strategies.json").read_text(encoding="utf-8"), encoding="utf-8")

    print(f"Fenêtre commune : {common_start} → {common_end}  (frais {a.cost:.2%} par transaction)\n")
    print(fmt_table(pd.DataFrame(rows_common).sort_values("sharpe", ascending=False)))
    print("\nHistorique complet de chaque stratégie :\n")
    df = pd.DataFrame(rows_full)
    df["name"] = df["name"] + " (" + df["start"] + ")"
    print(fmt_table(df.sort_values("sharpe", ascending=False)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
