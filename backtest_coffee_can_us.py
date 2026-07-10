#!/usr/bin/env python3
"""
backtest_coffee_can_us.py — POINT-IN-TIME backtest of the Coffee Can screen on US
equities (Saurabh Mukherjea: consistent high-ROE compounders, steady revenue growth,
low leverage), using SEC-EDGAR historical financials + the stored 10y OHLCV. Sister
to backtest_piotroski_us.py.

Screen (matches strategies/coffee_can.py), evaluated at each fiscal year point-in-time:
  • ROE >= 15%              (net_income / equity)
  • ROE consistent          (trailing 5y all >= 15%, ≥4 yrs present)
  • Revenue CAGR 5y >= 10%  ((rev_t / rev_{t-5})^(1/5) − 1)
  • Debt/Equity <= 1        (long_term_debt / equity)
PASS = all four. We report PASS vs FAIL vs baseline forward returns, plus a gradient
by how many of the four criteria are met.

Entry = first trading day after the 10-K `filed` date (no look-ahead); exit = HORIZON
trading days later, priced from cache_seed/ltm/US.parquet.

Educational/research only. Survivorship caveat: ltm holds only currently-listed names,
which flatters a buy-and-hold quality screen especially.

  python3 backtest_coffee_can_us.py                 # 252-day (~1y) — Coffee Can is long-hold
  python3 backtest_coffee_can_us.py --horizon 504   # ~2y
"""
import argparse
import os

import numpy as np
import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
HIST = os.path.join(
    os.environ.get("FUND_HIST_DIR") or os.path.join(BASE, "cache_seed", "fundamentals_history"),
    "US.parquet",
)
PRICES = os.path.join(BASE, "cache_seed", "ltm", "US.parquet")

ROE_MIN, REV_CAGR_MIN, DE_MAX = 15.0, 10.0, 1.0


def _coffee_can(df):
    df = df.sort_values(["ticker", "fy_end"]).copy()
    for c in ["net_income", "equity", "revenue", "long_term_debt"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["roe"] = np.where(df["equity"] > 0, df["net_income"] / df["equity"] * 100, np.nan)
    df["de"] = np.where(df["equity"] > 0, df["long_term_debt"] / df["equity"], np.nan)
    g = df.groupby("ticker")
    # trailing-5y ROE consistency (all present years >= 15, need >=4 present)
    roe_min5 = g["roe"].transform(lambda s: s.rolling(5, min_periods=4).min())
    roe_cnt5 = g["roe"].transform(lambda s: s.rolling(5, min_periods=4).count())
    df["roe_consistent"] = (roe_min5 >= ROE_MIN) & (roe_cnt5 >= 4)
    rev5 = g["revenue"].shift(5)
    df["rev_cagr5"] = (
        np.where((rev5 > 0) & (df["revenue"] > 0), (df["revenue"] / rev5) ** (1 / 5) - 1, np.nan)
        * 100
    )

    c_roe = df["roe"] >= ROE_MIN
    c_cons = df["roe_consistent"]
    c_rev = df["rev_cagr5"] >= REV_CAGR_MIN
    c_de = df["de"] <= DE_MAX
    df["n_criteria"] = (
        c_roe.astype(float) + c_cons.astype(float) + c_rev.astype(float) + c_de.astype(float)
    )
    df["PASS"] = c_roe & c_cons & c_rev & c_de
    # a row is only evaluable once the 5y window + D/E exist
    ok = df["rev_cagr5"].notna() & df["de"].notna() & roe_cnt5.ge(4)
    return df[ok].copy()


def _forward_returns(scored, horizon):
    px = pd.read_parquet(PRICES, columns=["Date", "Close", "Symbol"])
    px["Date"] = pd.to_datetime(px["Date"])
    px["Symbol"] = px["Symbol"].astype(str).str.upper()
    px = px.sort_values(["Symbol", "Date"])
    by_sym = {
        s: (grp["Date"].to_numpy(), grp["Close"].to_numpy()) for s, grp in px.groupby("Symbol")
    }
    fwd = []
    for _, r in scored.iterrows():
        arr = by_sym.get(str(r["ticker"]).upper())
        if arr is None or not r.get("filed") or str(r["filed"]) == "9999-99-99":
            fwd.append(np.nan)
            continue
        dates, closes = arr
        entry_dt = np.datetime64(str(r["filed"])) + np.timedelta64(1, "D")
        i = int(np.searchsorted(dates, entry_dt))
        j = i + horizon
        fwd.append(closes[j] / closes[i] - 1.0 if (j < len(dates) and closes[i] > 0) else np.nan)
    scored = scored.copy()
    scored["fwd"] = fwd
    return scored.dropna(subset=["fwd"])


def main():
    ap = argparse.ArgumentParser(description="Point-in-time Coffee Can backtest (US)")
    ap.add_argument(
        "--horizon", type=int, default=252, help="forward trading days (default 252≈1y)"
    )
    args = ap.parse_args()
    if not os.path.exists(HIST):
        raise SystemExit(f"missing {HIST} — run sec_history_collector.py first")

    scored = _forward_returns(_coffee_can(pd.read_parquet(HIST)), args.horizon)
    lo_c, hi_c = scored["fwd"].quantile([0.01, 0.99]).to_numpy()
    scored["fwd_w"] = scored["fwd"].clip(lo_c, hi_c)
    base, base_med = scored["fwd_w"].mean(), scored["fwd"].median()

    print(f"Coffee Can backtest — US — {args.horizon}-day forward, point-in-time")
    print(
        f"  scored rows: {len(scored):,} | tickers: {scored['ticker'].nunique()} "
        f"| years: {pd.to_datetime(scored['fy_end']).dt.year.min()}–{pd.to_datetime(scored['fy_end']).dt.year.max()}"
    )
    print(f"  baseline (winsorized mean {base*100:+.2f}% | median {base_med*100:+.2f}%)\n")
    print(
        f"  {'group':<14}{'n':>7}{'wins.mean%':>11}{'edge pp':>9}{'median%':>10}{'edge pp':>9}{'win%':>7}"
    )

    def line(label, sub):
        if len(sub):
            m, md = sub["fwd_w"].mean(), sub["fwd"].median()
            print(
                f"  {label:<14}{len(sub):>7,}{m*100:>10.2f}%{(m-base)*100:>+8.2f}"
                f"{md*100:>9.2f}%{(md-base_med)*100:>+8.2f}{(sub['fwd']>0).mean()*100:>6.1f}%"
            )

    line("PASS (all 4)", scored[scored["PASS"]])
    line("FAIL", scored[~scored["PASS"]])
    print("\n  by # criteria met:")
    for k in [4, 3, 2, 1, 0]:
        line(f"  {k}/4", scored[scored["n_criteria"] == k])


if __name__ == "__main__":
    main()
