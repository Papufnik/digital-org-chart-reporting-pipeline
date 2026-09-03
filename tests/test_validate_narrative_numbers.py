"""
Tests for lib/validate_narrative_numbers.py -- the guardrail that decides
whether an LLM-generated narrative is allowed to ship.

The most important test here is test_check_narrative_catches_real_rounding_slip,
which pins down the exact scenario the README describes: a hand-written sample
narrative said "$59,417" where the verified source fact was "$54,830.25".
That's a genuine-looking number, just not one that was actually verified --
and the guardrail's whole job is to reject exactly that.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.validate_narrative_numbers import (
    extract_numbers,
    collect_allowed_numbers_from_data,
    numbers_match,
    check_narrative,
)


def test_extract_numbers_plain_integers_and_decimals():
    assert extract_numbers("we sold 12 units at 4.5 each") == {12.0, 4.5}


def test_extract_numbers_strips_money_percent_and_multiplier_signs():
    text = "revenue was $54,830.25, up 12.5%, a 2.5x multiple"
    assert extract_numbers(text) == {54830.25, 12.5, 2.5}


def test_extract_numbers_ignores_non_numeric_text():
    assert extract_numbers("no numbers in this sentence at all") == set()


def test_numbers_match_exact():
    allowed = {54830.25, 12.0}
    assert numbers_match(54830.25, allowed) is True


def test_numbers_match_rounded_to_nearest_whole_unit():
    # $68,920.14 in the source fact should validate "$68,920" in prose.
    allowed = {68920.14}
    assert numbers_match(68920.0, allowed) is True


def test_numbers_match_within_small_tolerance():
    allowed = {12.5}
    assert numbers_match(12.6, allowed, tol=0.5) is True


def test_numbers_match_rejects_unrelated_number():
    allowed = {54830.25, 12.0}
    assert numbers_match(59417.0, allowed) is False


def test_collect_allowed_numbers_from_data_walks_nested_structures():
    cfo = {"cashDebtAndTerms": [{"metric": "$54,830.25 on hand"}]}
    coo = {"needsAttention": [{"value": 12.5}]}
    allowed = collect_allowed_numbers_from_data(cfo, coo)
    assert 54830.25 in allowed
    assert 12.5 in allowed


def test_check_narrative_passes_when_every_number_is_verified():
    allowed = collect_allowed_numbers_from_data(
        {"cash": "Cash on hand is $54,830.25, up 12.5% year over year."}
    )
    narrative = "Cash on hand is $54,830.25, up 12.5% year over year."
    is_valid, unmatched = check_narrative(narrative, allowed)
    assert is_valid is True
    assert unmatched == []


def test_check_narrative_catches_real_rounding_slip():
    """The exact real bug from the README: source fact was $54,830.25,
    a hand-written narrative said $59,417 -- a plausible-looking but
    fabricated number. The guardrail must reject the whole narrative,
    not just flag the one bad number."""
    allowed = collect_allowed_numbers_from_data(
        {"cash": "Cash on hand is $54,830.25 this week."}
    )
    narrative = "Cash on hand is $59,417 this week, a healthy cushion."
    is_valid, unmatched = check_narrative(narrative, allowed)
    assert is_valid is False
    assert 59417.0 in unmatched


def test_check_narrative_fails_closed_on_any_single_bad_number():
    """One unverified number discards the WHOLE narrative -- no
    partial-trust, per the documented guardrail design."""
    allowed = collect_allowed_numbers_from_data({"cash": "$100.00 on hand."})
    narrative = "We have $100.00 on hand, and margin improved by 40%."
    is_valid, unmatched = check_narrative(narrative, allowed)
    assert is_valid is False
    assert 40.0 in unmatched
