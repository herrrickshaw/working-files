#!/usr/bin/env python3
"""
yf_fundamentals.py — FAST multi-year DATED fundamentals via yfinance for ANY market.
====================================================================================
Generalises india_fundamentals_yf.py to every market. yfinance returns ~4-5 years of
dated annual statements (income / balance-sheet / cash-flow) with every Piotroski input
for internationally-listed names, no login and no hard throttle, so it is threaded.

Output per market: cache_seed/fundamentals_history/<MKT>.parquet (FUND_HIST_DIR-aware),
same schema as the US SEC collector — one row per (ticker, fy_end) with net_income,
revenue, gross_profit, total_assets, current_assets, current_liabilities, long_term_debt,
shares, equity, cfo, and filed = fy_end + reporting-lag proxy (yfinance carries the
period-end, not the filing date).

Ticker format matches cache_seed/ltm/<MKT>.parquet so the backtests join cleanly:
India stores BARE NSE symbols (strip .NS/.BO); every other market keeps the pre-suffixed
yfinance ticker (7203.T, SAP.DE, 005930.KS, …). US is skipped by default — SEC EDGAR
gives US true point-in-time (with filing dates); yfinance would be a downgrade there.

  python3 yf_fundamentals.py --market JP
  python3 yf_fundamentals.py --all                 # all ltm markets except US
  python3 yf_fundamentals.py --markets DE,UK,FR --workers 16
"""
import argparse
import glob
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
FUND_DIR = os.environ.get("FUND_HIST_DIR") or os.path.join(
    BASE, "cache_seed", "fundamentals_history"
)
UNI_DIR = os.path.join(BASE, "data", "global_universe")
LTM_DIR = os.path.join(BASE, "cache_seed", "ltm")
BARE_MARKETS = {"IN"}  # store bare symbols to match ltm; all others keep the yf suffix
SKIP = {"US"}  # US uses SEC EDGAR (true PIT) — don't downgrade to yfinance

INCOME = {
    "net_income": ["Net Income"],
    "revenue": ["Total Revenue"],
    "gross_profit": ["Gross Profit"],
}
BAL = {
    "total_assets": ["Total Assets"],
    "current_assets": ["Current Assets"],
    "current_liabilities": ["Current Liabilities"],
    "long_term_debt": ["Long Term Debt"],
    "shares": ["Ordinary Shares Number", "Share Issued"],
    "equity": ["Stockholders Equity", "Total Equity Gross Minority Interest"],
}
CASH = {"cfo": ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"]}


def _pick(df, labels):
    if df is None or df.empty:
        return {}
    for lab in labels:
        if lab in df.index:
            return {pd.Timestamp(c).normalize(): v for c, v in df.loc[lab].items() if pd.notna(v)}
    return {}


def collect_ticker(yf_ticker, bare):
    import yfinance as yf

    t = yf.Ticker(yf_ticker)
    inc, bal, cash = t.income_stmt, t.balance_sheet, t.cashflow
    series = {}
    for field, labs in {**INCOME}.items():
        series[field] = _pick(inc, labs)
    for field, labs in BAL.items():
        series[field] = _pick(bal, labs)
    for field, labs in CASH.items():
        series[field] = _pick(cash, labs)
    fy_ends = sorted({d for s in series.values() for d in s})
    sym = yf_ticker.replace(".NS", "").replace(".BO", "").upper() if bare else yf_ticker.upper()
    rows = []
    for fy in fy_ends:
        row = {"ticker": sym, "fy_end": fy.strftime("%Y-%m-%d")}
        for field, s in series.items():
            if fy in s:
                row[field] = float(s[fy])
        row["filed"] = (fy + pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        rows.append(row)
    return rows


def _markets(args):
    if args.markets:
        return [m.strip().upper() for m in args.markets.split(",")]
    if args.market:
        return [args.market.upper()]
    # --all: every market with a 10y-price panel (ltm), minus US (SEC EDGAR is better)
    ltm = {os.path.basename(p)[:-8] for p in glob.glob(os.path.join(LTM_DIR, "*.parquet"))}
    return sorted(ltm - SKIP)


def collect_market(market, workers):
    # ticker source: the market's universe CSV if present, else the ltm price panel
    # (European sub-markets DE/UK/CH/SE/DK/FI have no universe CSV — their pre-suffixed
    # tickers live only in cache_seed/ltm/<MKT>.parquet).
    uni_csv = os.path.join(UNI_DIR, f"{market}.csv")
    ltm_pq = os.path.join(LTM_DIR, f"{market}.parquet")
    if os.path.exists(uni_csv):
        universe = sorted(set(pd.read_csv(uni_csv)["yf_ticker"].astype(str)))
    elif os.path.exists(ltm_pq):
        universe = sorted(set(pd.read_parquet(ltm_pq, columns=["Symbol"])["Symbol"].astype(str)))
    else:
        print(f"  {market}: no universe CSV or ltm panel, skipping")
        return
    bare = market in BARE_MARKETS
    out = os.path.join(FUND_DIR, f"{market}.parquet")
    done, existing = set(), []
    if os.path.exists(out):
        prev = pd.read_parquet(out)
        if "total_assets" in prev.columns:  # only reuse yfinance-schema rows
            done = set(prev["ticker"].astype(str).str.upper())
            existing = [prev]

    def key(tk):
        return tk.replace(".NS", "").replace(".BO", "").upper() if bare else tk.upper()

    todo = [t for t in universe if key(t) not in done]
    print(f"  {market}: {len(universe)} names, {len(done)} done, {len(todo)} to fetch")
    rows, n_ok, n = [], 0, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(collect_ticker, tk, bare): tk for tk in todo}
        for fut in as_completed(futs):
            n += 1
            try:
                r = fut.result()
                if r:
                    rows.extend(r)
                    n_ok += 1
            except Exception:
                pass
            if n % 300 == 0 or n == len(todo):
                os.makedirs(FUND_DIR, exist_ok=True)  # survive a mid-run dir wipe
                df = (
                    pd.concat(existing + [pd.DataFrame(rows)], ignore_index=True)
                    if (existing or rows)
                    else pd.DataFrame()
                )
                if not df.empty:
                    df.to_parquet(out, index=False)
    print(f"  {market}: done — {n_ok} names with data")


def main():
    ap = argparse.ArgumentParser(description="Multi-market dated fundamentals via yfinance")
    ap.add_argument("--market", help="single market code (e.g. JP)")
    ap.add_argument("--markets", help="comma list (e.g. DE,UK,JP)")
    ap.add_argument("--all", action="store_true", help="all ltm markets except US")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    os.makedirs(FUND_DIR, exist_ok=True)
    markets = _markets(args)
    print(f"yfinance fundamentals — {len(markets)} markets: {', '.join(markets)}")
    for m in markets:
        collect_market(m, args.workers)
    print("done")


if __name__ == "__main__":
    main()
