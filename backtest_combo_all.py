#!/usr/bin/env python3
"""
backtest_combo_all.py — POINT-IN-TIME price×fundamental COMBO backtest across ALL markets
(the cross-market generalization of backtest_combo_us.py's Darvas×Piotroski test).

Per market it walks the ltm price panel (cache_seed/ltm/<MKT>.parquet) every 21 days from
bar 200, and at each as-of date attaches the latest fundamentals FILED on/before that date
(cache_seed/fundamentals_history/<MKT>.parquet, FUND_HIST_DIR-overridable). It then tests
each PRICE screen alone, the Piotroski F≥7 overlay alone, and each price×F≥7 COMBO —
reporting the winsorized-median forward-return edge vs the market baseline, and whether the
quality overlay IMPROVES the market's best price screen.

Price screens: near_high · rsi_oversold · momentum · darvas (box breakout + volume).
Overlay: piotroski7 = latest known Piotroski F-score ≥ 7.

  python3 backtest_combo_all.py                 # 126d, all markets
  python3 backtest_combo_all.py --horizon 63 --markets IN,JP,KR
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

import backtest  # _pit() + SCREENS

BASE = os.path.expanduser("~/Downloads/code/python_files")
FUND_DIR = os.environ.get("FUND_HIST_DIR") or os.path.join(
    BASE, "cache_seed", "fundamentals_history"
)
LTM = os.environ.get("LTM_DIR") or os.path.join(BASE, "cache_seed", "ltm")
PRICE_SCREENS = ["near_high", "rsi_oversold", "momentum"]  # from backtest.SCREENS + darvas

try:  # prefer the DuckDB warehouse; fall back to parquets
    import warehouse as _wh

    _USE_WH = os.path.exists(_wh.DB)
except Exception:
    _USE_WH = False


def _fscore_by_ticker(market):
    """{ticker: (filed_dates_sorted, F_values)} for point-in-time overlay lookup."""
    if _USE_WH:
        if market not in _wh.markets():
            return {}
        df = _wh.fundamentals(market).sort_values(["ticker", "fy_end"]).copy()
    else:
        fp = os.path.join(FUND_DIR, f"{market}.parquet")
        if not os.path.exists(fp):
            return {}
        df = pd.read_parquet(fp).sort_values(["ticker", "fy_end"]).copy()
    for c in [
        "net_income",
        "revenue",
        "gross_profit",
        "cfo",
        "total_assets",
        "current_assets",
        "current_liabilities",
        "long_term_debt",
        "shares",
    ]:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df["long_term_debt"] = df["long_term_debt"].fillna(0)
    g = df.groupby("ticker")

    def p(c):
        return g[c].shift(1)

    ta, ta1 = df["total_assets"], p("total_assets")
    ni, cfo = df["net_income"], df["cfo"]
    roa, roa1 = ni / ta, p("net_income") / ta1
    lev, lev1 = df["long_term_debt"] / ta, p("long_term_debt") / ta1
    cr = df["current_assets"] / df["current_liabilities"]
    cr1 = p("current_assets") / p("current_liabilities")
    sh, sh1 = df["shares"], p("shares")
    gm, gm1 = df["gross_profit"] / df["revenue"], p("gross_profit") / p("revenue")
    at, at1 = df["revenue"] / ta, p("revenue") / ta1
    df["F"] = (
        (roa > 0).astype(float)
        + (cfo > 0).astype(float)
        + (roa > roa1).astype(float)
        + ((cfo / ta) > roa).astype(float)
        + (lev < lev1).astype(float)
        + (cr > cr1).astype(float)
        + (sh <= sh1 * 1.02).astype(float)
        + (gm > gm1).astype(float)
        + (at > at1).astype(float)
    )
    df["F"] = np.where(ta1.notna() & (ta1 != 0), df["F"], np.nan)
    df["filed_dt"] = pd.to_datetime(df["filed"], errors="coerce")
    df = df.dropna(subset=["filed_dt", "F"])
    out = {}
    for tk, grp in df.sort_values("filed_dt").groupby("ticker"):
        out[str(tk).upper()] = (grp["filed_dt"].to_numpy(), grp["F"].to_numpy())
    return out


def _darvas(high, vol, close, t, box=60, volmult=1.2):
    if t < box + 1:
        return False
    box_top = np.max(high[t - box : t])
    avgv = np.mean(vol[t - 20 : t])
    return bool(
        close[t] > box_top and close[t - 1] <= box_top and avgv > 0 and vol[t] > volmult * avgv
    )


def _f_asof(fd, date_t):
    filed, F = fd
    i = int(np.searchsorted(filed, np.datetime64(date_t), side="right")) - 1
    return F[i] if i >= 0 else np.nan


def backtest_market(market, horizon, step=21):
    fund = _fscore_by_ticker(market)
    if not fund:
        return None
    if _USE_WH:
        px = _wh.prices(market)
    else:
        lp = os.path.join(LTM, f"{market}.parquet")
        if not os.path.exists(lp):
            return None
        px = pd.read_parquet(lp, columns=["Date", "High", "Close", "Volume", "Symbol"])
    px["Date"] = pd.to_datetime(px["Date"])
    px["Symbol"] = px["Symbol"].astype(str).str.upper()
    px = px.sort_values(["Symbol", "Date"])
    screens = ["darvas"] + PRICE_SCREENS
    labels = screens + ["piotroski7"] + [f"{s}×F7" for s in screens]
    fwd_all, picks = [], {label: [] for label in labels}
    for sym, grp in px.groupby("Symbol"):
        n = len(grp)
        if n < 200 + horizon + 1:
            continue
        dates = grp["Date"].to_numpy()
        close = grp["Close"].to_numpy("float64")
        high = grp["High"].to_numpy("float64")
        vol = grp["Volume"].to_numpy("float64")
        fd = fund.get(sym)
        for t in range(200, n - horizon - 1, step):
            if not close[t] or not np.isfinite(close[t]):
                continue
            fwd = close[t + horizon] / close[t] - 1
            if not np.isfinite(fwd):
                continue
            idx = len(fwd_all)
            fwd_all.append(fwd)
            f = backtest._pit(close, t)
            if not f:
                continue
            flags = {
                "darvas": _darvas(high, vol, close, t),
                "near_high": f["pct_from_high"] >= -3,
                "rsi_oversold": f["rsi"] < 30,
                "momentum": f["ret126"] > 25 and f["sma50"] > f["sma200"],
            }
            F = _f_asof(fd, dates[t]) if fd is not None else np.nan
            flags["piotroski7"] = bool(np.isfinite(F) and F >= 7)
            for s in screens:
                flags[f"{s}×F7"] = flags[s] and flags["piotroski7"]
            for label, on in flags.items():
                if on:
                    picks[label].append(idx)
    arr = np.array(fwd_all, float)
    if len(arr) < 200:
        return None
    lo, hi = np.nanpercentile(arr, [1, 99])
    base_med = float(np.nanmedian(arr))
    res = {"market": market, "windows": len(arr), "base": base_med * 100}
    for label in labels:
        ix = picks[label]
        res[label] = (float(np.nanmedian(arr[ix])) - base_med) * 100 if len(ix) >= 20 else None
        res[label + "_n"] = len(ix)
    return res


def main():
    ap = argparse.ArgumentParser(description="Cross-market price×fundamental combo backtest")
    ap.add_argument("--horizon", type=int, default=126)
    ap.add_argument("--markets", default="")
    args = ap.parse_args()
    markets = (
        [m.strip().upper() for m in args.markets.split(",")]
        if args.markets
        else (
            _wh.markets()
            if _USE_WH
            else sorted(os.path.basename(p)[:-8] for p in glob.glob(f"{FUND_DIR}/*.parquet"))
        )
    )
    print(f"Cross-market price×fundamental combo — {args.horizon}d forward, point-in-time")
    print("  median edge (pp); does the F≥7 overlay improve the market's best price screen?\n")
    print(
        "  "
        + "Mkt".rjust(4)
        + "BestPrice".rjust(16)
        + "edge".rjust(7)
        + "  →  "
        + "same×F≥7".rjust(9)
        + "Δ".rjust(7)
    )
    rows = []
    screens = ["darvas", "near_high", "rsi_oversold", "momentum"]
    for m in markets:
        r = backtest_market(m, args.horizon)
        if not r:
            print(f"  {m:>4}  (insufficient data)")
            continue
        rows.append(r)
        # the market's best PRICE screen, and that screen's ×F7 combo
        pr = {s: r[s] for s in screens if r.get(s) is not None}
        if not pr:
            continue
        best = max(pr, key=pr.get)
        combo = r.get(f"{best}×F7")
        delta = (combo - r[best]) if (combo is not None) else None
        arrow = f"{combo:+.1f}" if combo is not None else "n<20"
        dtxt = f"{delta:+.1f}" if delta is not None else ""
        print(f"  {m:>4}{best:>16}{r[best]:>+7.1f}  →  {arrow:>9}{dtxt:>7}")

    if rows:
        df = pd.DataFrame(rows)
        # how often does adding F≥7 to the best price screen help?
        helped = 0
        tot = 0
        for r in rows:
            pr = {s: r[s] for s in screens if r.get(s) is not None}
            if not pr:
                continue
            best = max(pr, key=pr.get)
            c = r.get(f"{best}×F7")
            if c is not None:
                tot += 1
                helped += c > r[best]
        print(f"\n  F≥7 overlay improved the best price screen in {helped}/{tot} markets.")
        print(
            "  darvas×F7 avg edge: "
            f"{np.nanmean([r['darvas×F7'] for r in rows if r.get('darvas×F7') is not None]):+.1f}pp"
            f" (vs darvas {np.nanmean([r['darvas'] for r in rows if r.get('darvas') is not None]):+.1f})"
        )
        out = os.path.join(BASE, "data", "curated", "combo_backtest_all.parquet")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        df.to_parquet(out, index=False)
        print(f"  → {os.path.relpath(out, BASE)}")


if __name__ == "__main__":
    main()
