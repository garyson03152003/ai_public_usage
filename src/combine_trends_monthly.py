"""Build a state x year x month AI-search-interest panel from the monthly
Trends fetch (src/trends/fetch_trends.py --granularity month), independent
of the annual combined_state_data.csv.

Kept separate from combine.py rather than merged in: the government-usage
data (court stats, parking, unemployment insurance) is only available
annually, so joining it onto a monthly grid would just repeat each year's
value 12 times without adding information -- misleading in a table that
otherwise implies month-level resolution. If you need both together,
join this file's output to combined_state_data.csv on state+year yourself
and keep the annual columns clearly labeled as such.

Usage:
    python -m src.combine_trends_monthly
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.us_states import US_STATE_TO_ABBR, normalize_state_name

ROOT = Path(__file__).resolve().parent.parent
TRENDS_MONTHLY_DIR = ROOT / "data" / "raw" / "trends_monthly"
OUTPUT_PATH = ROOT / "data" / "processed" / "trends_state_month.csv"

ALL_STATES = pd.DataFrame({"state": list(US_STATE_TO_ABBR.keys())})


def _load_period(period_dir: Path) -> pd.DataFrame:
    """Read every per-term CSV in one YYYY-MM directory and join into one
    wide frame: state, <term>_interest, ..., ai_interest_index."""
    wide = ALL_STATES.set_index("state")
    term_columns: list[str] = []

    for csv_path in sorted(period_dir.glob("*.csv")):
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


def build(trends_monthly_dir: Path = TRENDS_MONTHLY_DIR, output_path: Path = OUTPUT_PATH) -> pd.DataFrame:
    if not trends_monthly_dir.exists():
        raise FileNotFoundError(
            f"{trends_monthly_dir} doesn't exist -- run "
            "`python -m src.trends.fetch_trends --granularity month` first"
        )

    period_dirs = sorted(p for p in trends_monthly_dir.iterdir() if p.is_dir() and len(p.name) == 7 and p.name[4] == "-")
    frames = []
    for period_dir in period_dirs:
        year_str, month_str = period_dir.name.split("-")
        period_df = _load_period(period_dir)
        period_df.insert(1, "year", int(year_str))
        period_df.insert(2, "month", int(month_str))
        frames.append(period_df)

    if not frames:
        raise FileNotFoundError(f"No YYYY-MM subdirectories found under {trends_monthly_dir}")

    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined.insert(1, "state_abbr", combined["state"].map(US_STATE_TO_ABBR))
    combined = combined.sort_values(["state", "year", "month"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    print(f"Wrote monthly trends panel ({len(combined)} state-month rows) -> {output_path}")
    return combined


if __name__ == "__main__":
    build()
