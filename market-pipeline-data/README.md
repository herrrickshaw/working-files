# market-pipeline-data

Uncommitted data artifacts from the `market-pipeline` research repo
(`~/market-pipeline/code/python_files/`), archived here 2026-07-18 because
they're expensive to re-collect/re-compute (API rate limits, long scan runs)
and weren't tracked anywhere else — cache and scan-output directories are
gitignored in `market-pipeline` itself by design (see that repo's `CLAUDE.md`),
so this is their only durable copy.

## Contents

| Directory | What it is |
|---|---|
| `cache_seed/` | Collected fundamentals/earnings-date caches across markets (parquet), plus circuit-breaker backtest datasets, DART corp code mapping, sector classification extensions. Mostly parquet + JSON + txt logs. |
| `correlation_scan/correlation_scan.duckdb` | Pairwise stock-return correlation matrices for US/Japan/Korea/NSE — see below, this is a warehoused/compressed form, not the original CSVs. |
| `combined_report_results/`, `indian_full_scan/`, `european_scan/`, `korea_scan/`, `japan_scan/`, `us_full_scan/` | Per-market screener scan output (mostly `.xlsx`). |
| `docs_cache/` | Cached reference docs. |
| `brief_today*.html`, `action_brief_today.html` | Daily mailer HTML drafts/output snapshots. |

## `correlation_scan.duckdb` — why this isn't 4 raw CSVs

The original `correlation_scan/*.csv` were dense NxN correlation matrices
(one row/column per symbol) — 1.3GB total, with the US one alone at 801MB
(6,428×6,428 symbols), over GitHub's 100MB single-file push limit even before
LFS considerations. Converted to a single DuckDB database instead:

- **Long format**: `(symbol_a, symbol_b, correlation)` instead of wide NxN — a
  correlation matrix is symmetric with a diagonal of 1.0, so only the lower
  triangle (`symbol_a < symbol_b`) is stored; the upper triangle and diagonal
  are 100% redundant and reconstructible.
- **One table per market**: `us_correlation`, `japan_correlation`,
  `korea_correlation`, `nse_correlation`.
- **Result**: 1.3GB → 330MB (4x), with exact values preserved (spot-checked
  against the source CSVs before deleting them from the raw form).

Query it directly with the `duckdb` CLI or Python, no need to load the whole
file into memory:

```python
import duckdb
con = duckdb.connect("correlation_scan/correlation_scan.duckdb", read_only=True)

# Most correlated pairs in the NSE universe
con.execute("""
    SELECT * FROM nse_correlation
    ORDER BY correlation DESC LIMIT 20
""").fetchdf()

# Correlation between two specific symbols (works regardless of which one
# was symbol_a/symbol_b in storage, since only the lower triangle is kept)
con.execute("""
    SELECT correlation FROM nse_correlation
    WHERE (symbol_a = 'RELIANCE' AND symbol_b = 'TCS')
       OR (symbol_a = 'TCS' AND symbol_b = 'RELIANCE')
""").fetchdf()
```

Row counts: US 20,652,968 · Japan 6,274,653 · Korea 3,643,166 · NSE 2,496,495.
