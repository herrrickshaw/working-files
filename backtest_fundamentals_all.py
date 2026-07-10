#!/usr/bin/env python3
"""
backtest_fundamentals_all.py — point-in-time fundamental-screener backtest across ALL
markets, using the dated fundamentals (cache_seed/fundamentals_history/<MKT>.parquet,
FUND_HIST_DIR-overridable) + the 10y OHLCV (cache_seed/ltm/<MKT>.parquet).

For every market it computes, point-in-time (entry = `filed`+1 trading day — real SEC
filing date for US, fy_end+90d reporting-lag proxy elsewhere — exit = +horizon):
  • Piotroski F-Score bands (strong 8-9 · ≥7 · mid 4-6 · weak 0-3)
  • Magic Formula   (earnings yield EBIT/EV ≥ 8% AND ROC EBIT/(TA-CL) ≥ 15%)
  • Quality         (ROCE ≥ 15% AND D/E ≤ 1)
  • Net-net         (Graham: market cap < net current asset value)
  • Low-debt        (long-term debt fell YoY)
Reported as winsorized-median edge vs each market's equal-weight baseline (median is
outlier-proof; magnitudes are survivorship-flattered — trust the ordering).

  python3 backtest_fundamentals_all.py                 # 252d, all markets
  python3 backtest_fundamentals_all.py --horizon 126 --markets IN,JP,DE
"""
import argparse
import glob
import os

import numpy as np
import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
FUND_DIR = os.environ.get("FUND_HIST_DIR") or os.path.join(
    BASE, "cache_seed", "fundamentals_history"
)
LTM = os.environ.get("LTM_DIR") or os.path.join(BASE, "cache_seed", "ltm")

try:  # prefer the consolidated DuckDB warehouse; fall back to per-market parquets
    import warehouse as _wh

    _USE_WH = os.path.exists(_wh.DB)
except Exception:
    _USE_WH = False


def _fund_df(market):
    if _USE_WH:
        return _wh.fundamentals(market)
    return pd.read_parquet(os.path.join(FUND_DIR, f"{market}.parquet"))


def _px_df(market):
    if _USE_WH:
        return _wh.prices(market)
    return pd.read_parquet(
        os.path.join(LTM, f"{market}.parquet"), columns=["Date", "Close", "Symbol"]
    )


def _has(market):
    if _USE_WH:
        return market in _wh.markets()
    return os.path.exists(os.path.join(FUND_DIR, f"{market}.parquet")) and os.path.exists(
        os.path.join(LTM, f"{market}.parquet")
    )


def _fscore(df):
    """9-point Piotroski + derived screen fields per (ticker, fy_end), year vs prior."""
    df = df.sort_values(["ticker", "fy_end"]).copy()
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
        "equity",
    ]:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    df["long_term_debt"] = df["long_term_debt"].fillna(0)
    g = df.groupby("ticker")

    def p(c):
        return g[c].shift(1)

    ta, ta1 = df["total_assets"], p("total_assets")
    ni, cfo = df["net_income"], df["cfo"]
    roa, roa1 = ni / ta, p("net_income") / ta1
    lev, lev1 = df["long_term_debt"] / ta, p("long_term_debt") / ta1
    cr = df["current_assets"] / df["current_liabilities"]
    cr1 = p("current_assets") / p("current_liabilities")
    sh, sh1 = df["shares"], p("shares")
    gm, gm1 = df["gross_profit"] / df["revenue"], p("gross_profit") / p("revenue")
    at, at1 = df["revenue"] / ta, p("revenue") / ta1
    df["F"] = (
        (roa > 0).astype(float)
        + (cfo > 0).astype(float)
        + (roa > roa1).astype(float)
        + ((cfo / ta) > roa).astype(float)
        + (lev < lev1).astype(float)
        + (cr > cr1).astype(float)
        + (sh <= sh1 * 1.02).astype(float)
        + (gm > gm1).astype(float)
        + (at > at1).astype(float)
    )
    df["F"] = np.where(ta1.notna() & (ta1 != 0), df["F"], np.nan)
    cap = ta - df["current_liabilities"]
    # EBIT is absent from the yfinance schema, so use net income as the earnings numerator
    # uniformly across markets: ROCE = net_income/(TA−CL) (return on capital), EY = net_income/EV.
    df["roce"] = np.where(cap > 0, ni / cap * 100, np.nan)
    df["de"] = np.where(df["equity"] > 0, df["long_term_debt"] / df["equity"], np.nan)
    df["lowdebt"] = (df["long_term_debt"] < p("long_term_debt")).astype(float)
    df["ncav"] = df["current_assets"] - (ta - df["equity"])  # cur assets − total liabilities
    df["ey_num"] = ni  # earnings for EY (net income; EBIT absent in yf schema)
    return df.dropna(subset=["F"])


def _prices(market):
    px = _px_df(market)
    px["Date"] = pd.to_datetime(px["Date"])
    px["Symbol"] = px["Symbol"].astype(str).str.upper()
    px = px.sort_values(["Symbol", "Date"])
    return {s: (g["Date"].to_numpy(), g["Close"].to_numpy()) for s, g in px.groupby("Symbol")}


def _attach(scored, by_sym, horizon):
    entry_px, fwd = [], []
    for _, r in scored.iterrows():
        arr = by_sym.get(str(r["ticker"]).upper())
        filed = r.get("filed")
        if arr is None or not filed or str(filed) == "9999-99-99":
            entry_px.append(np.nan)
            fwd.append(np.nan)
            continue
        dates, closes = arr
        i = int(np.searchsorted(dates, np.datetime64(str(filed)) + np.timedelta64(1, "D")))
        j = i + horizon
        if i < len(dates) and closes[i] > 0:
            entry_px.append(closes[i])
            fwd.append(closes[j] / closes[i] - 1 if j < len(dates) else np.nan)
        else:
            entry_px.append(np.nan)
            fwd.append(np.nan)
    scored = scored.copy()
    scored["entry_px"], scored["fwd"] = entry_px, fwd
    return scored.dropna(subset=["fwd"])


def backtest_market(market, horizon):
    if not _has(market):
        return None
    d = _fscore(_fund_df(market))
    d = _attach(d, _prices(market), horizon)
    if len(d) < 100:
        return None
    lo, hi = d["fwd"].quantile([0.01, 0.99]).to_numpy()
    d["fwd_w"] = d["fwd"].clip(lo, hi)
    base = float(d["fwd"].median())
    mcap = d["shares"] * d["entry_px"]
    ev = mcap + d["long_term_debt"]
    d["magic"] = (np.where(ev > 0, d["ey_num"] / ev, np.nan) >= 0.06) & (d["roce"] >= 12)
    d["quality"] = (d["roce"] >= 15) & (d["de"] <= 1)
    d["net_net"] = (d["ncav"] > 0) & (mcap < d["ncav"])
    d["ld"] = d["lowdebt"] == 1

    def med_edge(mask):
        s = d[mask]
        return (float(s["fwd"].median()) - base, len(s)) if len(s) >= 20 else (np.nan, len(s))

    strong = med_edge(d["F"] >= 8)
    p7 = med_edge(d["F"] >= 7)
    weak = med_edge(d["F"] <= 3)
    return {
        "market": market,
        "n": len(d),
        "base": base * 100,
        "F>=8": strong[0] * 100 if strong[0] == strong[0] else None,
        "n_F8": strong[1],
        "F>=7": p7[0] * 100 if p7[0] == p7[0] else None,
        "F<=3": weak[0] * 100 if weak[0] == weak[0] else None,
        "magic": (
            med_edge(d["magic"])[0] * 100
            if med_edge(d["magic"])[0] == med_edge(d["magic"])[0]
            else None
        ),
        "quality": (
            med_edge(d["quality"])[0] * 100
            if med_edge(d["quality"])[0] == med_edge(d["quality"])[0]
            else None
        ),
        "net_net": (
            med_edge(d["net_net"])[0] * 100
            if med_edge(d["net_net"])[0] == med_edge(d["net_net"])[0]
            else None
        ),
        "lowdebt": (
            med_edge(d["ld"])[0] * 100 if med_edge(d["ld"])[0] == med_edge(d["ld"])[0] else None
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Cross-market fundamental-screener backtest")
    ap.add_argument("--horizon", type=int, default=252)
    ap.add_argument("--markets", default="")
    args = ap.parse_args()
    if args.markets:
        markets = [m.strip().upper() for m in args.markets.split(",")]
    else:
        markets = (
            _wh.markets()
            if _USE_WH
            else sorted(os.path.basename(p)[:-8] for p in glob.glob(f"{FUND_DIR}/*.parquet"))
        )

    print(f"Cross-market fundamental backtest — {args.horizon}d forward, point-in-time")
    print("  median edge (pp) vs each market's baseline; ⭐ = the market's best screen\n")
    hdr = ["Mkt", "n", "F>=8", "F>=7", "F<=3", "magic", "quality", "net_net", "lowdebt"]
    print("  " + "".join(h.rjust(9) for h in hdr))
    rows = []
    SCREENS = ["F>=8", "F>=7", "F<=3", "magic", "quality", "net_net", "lowdebt"]
    for m in markets:
        r = backtest_market(m, args.horizon)
        if not r:
            print(f"  {m:>9}  (insufficient data)")
            continue
        rows.append(r)
        best = max((s for s in SCREENS if r.get(s) is not None), key=lambda s: r[s], default=None)
        cells = f"  {m:>9}{r['n']:>9}"
        for s in SCREENS:
            v = r.get(s)
            tag = "⭐" if s == best else " "
            cells += f"{v:>+8.1f}{tag}" if v is not None else "     —   "
        print(cells)

    if rows:
        df = pd.DataFrame(rows)
        print("\n  === which screen works where (positive median edge) ===")
        for s in SCREENS:
            pos = df[df[s] > 0]["market"].tolist()
            avg = df[s].mean()
            print(
                f"  {s:<9} avg {avg:>+5.1f}pp · positive in {len(pos)}/{len(df)}: {', '.join(pos)}"
            )
        out = os.path.join(BASE, "data", "curated", "fundamental_backtest_all.parquet")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        df.to_parquet(out, index=False)
        print(f"\n  → {os.path.relpath(out, BASE)}")


if __name__ == "__main__":
    main()
