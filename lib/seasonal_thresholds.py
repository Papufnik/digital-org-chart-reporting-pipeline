import os
import json
import re
from datetime import datetime

"""
seasonal_thresholds.py

Added 2026-08-18. the operator's call, after reviewing the CFO/COO threshold table
in DIGITAL_ORG_CHART.md: several dollar/percent thresholds were flat numbers
that don't make sense across a business this seasonal (January runs 0.32x
an average month, July runs 2.16x -- a $25,000 "lost sales" WARNING is
appropriately aggressive in January and almost meaningless in July). This
module is the shared logic both cfo_executive_audit.py and
coo_operations_audit.py use to scale their thresholds by real historical
data, not a hand-typed seasonal guess.

TWO DIFFERENT SCALING METHODS, deliberately not the same one everywhere:

1. REVENUE-MULTIPLIER SCALING (`seasonal_dollar_threshold`) -- for dollar
   thresholds that represent "how much money moving through the business
   this month makes this concerning" (stockout lost sales, capital tied up
   in slow-moving stock). Multiplies the flat base threshold by
   historical_sales_patterns_live.json's real 4-year blended month index
   (already trusted and reused elsewhere in this codebase -- see
   build_cash_forecast.py). NOT applied to ratios/percentages (GMROI,
   vendor markup, correlation thresholds) or to data-integrity checks
   (bank-vs-POS match, fee-rate outliers) -- those aren't revenue-scale
   problems and scaling them would be wrong, not just unnecessary.

2. HISTORICAL-OWN-MONTH SCALING (`seasonal_labor_threshold`) -- for labor
   as % of net sales specifically. This is already a revenue-relative
   ratio, so multiplying it by a revenue index would double-count
   seasonality. What actually varies by month is the "normal" ratio itself
   -- fixed staffing costs against thin winter revenue structurally push
   this ratio much higher (Nov-Feb historically 38-53%) than peak summer
   (Jun-Sep historically 17-22%), confirmed real in
   labor_efficiency_live.json's monthlyLaborPct series. This function reads
   that same calendar month's own historical value (currently 1 year of
   data per month -- thin, flagged as such) and adds a fixed percentage-
   point buffer on top, rather than applying one flat cutoff to every
   month.

Both functions fail safe: if the source file or a specific month's history
is missing, they fall back to the original flat threshold, loudly (printed
warning), never silently.
"""

_MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def _load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[WARN] seasonal_thresholds: failed to load {path}: {e}")
        return None


def get_month_multiplier(dash_dir, month_num=None):
    """Real 4-year blended seasonal index for the given month (1-12,
    defaults to today's month). Returns (multiplier, note) -- multiplier is
    None if the source file is missing or that month has no data, in which
    case the caller should fall back to its flat threshold."""
    month_num = month_num or datetime.now().month
    data = _load_json(os.path.join(dash_dir, "historical_sales_patterns_live.json"))
    if not data:
        return None, "historical_sales_patterns_live.json missing -- run build_historical_sales_patterns.py"
    entry = (data.get("monthMultipliers") or {}).get(str(month_num))
    if not entry:
        return None, f"No seasonal index entry for month {month_num}"
    years = entry.get("yearsUsed", 0)
    return entry["multiplier"], f"{years}-year blended seasonal index"


def seasonal_dollar_threshold(dash_dir, base_value, month_num=None):
    """Scales a flat dollar threshold by the real seasonal revenue index.
    Returns (scaled_value, note). Falls back to base_value if no index is
    available."""
    mult, note = get_month_multiplier(dash_dir, month_num)
    if mult is None:
        return base_value, f"flat (unscaled) -- {note}"
    scaled = round(base_value * mult, 2)
    return scaled, f"{note}, {mult:.2f}x this month vs. average -- scaled from ${base_value:,.0f} base"


def _month_num_from_label(label):
    """'Jul \\'26' or 'Jul \\'26 (MTD thru 8/14)' -> 7. Returns None if the
    label doesn't start with a recognized 3-letter month abbreviation."""
    m = re.match(r"^([A-Za-z]{3})", str(label).strip())
    if not m:
        return None
    abbr = m.group(1).title()
    return _MONTH_NAMES.index(abbr) + 1 if abbr in _MONTH_NAMES else None


def seasonal_labor_threshold(dash_dir, base_pct, target_month_label, buffer_pp=0.08):
    """Historical-own-month labor% for the SAME calendar month as
    target_month_label (e.g. "Jul '26"), plus a fixed percentage-point
    buffer, as the WARNING cutoff -- not the flat base_pct. Returns
    (threshold, note). Falls back to base_pct if the source file or that
    month's history is missing.

    The row being evaluated (matched by its exact month label, e.g. this
    "Jun '26" itself) is excluded from its own baseline -- the point is to
    compare this month against PRIOR years' same month, not blend the
    current observation into the number it's being judged against, which
    would make the threshold chase whatever value it's supposed to be
    testing.

    buffer_pp=0.08 (8 percentage points) is itself a starting proposal, same
    as every other number in this file -- picked as reasonable headroom
    above a single year's noisy observation, not independently validated.
    """
    target_month_num = _month_num_from_label(target_month_label)
    if target_month_num is None:
        return base_pct, f"flat (unscaled) -- couldn't parse a month from '{target_month_label}'"

    data = _load_json(os.path.join(dash_dir, "labor_efficiency_live.json"))
    if not data:
        return base_pct, "flat (unscaled) -- labor_efficiency_live.json missing"

    monthly = data.get("monthlyLaborPct", [])
    same_month_pcts = []
    for m in monthly:
        if "MTD" in str(m.get("month", "")):
            continue  # a partial month's ratio isn't comparable, same exclusion coo_operations_audit.py already applies
        if str(m.get("month", "")).strip() == str(target_month_label).strip():
            continue  # exclude the row being evaluated from its own baseline -- see docstring
        if _month_num_from_label(m.get("month")) == target_month_num:
            same_month_pcts.append(m["laborPct"])

    if not same_month_pcts:
        return base_pct, f"flat (unscaled) -- no PRIOR-year historical data for {_MONTH_NAMES[target_month_num-1]} (only the month being evaluated is on file)"

    hist_avg = sum(same_month_pcts) / len(same_month_pcts)
    threshold = round(hist_avg + buffer_pp, 4)
    n = len(same_month_pcts)
    return threshold, (f"{_MONTH_NAMES[target_month_num-1]}'s own historical average is "
                        f"{hist_avg*100:.1f}% (n={n} year{'s' if n != 1 else ''} of data"
                        f"{', thin sample' if n < 3 else ''}) + {buffer_pp*100:.0f}pp buffer")
