#!/usr/bin/env python3
"""
combined_mailer.py — one email that stacks BOTH:
  1. the daily stock-screener brief (build_mailer.build — regime picks, India/US screeners,
     convergence, AI screens, global momentum, 5y scoreboard, …), and
  2. the cross-market research insights (program_summary_mailer.build — the dataset, the
     three findings, the per-market combo table, deliverables).

Daily/actionable content on top; the research summary below a divider. Self-contained;
sendable via the existing pipeline. Educational/research only — NOT investment advice.

  from combined_mailer import build; subj, text, html = build()
  python3 combined_mailer.py            # write combined_brief.html
  python3 combined_mailer.py --send     # build + send via send_mailer.send()
"""
import sys
from datetime import date

FONT = "-apple-system,Segoe UI,Roboto,Arial,sans-serif"


def _daily():
    """The daily screener brief; fall back to just the regime-picks section if the full
    brief can't assemble (missing cached scan data)."""
    try:
        from build_mailer import build as build_daily

        _, text, html = build_daily()
        return text, html
    except Exception:
        try:
            import regime_picks

            sec = regime_picks.section_html()
            return "Regime picks (per-market, preferred screener).", (
                f'<div style="font-family:{FONT};max-width:760px;color:#1a1a1a">'
                f'<h1 style="font-size:21px;margin:0 0 8px">📈 Daily Screener Brief</h1>{sec}</div>'
            )
        except Exception:
            return "", ""


def _reward_picks():
    """OOS-robust reward-optimised screener section (explanation + current picks)."""
    try:
        import reward_picks_mailer as rp

        return rp.section_text(), rp.section_html()
    except Exception:
        return "", ""


def build():
    today = date.today().isoformat()
    from program_summary_mailer import build as build_summary

    dtext, dhtml = _daily()
    rtext, rhtml = _reward_picks()
    _, stext, shtml = build_summary()

    divider = (
        f'<div style="max-width:760px;margin:26px auto 6px">'
        f'<div style="border-top:3px double #1a73e8;padding-top:8px">'
        f'<p style="font-family:{FONT};font-size:13px;color:#1a73e8;font-weight:700;'
        f'letter-spacing:.04em;margin:0">🌐 CROSS-MARKET RESEARCH — the analysis behind the picks</p>'
        f'<p style="font-family:{FONT};font-size:11px;color:#666;margin:2px 0 0">Why each market uses '
        f"its screener: the full point-in-time backtest program, below.</p></div></div>"
    )

    html = (dhtml or "") + (rhtml or "") + divider + shtml
    text = (
        f"Daily Market Brief + Cross-Market Research — {today}\n\n"
        + (dtext or "")
        + (("\n\n" + rtext) if rtext else "")
        + "\n\n=========================  CROSS-MARKET RESEARCH  =========================\n\n"
        + stext
    )
    subject = f"📈 Daily Brief + 🌐 Cross-Market Research — {today}"
    return subject, text, html


if __name__ == "__main__":
    s, t, h = build()
    if "--send" in sys.argv:
        try:
            from send_mailer import send

            print("sent" if send(s, t, h) else "not sent (no creds) — saved combined_brief.html")
        except Exception as e:
            print(f"send failed ({e}); saving html")
    open("combined_brief.html", "w").write(h)
    print(s, "\n\nhtml bytes:", len(h), "→ combined_brief.html")
