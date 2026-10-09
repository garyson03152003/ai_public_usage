"""Event-study regressions: for a given outcome and a chosen AI-model
launch event, estimate how the outcome moves in each month relative to
the launch, controlling for state and calendar-month fixed effects (and,
optionally, other covariates like the unemployment-rate control).

Model (one event at a time):
    outcome_it = sum_{k != -1} beta_k * 1(event_time_it = k)
                 + state_i fixed effects + [controls] + error_it

event_time = -1 (the month right before launch) is the omitted/reference
category, so each beta_k is the change in outcome relative to that
baseline month. Standard errors are clustered by state to allow for
within-state serial correlation.

Deliberately NOT included: calendar-month (seasonality) fixed effects.
For a single event, event_time is an affine function of calendar time
(each event_time value corresponds to one specific year-month, or two if
the window spans >12 months) -- so a full set of calendar-month dummies
is collinear with the event_time dummies and isn't separately identified
here. Netting out seasonality properly needs a *stacked* design across
multiple events (comparing the same calendar month at different
event-relative times across different actual launch dates), which this
module doesn't implement. Treat any seasonal pattern near a given launch
date as a possible confound for that specific event's estimates.

This is descriptive/associational, not causal: it does not claim a launch
*caused* a change in outcome, only that outcome moved coincident with it,
after netting out state-level levels and seasonality. See fuzzy_rd.py for
the sharper local-comparison version.

Usage:
    python -m src.analysis.event_study --event chatgpt_launch --outcome ai_interest_index
    python -m src.analysis.event_study --event deepseek_r1 --outcome ui_pct_within_21_days --controls unemployment_rate
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
import statsmodels.formula.api as smf

from src.analysis.events import EVENTS_BY_KEY, Event, months_since

ROOT = Path(__file__).resolve().parents[2]
PANEL_PATH = ROOT / "data" / "processed" / "analysis_panel_state_month.csv"
OUTPUT_DIR = ROOT / "data" / "processed" / "event_study"

COEF_PATTERN = re.compile(r"\[T\.(-?\d+)\]")


def add_event_time(panel: pd.DataFrame, event: Event) -> pd.DataFrame:
    df = panel.copy()
    df["event_time"] = [months_since(y, m, event) for y, m in zip(df["year"], df["month"])]
    return df


def run_event_study(
    panel: pd.DataFrame,
    event: Event,
    outcome_col: str,
    window: int = 12,
    control_cols: list[str] | None = None,
    reference_period: int = -1,
) -> pd.DataFrame:
    """Returns one row per event_time in [-window, window] (excluding
    reference_period) with the estimated coefficient, clustered-by-state
    standard error, and a 95% confidence interval."""
    df = add_event_time(panel, event)
    df = df[(df["event_time"] >= -window) & (df["event_time"] <= window)]
    df = df.dropna(subset=[outcome_col, "state"])
    if control_cols:
        df = df.dropna(subset=control_cols)

    if df["event_time"].nunique() < 2:
        raise ValueError(f"Not enough distinct event_time periods in range for {event.key}/{outcome_col} -- is the panel populated for this window?")

    df["event_time_cat"] = df["event_time"].astype(int).astype(str)
    reference_str = str(reference_period)
    if reference_str not in set(df["event_time_cat"]):
        # Fall back to the earliest available period if the exact reference is missing
        reference_str = str(sorted(df["event_time"].unique())[0])

    formula = f"{outcome_col} ~ C(event_time_cat, Treatment(reference='{reference_str}')) + C(state)"
    if control_cols:
        formula += " + " + " + ".join(control_cols)

    ols = smf.ols(formula, data=df)
    n_clusters = df["state"].nunique()
    if n_clusters < 2:
        # Cluster-robust SEs need >=2 clusters (the small-cluster
        # correction divides by n_clusters - 1); a single-state outcome
        # like the NYC parking data has nothing to cluster across, so
        # fall back to heteroskedasticity-robust SEs.
        print(f"Note: outcome '{outcome_col}' has only {n_clusters} state(s) -- using HC1 robust SEs instead of state-clustered SEs.")
        model = ols.fit(cov_type="HC1")
    else:
        model = ols.fit(cov_type="cluster", cov_kwds={"groups": df["state"]})

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

    # Add the reference period back in at coef=0 so plots/tables read naturally.
    ref_row = pd.DataFrame([{"event_time": int(reference_str), "coef": 0.0, "std_err": 0.0, "ci_low": 0.0, "ci_high": 0.0, "p_value": float("nan")}])
    result = pd.concat([result, ref_row], ignore_index=True).sort_values("event_time").reset_index(drop=True)

    result.attrs["n_obs"] = int(model.nobs)
    result.attrs["r_squared"] = float(model.rsquared)
    return result


def plot_event_study(result: pd.DataFrame, event: Event, outcome_col: str, output_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.axhline(0, color="gray", linewidth=0.8)
    ax.axvline(-0.5, color="red", linestyle="--", linewidth=1, label=f"{event.label} ({event.date.isoformat()})")
    ax.errorbar(
        result["event_time"],
        result["coef"],
        yerr=[result["coef"] - result["ci_low"], result["ci_high"] - result["coef"]],
        fmt="o-",
        capsize=3,
        color="tab:blue",
    )
    ax.set_xlabel("Months relative to launch")
    ax.set_ylabel(f"Effect on {outcome_col} (vs. month before launch)")
    ax.set_title(f"Event study: {event.label}")
    ax.legend()
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"Saved plot -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--event", required=True, choices=sorted(EVENTS_BY_KEY.keys()))
    parser.add_argument("--outcome", required=True, help="Outcome column in the analysis panel, e.g. ai_interest_index or ui_pct_within_21_days")
    parser.add_argument("--window", type=int, default=12, help="Months before/after the event to include (default 12)")
    parser.add_argument("--controls", nargs="*", default=None, help="Extra control columns, e.g. unemployment_rate")
    parser.add_argument("--panel", type=Path, default=PANEL_PATH)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel)
    event = EVENTS_BY_KEY[args.event]
    result = run_event_study(panel, event, args.outcome, window=args.window, control_cols=args.controls)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / f"{event.key}__{args.outcome}.csv"
    result.to_csv(csv_path, index=False)
    print(f"n_obs={result.attrs.get('n_obs')} r_squared={result.attrs.get('r_squared'):.4f}")
    print(result.to_string(index=False))
    print(f"Wrote -> {csv_path}")

    plot_event_study(result, event, args.outcome, OUTPUT_DIR / f"{event.key}__{args.outcome}.png")


if __name__ == "__main__":
    main()
