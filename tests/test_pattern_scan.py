"""
Tests for lib/pattern_scan.py -- the shared Pearson-correlation utility
every Senior Manager script can call to scan its own domain's time series
for non-obvious patterns, without asking an LLM to "notice" anything.
"""
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.pattern_scan import pearson, scan_correlations


def test_pearson_perfect_positive_correlation():
    a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    b = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20]
    r, n = pearson(a, b, min_overlap=5)
    assert n == 10
    assert r == pytest.approx(1.0)


def test_pearson_perfect_negative_correlation():
    a = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    b = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    r, n = pearson(a, b, min_overlap=5)
    assert r == pytest.approx(-1.0)


def test_pearson_returns_none_below_min_overlap():
    a = [1, 2, 3]
    b = [1, 2, 3]
    r, n = pearson(a, b, min_overlap=10)
    assert r is None
    assert n == 3


def test_pearson_returns_none_for_constant_series():
    """A constant series has undefined correlation -- must not divide by
    zero or report a bogus r value."""
    a = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5]
    b = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    r, n = pearson(a, b, min_overlap=5)
    assert r is None


def test_pearson_skips_none_values_in_pairs():
    a = [1, None, 3, 4, 5, 6, 7, 8, 9, 10]
    b = [2, 4, None, 8, 10, 12, 14, 16, 18, 20]
    r, n = pearson(a, b, min_overlap=5)
    # only the 8 fully-paired points count
    assert n == 8


def test_scan_correlations_lag_zero_is_symmetric_and_tagged_same_domain():
    series = {
        "LAB-WAGES": [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110],
        "LAB-HOURS": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
        "INC-REV": [100, 90, 80, 70, 60, 50, 40, 30, 20, 10, 0],
    }
    result = scan_correlations(series, min_overlap=5, lags=(0,))
    assert result["testsRun"] == 3  # C(3,2) unordered pairs at lag 0
    lab_pair = next(
        r for r in result["results"]
        if {r["a"], r["b"]} == {"LAB-WAGES", "LAB-HOURS"}
    )
    assert lab_pair["sameDomain"] is True
    cross = next(
        r for r in result["results"]
        if {r["a"], r["b"]} == {"LAB-WAGES", "INC-REV"}
    )
    assert cross["sameDomain"] is False


def test_scan_correlations_respects_min_overlap_guardrail():
    """A business with less history than min_overlap should get zero
    results -- the documented 'correct behavior, not a bug' case."""
    series = {
        "A": [1, 2, 3],
        "B": [3, 2, 1],
    }
    result = scan_correlations(series, min_overlap=10, lags=(0,))
    assert result["resultsWithEnoughData"] == 0
    assert result["results"] == []
