from pathlib import Path

from src.combine import combine

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_combine_merges_all_three_sources(tmp_path):
    output_path = tmp_path / "combined_state_data.csv"

    combined = combine(
        trends_dir=FIXTURES / "trends",
        court_stats_dir=FIXTURES / "court_stats",
        parking_dir=FIXTURES / "parking_tickets",
        output_path=output_path,
    )

    assert output_path.exists()
    # All 50 states + DC are always present, even with sparse source data.
    assert len(combined) == 51

    ca = combined.set_index("state").loc["California"]
    assert ca["state_abbr"] == "CA"
    # ai_interest_index is the mean of Claude AI (78) and ChatGPT (90).
    assert ca["ai_interest_index"] == 84.0
    assert ca["small_claims_filings"] == 150000
    assert ca["data_coverage_notes"] == "trends,court-stats,no-parking"

    ny = combined.set_index("state").loc["New York"]
    # Most recent year (2024) small-claims row should win over 2023.
    assert ny["small_claims_avg_processing_days"] == 74
    assert ny["parking_admin_hearing_records"] == 3
    assert ny["data_coverage_notes"] == "trends,court-stats,parking"

    # A state with no gov-usage fixture data at all still appears, with NaNs.
    wy = combined.set_index("state").loc["Wyoming"]
    assert wy["ai_interest_index"] == 10.0
    assert wy["data_coverage_notes"] == "trends,no-court-stats,no-parking"

    montana = combined.set_index("state").loc["Montana"]
    assert montana["data_coverage_notes"] == "no-trends,no-court-stats,no-parking"


def test_state_normalization_handles_abbreviations_and_cities():
    from src.us_states import normalize_state_name

    assert normalize_state_name("California") == "California"
    assert normalize_state_name("ca") == "California"
    assert normalize_state_name("New York City") == "New York"
    assert normalize_state_name("Not A Real Place") is None
