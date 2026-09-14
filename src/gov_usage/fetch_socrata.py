"""Fetch parking-ticket appeal/hearing data from city open data portals
running Socrata ("SODA API"), as configured in sources.yaml, aggregated to
one row per (period, outcome status) rather than downloading raw ticket-
level rows -- these portals' violation tables run into the hundreds of
millions of rows, so a server-side count(*) group-by is the only
practical way to pull this from a sandboxed/CI environment.

Supports two granularities:
  --granularity year (default): one query per (source, year) ->
      data/raw/parking_tickets/<dataset_id>_<year>.csv
  --granularity month: one query per (source, year, month) ->
      data/raw/parking_tickets_monthly/<dataset_id>_<year>-<month>.csv,
      needed to join this data into the monthly event-study/fuzzy-RD
      analysis panel (src/analysis/build_panel.py) -- the annual file
      alone has no within-year timing to align with a launch date.

Requires network access to each portal's domain (e.g. data.cityofnewyork.us).
This is NOT reachable from this project's default sandboxed dev
environment -- run this from a machine/CI job with normal internet access.
An unauthenticated aggregation over a full year of NYC's dataset takes on
the order of a couple of minutes regardless of how narrow the date filter
is (Socrata does a full-table scan for an arbitrary LIKE pattern here,
since issue_date is plain text, not an indexed date column) -- so the
monthly version isn't ~12x faster than the yearly one despite matching
~12x fewer rows, and 7 years x 12 months is a multi-hour fetch. A free
Socrata app token (--app-token) speeds this up and avoids throttling.

Usage:
    python -m src.gov_usage.fetch_socrata
    python -m src.gov_usage.fetch_socrata --start-year 2022 --end-year 2024 --app-token XXXX
    python -m src.gov_usage.fetch_socrata --granularity month
"""

from __future__ import annotations

import argparse
import datetime
import random
import time
from pathlib import Path

import pandas as pd
import yaml
from sodapy import Socrata

from src.trends.fetch_trends import DEFAULT_START_YEAR

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "parking_tickets"
RAW_DIR_MONTHLY = Path(__file__).resolve().parents[2] / "data" / "raw" / "parking_tickets_monthly"
SOURCES_PATH = Path(__file__).resolve().parent / "sources.yaml"
REQUEST_TIMEOUT = 300


def load_sources() -> list[dict]:
    config = yaml.safe_load(SOURCES_PATH.read_text())
    return [s for s in config["sources"] if s.get("enabled") and s.get("dataset_id")]


def _status_clause(source: dict) -> str:
    return " OR ".join(f"{source['status_field']} like '%{kw}%'" for kw in source["status_filter"])


def _query(source: dict, date_filter: str, app_token: str | None) -> pd.DataFrame:
    client = Socrata(source["domain"], app_token, timeout=REQUEST_TIMEOUT)
    where = f"{source['date_field']} like '{date_filter}' AND ({_status_clause(source)})"

    results = client.get(
        source["dataset_id"],
        select=f"{source['status_field']} as violation_status, count(*) as n",
        where=where,
        group=f"{source['status_field']}",
        order="n DESC",
        limit=1000,
    )
    df = pd.DataFrame.from_records(results)
    if df.empty:
        df = pd.DataFrame(columns=["violation_status", "n"])
    df["n"] = pd.to_numeric(df["n"], errors="coerce")
    df["state"] = source["state"]
    df["source_name"] = source["name"]
    return df


def _fetch_with_retry(source: dict, date_filter: str, app_token: str | None, label: str, max_retries: int = 3) -> pd.DataFrame | None:
    """Retry with backoff on the timeouts these large, unauthenticated
    group-by queries commonly hit. Returns None (skip) if every attempt
    fails, rather than crashing the whole multi-period run."""
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return _query(source, date_filter, app_token)
        except Exception as exc:  # sodapy/requests raise a variety of transient errors
            last_exc = exc
            wait = min(120, 15 * attempt) + random.uniform(0, 5)
            print(f"[{source['name']} / {label}] attempt {attempt}/{max_retries} failed ({exc}); retrying in {wait:.0f}s")
            time.sleep(wait)
    print(f"SKIP: '{source['name']}' / {label} failed after {max_retries} attempts ({last_exc})")
    return None


def fetch_source_year(source: dict, year: int, app_token: str | None, max_retries: int = 3) -> Path | None:
    df = _fetch_with_retry(source, f"%/{year}", app_token, str(year), max_retries)
    if df is None:
        return None
    df["year"] = year

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{source['dataset_id']}_{year}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} status rows ({int(df['n'].sum())} tickets) from '{source['name']}' / {year} -> {out_path}")
    return out_path


def fetch_source_month(source: dict, year: int, month: int, app_token: str | None, max_retries: int = 3) -> Path | None:
    label = f"{year}-{month:02d}"
    df = _fetch_with_retry(source, f"{month:02d}/%/{year}", app_token, label, max_retries)
    if df is None:
        return None
    df["year"] = year
    df["month"] = month

    RAW_DIR_MONTHLY.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR_MONTHLY / f"{source['dataset_id']}_{label}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} status rows ({int(df['n'].sum())} tickets) from '{source['name']}' / {label} -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR, help="First calendar year to fetch (default: 2020)")
    parser.add_argument("--end-year", type=int, default=datetime.date.today().year, help="Last calendar year to fetch (default: current year)")
    parser.add_argument("--granularity", choices=["year", "month"], default="year", help="Time period per request (default: year)")
    parser.add_argument(
        "--app-token",
        default=None,
        help="Socrata app token (optional but recommended; unauthenticated requests are slower and more heavily throttled). "
        "Get one free at the portal's developer settings page.",
    )
    args = parser.parse_args()

    sources = load_sources()
    if not sources:
        print("No enabled sources with a dataset_id found in sources.yaml -- nothing to fetch.")
        return

    today = datetime.date.today()
    for source in sources:
        for year in range(args.start_year, args.end_year + 1):
            if args.granularity == "month":
                last_month = today.month if year == today.year else 12
                for month in range(1, last_month + 1):
                    fetch_source_month(source, year, month, app_token=args.app_token)
            else:
                fetch_source_year(source, year, app_token=args.app_token)


if __name__ == "__main__":
    main()
