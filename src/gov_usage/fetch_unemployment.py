"""Fetch state-level unemployment-insurance "first payment" processing-time
data from the US Department of Labor's ETA 9050 report (Time Lapse of All
First Payments Except Workshare).

Unlike the other gov_usage sources, this one is genuinely easy: DOL
publishes ar9050.csv directly at a stable URL, updated daily, going back
to 1997, for all states + DC/PR/VI, no API key or pagination needed.

The raw file has no header names beyond "st"/"rptdate" -- columns c1..c96
are a fixed grid documented in DOL's data-map PDF
(https://oui.doleta.gov/dmstree/handbooks/402/402_4/4024c6/4024c6.pdf,
"TABLE ar9050"): 12 time-lapse buckets (<=7, 8-14, 15-21, 22-28, 29-35,
36-42, 43-49, 50-56, 57-63, 64-70, >70 days), each with 8 columns
(Intra-State Total/UI/UCFE/UCX, then Inter-State Total/UI/UCFE/UCX). This
module only uses the Intra-State Total column of each bucket (index 0 of
every 8-column block, i.e. c1, c9, c17, ...) -- the count of ordinary
in-state first payments made within that many days.

Requires network access to oui.doleta.gov.

Usage:
    python -m src.gov_usage.fetch_unemployment
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
import requests

from src.trends.fetch_trends import DEFAULT_START_YEAR
from src.us_states import normalize_state_name

RAW_DIR = Path(__file__).resolve().parents[2] / "data" / "raw" / "unemployment"
SOURCE_URL = "https://oui.doleta.gov/unemploy/csv/ar9050.csv"

# 12 time-lapse buckets in order, each an 8-column block; index 0 of each
# block is "Intra-State Total". Midpoints are used to approximate an
# average days-to-first-payment; ">70" has no natural midpoint so a
# conservative estimate is used -- treat that average as directional, not
# exact, and prefer pct_within_21_days for actual performance comparisons.
BUCKET_MIDPOINTS = [3.5, 11, 18, 25, 32, 39, 46, 53, 60, 67, 80]
N_BUCKETS = len(BUCKET_MIDPOINTS)
BLOCK_WIDTH = 8


def _intrastate_total_columns() -> list[str]:
    return [f"c{i * BLOCK_WIDTH + 1}" for i in range(N_BUCKETS)]


def download_raw(url: str = SOURCE_URL) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    out_path = RAW_DIR / "ar9050_raw.csv"
    out_path.write_bytes(resp.content)
    print(f"Downloaded ETA 9050 -> {out_path} ({len(resp.content)} bytes)")
    return out_path


def summarize_by_state_year(raw_path: Path, start_year: int, end_year: int) -> pd.DataFrame:
    """Aggregate DOL's monthly, bucketed first-payment counts into one row
    per (state, year): total intrastate first payments, the share made
    within 21 days (the de facto federal timeliness benchmark once a
    state's statutory waiting week is accounted for), and an approximate
    average days-to-first-payment from bucket midpoints."""
    raw = pd.read_csv(raw_path)
    raw["year"] = pd.to_datetime(raw["rptdate"]).dt.year
    raw = raw[(raw["year"] >= start_year) & (raw["year"] <= end_year)]
    raw["state"] = raw["st"].map(normalize_state_name)

    bucket_cols = _intrastate_total_columns()
    yearly = raw.groupby(["state", "year"], as_index=False)[bucket_cols].sum()

    total = yearly[bucket_cols].sum(axis=1)
    within_21_days = yearly[bucket_cols[:3]].sum(axis=1)  # <=7, 8-14, 15-21
    weighted_days = sum(yearly[col] * mid for col, mid in zip(bucket_cols, BUCKET_MIDPOINTS))

    out = pd.DataFrame(
        {
            "state": yearly["state"],
            "year": yearly["year"],
            "ui_first_payments_total": total,
            "ui_pct_within_21_days": (within_21_days / total * 100).where(total > 0),
            "ui_avg_days_to_first_payment_approx": (weighted_days / total).where(total > 0),
        }
    )
    return out


def fetch(start_year: int = DEFAULT_START_YEAR, end_year: int | None = None) -> Path:
    end_year = end_year or datetime.date.today().year
    raw_path = download_raw()
    summary = summarize_by_state_year(raw_path, start_year, end_year)

    out_path = RAW_DIR / "eta9050_state_year.csv"
    summary.to_csv(out_path, index=False)
    print(f"Wrote {len(summary)} state-year rows -> {out_path}")
    return out_path


if __name__ == "__main__":
    fetch()
