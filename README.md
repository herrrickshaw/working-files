# working-files

**This repo is mid-cleanup, not a real project.** It was a bulk-import
dumping ground (2026-07-13, 2 commits) containing near-duplicate copies of
several other repos plus a few genuinely orphaned tools — a repo hygiene
audit on 2026-07-17 traced and rescued each piece to its real home:

| Removed subfolder | What it was | Where it went |
|---|---|---|
| `BMS_analysis_battery/` | Stock-platform copy | Confirmed duplicate of `global-market-research-platform`, except `backend/vcrud/`, `backend/benchmarks/`, `backend/ml/sentiment_scorer.py`, `backend/routers/{benchmark,movers}.py`, `frontend/.../BenchmarkPanel.jsx` — rescued into `global-market-research-platform` (inert, not wired into the app) |
| `herrrickshaw/` | Another stock-platform copy | Confirmed duplicate, except `bms/datasets/`, the Kaggle download scripts, and the NASA notebook — rescued into `bms-battery-management` |
| `claude-lmstudio-router/` | Complete standalone tool, no copy existed elsewhere | Promoted to its own repo: `claude-lmstudio-router` |
| `india-election-analysis/` | Stale duplicate of the real repo | Deleted — confirmed only cosmetic diffs (README text, 2 regenerated .xlsx files) against the actively-maintained `india-election-analysis` repo |
| `python_files/` | Data-validation-framework + DDD screener/backtest package + vCRUD tooling, only surviving copy | Rescued into `data_validator` (see that repo's README for the full scope and two flagged items) |

**Still here, needs your own review:** `india-election-analysis-clean/` — a
genuinely divergent variant (not a subset) of the real `india-election-
analysis` repo. It's missing some content the real repo has (women's-
participation data, later-phase outputs) but has content the real repo
lacks (`docs/`, `visualisations/`, `reverse-monte-carlo/`, `state-wise-
analysis/`). Worth deciding whether any of that unique analysis should be
merged into the real repo before this folder — and this whole repo — gets
deleted.
