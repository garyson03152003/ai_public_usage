# ai_public_usage

Data pipeline that compiles two things side by side, by US state, for
2020 through the current year:

1. **AI usage, proxied by Google search interest** — Google Trends'
   "interest by region", per calendar year, for a broad list of
   AI-related terms (Anthropic, Claude and specific Claude models,
   ChatGPT/OpenAI, Gemini, Copilot, Perplexity, DeepSeek, Llama, Grok,
   Mistral, ...).
2. **Public-resource usage** — state-level civil/small-claims court
   caseloads and processing times, NYC parking-ticket hearing/appeal
   volume as an illustrative city case study, and state unemployment-
   insurance first-payment processing time, alongside a control variable
   (state unemployment rate) so the UI processing-time numbers aren't
   compared without accounting for claim-volume pressure.

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
    fetch_trends.py          # pytrends: per-term, per-year (or --granularity month) interest-by-region
  combine_trends_monthly.py   # merges data/raw/trends_monthly/* -> data/processed/trends_state_month.csv
  gov_usage/
    fetch_court_stats.py     # data.gov CKAN attempt + manual-export normalizer for court caseload data
    fetch_socrata.py         # Socrata (SODA API) fetcher, aggregated per year, for city portals
    fetch_unemployment.py    # DOL ETA 9050: UI first-payment processing time, by state x year
    fetch_bls_controls.py    # BLS LAUS: state unemployment rate, the control variable for the above
    sources.yaml              # config: which city/state open-data sources to pull
  combine.py                  # merges data/raw/* -> data/processed/combined_state_data.csv (state x year panel)
  analysis/
    events.py                 # curated, cited list of major AI model/service launch dates
    build_panel.py             # monthly trends + monthly UI data -> analysis_panel_state_month.csv
    event_study.py              # per-event regression: outcome by month relative to launch
    stacked_event_study.py       # pooled regression across all events at once (more reliable)
    fuzzy_rd.py                   # local-linear fuzzy RD at the launch date (Wald/IV estimate)
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

# 1b. Optional: the same thing at monthly granularity instead of yearly,
#     for an actual trend line rather than one point per year. This is
#     ~12x the requests (all 20 terms, 2020-present, is ~1600+ requests --
#     budget a couple of hours) and writes to a separate directory so it
#     doesn't clobber the yearly fetch:
python -m src.trends.fetch_trends --granularity month
python -m src.combine_trends_monthly   # -> data/processed/trends_state_month.csv

# 2. Government usage data
python -m src.gov_usage.fetch_court_stats          # best-effort data.gov download attempt, see caveat below
python -m src.gov_usage.fetch_socrata              # pulls city portals enabled in sources.yaml, 2020-present
python -m src.gov_usage.fetch_unemployment         # DOL ETA 9050, all states, 2020-present
python -m src.gov_usage.fetch_bls_controls         # BLS state unemployment rate (the control variable)

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

  For an actual trend line rather than one point per year, `fetch_trends.py
  --granularity month` fetches the same thing per calendar month instead
  (data/raw/trends_monthly/<year>-<month>/<term>.csv), and
  `combine_trends_monthly.py` builds a state x year x month panel from it
  at `data/processed/trends_state_month.csv`. This is kept as a separate
  file rather than merged into combined_state_data.csv: the government-
  usage data below is only available annually, so joining it onto a
  monthly grid would just repeat each year's value 12 times without
  adding information.
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
  app token via `--app-token` to speed this up).

  The largest city in every other state was checked directly (live API
  queries, not just search results) for an equivalent dataset — see the
  research notes at the top of `sources.yaml`. None qualified: most cities
  have no open-data portal or run ArcGIS Hub/CKAN instead of Socrata, and
  the few genuine Socrata parking-citation datasets found (LA, New
  Orleans, Kansas City, Richmond, Seattle, Dallas, Austin, Providence,
  Philadelphia) only track issuance/payment, not hearing or appeal
  outcomes. NYC appears to be a real outlier in publishing this level of
  detail, so treat this part of the combined table as an NYC case study,
  not a 50-state comparison, until a new source turns up.

- **Unemployment-insurance first-payment processing time** — DOL's ETA
  9050 report ("Time Lapse of All First Payments Except Workshare") is
  published directly as a stable CSV
  (`oui.doleta.gov/unemploy/csv/ar9050.csv`), updated daily, all states +
  DC/PR/VI, back to 1997 — no API key, no pagination, genuinely easy
  compared to the other two sources. `fetch_unemployment.py` aggregates
  DOL's monthly, bucketed (by days-to-payment) counts into
  `ui_pct_within_21_days` and an approximate
  `ui_avg_days_to_first_payment_approx` per (state, year); see the
  docstring for the column layout, taken from DOL's own data-map PDF.
  **This needs a control**: processing time balloons whenever claim volume
  spikes (2020's numbers are dramatically different from surrounding
  years for exactly this reason) for reasons that have nothing to do with
  AI adoption or state competence. `fetch_bls_controls.py` pulls each
  state's annual average unemployment rate from BLS's public LAUS API as
  that control variable (`unemployment_rate_avg`) — treat any comparison
  of the UI processing-time columns across states/years as needing to
  control for it, not read at face value. The BLS API's anonymous quota
  is shared per source IP and can run out for reasons unrelated to this
  project (25 queries/day); pass `--api-key` with a free BLS registration
  if you hit that.

`data/processed/combined_state_data.csv` includes a `data_coverage_notes`
column per (state, year) row (e.g. `trends,court-stats,no-parking,unemployment,controls`)
so gaps are explicit rather than silently blank.

## Event study / fuzzy RD around AI model launches

`src/analysis/` asks a sharper question than "did AI interest and public-
resource usage both rise over time": does a specific model/service launch
coincide with a shift in a usage metric, right around that date? This
needs monthly resolution, which rules out the parking and court-stats
data (annual only) -- only AI search interest and UI first-payment
processing time are available monthly, so that's what this analysis uses.

```bash
# Needs the monthly Trends fetch (see above) and fetch_unemployment.py
# (which now writes a monthly file too, not just the annual one) already run.
python -m src.analysis.build_panel   # -> data/processed/analysis_panel_state_month.csv

# Event-study: outcome in each month relative to a launch date, vs. the
# month right before it, with state fixed effects and clustered SEs.
python -m src.analysis.event_study --event chatgpt_launch --outcome ai_interest_index
python -m src.analysis.event_study --event deepseek_r1 --outcome ui_pct_within_21_days --controls unemployment_rate

# Fuzzy RD: local-linear jump in ai_interest_index (first stage) and in a
# usage outcome (reduced form) right at the launch date, ratio = LATE.
python -m src.analysis.fuzzy_rd --event chatgpt_launch --outcome ui_pct_within_21_days

# Stacked/pooled event study across all 12 launches at once, instead of
# one noisy regression per launch -- see below for why this is the more
# reliable version.
python -m src.analysis.stacked_event_study --outcome ai_interest_index
python -m src.analysis.stacked_event_study --outcome ui_pct_within_21_days --controls unemployment_rate --window 6
```

- `src/analysis/events.py` — 12 major launches (ChatGPT through Gemini 3),
  dates checked directly against Wikipedia rather than trusted from a
  single web search or training memory; some AI-blog sources returned
  inconsistent/implausible dates for 2025-2026 releases and were
  discarded. See each event's `source` field.
- `src/analysis/event_study.py` — one regression per event: outcome ~
  event-time dummies (relative month, reference = the month before
  launch) + state fixed effects, clustered by state. Deliberately does
  **not** include calendar-month/seasonality fixed effects: for a single
  event, event-time is essentially a stand-in for calendar time itself
  (each event-time value maps to one, or at most two, actual months), so
  a full seasonality control isn't separately identified here — see the
  module docstring. This is descriptive, not causal: it shows the outcome
  moved around the launch, not that the launch caused it.
- `src/analysis/fuzzy_rd.py` — local-linear (triangular-kernel) regression
  discontinuity in months-since-launch, first stage = jump in AI search
  interest, reduced form = jump in the usage outcome, fuzzy-RD estimate =
  their ratio (the standard Wald/IV formula). The reported LATE standard
  error is a delta-method approximation that ignores covariance between
  the two jump estimates — read it as directional, not exact.
- `src/analysis/stacked_event_study.py` — the more reliable version: pools
  all 12 launches into one regression instead of running event_study.py
  once per launch. This has two real advantages, not just "more data":
  (1) each event-time bin now averages over many launches x many states
  instead of one launch x many states, and (2) because different launches
  fall in different calendar months, calendar-month fixed effects *are*
  separately identified here even though they aren't in the single-event
  version — pooling breaks the collinearity that forced dropping them
  above. The catch: this project's 12 events are packed close together
  (as little as 1 month apart in a few places), so a wide fixed window
  would let one launch's post-period bleed into the next launch's
  pre-period baseline. By default each event's window is trimmed to stop
  at its nearest neighbor's own month (`--no-trim` disables this); this
  prevents double-counting a calendar month as both "after A" and "before
  B", but doesn't guarantee full independence from a neighboring launch's
  lingering effect.
- All three are validated in `tests/test_analysis.py` against synthetic
  panels with a known, engineered jump, not just run against real data
  and eyeballed — including a check that pooling multiple events (landing
  in different calendar months) does let seasonality be identified where
  a single event provably can't, and a check on the window-trimming math
  itself using this project's actual event gaps.
- The actual estimates need the monthly Trends fetch to have reached each
  event's date — for events from late 2022 onward this means waiting for
  most of the ~1600-request monthly fetch to complete.

## Tests

```bash
python -m pytest tests/
```

Tests run against small fixture CSVs in `tests/fixtures/` and don't touch
the network or `data/raw/`.
