"""Pooled ("stacked") event study across multiple AI model/service
launches, rather than one regression per launch.

Why stack instead of running event_study.py once per event: with only one
occurrence of a given launch, calendar-month and event-time are the same
axis (see event_study.py's docstring), so seasonality can't be separately
controlled, and each single-event estimate is noisy (one state-month
observation per state per relative month). Pooling many launches together
fixes both: the same event_time value falls in different actual calendar
months for different launches (event_time=0 is November for the ChatGPT
launch but March for GPT-4), which breaks that collinearity and lets a
calendar-month fixed effect be estimated; and each event-time bin now
averages over many launches x many states instead of one launch x many
states.

Model:
    outcome_{i,e,t} = sum_{k != -1} beta_k * 1(event_time = k)
                      + state_i FE + event_e FE + calendar_month FE
                      + [controls] + error

beta_k is the *average*, across all pooled events, change in outcome in
relative month k vs. the month before each event's own launch. Standard
errors are clustered by state.

You may see a "rank-deficient design matrix" warning from statsmodels
here. Checked directly (via the design matrix's rank, not assumed): with
few events and equal, non-trimmed windows, event_time + event_key + month
fixed effects can have exactly one redundant combination -- an ambiguity
in how the overall constant splits between the event-level and
calendar-month baselines, not in the event_time coefficients themselves,
which stay correctly identified (statsmodels' pinv-based fit still
recovers them; tests/test_analysis.py confirms this against a synthetic
panel with a known jump). With the full 12-event production list and its
neighbor-trimmed, unequal window widths this is less likely to bind at
all, since the event-time-to-calendar-month correspondence is far less
rigid than in a small, uniform-window synthetic example.

Overlapping windows: this project's 12 events are packed close together
(1-6 months apart in several places -- GPT-4o to Claude 3.5 Sonnet is
just 1 month), so a naive wide window would let one event's post-period
bleed into a neighboring event's pre-period baseline. By default each
event's window is trimmed to stop at the midpoint-ish boundary with its
nearest neighbor (specifically: it never crosses into the calendar month
of an adjacent event), which avoids double-counting the same calendar
month as both "after A" and "before B" -- it does NOT guarantee the
estimates are free of a nearby launch's lingering effect, since real
adoption effects can outlast a few months. Read tight windows around
closely-spaced launches with that caveat; pass --no-trim to see the
(more contaminated) fixed-window version instead.

Optional weighting (--weight-col): by default every state-month in the
stacked sample counts equally toward the estimated impact. Passing e.g.
--weight-col ai_interest_index switches to weighted least squares, so a
state-month with more actual AI search attention counts more, and one
with (near-)zero search interest counts for little or nothing. Rows with
a non-positive weight are dropped rather than passed to WLS (which
requires positive weights) -- a month with literally zero recorded search
interest carries no information under this weighting scheme anyway, so
dropping it is equivalent to giving it zero weight. This changes what the
number means (a search-interest-weighted average effect, not a flat
average over calendar time) and is a different design from
fuzzy_rd.py's dose-response ratio -- WLS weighting still estimates a
level effect per event-time bin, it just reweights which state-months
that average leans on, whereas fuzzy_rd.py estimates the ratio of two
jumps (impact per unit of search-interest increase).

Optional per-EVENT weighting (--event-impact-col, via
compute_event_impact_weights()): different from --weight-col above,
which reweights individual state-months. This instead reweights whole
events: every row belonging to a given launch gets that launch's own
impact score (a plain pre/post mean difference in the given column, e.g.
ai_interest_index -- NOT fuzzy_rd.py's local-linear RD jump, which
measures discontinuity sharpness at the cutoff and badly underrates a
launch like ChatGPT whose interest built up gradually rather than
overnight; see compute_event_impact_weights()'s docstring), so a launch
that visibly moved search interest a lot (ChatGPT) counts more toward the
pooled average effect than one that barely moved it (e.g. GPT-4o,
already-elevated interest that barely rose further), rather than all 12
launches counting as equal contributions regardless of how big a splash
they actually made. Combine both flags to weight by both event-level
impact and within-event state-month attention at once.

Usage:
    python -m src.analysis.stacked_event_study --outcome ai_interest_index
    python -m src.analysis.stacked_event_study --outcome ui_pct_within_21_days --controls unemployment_rate --window 6
    python -m src.analysis.stacked_event_study --outcome parking_appeal_records --window 6 --no-trim --event-impact-col ai_interest_index
    python -m src.analysis.stacked_event_study --outcome parking_appeal_records --window 6 --no-trim --weight-col ai_interest_index
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf

from src.analysis.events import EVENTS, EVENTS_BY_KEY, Event, months_since

ROOT = Path(__file__).resolve().parents[2]
PANEL_PATH = ROOT / "data" / "processed" / "analysis_panel_state_month.csv"
OUTPUT_DIR = ROOT / "data" / "processed" / "event_study"

COEF_PATTERN = re.compile(r"\[T\.(-?\d+)\]")


def _month_diff(d1, d2) -> int:
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)


def event_time_bounds(event: Event, all_events: list[Event], max_window: int) -> tuple[int, int]:
    """(lower, upper) event_time bounds for `event`, capped at max_window
    and trimmed so the window never crosses into an adjacent event's own
    calendar month."""
    ordered = sorted(all_events, key=lambda e: e.date)
    idx = ordered.index(event)

    lower = -max_window
    if idx > 0:
        gap = _month_diff(ordered[idx - 1].date, event.date)
        lower = max(lower, -(gap - 1)) if gap > 1 else 0

    upper = max_window
    if idx < len(ordered) - 1:
        gap = _month_diff(event.date, ordered[idx + 1].date)
        upper = min(upper, gap - 1) if gap > 1 else 0

    return lower, upper


def build_stacked_panel(
    panel: pd.DataFrame,
    events: list[Event],
    max_window: int,
    trim_to_neighbors: bool = True,
) -> pd.DataFrame:
    """One copy of `panel` per event, restricted to that event's window,
    tagged with event_key and event_time, then concatenated."""
    frames = []
    for event in events:
        lower, upper = event_time_bounds(event, events, max_window) if trim_to_neighbors else (-max_window, max_window)
        df = panel.copy()
        df["event_time"] = [months_since(y, m, event) for y, m in zip(df["year"], df["month"])]
        df = df[(df["event_time"] >= lower) & (df["event_time"] <= upper)]
        df["event_key"] = event.key
        frames.append(df)
    if not frames:
        raise ValueError("No events given to stack")
    return pd.concat(frames, ignore_index=True)


def compute_event_impact_weights(
    panel: pd.DataFrame,
    events: list[Event],
    impact_col: str = "ai_interest_index",
    bandwidth: int = 6,
) -> dict[str, float]:
    """One scalar per event: how much impact_col shifted around that
    launch, as a plain pre-window-mean vs. post-window-mean difference
    (abs value). Meant to be passed as `event_weights` to
    run_stacked_event_study() so a blockbuster launch (a big, sustained
    rise in search interest, e.g. ChatGPT) counts more toward the pooled
    average effect than a smaller one (e.g. GPT-4o, whose search interest
    was already elevated and barely moved further), instead of every
    launch counting as one equal contribution regardless of how much
    attention it actually got.

    Deliberately NOT fuzzy_rd.py's local-linear RD jump, despite the
    superficial similarity -- tried that first and it gives the wrong
    answer here: RD estimates the sharpness of the discontinuity exactly
    at the cutoff month, which comes out tiny for a launch whose interest
    built up gradually/virally over the following months rather than
    jumping overnight (confirmed live: ChatGPT's own local-linear jump is
    ~0.2, the smallest of all 12 events, despite its plain pre/post mean
    difference of +5.6 being mid-to-high among them) -- not what "how big
    a splash did this launch make" means colloquially. A simple pre/post
    mean difference doesn't have that blind spot.

    An event whose window has no pre- or post-period data at all gets
    NaN, which run_stacked_event_study() will reject rather than silently
    drop -- pass a subset of `events` that all have coverage instead.
    """
    weights: dict[str, float] = {}
    for event in events:
        df = panel.copy()
        df["event_time"] = [months_since(y, m, event) for y, m in zip(df["year"], df["month"])]
        pre = df[df["event_time"].between(-bandwidth, -1)][impact_col].mean()
        post = df[df["event_time"].between(0, bandwidth)][impact_col].mean()
        weights[event.key] = abs(post - pre)
    return weights


def run_stacked_event_study(
    panel: pd.DataFrame,
    events: list[Event],
    outcome_col: str,
    max_window: int = 12,
    control_cols: list[str] | None = None,
    trim_to_neighbors: bool = True,
    reference_period: int = -1,
    weight_col: str | None = None,
    event_weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    stacked = build_stacked_panel(panel, events, max_window, trim_to_neighbors)
    stacked = stacked.dropna(subset=[outcome_col, "state"])
    if control_cols:
        stacked = stacked.dropna(subset=control_cols)

    effective_weight_col = weight_col
    if event_weights:
        # Per-event weight (same value for every row belonging to that
        # event), rather than weight_col's per-row weight -- see
        # compute_event_impact_weights()'s docstring. Combine with
        # weight_col by multiplying, if both are given.
        missing = sorted(e.key for e in events if e.key not in event_weights)
        if missing:
            raise ValueError(f"event_weights is missing entries for: {missing}")
        stacked["_event_impact_weight"] = stacked["event_key"].map(event_weights)
        if weight_col:
            stacked["_combined_weight"] = stacked[weight_col] * stacked["_event_impact_weight"]
            effective_weight_col = "_combined_weight"
        else:
            effective_weight_col = "_event_impact_weight"

    if effective_weight_col:
        stacked = stacked.dropna(subset=[effective_weight_col])
        zero_or_negative = (stacked[effective_weight_col] <= 0).sum()
        if zero_or_negative:
            print(
                f"Note: dropping {zero_or_negative} row(s) with a non-positive effective weight -- WLS weights must be "
                "positive, and (for a per-row weight_col) a month with literally zero search interest carries no "
                "information under this weighting anyway."
            )
            stacked = stacked[stacked[effective_weight_col] > 0]

    if stacked["event_time"].nunique() < 2:
        raise ValueError(f"Not enough distinct event_time periods across the stacked events for {outcome_col} -- is the panel populated?")

    stacked["event_time_cat"] = stacked["event_time"].astype(int).astype(str)
    reference_str = str(reference_period)
    if reference_str not in set(stacked["event_time_cat"]):
        reference_str = str(sorted(stacked["event_time"].unique())[0])

    formula = f"{outcome_col} ~ C(event_time_cat, Treatment(reference='{reference_str}')) + C(state) + C(event_key) + C(month)"
    if control_cols:
        formula += " + " + " + ".join(control_cols)

    if effective_weight_col:
        # WLS weighted by e.g. ai_interest_index (weight_col, per-row) or
        # each event's own attention-jump size (event_weights, per-event):
        # months/states/events with more of whatever is being weighted by
        # count more toward the estimated impact, instead of every
        # observation counting equally regardless of actual attention.
        ols = smf.wls(formula, data=stacked, weights=stacked[effective_weight_col])
    else:
        ols = smf.ols(formula, data=stacked)
    n_clusters = stacked["state"].nunique()
    if n_clusters < 2:
        # Cluster-robust SEs need >=2 clusters (the standard small-cluster
        # correction divides by n_clusters - 1); with a single-state
        # outcome like the NYC parking data there's nothing to cluster
        # across, so fall back to heteroskedasticity-robust SEs instead
        # of erroring or silently reporting bogus clustered ones.
        print(f"Note: outcome '{outcome_col}' has only {n_clusters} state(s) -- using HC1 robust SEs instead of state-clustered SEs.")
        model = ols.fit(cov_type="HC1")
    else:
        model = ols.fit(cov_type="cluster", cov_kwds={"groups": stacked["state"]})

    rows = []
    conf_int = model.conf_int(alpha=0.05)
    for term in model.params.index:
        match = COEF_PATTERN.search(term)
        if not match or "event_time_cat" not in term:
            continue
        event_time = int(match.group(1))
        rows.append(
            {
                "event_time": event_time,
                "coef": model.params[term],
                "std_err": model.bse[term],
                "ci_low": conf_int.loc[term, 0],
                "ci_high": conf_int.loc[term, 1],
                "p_value": model.pvalues[term],
            }
        )
    result = pd.DataFrame(rows).sort_values("event_time").reset_index(drop=True)

    ref_row = pd.DataFrame([{"event_time": int(reference_str), "coef": 0.0, "std_err": 0.0, "ci_low": 0.0, "ci_high": 0.0, "p_value": float("nan")}])
    result = pd.concat([result, ref_row], ignore_index=True).sort_values("event_time").reset_index(drop=True)

    result.attrs["n_obs"] = int(model.nobs)
    result.attrs["r_squared"] = float(model.rsquared)
    result.attrs["n_events"] = len(events)
    return result


def plot_stacked_event_study(result: pd.DataFrame, events: list[Event], outcome_col: str, output_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.axvline(-0.5, color="red", linestyle="--", linewidth=1, label=f"launch date (pooled, n={len(events)} events)")
    ax.errorbar(
        result["event_time"],
        result["coef"],
        yerr=[result["coef"] - result["ci_low"], result["ci_high"] - result["coef"]],
        fmt="o-",
        capsize=3,
        color="tab:blue",
    )
    ax.set_xlabel("Months relative to launch (pooled across events)")
    ax.set_ylabel(f"Effect on {outcome_col} (vs. month before launch)")
    ax.set_title(f"Stacked event study across {len(events)} AI launches")
    ax.legend()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events", nargs="*", default=None, choices=sorted(EVENTS_BY_KEY.keys()), help="Event keys to pool (default: all)")
    parser.add_argument("--outcome", required=True, help="Outcome column in the analysis panel, e.g. ai_interest_index or ui_pct_within_21_days")
    parser.add_argument("--window", type=int, default=12, help="Max months before/after each event (default 12; trimmed near neighbors)")
    parser.add_argument("--controls", nargs="*", default=None, help="Extra control columns, e.g. unemployment_rate")
    parser.add_argument("--no-trim", action="store_true", help="Use the fixed window for every event instead of trimming near neighbors")
    parser.add_argument(
        "--weight-col",
        default=None,
        help="Run WLS instead of OLS, weighted by this column (e.g. ai_interest_index) -- state-months with more "
        "of whatever this column measures count more toward the estimated impact.",
    )
    parser.add_argument(
        "--event-impact-col",
        default=None,
        help="Weight each EVENT (not each state-month) by the size of its own local-linear jump in this column "
        "(e.g. ai_interest_index), via compute_event_impact_weights() -- a launch with a bigger search-interest "
        "jump (e.g. ChatGPT) counts more toward the pooled average than a smaller one (e.g. Gemini 1.0), instead "
        "of every launch counting as one equal contribution. Combines with --weight-col if both are given.",
    )
    parser.add_argument("--panel", type=Path, default=PANEL_PATH)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel)
    events = [EVENTS_BY_KEY[k] for k in args.events] if args.events else list(EVENTS)

    event_weights = None
    if args.event_impact_col:
        event_weights = compute_event_impact_weights(panel, events, impact_col=args.event_impact_col, bandwidth=args.window)
        print("Per-event impact weights:")
        for event in events:
            print(f"  {event.key:20s} {event_weights[event.key]:.2f}")

    result = run_stacked_event_study(
        panel,
        events,
        args.outcome,
        max_window=args.window,
        control_cols=args.controls,
        trim_to_neighbors=not args.no_trim,
        weight_col=args.weight_col,
        event_weights=event_weights,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix_parts = []
    if args.weight_col:
        suffix_parts.append(f"weighted_{args.weight_col}")
    if args.event_impact_col:
        suffix_parts.append(f"eventweighted_{args.event_impact_col}")
    suffix = ("__" + "_".join(suffix_parts)) if suffix_parts else ""
    csv_path = OUTPUT_DIR / f"stacked__{args.outcome}{suffix}.csv"
    result.to_csv(csv_path, index=False)
    print(f"n_events={result.attrs.get('n_events')} n_obs={result.attrs.get('n_obs')} r_squared={result.attrs.get('r_squared'):.4f}")
    print(result.to_string(index=False))
    print(f"Wrote -> {csv_path}")

    plot_stacked_event_study(result, events, args.outcome, OUTPUT_DIR / f"stacked__{args.outcome}{suffix}.png")


if __name__ == "__main__":
    main()
