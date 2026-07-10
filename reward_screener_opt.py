#!/usr/bin/env python3
"""
reward_screener_opt.py — REWARD-OPTIMISATION screener discovery for India & US.

Instead of hand-picking a screener (Piotroski, Magic Formula, ...), this searches a
library of ~20 point-in-time fundamental + price factors and *builds* the conjunctive
filter set that maximises a reward, then validates it out-of-sample.

Method (no look-ahead):
  • Panel: one row per (ticker, fiscal-year) from cache_seed/fundamentals_history/<MKT>.
    ENTRY = first trading day after `filed` (US SEC filing date; India = fy_end+90d proxy).
    Forward return over HORIZON trading days, priced off cache_seed/ltm/<MKT>.parquet.
  • Reward: each row's forward return is de-meaned by its ENTRY-YEAR cohort median →
    `excess`. A filter's reward = winsor-robust MEDIAN excess of the names it passes
    (a market-neutral edge vs same-year peers), gated by a minimum sample floor.
  • Factors: profitability (ROA/ROE/margins/CFO), quality (accruals, F-score, current
    ratio, asset turnover, leverage), value (earnings yield, book/market, Magic-Formula
    EY & ROC), growth, and price/momentum (12-1 mom, 1-mo reversal, dist-from-52w-high,
    above-200dma, vol). Each factor is oriented so "more is better".
  • Search: TRAIN = entries with year <= --split, TEST = later years (a true holdout,
    untouched by selection). ALL selection is cross-validated WITHIN train on an early
    vs late fold — a filter must pay in the WORSE fold (overfit guard).
    (1) univariate — best threshold per factor whose worse-fold median-excess is > 0.
    (2) greedy forward-selection — add the filter that most improves the worse-fold
        reward, min-sample floor, stop when no add helps by >= eps or --max-filters hit.
  • Report the discovered screener, its TRAIN edge, and its OUT-OF-SAMPLE (test) edge,
    win-rate, and names/year, with a ROBUST / NOT-robust verdict.

  --source warehouse reads market_data.duckdb (all 19 ex-US markets); --source local
  reads the deep US SEC panel. reward_screener_all.py sweeps every market at once.

Educational/research only — NOT investment advice. Survivorship caveat: ltm holds only
currently-listed names, which flatters every band; trust the RELATIVE (cross-sectional,
cohort-neutral) edge, not the absolute level.

  python3 reward_screener_opt.py --market US --horizon 252
  python3 reward_screener_opt.py --market IN --horizon 252 --fund-dir <dir>
"""
import argparse
import os

import numpy as np
import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")

# ---- factor library ---------------------------------------------------------
# name -> (builder(df, extra)->Series, direction)   direction +1 = high is good.
KEEP_FRACS = [0.5, 0.4, 0.3, 0.2, 0.1]  # keep top / bottom this fraction
N_MIN_TRAIN = 150
N_MIN_TEST = 60
EPS = 0.004  # min reward improvement (0.4pp) to accept another filter


def _load(market, fund_dir, source="local"):
    """Return (fundamentals DataFrame, prices path-or-DataFrame).
    source='warehouse' reads the consolidated market_data.duckdb (all ex-US markets);
    source='local' reads cache_seed parquets (US SEC depth + ebit)."""
    if source == "warehouse":
        import warehouse as wh

        hist = wh.fundamentals(market)
        if hist.empty:
            raise SystemExit(f"no warehouse fundamentals for {market}")
        return hist, wh.prices(market)
    hist = os.path.join(
        fund_dir or os.path.join(BASE, "cache_seed", "fundamentals_history"),
        f"{market}.parquet",
    )
    prices = os.path.join(BASE, "cache_seed", "ltm", f"{market}.parquet")
    if not os.path.exists(hist):
        raise SystemExit(f"missing fundamentals {hist}")
    if not os.path.exists(prices):
        raise SystemExit(f"missing prices {prices}")
    return pd.read_parquet(hist), prices


def _prev(df, col):
    return df.groupby("ticker")[col].shift(1)


def _fscore(df):
    """9-point Piotroski where fields available (needs prior year)."""
    ta, ta1 = df["total_assets"], _prev(df, "total_assets")
    ni = df["net_income"]
    roa, roa1 = ni / ta, _prev(df, "net_income") / ta1
    cfo = df.get("cfo")
    ca, cl = df.get("current_assets"), df.get("current_liabilities")
    cr = ca / cl
    cr1 = _prev(df, "current_assets") / _prev(df, "current_liabilities")
    ltd, ltd1 = df.get("long_term_debt"), _prev(df, "long_term_debt")
    lev, lev1 = ltd / ta, ltd1 / ta1
    sh, sh1 = df.get("shares"), _prev(df, "shares")
    gp = df.get("gross_profit")
    gm, gm1 = gp / df["revenue"], _prev(df, "gross_profit") / _prev(df, "revenue")
    at, at1 = df["revenue"] / ta, _prev(df, "revenue") / ta1
    f = (
        (roa > 0).astype(float)
        + (cfo > 0).astype(float)
        + (roa > roa1).astype(float)
        + ((cfo / ta) > roa).astype(float)
        + (lev < lev1).astype(float)
        + (cr > cr1).astype(float)
        + (sh <= sh1).astype(float)
        + (gm > gm1).astype(float)
        + (at > at1).astype(float)
    )
    return np.where(ta1.notna(), f, np.nan)


def build_factors(df):
    """Attach oriented fundamental factors. Missing inputs -> NaN (row skipped by any
    filter that needs them, but still counts in the cohort baseline)."""
    df = df.sort_values(["ticker", "fy_end"]).copy()
    ni, ta, rev, eq = df["net_income"], df["total_assets"], df["revenue"], df["equity"]
    ca, cl = df.get("current_assets"), df.get("current_liabilities")
    ltd = df.get("long_term_debt")
    gp = df.get("gross_profit")
    ebit = df.get("ebit")
    cfo = df.get("cfo")

    F = {}
    F["roa"] = (ni / ta, +1)
    F["roe"] = (ni / eq.where(eq > 0), +1)
    F["net_margin"] = (ni / rev.where(rev > 0), +1)
    if gp is not None:
        F["gross_margin"] = (gp / rev.where(rev > 0), +1)
    if cfo is not None:
        F["cfo_ta"] = (cfo / ta, +1)
        F["accruals"] = ((ni - cfo) / ta, -1)  # low accruals = high earnings quality
    F["asset_turn"] = (rev / ta, +1)
    if ca is not None and cl is not None:
        F["current_ratio"] = (ca / cl.where(cl > 0), +1)
    if ltd is not None:
        F["leverage"] = (ltd / ta, -1)  # low leverage good
    if ebit is not None:
        F["ebit_margin"] = (ebit / rev.where(rev > 0), +1)
    # growth
    F["rev_growth"] = (rev / _prev(df, "revenue") - 1, +1)
    F["roa_growth"] = (ni / ta - _prev(df, "net_income") / _prev(df, "total_assets"), +1)
    # quality composite
    df["F"] = _fscore(df)
    F["fscore"] = (df["F"], +1)
    for k, (s, d) in F.items():
        df[k] = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
    df.attrs["dirs"] = {k: d for k, (s, d) in F.items()}
    df.attrs["has_ebit"] = ebit is not None
    df.attrs["has_ltd"] = ltd is not None
    return df


def attach_forward_and_price(df, prices_path, horizon):
    """Forward return + value & price/momentum factors evaluated AT ENTRY (filed+1).
    `prices` may be a parquet path or an already-loaded DataFrame (warehouse)."""
    if isinstance(prices_path, pd.DataFrame):
        px = prices_path[["Date", "Close", "Symbol"]].copy()
    else:
        px = pd.read_parquet(prices_path, columns=["Date", "Close", "Symbol"])
    px["Date"] = pd.to_datetime(px["Date"])
    px = px.sort_values(["Symbol", "Date"])
    by = {s: (g["Date"].to_numpy(), g["Close"].to_numpy()) for s, g in px.groupby("Symbol")}

    fwd, mktcap = [], []
    mom_12_1, rev_1m, dist_high, above_200, vol60 = [], [], [], [], []
    for _, r in df.iterrows():
        arr = by.get(str(r["ticker"]).upper())
        filed = r.get("filed")
        if arr is None or not filed or str(filed) in ("9999-99-99", "nan", "NaT"):
            fwd.append(np.nan)
            mktcap.append(np.nan)
            mom_12_1.append(np.nan)
            rev_1m.append(np.nan)
            dist_high.append(np.nan)
            above_200.append(np.nan)
            vol60.append(np.nan)
            continue
        dates, closes = arr
        entry = np.datetime64(str(filed)[:10]) + np.timedelta64(1, "D")
        i = int(np.searchsorted(dates, entry))
        # forward return
        j = i + horizon
        fwd.append(
            closes[j] / closes[i] - 1.0
            if i < len(dates) and j < len(dates) and closes[i] > 0
            else np.nan
        )
        if i >= len(dates) or closes[i] <= 0:
            mktcap.append(np.nan)
            mom_12_1.append(np.nan)
            rev_1m.append(np.nan)
            dist_high.append(np.nan)
            above_200.append(np.nan)
            vol60.append(np.nan)
            continue
        c0 = closes[i]
        mktcap.append(c0 * r["shares"] if pd.notna(r.get("shares")) else np.nan)
        # 12-1 momentum: price 21d ago / price 273d ago (skip the most recent month)
        mom_12_1.append(closes[i - 21] / closes[i - 273] - 1 if i >= 273 else np.nan)
        rev_1m.append(c0 / closes[i - 21] - 1 if i >= 21 else np.nan)  # 1-mo return
        win = closes[max(0, i - 252) : i + 1]
        dist_high.append(c0 / win.max() - 1 if len(win) else np.nan)  # 0=at 52w high
        w200 = closes[max(0, i - 200) : i]
        above_200.append(c0 / w200.mean() - 1 if len(w200) >= 50 else np.nan)
        w60 = closes[max(0, i - 61) : i + 1]
        rets = np.diff(w60) / w60[:-1] if len(w60) > 5 else np.array([np.nan])
        vol60.append(np.nanstd(rets))
    df = df.copy()
    df["fwd"] = fwd
    df["_mktcap"] = mktcap
    dirs = df.attrs.get("dirs", {})
    # value factors (need market cap at entry)
    df["earnings_yield"] = df["net_income"] / df["_mktcap"]
    dirs["earnings_yield"] = +1
    df["book_to_market"] = df["equity"] / df["_mktcap"]
    dirs["book_to_market"] = +1
    if df.attrs.get("has_ebit"):
        ev = df["_mktcap"] + (df["long_term_debt"].fillna(0) if df.attrs.get("has_ltd") else 0)
        df["mf_earn_yield"] = df["ebit"] / ev.where(ev > 0)
        dirs["mf_earn_yield"] = +1
        if "current_liabilities" in df:
            ce = df["total_assets"] - df["current_liabilities"]
            df["mf_roc"] = df["ebit"] / ce.where(ce > 0)
            dirs["mf_roc"] = +1
    # price / momentum factors
    for k, v, d in [
        ("mom_12_1", mom_12_1, +1),
        ("reversal_1m", rev_1m, -1),
        ("dist_52w_high", dist_high, +1),
        ("above_200dma", above_200, +1),
        ("vol_60", vol60, -1),
    ]:
        df[k] = pd.to_numeric(pd.Series(v, index=df.index), errors="coerce")
        df[k] = df[k].replace([np.inf, -np.inf], np.nan)
        dirs[k] = d
    df.attrs["dirs"] = dirs
    df = df.dropna(subset=["fwd"]).copy()
    # winsorise forward return 1/99 pct (for mean reporting only); median is outlier-proof
    lo, hi = df["fwd"].quantile([0.01, 0.99])
    df["fwd_w"] = df["fwd"].clip(lo, hi)
    # cohort-neutral reward: excess vs same entry-year median
    df["ey"] = pd.to_datetime(df["filed"]).dt.year
    df["excess"] = df["fwd"] - df.groupby("ey")["fwd"].transform("median")
    df["excess_w"] = df["fwd_w"] - df.groupby("ey")["fwd_w"].transform("median")
    return df


# ---- reward + search --------------------------------------------------------
def reward(sub):
    """Winsor-robust median excess (primary), plus mean & win-rate."""
    if len(sub) == 0:
        return None
    return {
        "n": len(sub),
        "med": float(sub["excess"].median()),
        "mean": float(sub["excess_w"].mean()),
        "win": float((sub["excess"] > 0).mean()),
    }


def candidates(train, dirs):
    """(factor, op, thr, pct) filters from TRAIN deciles, oriented by direction."""
    out = []
    for f, d in dirs.items():
        if f not in train or train[f].notna().sum() < N_MIN_TRAIN:
            continue
        s = train[f].dropna()
        for keep in KEEP_FRACS:
            if d > 0:  # high good -> keep TOP `keep`
                thr = s.quantile(1 - keep)
                op = ">="
            else:  # low good -> keep BOTTOM `keep`
                thr = s.quantile(keep)
                op = "<="
            out.append((f, op, float(thr), keep))
    return out


def mask_of(df, filters):
    m = pd.Series(True, index=df.index)
    for f, op, thr, _ in filters:
        col = df[f]
        m &= (col >= thr) if op == ">=" else (col <= thr)
        m &= col.notna()
    return m


def evaluate(df, filters):
    return reward(df[mask_of(df, filters)])


def discover(market, source="local", horizon=252, split=2021, max_filters=3, fund_dir=None):
    """Run the full reward-optimised search for one market; return a result dict."""
    mkt = market.upper()
    hist, prices = _load(mkt, fund_dir, source)
    df = build_factors(hist)
    df = attach_forward_and_price(df, prices, horizon)
    dirs = df.attrs["dirs"]
    train = df[df["ey"] <= split]
    test = df[df["ey"] > split]

    tyears = sorted(train["ey"].unique())
    mid = tyears[len(tyears) // 2] if len(tyears) > 1 else split
    foldA, foldB = train[train["ey"] < mid], train[train["ey"] >= mid]
    N_FOLD = max(50, N_MIN_TRAIN // 3)

    def cv(filters):
        ra, rb = evaluate(foldA, filters), evaluate(foldB, filters)
        if not ra or not rb or ra["n"] < N_FOLD or rb["n"] < N_FOLD:
            return None
        return {"med": min(ra["med"], rb["med"]), "na": ra["n"], "nb": rb["n"]}

    # (1) univariate pool: best threshold per factor whose WORSE-fold edge > 0
    best_by_factor = {}
    for filt in candidates(train, dirs):
        c = cv([filt])
        if c and c["med"] > 0:
            f = filt[0]
            if f not in best_by_factor or c["med"] > best_by_factor[f][2]["med"]:
                best_by_factor[f] = (filt, evaluate(train, [filt]), c, evaluate(test, [filt]))
    pool = sorted(best_by_factor.values(), key=lambda x: -x[2]["med"])

    # (2) greedy forward selection scored on the cross-validated (worse-fold) reward
    chosen, used, cur_med = [], set(), -1e9
    while pool and len(chosen) < max_filters:
        best = None
        for filt, *_ in pool:
            if filt[0] in used:
                continue
            c = cv(chosen + [filt])
            if c and c["med"] > (best[1]["med"] if best else -1e9):
                best = (filt, c)
        if not best or best[1]["med"] <= cur_med + EPS:
            break
        chosen.append(best[0])
        used.add(best[0][0])
        cur_med = best[1]["med"]
    if not chosen and pool:
        chosen = [pool[0][0]]

    tr, te, all_r = evaluate(train, chosen), evaluate(test, chosen), evaluate(df, chosen)
    yrs = df[mask_of(df, chosen)]["ey"] if chosen else pd.Series(dtype=int)
    per_yr = yrs.value_counts().mean() if len(yrs) else 0
    robust = bool(te and te["med"] > 0.005 and te["win"] >= 0.50)
    return {
        "market": mkt,
        "source": source,
        "horizon": horizon,
        "split": split,
        "mid": mid,
        "n_panel": len(df),
        "n_train": len(train),
        "n_test": len(test),
        "tickers": int(df["ticker"].nunique()),
        "pool": pool,
        "chosen": chosen,
        "train": tr,
        "test": te,
        "full": all_r,
        "per_yr": per_yr,
        "robust": robust,
    }


def print_report(res):
    m = res
    print(
        f"\n{'='*74}\n REWARD-OPTIMISED SCREENER — {m['market']}  ({m['horizon']}d horizon)\n{'='*74}"
    )
    print(
        f" panel {m['n_panel']:,} obs | train(≤{m['split']}) {m['n_train']:,} | "
        f"test(>{m['split']}) {m['n_test']:,} | {m['tickers']:,} tickers"
    )
    if m["n_train"] < 400 or m["n_test"] < 150:
        print(" ⚠ thin panel — treat results as indicative only")
    print(f"\n Robust factors (positive in BOTH train folds, split@{m['mid']}): {len(m['pool'])}")
    print(
        f" {'factor':<16}{'cut':>10}{'trn_med':>9}{'cv_worse':>9}{'oos_med':>9}{'oos_win':>8}{'oos_n':>7}"
    )
    for filt, rt, c, re in m["pool"][:14]:
        f, op, thr, keep = filt
        re = re or {"med": float("nan"), "win": float("nan"), "n": 0}
        print(
            f" {f:<16}{op+f'{thr:.3g}':>10}{rt['med']*100:>8.1f}%{c['med']*100:>8.1f}%"
            f"{re['med']*100:>8.1f}%{re['win']*100:>7.0f}%{re['n']:>7}"
        )
    if not m["chosen"]:
        print("\n no factor pays in both train folds — no robustly optimisable screen here.")
        print(f"{'='*74}\n")
        return
    print(f"\n{'─'*74}\n  ★ DISCOVERED SCREENER ({len(m['chosen'])} filters):")
    for f, op, thr, keep in m["chosen"]:
        side = "top" if op == ">=" else "bottom"
        print(f"      • {f:<15} {op} {thr:<12.4g}  ({side} {int(keep*100)}%)")
    print(f"{'─'*74}")

    def line(tag, r):
        if not r:
            print(f"  {tag:<10} (no names)")
            return
        print(
            f"  {tag:<10} median_excess {r['med']*100:+6.1f}%   mean_excess(w) {r['mean']*100:+6.1f}%"
            f"   win {r['win']*100:4.0f}%   n={r['n']}"
        )

    line("TRAIN", m["train"])
    line("TEST/OOS", m["test"])
    line("full", m["full"])
    print(f"  avg names selected / year: {m['per_yr']:.0f}")
    if m["robust"]:
        print(
            f"\n  VERDICT: ✅ ROBUST — edge persists out-of-sample "
            f"({m['test']['med']*100:+.1f}% median, {m['test']['win']*100:.0f}% win)."
        )
    else:
        oos = m["test"]["med"] * 100 if m["test"] else float("nan")
        print(
            f"\n  VERDICT: ⚠ NOT robust out-of-sample (OOS median {oos:+.1f}%). With this data "
            f"depth, no durable {m['market']} screener — treat as indicative only."
        )
    print(f"{'='*74}\n")


def main():
    ap = argparse.ArgumentParser(description="Reward-optimised screener discovery")
    ap.add_argument("--market", default="US")
    ap.add_argument("--source", default="local", choices=["local", "warehouse"])
    ap.add_argument("--horizon", type=int, default=252)
    ap.add_argument("--split", type=int, default=2021, help="last TRAIN entry year")
    ap.add_argument("--fund-dir", default=None)
    ap.add_argument("--max-filters", type=int, default=3)
    args = ap.parse_args()
    res = discover(
        args.market, args.source, args.horizon, args.split, args.max_filters, args.fund_dir
    )
    print_report(res)


if __name__ == "__main__":
    main()
