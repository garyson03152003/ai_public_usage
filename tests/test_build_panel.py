from pathlib import Path

from src.analysis.build_panel import load_parking_monthly, load_tx_small_claims_monthly, load_wa_small_claims_monthly

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "parking_tickets_monthly"
TX_CARD_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "court_stats" / "tx_justice_court_civil_month.csv"
WA_CASELOAD_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "court_stats" / "wa_small_claims_month.csv"


def test_load_parking_monthly_aggregates_hearings_and_appeals():
    result = load_parking_monthly(FIXTURES)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["state"] == "New York"
    assert row["year"] == 2022
    assert row["month"] == 11
    assert row["parking_hearing_records"] == 110
    assert row["parking_appeal_records"] == 10


def test_load_parking_monthly_missing_dir_returns_empty():
    result = load_parking_monthly(Path("/nonexistent/path"))
    assert result.empty
    assert list(result.columns) == ["state", "year", "month", "parking_hearing_records", "parking_appeal_records"]


def test_load_tx_small_claims_monthly_pivots_out_small_claims_only():
    result = load_tx_small_claims_monthly(TX_CARD_FIXTURE)
    assert list(result.columns) == ["state", "year", "month", "small_claims_filings", "small_claims_dispositions"]
    row = result[(result["year"] == 2022) & (result["month"] == 11)].iloc[0]
    assert row["state"] == "Texas"
    assert row["small_claims_filings"] == 5000
    assert row["small_claims_dispositions"] == 4800


def test_load_tx_small_claims_monthly_missing_file_returns_empty():
    result = load_tx_small_claims_monthly(Path("/nonexistent/path.csv"))
    assert result.empty
    assert list(result.columns) == ["state", "year", "month", "small_claims_filings", "small_claims_dispositions"]


def test_load_wa_small_claims_monthly_renames_columns():
    result = load_wa_small_claims_monthly(WA_CASELOAD_FIXTURE)
    assert list(result.columns) == ["state", "year", "month", "small_claims_filings", "small_claims_dispositions"]
    row = result[(result["year"] == 2026) & (result["month"] == 7)].iloc[0]
    assert row["state"] == "Washington"
    assert row["small_claims_filings"] == 469
    assert row["small_claims_dispositions"] == 366


def test_load_wa_small_claims_monthly_missing_file_returns_empty():
    result = load_wa_small_claims_monthly(Path("/nonexistent/path.csv"))
    assert result.empty
    assert list(result.columns) == ["state", "year", "month", "small_claims_filings", "small_claims_dispositions"]
