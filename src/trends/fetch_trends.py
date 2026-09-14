"""Fetch Google Trends 'interest by region' (US state breakdown) for a list
of AI-related search terms, one term at a time, one calendar year at a
time, from 2020 through the current year.

Google Trends' comparison endpoint normalizes multiple terms against each
other and caps you at 5 per request, which distorts cross-term
comparisons -- so each term is fetched independently (its own 0-100 scale
for that year). Splitting by year (rather than one request over the whole
2020-now range) gives a state x year panel that lines up with the
multi-year government caseload data in combine.py, instead of a single
number averaged over several years.

Output layout: data/raw/trends/<year>/<term_slug>.csv

Requires network access to trends.google.com. This is NOT reachable from
this project's default sandboxed dev environment (see repo README,
"Network requirements") -- run this from a machine/CI job with normal
internet access.

Usage:
    python -m src.trends.fetch_trends
    python -m src.trends.fetch_trends --terms "Claude AI" "ChatGPT" --start-year 2022
"""

from __future__ import annotations

import argparse
import datetime
import json
import random
import time
from pathlib import Path

import pandas as pd
from pytrends.request import TrendReq

from src.trends.terms import SEARCH_TERMS

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "trends"
DEFAULT_START_YEAR = 2020


def _slug(term: str) -> str:
    return term.lower().replace(" ", "_").replace("/", "-")


def year_timeframe(year: int, today: datetime.date) -> str:
    """A pytrends timeframe string covering all of `year`, truncated at
    `today` for the current, still-in-progress year."""
    start = f"{year}-01-01"
    if year >= today.year:
        end = today.isoformat()
    else:
        end = f"{year}-12-31"
    return f"{start} {end}"


def fetch_term(pytrends: TrendReq, term: str, timeframe: str, max_retries: int = 5) -> pd.DataFrame:
    """Fetch state-level interest for a single term/timeframe, retrying
    with backoff on the rate-limit (429) errors pytrends/Google Trends
    commonly throw."""
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


def fetch_all(
    terms: list[str],
    start_year: int,
    end_year: int,
    sleep_between: float,
    today: datetime.date | None = None,
) -> dict[str, dict[str, str]]:
    today = today or datetime.date.today()
    pytrends = TrendReq(hl="en-US", tz=360)

    saved: dict[str, dict[str, str]] = {}
    failed: list[str] = []
    for year in range(start_year, end_year + 1):
        timeframe = year_timeframe(year, today)
        year_dir = RAW_DIR / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)

        for term in terms:
            try:
                df = fetch_term(pytrends, term, timeframe=timeframe)
            except RuntimeError as exc:
                print(f"SKIP: {exc}")
                failed.append(f"{term} ({year})")
                continue

            out_path = year_dir / f"{_slug(term)}.csv"
            df.to_csv(out_path)
            saved.setdefault(str(year), {})[term] = str(out_path.relative_to(RAW_DIR.parents[2]))
            print(f"Saved '{term}' / {year} -> {out_path}")
            time.sleep(sleep_between)

    manifest = {
        "start_year": start_year,
        "end_year": end_year,
        "fetched_at": pd.Timestamp.now("UTC").isoformat(),
        "saved": saved,
        "failed": failed,
    }
    (RAW_DIR / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    if failed:
        print(f"\n{len(failed)} term/year combination(s) failed and were skipped: {failed}")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--terms", nargs="*", default=SEARCH_TERMS, help="Search terms to fetch (default: src/trends/terms.py list)")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR, help="First calendar year to fetch (default: 2020)")
    parser.add_argument("--end-year", type=int, default=datetime.date.today().year, help="Last calendar year to fetch (default: current year)")
    parser.add_argument("--sleep", type=float, default=5.0, help="Seconds to sleep between requests to avoid rate limiting")
    args = parser.parse_args()

    fetch_all(args.terms, args.start_year, args.end_year, args.sleep)


if __name__ == "__main__":
    main()
