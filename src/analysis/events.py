"""Curated list of major AI model/service launch dates used as "events" for
the event-study and fuzzy-RD analysis in this package.

Dates were checked directly against Wikipedia (not taken from training
knowledge or a single web-search summary, both of which turned out to
disagree with each other and with speculative-looking blog sources for
2025-2026 releases) as of this repo's last update. Recheck before relying
on this for anything more than exploratory analysis, and see each event's
`source` field.

Selection criteria: included events are widely-covered, mainstream-press
launches likely to produce a detectable jump in search interest (the
first stage of the fuzzy-RD design) -- not an exhaustive list of every
model release. Very recent releases (the last ~2 months of available
data) are excluded because there isn't enough post-period to estimate an
effect.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    key: str
    label: str
    date: datetime.date
    source: str


EVENTS: list[Event] = [
    Event("chatgpt_launch", "ChatGPT public launch", datetime.date(2022, 11, 30), "https://en.wikipedia.org/wiki/ChatGPT"),
    Event("gpt4", "GPT-4 release", datetime.date(2023, 3, 14), "https://en.wikipedia.org/wiki/GPT-4"),
    Event("claude2", "Claude 2 release", datetime.date(2023, 7, 11), "https://en.wikipedia.org/wiki/Claude_(language_model)"),
    Event("gemini1", "Gemini 1.0 launch", datetime.date(2023, 12, 6), "https://en.wikipedia.org/wiki/Gemini_(language_model)"),
    Event("claude3", "Claude 3 release", datetime.date(2024, 3, 4), "https://en.wikipedia.org/wiki/Claude_(language_model)"),
    Event("gpt4o", "GPT-4o release", datetime.date(2024, 5, 13), "https://en.wikipedia.org/wiki/GPT-4o"),
    Event("claude35_sonnet", "Claude 3.5 Sonnet release", datetime.date(2024, 6, 20), "https://en.wikipedia.org/wiki/Claude_(language_model)"),
    Event("gemini2", "Gemini 2.0 launch", datetime.date(2024, 12, 11), "https://en.wikipedia.org/wiki/Gemini_(language_model)"),
    Event("deepseek_r1", "DeepSeek R1 release", datetime.date(2025, 1, 20), "https://en.wikipedia.org/wiki/DeepSeek"),
    Event("claude4", "Claude Sonnet 4 / Opus 4 release", datetime.date(2025, 5, 22), "https://en.wikipedia.org/wiki/Claude_(language_model)"),
    Event("gpt5", "GPT-5 release", datetime.date(2025, 8, 7), "https://en.wikipedia.org/wiki/GPT-5"),
    Event("gemini3", "Gemini 3 launch", datetime.date(2025, 11, 18), "https://en.wikipedia.org/wiki/Gemini_(language_model)"),
]

EVENTS_BY_KEY = {event.key: event for event in EVENTS}


def months_since(year: int, month: int, event: Event) -> int:
    """Integer months between a (year, month) observation and an event's
    date, e.g. -1 = the month before the event, 0 = the event's own month."""
    return (year - event.date.year) * 12 + (month - event.date.month)
