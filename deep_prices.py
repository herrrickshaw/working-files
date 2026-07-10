#!/usr/bin/env python3
"""
deep_prices.py — collect DEEP (10-year) daily OHLCV for the shallow-history markets via
yfinance + curl_cffi browser-impersonation (bypasses Yahoo's datacenter-IP throttle), so
the price×fundamental combo backtests become runnable everywhere.

Reads the unified ticker universe (tickers.csv: market,yf_ticker), fetches ~10y history per
ticker, and writes one <MKT>.parquet per market to LTM_OUT (default cache_seed/ltm) in the
existing ltm schema: Date, Open, High, Low, Close, Volume, Symbol. Threaded, rate-limited,
retrying, resumable.

  LTM_OUT=/path python3 deep_prices.py --markets AU,DE,UK
  LTM_OUT=/path python3 deep_prices.py --shallow      # the 15 markets that had only ~1y
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
LTM_OUT = os.environ.get("LTM_OUT") or os.path.join(BASE, "cache_seed", "ltm")
TICKERS = os.environ.get("TICKERS_CSV") or os.path.join(BASE, "tickers.csv")
# markets whose ltm panels were only ~1 year (need deep re-collection). CN/JP/KR/US/IN deep.
SHALLOW = ["AU", "BR", "CA", "CH", "DE", "DK", "EU", "FI", "HK", "SA", "SE", "SG", "TW", "UK", "ZA"]

_tl = threading.local()


def _sess():
    if not hasattr(_tl, "s"):
        _tl.s = creq.Session(impersonate="chrome")
    return _tl.s


MIN_INTERVAL = 0.08
_rl = threading.Lock()
_last = [0.0]


def _throttle():
    with _rl:
        g = time.time() - _last[0]
        if g < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - g)
        _last[0] = time.time()


def fetch(tk, retries=3):
    for a in range(retries):
        _throttle()
        try:
            h = yf.Ticker(tk, session=_sess()).history(period="10y", auto_adjust=True)
            if h is None or h.empty:
                raise ValueError("empty")
            h = h.reset_index()[["Date", "Open", "High", "Low", "Close", "Volume"]]
            h["Date"] = pd.to_datetime(h["Date"]).dt.tz_localize(None)
            h["Symbol"] = tk.upper()
            return h
        except Exception:
            time.sleep((2**a) + random.random())
    return None


def collect_market(market, tickers, workers=10):
    out = os.path.join(LTM_OUT, f"{market}.parquet")
    done, existing = set(), []
    if os.path.exists(out):
        prev = pd.read_parquet(out)
        # only reuse if it's already deep (median >327 bars/symbol); else re-collect fresh
        med = prev.groupby("Symbol").size().median() if "Symbol" in prev else 0
        if med and med > 327:
            done = set(prev["Symbol"].astype(str).str.upper())
            existing = [prev]
    todo = [t for t in tickers if t.upper() not in done]
    print(f"  {market}: {len(tickers)} names, {len(done)} deep, {len(todo)} to fetch", flush=True)
    frames, n_ok, n = [], 0, 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch, tk): tk for tk in todo}
        for fut in as_completed(futs):
            n += 1
            try:
                h = fut.result()
                if h is not None and len(h):
                    frames.append(h)
                    n_ok += 1
            except Exception:
                pass
            if n % 200 == 0 or n == len(todo):
                os.makedirs(LTM_OUT, exist_ok=True)
                allf = existing + frames
                if allf:
                    pd.concat(allf, ignore_index=True).to_parquet(out, index=False)
    print(f"  {market}: done — {n_ok} names with price history", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Deep 10y OHLCV via yfinance + curl_cffi")
    ap.add_argument("--markets", default="")
    ap.add_argument("--shallow", action="store_true", help="the 15 shallow-history markets")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    os.makedirs(LTM_OUT, exist_ok=True)
    U = pd.read_csv(TICKERS)
    if args.markets:
        markets = [m.strip().upper() for m in args.markets.split(",")]
    elif args.shallow:
        markets = SHALLOW
    else:
        markets = sorted(U["market"].unique())
    print(f"deep prices → {LTM_OUT}\nmarkets: {markets}", flush=True)
    for m in markets:
        tks = U[U["market"] == m]["yf_ticker"].astype(str).tolist()
        collect_market(m, tks, args.workers)
    print("\nDONE — depth check:", flush=True)
    for p in sorted(glob.glob(f"{LTM_OUT}/*.parquet")):
        d = pd.read_parquet(p, columns=["Symbol", "Date"])
        med = int(d.groupby("Symbol").size().median())
        print(
            f"  {os.path.basename(p)[:-8]}: {d['Symbol'].nunique()} syms, {med} med bars",
            flush=True,
        )


if __name__ == "__main__":
    main()
