"""
Typed next steps.

The A1 failure was not that the agent forgot a phone number. It was that "name a
route" is satisfiable by prose, so the cheapest prose that satisfies it wins —
the agent wrote "reply in chat" and the customer in a flooding kitchen was left
holding a keyboard.

This module makes the next step a value from a closed set, extracted from the
reply and, when absent, rendered by the platform rather than written by the
model. Nothing here is model-specific: it runs on any agent's output.

    step = extract(reply, BUSINESS)
    if step is None:
        reply = repair(reply, BUSINESS)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Literal

Kind = Literal["call", "book", "pay", "handoff"]


@dataclass(frozen=True)
class Business:
    name: str
    phone: str
    booking_url: str
    fee_usd: int


@dataclass(frozen=True)
class NextStep:
    kind: Kind
    target: str
    evidence: str

    def as_dict(self) -> dict:
        return asdict(self)


PHONE = re.compile(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")
BOOKING = re.compile(r"booking page|book online|request (?:a|your) (?:time|appointment)|schedule online", re.I)
PAY = re.compile(r"\bpay (?:the )?(?:diagnostic )?(?:fee|online)\b|\bpay \$\d+|\bpayment (?:link|of \$)", re.I)
HANDOFF = re.compile(r"(?:office|team|representative|a person|dispatch) (?:can|will|to)|hand(?:ed)? off|office review", re.I)
# "reply in chat" is the failure this module exists to catch
IN_CHAT = re.compile(r"reply (?:here|in chat)|send (?:me|us) (?:the|your) details|share (?:your )?(?:address|details) (?:here|in this chat)", re.I)


def extract(reply: str, business: Business) -> NextStep | None:
    """The last actionable route named in the reply, or None.

    Order matters: an explicit phone number beats a booking mention, which beats
    a payment mention, which beats a handoff. A reply that only asks the customer
    to keep typing returns None even though it contains words.
    """
    tail = reply[-700:]
    m = PHONE.search(tail)
    if m:
        return NextStep("call", business.phone, m.group(0))
    m = BOOKING.search(tail)
    if m:
        return NextStep("book", business.booking_url, m.group(0))
    m = PAY.search(tail)
    if m:
        return NextStep("pay", f"{business.booking_url}#pay", m.group(0))
    m = HANDOFF.search(tail)
    if m:
        return NextStep("handoff", business.phone, m.group(0))
    return None


def repair(reply: str, business: Business) -> str:
    """Append a platform-rendered next step. Idempotent."""
    if extract(reply, business) is not None:
        return reply
    return (
        reply.rstrip()
        + f"\n\nNext step: call or text {business.phone}, or open {business.booking_url} to request a time."
    )


def audit(reply: str, business: Business) -> dict:
    """What a platform would log for this turn."""
    step = extract(reply, business)
    return {
        "has_next_step": step is not None,
        "kind": step.kind if step else None,
        "in_chat_only": bool(IN_CHAT.search(reply[-700:])) and step is None,
    }


DEFAULT = Business(
    name="Budget Heating, Cooling & Plumbing",
    phone="(636) 887-2800",
    booking_url="https://justcallbudget.com/book-online/",
    fee_usd=99,
)
