#!/usr/bin/env python3
"""
screener_findings_mailer.py — a one-off RESEARCH BRIEFING email that summarises the
point-in-time backtest program: which screener works best in each market, the US
fundamental-screen ranking, and the Darvas×Piotroski combo result — with a plain-
English justification per market.

Self-contained (inline-styled HTML, same house style as build_mailer.py). Numbers are
the committed backtest outputs (backtest.py / backtest_price_sweep.py / backtest_combo_us.py
/ backtest_piotroski_us.py / global-market-scanners), point-in-time + winsorized median,
survivorship-flattered, GROSS of cost — trust the ordering, not the levels.

  from screener_findings_mailer import build; subj, text, html = build()

  python3 screener_findings_mailer.py               # write screener_findings.html
  python3 screener_findings_mailer.py --send        # build + send via send_mailer.send()
"""
import sys
from datetime import date

BLUE = "#1a73e8"

# ── the analysis, as committed data ─────────────────────────────────────────────
# (market, flag, best_screen, edge_pp, metric_note, regime, why)
REGIME_MAP = [
    # mean-reversion cluster
    (
        "US",
        "🇺🇸",
        "rsi_oversold",
        1.85,
        "21d mean, deep backtest",
        "Mean-reversion",
        "Efficient large-caps overreact then snap back; buying strength/breakouts loses standalone.",
    ),
    (
        "KR",
        "🇰🇷",
        "rsi_oversold",
        2.04,
        "21d mean, deep backtest",
        "Mean-reversion",
        "Developed East-Asia; strongest short-term reversal of the five original markets.",
    ),
    (
        "CN",
        "🇨🇳",
        "rsi_oversold",
        1.06,
        "21d mean, deep backtest",
        "Mean-reversion",
        "Retail-driven A-shares; oversold names bounce.",
    ),
    (
        "JP",
        "🇯🇵",
        "rsi_oversold",
        0.93,
        "21d mean, deep backtest",
        "Mean-reversion",
        "Reversal-prone; momentum only mild.",
    ),
    (
        "DK",
        "🇩🇰",
        "rsi_oversold",
        1.35,
        "21d median, sweep",
        "Mean-reversion",
        "Small, liquidity-thin market; dips revert.",
    ),
    (
        "SG",
        "🇸🇬",
        "rsi_oversold",
        2.04,
        "21d median, sweep",
        "Mean-reversion",
        "Oversold bounces pay; breakouts don't persist.",
    ),
    (
        "ZA",
        "🇿🇦",
        "rsi_oversold",
        3.90,
        "21d median, sweep ⚠",
        "Mean-reversion",
        "Median only — raw price panel has data-quality artifacts; treat level with caution.",
    ),
    # trend / breakout cluster
    (
        "IN",
        "🇮🇳",
        "near_high",
        1.33,
        "21d mean, deep backtest",
        "Trend / breakout",
        "Momentum-friendly; trending retail flows let 52-week-high strength persist.",
    ),
    (
        "TW",
        "🇹🇼",
        "momentum",
        6.12,
        "21d median, sweep",
        "Trend / breakout",
        "Semis/tech momentum — the single strongest trend edge in the study (+6.1pp).",
    ),
    (
        "HK",
        "🇭🇰",
        "near_high",
        3.77,
        "21d median, sweep",
        "Trend / breakout",
        "Breakouts to new highs carry.",
    ),
    (
        "CH",
        "🇨🇭",
        "golden_crossover",
        4.28,
        "21d median, sweep",
        "Trend / breakout",
        "Quality large-caps trend cleanly; the 50/200 cross actually pays here.",
    ),
    (
        "SE",
        "🇸🇪",
        "golden_crossover",
        2.74,
        "21d median, sweep",
        "Trend / breakout",
        "Nordic trend persistence; golden cross works.",
    ),
    (
        "AU",
        "🇦🇺",
        "golden_crossover",
        2.22,
        "21d median, sweep",
        "Trend / breakout",
        "Resource-heavy trending market.",
    ),
    (
        "SA",
        "🇸🇦",
        "momentum",
        2.09,
        "21d median, sweep",
        "Trend / breakout",
        "Highest win-rate (58%) on momentum; strong directional persistence.",
    ),
    (
        "CA",
        "🇨🇦",
        "near_high",
        2.05,
        "21d median, sweep",
        "Trend / breakout",
        "Resource/EM trend; new-high breakouts pay.",
    ),
    (
        "DE",
        "🇩🇪",
        "golden_crossover",
        1.43,
        "21d median, sweep",
        "Trend / breakout",
        "Trend-following; cross confirms.",
    ),
    (
        "FI",
        "🇫🇮",
        "near_high",
        1.08,
        "21d median, sweep",
        "Trend / breakout",
        "Breakout strength persists.",
    ),
    (
        "UK",
        "🇬🇧",
        "near_high",
        0.89,
        "21d median, sweep",
        "Trend / breakout",
        "Mild breakout edge; overall low predictability.",
    ),
    (
        "BR",
        "🇧🇷",
        "near_high",
        0.83,
        "21d median, sweep",
        "Trend / breakout",
        "EM trend, but thin/low win-rate — weakest signal in the set.",
    ),
    (
        "EU",
        "🇪🇺",
        "golden_state",
        0.48,
        "21d median, sweep",
        "Trend / breakout",
        "Aggregate Europe: staying above the 200-DMA is the most consistent (12/15) edge.",
    ),
]

# US fundamental screens, standalone (252d median edge, point-in-time)
US_FUNDAMENTAL = [
    (
        "net_net",
        "Graham NCAV (mcap < net current assets)",
        12.4,
        60,
        "Deep value — strongest; rare (~4.5k obs).",
    ),
    ("garp", "PEG ≤ 1 & earnings growth ≥ 15%", 5.9, 60, "Growth at a reasonable price pays."),
    (
        "magic",
        "Magic Formula (EY ≥ 8% & ROC ≥ 15%)",
        5.8,
        58,
        "Greenblatt cheap-and-good; confirmed.",
    ),
    ("quality", "ROCE ≥ 15% & D/E ≤ 1", 4.3, 57, "Steady, lower blow-up rate."),
    (
        "piotroski7",
        "Piotroski F-Score ≥ 7",
        3.4,
        56,
        "Median-positive but MEAN-inverted (−3.9) — see combo.",
    ),
    ("lowdebt", "Long-term debt fell YoY", 0.2, 52, "No standalone edge."),
]


def _table(headers, rows, sizes=None):
    th = "".join(
        f'<th style="text-align:left;padding:5px 8px;border-bottom:2px solid {BLUE};font-size:12px">{h}</th>'
        for h in headers
    )
    body = ""
    for r in rows:
        tds = "".join(
            f'<td style="padding:4px 8px;border-bottom:1px solid #eee;font-size:12px;vertical-align:top">{c}</td>'
            for c in r
        )
        body += f"<tr>{tds}</tr>"
    return (
        f'<table style="border-collapse:collapse;width:100%;margin:4px 0 10px">{th}{body}</table>'
    )


def _regime_rows():
    rows = []
    for mkt, flag, screen, edge, note, regime, why in REGIME_MAP:
        color = "#2e7d32" if edge > 0 else "#bf360c"
        rows.append(
            [
                f"{flag} <b>{mkt}</b>",
                f"<code>{screen}</code>",
                f'<b style="color:{color}">{edge:+.2f}pp</b>',
                f'<span style="color:#888;font-size:11px">{note}</span>',
                why,
            ]
        )
    return rows


def _fund_rows():
    rows = []
    for slug, desc, edge, win, why in US_FUNDAMENTAL:
        rows.append(
            [
                f"<code>{slug}</code>",
                desc,
                f'<b style="color:#2e7d32">{edge:+.1f}pp</b>',
                f"{win}%",
                why,
            ]
        )
    return rows


def build():
    today = date.today().isoformat()
    regime_rows = _regime_rows()
    fund_rows = _fund_rows()

    html = f"""<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:740px;color:#1a1a1a">
<h1 style="font-size:21px;margin:0 0 2px">🔬 Screener Backtest Briefing — {today}</h1>
<p style="color:#666;font-size:13px;margin:0 0 14px">Point-in-time, walk-forward results across 20 markets: which screen works where, why, and the US fundamental-screen ranking. Median (outlier-proof) edge vs an equal-weight baseline. Research/education only.</p>

<h2 style="font-size:16px;border-bottom:2px solid {BLUE};padding-bottom:3px">① Executive summary</h2>
<ul style="font-size:13px;line-height:1.5;margin:6px 0 14px;padding-left:18px">
  <li><b>There is no single global screen.</b> Markets split cleanly into two regimes: <b>mean-reversion</b> (buy oversold) vs <b>trend / breakout</b> (buy strength).</li>
  <li><b>Mean-reversion wins in the US + developed East Asia</b> (US, KR, CN, JP) and a few thin markets (DK, SG, ZA). <b>Trend/breakout wins in India + most of Europe + HK/TW and the resource/EM markets.</b></li>
  <li><b>On US <i>fundamentals</i>, value beats quality.</b> Graham net-nets, GARP and Magic Formula pay; Piotroski is <i>inverted</i> as a standalone signal.</li>
  <li><b>But Piotroski shines as an <i>overlay</i>:</b> Darvas breakouts gated by F≥7 give the best risk-adjusted combo (+9.9pp median, 62% win at 1y) — the whole beats the parts.</li>
  <li><b>The classic Golden Cross is <i>not</i> useless everywhere</b> — it's the top screen in CH, SE, AU, DE even though it was the worst in the original US/KR/IN/CN/JP test.</li>
</ul>

<h2 style="font-size:16px;border-bottom:2px solid {BLUE};padding-bottom:3px;margin-top:20px">② Best screen per market — and why</h2>
{_table(["Market", "Best screen", "Edge", "Basis", "Justification"], regime_rows)}
<p style="font-size:11px;color:#666;margin:2px 0">Edge = screen median 21-day forward return − market median. US/KR/IN/CN/JP from the 10y deep backtest (mean edge); the other 15 from the winsorized-median sweep. ⚠ ZA/UK raw price panels have data-quality artifacts — median is usable, mean is not.</p>

<h2 style="font-size:16px;border-bottom:2px solid {BLUE};padding-bottom:3px;margin-top:20px">③ Why the split? (the regime logic)</h2>
<p style="font-size:13px;line-height:1.5;margin:6px 0"><b style="color:#c62828">Mean-reversion markets (US, KR, CN, JP, DK, SG, ZA).</b> Deep, efficient or heavily retail-arbitraged books: sharp moves overshoot and snap back within weeks, so <code>rsi_oversold</code> (RSI&lt;30) buys the bounce. Buying 52-week-high strength here <i>loses</i> — you're paying up right before the reversion.</p>
<p style="font-size:13px;line-height:1.5;margin:6px 0"><b style="color:#2e7d32">Trend / breakout markets (India, most of Europe, HK, TW, CA, BR, SA, AU).</b> Flows are stickier and information diffuses slowly, so strength persists: <code>near_high</code> (new-high breakouts), <code>momentum</code> (6-mo winners above the 200-DMA) and even the <code>golden_crossover</code> keep paying. India is the archetype — its <code>rsi_oversold</code> edge is near zero while <code>near_high</code> and <code>momentum</code> are firmly positive. TW (semiconductors) shows the strongest single trend edge (+6.1pp).</p>
<p style="font-size:13px;line-height:1.5;margin:6px 0"><b>Independent confirmation.</b> A per-market ML factor model (Ridge on 10y price factors) <i>learned</i> the same split without being told — positive trend/momentum weights for India & Europe, negative for the US where it learned "buy oversold." Two methods, one map.</p>

<h2 style="font-size:16px;border-bottom:2px solid {BLUE};padding-bottom:3px;margin-top:20px">④ US fundamental screens (screener.in-style, 252-day, point-in-time)</h2>
{_table(["Screen", "Definition", "Median edge", "Win%", "Read"], fund_rows)}
<p style="font-size:13px;line-height:1.5;margin:6px 0"><b>Value beats quality on US.</b> Deep-value (Graham net-net +12.4pp), GARP (+5.9) and Magic Formula (+5.8) lead; pure quality (Piotroski, low-debt) does not pay as a stock-picker. Piotroski F≥7 is even mean-<i>inverted</i> (−3.9pp) — buying "high-quality" names broadly underperforms.</p>
<div style="background:#f1f8e9;border-left:4px solid #2e7d32;padding:8px 12px;margin:8px 0;font-size:13px;line-height:1.5">
<b>⭐ The key combination — Darvas × Piotroski.</b> Neither is strong alone (Darvas breakout +2.2pp median; Piotroski +3.4 median / −3.9 mean), but using F≥7 as a <b>quality overlay on breakouts</b> yields the best combo: <b>+9.9pp median edge, 62% win-rate, and it flips the winsorized mean positive (+2.6)</b> at a 1-year hold. Piotroski fails as a stock-picker but works as a <i>ranker of momentum names</i> — verified point-in-time on our SEC-EDGAR data, matching the global-market-scanners finding that F≥7 lifted Darvas returns 15%→21%/yr.
</div>

<h2 style="font-size:16px;border-bottom:2px solid {BLUE};padding-bottom:3px;margin-top:20px">⑤ Practical takeaways</h2>
<ul style="font-size:13px;line-height:1.5;margin:6px 0 12px;padding-left:18px">
  <li><b>Match the screen to the regime:</b> run <code>rsi_oversold</code> in US/KR/CN/JP/DK/SG; run <code>near_high</code>/<code>momentum</code>/<code>golden_crossover</code> in India, Europe, HK/TW and the EM/resource markets.</li>
  <li><b>For US fundamentals</b>, prefer value (net-net, GARP, Magic Formula) over quality; use Piotroski only as a <i>breakout overlay</i>, never standalone.</li>
  <li><b>Coming next:</b> the India fundamental history (screener.in) is being collected — it will let us test Piotroski, CCC and Bull-Cartel on India, which US SEC data can't support.</li>
</ul>

<p style="font-size:11px;color:#bf360c;border-top:1px solid #eee;padding-top:10px;margin-top:16px">⚠️ Educational/research only. NOT investment advice. All figures are historical, point-in-time backtests on a survivorship-limited universe (only currently-listed names) and are GROSS of transaction costs, taxes and slippage — after per-market costs (India ~0.30%, US ~0.10%, Europe ~0.40% round-trip) several marginal edges disappear. Trust the direction/ordering, not the magnitudes. Screener results are mechanical filters, not buy/sell signals. Past performance does not guarantee future returns. Consult a SEBI-registered / licensed investment adviser before acting.</p>
</div>"""

    text = (
        f"Screener Backtest Briefing — {today}\n\n"
        "No single global screen. Two regimes:\n"
        "  Mean-reversion (buy oversold): US, KR, CN, JP, DK, SG, ZA.\n"
        "  Trend/breakout (buy strength): India, most of Europe, HK, TW, CA, BR, SA, AU.\n\n"
        "US fundamentals (252d median edge): net_net +12.4 > GARP +5.9 > Magic +5.8 > "
        "quality +4.3 > Piotroski +3.4 > lowdebt +0.2. Value beats quality; Piotroski inverted standalone.\n"
        "Key combo: Darvas x Piotroski(F>=7) = +9.9pp median, 62% win at 1y — quality as a breakout overlay.\n\n"
        "Educational/research only. Point-in-time, survivorship-limited, gross of cost. NOT investment advice."
    )
    subject = f"🔬 Screener Backtest Briefing — best screen per market — {today}"
    return subject, text, html


if __name__ == "__main__":
    s, t, h = build()
    if "--send" in sys.argv:
        try:
            from send_mailer import send

            ok = send(s, t, h)
            print("sent" if ok else "not sent (no creds) — saved screener_findings.html")
        except Exception as e:
            print(f"send failed ({e}); saving html")
    open("screener_findings.html", "w").write(h)
    print(s, "\n\nhtml bytes:", len(h), "→ screener_findings.html")
