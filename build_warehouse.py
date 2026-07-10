#!/usr/bin/env python3
"""
build_warehouse.py — consolidate all market data into ONE DuckDB file (market_data.duckdb)
to shrink LFS: replaces 109 per-market parquets (~1.3 GB) with a single ~730 MB SQL store.

Tables:
  prices        (market, symbol, date, high, close, volume)   — float32; Open/Low dropped
                (unused by the backtests: only Close + High/Volume for Darvas are needed)
  fundamentals  (market, ticker, fy_end, filed, + all Piotroski inputs)
  exchange_reference  — the SSOT freshness table

  FUND_HIST_DIR=... LTM_DIR=... python3 build_warehouse.py --out market_data.duckdb
"""
import argparse
import glob
import os

import duckdb

BASE = os.path.expanduser("~/Downloads/code/python_files")
FUND_DIR = os.environ.get("FUND_HIST_DIR") or os.path.join(
    BASE, "cache_seed", "fundamentals_history"
)
LTM = os.environ.get("LTM_DIR") or os.path.join(BASE, "cache_seed", "ltm")
SSOT = os.path.join(BASE, "data", "curated", "exchange_reference.parquet")


def build(out):
    if os.path.exists(out):
        os.remove(out)
    con = duckdb.connect(out)
    con.execute(
        "CREATE TABLE prices(market VARCHAR, symbol VARCHAR, date DATE, "
        "high FLOAT, close FLOAT, volume FLOAT)"
    )
    n_mkt = 0
    for p in sorted(glob.glob(os.path.join(LTM, "*.parquet"))):
        m = os.path.basename(p)[:-8]
        con.execute(
            f"INSERT INTO prices SELECT '{m}', Symbol, CAST(Date AS DATE), High, Close, Volume "
            f"FROM read_parquet('{p}')"
        )
        n_mkt += 1
    con.execute(
        "CREATE TABLE fundamentals AS "
        f"SELECT * FROM read_parquet('{FUND_DIR}/*.parquet', union_by_name=true, filename=true)"
    )
    con.execute("ALTER TABLE fundamentals ADD COLUMN market VARCHAR")
    con.execute(
        r"UPDATE fundamentals SET market = regexp_extract(filename, '([A-Z]+)\.parquet', 1)"
    )
    con.execute("ALTER TABLE fundamentals DROP COLUMN filename")
    if os.path.exists(SSOT):
        con.execute(f"CREATE TABLE exchange_reference AS SELECT * FROM read_parquet('{SSOT}')")
    pr = con.execute("SELECT count(*) FROM prices").fetchone()[0]
    fu = con.execute("SELECT count(*) FROM fundamentals").fetchone()[0]
    con.close()
    sz = os.path.getsize(out) / 1024 / 1024
    print(f"  {n_mkt} price markets · {pr:,} price rows · {fu:,} fundamental rows")
    print(f"  {os.path.basename(out)}: {sz:.0f} MB")


def main():
    ap = argparse.ArgumentParser(description="Build the consolidated DuckDB warehouse")
    ap.add_argument("--out", default=os.path.join(BASE, "market_data.duckdb"))
    args = ap.parse_args()
    build(args.out)


if __name__ == "__main__":
    main()
