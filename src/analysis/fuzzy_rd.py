"""Fuzzy regression discontinuity around an AI-model launch date.

Design: the running variable is "months since launch" (from
src.analysis.events), the cutoff is 0. A model's release doesn't uniformly
switch every state "on" -- some states' search interest jumps much more
than others -- so this isn't a sharp RD where treatment goes cleanly from
0 to 1 at the cutoff. Instead:

  1. First stage:   ai_interest_index ~ treated + running + treated*running
  2. Reduced form:   outcome_col      ~ treated + running + treated*running

both estimated by local-linear weighted least squares (a triangular
kernel within +/-bandwidth months of the cutoff), separately allowing
different slopes on each side -- the standard local-linear RD estimator.
`treated` is 1(months_since_event >= 0).

The fuzzy-RD (Wald/IV) estimate is the ratio of the two jumps:

    LATE = reduced_form_jump / first_stage_jump

interpreted as: near the launch date, a one-unit increase in search
interest is associated with this much change in outcome_col. This is a
local comparison of state-months just before vs. just after launch, not
a claim that AI adoption *causes* the change in outcome_col -- confounds
that also move sharply at the same calendar date (e.g. an unrelated
policy change announced the same week) would bias it.

Caveat on the reported LATE standard error: it's a delta-method
approximation that ignores the covariance between the first-stage and
reduced-form estimates (both come from regressions on the same
observations, so their errors are probably correlated) -- treat it as
directionally useful, not exact. The first-stage and reduced-form jumps
each have proper clustered-by-state standard errors from their own
regression, which are exact under the model's usual assumptions.

Usage:
    python -m src.analysis.fuzzy_rd --event chatgpt_launch --outcome ui_pct_within_21_days
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from src.analysis.events import EVENTS_BY_KEY, Event, months_since

ROOT = Path(__file__).resolve().parents[2]
PANEL_PATH = ROOT / "data" / "processed" / "analysis_panel_state_month.csv"
OUTPUT_DIR = ROOT / "data" / "processed" / "fuzzy_rd"


@dataclass
class LocalLinearResult:
    jump: float
    std_err: float
    n_obs: int


def local_linear_jump(df: pd.DataFrame, outcome_col: str, bandwidth: int, cluster_col: str = "state") -> LocalLinearResult:
    """Estimate the discontinuity in outcome_col at running_time=0 via
    triangular-kernel-weighted local-linear regression within +/-bandwidth."""
    d = df.dropna(subset=[outcome_col, "event_time"]).copy()
    d = d[d["event_time"].abs() <= bandwidth]
    if d.empty or d["event_time"].nunique() < 2:
        raise ValueError(f"Not enough data within bandwidth={bandwidth} for {outcome_col}")

    d["treated"] = (d["event_time"] >= 0).astype(int)
    d["weight"] = (1 - d["event_time"].abs() / bandwidth).clip(lower=1e-6)
    d["interaction"] = d["treated"] * d["event_time"]

    model = smf.wls(f"{outcome_col} ~ treated + event_time + interaction", data=d, weights=d["weight"]).fit(
        cov_type="cluster", cov_kwds={"groups": d[cluster_col]}
    )
    return LocalLinearResult(jump=model.params["treated"], std_err=model.bse["treated"], n_obs=int(model.nobs))


def fuzzy_rd(
    panel: pd.DataFrame,
    event: Event,
    outcome_col: str,
    running_metric_col: str = "ai_interest_index",
    bandwidth: int = 6,
) -> dict:
    df = panel.copy()
    df["event_time"] = [months_since(y, m, event) for y, m in zip(df["year"], df["month"])]

    first_stage = local_linear_jump(df, running_metric_col, bandwidth)
    reduced_form = local_linear_jump(df, outcome_col, bandwidth)

    late = reduced_form.jump / first_stage.jump
    # Delta method, ignoring cov(first_stage, reduced_form) -- see module docstring.
    late_se = np.sqrt(
        (reduced_form.std_err / first_stage.jump) ** 2
        + (reduced_form.jump * first_stage.std_err / first_stage.jump**2) ** 2
    )

    return {
        "event": event.key,
        "event_label": event.label,
        "event_date": event.date.isoformat(),
        "outcome": outcome_col,
        "running_metric": running_metric_col,
        "bandwidth_months": bandwidth,
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
    parser.add_argument("--event", required=True, choices=sorted(EVENTS_BY_KEY.keys()))
    parser.add_argument("--outcome", required=True, help="Reduced-form outcome column, e.g. ui_pct_within_21_days")
    parser.add_argument("--running-metric", default="ai_interest_index", help="First-stage column (default: ai_interest_index)")
    parser.add_argument("--bandwidth", type=int, default=6, help="Months on each side of the cutoff (default 6)")
    parser.add_argument("--panel", type=Path, default=PANEL_PATH)
    args = parser.parse_args()

    panel = pd.read_csv(args.panel)
    event = EVENTS_BY_KEY[args.event]
    result = fuzzy_rd(panel, event, args.outcome, args.running_metric, args.bandwidth)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{event.key}__{args.outcome}.csv"
    pd.DataFrame([result]).to_csv(out_path, index=False)

    for k, v in result.items():
        print(f"{k}: {v}")
    print(f"Wrote -> {out_path}")


if __name__ == "__main__":
    main()
