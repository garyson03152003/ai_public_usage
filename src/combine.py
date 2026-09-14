"""Merge the fetched Google Trends and government-usage data into a single
state x year panel at data/processed/combined_state_data.csv, covering
2020 through the current year.

This only reads files already present under data/raw/ -- it does no
network access itself, so it can run anywhere (including this sandbox) as
long as data/raw/ has been populated by the fetch_* scripts elsewhere.

Coverage is inherently uneven: Trends data covers all 50 states + DC for
whichever term/year combinations were successfully fetched; court-stats
and parking-ticket data only cover whatever years/states/cities you
fetched (parking data is city-level, e.g. NYC only, not a 50-state
comparison). Missing values are left as NaN rather than silently dropped
or interpolated, and a `data_coverage_notes` column flags which pieces are
present for each (state, year) row.

Usage:
    python -m src.combine
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd

from src.trends.fetch_trends import DEFAULT_START_YEAR
from src.us_states import US_STATE_TO_ABBR, normalize_state_name

ROOT = Path(__file__).resolve().parent.parent
TRENDS_DIR = ROOT / "data" / "raw" / "trends"
COURT_STATS_DIR = ROOT / "data" / "raw" / "court_stats"
PARKING_DIR = ROOT / "data" / "raw" / "parking_tickets"
OUTPUT_PATH = ROOT / "data" / "processed" / "combined_state_data.csv"

ALL_STATES = pd.DataFrame({"state": list(US_STATE_TO_ABBR.keys())})


def _load_trends_for_year(year_dir: Path) -> pd.DataFrame:
    """Read every per-term CSV in a single year's trends directory and join
    into one wide frame: state, <term_1>_interest, ..., ai_interest_index
    (the row-wise mean across all terms successfully fetched for that year)."""
    wide = ALL_STATES.set_index("state")
    term_columns: list[str] = []

    for csv_path in sorted(year_dir.glob("*.csv")):
        df = pd.read_csv(csv_path, index_col=0)
        if df.empty or df.shape[1] == 0:
            continue
        term = df.columns[0]
        col_name = f"{term}_interest"
        series = df[term].rename(col_name)
        series.index = series.index.map(lambda s: normalize_state_name(s) or s)
        wide = wide.join(series, how="left")
        term_columns.append(col_name)

    if term_columns:
        wide["ai_interest_index"] = wide[term_columns].mean(axis=1, skipna=True)
    else:
        wide["ai_interest_index"] = pd.NA

    return wide.reset_index().rename(columns={"index": "state"})


def load_trends(trends_dir: Path = TRENDS_DIR) -> pd.DataFrame:
    """Read data/raw/trends/<year>/<term>.csv for every fetched year and
    concatenate into a state x year panel."""
    if not trends_dir.exists():
        return pd.DataFrame(columns=["state", "year", "ai_interest_index"])

    year_dirs = sorted(p for p in trends_dir.iterdir() if p.is_dir() and p.name.isdigit())
    frames = []
    for year_dir in year_dirs:
        year_df = _load_trends_for_year(year_dir)
        year_df.insert(1, "year", int(year_dir.name))
        frames.append(year_df)

    if not frames:
        return pd.DataFrame(columns=["state", "year", "ai_interest_index"])
    return pd.concat(frames, ignore_index=True, sort=False)


def load_court_stats(court_stats_dir: Path = COURT_STATS_DIR) -> pd.DataFrame:
    """Read standardized court-stats CSVs (output of
    fetch_court_stats.normalize_manual_export) and aggregate to one row per
    (state, year): small-claims filings (summed across case-type rows, if
    more than one) and average time-to-disposition."""
    frames = [pd.read_csv(p) for p in court_stats_dir.glob("normalized_*.csv")]
    if not frames:
        return pd.DataFrame(columns=["state", "year", "small_claims_filings", "small_claims_avg_processing_days"])

    df = pd.concat(frames, ignore_index=True)
    df["state"] = df["state"].map(lambda s: normalize_state_name(s) or s)
    df["year"] = pd.to_numeric(df["year"], errors="coerce")

    small_claims = df[df["case_type"].astype(str).str.contains("small claims", case=False, na=False)]
    if small_claims.empty:
        small_claims = df  # fall back to whatever case types are present

    panel = small_claims.groupby(["state", "year"], as_index=False).agg(
        small_claims_filings=("filings", "sum"),
        small_claims_avg_processing_days=("avg_time_to_disposition_days", "mean"),
    )
    return panel


def load_parking_tickets(parking_dir: Path = PARKING_DIR) -> pd.DataFrame:
    """Read the yearly violation_status-count CSVs produced by
    fetch_socrata.py and roll up to one row per (state, year):
    total hearing+appeal ticket volume, and the subset that were actual
    appeals (violation_status containing "APPEAL")."""
    frames = [pd.read_csv(p) for p in parking_dir.glob("*.csv")]
    if not frames:
        return pd.DataFrame(columns=["state", "year", "parking_hearing_records", "parking_appeal_records"])

    df = pd.concat(frames, ignore_index=True)
    df["state"] = df["state"].map(lambda s: normalize_state_name(s) or s)
    is_appeal = df["violation_status"].astype(str).str.contains("APPEAL", case=False, na=False)
    df["appeal_n"] = df["n"].where(is_appeal, 0)

    panel = df.groupby(["state", "year"], as_index=False).agg(
        parking_hearing_records=("n", "sum"),
        parking_appeal_records=("appeal_n", "sum"),
    )
    return panel


def coverage_note(row: pd.Series) -> str:
    parts = [
        "trends" if pd.notna(row.get("ai_interest_index")) else "no-trends",
        "court-stats" if pd.notna(row.get("small_claims_filings")) else "no-court-stats",
        "parking" if pd.notna(row.get("parking_hearing_records")) else "no-parking",
    ]
    return ",".join(parts)


def combine(
    trends_dir: Path = TRENDS_DIR,
    court_stats_dir: Path = COURT_STATS_DIR,
    parking_dir: Path = PARKING_DIR,
    output_path: Path = OUTPUT_PATH,
    start_year: int = DEFAULT_START_YEAR,
    end_year: int | None = None,
) -> pd.DataFrame:
    end_year = end_year or datetime.date.today().year

    trends = load_trends(trends_dir)
    court_stats = load_court_stats(court_stats_dir)
    parking = load_parking_tickets(parking_dir)

    years = pd.DataFrame({"year": range(start_year, end_year + 1)})
    backbone = ALL_STATES.merge(years, how="cross")

    combined = (
        backbone.merge(trends, on=["state", "year"], how="left")
        .merge(court_stats, on=["state", "year"], how="left")
        .merge(parking, on=["state", "year"], how="left")
    )
    combined.insert(1, "state_abbr", combined["state"].map(US_STATE_TO_ABBR))
    combined["data_coverage_notes"] = combined.apply(coverage_note, axis=1)
    combined = combined.sort_values(["state", "year"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    print(f"Wrote combined panel ({len(combined)} state-year rows, {start_year}-{end_year}) -> {output_path}")
    return combined


if __name__ == "__main__":
    combine()
