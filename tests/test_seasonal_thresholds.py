"""
Tests for lib/seasonal_thresholds.py -- the two deliberately-different
seasonal scaling methods (revenue-multiplier for dollar thresholds,
own-month historical average for labor % thresholds). See that module's
own header for why applying the wrong method to the wrong metric would
silently produce a backwards threshold -- these tests exist to keep that
distinction pinned down.
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.seasonal_thresholds import (
    seasonal_dollar_threshold,
    seasonal_labor_threshold,
    _month_num_from_label,
)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def test_seasonal_dollar_threshold_scales_by_real_month_multiplier(tmp_path):
    _write_json(
        tmp_path / "historical_sales_patterns_live.json",
        {"monthMultipliers": {"7": {"multiplier": 2.16, "yearsUsed": 4}}},
    )
    scaled, note = seasonal_dollar_threshold(str(tmp_path), 25000, month_num=7)
    assert scaled == 25000 * 2.16
    assert "2.16x" in note


def test_seasonal_dollar_threshold_falls_back_when_file_missing(tmp_path):
    scaled, note = seasonal_dollar_threshold(str(tmp_path), 25000, month_num=1)
    assert scaled == 25000
    assert "flat (unscaled)" in note


def test_seasonal_dollar_threshold_falls_back_when_month_has_no_entry(tmp_path):
    _write_json(
        tmp_path / "historical_sales_patterns_live.json",
        {"monthMultipliers": {"7": {"multiplier": 2.16, "yearsUsed": 4}}},
    )
    scaled, note = seasonal_dollar_threshold(str(tmp_path), 25000, month_num=1)
    assert scaled == 25000
    assert "flat (unscaled)" in note


def test_month_num_from_label_parses_standard_and_mtd_labels():
    assert _month_num_from_label("Jul '26") == 7
    assert _month_num_from_label("Jul '26 (MTD thru 8/14)") == 7
    assert _month_num_from_label("Dec '25") == 12


def test_month_num_from_label_returns_none_for_unrecognized_text():
    assert _month_num_from_label("not a month") is None


def test_seasonal_labor_threshold_averages_prior_years_same_month_only(tmp_path):
    """July historically ran 18% and 20% in two prior years; the row being
    evaluated (this year's July, 55%) must NOT be blended into its own
    baseline, and a different month's data must not leak in either."""
    _write_json(
        tmp_path / "labor_efficiency_live.json",
        {
            "monthlyLaborPct": [
                {"month": "Jul '24", "laborPct": 0.18},
                {"month": "Jul '25", "laborPct": 0.20},
                {"month": "Jul '26", "laborPct": 0.55},  # row being evaluated
                {"month": "Aug '25", "laborPct": 0.90},  # different month
                {"month": "Jul '26 (MTD thru 7/14)", "laborPct": 0.99},  # partial, excluded
            ]
        },
    )
    threshold, note = seasonal_labor_threshold(
        str(tmp_path), base_pct=0.30, target_month_label="Jul '26", buffer_pp=0.08
    )
    # historical average of 0.18 and 0.20 = 0.19, plus an 8pp buffer = 0.27
    assert threshold == 0.27
    assert "n=2" in note


def test_seasonal_labor_threshold_falls_back_with_no_prior_year_data(tmp_path):
    _write_json(
        tmp_path / "labor_efficiency_live.json",
        {"monthlyLaborPct": [{"month": "Jul '26", "laborPct": 0.55}]},
    )
    threshold, note = seasonal_labor_threshold(
        str(tmp_path), base_pct=0.30, target_month_label="Jul '26"
    )
    assert threshold == 0.30
    assert "flat (unscaled)" in note
