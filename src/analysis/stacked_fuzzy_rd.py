"""Pooled ("stacked") fuzzy regression discontinuity across multiple AI
model/service launches, rather than one fuzzy_rd.py run per launch.

Why: fuzzy_rd.py's individual per-event estimates are noisy, especially
for a single-state outcome like NYC's parking-ticket appeals or Texas's
small-claims filings -- few observations fall within +/-bandwidth months
of any one cutoff, so the reported LATE standard errors end up several
times the point estimate (confirmed against real data -- see the main
README's fuzzy-RD notes). Exactly the same problem stacked_event_study.py
already solved for the event-time-dummy design, applied here to the
local-linear RD design instead: pool state-months across N events into
one local-linear regression per side (first stage, reduced form), with
state and event fixed effects, so each event-time bin gets many events'
worth of observations instead of one.

Model (first stage and reduced form estimated separately, same two-step
Wald/IV structure as fuzzy_rd.py):
    metric ~ treated + event_time + treated*event_time + state FE + event FE
weighted by a triangular kernel within +/-bandwidth months of each row's
own event's cutoff (same kernel convention as fuzzy_rd.py). `treated` is
1(event_time >= 0). Deliberately no calendar-month FE here, unlike
stacked_event_study.py: this is a local comparison right at each cutoff,
not a full seasonally-adjusted model, and adding another FE dimension on
top of state + event fixed effects within an already-narrow local window
risks the same kind of rank-deficiency issue documented there for little
benefit -- a local-linear RD's job is to net out the *trend*, not every
possible confound.

    LATE = pooled reduced-form jump / pooled first-stage jump

same ratio interpretation as fuzzy_rd.py: near a launch date, a one-unit
increase in search interest is associated with this much change in
outcome_col, this time averaged over all pooled events rather than one.
Same standard-error caveat as fuzzy_rd.py applies (delta-method
approximation, ignores covariance between the two jump estimates).

Reuses stacked_event_study.py's build_stacked_panel() for the windowing/
trimming logic, so the same neighbor-trimming default and --no-trim
override apply here too (see that module's docstring for why: without
trimming, a launch's own +/-bandwidth window can bleed into a
closely-spaced neighboring launch's window).

Usage:
    python -m src.analysis.stacked_fuzzy_rd --outcome parking_appeal_records --bandwidth 6
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from src.analysis.events import EVENTS, EVENTS_BY_KEY, Event
from src.analysis.stacked_event_study import build_stacked_panel

ROOT = Path(__file__).resolve().parents[2]
PANEL_PATH = ROOT / "data" / "processed" / "analysis_panel_state_month.csv"
OUTPUT_DIR = ROOT / "data" / "processed" / "fuzzy_rd"


@dataclass
class PooledLocalLinearResult:
    jump: float
    std_err: float
    n_obs: int


def pooled_local_linear_jump(stacked: pd.DataFrame, outcome_col: str, bandwidth: int, cluster_col: str = "state") -> PooledLocalLinearResult:
    """Same triangular-kernel local-linear jump as fuzzy_rd.py's
    local_linear_jump(), but on an already-built multi-event stacked
    panel (see build_stacked_panel()), with state and event fixed
    effects added since the pooled sample now spans multiple launches."""
    d = stacked.dropna(subset=[outcome_col, "event_time"]).copy()
    if d.empty or d["event_time"].nunique() < 2:
        raise ValueError(f"Not enough data within bandwidth={bandwidth} for {outcome_col}")

    d["treated"] = (d["event_time"] >= 0).astype(int)
    d["weight"] = (1 - d["event_time"].abs() / bandwidth).clip(lower=1e-6)
    d["interaction"] = d["treated"] * d["event_time"]

    formula = f"{outcome_col} ~ treated + event_time + interaction + C(state)"
    if d["event_key"].nunique() > 1:
        formula += " + C(event_key)"

    wls = smf.wls(formula, data=d, weights=d["weight"])
    n_clusters = d[cluster_col].nunique()
    if n_clusters < 2:
        # Same single-cluster fallback as fuzzy_rd.py/event_study.py --
        # cluster-robust SEs need >=2 clusters.
        print(f"Note: outcome '{outcome_col}' has only {n_clusters} state(s) -- using HC1 robust SEs instead of state-clustered SEs.")
        model = wls.fit(cov_type="HC1")
    else:
        model = wls.fit(cov_type="cluster", cov_kwds={"groups": d[cluster_col]})
    return PooledLocalLinearResult(jump=model.params["treated"], std_err=model.bse["treated"], n_obs=int(model.nobs))


def stacked_fuzzy_rd(
    panel: pd.DataFrame,
    events: list[Event],
    outcome_col: str,
    running_metric_col: str = "ai_interest_index",
    bandwidth: int = 6,
    trim_to_neighbors: bool = True,
) -> dict:
    stacked = build_stacked_panel(panel, events, bandwidth, trim_to_neighbors)

    first_stage = pooled_local_linear_jump(stacked, running_metric_col, bandwidth)
    reduced_form = pooled_local_linear_jump(stacked, outcome_col, bandwidth)

    late = reduced_form.jump / first_stage.jump
    # Delta method, ignoring cov(first_stage, reduced_form) -- see module docstring.
    late_se = np.sqrt(
        (reduced_form.std_err / first_stage.jump) ** 2
        + (reduced_form.jump * first_stage.std_err / first_stage.jump**2) ** 2
    )

    return {
        "n_events": len(events),
        "outcome": outcome_col,
        "running_metric": running_metric_col,
        "bandwidth_months": bandwidth,
        "trim_to_neighbors": trim_to_neighbors,
        "first_stage_jump": first_stage.jump,
        "first_stage_se": first_stage.std_err,
        "first_stage_n": first_stage.n_obs,
        "reduced_form_jump": reduced_form.jump,
        "reduced_form_se": reduced_form.std_err,
        "reduced_form_n": reduced_form.n_obs,
        "fuzzy_rd_late": late,
        "fuzzy_rd_late_se_approx": late_se,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events", nargs="*", default=None, choices=sorted(EVENTS_BY_KEY.keys()), help="Event keys to pool (default: all)")
    parser.add_argument("--outcome", required=True, help="Reduced-form outcome column, e.g. parking_appeal_records")
    parser.add_argument("--running-metric", default="ai_interest_index", help="First-stage column (default: ai_interest_index)")
    parser.add_argument("--bandwidth", type=int, default=6, help="Months on each side of each event's cutoff (default 6)")
    parser.add_argument("--no-trim", action="store_true", help="Use the fixed bandwidth for every event instead of trimming near neighbors")
    parser.add_argument("--panel", type=Path, default=PANEL_PATH)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel)
    events = [EVENTS_BY_KEY[k] for k in args.events] if args.events else list(EVENTS)
    result = stacked_fuzzy_rd(
        panel, events, args.outcome, args.running_metric, args.bandwidth, trim_to_neighbors=not args.no_trim
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if not args.no_trim else "__no_trim"
    out_path = OUTPUT_DIR / f"stacked__{args.outcome}{suffix}.csv"
    pd.DataFrame([result]).to_csv(out_path, index=False)

    for k, v in result.items():
        print(f"{k}: {v}")
    print(f"Wrote -> {out_path}")


if __name__ == "__main__":
    main()
