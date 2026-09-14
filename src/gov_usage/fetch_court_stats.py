"""Fetch state-level civil / small-claims court caseload data.

There is no single clean nationwide API for this. Two complementary paths
are implemented:

1. `fetch_datagov()` -- the DOJ/BJS "State Court Statistics Series" dataset
   is catalogued on data.gov's CKAN API (package id
   "state-court-statistics-series-a021b"). CKAN's package_show endpoint
   returns resource URLs (usually CSV/PDF/SPSS) that we download as-is into
   data/raw/court_stats/. This is fully automatable.

2. `normalize_manual_export()` -- the National Center for State Courts'
   Court Statistics Project (courtstatistics.org, "CSP STAT") publishes the
   richer, more current small-claims/civil caseload and time-to-disposition
   figures, but only through an interactive Tableau-style dashboard with
   manual CSV/Excel export -- there is no stable public REST endpoint to
   automate. Export the state(s) and case type(s) you need from
   https://www.courtstatistics.org/court-statistics/interactive-caseload-data-displays/csp-stat
   and point this function at the exported file; it standardizes whatever
   columns you give it via a small mapping you fill in once you see your
   export's actual headers.

Requires network access to catalog.data.gov (path 1 only). This is NOT
reachable from this project's default sandboxed dev environment -- run
path 1 from a machine/CI job with normal internet access. Path 2 needs no
network access here since it only reformats a file you already downloaded.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import requests

from src.us_states import normalize_state_name

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "court_stats"

DATAGOV_PACKAGE_ID = "state-court-statistics-series-a021b"
DATAGOV_API = "https://catalog.data.gov/api/3/action/package_show"

# Standardized output schema for this project's court-stats data:
#   state, year, case_type, filings, dispositions, avg_time_to_disposition_days
STANDARD_COLUMNS = ["state", "year", "case_type", "filings", "dispositions", "avg_time_to_disposition_days"]


def fetch_datagov(package_id: str = DATAGOV_PACKAGE_ID) -> list[Path]:
    """Download every resource file listed for the data.gov package into
    data/raw/court_stats/. Returns the list of downloaded file paths.

    The downloaded files are whatever format DOJ/BJS published (often CSV
    next to PDF codebooks) and are NOT yet in this project's standard
    schema -- inspect them and adapt normalize_manual_export()'s column
    mapping to match.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    resp = requests.get(DATAGOV_API, params={"id": package_id}, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"data.gov package_show failed: {payload}")

    resources = payload["result"]["resources"]
    (RAW_DIR / "_package_metadata.json").write_text(json.dumps(payload["result"], indent=2))

    downloaded = []
    for resource in resources:
        url = resource.get("url")
        name = resource.get("name") or resource["id"]
        fmt = (resource.get("format") or "").lower()
        if not url:
            continue
        out_path = RAW_DIR / f"{name}.{fmt or 'bin'}".replace(" ", "_")
        file_resp = requests.get(url, timeout=60)
        file_resp.raise_for_status()
        out_path.write_bytes(file_resp.content)
        downloaded.append(out_path)
        print(f"Downloaded {name!r} ({fmt}) -> {out_path}")

    return downloaded


def normalize_manual_export(
    input_path: str | Path,
    column_map: dict[str, str],
    year: int | None = None,
    case_type: str | None = None,
    output_name: str | None = None,
) -> Path:
    """Standardize a manually-exported CSV/Excel file (e.g. from CSP STAT)
    into this project's schema and write it to data/raw/court_stats/.

    column_map maps this project's standard column names to the column
    names actually present in your export, e.g.:
        {"state": "State", "filings": "Total Filings", ...}
    Any standard column not present in the export is left as NaN. Pass
    `year`/`case_type` as constants when the export is a single
    year/case-type slice that doesn't carry its own column for them.
    """
    input_path = Path(input_path)
    if input_path.suffix.lower() in {".xlsx", ".xls"}:
        raw = pd.read_excel(input_path)
    else:
        raw = pd.read_csv(input_path)

    out = pd.DataFrame()
    for std_col in STANDARD_COLUMNS:
        src_col = column_map.get(std_col)
        if src_col and src_col in raw.columns:
            out[std_col] = raw[src_col]
        else:
            out[std_col] = pd.NA

    if year is not None:
        out["year"] = year
    if case_type is not None:
        out["case_type"] = case_type

    out["state"] = out["state"].map(normalize_state_name)
    dropped = out["state"].isna().sum()
    if dropped:
        print(f"Warning: {dropped} row(s) had a state value that couldn't be normalized and will show as NaN")

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAW_DIR / (output_name or f"normalized_{input_path.stem}.csv")
    out.to_csv(out_path, index=False)
    print(f"Wrote standardized court stats -> {out_path}")
    return out_path


if __name__ == "__main__":
    fetch_datagov()
