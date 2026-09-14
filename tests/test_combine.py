from pathlib import Path

import pandas as pd

from src.combine import combine

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_combine_builds_state_year_panel(tmp_path):
    output_path = tmp_path / "combined_state_data.csv"

    combined = combine(
        trends_dir=FIXTURES / "trends",
        court_stats_dir=FIXTURES / "court_stats",
        parking_dir=FIXTURES / "parking_tickets",
        output_path=output_path,
        start_year=2023,
        end_year=2024,
    )

    assert output_path.exists()
    # All 50 states + DC, for every year in [start_year, end_year].
    assert len(combined) == 51 * 2

    by_state_year = combined.set_index(["state", "year"])

    ca_2024 = by_state_year.loc[("California", 2024)]
    assert ca_2024["state_abbr"] == "CA"
    # ai_interest_index is the mean of Claude AI (78) and ChatGPT (90) for 2024.
    assert ca_2024["ai_interest_index"] == 84.0
    assert ca_2024["small_claims_filings"] == 150000
    assert ca_2024["data_coverage_notes"] == "trends,court-stats,no-parking"

    # 2023 fixtures only include Claude AI (no ChatGPT) and no CA court-stats row.
    ca_2023 = by_state_year.loc[("California", 2023)]
    assert ca_2023["ai_interest_index"] == 30.0
    assert ca_2023["data_coverage_notes"] == "trends,no-court-stats,no-parking"

    ny_2024 = by_state_year.loc[("New York", 2024)]
    assert ny_2024["small_claims_avg_processing_days"] == 74
    # 2 "HEARING HELD-GUILTY" + 1 "APPEAL AFFIRMED" from the fixture.
    assert ny_2024["parking_hearing_records"] == 3
    assert ny_2024["parking_appeal_records"] == 1
    assert ny_2024["data_coverage_notes"] == "trends,court-stats,parking"

    # Parking fixture only covers 2024, so 2023 has no parking data.
    ny_2023 = by_state_year.loc[("New York", 2023)]
    assert ny_2023["small_claims_avg_processing_days"] == 80
    assert pd.isna(ny_2023["parking_hearing_records"])
    assert ny_2023["data_coverage_notes"] == "trends,court-stats,no-parking"

    # A state with no gov-usage fixture data at all still appears, with NaNs.
    wyoming_2024 = by_state_year.loc[("Wyoming", 2024)]
    assert wyoming_2024["ai_interest_index"] == 10.0
    assert wyoming_2024["data_coverage_notes"] == "trends,no-court-stats,no-parking"

    montana_2024 = by_state_year.loc[("Montana", 2024)]
    assert montana_2024["data_coverage_notes"] == "no-trends,no-court-stats,no-parking"


def test_state_normalization_handles_abbreviations_and_cities():
    from src.us_states import normalize_state_name

    assert normalize_state_name("California") == "California"
    assert normalize_state_name("ca") == "California"
    assert normalize_state_name("New York City") == "New York"
    assert normalize_state_name("Not A Real Place") is None
