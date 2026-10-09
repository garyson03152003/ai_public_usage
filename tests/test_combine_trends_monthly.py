from pathlib import Path

from src.combine_trends_monthly import build

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "trends_monthly"


def test_builds_state_year_month_panel(tmp_path):
    output_path = tmp_path / "trends_state_month.csv"

    combined = build(trends_monthly_dir=FIXTURES, output_path=output_path)

    assert output_path.exists()
    # 51 states x 2 months in the fixtures.
    assert len(combined) == 51 * 2

    by_state_period = combined.set_index(["state", "year", "month"])

    ca_jan = by_state_period.loc[("California", 2024, 1)]
    assert ca_jan["state_abbr"] == "CA"
    # mean of Claude AI (20) and ChatGPT (80) for January.
    assert ca_jan["ai_interest_index"] == 50.0

    # February fixture only has Claude AI (no ChatGPT).
    ca_feb = by_state_period.loc[("California", 2024, 2)]
    assert ca_feb["ai_interest_index"] == 40.0

    wyoming_jan = by_state_period.loc[("Wyoming", 2024, 1)]
    assert wyoming_jan["ai_interest_index"] == 10.0
