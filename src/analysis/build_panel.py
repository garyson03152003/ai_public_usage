"""Build the monthly state x year x month panel used by the event-study
and fuzzy-RD scripts: AI search interest (from the monthly Trends fetch)
joined with this project's monthly-resolution government-usage metrics --
UI first-payment processing time (all states), NYC parking-ticket
hearing/appeal volume (New York only), and small-claims filings/
dispositions for Texas (via `fetch_tx_card.py`) and Washington (via
`fetch_wa_caseload.py`) -- plus the UI control (state unemployment rate).

This is a distinct, narrower panel from combine.py's annual
combined_state_data.csv -- it exists because event-time analysis around
specific launch dates needs monthly resolution, which most court-stats
sources don't have (see the main README), but parking-ticket data and
the two small-claims sources now do.

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
PARKING_MONTHLY_DIR = ROOT / "data" / "raw" / "parking_tickets_monthly"
TX_CARD_PATH = ROOT / "data" / "raw" / "court_stats" / "tx_justice_court_civil_month.csv"
WA_CASELOAD_PATH = ROOT / "data" / "raw" / "court_stats" / "wa_small_claims_month.csv"
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


def load_parking_monthly(parking_dir: Path = PARKING_MONTHLY_DIR) -> pd.DataFrame:
    """Read fetch_socrata.py --granularity month output and roll up to one
    row per (state, year, month): total hearing+appeal volume and the
    appeal-only subset. NYC-only (state=New York), same caveat as
    combine.py's annual version."""
    if not parking_dir.exists():
        return pd.DataFrame(columns=["state", "year", "month", "parking_hearing_records", "parking_appeal_records"])
    frames = [pd.read_csv(p) for p in parking_dir.glob("*.csv")]
    if not frames:
        return pd.DataFrame(columns=["state", "year", "month", "parking_hearing_records", "parking_appeal_records"])

    df = pd.concat(frames, ignore_index=True)
    df["state"] = df["state"].map(lambda s: normalize_state_name(s) or s)
    is_appeal = df["violation_status"].astype(str).str.contains("APPEAL", case=False, na=False)
    df["appeal_n"] = df["n"].where(is_appeal, 0)

    return df.groupby(["state", "year", "month"], as_index=False).agg(
        parking_hearing_records=("n", "sum"),
        parking_appeal_records=("appeal_n", "sum"),
    )


def load_tx_small_claims_monthly(path: Path = TX_CARD_PATH) -> pd.DataFrame:
    """Read fetch_tx_card.py output and pivot out the Small Claims case
    type into its own filings/dispositions columns. Texas-only, same
    single-state caveat as the NYC parking columns."""
    columns = ["state", "year", "month", "small_claims_filings", "small_claims_dispositions"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path)
    small_claims = df[df["case_type"] == "Small Claims"].copy()
    if small_claims.empty:
        return pd.DataFrame(columns=columns)
    small_claims = small_claims.rename(columns={"filings": "small_claims_filings", "dispositions": "small_claims_dispositions"})
    return small_claims[columns]


def load_wa_small_claims_monthly(path: Path = WA_CASELOAD_PATH) -> pd.DataFrame:
    """Read fetch_wa_caseload.py output, already state-level statewide
    small-claims filings/dispositions. Washington-only, same single-state
    caveat as the Texas and NYC parking columns; shares the same
    small_claims_filings/small_claims_dispositions columns as
    load_tx_small_claims_monthly() since the two sources cover disjoint
    states (Texas, Washington) and combine cleanly by concatenation."""
    columns = ["state", "year", "month", "small_claims_filings", "small_claims_dispositions"]
    if not path.exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_csv(path)
    if df.empty:
        return pd.DataFrame(columns=columns)
    return df.rename(columns={"filings": "small_claims_filings", "dispositions": "small_claims_dispositions"})[columns]


def build(
    trends_path: Path = TRENDS_MONTHLY_PANEL,
    ui_path: Path = UI_MONTHLY_PATH,
    controls_path: Path = CONTROLS_MONTHLY_PATH,
    parking_dir: Path = PARKING_MONTHLY_DIR,
    tx_card_path: Path = TX_CARD_PATH,
    wa_caseload_path: Path = WA_CASELOAD_PATH,
    output_path: Path = OUTPUT_PATH,
) -> pd.DataFrame:
    trends = load_trends_monthly(trends_path)
    ui = load_ui_monthly(ui_path)
    controls = load_controls_monthly(controls_path)
    parking = load_parking_monthly(parking_dir)
    small_claims = pd.concat(
        [load_tx_small_claims_monthly(tx_card_path), load_wa_small_claims_monthly(wa_caseload_path)],
        ignore_index=True,
    )

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
        .merge(parking, on=["state", "year", "month"], how="left")
        .merge(small_claims, on=["state", "year", "month"], how="left")
    )
    panel.insert(1, "state_abbr", panel["state"].map(US_STATE_TO_ABBR))
    panel = panel.sort_values(["state", "year", "month"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output_path, index=False)
    print(f"Wrote analysis panel ({len(panel)} state-month rows) -> {output_path}")
    return panel


if __name__ == "__main__":
    build()
