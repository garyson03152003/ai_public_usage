import io

import pandas as pd

from src.gov_usage.fetch_tx_card import parse_civil_case_activity


def _build_fake_report_xlsx() -> bytes:
    """A minimal grid mimicking the real Crystal Reports layout closely
    enough for parse_civil_case_activity: a CIVIL CASES section with a
    Debt Claim / Landlord-Tenant / Small Claims header row, then a "New
    Cases Filed" and (further down, past some unrelated rows) a "Total
    Cases Disposed" row -- exactly the structure/labels the real export
    uses, but with tiny made-up numbers instead of real ones."""
    rows = [[None] * 24 for _ in range(30)]
    rows[5][1] = "CIVIL CASES"
    rows[6][7] = "\n\nDebt Claim"
    rows[6][12] = "\n\nLandlord/Tenant"
    rows[6][15] = "\n\nSmall Claims"
    rows[6][22] = "\n\nTotal"
    rows[10][2] = "New Cases Filed"
    rows[10][7] = "1,000"
    rows[10][12] = "2,000"
    rows[10][15] = "300"
    rows[10][22] = "3,300"
    rows[20][2] = "Total Cases Disposed"
    rows[20][7] = "900"
    rows[20][12] = "1,800"
    rows[20][15] = "250"
    rows[20][22] = "2,950"

    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([None] * (ncols - len(r)))

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, sheet_name="Sheet1", header=False, index=False, engine="openpyxl")
    return buf.getvalue()


def test_parse_civil_case_activity_extracts_small_claims_and_debt_claim():
    xls_bytes = _build_fake_report_xlsx()
    result = parse_civil_case_activity(xls_bytes, year=2021, month=6)

    assert set(result["case_type"]) == {"Debt Claim", "Landlord/Tenant", "Small Claims"}
    assert all(result["state"] == "Texas")
    assert all(result["year"] == 2021)
    assert all(result["month"] == 6)

    small_claims = result[result["case_type"] == "Small Claims"].iloc[0]
    assert small_claims["filings"] == 300
    assert small_claims["dispositions"] == 250

    debt_claim = result[result["case_type"] == "Debt Claim"].iloc[0]
    assert debt_claim["filings"] == 1000
    assert debt_claim["dispositions"] == 900


def test_parse_civil_case_activity_handles_dash_and_parens_as_zero_and_negative():
    rows = [[None] * 24 for _ in range(15)]
    rows[0][1] = "CIVIL CASES"
    rows[1][7] = "\n\nDebt Claim"
    rows[1][12] = "\n\nLandlord/Tenant"
    rows[1][15] = "\n\nSmall Claims"
    rows[3][2] = "New Cases Filed"
    rows[3][7] = "---"
    rows[3][12] = "(5)"
    rows[3][15] = "10"
    rows[6][2] = "Total Cases Disposed"
    rows[6][7] = "0"
    rows[6][12] = "1"
    rows[6][15] = "9"

    df = pd.DataFrame(rows)
    buf = io.BytesIO()
    df.to_excel(buf, sheet_name="Sheet1", header=False, index=False, engine="openpyxl")

    result = parse_civil_case_activity(buf.getvalue(), year=2020, month=1)
    debt_claim = result[result["case_type"] == "Debt Claim"].iloc[0]
    landlord = result[result["case_type"] == "Landlord/Tenant"].iloc[0]
    assert debt_claim["filings"] == 0
    assert landlord["filings"] == -5
