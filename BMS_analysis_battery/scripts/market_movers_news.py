#!/usr/bin/env python3
"""
Fetch major movers (top gainers + losers) for India (NSE) and US markets
using tickers from the global-ticker-universe, then pull news per mover.

Designed to run both locally and inside GitHub Actions (where Yahoo Finance
is reachable). Results are written to JSON for the backend to serve.

Usage:
  python3 scripts/market_movers_news.py
  python3 scripts/market_movers_news.py --markets india
  python3 scripts/market_movers_news.py --markets us --top 10 --news 5
  python3 scripts/market_movers_news.py --output data/movers/movers_news.json --split
  NEWSAPI_KEY=xxx python3 scripts/market_movers_news.py
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
UNIVERSE_URL = (
    "https://raw.githubusercontent.com/herrrickshaw/global-ticker-universe"
    "/main/data/global_universe_flat.csv"
)

# Market code → filter key in universe CSV
MARKET_CODES = {"india": "IN", "us": "US"}

# Fallback hardcoded tickers if universe fetch fails
FALLBACK = {
    "india": [
        "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
        "HINDUNILVR.NS","ITC.NS","SBIN.NS","BAJFINANCE.NS","BHARTIARTL.NS",
        "AXISBANK.NS","KOTAKBANK.NS","LT.NS","ASIANPAINT.NS","MARUTI.NS",
        "SUNPHARMA.NS","NESTLEIND.NS","TITAN.NS","ULTRACEMCO.NS","WIPRO.NS",
        "HCLTECH.NS","TECHM.NS","POWERGRID.NS","NTPC.NS","ONGC.NS",
        "COALINDIA.NS","TATAMOTORS.NS","TATASTEEL.NS","JSWSTEEL.NS",
        "ADANIENT.NS","ADANIPORTS.NS","BAJAJFINSV.NS","DRREDDY.NS",
        "CIPLA.NS","EICHERMOT.NS","HEROMOTOCO.NS","BPCL.NS","GRASIM.NS",
    ],
    "us": [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","JPM","UNH",
        "XOM","V","LLY","JNJ","MA","PG","HD","AVGO","CVX","MRK",
        "ABBV","COST","PEP","ADBE","AMD","NFLX","INTC","CSCO","TMO",
        "WMT","BAC","ACN","MCD","CRM","ABT","NEE","QCOM","LIN","DHR",
    ],
}


# ── Ticker universe ───────────────────────────────────────────────────────────

def load_universe(market_code: str, limit: int = 200) -> List[str]:
    """
    Load tickers from global-ticker-universe for a market code.
    Falls back to hardcoded lists if the URL is unreachable.
    Caps at `limit` tickers to keep yfinance batch download fast.
    """
    market_key = MARKET_CODES.get(market_code, market_code.upper())
    try:
        log.info("Loading universe for %s from GitHub...", market_code)
        with urllib.request.urlopen(UNIVERSE_URL, timeout=10) as resp:
            text = resp.read().decode()
        reader = csv.DictReader(text.splitlines())
        tickers = [
            r["yf_symbol"] for r in reader
            if r.get("market_code") == market_key and r.get("yf_symbol")
        ]
        # Prioritise liquid names: for India prefer .NS, for US bare symbols
        if market_code == "india":
            ns = [t for t in tickers if t.endswith(".NS")]
            tickers = ns or tickers
        log.info("  %d tickers loaded for %s (capped at %d)", len(tickers), market_code, limit)
        return tickers[:limit]
    except Exception as exc:
        log.warning("Universe fetch failed (%s) — using fallback list", exc)
        return FALLBACK.get(market_code, [])


# ── Price movers ─────────────────────────────────────────────────────────────

def fetch_movers(tickers: List[str], market: str,
                 top_n: int = 10) -> Tuple[List[Dict], List[Dict]]:
    import yfinance as yf
    log.info("Downloading prices for %d %s tickers...", len(tickers), market)
    try:
        data = yf.download(
            tickers, period="2d", interval="1d",
            group_by="ticker", auto_adjust=True,
            progress=False, threads=True,
        )
    except Exception as exc:
        log.error("yfinance download failed: %s", exc)
        return [], []

    moves: List[Dict] = []
    for t in tickers:
        try:
            if len(tickers) == 1:
                closes = data["Close"]
            elif t in data.columns.get_level_values(0):
                closes = data[t]["Close"]
            else:
                continue
            closes = closes.dropna()
            if len(closes) < 2:
                continue
            prev, last = float(closes.iloc[-2]), float(closes.iloc[-1])
            if prev == 0:
                continue
            pct = (last - prev) / prev * 100
            moves.append({
                "ticker":     t,
                "market":     market,
                "pct_change": round(pct, 2),
                "prev_close": round(prev, 2),
                "last_close": round(last, 2),
            })
        except Exception:
            continue

    moves.sort(key=lambda x: x["pct_change"], reverse=True)
    return moves[:top_n], moves[-top_n:][::-1]


# ── News fetchers ─────────────────────────────────────────────────────────────

def _newsapi_fetch(query: str, limit: int, api_key: str) -> List[Dict]:
    import urllib.parse
    url = ("https://newsapi.org/v2/everything?" + urllib.parse.urlencode({
        "q": query, "language": "en", "sortBy": "publishedAt",
        "pageSize": limit, "apiKey": api_key,
    }))
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        return [
            {
                "title":     a.get("title", ""),
                "publisher": (a.get("source") or {}).get("name", ""),
                "link":      a.get("url", ""),
                "published": a.get("publishedAt", ""),
                "source":    "newsapi",
            }
            for a in data.get("articles", [])
        ]
    except Exception as exc:
        log.warning("NewsAPI failed for '%s': %s", query, exc)
        return []


def _yfinance_news(ticker: str, limit: int) -> List[Dict]:
    import yfinance as yf
    try:
        raw = yf.Ticker(ticker).news or []
        return [
            {
                "title":     a.get("title", ""),
                "publisher": a.get("publisher", ""),
                "link":      a.get("link", ""),
                "published": datetime.utcfromtimestamp(
                    a["providerPublishTime"]).strftime("%Y-%m-%dT%H:%M:%SZ")
                if a.get("providerPublishTime") else "",
                "source":    "yfinance",
            }
            for a in raw[:limit]
        ]
    except Exception as exc:
        log.warning("yfinance news failed for %s: %s", ticker, exc)
        return []


def fetch_news(ticker: str, limit: int = 5,
               newsapi_key: Optional[str] = None) -> List[Dict]:
    bare = ticker.replace(".NS", "").replace(".BO", "")
    if newsapi_key:
        articles = _newsapi_fetch(bare, limit, newsapi_key)
        if articles:
            return articles
    return _yfinance_news(ticker, limit)


# ── Terminal report ───────────────────────────────────────────────────────────

_G = "\033[92m"; _R = "\033[91m"; _B = "\033[1m"; _D = "\033[2m"; _0 = "\033[0m"

def print_section(label: str, movers: List[Dict], kind: str):
    icon = "▲" if kind == "gainers" else "▼"
    print(f"\n{_B}{'─'*70}{_0}\n{_B}  {label} — {kind.upper()} {icon}{_0}\n{_B}{'─'*70}{_0}")
    if not movers:
        print("  (no data)")
        return
    for m in movers:
        c = _G if m["pct_change"] >= 0 else _R
        print(f"\n  {_B}{m['ticker']:22s}{_0}{c}{m['pct_change']:+7.2f}%{_0}"
              f"  {_D}prev={m['prev_close']}  last={m['last_close']}{_0}")
        for a in m.get("news", []):
            if a.get("title"):
                print(f"    {_D}•{_0} {a['title'][:76]}")
                print(f"      {_D}[{a.get('publisher','')}]  {a.get('published','')[:16]}{_0}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Market movers + news")
    parser.add_argument("--markets", default="all",
                        help="Comma-separated: india,us  (default: all)")
    parser.add_argument("--top",    type=int, default=10)
    parser.add_argument("--news",   type=int, default=5)
    parser.add_argument("--limit",  type=int, default=200,
                        help="Max tickers per market from universe (default 200)")
    parser.add_argument("--output", default=None,
                        help="JSON output path (default: reports/movers_news.json)")
    parser.add_argument("--split",  action="store_true",
                        help="Also write per-market files: data/movers/<market>.json")
    args = parser.parse_args()

    markets = (["india", "us"] if args.markets in ("all", "")
               else [m.strip() for m in args.markets.split(",")])
    newsapi_key = os.environ.get("NEWSAPI_KEY")

    all_results: Dict = {}
    for market in markets:
        label = "India (NSE)" if market == "india" else "US (NYSE/NASDAQ)"
        print(f"\n{'='*70}\n  {label}\n{'='*70}")
        tickers = load_universe(market, args.limit)
        if not tickers:
            print("  No tickers found.")
            continue

        gainers, losers = fetch_movers(tickers, market, top_n=args.top)
        if not gainers and not losers:
            print("  No price data — Yahoo Finance may be unreachable from this host.")
            continue

        for m in gainers + losers:
            if args.news > 0:
                log.info("  news: %s (%+.2f%%)", m["ticker"], m["pct_change"])
                m["news"] = fetch_news(m["ticker"], args.news, newsapi_key)

        print_section(label, gainers, "gainers")
        print_section(label, losers,  "losers")

        payload = {
            "market":     market,
            "label":      label,
            "gainers":    gainers,
            "losers":     losers,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        all_results[market] = payload

        if args.split:
            split_path = ROOT / "data" / "movers" / f"{market}.json"
            split_path.parent.mkdir(parents=True, exist_ok=True)
            split_path.write_text(json.dumps(payload, indent=2))
            log.info("Wrote %s", split_path)

    out_path = Path(args.output) if args.output else ROOT / "reports" / "movers_news.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nSaved to {out_path}\n")


if __name__ == "__main__":
    main()
