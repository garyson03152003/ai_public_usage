import numpy as np
import pandas as pd
import pytest

from src.analysis.events import EVENTS_BY_KEY, months_since
from src.analysis.event_study import run_event_study
from src.analysis.fuzzy_rd import fuzzy_rd

EVENT = EVENTS_BY_KEY["chatgpt_launch"]  # 2022-11-30


def test_months_since():
    assert months_since(2022, 11, EVENT) == 0
    assert months_since(2022, 10, EVENT) == -1
    assert months_since(2022, 12, EVENT) == 1
    assert months_since(2023, 11, EVENT) == 12
    assert months_since(2021, 11, EVENT) == -12


def _synthetic_panel(true_jump: float, seed: int = 0, n_months: int = 24) -> pd.DataFrame:
    """States with different fixed effects, a smooth linear drift in
    event_time (which a local-linear/event-time-dummy model should fully
    absorb, isolating the jump), and a deterministic jump of `true_jump`
    at event_time >= 0, plus small noise. Deliberately no seasonal/curved
    confound here -- that would bias a *local-linear* estimator by
    construction (finite-bandwidth bias), which is a property of the
    method, not something this test is meant to probe."""
    rng = np.random.default_rng(seed)
    states = ["California", "Texas", "New York", "Wyoming"]
    state_effect = {"California": 10.0, "Texas": 5.0, "New York": 8.0, "Wyoming": 0.0}

    periods = pd.period_range("2022-01", periods=n_months, freq="M")
    rows = []
    for state in states:
        for period in periods:
            year, month = period.year, period.month
            event_time = months_since(year, month, EVENT)
            trend = 0.1 * event_time
            jump = true_jump if event_time >= 0 else 0.0
            noise = rng.normal(0, 0.5)
            rows.append(
                {
                    "state": state,
                    "year": year,
                    "month": month,
                    "y": state_effect[state] + trend + jump + noise,
                }
            )
    return pd.DataFrame(rows)


def test_event_study_recovers_known_jump():
    panel = _synthetic_panel(true_jump=7.0)
    result = run_event_study(panel, EVENT, "y", window=10)

    post_launch = result[result["event_time"].between(0, 8)]
    assert post_launch["coef"].mean() == pytest.approx(7.0, abs=0.6)

    pre_launch = result[result["event_time"].between(-8, -2)]
    assert pre_launch["coef"].mean() == pytest.approx(0.0, abs=0.6)


def test_fuzzy_rd_recovers_known_ratio():
    rng_state = 42
    # First-stage variable jumps by 20, outcome jumps by 8 -> true LATE = 0.4
    first_stage_panel = _synthetic_panel(true_jump=20.0, seed=rng_state).rename(columns={"y": "ai_interest_index"})
    reduced_form_panel = _synthetic_panel(true_jump=8.0, seed=rng_state + 1).rename(columns={"y": "outcome"})
    panel = first_stage_panel.merge(reduced_form_panel, on=["state", "year", "month"])

    result = fuzzy_rd(panel, EVENT, outcome_col="outcome", running_metric_col="ai_interest_index", bandwidth=8)

    assert result["first_stage_jump"] == pytest.approx(20.0, abs=1.5)
    assert result["reduced_form_jump"] == pytest.approx(8.0, abs=1.5)
    assert result["fuzzy_rd_late"] == pytest.approx(0.4, abs=0.1)
