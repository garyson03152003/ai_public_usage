"""Fetch MONTHLY Texas small-claims (Justice Court civil) case activity from
the Texas Office of Court Administration's Court Activity Reporting Database
(card.txcourts.gov).

This is the one small-claims source this project found that actually has
month-level resolution, statewide. Everything else investigated
(data.gov/BJS "State Court Statistics Series", NCSC's Court Statistics
Project on Tableau -- see fetch_court_stats.py) is annual at best, or
requires an interactive Tableau session this sandbox can't reach (no
WebSocket support through the egress proxy). Texas's own OCA report tool
(https://card.txcourts.gov/ReportSelection.aspx) turned out to expose a
"Justice Court Activity Detail" report with an explicit from/to
month+year picker -- confirmed live, not assumed, by driving the tool's
ASP.NET WebForms postback sequence with plain `requests` (no browser
needed) and checking the returned figures actually change per month
requested.

Coverage: Texas only, statewide (ddlCountyPostBack="0" = "All" counties).
The HB79 reporting period starts 9/2013; data before that needs the
separate "Pre-HB79" period, not implemented here since it predates this
project's 2020+ range. Each monthly export's header reports a "Percent
Reporting Rate" (e.g. "96.2 Percent Reporting Rate, 9,286 Reports Received
Out of a Possible 9,648") -- courts self-report to OCA and coverage is
usually >90% but not 100%; this isn't captured per-row here, just noted so
consumers know small gaps in a given month are normal under-reporting, not
a fetch bug.

How the tool actually works (reverse-engineered live against the real
site): it's classic ASP.NET WebForms, driven by `__doPostBack` on
`<select>` `onchange` handlers, each carrying forward `__VIEWSTATE` /
`__EVENTVALIDATION` from the previous response. The sequence to reach the
query form is:
  1. GET  ReportSelection.aspx
  2. POST __EVENTTARGET=ddlReportType,  ddlReportType=5020        (Justice Courts)
  3. POST __EVENTTARGET=ddlReportName,  ddlReportName=134         (Justice Court Activity Detail)
  4. POST __EVENTTARGET=ddlReportPeriod, ddlReportPeriod=HB79     (9/2013-present)
  5. POST __EVENTTARGET=cmdContinue                                -> redirects (via the
     response's own <form action=...>) to ReportCriteria.aspx, which carries the actual
     date-range/county/format picker. Note the form's `action` attribute must be followed
     -- it is NOT the same page as step 1-4, and posting to the wrong URL here silently
     produces a generic ASP.NET "Runtime Error" 500 (confirmed by trying the obvious-but-
     wrong same-URL approach first).
  6. POST __EVENTTARGET=ddlFromYear (or any date field) once, with a real year selected
     (e.g. 2020) -- this repopulates ddlFromMonth/ddlToMonth from a fixed 4-option stub
     (Sep-Dec only, an artifact of the 2013 HB79 start date being pre-selected) to the
     full 12 months for that year. Confirmed live: before this postback only Sep-Dec show
     as options; after selecting a later year, Jan-Dec are all present.
  7. POST __EVENTTARGET=btnRunReport with ddlFromMonth/ddlFromYear/ddlToMonth/ddlToYear
     set to the same month (for a single-month pull), ddlCountyPostBack="0" (statewide),
     ddlFormat="1625" (MS Excel -- a real Crystal-Reports-generated .xls, confirmed via
     `file`, not an HTML table in disguise). The response IS the file directly (no further
     redirect), streamed as `application/vnd.ms-excel`.

Steps 1-6 only need to happen once per session: the VIEWSTATE captured after
step 6 stays valid for repeated step-7 calls with different month/year
values (confirmed live -- ran it back-to-back for Feb 2020 and Mar 2020 off
the same captured fields and got two distinct, correct months back), so
fetching a whole year range costs 1 session setup + 1 request per month,
not 6 requests per month.

The .xls itself is a fixed Crystal Reports layout (same for every month):
a "CIVIL CASES" section with a 4-column table (Debt Claim / Landlord-Tenant
/ Small Claims / Total) giving "New Cases Filed" (filings) and "Total Cases
Disposed" (dispositions) rows, among others. This module parses those two
rows by label rather than by fixed row/column index, since blank
formatting rows shift slightly in different exports.

Usage:
    python -m src.gov_usage.fetch_tx_card --start 2020-01 --end 2026-08
"""

from __future__ import annotations

import argparse
import io
import re
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "court_stats"
OUTPUT_PATH = RAW_DIR / "tx_justice_court_civil_month.csv"

BASE_URL = "https://card.txcourts.gov/ReportSelection.aspx"
REPORT_TYPE_JUSTICE_COURTS = "5020"
REPORT_NAME_ACTIVITY_DETAIL = "134"
REPORT_PERIOD_HB79 = "HB79"
FORMAT_EXCEL = "1625"
COUNTY_ALL = "0"

CASE_TYPES = ("Debt Claim", "Landlord/Tenant", "Small Claims")

_HIDDEN_FIELD_NAMES = ["__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__EVENTARGUMENT"]


@dataclass
class CardSession:
    session: requests.Session
    url: str
    fields: dict


def _parse_hidden(html: str) -> dict:
    fields = {}
    for name in _HIDDEN_FIELD_NAMES:
        m = re.search(rf'id="{name}"[^>]*value="([^"]*)"', html)
        fields[name] = m.group(1) if m else ""
    return fields


def _form_action(html: str, fallback: str) -> str:
    m = re.search(r'<form[^>]*action="([^"]+)"', html)
    if not m:
        return fallback
    action = m.group(1).replace("&amp;", "&")
    return action if action.startswith("http") else "https://card.txcourts.gov/" + action


def _post(session: requests.Session, url: str, data: dict) -> requests.Response:
    resp = session.post(url, data=data, timeout=60)
    resp.raise_for_status()
    return resp


def start_session() -> CardSession:
    """Run the one-time postback sequence (steps 1-6 in the module
    docstring) that lands on the Justice Court Activity Detail / HB79
    query form with a real year selected, ready for repeated btnRunReport
    calls for individual months."""
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0"})

    resp = s.get(BASE_URL, timeout=30)
    resp.raise_for_status()
    html = resp.text
    fields = _parse_hidden(html)
    url = BASE_URL

    data = {"__EVENTTARGET": "ddlReportType", "__EVENTARGUMENT": "", **fields, "ddlReportType": REPORT_TYPE_JUSTICE_COURTS}
    html = _post(s, url, data).text
    fields = _parse_hidden(html)
    url = _form_action(html, url)

    data = {
        "__EVENTTARGET": "ddlReportName",
        "__EVENTARGUMENT": "",
        **fields,
        "ddlReportType": REPORT_TYPE_JUSTICE_COURTS,
        "ddlReportName": REPORT_NAME_ACTIVITY_DETAIL,
    }
    html = _post(s, url, data).text
    fields = _parse_hidden(html)
    url = _form_action(html, url)

    data = {
        "__EVENTTARGET": "ddlReportPeriod",
        "__EVENTARGUMENT": "",
        **fields,
        "ddlReportType": REPORT_TYPE_JUSTICE_COURTS,
        "ddlReportName": REPORT_NAME_ACTIVITY_DETAIL,
        "ddlReportPeriod": REPORT_PERIOD_HB79,
    }
    html = _post(s, url, data).text
    fields = _parse_hidden(html)
    url = _form_action(html, url)

    data = {
        "__EVENTTARGET": "cmdContinue",
        "__EVENTARGUMENT": "",
        **fields,
        "ddlReportType": REPORT_TYPE_JUSTICE_COURTS,
        "ddlReportName": REPORT_NAME_ACTIVITY_DETAIL,
        "ddlReportPeriod": REPORT_PERIOD_HB79,
    }
    html = _post(s, url, data).text
    fields = _parse_hidden(html)
    url = _form_action(html, url)

    base_extra = {
        "ddlReportType": REPORT_TYPE_JUSTICE_COURTS,
        "ddlReportName": REPORT_NAME_ACTIVITY_DETAIL,
        "ddlReportPeriod": REPORT_PERIOD_HB79,
        "txtReportName": "JC_Justice_Court_Activity_Detail_HB79_N.rpt",
        "txtReportTypeDesc": "Justice Courts",
        "chkFrom": "on",
        "chkTo": "on",
        "txtFromMonthField": "@FromMonth",
        "txtFromYearField": "@FromYear",
        "txtToMonthField": "@ToMonth",
        "txtToYearField": "@ToYear",
        "txtCountyPostBackField": "@CountyID",
        "txtPrecinctField": "@PrecinctID",
        "txtPlaceField": "@PrecinctPlaceID",
        "ddlFromMonth": "9",
        "ddlFromYear": "2013",
        "ddlToMonth": "9",
        "ddlToYear": "2013",
        "ddlCountyPostBack": COUNTY_ALL,
        "ddlPlace": "0",
        "ddlPrecinct": "0",
        "ddlFormat": "1706",
    }

    # Selecting a real year repopulates ddlFromMonth/ddlToMonth from the
    # Sep-Dec-only stub to the full 12 months -- see module docstring.
    data = {"__EVENTTARGET": "ddlFromYear", "__EVENTARGUMENT": "", **fields, **base_extra}
    data["ddlFromYear"] = "2020"
    data["ddlToYear"] = "2020"
    html = _post(s, url, data).text
    fields = _parse_hidden(html)

    return CardSession(session=s, url=url, fields={**base_extra, **fields})


def fetch_month_xls(card: CardSession, year: int, month: int) -> bytes:
    """Run the report for a single statewide month and return the raw
    .xls bytes (a Crystal Reports export, not an HTML table)."""
    data = {"__EVENTTARGET": "btnRunReport", "__EVENTARGUMENT": "", **card.fields}
    data["ddlFromMonth"] = str(month)
    data["ddlFromYear"] = str(year)
    data["ddlToMonth"] = str(month)
    data["ddlToYear"] = str(year)
    data["ddlCountyPostBack"] = COUNTY_ALL
    data["ddlFormat"] = FORMAT_EXCEL

    resp = _post(card.session, card.url, data)
    content_type = resp.headers.get("Content-Type", "")
    if "excel" not in content_type and "spreadsheet" not in content_type:
        raise RuntimeError(
            f"Expected an Excel response for {year}-{month:02d}, got Content-Type={content_type!r} "
            f"(likely the postback sequence broke -- see module docstring for the expected steps)"
        )
    return resp.content


def _to_num(value) -> int:
    if pd.isna(value) or value == "---":
        return 0
    s = str(value).replace(",", "").strip()
    if s.startswith("(") and s.endswith(")"):
        return -int(s[1:-1])
    return int(s)


def parse_civil_case_activity(xls_bytes: bytes, year: int, month: int) -> pd.DataFrame:
    """Parse the CIVIL CASES section (Debt Claim / Landlord-Tenant / Small
    Claims) out of one monthly export: filings ("New Cases Filed") and
    dispositions ("Total Cases Disposed") per case type."""
    df = pd.read_excel(io.BytesIO(xls_bytes), sheet_name=0, header=None)

    civil_row = None
    for i in range(len(df)):
        if any(isinstance(v, str) and "CIVIL CASES" in v for v in df.iloc[i]):
            civil_row = i
            break
    if civil_row is None:
        raise ValueError(f"Could not find 'CIVIL CASES' section in {year}-{month:02d} export")

    header_row = None
    for i in range(civil_row, civil_row + 5):
        if any(isinstance(v, str) and "Small Claims" in v for v in df.iloc[i]):
            header_row = i
            break
    if header_row is None:
        raise ValueError(f"Could not find civil-case-type header row in {year}-{month:02d} export")

    col_map = {}
    for j, v in enumerate(df.iloc[header_row]):
        if isinstance(v, str):
            label = v.replace("\n", "").strip()
            if label in CASE_TYPES:
                col_map[label] = j
    missing = [c for c in CASE_TYPES if c not in col_map]
    if missing:
        raise ValueError(f"Missing expected case-type columns {missing} in {year}-{month:02d} export")

    def find_row(label: str) -> int:
        for i in range(header_row, header_row + 60):
            row = df.iloc[i]
            for v in row[:6]:
                if isinstance(v, str) and v.strip().lstrip("\xa0") == label:
                    return i
        raise ValueError(f"Could not find row {label!r} in {year}-{month:02d} export")

    filed_row = find_row("New Cases Filed")
    disposed_row = find_row("Total Cases Disposed")

    rows = []
    for case_type in CASE_TYPES:
        col = col_map[case_type]
        rows.append(
            {
                "state": "Texas",
                "year": year,
                "month": month,
                "case_type": case_type,
                "filings": _to_num(df.iloc[filed_row, col]),
                "dispositions": _to_num(df.iloc[disposed_row, col]),
            }
        )
    return pd.DataFrame(rows)


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
    CSV. Resumable: if output_path already exists and force=False, months
    already present are skipped."""
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

    print(f"Fetching {len(months)} month(s) from Texas CARD: {months[0]} .. {months[-1]}")
    card = start_session()

    new_frames = []
    for i, (y, m) in enumerate(months):
        try:
            xls_bytes = fetch_month_xls(card, y, m)
            frame = parse_civil_case_activity(xls_bytes, y, m)
            new_frames.append(frame)
            print(f"  {y}-{m:02d}: OK ({frame['filings'].sum()} total civil filings)")
        except Exception as exc:
            print(f"  {y}-{m:02d}: FAILED -- {exc}")
        if i < len(months) - 1:
            time.sleep(delay_seconds)

    if not new_frames:
        print("No months fetched successfully.")
        return output_path

    combined = pd.concat([existing, *new_frames], ignore_index=True) if not existing.empty else pd.concat(new_frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["state", "year", "month", "case_type"], keep="last")
    combined = combined.sort_values(["year", "month", "case_type"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_path, index=False)
    print(f"Wrote {len(combined)} row(s) -> {output_path}")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", required=True, help="Start year-month, e.g. 2020-01")
    parser.add_argument("--end", required=True, help="End year-month, e.g. 2026-08")
    parser.add_argument("--out", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--force", action="store_true", help="Refetch months even if already present in --out")
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds to sleep between month requests (default 1.0)")
    args = parser.parse_args()

    sy, sm = (int(x) for x in args.start.split("-"))
    ey, em = (int(x) for x in args.end.split("-"))
    fetch_range(sy, sm, ey, em, output_path=args.out, force=args.force, delay_seconds=args.delay)


if __name__ == "__main__":
    main()
