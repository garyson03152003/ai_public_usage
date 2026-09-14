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

Usage:
    python -m src.analysis.stacked_event_study --outcome ai_interest_index
    python -m src.analysis.stacked_event_study --outcome ui_pct_within_21_days --controls unemployment_rate --window 6
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


def run_stacked_event_study(
    panel: pd.DataFrame,
    events: list[Event],
    outcome_col: str,
    max_window: int = 12,
    control_cols: list[str] | None = None,
    trim_to_neighbors: bool = True,
    reference_period: int = -1,
) -> pd.DataFrame:
    stacked = build_stacked_panel(panel, events, max_window, trim_to_neighbors)
    stacked = stacked.dropna(subset=[outcome_col, "state"])
    if control_cols:
        stacked = stacked.dropna(subset=control_cols)

    if stacked["event_time"].nunique() < 2:
        raise ValueError(f"Not enough distinct event_time periods across the stacked events for {outcome_col} -- is the panel populated?")

    stacked["event_time_cat"] = stacked["event_time"].astype(int).astype(str)
    reference_str = str(reference_period)
    if reference_str not in set(stacked["event_time_cat"]):
        reference_str = str(sorted(stacked["event_time"].unique())[0])

    formula = f"{outcome_col} ~ C(event_time_cat, Treatment(reference='{reference_str}')) + C(state) + C(event_key) + C(month)"
    if control_cols:
        formula += " + " + " + ".join(control_cols)

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
    parser.add_argument("--panel", type=Path, default=PANEL_PATH)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel)
    events = [EVENTS_BY_KEY[k] for k in args.events] if args.events else list(EVENTS)
    result = run_stacked_event_study(
        panel, events, args.outcome, max_window=args.window, control_cols=args.controls, trim_to_neighbors=not args.no_trim
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / f"stacked__{args.outcome}.csv"
    result.to_csv(csv_path, index=False)
    print(f"n_events={result.attrs.get('n_events')} n_obs={result.attrs.get('n_obs')} r_squared={result.attrs.get('r_squared'):.4f}")
    print(result.to_string(index=False))
    print(f"Wrote -> {csv_path}")

    plot_stacked_event_study(result, events, args.outcome, OUTPUT_DIR / f"stacked__{args.outcome}.png")


if __name__ == "__main__":
    main()
