import fitz
import pytest

from src.gov_usage.fetch_wa_caseload import parse_small_claims_section


def _build_fake_report_pdf(with_toc_decoy: bool = False) -> bytes:
    """A minimal PDF mimicking the real monthly bundle closely enough for
    parse_small_claims_section: optionally a decoy table-of-contents page
    whose "Small Claims Cases - Proceedings Detailed Report" line also
    starts with "Small Claims Cases -" (the real report has exactly this
    line, and an earlier version of the parser matched it by mistake),
    followed by the real "Small Claims Cases - <Month> <Year>" section
    with a "State Total" row of 9 numbers."""
    doc = fitz.open()

    if with_toc_decoy:
        toc_page = doc.new_page()
        toc_page.insert_text((50, 50), "Table of Contents")
        toc_page.insert_text((50, 70), "Small Claims Cases - Proceedings Detailed Report          177")

    page = doc.new_page()
    page.insert_text((50, 50), "Caseloads of the Courts of Washington")
    page.insert_text((50, 70), "Small Claims Cases - July 2026")
    page.insert_text((50, 90), "Page 1 of 4")
    page.insert_text((50, 150), "State Total  469  64  244  58  366  106  182  328  1")
    page.insert_text((50, 170), "Chelan County")

    return doc.write()


def test_parse_small_claims_section_extracts_filings_and_dispositions():
    pdf_bytes = _build_fake_report_pdf()
    result = parse_small_claims_section(pdf_bytes, year=2026, month=7)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["state"] == "Washington"
    assert row["year"] == 2026
    assert row["month"] == 7
    assert row["filings"] == 469
    assert row["dispositions"] == 366


def test_parse_small_claims_section_skips_toc_decoy_line():
    """Regression test: a table-of-contents entry for the 'Proceedings
    Detailed Report' sub-section also starts with 'Small Claims Cases -',
    which made an earlier version of the section-title check match the
    wrong page (one with no 'State Total' row) and raise."""
    pdf_bytes = _build_fake_report_pdf(with_toc_decoy=True)
    result = parse_small_claims_section(pdf_bytes, year=2026, month=7)
    assert result.iloc[0]["filings"] == 469


def test_parse_small_claims_section_raises_when_section_missing():
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Some Other Report")
    pdf_bytes = doc.write()

    with pytest.raises(ValueError, match="Could not find"):
        parse_small_claims_section(pdf_bytes, year=2026, month=7)
