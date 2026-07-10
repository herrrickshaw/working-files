#!/usr/bin/env python3
"""
warehouse.py — read the consolidated DuckDB market-data store (market_data.duckdb).
The single-file replacement for the per-market ltm/ + fundamentals_history/ parquets.

  import warehouse as wh
  wh.prices("JP")            # → DataFrame(Date, High, Close, Volume, Symbol) for one market
  wh.fundamentals("IN")      # → DataFrame of dated fundamentals for one market
  wh.markets()               # → list of markets with price data
  wh.sql("SELECT market, count(DISTINCT symbol) FROM prices GROUP BY market")

The backtests read from here (or from the parquet dirs if the DB is absent), so the repo
can track just market_data.duckdb instead of 109 LFS parquets.
"""
import os

import duckdb
import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
DB = os.environ.get("MARKET_DB") or os.path.join(BASE, "market_data.duckdb")


def _con():
    return duckdb.connect(DB, read_only=True)


def sql(query: str) -> pd.DataFrame:
    with _con() as c:
        return c.execute(query).df()


def markets() -> list:
    return sorted(sql("SELECT DISTINCT market FROM prices")["market"].tolist())


def prices(market: str) -> pd.DataFrame:
    """OHLCV-subset for a market in the ltm schema (Date, High, Close, Volume, Symbol)."""
    df = sql(
        f"SELECT date AS Date, high AS High, close AS Close, volume AS Volume, "
        f"symbol AS Symbol FROM prices WHERE market = '{market.upper()}'"
    )
    df["Date"] = pd.to_datetime(df["Date"])
    return df


def fundamentals(market: str) -> pd.DataFrame:
    return sql(f"SELECT * FROM fundamentals WHERE market = '{market.upper()}'")


if __name__ == "__main__":
    if not os.path.exists(DB):
        raise SystemExit(f"no warehouse at {DB} — run build_warehouse.py first")
    print("markets:", markets())
    print(
        sql(
            "SELECT market, count(DISTINCT symbol) syms, count(*) n FROM prices "
            "GROUP BY market ORDER BY n DESC"
        ).to_string(index=False)
    )
