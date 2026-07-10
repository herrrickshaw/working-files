#!/usr/bin/env python3
"""
exchange_reference.py — daily data-freshness checklist + SSOT across ALL exchanges.
===================================================================================
Single source of truth so stale market data is caught at a glance:

  data/curated/exchange_reference.parquet   one row per (market, exchange) with
      the ticker list, the universe-list update date, the scan-DATA update date,
      the dated FUNDAMENTALS-collection status (ticker count, fiscal-year range,
      collection date), age in days, and a FRESH / STALE / UNIVERSE_ONLY status.

  data/curated/daily_checklist_<date>.md    a human-readable ✅/⚠️ checklist.

Freshness layers:
  • universe_updated — when the ticker LIST for that exchange was last refreshed
    (mtime of data/global_universe/<MKT>.csv).
  • data_updated     — when the SCAN data (OHLC scan workbook) for that market was
    last rebuilt. Only US/EU/IN are scanned; others are UNIVERSE_ONLY.
  • fundamentals     — dated point-in-time financials collected per market
    (cache_seed/fundamentals_history/<MKT>.parquet, FUND_HIST_DIR-overridable):
    US via SEC EDGAR, IN via yfinance (5y) / screener.in (10y). Records the ticker
    count, fiscal-year span, row count and the collection date.

CLI:
  python3 exchange_reference.py            # build parquet + print checklist
  python3 exchange_reference.py --stale    # exit 1 if any scanned exchange is stale
"""
import argparse
import datetime
import glob
import os
import sys

import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
CURATED = os.path.join(BASE, "data", "curated")
UNIVERSE_GLOB = os.path.join(BASE, "data", "global_universe", "*.csv")
FUND_DIR = os.environ.get("FUND_HIST_DIR") or os.path.join(
    BASE, "cache_seed", "fundamentals_history"
)

# market → scan workbook glob (data freshness). Markets absent here are UNIVERSE_ONLY.
SCAN_GLOBS = {
    "US": "us_full_scan/us_full_scan_*.xlsx",
    "EU": "european_scan/european_market_scan_broad_*.xlsx",
    "IN": "indian_full_scan/indian_full_scan_*.xlsx",
}
# per-market source of the dated fundamentals collection (for the checklist).
FUND_SOURCE = {"US": "SEC EDGAR", "IN": "yfinance/screener.in"}
US_EXCH_FIX = {"N": "NYSE", "A": "NYSE American", "P": "NYSE Arca", "Z": "Cboe BZX", "K": "Nasdaq"}
STALE_AFTER_DAYS = 1  # weekday scan data older than this = STALE


def _mtime_date(path):
    return (
        datetime.date.fromtimestamp(os.path.getmtime(path))
        if path and os.path.exists(path)
        else None
    )


def _latest(patt):
    f = sorted(glob.glob(os.path.join(BASE, patt)), key=os.path.getmtime)
    return f[-1] if f else None


def _fundamentals_status(market):
    """Dated-fundamentals collection status for a market (empty if none collected)."""
    p = os.path.join(FUND_DIR, f"{market}.parquet")
    if not os.path.exists(p):
        return {}
    try:
        d = pd.read_parquet(p, columns=["ticker", "fy_end"])
    except Exception:
        return {}
    if d.empty:
        return {}
    yrs = pd.to_datetime(d["fy_end"], errors="coerce").dt.year.dropna()
    return {
        "fund_source": FUND_SOURCE.get(market, "yfinance"),
        "n_fund_tickers": int(d["ticker"].nunique()),
        "fund_rows": int(len(d)),
        "fund_year_min": int(yrs.min()) if not yrs.empty else None,
        "fund_year_max": int(yrs.max()) if not yrs.empty else None,
        "fund_collected_on": _mtime_date(p).isoformat(),
    }


def build_reference(today=None):
    """Return the per-(market,exchange) freshness/SSOT DataFrame."""
    today = today or datetime.date.today()
    scan = {m: (_latest(g), _mtime_date(_latest(g))) for m, g in SCAN_GLOBS.items()}
    rows = []
    for f in sorted(glob.glob(UNIVERSE_GLOB)):
        df = pd.read_csv(f)
        market = os.path.splitext(os.path.basename(f))[0].upper()
        uni_date = _mtime_date(f)
        tcol = "yf_ticker" if "yf_ticker" in df.columns else df.columns[0]
        if "exchange" not in df.columns:
            df["exchange"] = market
        df["exchange"] = df["exchange"].astype(str).replace(US_EXCH_FIX)
        scan_wb, scan_date = scan.get(market, (None, None))
        fund = _fundamentals_status(market)
        for exch, g in df.groupby("exchange"):
            tickers = sorted(g[tcol].dropna().astype(str).unique())
            if scan_date:
                age = (today - scan_date).days
                status = "FRESH" if age <= STALE_AFTER_DAYS else "STALE"
                data_updated = scan_date.isoformat()
            else:
                age = (today - uni_date).days if uni_date else None
                status = "UNIVERSE_ONLY"
                data_updated = None
            rows.append(
                {
                    "market": market,
                    "exchange": exch,
                    "n_tickers": len(tickers),
                    "tickers": tickers,
                    "universe_source": os.path.relpath(f, BASE),
                    "universe_updated": uni_date.isoformat() if uni_date else None,
                    "scan_source": os.path.relpath(scan_wb, BASE) if scan_wb else None,
                    "data_updated": data_updated,
                    "age_days": age,
                    "status": status,
                    "fund_source": fund.get("fund_source"),
                    "n_fund_tickers": fund.get("n_fund_tickers"),
                    "fund_rows": fund.get("fund_rows"),
                    "fund_year_min": fund.get("fund_year_min"),
                    "fund_year_max": fund.get("fund_year_max"),
                    "fund_collected_on": fund.get("fund_collected_on"),
                    "checked": today.isoformat(),
                }
            )
    order = {"STALE": 0, "NO_DATA": 1, "FRESH": 2, "UNIVERSE_ONLY": 3}
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(
        ["status", "market", "exchange"], key=lambda s: s.map(order) if s.name == "status" else s
    ).reset_index(drop=True)


def write_parquet(df):
    os.makedirs(CURATED, exist_ok=True)
    out = os.path.join(CURATED, "exchange_reference.parquet")
    df.to_parquet(out, index=False)
    return out


_BADGE = {"FRESH": "✅", "STALE": "⚠️", "UNIVERSE_ONLY": "📋", "NO_DATA": "❌"}


def checklist_md(df, today):
    """Render a human-readable daily checklist (markdown)."""
    lines = [f"# 📋 Daily Data Freshness Checklist — {today.isoformat()}", ""]
    n_ex = len(df)
    stale = int((df["status"] == "STALE").sum())
    fresh = int((df["status"] == "FRESH").sum())
    uni = int((df["status"] == "UNIVERSE_ONLY").sum())
    lines.append(
        f"**{n_ex} exchanges** · ✅ {fresh} fresh · ⚠️ {stale} stale · 📋 {uni} universe-only "
        f"· {int(df['n_tickers'].sum()):,} tickers tracked"
    )
    # dated-fundamentals coverage summary (the SSOT's point-in-time layer)
    fdf = df[df["n_fund_tickers"].notna()].drop_duplicates("market")
    if not fdf.empty:
        parts = [
            f"{r['market']} {int(r['n_fund_tickers']):,} names "
            f"({int(r['fund_year_min'])}–{int(r['fund_year_max'])}, {r['fund_source']}, "
            f"collected {r['fund_collected_on']})"
            for _, r in fdf.iterrows()
        ]
        lines.append("\n**Dated fundamentals:** " + " · ".join(parts))
    if stale:
        names = ", ".join(df[df["status"] == "STALE"]["exchange"].tolist())
        lines.append(f"\n> ⚠️ **STALE — refresh needed:** {names}")
    lines.append(
        "\n| Status | Market | Exchange | Tickers | Data updated | Fund. names | Fund. yrs | Age (d) |"
    )
    lines.append("|---|---|---|---:|---|---:|---|---:|")
    for _, r in df.iterrows():
        badge = _BADGE.get(r["status"], "")
        age = "" if pd.isna(r["age_days"]) else int(r["age_days"])
        fn = "" if pd.isna(r["n_fund_tickers"]) else f"{int(r['n_fund_tickers']):,}"
        fy = (
            f"{int(r['fund_year_min'])}–{int(r['fund_year_max'])}"
            if pd.notna(r["fund_year_min"])
            else "—"
        )
        lines.append(
            f"| {badge} {r['status']} | {r['market']} | {r['exchange']} | {r['n_tickers']:,} | "
            f"{r['data_updated'] or '—'} | {fn or '—'} | {fy} | {age} |"
        )
    return "\n".join(lines) + "\n"


def run(today=None, write=True):
    today = today or datetime.date.today()
    df = build_reference(today)
    if df.empty:
        print("No universe files found under data/global_universe/*.csv")
        return df, None
    pq = write_parquet(df) if write else None
    md = checklist_md(df, today)
    if write:
        md_path = os.path.join(CURATED, f"daily_checklist_{today.isoformat()}.md")
        open(md_path, "w").write(md)
    print(md.split("\n| Status")[0])  # header + summary + fundamentals + stale line
    print(f"\nparquet → {os.path.relpath(pq, BASE) if pq else '(not written)'}")
    return df, pq


def main():
    ap = argparse.ArgumentParser(description="Daily exchange data-freshness reference + SSOT")
    ap.add_argument("--stale", action="store_true", help="exit 1 if any scanned exchange is STALE")
    ap.add_argument("--no-write", action="store_true", help="print only; don't write files")
    args = ap.parse_args()
    df, _ = run(write=not args.no_write)
    if args.stale and not df.empty and (df["status"] == "STALE").any():
        sys.exit(1)


if __name__ == "__main__":
    main()
