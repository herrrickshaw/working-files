#!/usr/bin/env python3
"""
local_collect.py — run the multi-market yfinance fundamentals collection LOCALLY with
curl_cffi browser-impersonation (robust vs Yahoo throttling). Reads the unified ticker
universe (tickers.csv: market,yf_ticker) and writes one <MKT>.parquet per market to
FUND_HIST_DIR, same schema as the US SEC collector. US is skipped (keeps its SEC data).

  FUND_HIST_DIR=/path python3 local_collect.py                 # all markets
  FUND_HIST_DIR=/path python3 local_collect.py --markets DK,SE --workers 6
"""
import argparse
import glob
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yfinance as yf
from curl_cffi import requests as creq

BASE = os.path.expanduser("~/Downloads/code/python_files")
OUT_DIR = os.environ.get("FUND_HIST_DIR") or os.path.join(
    BASE, "cache_seed", "fundamentals_history"
)
TICKERS = os.environ.get("TICKERS_CSV") or os.path.join(BASE, "tickers.csv")
BARE, SKIP = {"IN"}, {"US"}

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

_tl = threading.local()


def _sess():
    if not hasattr(_tl, "s"):
        _tl.s = creq.Session(impersonate="chrome")
    return _tl.s


MIN_INTERVAL = 0.10
_rl = threading.Lock()
_last = [0.0]


def _throttle():
    with _rl:
        g = time.time() - _last[0]
        if g < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - g)
        _last[0] = time.time()


def _pick(df, labels):
    if df is None or df.empty:
        return {}
    for lab in labels:
        if lab in df.index:
            return {pd.Timestamp(c).normalize(): v for c, v in df.loc[lab].items() if pd.notna(v)}
    return {}


def fetch(tk, bare, retries=3):
    for a in range(retries):
        _throttle()
        try:
            t = yf.Ticker(tk, session=_sess())
            inc, bal, cash = t.income_stmt, t.balance_sheet, t.cashflow
            if (inc is None or inc.empty) and (bal is None or bal.empty):
                raise ValueError("empty")
            ser = {}
            for f, l in INCOME.items():
                ser[f] = _pick(inc, l)
            for f, l in BAL.items():
                ser[f] = _pick(bal, l)
            for f, l in CASH.items():
                ser[f] = _pick(cash, l)
            fy = sorted({d for s in ser.values() for d in s})
            sym = tk.replace(".NS", "").replace(".BO", "").upper() if bare else tk.upper()
            out = []
            for d in fy:
                row = {"ticker": sym, "fy_end": d.strftime("%Y-%m-%d")}
                for f, s in ser.items():
                    if d in s:
                        row[f] = float(s[d])
                row["filed"] = (d + pd.Timedelta(days=90)).strftime("%Y-%m-%d")
                out.append(row)
            return out
        except Exception:
            time.sleep((2**a) + random.random())
    return []


def collect_market(market, tickers, workers=8):
    bare = market in BARE
    out = os.path.join(OUT_DIR, f"{market}.parquet")
    done, existing = set(), []
    if os.path.exists(out):
        prev = pd.read_parquet(out)
        if "total_assets" in prev.columns:
            done = set(prev["ticker"].astype(str).str.upper())
            existing = [prev]

    def key(tk):
        return tk.replace(".NS", "").replace(".BO", "").upper() if bare else tk.upper()

    todo = [t for t in tickers if key(t) not in done]
    print(f"  {market}: {len(tickers)} names, {len(done)} done, {len(todo)} to fetch", flush=True)
    rows, n_ok, n = [], 0, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch, tk, bare): tk for tk in todo}
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
                os.makedirs(OUT_DIR, exist_ok=True)
                df = (
                    pd.concat(existing + [pd.DataFrame(rows)], ignore_index=True)
                    if (existing or rows)
                    else pd.DataFrame()
                )
                if not df.empty:
                    df.to_parquet(out, index=False)
    print(f"  {market}: done — {n_ok} names with data", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default="")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    U = pd.read_csv(TICKERS)
    markets = (
        [m.strip().upper() for m in args.markets.split(",")]
        if args.markets
        else [m for m in sorted(U["market"].unique()) if m not in SKIP]
    )
    print(f"local curl_cffi collection → {OUT_DIR}\nmarkets: {markets}", flush=True)
    for m in markets:
        tks = U[U["market"] == m]["yf_ticker"].astype(str).tolist()
        collect_market(m, tks, args.workers)
    print("\nALL DONE — coverage:", flush=True)
    for p in sorted(glob.glob(f"{OUT_DIR}/*.parquet")):
        d = pd.read_parquet(p, columns=["ticker"])
        print(
            f"  {os.path.basename(p)[:-8]}: {d['ticker'].nunique()} tickers, {len(d)} rows",
            flush=True,
        )


if __name__ == "__main__":
    main()
