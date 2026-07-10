#!/usr/bin/env python3
"""
backtest_magic_formula_us.py — POINT-IN-TIME backtest of Joel Greenblatt's Magic
Formula on US equities, using SEC-EDGAR historical financials + the stored 10y OHLCV.
Sister to backtest_piotroski_us.py.

Magic Formula is a cross-sectional RANKING strategy, so this backtests it as such:
  • Earnings Yield  EY = EBIT / EV,   EV = market_cap + long_term_debt
      market_cap = shares × entry price  (price on the entry day — see below)
  • Return on Capital  ROC = EBIT / (total_assets − current_liabilities)
      (= EBIT / capital-employed; the Greenblatt NWC+net-fixed-assets denominator)
  • Combined rank = rank(EY, desc) + rank(ROC, desc), ranked WITHIN each filing-year
    cohort (cross-sectional, as Greenblatt intends). Lower combined rank = better.
  • Bucket each cohort into deciles by combined rank; report forward return per decile.
    D1 = the Magic-Formula portfolio (cheap AND good); D10 = expensive AND low-quality.

Entry = first trading day after the 10-K `filed` date (no look-ahead); market cap and
the exit are both taken from that entry day forward (cache_seed/ltm/US.parquet), so EY
uses a genuinely as-of price. Exit = HORIZON trading days later.

Educational/research only. Survivorship caveat: ltm holds only currently-listed names.

  python3 backtest_magic_formula_us.py                 # 252-day (~1y) horizon
  python3 backtest_magic_formula_us.py --horizon 126
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


def _attach_entry_and_fwd(df, horizon):
    """For each row: entry price (day after `filed`) + forward return to +horizon."""
    px = pd.read_parquet(PRICES, columns=["Date", "Close", "Symbol"])
    px["Date"] = pd.to_datetime(px["Date"])
    px["Symbol"] = px["Symbol"].astype(str).str.upper()
    px = px.sort_values(["Symbol", "Date"])
    by_sym = {
        s: (grp["Date"].to_numpy(), grp["Close"].to_numpy()) for s, grp in px.groupby("Symbol")
    }
    entry_px, fwd = [], []
    for _, r in df.iterrows():
        arr = by_sym.get(str(r["ticker"]).upper())
        if arr is None or not r.get("filed") or str(r["filed"]) == "9999-99-99":
            entry_px.append(np.nan)
            fwd.append(np.nan)
            continue
        dates, closes = arr
        entry_dt = np.datetime64(str(r["filed"])) + np.timedelta64(1, "D")
        i = int(np.searchsorted(dates, entry_dt))
        j = i + horizon
        if i < len(dates) and closes[i] > 0:
            entry_px.append(closes[i])
            fwd.append(closes[j] / closes[i] - 1.0 if j < len(dates) else np.nan)
        else:
            entry_px.append(np.nan)
            fwd.append(np.nan)
    df = df.copy()
    df["entry_px"], df["fwd"] = entry_px, fwd
    return df.dropna(subset=["entry_px", "fwd"])


def _magic(df, horizon):
    df = df.copy()
    for c in ["ebit", "long_term_debt", "shares", "total_assets", "current_liabilities"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["ebit", "shares", "total_assets", "current_liabilities"])
    df = _attach_entry_and_fwd(df, horizon)
    df["mcap"] = df["shares"] * df["entry_px"]
    df["ev"] = df["mcap"] + df["long_term_debt"].fillna(0)
    df["cap_emp"] = df["total_assets"] - df["current_liabilities"]
    df = df[(df["ev"] > 0) & (df["cap_emp"] > 0) & (df["ebit"].notna())]
    df["ey"] = df["ebit"] / df["ev"]
    df["roc"] = df["ebit"] / df["cap_emp"]
    # cross-sectional combined rank within each filing-year cohort
    df["cohort"] = pd.to_datetime(df["filed"]).dt.year
    df["r_ey"] = df.groupby("cohort")["ey"].rank(ascending=False)
    df["r_roc"] = df.groupby("cohort")["roc"].rank(ascending=False)
    df["mf_rank"] = df["r_ey"] + df["r_roc"]
    df["decile"] = df.groupby("cohort")["mf_rank"].transform(
        lambda s: pd.qcut(s.rank(method="first"), 10, labels=False, duplicates="drop") + 1
    )
    return df


def main():
    ap = argparse.ArgumentParser(description="Point-in-time Magic Formula backtest (US)")
    ap.add_argument(
        "--horizon", type=int, default=252, help="forward trading days (default 252≈1y)"
    )
    args = ap.parse_args()
    if not os.path.exists(HIST):
        raise SystemExit(f"missing {HIST} — run sec_history_collector.py first")

    df = _magic(pd.read_parquet(HIST), args.horizon)
    lo_c, hi_c = df["fwd"].quantile([0.01, 0.99]).to_numpy()
    df["fwd_w"] = df["fwd"].clip(lo_c, hi_c)
    base, base_med = df["fwd_w"].mean(), df["fwd"].median()

    print(f"Magic Formula backtest — US — {args.horizon}-day forward, point-in-time")
    print(
        f"  scored rows: {len(df):,} | tickers: {df['ticker'].nunique()} "
        f"| cohorts: {int(df['cohort'].min())}–{int(df['cohort'].max())}"
    )
    print(f"  baseline (winsorized mean {base*100:+.2f}% | median {base_med*100:+.2f}%)\n")
    print(
        f"  {'decile':<10}{'n':>7}{'wins.mean%':>11}{'edge pp':>9}{'median%':>10}{'edge pp':>9}{'win%':>7}"
    )
    for d in range(1, 11):
        sub = df[df["decile"] == d]
        if len(sub):
            m, md = sub["fwd_w"].mean(), sub["fwd"].median()
            tag = "D1 = MF port" if d == 1 else ("D10 = worst" if d == 10 else "")
            print(
                f"  D{d:<9}{len(sub):>7,}{m*100:>10.2f}%{(m-base)*100:>+8.2f}"
                f"{md*100:>9.2f}%{(md-base_med)*100:>+8.2f}{(sub['fwd']>0).mean()*100:>6.1f}%  {tag}"
            )
    top, bot = df[df["decile"] == 1], df[df["decile"] == 10]
    if len(top) and len(bot):
        spread = (top["fwd_w"].mean() - bot["fwd_w"].mean()) * 100
        print(f"\n  D1−D10 winsorized-mean spread: {spread:+.2f} pp")


if __name__ == "__main__":
    main()
