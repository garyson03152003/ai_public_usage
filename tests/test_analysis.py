import datetime

import numpy as np
import pandas as pd
import pytest

from src.analysis.events import EVENTS, EVENTS_BY_KEY, Event, months_since
from src.analysis.event_study import run_event_study
from src.analysis.fuzzy_rd import fuzzy_rd
from src.analysis.stacked_event_study import event_time_bounds, run_stacked_event_study

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


def test_event_time_bounds_trims_near_close_neighbors():
    # Real production gaps: chatgpt_launch -> gpt4 is 4 months, gpt4o -> claude35_sonnet is 1 month.
    lower, upper = event_time_bounds(EVENTS_BY_KEY["chatgpt_launch"], EVENTS, max_window=12)
    assert lower == -12  # no earlier neighbor, so the fixed window applies
    assert upper == 3  # capped just before gpt4's own month (4 months later)

    lower, upper = event_time_bounds(EVENTS_BY_KEY["gpt4o"], EVENTS, max_window=12)
    assert upper == 0  # claude35_sonnet is only 1 month later -- no post-period room at all


def _well_separated_events() -> list[Event]:
    """Three synthetic events far enough apart that a +/-6 window never
    overlaps, each landing in a different calendar month -- so pooling
    them should let calendar-month fixed effects be identified even
    though a single event's window alone can't (see event_study.py)."""
    return [
        Event("e1", "Event 1", datetime.date(2020, 3, 15), "synthetic"),
        Event("e2", "Event 2", datetime.date(2021, 9, 15), "synthetic"),
        Event("e3", "Event 3", datetime.date(2023, 1, 15), "synthetic"),
    ]


def _stacked_synthetic_panel(events: list[Event], true_jump: float, seed: int = 0) -> pd.DataFrame:
    """Unlike _synthetic_panel, this one DOES include a seasonal
    (sinusoidal) confound -- the point of this test is to check that
    pooling multiple events (landing in different calendar months) lets
    the model separate that seasonality from the event-time jump, which a
    single-event regression provably cannot do (see event_study.py's
    docstring on why calendar-month FE is dropped there)."""
    rng = np.random.default_rng(seed)
    states = ["California", "Texas", "New York", "Wyoming"]
    state_effect = {"California": 10.0, "Texas": 5.0, "New York": 8.0, "Wyoming": 0.0}

    start = min(e.date for e in events)
    periods = pd.period_range(f"{start.year - 1}-01", periods=(max(e.date.year for e in events) - start.year + 3) * 12, freq="M")

    rows = []
    for state in states:
        for period in periods:
            year, month = period.year, period.month
            seasonal = 3.0 * np.sin(month / 12 * 2 * np.pi)
            jump = 0.0
            for event in events:
                et = months_since(year, month, event)
                if -6 <= et <= 6 and et >= 0:
                    jump = true_jump
            noise = rng.normal(0, 0.3)
            rows.append({"state": state, "year": year, "month": month, "y": state_effect[state] + seasonal + jump + noise})
    return pd.DataFrame(rows)


def test_stacked_event_study_recovers_jump_and_identifies_seasonality():
    events = _well_separated_events()
    panel = _stacked_synthetic_panel(events, true_jump=6.0)

    result = run_stacked_event_study(panel, events, "y", max_window=6)

    post = result[result["event_time"].between(0, 6)]
    assert post["coef"].mean() == pytest.approx(6.0, abs=0.5)

    pre = result[result["event_time"].between(-6, -2)]
    assert pre["coef"].mean() == pytest.approx(0.0, abs=0.5)
