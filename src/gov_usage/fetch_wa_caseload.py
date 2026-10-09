"""Fetch MONTHLY Washington state small-claims case activity from the
Administrative Office of the Courts' "Caseloads of the Courts of
Washington" monthly report archive.

Found as part of a broader 50-state search for a second (non-Texas)
small-claims source with real month-level resolution -- see
fetch_tx_card.py's docstring for the first one found (Texas). Washington
turned out to have exactly what was needed, confirmed live:

  - courts.wa.gov/caseload/?fa=caseload.showIndex&level=d&freq=m lists
    Washington's "Courts of Limited Jurisdiction" monthly reports, one of
    which (fileID=rpt12) is literally titled "Small Claims Cases" -- not
    folded into a broader civil category the way Virginia's monthly GDC
    filings report turned out to be (checked and ruled out first: VA's
    "General Civil & Civil Commitments" category doesn't separately track
    small claims, confirmed by reading its Quick Reference Guide too).
  - The live rpt12 page only ever shows the latest processed month, but
    every past month is separately archived as a large, predictably-named
    PDF: `/caseload/content/archive/clj/Monthly/<year>/<Mon><year>Mon.pdf`
    (e.g. `Jul2026Mon.pdf`), confirmed going back to 2000. No query
    string, no session, no postback needed -- just construct the URL.
  - Each monthly PDF bundles every "Courts of Limited Jurisdiction"
    report together; "Small Claims Cases" is one section, found by
    searching for the page whose title line is exactly "Small Claims
    Cases - <Month> <Year>" (page numbers shift month to month, since the
    bundle is assembled dynamically -- and a loose "starts with" title
    check isn't specific enough: the table of contents itself has a line
    "Small Claims Cases - Proceedings Detailed Report ... 177" for a
    different section, confirmed live to match first and produce a
    "no State Total row" error before this stricter pattern was used).
    Confirmed the real section's "State Total" row matches the live
    rpt12 HTML page's numbers exactly for the same month (469 cases
    filed, 366 disposed, July 2026, checked both ways).

Extracting the numbers needs `page.get_text(sort=True)` specifically --
without `sort=True`, PyMuPDF's default reading order badly interleaves
this report's multi-column table (confirmed by trying both ways on the
same page); with it, "State Total" and its 9 numbers land cleanly on one
line, in the same order as the column headers: Cases Filed, Default,
Other Pre-Trial, After Trial, Disposed (total), Transfer to Civil,
Contested Hearings, Other Hearings, Cases Appealed. This module keeps
just the two that matter here: Cases Filed (filings) and Disposed
(dispositions).

The most recent 1-2 months are typically not archived yet (confirmed
live: as of this writing the August 2026 archive URL 404s via an HTML
redirect page, not a real PDF, while July 2026 is a normal ~180-page
PDF) -- fetch_month() detects this (a real PDF starts with the `%PDF`
magic bytes; the redirect page doesn't) and raises rather than silently
mis-parsing an HTML error page as if it were a report.

Usage:
    python -m src.gov_usage.fetch_wa_caseload --start 2020-01 --end 2026-07
"""

from __future__ import annotations

import argparse
import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover
    raise ImportError("This module needs PyMuPDF: pip install pymupdf") from exc

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "court_stats"
OUTPUT_PATH = RAW_DIR / "wa_small_claims_month.csv"

BASE_URL = "https://www.courts.wa.gov/caseload/content/archive/clj/Monthly/{year}/{abbr}{year}Mon.pdf"
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

STATE_TOTAL_ROW = re.compile(r"State Total\s+([\d,\-\s]+?)(?:\n|$)")
# Matches e.g. "Small Claims Cases - July 2026", but not the table of
# contents' "Small Claims Cases - Proceedings Detailed Report ... 177"
# entry (that section is a different report -- a separate PDF page whose
# title also starts with "Small Claims Cases -", found and rejected here
# live before landing on this stricter pattern).
SECTION_TITLE = re.compile(r"^Small Claims Cases - [A-Za-z]+ \d{4}$")


def fetch_month_pdf(year: int, month: int, timeout: int = 60) -> bytes:
    """Download one month's combined "Courts of Limited Jurisdiction"
    report. Raises if the archive doesn't have this month yet (returns an
    HTML redirect page instead of a real PDF -- typically the most recent
    1-2 months)."""
    url = BASE_URL.format(year=year, abbr=MONTH_ABBR[month - 1])
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        raise RuntimeError(f"{year}-{month:02d} not archived yet (got a non-PDF response from {url})")
    return resp.content


def parse_small_claims_section(pdf_bytes: bytes, year: int, month: int) -> pd.DataFrame:
    """Find the "Small Claims Cases" section in one monthly PDF bundle
    and return its statewide totals as a single-row DataFrame."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        text = page.get_text(sort=True)
        lines = text.splitlines()
        if not any(SECTION_TITLE.match(line.strip()) for line in lines):
            continue
        match = STATE_TOTAL_ROW.search(text)
        if not match:
            raise ValueError(f"Found the Small Claims Cases page for {year}-{month:02d} but no 'State Total' row in it")
        numbers = [int(n.replace(",", "")) if n not in ("-", "--", "---") else 0 for n in match.group(1).split()]
        if len(numbers) != 9:
            raise ValueError(f"Expected 9 numbers in the State Total row for {year}-{month:02d}, got {len(numbers)}: {numbers}")
        filed, _default, _other_pretrial, _after_trial, disposed, _transfer, _contested, _other_hearings, _appealed = numbers
        return pd.DataFrame([{"state": "Washington", "year": year, "month": month, "filings": filed, "dispositions": disposed}])
    raise ValueError(f"Could not find a 'Small Claims Cases' section in the {year}-{month:02d} report")


def fetch_range(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    output_path: Path = OUTPUT_PATH,
    force: bool = False,
    delay_seconds: float = 1.0,
) -> Path:
    """Fetch every month in [start, end] (inclusive) and write one combined
    CSV. Resumable: months already in output_path are skipped unless force."""
    existing = pd.DataFrame()
    if output_path.exists() and not force:
        existing = pd.read_csv(output_path)

    months = []
    y, m = start_year, start_month
    while (y, m) <= (end_year, end_month):
        already_done = not existing.empty and ((existing["year"] == y) & (existing["month"] == m)).any()
        if not already_done:
            months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1

    if not months:
        print(f"All months in range already present in {output_path}, nothing to do.")
        return output_path

    print(f"Fetching {len(months)} month(s) from WA Courts of Limited Jurisdiction reports: {months[0]} .. {months[-1]}")

    new_frames = []
    for i, (y, m) in enumerate(months):
        try:
            pdf_bytes = fetch_month_pdf(y, m)
            frame = parse_small_claims_section(pdf_bytes, y, m)
            new_frames.append(frame)
            print(f"  {y}-{m:02d}: OK ({int(frame['filings'].iloc[0])} small claims filings)")
        except Exception as exc:
            print(f"  {y}-{m:02d}: FAILED -- {exc}")
        if i < len(months) - 1:
            time.sleep(delay_seconds)

    if not new_frames:
        print("No months fetched successfully.")
        return output_path

    combined = pd.concat([existing, *new_frames], ignore_index=True) if not existing.empty else pd.concat(new_frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["state", "year", "month"], keep="last")
    combined = combined.sort_values(["year", "month"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    print(f"Wrote {len(combined)} row(s) -> {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", required=True, help="Start year-month, e.g. 2020-01")
    parser.add_argument("--end", required=True, help="End year-month, e.g. 2026-07")
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--force", action="store_true", help="Refetch months even if already present in --out")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to sleep between month requests (default 1.0)")
    args = parser.parse_args()

    sy, sm = (int(x) for x in args.start.split("-"))
    ey, em = (int(x) for x in args.end.split("-"))
    fetch_range(sy, sm, ey, em, output_path=args.out, force=args.force, delay_seconds=args.delay)


if __name__ == "__main__":
    main()
