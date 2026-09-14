# ai_public_usage

Data pipeline that compiles two things side by side, by US state:

1. **AI usage, proxied by Google search interest** — Google Trends'
   "interest by region" for a broad list of AI-related terms (Anthropic,
   Claude and specific Claude models, ChatGPT/OpenAI, Gemini, Copilot,
   Perplexity, DeepSeek, Llama, Grok, Mistral, ...).
2. **Public-resource usage** — state-level civil/small-claims court
   caseloads and processing times, plus city-level parking-ticket /
   administrative-hearing appeal volume as illustrative case studies.

The two are merged into one state-level table
(`data/processed/combined_state_data.csv`) for exploratory analysis.

## Network requirements (read this first)

The fetch scripts need normal internet access to `trends.google.com`,
`catalog.data.gov`, and city open-data portals (e.g.
`data.cityofnewyork.us`). **This will fail in a network-restricted
sandbox** (including, by default, this repo's own dev container/CI
environment if it enforces an egress allowlist) — you'll see connection
or 403 errors. Run the `fetch_*.py` scripts from a machine or CI job with
open internet access; `src/combine.py` and the test suite need no network
and run anywhere, against whatever is already in `data/raw/`.

## Layout

```
src/
  us_states.py              # state name/abbreviation/city normalization used to join everything
  trends/
    terms.py                # the list of search terms tracked
    fetch_trends.py          # pytrends: per-term interest-by-region -> data/raw/trends/<term>.csv
  gov_usage/
    fetch_court_stats.py     # data.gov CKAN download + manual-export normalizer for court caseload data
    fetch_socrata.py         # generic Socrata (SODA API) fetcher for city portals
    sources.yaml              # config: which city/state open-data sources to pull
  combine.py                  # merges data/raw/* -> data/processed/combined_state_data.csv
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
# 1. Google Trends by state, for the default term list in src/trends/terms.py
python -m src.trends.fetch_trends
# or a custom term list / longer lookback window:
python -m src.trends.fetch_trends --terms "Claude AI" "ChatGPT" --timeframe "today 5-y"

# 2. Government usage data
python -m src.gov_usage.fetch_court_stats          # downloads the data.gov "State Court Statistics Series" package as-is
python -m src.gov_usage.fetch_socrata              # pulls city portals enabled in sources.yaml

# 3. Merge everything
python -m src.combine
```

Step 2's data.gov download is not yet in this project's standard schema —
inspect what it downloads into `data/raw/court_stats/` and normalize it
with `fetch_court_stats.normalize_manual_export(...)`. That same function
is also how you bring in the National Center for State Courts' richer
CSP STAT small-claims/time-to-disposition figures, which only publish
through an interactive dashboard with manual export (no stable API) — see
the docstring in `src/gov_usage/fetch_court_stats.py`.

## Data sources and known gaps

- **Google Trends** ("interest by region", 0–100 relative scale per term,
  per state) — fetched one term at a time via `pytrends` and averaged into
  an `ai_interest_index` in the combined table. This is *relative search
  interest*, not usage; a spike can reflect news coverage as easily as
  adoption. Low-population states can be noisy or suppressed entirely by
  Google Trends for low search volume.
- **State court caseloads** — the DOJ/BJS "State Court Statistics Series"
  on data.gov (`state-court-statistics-series-a021b`) is the one
  source here with a stable, scriptable download path. The National
  Center for State Courts' Court Statistics Project (courtstatistics.org)
  has more current and granular small-claims data but only via manual
  dashboard export.
- **Parking ticket appeals** — there is no national dataset. This repo
  ships one confirmed source (NYC's OATH Hearings Division Case Status,
  Socrata dataset `jz4z-kudi`) and a placeholder for Chicago in
  `sources.yaml` pending someone confirming its current dataset id. Adding
  more cities means adding more entries to that file — it does not
  generalize to state-level coverage. Treat this part of the combined
  table as city case studies, not a 50-state comparison.

`data/processed/combined_state_data.csv` includes a `data_coverage_notes`
column per state (e.g. `trends,court-stats,no-parking`) so gaps are
explicit rather than silently blank.

## Tests

```bash
python -m pytest tests/
```

Tests run against small fixture CSVs in `tests/fixtures/` and don't touch
the network or `data/raw/`.
