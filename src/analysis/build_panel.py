"""Build the monthly state x year x month panel used by the event-study
and fuzzy-RD scripts: AI search interest (from the monthly Trends fetch)
joined with the one genuinely monthly-resolution government-usage metric
this project has (UI first-payment processing time) and its control
(state unemployment rate).

This is a distinct, narrower panel from combine.py's annual
combined_state_data.csv -- it exists because event-time analysis around
specific launch dates needs monthly resolution, which only the trends and
unemployment-insurance data currently have (parking-ticket and court-stats
data are annual-only, see the main README).

Usage:
    python -m src.analysis.build_panel
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.us_states import US_STATE_TO_ABBR, normalize_state_name

ROOT = Path(__file__).resolve().parents[2]
TRENDS_MONTHLY_PANEL = ROOT / "data" / "processed" / "trends_state_month.csv"
UI_MONTHLY_PATH = ROOT / "data" / "raw" / "unemployment" / "eta9050_state_month.csv"
CONTROLS_MONTHLY_PATH = ROOT / "data" / "raw" / "controls" / "bls_unemployment_rate_monthly.csv"
OUTPUT_PATH = ROOT / "data" / "processed" / "analysis_panel_state_month.csv"

ALL_STATES = pd.DataFrame({"state": list(US_STATE_TO_ABBR.keys())})


def load_trends_monthly(path: Path = TRENDS_MONTHLY_PANEL) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["state", "year", "month", "ai_interest_index"])
    df = pd.read_csv(path)
    interest_cols = [c for c in df.columns if c.endswith("_interest")] + ["ai_interest_index"]
    return df[["state", "year", "month", *interest_cols]]


def load_ui_monthly(path: Path = UI_MONTHLY_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["state", "year", "month", "ui_first_payments_total", "ui_pct_within_21_days", "ui_avg_days_to_first_payment_approx"])
    df = pd.read_csv(path)
    df["state"] = df["state"].map(lambda s: normalize_state_name(s) or s)
    return df


def load_controls_monthly(path: Path = CONTROLS_MONTHLY_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["state", "year", "month", "unemployment_rate"])
    df = pd.read_csv(path)
    df["state"] = df["state"].map(lambda s: normalize_state_name(s) or s)
    return df


def build(
    trends_path: Path = TRENDS_MONTHLY_PANEL,
    ui_path: Path = UI_MONTHLY_PATH,
    controls_path: Path = CONTROLS_MONTHLY_PATH,
    output_path: Path = OUTPUT_PATH,
) -> pd.DataFrame:
    trends = load_trends_monthly(trends_path)
    ui = load_ui_monthly(ui_path)
    controls = load_controls_monthly(controls_path)

    if trends.empty:
        raise FileNotFoundError(
            f"{trends_path} not found or empty -- run "
            "`python -m src.trends.fetch_trends --granularity month` and "
            "`python -m src.combine_trends_monthly` first"
        )

    periods = trends[["year", "month"]].drop_duplicates()
    backbone = ALL_STATES.merge(periods, how="cross")

    panel = (
        backbone.merge(trends, on=["state", "year", "month"], how="left")
        .merge(ui, on=["state", "year", "month"], how="left")
        .merge(controls, on=["state", "year", "month"], how="left")
    )
    panel.insert(1, "state_abbr", panel["state"].map(US_STATE_TO_ABBR))
    panel = panel.sort_values(["state", "year", "month"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output_path, index=False)
    print(f"Wrote analysis panel ({len(panel)} state-month rows) -> {output_path}")
    return panel


if __name__ == "__main__":
    build()
