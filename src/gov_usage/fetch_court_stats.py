"""Fetch state-level civil / small-claims court caseload data.

There is no single clean nationwide API for this, and it's gotten harder:
as of this writing (2026) data.gov has been re-platformed away from
classic CKAN. `catalog.data.gov/api/3/action/*` -- the documented,
previously-reliable way to script downloads -- now 404s across the board,
even for unrelated, definitely-still-published datasets, and the old
"state-court-statistics-series-a021b" dataset page itself now 404s too.
This was confirmed against the live site, not assumed.

Two paths are implemented:

1. `fetch_datagov()` -- kept as a best-effort attempt at the old CKAN API,
   in case it comes back or is restored at the same path for you. It fails
   fast with a clear error pointing here if the API isn't there. If you hit
   that, search https://catalog.data.gov/ by hand for the current DOJ/BJS
   "State Court Statistics Series" (or equivalent) dataset and either
   adapt this function's URL or download the file manually and use path 2.

2. `normalize_manual_export()` -- the reliable path. The National Center
   for State Courts' Court Statistics Project now lives on a Tableau
   Server (tableau.ncsc.org, linked from
   https://www.ncsc.org/explore-court-caseload-data), with richer, more
   current small-claims/civil caseload figures than DOJ/BJS's stalled
   series. Export the state(s)/case type(s) you need by hand from a
   dashboard there and point this function at the exported file; it
   standardizes whatever columns you give it via a small mapping you fill
   in once you see your export's actual headers.

   What was actually investigated here, live, before concluding manual
   export is necessary (not assumed): Tableau Server supports a simple
   `<view-url>.csv` GET that exports a view's data without needing a full
   interactive session -- confirmed working, e.g.
   `tableau.ncsc.org/t/Research/views/TrialDashboards/Overview.csv`
   returns real national civil/criminal caseload-by-year figures, and
   `.../CivilTrends2018-2022/TrendbyState2.csv?CaseType=Small%20Claims`
   confirms "Small Claims" is a real case-type category in NCSC's data
   model. But the specific dashboards linked from NCSC's public pages
   render as either a national KPI number (not state-level) or an
   interactive map/crosstab whose underlying by-state data isn't exposed
   through that simple GET -- getting it needs Tableau's in-app "Download
   Crosstab" feature, which runs over a live VizQL session (WebSocket).
   This sandbox's egress proxy doesn't support WebSocket upgrades
   (confirmed via repeated `ws_closed_mid_exchange` failures against
   tableau.ncsc.org, not assumed), so that path isn't reachable from here
   even with a real browser (tried via Playwright). A differently
   configured environment with full WebSocket support could likely
   automate this properly; from here, manual export remains the reliable
   option.

Path 1 needs network access to catalog.data.gov. Path 2 needs no network
access here since it only reformats a file you already downloaded.
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
    if resp.status_code == 404:
        raise RuntimeError(
            "catalog.data.gov's CKAN API (or this package id) is not available "
            "-- confirmed dead as of 2026, see this module's docstring. Find the "
            "current dataset by hand at https://catalog.data.gov/ and either "
            "update DATAGOV_API/DATAGOV_PACKAGE_ID or download it manually and "
            "use normalize_manual_export() instead."
        )
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
