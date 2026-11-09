"""
One clock, resolved once, customer premise wins.

The A3 failure: told to say when the office reopens, the agent queried the server
clock and used it to contradict a customer standing outside a house that smelled
of gas — "the office-status check reports Saturday 9:49 a.m., which conflicts
with your saying it's Sunday 11 p.m."

Two things went wrong, and only one of them is about time. The agent inferred a
concept it should have been handed, and it preferred a tool's answer to the
customer's. This module makes both impossible: time is resolved once per turn,
and when the customer states a time, that time is the one used. A disagreement is
logged, never spoken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
ABBREV = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3,
          "fri": 4, "sat": 5, "sun": 6}

# (weekday, open_hour, close_hour) — None means closed all day
DEFAULT_HOURS = {
    0: (8, 19), 1: (8, 19), 2: (8, 19), 3: (8, 19), 4: (8, 19),
    5: (9, 17), 6: None,
}


@dataclass(frozen=True)
class TimeFacts:
    source: str            # "customer" | "server"
    at: str                # ISO-ish description of the time being reasoned about
    open_now: bool
    next_open: str
    conflict: bool         # customer's stated time disagrees with the server clock
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


DAY_RX = re.compile(r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                    r"mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b", re.I)
HOUR_RX = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.I)
AFTER_RX = re.compile(r"\bafter\s+(\d{1,2})\b", re.I)


def parse_customer_time(text: str) -> tuple[int | None, int | None]:
    """(weekday_index, hour24) as stated by the customer, either may be None."""
    wd = None
    m = DAY_RX.search(text)
    if m:
        token = m.group(1).lower()
        wd = WEEKDAYS.index(token) if token in WEEKDAYS else ABBREV.get(token)
    hour = None
    m = HOUR_RX.search(text)
    if m:
        h = int(m.group(1)) % 12
        hour = h + (12 if m.group(3).lower() == "pm" else 0)
    else:
        m = AFTER_RX.search(text)
        if m:
            h = int(m.group(1))
            hour = h + 12 if h <= 7 else h
    return wd, hour


def _next_open(from_dt: datetime, hours: dict) -> datetime:
    probe = from_dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    for _ in range(24 * 8):
        span = hours.get(probe.weekday())
        if span and span[0] <= probe.hour < span[1]:
            return probe
        probe += timedelta(hours=1)
    return probe


def _fmt(dt: datetime) -> str:
    return dt.strftime("%A %-I:%M %p") if hasattr(dt, "strftime") else str(dt)


def resolve(customer_text: str, now: datetime, hours: dict | None = None) -> TimeFacts:
    """Resolve the time this turn is about. The customer's premise wins."""
    hours = hours or DEFAULT_HOURS
    wd, hour = parse_customer_time(customer_text)

    if wd is None and hour is None:
        span = hours.get(now.weekday())
        is_open = bool(span and span[0] <= now.hour < span[1])
        nxt = _next_open(now, hours)
        return TimeFacts(
            source="server", at=now.strftime("%A %H:%M"), open_now=is_open,
            next_open=nxt.strftime("%A %H:%M"),
            conflict=False,
            note="no time stated by the customer; server clock used",
        )

    # build the customer's implied datetime, nearest future match
    base = now
    target_wd = wd if wd is not None else now.weekday()
    days_ahead = (target_wd - now.weekday()) % 7
    cand = (now + timedelta(days=days_ahead)).replace(minute=0, second=0, microsecond=0)
    if hour is not None:
        cand = cand.replace(hour=hour)
    if cand < now:
        cand += timedelta(days=7)

    span = hours.get(cand.weekday())
    is_open = bool(span and span[0] <= cand.hour < span[1])
    nxt = _next_open(cand, hours)

    conflict = (wd is not None and wd != now.weekday()) or (
        hour is not None and abs(hour - now.hour) >= 2
    )

    return TimeFacts(
        source="customer", at=cand.strftime("%A %H:%M"), open_now=is_open,
        next_open=nxt.strftime("%A %H:%M"), conflict=conflict,
        note=("customer premise used; server clock disagrees and is logged, not spoken"
              if conflict else "customer premise agrees with the server clock"),
    )


def spoken(facts: TimeFacts) -> str:
    """The sentence a platform would hand the agent. Never mentions the clock."""
    if facts.open_now:
        return f"The office is open at {facts.at}."
    return f"The office is closed at {facts.at}. It opens {facts.next_open}."
