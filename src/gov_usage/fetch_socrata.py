"""Fetch parking-ticket appeal/hearing data from city open data portals
running Socrata ("SODA API"), as configured in sources.yaml, aggregated to
one row per (year, outcome status) rather than downloading raw ticket-level
rows -- these portals' violation tables run into the hundreds of millions
of rows, so a server-side count(*) group-by is the only practical way to
pull this from a sandboxed/CI environment.

Requires network access to each portal's domain (e.g. data.cityofnewyork.us).
This is NOT reachable from this project's default sandboxed dev
environment -- run this from a machine/CI job with normal internet access.
An unauthenticated aggregation over a full year of NYC's dataset takes on
the order of a couple of minutes; a free Socrata app token (--app-token)
speeds this up and avoids throttling.

Usage:
    python -m src.gov_usage.fetch_socrata
    python -m src.gov_usage.fetch_socrata --start-year 2022 --end-year 2024 --app-token XXXX
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import pandas as pd
import yaml
from sodapy import Socrata

from src.trends.fetch_trends import DEFAULT_START_YEAR

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "parking_tickets"
SOURCES_PATH = Path(__file__).resolve().parent / "sources.yaml"


def load_sources() -> list[dict]:
    config = yaml.safe_load(SOURCES_PATH.read_text())
    return [s for s in config["sources"] if s.get("enabled") and s.get("dataset_id")]


def fetch_source_year(source: dict, year: int, app_token: str | None) -> Path:
    client = Socrata(source["domain"], app_token, timeout=180)

    status_clause = " OR ".join(f"{source['status_field']} like '%{kw}%'" for kw in source["status_filter"])
    where = f"{source['date_field']} like '%/{year}' AND ({status_clause})"

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
    df["year"] = year
    df["state"] = source["state"]
    df["source_name"] = source["name"]

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{source['dataset_id']}_{year}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} status rows ({int(df['n'].sum())} tickets) from '{source['name']}' / {year} -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR, help="First calendar year to fetch (default: 2020)")
    parser.add_argument("--end-year", type=int, default=datetime.date.today().year, help="Last calendar year to fetch (default: current year)")
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

    for source in sources:
        for year in range(args.start_year, args.end_year + 1):
            fetch_source_year(source, year, app_token=args.app_token)


if __name__ == "__main__":
    main()
