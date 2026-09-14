"""Fetch Google Trends 'interest by region' (US state breakdown) for a list
of AI-related search terms, one term at a time, and save each as its own
raw CSV under data/raw/trends/.

Google Trends' comparison endpoint normalizes multiple terms against each
other and caps you at 5 per request, which distorts cross-term comparisons.
Instead we fetch each term independently (its own 0-100 scale) and leave
aggregation/normalization to combine.py, where all terms can be reasoned
about together.

Requires network access to trends.google.com. This is NOT reachable from
this project's default sandboxed dev environment (see repo README,
"Network requirements") -- run this from a machine/CI job with normal
internet access.

Usage:
    python -m src.trends.fetch_trends
    python -m src.trends.fetch_trends --terms "Claude AI" "ChatGPT" --timeframe "today 5-y"
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import pandas as pd
from pytrends.request import TrendReq

from src.trends.terms import SEARCH_TERMS

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "trends"


def _slug(term: str) -> str:
    return term.lower().replace(" ", "_").replace("/", "-")


def fetch_term(pytrends: TrendReq, term: str, timeframe: str, max_retries: int = 5) -> pd.DataFrame:
    """Fetch state-level interest for a single term, retrying with backoff
    on the rate-limit (429) errors pytrends/Google Trends commonly throw."""
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            pytrends.build_payload([term], timeframe=timeframe, geo="US")
            df = pytrends.interest_by_region(resolution="REGION", inc_low_vol=True, inc_geo_code=False)
            return df
        except Exception as exc:  # pytrends raises plain Exception/ResponseError
            last_exc = exc
            wait = min(60, 2**attempt) + random.uniform(0, 1)
            print(f"[{term}] attempt {attempt}/{max_retries} failed ({exc}); retrying in {wait:.1f}s")
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch trends for {term!r} after {max_retries} attempts") from last_exc


def fetch_all(terms: list[str], timeframe: str, sleep_between: float) -> dict[str, str]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    pytrends = TrendReq(hl="en-US", tz=360)

    saved: dict[str, str] = {}
    failed: list[str] = []
    for term in terms:
        try:
            df = fetch_term(pytrends, term, timeframe=timeframe)
        except RuntimeError as exc:
            print(f"SKIP: {exc}")
            failed.append(term)
            continue

        out_path = RAW_DIR / f"{_slug(term)}.csv"
        df.to_csv(out_path)
        saved[term] = str(out_path.relative_to(RAW_DIR.parents[2]))
        print(f"Saved '{term}' -> {out_path}")
        time.sleep(sleep_between)

    manifest = {
        "timeframe": timeframe,
        "fetched_at": pd.Timestamp.utcnow().isoformat(),
        "saved": saved,
        "failed": failed,
    }
    (RAW_DIR / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    if failed:
        print(f"\n{len(failed)} term(s) failed and were skipped: {failed}")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--terms", nargs="*", default=SEARCH_TERMS, help="Search terms to fetch (default: src/trends/terms.py list)")
    parser.add_argument("--timeframe", default="today 12-m", help="pytrends timeframe string, e.g. 'today 12-m', 'today 5-y'")
    parser.add_argument("--sleep", type=float, default=5.0, help="Seconds to sleep between terms to avoid rate limiting")
    args = parser.parse_args()

    fetch_all(args.terms, args.timeframe, args.sleep)


if __name__ == "__main__":
    main()
