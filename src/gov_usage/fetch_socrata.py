"""Fetch parking-ticket-appeal / administrative-hearing data from city open
data portals running Socrata ("SODA API"), as configured in sources.yaml.

Requires network access to each portal's domain (e.g. data.cityofnewyork.us).
This is NOT reachable from this project's default sandboxed dev
environment -- run this from a machine/CI job with normal internet access.

Usage:
    python -m src.gov_usage.fetch_socrata
    python -m src.gov_usage.fetch_socrata --limit 50000
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml
from sodapy import Socrata

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "parking_tickets"
SOURCES_PATH = Path(__file__).resolve().parent / "sources.yaml"


def load_sources() -> list[dict]:
    config = yaml.safe_load(SOURCES_PATH.read_text())
    return [s for s in config["sources"] if s.get("enabled") and s.get("dataset_id")]


def fetch_source(source: dict, limit: int, app_token: str | None) -> Path:
    client = Socrata(source["domain"], app_token)
    results = client.get(source["dataset_id"], limit=limit)
    df = pd.DataFrame.from_records(results)
    df["source_name"] = source["name"]
    df["state"] = source["state"]

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / f"{source['dataset_id']}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} rows from '{source['name']}' -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50_000, help="Max rows to pull per source")
    parser.add_argument(
        "--app-token",
        default=None,
        help="Socrata app token (optional; unauthenticated requests are heavily throttled). "
        "Get one free at the portal's developer settings page.",
    )
    args = parser.parse_args()

    sources = load_sources()
    if not sources:
        print("No enabled sources with a dataset_id found in sources.yaml -- nothing to fetch.")
        return

    for source in sources:
        fetch_source(source, limit=args.limit, app_token=args.app_token)


if __name__ == "__main__":
    main()
