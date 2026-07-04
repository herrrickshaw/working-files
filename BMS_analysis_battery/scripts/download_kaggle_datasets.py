#!/usr/bin/env python3
"""
Download all 11 Kaggle datasets used by the Herrrickshaw platform.

Prerequisites:
  pip install kaggle
  Set KAGGLE_USERNAME and KAGGLE_KEY environment variables
  (or place ~/.kaggle/kaggle.json with {"username":"...","key":"..."})

Usage:
  python scripts/download_kaggle_datasets.py
  python scripts/download_kaggle_datasets.py --category sentiment
  python scripts/download_kaggle_datasets.py --category benchmark
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / 'data' / 'kaggle'

# Optional VCRUD tracking — silently skipped when psycopg2 / DATABASE_URL unavailable
def _get_tracker():
    try:
        sys.path.insert(0, str(ROOT / 'backend'))
        from vcrud.kaggle_tracker import KaggleDatasetTracker
        return KaggleDatasetTracker(db_url=None, repo_root=str(ROOT))
    except Exception:
        return None

DATASETS = {
    # ── Sentiment / News ──────────────────────────────────────────────────────
    'sentiment': [
        {
            'slug':   'pratyushpuri/financial-news-market-events-dataset-2025',
            'dest':   DATA_DIR / 'sentiment' / 'market-events-2025',
            'desc':   'Financial News Market Events 2025 (NLP, sentiment, impact levels)',
        },
        {
            'slug':   'dyutidasmahaptra/s-and-p-500-with-financial-news-headlines-20082024',
            'dest':   DATA_DIR / 'sentiment' / 'sp500-headlines-2008-2024',
            'desc':   'S&P 500 + Financial News Headlines 2008–2024',
        },
        {
            'slug':   'ankurzing/sentiment-analysis-for-financial-news',
            'dest':   DATA_DIR / 'sentiment' / 'labelled-financial-news',
            'desc':   'Sentiment Analysis for Financial News (labelled pos/neg/neutral)',
        },
        {
            'slug':   'antobenedetti/finance-news-sentiments',
            'dest':   DATA_DIR / 'sentiment' / 'finance-news-sentiments',
            'desc':   'Finance News Sentiments (32k+ labelled articles)',
        },
        {
            'slug':   'dyutidasmahaptra/financial-sentiment-lexicon',
            'dest':   DATA_DIR / 'sentiment' / 'financial-sentiment-lexicon',
            'desc':   'Financial Sentiment Lexicon (580+ terms, -1 to +1 scores)',
        },
        {
            'slug':   'equinxx/stock-tweets-for-sentiment-analysis-and-prediction',
            'dest':   DATA_DIR / 'sentiment' / 'stock-tweets',
            'desc':   'Stock Tweets for Sentiment Analysis and Prediction',
        },
    ],
    # ── Portfolio / Benchmark ─────────────────────────────────────────────────
    'benchmark': [
        {
            'slug':   'andrewmvd/sp-500-stocks',
            'dest':   DATA_DIR / 'benchmark' / 'sp500-daily',
            'desc':   'S&P 500 Stocks — daily updated OHLCV',
        },
        {
            'slug':   'codebynadiia/s-and-p-500-stocks-dataset-first-half-2025',
            'dest':   DATA_DIR / 'benchmark' / 'sp500-h1-2025',
            'desc':   'S&P 500 Stocks Dataset — First Half 2025',
        },
        {
            'slug':   'salaheddineelkhirani/5-year-data-for-s-and-p-500-and-nasdaq-100',
            'dest':   DATA_DIR / 'benchmark' / 'sp500-nasdaq-5y',
            'desc':   'S&P 500 & NASDAQ 100 — 5-year 5-min interval data',
        },
        {
            'slug':   'nikitamanaenkov/stock-portfolio-data-with-prices-and-indices',
            'dest':   DATA_DIR / 'benchmark' / 'portfolio-with-indices',
            'desc':   'Stock Portfolio Data with Prices and Indices',
        },
        {
            'slug':   'ilyaryabov/financial-performance-of-companies-from-sp500',
            'dest':   DATA_DIR / 'benchmark' / 'sp500-fundamentals',
            'desc':   'Financial Performance of S&P 500 Companies (72 indicators)',
        },
    ],
}


def _check_kaggle_cli() -> bool:
    try:
        subprocess.run(['kaggle', '--version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _lfs_available() -> bool:
    try:
        subprocess.run(['git', 'lfs', 'version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _git_add_lfs(dest: Path) -> None:
    """Stage downloaded files so LFS pointer objects are committed."""
    try:
        subprocess.run(['git', '-C', str(ROOT), 'add', str(dest)],
                       capture_output=True, check=True)
    except subprocess.CalledProcessError:
        pass


def download(slug: str, dest: Path, desc: str, category: str,
             tracker=None, use_lfs: bool = False) -> bool:
    dest.mkdir(parents=True, exist_ok=True)
    print(f'\n[↓] {desc}')
    print(f'    {slug} → {dest}')
    try:
        subprocess.run(
            ['kaggle', 'datasets', 'download', '-d', slug, '-p', str(dest), '--unzip'],
            check=True,
        )
        files = [f for f in dest.rglob('*') if f.is_file()]
        print(f'    ✓ {len(files)} file(s): {", ".join(f.name for f in files[:5])}')
        if use_lfs:
            _git_add_lfs(dest)
            print('    🗃  LFS: staged for commit')
        if tracker:
            result = tracker.index_dataset(dest, category=category, slug=slug)
            if result.get('indexed', 0) > 0:
                print(f'    📦 VCRUD: indexed {result["indexed"]} file(s)')
        return True
    except subprocess.CalledProcessError as exc:
        print(f'    ✗ Failed: {exc}')
        return False


def main():
    parser = argparse.ArgumentParser(description='Download Kaggle datasets for Herrrickshaw')
    parser.add_argument('--category', choices=['sentiment', 'benchmark', 'all'], default='all')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be downloaded')
    parser.add_argument('--no-lfs', action='store_true', help='Skip git-lfs staging after download')
    args = parser.parse_args()

    if not args.dry_run and not _check_kaggle_cli():
        print('Error: kaggle CLI not found. Install with: pip install kaggle')
        print('Then set KAGGLE_USERNAME and KAGGLE_KEY env vars or create ~/.kaggle/kaggle.json')
        sys.exit(1)

    categories = ['sentiment', 'benchmark'] if args.category == 'all' else [args.category]
    total, ok = 0, 0

    use_lfs = not args.no_lfs and not args.dry_run and _lfs_available()
    if use_lfs:
        print('🗃  git-lfs detected — dataset files will be staged via LFS')
    elif not args.dry_run and not args.no_lfs:
        print('ℹ️  git-lfs not found — files will be stored as regular git objects')

    tracker = None
    if not args.dry_run:
        tracker = _get_tracker()
        if tracker and tracker.available:
            print('📦 VCRUD tracking enabled — files will be indexed after download')
        else:
            print('ℹ️  VCRUD tracking disabled (set DATABASE_URL to enable)')

    for cat in categories:
        print(f'\n{"="*60}')
        print(f'  {cat.upper()} DATASETS')
        print(f'{"="*60}')
        for entry in DATASETS[cat]:
            total += 1
            if args.dry_run:
                print(f'  [dry] {entry["slug"]} → {entry["dest"]}')
                ok += 1
            else:
                if download(entry['slug'], entry['dest'], entry['desc'],
                            category=cat, tracker=tracker, use_lfs=use_lfs):
                    ok += 1

    print(f'\n{"="*60}')
    print(f'Done: {ok}/{total} datasets downloaded to {DATA_DIR}')
    if ok < total:
        print('Tip: check your Kaggle API credentials and dataset access.')
    print(f'{"="*60}\n')


if __name__ == '__main__':
    main()
