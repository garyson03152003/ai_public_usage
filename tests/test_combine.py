from pathlib import Path

import pandas as pd

from src.combine import combine, load_tx_small_claims_annual

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_combine_builds_state_year_panel(tmp_path):
    output_path = tmp_path / "combined_state_data.csv"

    combined = combine(
        trends_dir=FIXTURES / "trends",
        court_stats_dir=FIXTURES / "court_stats",
        tx_card_path=tmp_path / "no_tx_data_here.csv",
        parking_dir=FIXTURES / "parking_tickets",
        unemployment_dir=FIXTURES / "unemployment",
        controls_dir=FIXTURES / "controls",
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
    assert ca_2024["ui_pct_within_21_days"] == 72.5
    assert ca_2024["unemployment_rate_avg"] == 5.2
    assert ca_2024["data_coverage_notes"] == "trends,court-stats,no-parking,unemployment,controls"

    # 2023 fixtures only include Claude AI (no ChatGPT) and no CA court-stats/UI row.
    ca_2023 = by_state_year.loc[("California", 2023)]
    assert ca_2023["ai_interest_index"] == 30.0
    assert pd.isna(ca_2023["ui_pct_within_21_days"])
    assert ca_2023["data_coverage_notes"] == "trends,no-court-stats,no-parking,no-unemployment,no-controls"

    ny_2024 = by_state_year.loc[("New York", 2024)]
    assert ny_2024["small_claims_avg_processing_days"] == 74
    # 2 "HEARING HELD-GUILTY" + 1 "APPEAL AFFIRMED" from the fixture.
    assert ny_2024["parking_hearing_records"] == 3
    assert ny_2024["parking_appeal_records"] == 1
    assert ny_2024["ui_first_payments_total"] == 50000
    assert ny_2024["unemployment_rate_avg"] == 4.4
    assert ny_2024["data_coverage_notes"] == "trends,court-stats,parking,unemployment,controls"

    # Parking fixture only covers 2024, but UI/controls fixtures cover both years.
    ny_2023 = by_state_year.loc[("New York", 2023)]
    assert ny_2023["small_claims_avg_processing_days"] == 80
    assert pd.isna(ny_2023["parking_hearing_records"])
    assert ny_2023["ui_pct_within_21_days"] == 60.0
    assert ny_2023["unemployment_rate_avg"] == 4.1
    assert ny_2023["data_coverage_notes"] == "trends,court-stats,no-parking,unemployment,controls"

    # A state with no gov-usage fixture data at all still appears, with NaNs.
    wyoming_2024 = by_state_year.loc[("Wyoming", 2024)]
    assert wyoming_2024["ai_interest_index"] == 10.0
    assert wyoming_2024["data_coverage_notes"] == "trends,no-court-stats,no-parking,no-unemployment,no-controls"

    montana_2024 = by_state_year.loc[("Montana", 2024)]
    assert montana_2024["data_coverage_notes"] == "no-trends,no-court-stats,no-parking,no-unemployment,no-controls"


def test_combine_merges_tx_small_claims_into_court_stats(tmp_path):
    output_path = tmp_path / "combined_state_data.csv"

    combined = combine(
        trends_dir=FIXTURES / "trends",
        court_stats_dir=FIXTURES / "court_stats",
        tx_card_path=FIXTURES / "court_stats" / "tx_justice_court_civil_month.csv",
        parking_dir=FIXTURES / "parking_tickets",
        unemployment_dir=FIXTURES / "unemployment",
        controls_dir=FIXTURES / "controls",
        output_path=output_path,
        start_year=2022,
        end_year=2022,
    )

    texas_2022 = combined.set_index(["state", "year"]).loc[("Texas", 2022)]
    # Fixture has Nov + Dec 2022 Small Claims filings 5000 + 6000 = 11000.
    assert texas_2022["small_claims_filings"] == 11000
    assert texas_2022["data_coverage_notes"] == "no-trends,court-stats,no-parking,no-unemployment,no-controls"


def test_load_tx_small_claims_annual_rolls_up_months():
    result = load_tx_small_claims_annual(FIXTURES / "court_stats" / "tx_justice_court_civil_month.csv")
    assert len(result) == 1
    row = result.iloc[0]
    assert row["state"] == "Texas"
    assert row["year"] == 2022
    assert row["small_claims_filings"] == 11000
    assert row["small_claims_dispositions"] == 10500


def test_load_tx_small_claims_annual_missing_file_returns_empty():
    result = load_tx_small_claims_annual(Path("/nonexistent/path.csv"))
    assert result.empty


def test_state_normalization_handles_abbreviations_and_cities():
    from src.us_states import normalize_state_name

    assert normalize_state_name("California") == "California"
    assert normalize_state_name("ca") == "California"
    assert normalize_state_name("New York City") == "New York"
    assert normalize_state_name("Not A Real Place") is None
