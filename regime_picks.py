#!/usr/bin/env python3
"""
regime_picks.py — today's stock picks per market from each market's BEST-BACKTESTED
("preferred") screener, plus a one-line explanation of why that screener is used there.

The preferred screener per market is the winner of the point-in-time backtests
(backtest.py deep 5-market run + backtest_price_sweep.py 15-market sweep; see
screener_findings_mailer.py / the briefing). This module applies that screener to the
LATEST bar of each market's 10y OHLCV (cache_seed/ltm/<MKT>.parquet) and returns the
most-liquid current matches — so the daily brief carries live picks that are consistent
with what actually worked in each market.

  from regime_picks import section_html          # HTML block for build_mailer
  python3 regime_picks.py                         # print a text preview
  python3 regime_picks.py --markets US,IN,TW      # subset
"""
import argparse
import os

import numpy as np

import backtest  # SCREENS predicates + _pit() point-in-time features

try:
    import datalink
except Exception:
    datalink = None

BASE = os.path.expanduser("~/Downloads/code/python_files")

# best screener per market (from the committed backtests). screens are keys of
# backtest.SCREENS: golden_state, golden_crossover, near_high, rsi_oversold, momentum.
PREFERRED = {
    # mean-reversion regime
    "US": "rsi_oversold",
    "KR": "rsi_oversold",
    "CN": "rsi_oversold",
    "JP": "rsi_oversold",
    "DK": "rsi_oversold",
    "SG": "rsi_oversold",
    "ZA": "rsi_oversold",
    # trend / breakout regime
    "IN": "near_high",
    "TW": "momentum",
    "HK": "near_high",
    "CH": "golden_crossover",
    "SE": "golden_crossover",
    "AU": "golden_crossover",
    "SA": "momentum",
    "CA": "near_high",
    "DE": "golden_crossover",
    "FI": "near_high",
    "UK": "near_high",
    "BR": "near_high",
    "EU": "golden_state",
}
WHY = {
    "rsi_oversold": ("Mean-reversion", "buy oversold (RSI&lt;30) — dips snap back in this market"),
    "near_high": ("Trend", "buy strength near the 52-week high — breakouts persist here"),
    "momentum": ("Trend", "buy 6-month winners still above the 200-DMA"),
    "golden_crossover": ("Trend", "buy the fresh 50/200-DMA golden cross"),
    "golden_state": ("Trend", "hold names trading above the 200-DMA"),
}
# markets shown by default in the daily brief (majors + strongest-edge exemplars,
# both regimes). Others are still available via --markets.
DEFAULT_MARKETS = ["IN", "US", "TW", "HK", "DE", "UK", "JP", "KR"]
FLAG = {
    "US": "🇺🇸",
    "IN": "🇮🇳",
    "TW": "🇹🇼",
    "HK": "🇭🇰",
    "DE": "🇩🇪",
    "UK": "🇬🇧",
    "JP": "🇯🇵",
    "KR": "🇰🇷",
    "CN": "🇨🇳",
    "EU": "🇪🇺",
    "CH": "🇨🇭",
    "SE": "🇸🇪",
    "AU": "🇦🇺",
    "SA": "🇸🇦",
    "CA": "🇨🇦",
    "FI": "🇫🇮",
    "BR": "🇧🇷",
    "SG": "🇸🇬",
    "DK": "🇩🇰",
    "ZA": "🇿🇦",
}
CUR = {
    "US": "$",
    "IN": "₹",
    "JP": "¥",
    "KR": "₩",
    "CN": "¥",
    "EU": "€",
    "UK": "£",
    "DE": "€",
    "CH": "Fr",
    "SE": "kr",
    "TW": "NT$",
    "HK": "HK$",
    "SG": "S$",
}


def picks_for(market, top=6):
    """Apply the market's preferred screener to the latest bar; return top-N by liquidity."""
    if datalink is None:
        return []
    screen = PREFERRED.get(market)
    pred = backtest.SCREENS.get(screen)
    if not pred:
        return []
    data = datalink.load_market(market, tier="ltm") or datalink.load_market(market)
    if not data:
        return []
    out = []
    for sym, df in data.items():
        if df is None or len(df) < 220:
            continue
        close = df["Close"].to_numpy("float64")
        vol = df["Volume"].to_numpy("float64") if "Volume" in df else np.zeros(len(close))
        t = len(close) - 1
        if not close[t] or not np.isfinite(close[t]):
            continue
        f = backtest._pit(close, t)
        if not f:
            continue
        try:
            hit = pred(f)
        except Exception:
            hit = False
        if not hit:
            continue
        dvol = float(np.nanmean(close[t - 20 : t] * vol[t - 20 : t])) if t > 20 else 0.0
        ret1m = (close[t] / close[t - 21] - 1) * 100 if t > 21 and close[t - 21] else np.nan
        out.append(
            {
                "symbol": sym,
                "price": float(close[t]),
                "dvol_m": dvol / 1e6,
                "ret1m": ret1m,
                "rsi": f.get("rsi"),
                "from_high": f.get("pct_from_high"),
            }
        )
    out.sort(key=lambda r: r["dvol_m"], reverse=True)
    return out[:top]


def _enrich_trendlyne(picks):
    """Attach current Trendlyne Piotroski + DVM Durability to each pick (India only).
    The backtests show quality is best used as an OVERLAY on breakouts, so a near_high
    pick that is also high-Piotroski is the strongest signal. Best-effort: degrades
    silently if Trendlyne is unreachable."""
    try:
        import trendlyne_auth as tl

        s = tl.session()
    except Exception:
        return picks
    for p in picks:
        try:
            sc = tl.scores(p["symbol"], s)
            p["piotroski"] = sc.get("piotroski")
            p["dvm_dur"] = sc.get("dvm_durability")
        except Exception:
            pass
    return picks


def _rows_html(market, picks):
    cur = CUR.get(market, "")
    has_q = any(p.get("piotroski") is not None for p in picks)  # Trendlyne overlay present
    cells = ""
    for p in picks:
        r1 = f'{p["ret1m"]:+.1f}%' if p["ret1m"] == p["ret1m"] else "—"
        td = 'style="padding:3px 8px;border-bottom:1px solid #eee;font-size:12px'
        qcells = ""
        if has_q:
            f_ = p.get("piotroski")
            dur = p.get("dvm_dur")
            star = " ⭐" if (f_ is not None and f_ >= 7) else ""
            fcol = "#2e7d32" if (f_ is not None and f_ >= 7) else "#333"
            qcells = (
                f'<td {td};text-align:right;color:{fcol};font-weight:600">'
                f'{f_ if f_ is not None else "—"}{star}</td>'
                f'<td {td};text-align:right">{dur if dur is not None else "—"}</td>'
            )
        cells += (
            f'<tr><td {td}"><b>{p["symbol"]}</b></td>'
            f'<td {td};text-align:right">{cur}{p["price"]:,.2f}</td>'
            f'<td {td};text-align:right">{r1}</td>'
            f'<td {td};text-align:right">${p["dvol_m"]:,.1f}M</td>{qcells}</tr>'
        )
    th = 'style="text-align:right;padding:3px 8px;border-bottom:2px solid #1a73e8;font-size:11px"'
    qhead = f"<th {th}>Piotroski</th><th {th}>Durability</th>" if has_q else ""
    return (
        '<table style="border-collapse:collapse;width:100%;margin:2px 0 12px">'
        '<tr><th style="text-align:left;padding:3px 8px;border-bottom:2px solid #1a73e8;font-size:11px">Symbol</th>'
        f"<th {th}>Price</th><th {th}>1-mo</th><th {th}>Liquidity/day</th>{qhead}</tr>"
        f"{cells}</table>"
    )


def section_html(markets=None, top=6):
    """The full 'Regime Picks + Screener Guide' HTML block for the daily brief."""
    markets = markets or DEFAULT_MARKETS
    blocks = ""
    for m in markets:
        screen = PREFERRED.get(m, "—")
        regime, why = WHY.get(screen, ("", ""))
        picks = picks_for(m, top)
        if m == "IN" and picks:  # Trendlyne covers India — add the quality overlay
            picks = _enrich_trendlyne(picks)
        badge = "#c62828" if regime == "Mean-reversion" else "#2e7d32"
        blocks += (
            f'<h3 style="font-size:13px;margin:12px 0 2px">{FLAG.get(m,"")} {m} '
            f'<span style="font-family:monospace;font-size:12px;color:#1a73e8">{screen}</span> '
            f'<span style="font-size:10px;color:#fff;background:{badge};padding:1px 6px;border-radius:10px">{regime}</span></h3>'
            f'<p style="font-size:11px;color:#666;margin:0 0 3px">Why here: {why}.</p>'
            + (
                _rows_html(m, picks)
                if picks
                else '<p style="font-size:12px;color:#999">no current matches</p>'
            )
        )
    guide = (
        '<div style="background:#f1f8e9;border-left:4px solid #2e7d32;padding:8px 12px;'
        'margin:10px 0 4px;font-size:11.5px;color:#33691e;line-height:1.5">'
        "<b>Screener guide (from the backtests).</b> "
        "<b>Price:</b> use <code>rsi_oversold</code> in US/KR/CN/JP/DK/SG; "
        "<code>near_high</code>/<code>momentum</code>/<code>golden_crossover</code> in India, Europe, "
        "HK/TW &amp; resource/EM. "
        "<b>US fundamentals:</b> value beats quality — Graham net-net (+12.4pp) &gt; GARP &gt; Magic "
        "Formula &gt; quality; Piotroski is inverted standalone but is the best <i>overlay</i> on Darvas "
        "breakouts (+9.9pp median, 62% win). Educational only.</div>"
    )
    return (
        '<h2 style="font-size:16px;border-bottom:2px solid #1a73e8;padding-bottom:3px;margin-top:22px">'
        "🎯 Regime Picks — each market screened by its best-backtested filter</h2>"
        '<p style="font-size:11px;color:#555;margin:2px 0 6px">Point-in-time backtests show no single '
        "global screen: mean-reversion pays in the US &amp; developed East Asia, trend/breakout in India, "
        "Europe &amp; HK/TW. Below, each market is screened by <i>its own</i> winning filter, newest bar, "
        "ranked by liquidity. Mechanical filters, not buy/sell advice.</p>"
        f"{guide}{blocks}"
    )


def section_text(markets=None, top=6):
    markets = markets or DEFAULT_MARKETS
    lines = ["Regime Picks (each market screened by its best-backtested filter):"]
    for m in markets:
        screen = PREFERRED.get(m, "—")
        picks = picks_for(m, top)
        syms = ", ".join(p["symbol"] for p in picks) or "none"
        lines.append(f"  {m} [{screen}]: {syms}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Today's picks per market from the preferred screener")
    ap.add_argument("--markets", default="", help="comma list (default: majors + exemplars)")
    ap.add_argument("--top", type=int, default=6)
    args = ap.parse_args()
    markets = [m.strip().upper() for m in args.markets.split(",")] if args.markets else None
    print(section_text(markets, args.top))
    html = section_html(markets, args.top)
    open(os.path.join(BASE, "regime_picks_section.html"), "w").write(html)
    print(f"\nhtml bytes: {len(html)} → regime_picks_section.html")


if __name__ == "__main__":
    main()
