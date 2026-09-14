from pathlib import Path

from src.analysis.build_panel import load_parking_monthly

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "parking_tickets_monthly"


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
