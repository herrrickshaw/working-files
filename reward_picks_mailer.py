#!/usr/bin/env python3
"""
reward_picks_mailer.py — HTML/text section for the daily mailer that (1) explains the
reward-optimised, out-of-sample-validated screener, and (2) lists the names currently
passing it in the markets where the edge actually held out of sample.

Data: reports/reward_screeners_252d.csv (per-market discovered screener + OOS stats) and
reports/reward_picks.csv (current names), both produced by reward_screener_opt.py /
reward_screener_all.py / reward_screener_picks.py. If either file is missing the section
degrades to just the explanation (no picks) so the mailer never breaks.

  from reward_picks_mailer import section_html, section_text
  python3 reward_picks_mailer.py            # print a text preview

⚠ Educational/research only — NOT investment advice.
"""
import os

import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
FONT = "-apple-system,Segoe UI,Roboto,Arial,sans-serif"
SCREENS = os.path.join(BASE, "reports", "reward_screeners_252d.csv")
PICKS = os.path.join(BASE, "reports", "reward_picks.csv")

FLAG = {"US": "🇺🇸", "CA": "🇨🇦", "TW": "🇹🇼", "IN": "🇮🇳", "CN": "🇨🇳"}
CCY = {"US": "$", "CA": "C$", "TW": "NT$", "IN": "₹", "CN": "¥"}
# one-liner: what the discovered factor is, and why it is the edge in that market
STYLE = {
    "book_to_market": ("deep value", "cheapest decile by book/price — value pays in the US"),
    "mom_12_1": ("12-month momentum", "last year's winners keep winning here"),
    "vol_60": ("low volatility", "calmest names beat the market cross-section here"),
    "above_200dma": ("uptrend", "names trading above their 200-day average"),
}
# light company-name map for the large caps that surface most; unknown → ticker only
NAMES = {
    "KHC": "Kraft Heinz",
    "CMCSA": "Comcast",
    "TFC": "Truist",
    "AIG": "AIG",
    "LEN": "Lennar",
    "CAG": "ConAgra",
    "GPN": "Global Payments",
    "VICI": "VICI Props",
    "CLF": "Cleveland-Cliffs",
    "RIG": "Transocean",
    "MSTR": "MicroStrategy",
    "TD.TO": "TD Bank",
    "SU.TO": "Suncor",
    "CM.TO": "CIBC",
    "CVE.TO": "Cenovus",
    "CLS.TO": "Celestica",
    "MG.TO": "Magna",
    "ABX.TO": "Barrick",
    "ATZ.TO": "Aritzia",
    "2330.TW": "TSMC",
    "2317.TW": "Hon Hai",
    "2882.TW": "Cathay Fin",
    "2881.TW": "Fubon",
    "2382.TW": "Quanta",
    "2891.TW": "CTBC",
    "2357.TW": "Asus",
    "300750.SZ": "CATL",
    "600519.SS": "Kweichow Moutai",
    "000063.SZ": "ZTE",
    "601899.SS": "Zijin Mining",
    "300059.SZ": "East Money",
    "002371.SZ": "NAURA",
    "ADANIPOWER": "Adani Power",
    "ADANIGREEN": "Adani Green",
    "ADANIENT": "Adani Ent",
    "ADANIPORTS": "Adani Ports",
    "BHEL": "BHEL",
    "POWERINDIA": "Hitachi Energy",
    "MCX": "MCX",
    "BSE": "BSE Ltd",
    "NETWEB": "Netweb",
}


def _load():
    if not os.path.exists(SCREENS) or not os.path.exists(PICKS):
        return None, None
    scr = pd.read_csv(SCREENS)
    scr = scr[scr["robust"]].copy()
    return scr, pd.read_csv(PICKS)


def _order(scr):
    return scr.sort_values("oos_med", ascending=False)["market"].tolist()


def _explain_html():
    return (
        f'<div style="background:#eef3fb;border-left:4px solid #1a73e8;padding:9px 13px;'
        f'margin:6px 0 12px;font-size:12px;color:#20364f;line-height:1.55;font-family:{FONT}">'
        "<b>What is an out-of-sample screener?</b> Rather than trusting a fixed recipe "
        "(Piotroski, Magic Formula…), we let the data choose. Across ~20 point-in-time "
        "factors — value, quality, growth, momentum, volatility — a search builds the "
        "filter set that most rewards a market-neutral edge (median return vs same-year "
        "peers). The guard against curve-fitting: every filter is <b>trained on early "
        "years and then tested on later years it never saw</b>. Only screens whose edge "
        "<b>persisted on that unseen data</b> are shown below. "
        "It survives in just <b>5 of 20 markets</b>: the US is the only one where "
        "<b>fundamentals</b> (deep value) win out-of-sample; everywhere else the durable "
        "edge is a <b>price/risk</b> factor (momentum, low-volatility, trend). "
        '<span style="color:#8a6d00">Edges are modest and survivorship-flattered — '
        "research only, not advice.</span></div>"
    )


def _picks_table(mkt, rows):
    ccy = CCY.get(mkt, "")
    th = "text-align:right;padding:3px 7px;border-bottom:2px solid #1a73e8;font-size:10.5px;color:#555"
    head = (
        '<table style="border-collapse:collapse;width:100%;margin:2px 0 10px">'
        f'<tr><th style="text-align:left;padding:3px 7px;border-bottom:2px solid #1a73e8;'
        f'font-size:10.5px;color:#555">Name</th>'
        f'<th style="{th}">Ticker</th><th style="{th}">6-mo</th><th style="{th}">Last</th></tr>'
    )
    body = ""
    for _, r in rows.iterrows():
        tk = str(r["ticker"])
        nm = NAMES.get(tk, "")
        ret = r["ret_6m"] * 100 if pd.notna(r["ret_6m"]) else float("nan")
        rc = "#2e7d32" if ret >= 0 else "#c62828"
        td = "padding:3px 7px;border-bottom:1px solid #eee;font-size:11.5px"
        body += (
            f'<tr><td style="{td};color:#333">{nm or "—"}</td>'
            f'<td style="{td};text-align:right;font-family:monospace;color:#1a73e8">{tk}</td>'
            f'<td style="{td};text-align:right;color:{rc}">{ret:+.0f}%</td>'
            f'<td style="{td};text-align:right;color:#333">{ccy}{r["last_price"]:,.2f}</td></tr>'
        )
    return head + body + "</table>"


def section_html(top=8):
    scr, picks = _load()
    head = (
        f'<div style="font-family:{FONT};max-width:760px;color:#1a1a1a">'
        '<h2 style="font-size:16px;border-bottom:2px solid #1a73e8;padding-bottom:3px;'
        'margin-top:22px">🧪 Reward-Optimised Screeners — Out-of-Sample Robust Picks</h2>'
    )
    if scr is None or scr.empty:
        return head + _explain_html() + "</div>"
    out = [head, _explain_html()]
    for mkt in _order(scr):
        s = scr[scr["market"] == mkt].iloc[0]
        fac = s["screener"].split("↑")[0].split("↓")[0].split(" & ")[0]
        label, why = STYLE.get(fac, (s["screener"], ""))
        edge = f"OOS +{s['oos_med']*100:.1f}% median · {s['oos_win']*100:.0f}% win · ~{int(s['per_yr'])}/yr"
        rows = picks[picks["market"] == mkt].head(top)
        out.append(
            f'<h3 style="font-size:13.5px;margin:14px 0 1px">{FLAG.get(mkt,"")} {mkt} — {label} '
            f'<span style="font-size:10px;color:#fff;background:#1a73e8;padding:1px 7px;'
            f'border-radius:10px">{edge}</span></h3>'
            f'<p style="font-size:11px;color:#666;margin:0 0 3px">Why here: {why}.</p>'
        )
        out.append(
            _picks_table(mkt, rows)
            if len(rows)
            else '<p style="font-size:12px;color:#999">no current matches</p>'
        )
    out.append(
        '<p style="font-size:10.5px;color:#8a6d00;margin:6px 0 0">Ranked by liquidity within '
        "each screen (not the most-extreme factor value, which surfaces pumps/distress). "
        "Full list: reports/reward_picks.csv.</p></div>"
    )
    return "".join(out)


def section_text(top=8):
    scr, picks = _load()
    lines = ["REWARD-OPTIMISED SCREENERS — OUT-OF-SAMPLE ROBUST PICKS", ""]
    lines.append(
        "Data-chosen screens (search over ~20 factors) validated on HELD-OUT later years; "
        "only edges that persisted out-of-sample are shown. Robust in 5/20 markets — US "
        "value is the only robust fundamental screen; elsewhere price/risk factors win. "
        "Modest, survivorship-flattered edges. Research only, not advice."
    )
    if scr is None or scr.empty:
        return "\n".join(lines)
    for mkt in _order(scr):
        s = scr[scr["market"] == mkt].iloc[0]
        fac = s["screener"].split("↑")[0].split("↓")[0].split(" & ")[0]
        label = STYLE.get(fac, (s["screener"], ""))[0]
        lines.append("")
        lines.append(
            f"{mkt} — {label}  (OOS +{s['oos_med']*100:.1f}% med, {s['oos_win']*100:.0f}% win)"
        )
        for _, r in picks[picks["market"] == mkt].head(top).iterrows():
            nm = NAMES.get(str(r["ticker"]), "")
            lines.append(f"  {str(r['ticker']):<12} {nm:<16} 6mo {r['ret_6m']*100:+.0f}%")
    return "\n".join(lines)


if __name__ == "__main__":
    print(section_text())
