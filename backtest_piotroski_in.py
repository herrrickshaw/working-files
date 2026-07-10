#!/usr/bin/env python3
"""
backtest_piotroski_in.py — POINT-IN-TIME(-ish) backtest of the Piotroski F-Score on
INDIAN equities, using screener.in historical annual financials
(cache_seed/fundamentals_history/IN.parquet, from screener_history_collector.py) +
the stored 10-year OHLCV (cache_seed/ltm/IN.parquet). The India analogue of
backtest_piotroski_us.py.

Method:
  • F-score per (ticker, fiscal-year) from year vs year-1. Balance-sheet totals are
    derived from screener.in components:
        equity        = equity_capital + reserves
        total_assets  = equity + borrowings + other_liab
    Two of the nine signals are APPROXIMATED because screener.in's export does not
    split current items or report gross profit:
        F6 current-ratio  → (inventory+receivables+cash) / other_liab  (proxy)
        F8 margin         → net margin (net_income/revenue)  instead of gross margin
  • ENTRY: screener.in gives the fiscal period-end but NOT a filing date. Indian
    issuers file audited annuals within ~60 days of FY-end (SEBI LODR); we enter
    fy_end + LAG calendar days (default 90) as a conservative no-look-ahead proxy.
    EXIT = HORIZON trading days later, priced from ltm/IN.parquet. Bonus/split years
    can spuriously trip the share-issuance signal (F7 uses a 2% tolerance).

Educational/research only. As-restated (not true PIT) + survivorship: ltm holds only
currently-listed names. Trust sign/ordering across F-bands, not absolute levels.

  python3 backtest_piotroski_in.py                 # 126-day (~6mo) horizon, 90d lag
  python3 backtest_piotroski_in.py --horizon 252 --lag 120
"""
import argparse
import os

import numpy as np
import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
HIST = os.path.join(
    os.environ.get("FUND_HIST_DIR") or os.path.join(BASE, "cache_seed", "fundamentals_history"),
    "IN.parquet",
)
PRICES = os.path.join(BASE, "cache_seed", "ltm", "IN.parquet")


def _piotroski(df):
    """Compute F-score per (ticker, fy_end), year vs prior year. Schema-aware: if the
    yfinance/SEC columns (total_assets + current_assets/liabilities + gross_profit) are
    present, use the proper 9-point Piotroski (real current ratio + gross margin). Else
    fall back to the screener.in derivation (approximated current ratio + net margin)."""
    df = df.sort_values(["ticker", "fy_end"]).copy()
    direct = (
        "total_assets" in df.columns
        and pd.to_numeric(df.get("total_assets"), errors="coerce").notna().any()
    )

    if direct:  # yfinance / SEC schema — full 9-point
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
        df["long_term_debt"] = df["long_term_debt"].fillna(0)  # debt-free names → 0
        g = df.groupby("ticker")

        def prev(c):
            return g[c].shift(1)

        ta, ta1 = df["total_assets"], prev("total_assets")
        ni, cfo = df["net_income"], df["cfo"]
        roa, roa1 = ni / ta, prev("net_income") / ta1
        lev, lev1 = df["long_term_debt"] / ta, prev("long_term_debt") / ta1
        cr = df["current_assets"] / df["current_liabilities"]
        cr1 = prev("current_assets") / prev("current_liabilities")
        sh, sh1 = df["shares"], prev("shares")
        gm = df["gross_profit"] / df["revenue"]
        gm1 = prev("gross_profit") / prev("revenue")
        at, at1 = df["revenue"] / ta, prev("revenue") / ta1
    else:  # screener.in schema — derive totals from components
        for c in [
            "net_income",
            "revenue",
            "cfo",
            "borrowings",
            "reserves",
            "equity_capital",
            "other_liab",
            "inventory",
            "receivables",
            "cash",
            "shares",
        ]:
            df[c] = pd.to_numeric(df.get(c), errors="coerce")
        df["equity"] = df["equity_capital"].fillna(0) + df["reserves"].fillna(0)
        df["total_assets"] = df["equity"] + df["borrowings"].fillna(0) + df["other_liab"].fillna(0)
        df["cur_assets"] = (
            df["inventory"].fillna(0) + df["receivables"].fillna(0) + df["cash"].fillna(0)
        )
        g = df.groupby("ticker")

        def prev(c):
            return g[c].shift(1)

        ta, ta1 = df["total_assets"], prev("total_assets")
        ni, cfo = df["net_income"], df["cfo"]
        roa, roa1 = ni / ta, prev("net_income") / ta1
        lev, lev1 = df["borrowings"] / ta, prev("borrowings") / ta1
        cr = df["cur_assets"] / df["other_liab"]
        cr1 = prev("cur_assets") / prev("other_liab")
        sh, sh1 = df["shares"], prev("shares")
        gm = ni / df["revenue"]  # net-margin proxy
        gm1 = prev("net_income") / prev("revenue")
        at, at1 = df["revenue"] / ta, prev("revenue") / ta1

    f = (
        (roa > 0).astype(float)
        + (cfo > 0).astype(float)
        + (roa > roa1).astype(float)
        + ((cfo / ta) > roa).astype(float)
        + (lev < lev1).astype(float)
        + (cr > cr1).astype(float)
        + (sh <= sh1 * 1.02).astype(float)  # tolerance so rounding ≠ dilution
        + (gm > gm1).astype(float)
        + (at > at1).astype(float)
    )
    df["F"] = np.where(ta1.notna() & (ta1 != 0), f, np.nan)
    return df.dropna(subset=["F"])


def _forward_returns(scored, horizon, lag):
    """Attach forward return: entry = fy_end + `lag` calendar days, exit = +horizon."""
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
        if arr is None:
            fwd.append(np.nan)
            continue
        dates, closes = arr
        entry_dt = np.datetime64(str(r["fy_end"])) + np.timedelta64(lag, "D")
        i = int(np.searchsorted(dates, entry_dt))
        j = i + horizon
        if i < len(dates) and j < len(dates) and closes[i] > 0:
            fwd.append(closes[j] / closes[i] - 1.0)
        else:
            fwd.append(np.nan)
    scored = scored.copy()
    scored["fwd"] = fwd
    return scored.dropna(subset=["fwd"])


def main():
    ap = argparse.ArgumentParser(description="Point-in-time-ish Piotroski backtest (India)")
    ap.add_argument(
        "--horizon", type=int, default=126, help="forward trading days (default 126 ≈ 6mo)"
    )
    ap.add_argument(
        "--lag", type=int, default=90, help="calendar days after FY-end to enter (reporting lag)"
    )
    args = ap.parse_args()
    if not os.path.exists(HIST):
        raise SystemExit(f"missing {HIST} — run screener_history_collector.py first")

    hist = pd.read_parquet(HIST)
    scored = _piotroski(hist)
    scored = _forward_returns(scored, args.horizon, args.lag)
    # winsorize band means (a few multibaggers otherwise dominate); median is
    # outlier-proof by construction.
    lo_c, hi_c = scored["fwd"].quantile([0.01, 0.99]).to_numpy()
    scored["fwd_w"] = scored["fwd"].clip(lo_c, hi_c)
    base, base_med = scored["fwd_w"].mean(), scored["fwd"].median()

    print(
        f"Piotroski F-Score backtest — INDIA — {args.horizon}-day forward, "
        f"entry=FY-end+{args.lag}d (as-restated proxy)"
    )
    print(
        f"  scored rows: {len(scored):,} | tickers: {scored['ticker'].nunique()} "
        f"| years: {pd.to_datetime(scored['fy_end']).dt.year.min()}–{pd.to_datetime(scored['fy_end']).dt.year.max()}"
    )
    print(f"  baseline (winsorized mean {base*100:+.2f}% | median {base_med*100:+.2f}%)\n")
    print(
        f"  {'F band':<10}{'n':>7}{'wins.mean%':>11}{'edge pp':>9}"
        f"{'median%':>10}{'edge pp':>9}{'win%':>7}"
    )
    for lo, hi, label in [
        (8, 9, "strong 8–9"),
        (7, 9, "≥7"),
        (4, 6, "mid 4–6"),
        (0, 3, "weak 0–3"),
    ]:
        sub = scored[(scored["F"] >= lo) & (scored["F"] <= hi)]
        if len(sub):
            m, md = sub["fwd_w"].mean(), sub["fwd"].median()
            print(
                f"  {label:<10}{len(sub):>7,}{m*100:>10.2f}%{(m-base)*100:>+8.2f}"
                f"{md*100:>9.2f}%{(md-base_med)*100:>+8.2f}{(sub['fwd']>0).mean()*100:>6.1f}%"
            )
    print("\n  by exact F (winsorized mean · median):")
    tab = scored.groupby(scored["F"].astype(int)).agg(
        n=("fwd", "size"), wmean=("fwd_w", "mean"), med=("fwd", "median")
    )
    for f, row in tab.iterrows():
        print(
            f"    F={f}: n={int(row['n']):>6,}  mean {row['wmean']*100:+.2f}%"
            f"  median {row['med']*100:+.2f}%"
        )


if __name__ == "__main__":
    main()
