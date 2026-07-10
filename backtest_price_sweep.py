#!/usr/bin/env python3
"""
backtest_price_sweep.py — run the repo's walk-forward price screens (backtest.SCREENS
+ backtest._pit, point-in-time) across MANY markets and assemble one comparison matrix,
extending BACKTEST_FINDINGS.md (US/KR/IN/CN/JP) to the 15 never-run markets.

Robustness fix over a naive backtest.py sweep: the raw ltm price panels contain
penny-stock / unadjusted-price artifacts (e.g. ZA/UK show +100s of %% "market" 21d
returns). We therefore WINSORIZE forward returns to the market's 1st–99th pct and
report BOTH a winsorized-mean edge and an outlier-proof MEDIAN edge — the same
treatment the fundamental backtests use.

Single pass per market: compute _pit() features once per (symbol, as-of t), evaluate
all 5 screens, and pair each pick's forward return against the equal-weight baseline
(all eligible names at the same as-of windows).

  python3 backtest_price_sweep.py                    # the 15 un-run markets
  python3 backtest_price_sweep.py --markets EU,UK,DE
  python3 backtest_price_sweep.py --all --horizon 21
"""
import argparse
import os

import numpy as np
import pandas as pd

import backtest

BASE = os.path.expanduser("~/Downloads/code/python_files")
OUT = os.path.join(BASE, "results", "price_sweep.csv")
DONE = ["US", "KR", "IN", "CN", "JP"]  # already in BACKTEST_FINDINGS.md
SCREEN_ORDER = ["rsi_oversold", "near_high", "momentum", "golden_state", "golden_crossover"]

try:
    import datalink
except Exception:
    datalink = None


def _all_markets():
    d = os.path.join(BASE, "cache_seed", "ltm")
    return sorted(f[:-8] for f in os.listdir(d) if f.endswith(".parquet"))


def sweep_market(market, horizon, step=21):
    """One robust pass: returns {screen: metrics} + baseline, all winsorized."""
    data = datalink.load_market(market, tier="ltm") or datalink.load_market(market)
    if not data:
        return None
    screens = backtest.SCREENS
    fwd_all, picks = [], {s: [] for s in screens}
    for df in data.values():
        if df is None or len(df) < 200 + horizon + 1:
            continue
        close = df["Close"].to_numpy("float64")
        n = len(close)
        for t in range(200, n - horizon - 1, step):
            if not close[t]:
                continue
            fwd = (close[t + horizon] / close[t] - 1) * 100
            if not np.isfinite(fwd):
                continue
            idx = len(fwd_all)
            fwd_all.append(fwd)
            f = backtest._pit(close, t)
            if not f:
                continue
            for s, pred in screens.items():
                try:
                    if pred(f):
                        picks[s].append(idx)
                except Exception:
                    pass
    if len(fwd_all) < 50:
        return None
    arr = np.array(fwd_all, float)
    lo, hi = np.nanpercentile(arr, [1, 99])
    arrw = np.clip(arr, lo, hi)  # winsorize the whole market panel
    base_mean, base_med = float(np.nanmean(arrw)), float(np.nanmedian(arr))
    out = {"_baseline": {"mean": base_mean, "median": base_med, "n": len(arr)}}
    for s in screens:
        ix = picks[s]
        if not ix:
            out[s] = {"edge": 0.0, "edge_med": 0.0, "win": 0.0, "trades": 0}
            continue
        pm, pmd = float(np.nanmean(arrw[ix])), float(np.nanmedian(arr[ix]))
        out[s] = {
            "edge": round(pm - base_mean, 2),
            "edge_med": round(pmd - base_med, 2),
            "win": round(float(np.nanmean(arr[ix] > 0)), 3),
            "trades": len(ix),
        }
    return out


def main():
    ap = argparse.ArgumentParser(description="Robust price-screen sweep across markets")
    ap.add_argument("--markets", default="", help="comma list (default: the 15 un-run markets)")
    ap.add_argument("--all", action="store_true", help="all 20 ltm markets")
    ap.add_argument("--horizon", type=int, default=21, help="forward hold days (default 21)")
    args = ap.parse_args()
    if datalink is None:
        raise SystemExit("datalink module unavailable")

    allm = _all_markets()
    if args.markets:
        markets = [m.strip().upper() for m in args.markets.split(",")]
    elif args.all:
        markets = allm
    else:
        markets = [m for m in allm if m not in DONE]

    print(f"Robust price-screen sweep — {args.horizon}d hold — {len(markets)} markets")
    print("  winsorized 1–99pct; edge in pp vs equal-weight baseline\n")

    rows = []
    for m in markets:
        res = sweep_market(m, args.horizon)
        if not res:
            print(f"  {m:<4} (insufficient data)")
            continue
        b = res["_baseline"]
        best = max((s for s in backtest.SCREENS), key=lambda s: res[s]["edge_med"])
        print(
            f"  {m:<4} best(median): {best:<17} {res[best]['edge_med']:+6.2f}pp"
            f"   base_med {b['median']:+.2f}%  n={b['n']:,}"
        )
        for s in backtest.SCREENS:
            rows.append({"market": m, "screen": s, **res[s]})

    df = pd.DataFrame(rows)
    if df.empty:
        print("no results")
        return

    for metric, title in [
        ("edge_med", "MEDIAN edge (pp, outlier-proof)"),
        ("edge", "winsorized-MEAN edge (pp)"),
    ]:
        mat = df.pivot(index="market", columns="screen", values=metric)
        mat = mat[[c for c in SCREEN_ORDER if c in mat.columns]]
        print(f"\n=== {title} — market × screen ===")
        print(mat.round(2).to_string())
        print("  per-screen avg:")
        for s, v in mat.mean().sort_values(ascending=False).items():
            pos = int((mat[s] > 0).sum())
            print(f"    {s:<18}{v:>+7.2f}   (positive in {pos}/{len(mat)})")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"\n  full results → {os.path.relpath(OUT, BASE)} ({len(df)} rows)")


if __name__ == "__main__":
    main()
