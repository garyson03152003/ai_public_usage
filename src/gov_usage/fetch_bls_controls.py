"""Fetch a control variable for the unemployment-insurance processing-time
data: each state's annual average unemployment rate, from the Bureau of
Labor Statistics' public API (LAUS -- Local Area Unemployment Statistics).

Why this matters: comparing UI first-payment processing time across states
or years without controlling for how many people are actually filing
claims is misleading -- a state mid-recession with a surging caseload
will look slower for reasons that have nothing to do with AI adoption or
administrative competence. Unemployment rate is the standard proxy for
claim-volume pressure; combine.py keeps it alongside the raw processing-
time metrics so an analysis can control for it (e.g. regress processing
time on ai_interest_index with unemployment_rate as a covariate) rather
than comparing raw numbers directly.

Requires network access to api.bls.gov. The public API works
unauthenticated for modest request volumes (25 series per query, 25
queries/day) -- this project's 51 series need 3 batched requests, which
fits; pass --api-key (a free BLS registration) if you hit the daily quota
or want the higher query limits it grants.

Usage:
    python -m src.gov_usage.fetch_bls_controls
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import pandas as pd
import requests

from src.trends.fetch_trends import DEFAULT_START_YEAR
from src.us_states import US_STATE_TO_FIPS

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "controls"
BLS_API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
MAX_SERIES_PER_REQUEST = 25  # BLS API v2 limit per request, registered or not


def series_id_for_state(state: str) -> str:
    """LAUS statewide unemployment rate, not seasonally adjusted."""
    fips = US_STATE_TO_FIPS[state]
    return f"LASST{fips}0000000000003"


def _chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_series(series_ids: list[str], start_year: int, end_year: int, api_key: str | None) -> dict:
    """POST to the BLS API in batches of MAX_SERIES_PER_REQUEST and merge
    the results into one {seriesID: [...data...]} dict."""
    merged: dict[str, list] = {}
    for batch in _chunks(series_ids, MAX_SERIES_PER_REQUEST):
        payload = {"seriesid": batch, "startyear": str(start_year), "endyear": str(end_year)}
        if api_key:
            payload["registrationkey"] = api_key

        resp = requests.post(BLS_API, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "REQUEST_SUCCEEDED":
            raise RuntimeError(f"BLS API request failed: {data.get('status')} {data.get('message')}")

        for series in data["Results"]["series"]:
            merged[series["seriesID"]] = series["data"]
    return merged


def fetch(start_year: int = DEFAULT_START_YEAR, end_year: int | None = None, api_key: str | None = None) -> Path:
    end_year = end_year or datetime.date.today().year

    state_by_series = {series_id_for_state(state): state for state in US_STATE_TO_FIPS}
    raw = fetch_series(list(state_by_series.keys()), start_year, end_year, api_key)

    rows = []
    for series_id, data_points in raw.items():
        state = state_by_series[series_id]
        for point in data_points:
            if not point["period"].startswith("M") or point["period"] == "M13":
                continue  # skip annual-average pseudo-periods, keep monthly
            try:
                value = float(point["value"])
            except ValueError:
                continue  # e.g. "-" for a lapse-in-appropriations gap
            rows.append({"state": state, "year": int(point["year"]), "month": int(point["period"][1:]), "unemployment_rate": value})

    monthly = pd.DataFrame(rows)
    annual = monthly.groupby(["state", "year"], as_index=False)["unemployment_rate"].mean()
    annual = annual.rename(columns={"unemployment_rate": "unemployment_rate_avg"})

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / "bls_unemployment_rate.csv"
    annual.to_csv(out_path, index=False)
    print(f"Wrote {len(annual)} state-year unemployment-rate rows -> {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start-year", type=int, default=DEFAULT_START_YEAR)
    parser.add_argument("--end-year", type=int, default=datetime.date.today().year)
    parser.add_argument("--api-key", default=None, help="Free BLS registration key, raises the daily query limit")
    args = parser.parse_args()

    fetch(args.start_year, args.end_year, args.api_key)


if __name__ == "__main__":
    main()
