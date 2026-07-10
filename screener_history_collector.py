#!/usr/bin/env python3
"""
screener_history_collector.py — collect POINT-IN-TIME historical ANNUAL financials
for INDIAN (NSE/BSE) tickers from screener.in's per-company Excel export, so the
fundamental screeners (Piotroski, Coffee Can) can be BACKTESTED on India without
look-ahead — the India analogue of sec_history_collector.py (which does US via
SEC EDGAR).

Each company's screener.in export carries a "Data Sheet" with ANNUAL line items
aligned to a fiscal "Report Date" axis (Mar-YYYY, ~10 years). We extract the
Piotroski/Coffee-Can inputs per fiscal year:
  net_income, revenue, cfo, borrowings, reserves, equity_capital, other_liab,
  inventory, receivables, cash, operating_profit, shares.

CAVEAT vs the US collector: screener.in exposes the fiscal PERIOD-END but NOT the
filing date. Indian issuers must file audited annual results within ~60 days of the
FY-end (SEBI LODR); the backtest therefore enters `fy_end + reporting-lag` days
later (default 90) as a conservative, no-look-ahead proxy — there is no earlier
as-of date available, so this is the honest best we can do.

Output: cache_seed/fundamentals_history/IN.parquet — long format, one row per
(ticker, fy_end). Resumable: reuses already-collected tickers on re-run.

  python3 screener_history_collector.py                 # NSE universe (data/global_universe/IN.csv)
  python3 screener_history_collector.py --limit 200      # test on the first 200
  python3 screener_history_collector.py --tickers RELIANCE TCS INFY
  python3 screener_history_collector.py --liquid-only     # only names present in cache_seed/ltm/IN.parquet
"""
import argparse
import io
import os
import time

import pandas as pd

BASE = os.path.expanduser("~/Downloads/code/python_files")
OUT_DIR = os.environ.get("FUND_HIST_DIR") or os.path.join(
    BASE, "cache_seed", "fundamentals_history"
)
OUT = os.path.join(OUT_DIR, "IN.parquet")
UNIVERSE = os.path.join(BASE, "data", "global_universe", "IN.csv")
LTM = os.path.join(BASE, "cache_seed", "ltm", "IN.parquet")
_RATE = 0.7  # polite delay between screener.in fetches (ToS-friendly)

# Data-Sheet row label → our field name (annual series only; first present wins).
FIELDS = {
    "net_income": ["Net profit", "Net Profit"],
    "revenue": ["Sales", "Sales+", "Revenue", "Total Revenue"],
    "operating_profit": ["Operating Profit", "Operating Profit+"],
    "cfo": ["Cash from Operating Activity", "Cash from Operating Activity+"],
    "borrowings": ["Borrowings", "Borrowings+", "Total Debt"],
    "reserves": ["Reserves"],
    "equity_capital": ["Equity Capital", "Equity Share Capital", "Share Capital"],
    "other_liab": ["Other Liabilities", "Other Liabilities+"],
    "inventory": ["Inventory", "Inventories"],
    "receivables": ["Trade receivables", "Debtors", "Receivables"],
    "cash": ["Cash & Bank", "Cash Equivalents"],
    "shares": ["No. of Equity Shares", "No of Equity Shares"],
}


def _num(x):
    try:
        return float(str(x).replace(",", "").replace("%", "").strip())
    except Exception:
        return None


def _is_annual_axis(vals):
    """A 'Report Date' row is the ANNUAL axis iff every date is a fiscal year-end
    (month == 3). Quarterly Report-Date rows carry Jun/Sep/Dec and are skipped so we
    never mistake a quarterly Sales/Net-profit row for the annual one."""
    dates = [v for v in vals if isinstance(v, pd.Timestamp) or hasattr(v, "month")]
    if not dates:
        return None
    if all(getattr(d, "month", 0) == 3 for d in dates):
        return [pd.Timestamp(d).normalize() for d in dates]
    return None


def _extract_annual(df):
    """Walk the Data Sheet top→bottom, tracking the current annual Report-Date axis,
    and pull each wanted field's values aligned to fiscal year-ends. Returns
    {fy_end: {field: value}}. First annual occurrence of a field wins (the annual
    block precedes the quarterly block for Sales/Net profit)."""
    # invert label → field for quick lookup
    label_to_field = {}
    for field, labels in FIELDS.items():
        for lab in labels:
            label_to_field[lab.strip().lower()] = field

    axis = None  # current annual fiscal axis (list of Timestamps) or None if quarterly
    out = {}  # fy_end -> {field: val}
    seen = set()  # fields already captured (first annual wins)
    for _, r in df.iterrows():
        cells = r.tolist()
        label = str(cells[0]).strip().lower()
        vals = cells[1:]
        if label == "report date":
            axis = _is_annual_axis(vals)
            continue
        if axis is None:
            continue
        field = label_to_field.get(label)
        if field is None or field in seen:
            continue
        seen.add(field)
        for dt, v in zip(axis, vals):
            n = _num(v)
            if n is not None:
                out.setdefault(pd.Timestamp(dt), {})[field] = n
    return out


def collect_ticker(sess_mod, ticker):
    """Fetch + parse one company. Returns list of per-fiscal-year row dicts."""
    raw = sess_mod.company_export_bytes(ticker)
    if not raw:
        return []
    try:
        xl = pd.ExcelFile(io.BytesIO(raw))
        sheet = next((s for s in xl.sheet_names if "data" in s.lower()), xl.sheet_names[0])
        df = pd.read_excel(io.BytesIO(raw), sheet_name=sheet, header=None)
    except Exception:
        return []
    annual = _extract_annual(df)
    rows = []
    for fy, fields in sorted(annual.items()):
        row = {"ticker": ticker, "fy_end": fy.strftime("%Y-%m-%d")}
        row.update(fields)
        rows.append(row)
    return rows


def _universe(args):
    if args.tickers:
        return [t.upper() for t in args.tickers]
    uni = pd.read_csv(UNIVERSE)
    syms = uni["yf_ticker"].astype(str).str.replace(r"\.(NS|BO)$", "", regex=True).str.upper()
    syms = sorted(set(syms))
    if args.liquid_only and os.path.exists(LTM):
        liq = set(pd.read_parquet(LTM, columns=["Symbol"])["Symbol"].astype(str).str.upper())
        syms = [s for s in syms if s in liq]
    return syms


def main():
    ap = argparse.ArgumentParser(description="Collect India historical financials from screener.in")
    ap.add_argument("--tickers", nargs="*", help="explicit NSE symbols (else the India universe)")
    ap.add_argument("--limit", type=int, default=0, help="cap number of tickers (testing)")
    ap.add_argument(
        "--liquid-only", action="store_true", help="only names present in cache_seed/ltm/IN.parquet"
    )
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    import screener_in_auth as sess_mod

    sess_mod.session()  # login once (cached); raises if creds missing/invalid

    universe = _universe(args)
    if args.limit:
        universe = universe[: args.limit]

    done, existing = set(), []
    if os.path.exists(OUT):
        prev = pd.read_parquet(OUT)
        done = set(prev["ticker"].astype(str).str.upper())
        existing = [prev]
    todo = [t for t in universe if t not in done]
    print(
        f"screener.in history: {len(universe)} tickers, {len(done)} already done, "
        f"{len(todo)} to fetch (~{len(todo)*_RATE/60:.0f} min at {_RATE}s/req)"
    )

    rows, n_ok, t0 = [], 0, time.time()
    for i, tk in enumerate(todo, 1):
        time.sleep(_RATE)
        try:
            r = collect_ticker(sess_mod, tk)
            if r:
                rows.extend(r)
                n_ok += 1
        except Exception:
            pass
        if i % 100 == 0 or i == len(todo):
            df = (
                pd.concat(existing + [pd.DataFrame(rows)], ignore_index=True)
                if (existing or rows)
                else pd.DataFrame()
            )
            if not df.empty:
                os.makedirs(OUT_DIR, exist_ok=True)  # survive a mid-run dir wipe
                df.to_parquet(OUT, index=False)
            print(f"  {i}/{len(todo)} | {n_ok} with data | {len(df)} rows | {time.time()-t0:.0f}s")
    print(f"done → {os.path.relpath(OUT, BASE)}")


if __name__ == "__main__":
    main()
