"""Merge the fetched Google Trends and government-usage data into a single
state-level table at data/processed/combined_state_data.csv.

This only reads files already present under data/raw/ -- it does no
network access itself, so it can run anywhere (including this sandbox) as
long as data/raw/ has been populated by the fetch_* scripts elsewhere.

Coverage is inherently uneven: Trends data covers all 50 states + DC for
whichever terms were successfully fetched; court-stats and parking-ticket
data only cover whatever states/cities you fetched. Missing values are
left as NaN rather than silently dropped, and a `data_coverage_notes`
column flags which pieces are present for each state.

Usage:
    python -m src.combine
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.us_states import US_STATE_TO_ABBR, normalize_state_name

ROOT = Path(__file__).resolve().parent.parent
TRENDS_DIR = ROOT / "data" / "raw" / "trends"
COURT_STATS_DIR = ROOT / "data" / "raw" / "court_stats"
PARKING_DIR = ROOT / "data" / "raw" / "parking_tickets"
OUTPUT_PATH = ROOT / "data" / "processed" / "combined_state_data.csv"

ALL_STATES = pd.DataFrame({"state": list(US_STATE_TO_ABBR.keys())})


def load_trends(trends_dir: Path = TRENDS_DIR) -> pd.DataFrame:
    """Read every per-term CSV in trends_dir and join into one wide
    frame: state, <term_1>_interest, <term_2>_interest, ..., ai_interest_index
    (the row-wise mean across all successfully-fetched terms)."""
    wide = ALL_STATES.set_index("state")
    term_columns: list[str] = []

    for csv_path in sorted(trends_dir.glob("*.csv")):
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


def load_court_stats(court_stats_dir: Path = COURT_STATS_DIR) -> pd.DataFrame:
    """Read standardized court-stats CSVs (output of
    fetch_court_stats.normalize_manual_export) and aggregate to one row per
    state: most recent year's small-claims filings and average
    time-to-disposition, if present."""
    frames = [
        pd.read_csv(p)
        for p in court_stats_dir.glob("normalized_*.csv")
    ]
    if not frames:
        return pd.DataFrame(columns=["state", "small_claims_filings", "small_claims_avg_processing_days"])

    df = pd.concat(frames, ignore_index=True)
    df["state"] = df["state"].map(lambda s: normalize_state_name(s) or s)

    small_claims = df[df["case_type"].astype(str).str.contains("small claims", case=False, na=False)]
    if small_claims.empty:
        small_claims = df  # fall back to whatever case types are present

    latest = (
        small_claims.sort_values("year")
        .groupby("state", as_index=False)
        .last()[["state", "filings", "avg_time_to_disposition_days"]]
        .rename(
            columns={
                "filings": "small_claims_filings",
                "avg_time_to_disposition_days": "small_claims_avg_processing_days",
            }
        )
    )
    return latest


def load_parking_tickets(parking_dir: Path = PARKING_DIR) -> pd.DataFrame:
    """Read raw Socrata exports and roll up to one row per state: total
    record count as a rough proxy for administrative-hearing/appeal volume.
    Column names vary by portal and were not verified live, so this only
    relies on the 'state' column this project adds itself in fetch_socrata.py."""
    frames = [pd.read_csv(p) for p in parking_dir.glob("*.csv")]
    if not frames:
        return pd.DataFrame(columns=["state", "parking_admin_hearing_records"])

    df = pd.concat(frames, ignore_index=True)
    df["state"] = df["state"].map(lambda s: normalize_state_name(s) or s)
    counts = df.groupby("state", as_index=False).size().rename(columns={"size": "parking_admin_hearing_records"})
    return counts


def coverage_note(row: pd.Series) -> str:
    parts = [
        "trends" if pd.notna(row.get("ai_interest_index")) else "no-trends",
        "court-stats" if pd.notna(row.get("small_claims_filings")) else "no-court-stats",
        "parking" if pd.notna(row.get("parking_admin_hearing_records")) else "no-parking",
    ]
    return ",".join(parts)


def combine(
    trends_dir: Path = TRENDS_DIR,
    court_stats_dir: Path = COURT_STATS_DIR,
    parking_dir: Path = PARKING_DIR,
    output_path: Path = OUTPUT_PATH,
) -> pd.DataFrame:
    trends = load_trends(trends_dir)
    court_stats = load_court_stats(court_stats_dir)
    parking = load_parking_tickets(parking_dir)

    combined = trends.merge(court_stats, on="state", how="left").merge(parking, on="state", how="left")
    combined.insert(1, "state_abbr", combined["state"].map(US_STATE_TO_ABBR))
    combined["data_coverage_notes"] = combined.apply(coverage_note, axis=1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    print(f"Wrote combined dataset ({len(combined)} states) -> {output_path}")
    return combined


if __name__ == "__main__":
    combine()
