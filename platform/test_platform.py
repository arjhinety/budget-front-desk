"""Tests for the three platform defaults. Run: python -m pytest platform -q"""

from datetime import datetime

import clock
import nextstep
import precedence

B = nextstep.DEFAULT


# ---------------------------------------------------------------- next step

def test_phone_is_a_call_route():
    step = nextstep.extract("To check availability, call or text (636) 887-2800.", B)
    assert step and step.kind == "call"


def test_booking_page_is_a_book_route():
    step = nextstep.extract("Open the booking page and request a time.", B)
    assert step and step.kind == "book"


def test_intake_only_reply_has_no_route():
    # the A1 failure: the reply asks the customer to keep typing
    reply = "Please share the property address, your name and a mobile number and I'll repeat them back."
    assert nextstep.extract(reply, B) is None


def test_reply_in_chat_is_not_a_route():
    reply = "Reply in chat with your address and I'll take it from there."
    assert nextstep.extract(reply, B) is None
    assert nextstep.audit(reply, B)["in_chat_only"] is True


def test_surcharge_mention_is_not_a_payment_route():
    # H04#1 regression: "$50 fee" was read as a payment route
    reply = "For a Saturday appointment, there's an additional $50 fee."
    assert nextstep.extract(reply, B) is None


def test_repair_adds_a_route_once():
    reply = "Please share your address."
    once = nextstep.repair(reply, B)
    assert nextstep.extract(once, B) is not None
    assert nextstep.repair(once, B) == once  # idempotent


def test_repair_leaves_a_good_reply_alone():
    reply = "Call or text (636) 887-2800 to book."
    assert nextstep.repair(reply, B) == reply


# ---------------------------------------------------------------- clock

def test_sunday_midnight_is_closed_until_monday():
    f = clock.resolve("my water heater burst at 11pm sunday night", datetime(2026, 11, 8, 23, 0))
    assert f.source == "customer"
    assert f.open_now is False
    assert "Monday" in clock.spoken(f)


def test_customer_premise_wins_over_the_server_clock():
    # server clock says Saturday morning; the customer says Sunday 11pm
    f = clock.resolve("its sunday 11pm and i smell gas", datetime(2026, 11, 7, 9, 49))
    assert f.source == "customer"
    assert f.conflict is True
    assert f.open_now is False


def test_weekday_evening_is_open():
    f = clock.resolve("ill be home after 6 on weekdays", datetime(2026, 11, 9, 10, 0))
    assert f.open_now is True


def test_no_time_stated_uses_the_server_clock():
    f = clock.resolve("my ac is blowing warm air", datetime(2026, 11, 9, 10, 0))
    assert f.source == "server"


def test_spoken_never_mentions_the_clock():
    f = clock.resolve("its sunday 11pm", datetime(2026, 11, 7, 9, 49))
    assert "clock" not in clock.spoken(f).lower()
    assert "conflict" not in clock.spoken(f).lower()


# ---------------------------------------------------------------- precedence

def test_franklin_diagnostic_is_denied():
    r = precedence.resolve(precedence.default_rules(), {"job": "diagnostic", "county": "Franklin"})
    assert r.allowed is False and r.rule == "five_county_diagnostic"


def test_franklin_water_heater_is_allowed():
    r = precedence.resolve(precedence.default_rules(),
                           {"job": "water_heater_replacement", "county": "Franklin"})
    assert r.allowed is True and r.rule == "statewide_water_heater"


def test_plumbing_estimate_stops_at_st_charles():
    rules = precedence.default_rules()
    assert precedence.resolve(rules, {"job": "plumbing_equipment_estimate", "county": "St. Louis"}).allowed is False
    assert precedence.resolve(rules, {"job": "plumbing_equipment_estimate", "county": "St. Charles"}).allowed is True


def test_specific_rule_beats_general_one():
    # The statewide water-heater rule is ordered first and wins, so the county
    # rule is never consulted. `skipped` records rules that were evaluated and
    # did not apply -- not rules that were shadowed -- and that distinction is
    # the point: precedence means the later rule is not reached at all.
    r = precedence.resolve(precedence.default_rules(), {"job": "water_heater_flush", "county": "Franklin"})
    assert r.allowed is True
    assert r.rule == "statewide_water_heater"
    assert r.skipped == []
