# ai_public_usage

Data pipeline that compiles two things side by side, by US state, for
2020 through the current year:

1. **AI usage, proxied by Google search interest** — Google Trends'
   "interest by region", per calendar year, for a broad list of
   AI-related terms (Anthropic, Claude and specific Claude models,
   ChatGPT/OpenAI, Gemini, Copilot, Perplexity, DeepSeek, Llama, Grok,
   Mistral, ...).
2. **Public-resource usage** — state-level civil/small-claims court
   caseloads and processing times (annual nationwide where available, plus
   genuine MONTHLY, statewide small-claims filings/dispositions for Texas —
   see below), NYC parking-ticket hearing/appeal volume as an illustrative
   city case study, and state unemployment-insurance first-payment
   processing time, alongside a control variable (state unemployment rate)
   so the UI processing-time numbers aren't compared without accounting
   for claim-volume pressure.

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
    fetch_tx_card.py         # Texas Court Activity Reporting Database: genuine MONTHLY small-claims data
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
    stacked_fuzzy_rd.py            # pooled fuzzy RD across all events at once (same idea as stacked_event_study.py)
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
python -m src.gov_usage.fetch_tx_card --start 2020-01 --end 2026-08   # Texas MONTHLY small-claims data, see below
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
- **State court caseloads** — no working automated *nationwide* source as
  of 2026 (see above); use the NCSC manual-export path for other states.
  Confirmed live (not assumed) that NCSC's Tableau-hosted dashboards
  support a simple `<view>.csv` export for KPI-style views, including
  confirming "Small Claims" is a real case-type category in their data —
  but the specific by-state dashboards need Tableau's interactive
  "Download Crosstab" feature, which runs over a WebSocket session this
  sandbox's proxy doesn't support; see `fetch_court_stats.py`'s docstring
  for the full trail. Once normalized, `combine.py` keeps every (state,
  year) row rather than collapsing to a single snapshot.

  **Texas is the exception, and the only source in this project with
  genuine MONTHLY small-claims resolution.** The Texas Office of Court
  Administration runs its own query tool, the Court Activity Reporting
  Database (`card.txcourts.gov`), with an explicit from/to month+year
  picker for its "Justice Court Activity Detail" report — confirmed live
  by driving the tool's classic ASP.NET WebForms postback sequence with
  plain `requests` (no browser needed) and checking that the returned
  figures actually change per month requested (e.g. January 2020 alone
  returns different, internally consistent numbers from the full 2020
  calendar year). `fetch_tx_card.py` automates this end to end: one
  session setup, then one request per month, statewide, parsing the
  returned Crystal-Reports `.xls` export's "CIVIL CASES" section for
  filings ("New Cases Filed") and dispositions ("Total Cases Disposed")
  across Debt Claim / Landlord-Tenant / Small Claims. Coverage: Texas
  only, 9/2013-present (the "HB79" reporting period), and each month's
  export reports its own reporting-completeness rate (typically >90%,
  self-reported by county courts to OCA) which isn't captured per-row
  here — see the module docstring for the full postback trail, including
  the wrong-URL 500 error hit and fixed along the way. `build_panel.py`
  pulls this into the monthly analysis panel as `small_claims_filings`/
  `small_claims_dispositions` (Texas-only, same single-state caveat as
  the NYC parking columns below); `combine.py` rolls it up to annual and
  merges it into the same `small_claims_filings` column the NCSC
  manual-export path would otherwise populate, so either source works.
- **Parking ticket appeals** — there is no national dataset. This repo
  ships one verified source: NYC's "Open Parking and Camera Violations"
  (Socrata dataset `nc67-uf89` on `data.cityofnewyork.us`), which has a
  real `violation_status` field with hearing/appeal outcomes (HEARING
  HELD-GUILTY/NOT GUILTY, HEARING ADJOURNMENT, APPEAL AFFIRMED/REVERSED/
  ABANDONED/MODIFIED, etc.) — confirmed against the live API. The table
  is huge (hundreds of millions of rows) and `issue_date` is stored as
  plain text, so `fetch_socrata.py` aggregates counts per
  year/outcome server-side rather than downloading raw rows; expect each
  year (or, with `--granularity month`, each month -- Socrata still scans
  the whole table for a plain-text LIKE filter regardless of how narrow
  the date range is, so this isn't ~12x faster than the yearly version)
  to take a couple of minutes unauthenticated (pass a free Socrata app
  token via `--app-token` to speed this up).

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
needs monthly resolution, which rules out most court-stats data (annual
only) -- AI search interest, UI first-payment processing time, NYC
parking-ticket hearing/appeal volume (`fetch_socrata.py --granularity
month`), and now Texas small-claims filings/dispositions
(`fetch_tx_card.py`) are all available monthly, so those are the outcomes
this analysis can use (parking is NYC-only and small-claims is Texas-only,
same single-state caveat as the annual versions).

```bash
# Needs the monthly Trends fetch (see above), fetch_unemployment.py (which
# now writes a monthly file too, not just the annual one), and optionally
# fetch_socrata.py --granularity month for a parking-ticket outcome, already run.
python -m src.analysis.build_panel   # -> data/processed/analysis_panel_state_month.csv

# Event-study: outcome in each month relative to a launch date, vs. the
# month right before it, with state fixed effects and clustered SEs.
python -m src.analysis.event_study --event chatgpt_launch --outcome ai_interest_index
python -m src.analysis.event_study --event deepseek_r1 --outcome ui_pct_within_21_days --controls unemployment_rate

# Fuzzy RD: local-linear jump in ai_interest_index (first stage) and in a
# usage outcome (reduced form) right at the launch date, ratio = LATE.
python -m src.analysis.fuzzy_rd --event chatgpt_launch --outcome ui_pct_within_21_days

# Pooled fuzzy RD across all 12 launches at once -- same idea as
# stacked_event_study.py, applied to the local-linear RD design instead:
# individual per-event LATEs are too noisy (see below), so pool
# state-months across events with state + event fixed effects.
python -m src.analysis.stacked_fuzzy_rd --outcome parking_appeal_records --bandwidth 6

# The parking outcome only has data for New York, and the small-claims
# outcomes only for Texas, so after dropping other states' NaN rows the
# "state fixed effects" term in event_study.py/stacked_event_study.py has
# just one category and contributes nothing beyond the intercept. Worse
# for a SINGLE event: with one state, one observation per relative-month,
# and one dummy per relative-month, the model is fully saturated
# (R-squared = 1.0, SEs are NaN) -- it fits perfectly and says nothing.
# Only the pooled/stacked version below is actually informative for these
# outcomes, since pooling 12 events supplies multiple observations per
# relative-month bin.
python -m src.analysis.event_study --event chatgpt_launch --outcome parking_appeal_records  # degenerate, see above
python -m src.analysis.stacked_event_study --outcome small_claims_filings --window 6
python -m src.analysis.stacked_event_study --outcome small_claims_dispositions --window 6

# --no-trim: use the full +/-6 window for every event even where a
# neighboring launch falls inside it (e.g. gpt4o and claude35_sonnet are
# only 1 month apart), accepting some cross-event contamination in
# exchange for every event-time bin having all 12 events' support instead
# of the 1-4 events it gets under the default neighbor-trimmed windows
# above (see the trimming table in the stacked_event_study.py notes below).
python -m src.analysis.stacked_event_study --outcome parking_appeal_records --window 6 --no-trim

# --weight-col: run WLS instead of OLS, weighting each state-month by
# ai_interest_index -- months with more actual AI search attention count
# more toward the estimated impact, instead of every month counting
# equally regardless of whether anyone was paying attention to AI at all.
python -m src.analysis.stacked_event_study --outcome parking_appeal_records --window 6 --no-trim --weight-col ai_interest_index

# --event-impact-col: a different kind of weighting -- instead of
# reweighting individual state-months, reweight whole EVENTS by how much
# of a splash each launch made (a plain pre/post mean difference in
# ai_interest_index around that launch), so a launch that clearly moved
# search interest a lot counts more toward the pooled average than one
# that barely moved it, instead of all 12 launches counting equally
# regardless of how big a deal they actually were.
python -m src.analysis.stacked_event_study --outcome parking_appeal_records --window 6 --no-trim --event-impact-col ai_interest_index

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
- `src/analysis/stacked_fuzzy_rd.py` — the same pooling idea as
  `stacked_event_study.py`, applied to the local-linear RD design instead
  of the event-time-dummy design: pools state-months across all N events
  into one first-stage and one reduced-form local-linear regression, with
  state and event fixed effects, rather than running `fuzzy_rd.py` once
  per launch. Reuses `stacked_event_study.py`'s `build_stacked_panel()`
  for the same neighbor-trimming logic (`--no-trim` disables it here
  too). Deliberately does **not** add calendar-month fixed effects like
  the event-study version does — a local-linear RD's job is to net out a
  local *trend* right at the cutoff, not act as a full seasonally-adjusted
  model, and stacking another FE dimension on top of state + event FE
  within an already-narrow local window risks the same rank-deficiency
  issue for little benefit. Validated in `tests/test_analysis.py`: on a
  synthetic panel with a known jump ratio, the pooled estimate matches
  the true ratio and has a meaningfully *tighter* standard error than a
  single event's own `fuzzy_rd.py` estimate on the same data — pooling
  does what it's supposed to. On real data it helps, but can't fix a
  structural problem: parking's pooled first-stage jump (the discontinuity
  in `ai_interest_index` right at the average cutoff) is itself small
  (~0.4, comparable in size to its own SE), so the Wald ratio's
  denominator is close to zero and the LATE stays wildly noisy (SE far
  exceeding the point estimate) even after pooling substantially tightens
  each jump's own SE relative to an unlucky single-event estimate.
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
  lingering effect. This calendar-month control applies at any window
  width, including the narrow +/-6 months used for `parking_appeal_records`
  above: it's the pooling across 12 launches landing in 12 different
  calendar months that identifies seasonality, not how wide each launch's
  own window is, so there's no need to widen a single outcome's window
  just to get a seasonal control into the regression.
- `stacked_event_study.py --weight-col <column>` switches the regression
  from OLS to WLS, weighted by that column (e.g. `ai_interest_index`):
  state-months with more of whatever the weight column measures count
  more toward the estimated impact, rather than every state-month
  counting equally. Rows with a non-positive weight are dropped (WLS
  requires positive weights, and a month with zero recorded search
  interest carries no information under this weighting anyway). This is
  a different design from `fuzzy_rd.py`'s dose-response ratio: WLS
  weighting still reports a level effect per event-time bin, just
  reweighted toward higher-attention state-months, whereas the fuzzy-RD
  estimate is the ratio of two jumps (impact per unit of search-interest
  increase). Don't read too much precision into an exact weighted
  coefficient value from a small, single-state sample like parking's --
  `tests/test_analysis.py` confirms the weighting shifts the estimate in
  the right *direction* on synthetic data with a known, engineered
  weight-outcome relationship, but the project's own known rank-deficiency
  quirk (below) makes exact recovery on small synthetic panels noisier
  under WLS than under plain OLS.
- `stacked_event_study.py --event-impact-col <column>` weights whole
  EVENTS instead of individual state-months: every row from a given
  launch gets that launch's own impact score, so a launch that clearly
  moved search interest (ChatGPT) counts more toward the pooled average
  than one that barely moved it (e.g. GPT-4o, whose interest was already
  elevated and barely rose further), rather than treating all 12 launches
  as equal contributions regardless of how big a deal they actually were.
  `compute_event_impact_weights()` computes this as a plain pre/post mean
  difference in the given column around each launch -- **not**
  `fuzzy_rd.py`'s local-linear RD jump, despite the superficial
  similarity. That was tried first and gives the wrong answer here:
  confirmed live, ChatGPT's own local-linear jump comes out as ~0.2, the
  *smallest* of all 12 events, because RD measures the sharpness of the
  discontinuity exactly at the cutoff month, and ChatGPT's rise was
  gradual/viral over the following months rather than an overnight jump
  -- its plain pre/post mean difference (+5.6) tells the truer story and
  lands mid-to-high among the 12 launches, as expected. This is a useful
  general lesson about the two techniques in this codebase: RD-style
  jump estimation answers "how sharp was the break right at the cutoff,"
  which is not the same question as "how big a splash did this event
  make overall," and the wrong one will quietly give nonsensical weights.
- All three are validated in `tests/test_analysis.py` against synthetic
  panels with a known, engineered jump, not just run against real data
  and eyeballed — including a check that pooling multiple events (landing
  in different calendar months) does let seasonality be identified where
  a single event provably can't, a check on the window-trimming math
  itself using this project's actual event gaps, and checks that both
  `--weight-col` and `--event-impact-col` shift the estimate toward
  whichever states/months/events carry more weight.
- The actual estimates need the monthly Trends fetch to have reached each
  event's date — for events from late 2022 onward this means waiting for
  most of the ~1600-request monthly fetch to complete.
- Cluster-robust (by-state) standard errors need at least 2 clusters; the
  parking outcome only has one (New York) and the small-claims outcomes
  only have one (Texas), which divides by zero in statsmodels'
  small-cluster correction. All three scripts detect a single-cluster
  outcome and fall back to HC1 heteroskedasticity-robust SEs instead,
  printing a note when they do. A worse case for both: `event_study.py`/
  `fuzzy_rd.py` on a *single* event with a *single* state have only one
  observation per relative-month, so a full set of event-time dummies
  fits it exactly (R-squared = 1.0, SEs are NaN) — the per-event
  regressions are mathematically uninformative, not just noisy. Only
  `stacked_event_study.py`'s pooled version, which supplies multiple
  observations per relative-month by combining all 12 events, produces a
  meaningful result for these outcomes.

### What the results actually show (last run against real data)

- **AI search interest**: jumps clearly and significantly after launch in
  the pooled analysis (pre-period near zero to negative, post-period
  +1.8 to +6.7, all p<0.001). Expected, and a good sanity check that the
  pipeline works.
- **UI first-payment processing time**: no significant or coherent
  post-launch pattern in the pooled analysis (most p>0.19, sign flips
  between periods) — a credible null, not a data gap. Individual
  single-event checks (ChatGPT, GPT-4) show significant coefficients
  *before* the launch date even happens (a pre-trend), which is exactly
  the kind of noise the pooled design exists to average out.
- **NYC parking-ticket appeals**: also a null in the pooled analysis — no
  coefficient post-launch reaches significance (all p>0.15), no
  consistent direction (using `--no-trim`, which accepts some cross-event
  contamination in exchange for every event-time bin getting all 12
  events' support — see above; the neighbor-trimmed version has fewer
  observations per far bin but shows the same null). This already
  controls for seasonality via the pooled model's calendar-month fixed
  effect (see above — identified by pooling across the 12 launches'
  differing calendar months, not by widening this outcome's own window).
  With `--no-trim`, event_time=-6 is the one significant bin (p=0.023,
  coef=-1026), but it sits alongside similarly-sized, insignificant
  negative coefficients on both sides of the launch date rather than a
  clean pre/post break — read as a smooth, unrelated dip-and-recovery
  partly produced by neighboring launches' own windows bleeding into each
  other, not evidence of a launch effect. Reweighting this same regression
  by `ai_interest_index` (`--weight-col ai_interest_index`, so months with
  more actual AI search attention count more) doesn't change the
  conclusion either: every post-launch coefficient is still insignificant
  (p>0.16), and the shape is the same smooth, symmetric dip on both sides
  of the launch date. Weighting by each *event's* own impact instead
  (`--event-impact-col ai_interest_index`, so a launch that visibly moved
  search interest more — like ChatGPT's own +5.6 pre/post mean shift —
  counts more than one that barely moved it) gives the same null again:
  every post-launch coefficient stays insignificant (p>0.16), and the one
  borderline pre-period bin from the unweighted run (event_time=-6) drops
  to p=0.06, no longer even nominally significant. The individual-event
  regressions are degenerate (see above) rather than merely noisy, and
  the individual fuzzy-RD estimates have standard errors several times
  larger than their point estimates — uninformative, not evidence of an
  effect either way. Pooling the fuzzy-RD design too
  (`stacked_fuzzy_rd.py`) doesn't rescue it: the pooled first-stage jump
  (the discontinuity in `ai_interest_index` right at the average cutoff)
  is itself only ~0.4 — comparable to its own standard error — so the
  Wald ratio's denominator is close to zero and the resulting LATE
  (-570, SE ~1053) stays wildly noisy even though pooling did tighten
  each jump's own SE substantially versus an unlucky single event (e.g.
  ChatGPT's own LATE SE alone is ~11,700 — pooling brings the typical
  case down to ~1053, real progress, just not enough to rescue a ratio
  whose denominator is this close to zero).
- **Texas small-claims filings/dispositions**: essentially a null in the
  pooled analysis too. `small_claims_filings` has one significant
  coefficient right at launch month (event_time=0: -463, p=0.021) but
  every other post-launch bin (months 1-5) is insignificant with mixed
  signs, and the pre-period includes an even larger significant swing at
  event_time=-6 (+1345, p<0.001) driven by ordinary month-to-month filing
  volume differences rather than anything launch-related — with 12
  event-time bins tested, one being "significant" in isolation isn't
  strong evidence by itself. `small_claims_dispositions` shows the same
  pattern (only event_time=+4 significant, p=0.022, surrounded by
  insignificant neighbors). Individual-event fuzzy-RD checks (single
  state, single event) are far too noisy to read on their own -- e.g.
  chatgpt_launch's small_claims_filings LATE has a standard error ~6x its
  point estimate.
- Bottom line: strong evidence AI launches move search interest; no
  credible evidence, in any of the three government-usage outcomes
  tested (UI processing time, NYC parking appeals, Texas small-claims
  filings/dispositions), that they shift how fast or how much these
  public services get used or processed.

Caveat on this run specifically: BLS's anonymous LAUS API quota (25
queries/day, shared per source IP) was already exhausted when re-running
this analysis, so `unemployment_rate` (the claim-volume control for the UI
outcome) wasn't available and the numbers above for `small_claims_*`
were run without a `--controls` argument. Re-run `fetch_bls_controls.py`
(optionally with `--api-key`) to restore it.

## Tests

```bash
python -m pytest tests/
```

Tests run against small fixture CSVs in `tests/fixtures/` and don't touch
the network or `data/raw/`.
