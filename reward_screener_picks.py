#!/usr/bin/env python3
"""
reward_screener_picks.py — apply the OUT-OF-SAMPLE-ROBUST screeners discovered by
reward_screener_opt.py to the LATEST cross-section, and list the names currently passing.

Only the five markets whose discovered screener survived the held-out test are screened
(US, CA, TW, IN, CN — see reports/reward_screeners_252d.csv). Each screen is applied
cross-sectionally on the most recent prices (+ latest fundamentals for the US value screen),
after dropping the least-liquid 40% of names so the picks are tradeable.

⚠ EDUCATIONAL / RESEARCH ONLY — NOT investment advice, not a personalised recommendation.
These are the mechanical output of a screen with a modest, survivorship-flattered historical
edge; do your own diligence.

  MARKET_DB=/path/to/market_data.duckdb python3 reward_screener_picks.py --top 12
"""
import argparse
import os

import numpy as np
import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")

# market -> (label, factor, side, keep_frac, price_source)
ROBUST = {
    "US": ("deep value", "book_to_market", "top", 0.10, "local"),
    "CA": ("12-mo momentum", "mom_12_1", "top", 0.40, "warehouse"),
    "TW": ("low volatility", "vol_60", "bottom", 0.40, "warehouse"),
    "IN": ("uptrend (>200-DMA)", "above_200dma", "top", 0.50, "warehouse"),
    "CN": ("low volatility", "vol_60", "bottom", 0.50, "warehouse"),
}
LIQ_KEEP = 0.40  # keep only the most-liquid 40% of names (drop pump/illiquid tail)
MIN_PRICE = {"US": 3.0, "CA": 2.0, "TW": 10.0, "IN": 20.0, "CN": 2.0}  # kill penny stocks
# plausibility caps so the current cross-section isn't dominated by pumps / stale / distress
CAPS = {
    "mom_12_1": (0.0, 3.0),  # 0–300%: exclude losers and >300% pumps
    "above_200dma": (0.0, 1.0),  # 0–100% above 200-DMA: uptrend, not blow-off
    "vol_60": (0.008, 0.20),  # exclude near-zero (stale/dead) and chaos
    "book_to_market": (0.2, 8.0),  # sane deep-value band
}


def _prices(market, source):
    if source == "warehouse":
        import warehouse as wh

        return wh.prices(market)
    px = pd.read_parquet(
        os.path.join(BASE, "cache_seed", "ltm", f"{market}.parquet"),
        columns=["Date", "High", "Close", "Volume", "Symbol"],
    )
    px["Date"] = pd.to_datetime(px["Date"])
    return px


def _clean(g):
    """Drop NaN/non-positive closes so trailing gaps (delisted/halted) don't fake low vol."""
    c = pd.to_numeric(g["Close"], errors="coerce").to_numpy()
    v = pd.to_numeric(g["Volume"], errors="coerce").to_numpy()
    m = np.isfinite(c) & (c > 0)
    return c[m], np.where(np.isfinite(v[m]), v[m], 0.0)


def _latest_factor(market, source, factor):
    """Compute the screen factor + liquidity + 6-mo return per symbol at the latest date."""
    px = _prices(market, source).sort_values(["Symbol", "Date"])
    rows = []
    for sym, g in px.groupby("Symbol"):
        c, v = _clean(g)
        if len(c) < 273:
            continue
        dvol = float(np.nanmedian(c[-60:] * v[-60:]))
        if factor == "mom_12_1":
            f = c[-21] / c[-273] - 1
        elif factor == "vol_60":
            r = np.diff(c[-61:]) / c[-61:-1]
            f = float(np.nanstd(r))
        elif factor == "above_200dma":
            f = c[-1] / np.mean(c[-200:-1]) - 1
        else:
            f = np.nan
        rows.append((sym, f, dvol, c[-1], c[-1] / c[-126] - 1))
    df = pd.DataFrame(rows, columns=["symbol", "factor", "dvol", "last", "ret_6m"])
    return df.dropna(subset=["factor", "last", "ret_6m"])


def _us_value():
    """US book-to-market from latest SEC fundamentals + latest close (shares>0 guarded)."""
    fund = pd.read_parquet(
        os.path.join(BASE, "cache_seed", "fundamentals_history", "US.parquet"),
        columns=["ticker", "filed", "equity", "shares"],
    ).dropna(subset=["equity", "shares"])
    fund = fund[(fund["shares"] > 0) & (fund["equity"] > 0)]
    fund = fund.sort_values("filed").groupby("ticker").tail(1)  # most recent filing
    px = _prices("US", "local").sort_values(["Symbol", "Date"])
    rows = []
    for sym, g in px.groupby("Symbol"):
        c, v = _clean(g)
        if len(c) < 126:
            continue
        rows.append((sym, float(np.nanmedian(c[-60:] * v[-60:])), c[-1], c[-1] / c[-126] - 1))
    pr = pd.DataFrame(rows, columns=["symbol", "dvol", "last", "ret_6m"])
    m = fund.merge(pr, left_on="ticker", right_on="symbol")
    m["mktcap"] = m["shares"] * m["last"]
    m = m[m["mktcap"] >= 1e8]  # >= $100M cap
    m["factor"] = m["equity"] / m["mktcap"]  # book/market
    return m[["symbol", "factor", "dvol", "last", "ret_6m"]].dropna(subset=["factor"])


def screen(market, top):
    label, factor, side, keep, source = ROBUST[market]
    df = _us_value() if market == "US" else _latest_factor(market, source, factor)
    if df.empty:
        return label, df
    lo, hi = CAPS[factor]
    df = df[(df["factor"] >= lo) & (df["factor"] <= hi)]  # plausibility
    df = df[df["last"] >= MIN_PRICE[market]]  # no penny stocks
    df = df[df["dvol"] >= df["dvol"].quantile(1 - LIQ_KEEP)]  # most-liquid names only
    if df.empty:
        return label, df
    thr = df["factor"].quantile(1 - keep if side == "top" else keep)
    passed = df[df["factor"] >= thr] if side == "top" else df[df["factor"] <= thr]
    # rank qualifiers by LIQUIDITY (investable representatives), not the most-extreme tail
    return label, passed.sort_values("dvol", ascending=False).head(top)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()
    print("\n" + "=" * 78)
    print(" CURRENT NAMES PASSING THE OOS-ROBUST SCREENERS  (research only — NOT advice)")
    print("=" * 78)
    all_rows = []
    for mkt in ROBUST:
        label, picks = screen(mkt, args.top)
        f = ROBUST[mkt][1]
        unit = "b/m" if f == "book_to_market" else ("vol" if f == "vol_60" else f)
        print(f"\n  {mkt} — {label}  [{f}]")
        print(f"  {'ticker':<14}{unit:>8}{'6-mo ret':>10}{'last':>12}")
        for _, r in picks.iterrows():
            fv = f"{r['factor']:.3f}" if f != "book_to_market" else f"{r['factor']:.2f}"
            print(f"  {r['symbol']:<14}{fv:>8}{r['ret_6m']*100:>9.1f}%{r['last']:>12.2f}")
            all_rows.append(
                {
                    "market": mkt,
                    "screen": label,
                    "factor_name": f,
                    "ticker": r["symbol"],
                    "factor_value": round(float(r["factor"]), 5),
                    "ret_6m": round(float(r["ret_6m"]), 4),
                    "last_price": round(float(r["last"]), 2),
                }
            )
    out = os.path.join(BASE, "reports", "reward_picks.csv")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    pd.DataFrame(all_rows).to_csv(out, index=False)
    print("\n" + "=" * 78)
    print(f" {len(all_rows)} names written → reports/reward_picks.csv")
    print(" ⚠ Educational/research only. Survivorship-flattered, modest edge. Not advice.")
    print("=" * 78 + "\n")


if __name__ == "__main__":
    main()
