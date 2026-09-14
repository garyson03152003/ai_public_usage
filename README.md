# ai_public_usage

Data pipeline that compiles two things side by side, by US state, for
2020 through the current year:

1. **AI usage, proxied by Google search interest** — Google Trends'
   "interest by region", per calendar year, for a broad list of
   AI-related terms (Anthropic, Claude and specific Claude models,
   ChatGPT/OpenAI, Gemini, Copilot, Perplexity, DeepSeek, Llama, Grok,
   Mistral, ...).
2. **Public-resource usage** — state-level civil/small-claims court
   caseloads and processing times, plus NYC parking-ticket hearing/appeal
   volume as an illustrative city case study.

The two are merged into one state x year panel
(`data/processed/combined_state_data.csv`) for exploratory analysis.

## Network requirements

The fetch scripts need normal internet access to `trends.google.com` and
city/state open-data portals (e.g. `data.cityofnewyork.us`). Some
network-restricted sandboxes block this (you'll see connection or 403/
`EGRESS_BLOCKED` errors) — if so, run the `fetch_*.py` scripts from a
machine or CI job with open internet access instead. `src/combine.py` and
the test suite need no network and run anywhere, against whatever is
already in `data/raw/`.

## Layout

```
src/
  us_states.py              # state name/abbreviation/city normalization used to join everything
  trends/
    terms.py                # the list of search terms tracked
    fetch_trends.py          # pytrends: per-term, per-year interest-by-region -> data/raw/trends/<year>/<term>.csv
  gov_usage/
    fetch_court_stats.py     # data.gov CKAN attempt + manual-export normalizer for court caseload data
    fetch_socrata.py         # Socrata (SODA API) fetcher, aggregated per year, for city portals
    sources.yaml              # config: which city/state open-data sources to pull
  combine.py                  # merges data/raw/* -> data/processed/combined_state_data.csv (state x year panel)
data/
  raw/          # one subfolder per source, gitignored (regenerate by re-running fetch_*.py)
  processed/    # combined_state_data.csv, gitignored
tests/          # unit tests against small fixture CSVs, no network needed
```

## Setup

```bash
pip install -r requirements.txt
```

## Running the pipeline

```bash
# 1. Google Trends by state, one year at a time, 2020-present, for the
#    default term list in src/trends/terms.py
python -m src.trends.fetch_trends
# or a custom term list / year range:
python -m src.trends.fetch_trends --terms "Claude AI" "ChatGPT" --start-year 2023 --end-year 2026

# 2. Government usage data
python -m src.gov_usage.fetch_court_stats          # best-effort data.gov download attempt, see caveat below
python -m src.gov_usage.fetch_socrata              # pulls city portals enabled in sources.yaml, 2020-present

# 3. Merge everything into the state x year panel
python -m src.combine
```

Step 2's `fetch_court_stats.py` is honest about a real limitation: as of
2026, data.gov's classic CKAN API (`catalog.data.gov/api/3/action/*`) is
gone — confirmed by hitting it directly, not assumed — so the previously
scriptable DOJ/BJS "State Court Statistics Series" download no longer
works from code. There's no current replacement API. The reliable path is
`fetch_court_stats.normalize_manual_export(...)`: manually export
state/case-type slices from the National Center for State Courts' CSP STAT
dashboard (https://www.courtstatistics.org/court-statistics/interactive-caseload-data-displays/csp-stat)
and normalize them with that function — see the docstring in
`src/gov_usage/fetch_court_stats.py`.

## Data sources and known gaps

- **Google Trends** ("interest by region", 0–100 relative scale per term
  per calendar year) — fetched one term and one year at a time via
  `pytrends` (so each year is its own request, not a several-year average)
  and averaged across terms into an `ai_interest_index` per (state, year).
  This is *relative search interest*, not usage; a spike can reflect news
  coverage as easily as adoption. Low-population states can be noisy or
  suppressed entirely by Google Trends for low search volume.
- **State court caseloads** — no working automated nationwide source as
  of 2026 (see above); use the NCSC CSP STAT manual-export path. Once
  normalized, `combine.py` keeps every (state, year) row rather than
  collapsing to a single snapshot.
- **Parking ticket appeals** — there is no national dataset. This repo
  ships one verified source: NYC's "Open Parking and Camera Violations"
  (Socrata dataset `nc67-uf89` on `data.cityofnewyork.us`), which has a
  real `violation_status` field with hearing/appeal outcomes (HEARING
  HELD-GUILTY/NOT GUILTY, HEARING ADJOURNMENT, APPEAL AFFIRMED/REVERSED/
  ABANDONED/MODIFIED, etc.) — confirmed against the live API. The table
  is huge (hundreds of millions of rows) and `issue_date` is stored as
  plain text, so `fetch_socrata.py` aggregates counts per
  year/outcome server-side rather than downloading raw rows; expect each
  year to take a couple of minutes unauthenticated (pass a free Socrata
  app token via `--app-token` to speed this up). A placeholder for Chicago
  is in `sources.yaml` pending someone confirming its current dataset id.
  Treat this part of the combined table as an NYC case study, not a
  50-state comparison.

`data/processed/combined_state_data.csv` includes a `data_coverage_notes`
column per (state, year) row (e.g. `trends,court-stats,no-parking`) so
gaps are explicit rather than silently blank.

## Tests

```bash
python -m pytest tests/
```

Tests run against small fixture CSVs in `tests/fixtures/` and don't touch
the network or `data/raw/`.
