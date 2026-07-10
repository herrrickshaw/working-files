#!/usr/bin/env python3
"""
backtest_combo_us.py — POINT-IN-TIME backtest of PRICE screens × screener.in-style
FUNDAMENTAL screens and their COMBINATIONS on US equities. Tests the key hypothesis
from herrrickshaw/global-market-scanners: Piotroski works as a QUALITY OVERLAY on
breakout (Darvas) names even though it is inverted as a standalone signal.

Method (no look-ahead):
  • Walk forward the US price panel (cache_seed/ltm/US.parquet) every `step` days from
    bar 200. At each (symbol, as-of t) compute PRICE screens from bars ≤ t, and attach
    the FUNDAMENTALS from the latest 10-K FILED on or before date_t (SEC-EDGAR history,
    cache_seed/fundamentals_history/US.parquet — `filed` date = when it became public).
  • Forward return = close[t+horizon]/close[t] − 1, winsorized 1–99pct market-wide.
  • Report each screen (and combo) vs the equal-weight baseline: winsorized-mean edge,
    outlier-proof MEDIAN edge, and win-rate.

Screens
  price       : darvas (box breakout+vol), near_high, rsi_oversold
  fundamental : piotroski7 (F≥7), magic (EY≥8% & ROC≥15%), quality (ROCE≥15 & D/E≤1),
                lowdebt (LT-debt fell YoY), garp (PEG≤1 & growth≥15%), net_net (mcap<NCAV)
  combos      : darvas×piotroski7, darvas×magic, darvas×quality,
                near_high×piotroski7, rsi_oversold×piotroski7
(CCC and Bull-Cartel are omitted — SEC history lacks inventory/receivables/payables and
quarterly series; those screener.in screens are only computable on the India data.)

Educational/research only. Survivorship: ltm holds only currently-listed names.

  python3 backtest_combo_us.py                 # 126-day (~6mo) horizon
  python3 backtest_combo_us.py --horizon 252
"""
import argparse
import os

import numpy as np
import pandas as pd

import backtest  # reuse _pit() for sma/rsi/near_high price features

BASE = os.path.expanduser("~/Downloads/code/python_files")
HIST = os.path.join(
    os.environ.get("FUND_HIST_DIR") or os.path.join(BASE, "cache_seed", "fundamentals_history"),
    "US.parquet",
)
PRICES = os.path.join(BASE, "cache_seed", "ltm", "US.parquet")

PRICE_SCREENS = ["darvas", "near_high", "rsi_oversold"]
FUND_SCREENS = ["piotroski7", "magic", "quality", "lowdebt", "garp", "net_net"]
COMBOS = [
    ("darvas", "piotroski7"),
    ("darvas", "magic"),
    ("darvas", "quality"),
    ("near_high", "piotroski7"),
    ("rsi_oversold", "piotroski7"),
]


def _fundamentals_by_ticker():
    """Precompute point-in-time fundamental metrics per (ticker, filed). Returns
    {ticker: {'filed': datetime64[], metric: float[]}} sorted by filed date."""
    df = pd.read_parquet(HIST).sort_values(["ticker", "fy_end"]).copy()
    for c in [
        "net_income",
        "equity",
        "revenue",
        "cfo",
        "ebit",
        "total_assets",
        "current_assets",
        "current_liabilities",
        "long_term_debt",
        "shares",
        "gross_profit",
    ]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    g = df.groupby("ticker")

    def prev(c):
        return g[c].shift(1)

    ta, ta1 = df["total_assets"], prev("total_assets")
    ni, eq = df["net_income"], df["equity"]
    roa, roa1 = ni / ta, prev("net_income") / ta1
    cfo = df["cfo"]
    cr = df["current_assets"] / df["current_liabilities"]
    cr1 = prev("current_assets") / prev("current_liabilities")
    ltd, ltd1 = df["long_term_debt"], prev("long_term_debt")
    lev, lev1 = ltd / ta, ltd1 / ta1
    sh, sh1 = df["shares"], prev("shares")
    gm = df["gross_profit"] / df["revenue"]
    gm1 = prev("gross_profit") / prev("revenue")
    at, at1 = df["revenue"] / ta, prev("revenue") / ta1
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
    df.loc[ta1.isna(), "F"] = np.nan
    cap_emp = df["total_assets"] - df["current_liabilities"]
    df["roce"] = np.where(cap_emp > 0, df["ebit"] / cap_emp * 100, np.nan)
    df["de"] = np.where(eq > 0, ltd / eq, np.nan)
    df["lowdebt"] = (ltd < ltd1).astype(float)
    rev5 = g["revenue"].shift(5)
    df["rev_cagr5"] = (
        np.where((rev5 > 0) & (df["revenue"] > 0), (df["revenue"] / rev5) ** (1 / 5) - 1, np.nan)
        * 100
    )
    ni5 = g["net_income"].shift(5)
    df["ni_cagr5"] = np.where((ni5 > 0) & (ni > 0), (ni / ni5) ** (1 / 5) - 1, np.nan) * 100
    df["total_liab"] = df["total_assets"] - eq
    df["filed_dt"] = pd.to_datetime(df["filed"], errors="coerce")
    df = df.dropna(subset=["filed_dt"])

    cols = [
        "F",
        "roce",
        "de",
        "lowdebt",
        "rev_cagr5",
        "ni_cagr5",
        "ebit",
        "long_term_debt",
        "current_assets",
        "total_liab",
        "net_income",
        "shares",
    ]
    out = {}
    for tk, grp in df.sort_values("filed_dt").groupby("ticker"):
        out[tk] = {"filed": grp["filed_dt"].to_numpy()}
        for c in cols:
            out[tk][c] = grp[c].to_numpy("float64")
    return out


def _darvas(high, vol, close, t, box=60, volmult=1.2):
    """Fresh box breakout at t: close clears the prior-`box`-bar high (current bar
    excluded) on ≥volmult × 20d avg volume, and last bar was still inside the box."""
    if t < box + 1:
        return False
    box_top = np.max(high[t - box : t])  # excludes current bar t
    avgv = np.mean(vol[t - 20 : t])
    return bool(
        close[t] > box_top and close[t - 1] <= box_top and avgv > 0 and vol[t] > volmult * avgv
    )


def _fund_flags(fd, date_t, price):
    """Latest 10-K filed ≤ date_t → dict of fundamental screen booleans (price-aware)."""
    fl = {s: False for s in FUND_SCREENS}
    i = int(np.searchsorted(fd["filed"], np.datetime64(date_t), side="right")) - 1
    if i < 0:
        return fl
    F, roce, de = fd["F"][i], fd["roce"][i], fd["de"][i]
    lowdebt = fd["lowdebt"][i]
    nig = fd["ni_cagr5"][i]
    ebit, ltd = fd["ebit"][i], fd["long_term_debt"][i]
    ca, tl = fd["current_assets"][i], fd["total_liab"][i]
    ni, sh = fd["net_income"][i], fd["shares"][i]
    if not (sh and sh > 0):
        return fl
    mcap = sh * price
    ev = mcap + (ltd if np.isfinite(ltd) else 0)
    fl["piotroski7"] = bool(np.isfinite(F) and F >= 7)
    fl["quality"] = bool(np.isfinite(roce) and roce >= 15 and np.isfinite(de) and de <= 1)
    fl["lowdebt"] = bool(lowdebt == 1)
    if ev > 0 and np.isfinite(ebit):
        ey = ebit / ev
        fl["magic"] = bool(ey >= 0.08 and np.isfinite(roce) and roce >= 15)
    if ni and ni > 0 and np.isfinite(nig) and nig >= 15:
        eps = ni / sh
        pe = price / eps if eps > 0 else np.inf
        fl["garp"] = bool(pe <= nig)  # PEG = pe/growth ≤ 1
    if np.isfinite(tl):
        ncav = ca - tl
        fl["net_net"] = bool(ncav > 0 and mcap < ncav)
    return fl


def main():
    ap = argparse.ArgumentParser(description="Point-in-time price×fundamental combo backtest (US)")
    ap.add_argument(
        "--horizon", type=int, default=126, help="forward trading days (default 126≈6mo)"
    )
    ap.add_argument("--step", type=int, default=21, help="days between as-of windows")
    args = ap.parse_args()
    for p in (HIST, PRICES):
        if not os.path.exists(p):
            raise SystemExit(f"missing {p}")

    print("loading fundamentals…")
    fund = _fundamentals_by_ticker()
    print(f"  {len(fund)} tickers with SEC history")

    px = pd.read_parquet(PRICES, columns=["Date", "High", "Close", "Volume", "Symbol"])
    px["Date"] = pd.to_datetime(px["Date"])
    px["Symbol"] = px["Symbol"].astype(str).str.upper()
    px = px.sort_values(["Symbol", "Date"])

    all_screens = PRICE_SCREENS + FUND_SCREENS + [f"{a}×{b}" for a, b in COMBOS]
    fwd_all = []
    picks = {s: [] for s in all_screens}
    h, step = args.horizon, args.step

    for sym, grp in px.groupby("Symbol"):
        n = len(grp)
        if n < 200 + h + 1:
            continue
        dates = grp["Date"].to_numpy()
        close = grp["Close"].to_numpy("float64")
        high = grp["High"].to_numpy("float64")
        vol = grp["Volume"].to_numpy("float64")
        fd = fund.get(sym)
        for t in range(200, n - h - 1, step):
            if not close[t] or not np.isfinite(close[t]):
                continue
            fwd = close[t + h] / close[t] - 1
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
            }
            if fd is not None:
                flags.update(_fund_flags(fd, dates[t], close[t]))
            else:
                flags.update({s: False for s in FUND_SCREENS})
            for a, b in COMBOS:
                flags[f"{a}×{b}"] = flags.get(a, False) and flags.get(b, False)
            for s, on in flags.items():
                if on:
                    picks[s].append(idx)

    arr = np.array(fwd_all, float)
    lo, hi = np.nanpercentile(arr, [1, 99])
    arrw = np.clip(arr, lo, hi)
    base, base_med = float(np.nanmean(arrw)), float(np.nanmedian(arr))
    print(f"\nCombo backtest — US — {h}-day forward, point-in-time")
    print(
        f"  windows: {len(arr):,} | baseline winsorized-mean {base*100:+.2f}% · median {base_med*100:+.2f}%\n"
    )
    print(
        f"  {'screen':<22}{'n':>8}{'wins.mean%':>11}{'edge':>8}{'median%':>10}{'edge':>8}{'win%':>7}"
    )

    rows = []
    for s in all_screens:
        ix = picks[s]
        if len(ix) < 30:
            rows.append((s, len(ix), None, None, None, None))
            continue
        m, md = float(np.nanmean(arrw[ix])), float(np.nanmedian(arr[ix]))
        win = float(np.nanmean(arr[ix] > 0))
        rows.append((s, len(ix), m, m - base, md, md - base_med, win))

    def emit(title, names):
        print(f"\n  ── {title} ──")
        for r in rows:
            if r[0] not in names:
                continue
            if r[2] is None:
                print(f"  {r[0]:<22}{r[1]:>8}   (n<30 — skipped)")
                continue
            s, n_, m, ed, md, edm, win = r
            print(
                f"  {s:<22}{n_:>8}{m*100:>10.2f}%{ed*100:>+7.2f}{md*100:>9.2f}%{edm*100:>+7.2f}{win*100:>6.1f}%"
            )

    emit("PRICE screens", PRICE_SCREENS)
    emit("FUNDAMENTAL screens (screener.in-style)", FUND_SCREENS)
    emit("COMBINATIONS (price × fundamental)", [f"{a}×{b}" for a, b in COMBOS])


if __name__ == "__main__":
    main()
