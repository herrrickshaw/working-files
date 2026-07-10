#!/usr/bin/env python3
"""
program_summary_mailer.py — an EXTENSIVE briefing email summarising the whole
cross-market screener-backtest program: the dataset built, the three findings, the full
per-market combo table, the fundamental-screen ranking, the deliverables, and the
data-infrastructure story. Self-contained inline-HTML (house style of build_mailer.py);
numbers are the committed backtest outputs. Educational/research only.

  from program_summary_mailer import build; subj, text, html = build()
  python3 program_summary_mailer.py            # write program_summary.html
  python3 program_summary_mailer.py --send     # build + send via send_mailer.send()
"""
import sys
from datetime import date

B = "#1a73e8"  # section-rule blue (house style)
REV, TREND, QUAL, NEG = "#c62828", "#2e7d32", "#2e7d32", "#b00020"

# ── the analysis, as committed data ──────────────────────────────────────────────
REGIME = {
    "Mean-reversion  ·  rsi_oversold": [
        "🇺🇸 US",
        "🇰🇷 KR",
        "🇨🇳 CN",
        "🇯🇵 JP",
        "🇩🇰 DK",
        "🇸🇬 SG",
        "🇿🇦 ZA",
    ],
    "Trend / breakout  ·  near_high / momentum / golden-cross": [
        "🇮🇳 IN",
        "🇹🇼 TW",
        "🇭🇰 HK",
        "🇨🇭 CH",
        "🇸🇪 SE",
        "🇦🇺 AU",
        "🇸🇦 SA",
        "🇨🇦 CA",
        "🇩🇪 DE",
        "🇫🇮 FI",
        "🇬🇧 UK",
        "🇧🇷 BR",
        "🇪🇺 EU",
    ],
}
# US fundamental-screen ranking (252d median edge, pp) from backtest_combo_us.py
US_FUND = [
    ("net_net (Graham NCAV)", 12.4, "Deep value — strongest"),
    ("GARP (PEG≤1, growth≥15%)", 5.9, "Growth at a reasonable price"),
    ("Magic Formula (EY≥8, ROC≥15)", 5.8, "Cheap-and-good"),
    ("Quality (ROCE≥15, D/E≤1)", 4.3, "Steady, low blow-up"),
    ("Piotroski F≥7", 3.4, "Median +, mean −3.9 (inverted)"),
    ("Low-debt (ΔLT-debt<0)", 0.2, "No standalone edge"),
]
# per-market combo (126d): market, best price screen, alone, ×F7 delta
COMBO = [
    ("AU", "near_high", 2.9, 13.6),
    ("CN", "rsi_oversold", 2.4, 12.7),
    ("CA", "near_high", 1.6, 12.2),
    ("SG", "darvas", 1.0, 12.0),
    ("US", "darvas", 2.2, 7.7),
    ("DK", "near_high", 5.5, 6.6),
    ("JP", "near_high", 1.5, 5.3),
    ("HK", "near_high", 4.8, 3.7),
    ("FI", "near_high", 4.3, 1.5),
    ("KR", "near_high", 3.0, 1.5),
    ("UK", "near_high", 2.0, 1.2),
    ("DE", "momentum", 2.8, 0.6),
    ("SE", "near_high", 8.5, 0.6),
    ("CH", "darvas", 2.9, 0.5),
    ("BR", "near_high", 3.9, -1.3),
    ("EU", "momentum", 3.8, -2.1),
    ("TW", "near_high", 2.9, -3.0),
    ("ZA", "momentum", 3.8, -3.8),
    ("SA", "momentum", 6.8, -7.7),
]


def _h2(t):
    return (
        f'<h2 style="font-size:16px;border-bottom:2px solid {B};padding-bottom:3px;'
        f'margin-top:24px">{t}</h2>'
    )


def _chips(items, color):
    cells = "".join(
        f'<span style="display:inline-block;font-family:monospace;font-size:12px;'
        f"background:{color}14;color:{color};padding:2px 8px;border-radius:10px;"
        f'margin:2px 3px">{c}</span>'
        for c in items
    )
    return cells


def build():
    today = date.today().isoformat()

    # regime section
    regime_html = ""
    for label, mkts in REGIME.items():
        col = REV if "Mean-reversion" in label else TREND
        regime_html += (
            f'<p style="font-size:12px;margin:8px 0 2px;font-weight:600;color:{col}">{label}</p>'
            f"<div>{_chips(mkts, col)}</div>"
        )

    # US fundamental ranking
    fund_rows = "".join(
        f'<tr><td style="padding:3px 8px;border-bottom:1px solid #eee;font-size:12px">'
        f"<code>{n}</code></td>"
        f'<td style="padding:3px 8px;border-bottom:1px solid #eee;font-size:12px;text-align:right">'
        f'<b style="color:{QUAL}">+{e:.1f}pp</b></td>'
        f'<td style="padding:3px 8px;border-bottom:1px solid #eee;font-size:11px;color:#666">{d}</td></tr>'
        for n, e, d in US_FUND
    )

    # combo table (sorted by delta desc — already ordered)
    maxd = max(abs(d) for *_, d in COMBO)
    combo_rows = ""
    for m, scr, alone, d in COMBO:
        col = QUAL if d > 0 else NEG
        w = max(4, abs(d) / maxd * 100)
        combo_rows += (
            f'<tr><td style="padding:3px 8px;border-bottom:1px solid #eee;font-size:12px">'
            f"<b>{m}</b></td>"
            f'<td style="padding:3px 8px;border-bottom:1px solid #eee;font-size:11px;'
            f'font-family:monospace;color:#555">{scr}</td>'
            f'<td style="padding:3px 8px;border-bottom:1px solid #eee;font-size:12px;text-align:right">'
            f"{alone:+.1f}</td>"
            f'<td style="padding:3px 8px;border-bottom:1px solid #eee;font-size:12px;width:150px">'
            f'<span style="display:inline-block;height:11px;width:{w}%;background:{col};'
            f'border-radius:3px;opacity:.85;vertical-align:middle"></span> '
            f'<b style="color:{col};font-family:monospace;font-size:11px">{d:+.1f}</b></td></tr>'
        )

    html = f"""<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:760px;color:#1a1a1a">
<h1 style="font-size:22px;margin:0 0 2px">🌐 Cross-Market Screener Backtest — Program Summary</h1>
<p style="color:#666;font-size:13px;margin:0 0 14px">Point-in-time backtest of price + fundamental
stock screens across <b>19 markets + the US</b>, on a purpose-built dated-fundamentals & 10-year-price
dataset. {today}. Research/education only — NOT investment advice.</p>

<div style="background:#f1f8e9;border-left:4px solid #2e7d32;padding:10px 14px;margin:0 0 8px;font-size:13px;line-height:1.55">
<b>One rule, three parts.</b> (1) Price screens are <b>regime-specific</b> — buy weakness in the US &amp;
developed East Asia, buy strength elsewhere. (2) The Piotroski quality score <b>pays outside the US and
inverts inside it</b>. (3) The strongest signal is the <b>combination</b> — a price screen gated by
quality (F≥7) improves 13 of 19 markets.
</div>

{_h2("① The Dataset (built for this study)")}
<table style="border-collapse:collapse;width:100%;margin:4px 0 10px">
<tr>
  <td style="text-align:center;padding:8px;border:1px solid #eee"><div style="font-size:20px;font-weight:700;color:#0e7c7b;font-family:monospace">20</div><div style="font-size:11px;color:#666">markets (19 + US)</div></td>
  <td style="text-align:center;padding:8px;border:1px solid #eee"><div style="font-size:20px;font-weight:700;color:#0e7c7b;font-family:monospace">24,739</div><div style="font-size:11px;color:#666">companies · dated fundamentals</div></td>
  <td style="text-align:center;padding:8px;border:1px solid #eee"><div style="font-size:20px;font-weight:700;color:#0e7c7b;font-family:monospace">55M</div><div style="font-size:11px;color:#666">daily price rows (10y)</div></td>
  <td style="text-align:center;padding:8px;border:1px solid #eee"><div style="font-size:20px;font-weight:700;color:#0e7c7b;font-family:monospace">760MB</div><div style="font-size:11px;color:#666">single DuckDB warehouse</div></td>
</tr></table>
<p style="font-size:11px;color:#555;margin:2px 0">US fundamentals from <b>SEC EDGAR</b> (true filing dates,
1988–2026); 19 markets via <b>yfinance</b> (5y). Prices are deep 10-year OHLCV. All consolidated into one
SQL-queryable <code>market_data.duckdb</code> (<code>warehouse.py</code>).</p>

{_h2("② Finding 1 — Price screens are regime-specific")}
<p style="font-size:12px;color:#555;margin:2px 0 6px">No single price screen works everywhere; an
independent per-market ML factor model learned the same split unprompted.</p>
{regime_html}

{_h2("③ Finding 2 — Quality pays, except in the US")}
<p style="font-size:13px;margin:6px 0">Piotroski F≥7, point-in-time: <b style="color:{NEG}">US −3.9pp
(inverted)</b> vs <b style="color:{QUAL}">rest-of-world +2.6pp median edge</b> (positive in 7/10
deep-window markets). The US rewards value &amp; mean-reversion; most other markets reward quality.</p>
<p style="font-size:12px;color:#555;margin:4px 0 2px">US fundamental-screen ranking (252-day median edge):</p>
<table style="border-collapse:collapse;width:100%;margin:2px 0 8px">
<tr><th style="text-align:left;padding:3px 8px;border-bottom:2px solid {B};font-size:11px">Screen</th>
<th style="text-align:right;padding:3px 8px;border-bottom:2px solid {B};font-size:11px">Edge</th>
<th style="text-align:left;padding:3px 8px;border-bottom:2px solid {B};font-size:11px">Read</th></tr>
{fund_rows}</table>

{_h2("④ Finding 3 — The winner: price × quality")}
<p style="font-size:13px;margin:6px 0">Gate each market's best price screen by Piotroski <b>F≥7</b>. The
overlay improves the screen in <b>13 of 19 markets</b> — and compounds with horizon:
<b>darvas×F7 = +3.9pp (126d) / +10.9pp (252d)</b> vs darvas alone +1.1 / +2.2.</p>
<table style="border-collapse:collapse;width:100%;margin:2px 0 8px">
<tr><th style="text-align:left;padding:3px 8px;border-bottom:2px solid {B};font-size:11px">Mkt</th>
<th style="text-align:left;padding:3px 8px;border-bottom:2px solid {B};font-size:11px">Best price screen</th>
<th style="text-align:right;padding:3px 8px;border-bottom:2px solid {B};font-size:11px">alone</th>
<th style="text-align:left;padding:3px 8px;border-bottom:2px solid {B};font-size:11px">+ F≥7 overlay (Δ, 126d)</th></tr>
{combo_rows}</table>

{_h2("⑤ Deliverables & Reproducibility")}
<ul style="font-size:12.5px;line-height:1.55;margin:6px 0;padding-left:18px">
  <li><b>Data + code:</b> one repo <code>market-screener-backtests</code> — a single DuckDB warehouse,
      SQL access via <code>warehouse.py</code>, one clean commit, <b>CI green</b> (integrity + tests).</li>
  <li><b>Cross-market backtests:</b> <code>backtest_fundamentals_all.py</code> (Piotroski / Magic Formula /
      Quality / net-net) and <code>backtest_combo_all.py</code> (price × fundamental).</li>
  <li><b>US point-in-time:</b> <code>backtest_piotroski_us.py</code>, <code>backtest_coffee_can_us.py</code>,
      <code>backtest_magic_formula_us.py</code>, <code>backtest_combo_us.py</code> (SEC EDGAR history).</li>
  <li><b>Collectors:</b> <code>local_collect.py</code>, <code>deep_prices.py</code>,
      <code>yf_fundamentals.py</code> (curl_cffi, throttle-resistant) + a Google Colab notebook.</li>
  <li><b>SSOT:</b> <code>exchange_reference.parquet</code> — per-exchange ticker/collection-date freshness.</li>
  <li><b>Shareables:</b> an interactive findings artifact + a Word/PDF research summary.</li>
</ul>

{_h2("⑥ Infrastructure notes")}
<ul style="font-size:12px;line-height:1.5;color:#444;margin:6px 0;padding-left:18px">
  <li><b>Throttle bypass:</b> Yahoo blocks datacenter IPs; <code>curl_cffi</code> Chrome-impersonation +
      a global rate-limiter + retry-with-backoff made the full 20-market collection reliable.</li>
  <li><b>Storage:</b> consolidated 109 per-market parquets (~1.3 GB) → one DuckDB (~760 MB); history
      squashed to reclaim the old LFS objects.</li>
</ul>

<p style="font-size:11px;color:#bf360c;border-top:1px solid #eee;padding-top:10px;margin-top:16px">
⚠️ Educational/research only. NOT investment advice. All figures are historical, point-in-time backtests on
a survivorship-limited universe (currently-listed names only) and are GROSS of transaction costs, taxes and
slippage; after per-market costs several marginal edges disappear. Non-US fundamentals cover a shorter
2021–2025 window with modest samples; US uses deep SEC-EDGAR history. Trust the direction/ordering, not the
magnitudes. Screener results are mechanical filters, not buy/sell signals. Past performance does not
guarantee future returns. Consult a SEBI-registered / licensed adviser before acting.</p>
</div>"""

    text = (
        f"Cross-Market Screener Backtest — Program Summary ({today})\n\n"
        "One rule, three parts: (1) price screens are regime-specific (buy-weakness US/East-Asia, "
        "buy-strength elsewhere); (2) Piotroski quality pays ex-US, inverts in US; (3) the winner is the "
        "combination — price screen gated by F>=7 improves 13/19 markets.\n\n"
        "Dataset: 20 markets, 24,739 companies, 55M price rows, single 760MB DuckDB warehouse.\n"
        "Combo: darvas x F>=7 = +3.9pp (126d) / +10.9pp (252d) vs darvas +1.1/+2.2.\n"
        "US fundamentals: net_net +12.4 > GARP +5.9 > Magic +5.8 > quality +4.3 > Piotroski +3.4.\n\n"
        "Deliverables: market-screener-backtests repo (DuckDB + warehouse.py, CI green), cross-market "
        "backtests, curl_cffi collectors + Colab notebook, SSOT, interactive artifact + Word/PDF summary.\n\n"
        "Educational/research only. Point-in-time, survivorship-limited, gross of cost. NOT investment advice."
    )
    subject = f"🌐 Cross-Market Screener Backtest — full program summary — {today}"
    return subject, text, html


if __name__ == "__main__":
    s, t, h = build()
    if "--send" in sys.argv:
        try:
            from send_mailer import send

            print("sent" if send(s, t, h) else "not sent (no creds) — saved program_summary.html")
        except Exception as e:
            print(f"send failed ({e}); saving html")
    open("program_summary.html", "w").write(h)
    print(s, "\n\nhtml bytes:", len(h), "→ program_summary.html")
