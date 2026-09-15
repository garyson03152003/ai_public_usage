"""Fetch Google Trends 'interest by region' (US state breakdown) for a list
of AI-related search terms, one term at a time, from 2020 through the
current year -- either one calendar year at a time (default) or one
calendar month at a time (--granularity month, for a finer-grained trend
line at the cost of ~12x more requests).

Google Trends' comparison endpoint normalizes multiple terms against each
other and caps you at 5 per request, which distorts cross-term
comparisons -- so each term is fetched independently (its own 0-100 scale
for that period). Splitting by period (rather than one request over the
whole 2020-now range) gives a state x period panel that lines up with
other time-resolved data, instead of a single number averaged over
several years.

Output layout:
    year granularity:  data/raw/trends/<year>/<term_slug>.csv
    month granularity: data/raw/trends_monthly/<year>-<month:02d>/<term_slug>.csv

Requires network access to trends.google.com. This is NOT reachable from
this project's default sandboxed dev environment (see repo README,
"Network requirements") -- run this from a machine/CI job with normal
internet access. Monthly granularity for the full term list is a long
run (~1500-1700 requests over 2020-present) -- expect a couple of hours
even with retries succeeding on the first try, and budget for some
skipped term/period combinations if Google Trends rate-limits you harder
than the built-in backoff can absorb.

Usage:
    python -m src.trends.fetch_trends
    python -m src.trends.fetch_trends --terms "Claude AI" "ChatGPT" --start-year 2022
    python -m src.trends.fetch_trends --granularity month
"""

from __future__ import annotations

import argparse
import calendar
import datetime
import json
import random
import time
from pathlib import Path

import pandas as pd
from pytrends.request import TrendReq

from src.trends.terms import SEARCH_TERMS

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "trends"
RAW_DIR_MONTHLY = Path(__file__).resolve().parents[2] / "data" / "raw" / "trends_monthly"
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


def month_periods(start_year: int, end_year: int, today: datetime.date) -> list[tuple[int, int]]:
    """(year, month) pairs from January of start_year through the current
    month of end_year (or December, for a fully-elapsed end_year)."""
    periods = []
    for year in range(start_year, end_year + 1):
        last_month = today.month if year == today.year else 12
        for month in range(1, last_month + 1):
            periods.append((year, month))
    return periods


def month_timeframe(year: int, month: int, today: datetime.date) -> str:
    """A pytrends timeframe string covering all of `year`-`month`,
    truncated at `today` for the current, still-in-progress month."""
    start = datetime.date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = datetime.date(year, month, last_day)
    if end > today:
        end = today
    return f"{start.isoformat()} {end.isoformat()}"


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
    """Year-granularity fetch: one request per (term, year)."""
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
        "granularity": "year",
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


def fetch_all_monthly(
    terms: list[str],
    start_year: int,
    end_year: int,
    sleep_between: float,
    today: datetime.date | None = None,
) -> dict[str, dict[str, str]]:
    """Month-granularity fetch: one request per (term, year-month)."""
    today = today or datetime.date.today()
    pytrends = TrendReq(hl="en-US", tz=360)
    periods = month_periods(start_year, end_year, today)

    saved: dict[str, dict[str, str]] = {}
    failed: list[str] = []
    for year, month in periods:
        period_key = f"{year}-{month:02d}"
        timeframe = month_timeframe(year, month, today)
        period_dir = RAW_DIR_MONTHLY / period_key
        period_dir.mkdir(parents=True, exist_ok=True)

        for term in terms:
            try:
                df = fetch_term(pytrends, term, timeframe=timeframe)
            except RuntimeError as exc:
                print(f"SKIP: {exc}")
                failed.append(f"{term} ({period_key})")
                continue

            out_path = period_dir / f"{_slug(term)}.csv"
            df.to_csv(out_path)
            saved.setdefault(period_key, {})[term] = str(out_path.relative_to(RAW_DIR_MONTHLY.parents[1]))
            print(f"Saved '{term}' / {period_key} -> {out_path}")
            time.sleep(sleep_between)

    manifest = {
        "granularity": "month",
        "start_year": start_year,
        "end_year": end_year,
        "fetched_at": pd.Timestamp.now("UTC").isoformat(),
        "saved": saved,
        "failed": failed,
    }
    (RAW_DIR_MONTHLY / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    if failed:
        print(f"\n{len(failed)} term/month combination(s) failed and were skipped: {failed}")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--terms", nargs="*", default=SEARCH_TERMS, help="Search terms to fetch (default: src/trends/terms.py list)")
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR, help="First calendar year to fetch (default: 2020)")
    parser.add_argument("--end-year", type=int, default=datetime.date.today().year, help="Last calendar year to fetch (default: current year)")
    parser.add_argument("--sleep", type=float, default=5.0, help="Seconds to sleep between requests to avoid rate limiting")
    parser.add_argument("--granularity", choices=["year", "month"], default="year", help="Time period per request (default: year)")
    args = parser.parse_args()

    if args.granularity == "month":
        fetch_all_monthly(args.terms, args.start_year, args.end_year, args.sleep)
    else:
        fetch_all(args.terms, args.start_year, args.end_year, args.sleep)


if __name__ == "__main__":
    main()
