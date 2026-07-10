#!/usr/bin/env python3
# trendlyne_auth.py
# =================
# Authenticated Trendlyne data source for Indian equities — P/E, ROE, and the wider
# fundamentals/valuation snapshot Trendlyne renders on each stock page.
#
# Credentials come from env / .env ONLY (TRENDLYNE_EMAIL / TRENDLYNE_PASSWORD) —
# never hard-coded, pasted in chat, or committed.
#
#   from trendlyne_auth import session, fundamentals, snapshot
#   s = session()
#   fundamentals("RELIANCE", s)   # → {pe, pb, roe, roa, debt_to_equity, div_yield, ...}
#   snapshot("RELIANCE", s)       # → every {metric: value} blob on the page
#
#   python3 trendlyne_auth.py RELIANCE TCS INFY     # smoke test
#
# NOTE: the stock page embeds an SSR JSON blob of metrics; coverage is best-effort
# (Trendlyne rate-limits heavy scraping and lazy-loads some widgets). Use politely.
# ⚠️ Personal-account use only; respect Trendlyne's Terms of Service + rate limits.
# Research/education only, not advice.

from __future__ import annotations

import html as _html
import os
import re
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

_UA = {"User-Agent": "Mozilla/5.0"}
_LOGIN = "https://trendlyne.com/accounts/login/"

# Trendlyne metric title (as shown on the page) → our canonical key. Matched by
# case-insensitive substring so minor label variants ("ROE", "ROE Annual %") map too.
_TITLE_MAP = [
    ("pe ttm", "pe"),
    ("price to earning", "pe"),
    ("pb ttm", "pb"),
    ("price to book", "pb"),
    ("roe", "roe"),
    ("return on equity", "roe"),
    ("roa", "roa"),
    ("return on assets", "roa"),
    ("roce", "roce"),
    ("debt to equity", "debt_to_equity"),
    ("dividend yield", "div_yield"),
    ("eps ttm", "eps_ttm"),
    ("market cap", "market_cap"),
    ("net profit margin", "net_margin"),
    ("operating profit margin", "opm"),
    ("revenue growth", "revenue_growth"),
    ("sales growth", "revenue_growth"),
    ("profit growth", "profit_growth"),
    ("piotroski", "piotroski"),
    ("current ratio", "current_ratio"),
    ("promoter holding", "promoter_holding"),
    ("pledge", "promoter_pledge"),
    # Trendlyne DVM proprietary scores (0–100)
    ("durability score", "dvm_durability"),
    ("durability", "dvm_durability"),
    ("valuation score", "dvm_valuation"),
    ("momentum score", "dvm_momentum"),
]


def _load_dotenv() -> None:
    f = Path(__file__).parent / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if line.startswith("TRENDLYNE_") and "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def session():
    """Log in and return a requests.Session (raises on failure). Creds from env only."""
    _load_dotenv()
    email, pw = os.environ.get("TRENDLYNE_EMAIL"), os.environ.get("TRENDLYNE_PASSWORD")
    if not email or not pw:
        raise RuntimeError("set TRENDLYNE_EMAIL / TRENDLYNE_PASSWORD in .env")
    import requests

    s = requests.Session()
    s.get(_LOGIN, headers=_UA, timeout=20)
    r = s.post(
        _LOGIN,
        data={"csrfmiddlewaretoken": s.cookies.get("csrftoken"), "login": email, "password": pw},
        headers={**_UA, "Referer": _LOGIN},
        timeout=20,
    )
    if "login" in r.url.lower():
        raise RuntimeError("Trendlyne login failed — check credentials (rotate if exposed)")
    return s


def _lookup(s, symbol: str) -> Optional[Tuple]:
    """NSE symbol → (trendlyne_id, stock_code, slugname) via the autocomplete API."""
    hx = {**_UA, "X-Requested-With": "XMLHttpRequest"}
    try:
        j = s.get(
            f"https://trendlyne.com/member/api/ac_snames/stock/?term={symbol}",
            headers=hx,
            timeout=15,
        ).json()
    except Exception:
        return None
    if not j:
        return None
    for row in j:
        if str(row.get("stock_code", "")).upper() == symbol.upper():
            return row.get("k"), row.get("stock_code"), row.get("slugname")
    r0 = j[0]
    return r0.get("k"), r0.get("stock_code"), r0.get("slugname")


def _page(s, symbol: str) -> Optional[str]:
    lk = _lookup(s, symbol)
    if not lk:
        return None
    k, code, slug = lk
    try:
        return _html.unescape(
            s.get(f"https://trendlyne.com/equity/{k}/{code}/{slug}/", headers=_UA, timeout=20).text
        )
    except Exception:
        return None


def _parse_blobs(text: str) -> Dict[str, float]:
    """All {title: value} numeric blobs the page renders (SSR JSON)."""
    out: Dict[str, float] = {}
    for title, val in re.findall(r'"title":\s*"([^"]+)"\s*,\s*"value":\s*"?(-?[0-9.]+)"?', text):
        try:
            out.setdefault(title.strip(), float(val))
        except ValueError:
            pass
    return out


def snapshot(symbol: str, s=None) -> Dict[str, float]:
    """Every metric blob on the stock page ({raw title: value})."""
    s = s or session()
    text = _page(s, symbol)
    return _parse_blobs(text) if text else {}


def to_canonical(blobs: Dict[str, float]) -> dict:
    """Map raw Trendlyne titles → canonical keys the decision engine uses."""
    out: dict = {}
    for raw, val in blobs.items():
        low = raw.lower()
        for frag, key in _TITLE_MAP:
            if frag in low and key not in out:
                out[key] = val
                break
    return out


def fundamentals(symbol: str, s=None) -> dict:
    """Canonical fundamentals dict for a symbol (mapped keys + source tag)."""
    out = to_canonical(snapshot(symbol, s))
    return {"source": "trendlyne", **out} if out else {}


def scores(symbol: str, s=None) -> dict:
    """Current Piotroski F-score + DVM (Durability/Valuation/Momentum, each 0-100) for a
    symbol — the quality-overlay signals for LIVE picks (the backtests show Piotroski
    works as an overlay on breakouts). Snapshot only, not historical. The DVM scores live
    in an HTML tooltip, the F-score in an SSR JSON blob, so parse each specifically."""
    s = s or session()
    text = _page(s, symbol)
    if not text:
        return {}
    out: dict = {}
    m = re.search(r'"title":\s*"Piotroski Score",\s*"value":\s*"?(\d+)', text)
    if m:
        out["piotroski"] = int(m.group(1))
    for key, lab in (
        ("dvm_durability", "Durability Score"),
        ("dvm_valuation", "Valuation Score"),
        ("dvm_momentum", "Momentum Score"),
    ):
        mm = re.search(lab + r"\s*:\s*(\d+)", text)
        if mm:
            out[key] = int(mm.group(1))
    return out


def main() -> int:
    import sys

    s = session()
    print("Trendlyne login ok ✓")
    for sym in sys.argv[1:] or ["RELIANCE", "TCS", "INFY"]:
        print(f"  {sym}: fundamentals={fundamentals(sym, s)}  scores={scores(sym, s)}")
        time.sleep(0.4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
