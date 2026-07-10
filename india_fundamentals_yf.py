#!/usr/bin/env python3
"""
india_fundamentals_yf.py — FAST multi-year India fundamentals collector via yfinance,
the primary India source now that screener.in throttles heavily. yfinance returns ~5
years of DATED annual statements (income/balance-sheet/cash-flow) with every Piotroski
input, no login and no hard rate-limit, so it can be threaded.

Output schema matches the US SEC collector (cache_seed/fundamentals_history/US.parquet)
so the same point-in-time Piotroski logic applies: one row per (ticker, fy_end) with
net_income, revenue, gross_profit, total_assets, current_assets, current_liabilities,
long_term_debt, shares, equity, cfo, and `filed` = fy_end + reporting-lag proxy
(yfinance carries the fiscal period-end but no filing date; Indian issuers report within
~60-90d of FY-end, so filed = fy_end + 90d — the same convention as the screener.in path).

Source fallback chain for India dated fundamentals (best → weakest): screener.in (10y,
throttled) → **yfinance (5y, fast, this file)** → moneycontrol scrape (future). Groww /
NSE / BSE APIs are price/quote-oriented and don't expose clean multi-year statements.

  python3 india_fundamentals_yf.py                 # full NSE universe, threaded
  python3 india_fundamentals_yf.py --limit 500     # 500 most-liquid (by ltm dollar-vol)
  python3 india_fundamentals_yf.py --workers 16
"""
import argparse
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
OUT_DIR = os.environ.get("FUND_HIST_DIR") or os.path.join(
    BASE, "cache_seed", "fundamentals_history"
)
OUT = os.path.join(OUT_DIR, "IN.parquet")
UNIVERSE = os.path.join(BASE, "data", "global_universe", "IN.csv")
LTM = os.path.join(BASE, "cache_seed", "ltm", "IN.parquet")

# yfinance statement row label → our field (first present wins)
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
    """Return the {col_date: value} series for the first present label in df."""
    if df is None or df.empty:
        return {}
    for lab in labels:
        if lab in df.index:
            row = df.loc[lab]
            return {pd.Timestamp(c).normalize(): v for c, v in row.items() if pd.notna(v)}
    return {}


def collect_ticker(yf_ticker):
    """One NSE ticker (e.g. RELIANCE.NS) → list of per-fiscal-year row dicts."""
    import yfinance as yf

    t = yf.Ticker(yf_ticker)
    inc, bal, cash = t.income_stmt, t.balance_sheet, t.cashflow
    series = {}
    for field, labs in INCOME.items():
        series[field] = _pick(inc, labs)
    for field, labs in BAL.items():
        series[field] = _pick(bal, labs)
    for field, labs in CASH.items():
        series[field] = _pick(cash, labs)
    fy_ends = sorted({d for s in series.values() for d in s})
    sym = yf_ticker.replace(".NS", "").replace(".BO", "").upper()
    rows = []
    for fy in fy_ends:
        row = {"ticker": sym, "fy_end": fy.strftime("%Y-%m-%d")}
        for field, s in series.items():
            if fy in s:
                row[field] = float(s[fy])
        # yfinance has no filing date — Indian annual results land within ~60-90d of FY-end
        row["filed"] = (fy + pd.Timedelta(days=90)).strftime("%Y-%m-%d")
        rows.append(row)
    return rows


def _universe(args):
    uni = pd.read_csv(UNIVERSE)
    syms = uni["yf_ticker"].astype(str)
    if args.limit and os.path.exists(LTM):
        # keep the most-liquid names (by recent ltm dollar volume) — the backtestable ones
        px = pd.read_parquet(LTM, columns=["Symbol", "Close", "Volume"])
        px["dvol"] = px["Close"] * px["Volume"]
        liq = px.groupby("Symbol")["dvol"].mean().sort_values(ascending=False)
        keep = set(liq.head(args.limit).index.astype(str).str.upper())
        syms = [s for s in syms if s.replace(".NS", "").replace(".BO", "").upper() in keep]
    return sorted(set(syms))


def main():
    ap = argparse.ArgumentParser(description="Fast India fundamentals via yfinance (threaded)")
    ap.add_argument("--limit", type=int, default=0, help="cap to N most-liquid names (0 = all)")
    ap.add_argument("--workers", type=int, default=12, help="thread pool size")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)

    universe = _universe(args)
    done = set()
    existing = []
    if os.path.exists(OUT):
        prev = pd.read_parquet(OUT)
        # only reuse rows that came from this yfinance schema (have total_assets)
        if "total_assets" in prev.columns:
            done = set(prev["ticker"].astype(str).str.upper())
            existing = [prev]
    todo = [t for t in universe if t.replace(".NS", "").replace(".BO", "").upper() not in done]
    print(
        f"yfinance India: {len(universe)} names, {len(done)} done, {len(todo)} to fetch "
        f"({args.workers} threads)"
    )

    rows, n_ok, n = [], 0, 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(collect_ticker, tk): tk for tk in todo}
        for fut in as_completed(futs):
            n += 1
            try:
                r = fut.result()
                if r:
                    rows.extend(r)
                    n_ok += 1
            except Exception:
                pass
            if n % 200 == 0 or n == len(todo):
                os.makedirs(OUT_DIR, exist_ok=True)  # survive a mid-run dir wipe
                df = (
                    pd.concat(existing + [pd.DataFrame(rows)], ignore_index=True)
                    if (existing or rows)
                    else pd.DataFrame()
                )
                if not df.empty:
                    df.to_parquet(OUT, index=False)
                print(f"  {n}/{len(todo)} | {n_ok} with data | {len(df)} rows")
    print(f"done → {os.path.relpath(OUT, BASE)}")


if __name__ == "__main__":
    main()
