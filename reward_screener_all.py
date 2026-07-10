#!/usr/bin/env python3
"""
reward_screener_all.py — run the reward-optimised screener discovery across the WHOLE
warehouse (all 19 ex-US markets from market_data.duckdb) plus US (deep local SEC data),
and print one cross-market verdict table + write reports/reward_screeners.csv.

  MARKET_DB=/path/to/market_data.duckdb python3 reward_screener_all.py --horizon 252

For each market: discovers the optimal conjunctive filter set by cross-validated greedy
search, holds out the later years as a true out-of-sample test, and reports whether the
edge persists. US uses the deep SEC panel (2009-2026, real filing dates); every other
market uses yfinance fundamentals (~2021-2026, filed = fy_end+90d proxy) — so their test
window is short and results there are indicative. Educational/research only.
"""
import argparse
import os

import pandas as pd

import reward_screener_opt as R

# split year per data depth: US is deep (SEC back to 2009); warehouse markets are shallow
US = [("US", "local", 2021)]
WAREHOUSE = [
    "CN",
    "JP",
    "HK",
    "KR",
    "IN",
    "TW",
    "CA",
    "AU",
    "EU",
    "UK",
    "SG",
    "SE",
    "DE",
    "SA",
    "BR",
    "CH",
    "ZA",
    "FI",
    "DK",
]


def _fmt(r):
    return f"{r['med']*100:+5.1f}% / {r['win']*100:2.0f}%" if r else "   —   "


def _screen_str(chosen):
    if not chosen:
        return "(none robust)"
    parts = []
    for f, op, thr, keep in chosen:
        side = "↑" if op == ">=" else "↓"
        parts.append(f"{f}{side}{keep:.0%}")
    return " & ".join(parts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=252)
    ap.add_argument("--max-filters", type=int, default=3)
    ap.add_argument("--wh-split", type=int, default=2023, help="TRAIN cutoff for shallow markets")
    args = ap.parse_args()

    jobs = US + [(m, "warehouse", args.wh_split) for m in WAREHOUSE]
    rows = []
    print(f"\n{'='*96}")
    print(
        f" CROSS-MARKET REWARD-OPTIMISED SCREENERS  —  {args.horizon}d horizon  "
        f"(median_excess / win-rate)"
    )
    print(f"{'='*96}")
    print(
        f" {'mkt':<4}{'tk':>6}{'panel':>8}{'oos_n':>7}  {'TRAIN':>13}  {'OOS/TEST':>13}   "
        f"{'':2}discovered screener"
    )
    print(f" {'-'*92}")
    for mkt, src, split in jobs:
        try:
            res = R.discover(mkt, src, args.horizon, split, args.max_filters)
        except SystemExit as e:
            print(f" {mkt:<4} skipped: {e}")
            continue
        te = res["test"]
        tag = "✅" if res["robust"] else "⚠ "
        print(
            f" {mkt:<4}{res['tickers']:>6}{res['n_panel']:>8}{(te['n'] if te else 0):>7}  "
            f"{_fmt(res['train']):>13}  {_fmt(te):>13} {tag} {_screen_str(res['chosen'])}"
        )
        rows.append(
            {
                "market": mkt,
                "source": src,
                "horizon": args.horizon,
                "split": split,
                "tickers": res["tickers"],
                "panel": res["n_panel"],
                "screener": _screen_str(res["chosen"]),
                "train_med": res["train"]["med"] if res["train"] else None,
                "oos_med": te["med"] if te else None,
                "oos_win": te["win"] if te else None,
                "oos_n": te["n"] if te else 0,
                "per_yr": round(res["per_yr"]),
                "robust": res["robust"],
            }
        )
    print(f"{'='*96}")
    robust = [r for r in rows if r["robust"]]
    print(
        f" ROBUST out-of-sample: {len(robust)}/{len(rows)} markets — "
        f"{', '.join(r['market'] for r in robust) or 'none'}"
    )
    print(f"{'='*96}\n")

    out = os.path.join(R.BASE, "reports")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"reward_screeners_{args.horizon}d.csv")
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f" written → {os.path.relpath(path, R.BASE)}")


if __name__ == "__main__":
    main()
