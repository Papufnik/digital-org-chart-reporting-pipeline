import os
import json
from datetime import datetime, date

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.metrics_history import append_snapshot, load_history_series
from lib.pattern_scan import scan_correlations
from lib.seasonal_thresholds import seasonal_dollar_threshold, seasonal_labor_threshold

"""
coo_operations_audit.py -- the COO role in the Senior Manager layer
(see DIGITAL_ORG_CHART.md, Phase 2). Reads the operations-focused analysts'
live JSON output, applies real thresholds, and surfaces what actually needs
the operator's attention this week on the merchandising/inventory/staffing side.
Wired into run_suite_refresh.py, runs automatically after all the analysts
it reads from (see the ordering comment where it's added to that file).

2026-08-11: built following the same "verify real field names before writing
a single line" discipline that cfo_executive_audit.py's rewrite documented
being necessary for -- every JSON source below was inspected for its actual
top-level and nested keys before this file was written, not assumed from
script names or guessed:
  - inventory_velocity_live.json: deadStockCost/deadStockCount here are the
    SAME dead-stock figures cfo_executive_audit.py already reports from
    phantom_inventory_live.json (verified identical: $52,140.75 / 1,048 SKUs
    in both files as of this writing). Deliberately NOT re-reported here to
    avoid two Senior Managers printing the same number from two files --
    that's exactly the "two competing sources of truth" anti-pattern this
    codebase has been burned by before. This script instead surfaces the
    velocity-specific figures the CFO doesn't: missedSales30Days and
    oosDemandCount (revenue actually lost to being out of stock, which is
    a distinct number from capital tied up in stock that isn't moving).
  - stockout_alerts_live.json: top-level is
    totalMonitoredSKUs/atRiskStockoutSKUs/urgentStockouts (list); each
    urgent item has estimatedPOCost, not a pre-summed total.
  - markdown_optimization_live.json: totalCapitalTiedUp and
    totalSlowMovingSKUs are top-level; NOT the same capital figure as dead
    stock (markdown candidates still have some velocity, dead stock has
    none -- confirmed the two totals differ in the source data).
  - vendor_roi_live.json: overallMarkup is a proxy metric
    (isProxyMetric: true, per the file's own flag -- surfaced honestly
    here rather than presented as a hard number). bottomVendors is a list
    of dicts with a `markup` field, not pre-flagged as good/bad.
  - margin_erosion_alerts.json: this file is only refreshed when
    margin_erosion_agent.py runs, which currently happens inline inside
    daily_email_dispatcher.py -- NOT as its own step in
    run_suite_refresh.py's build_steps list. That means by the time this
    script runs during a suite refresh, this file may be up to one day
    stale. Rather than silently trust it (Rule 5), this script explicitly
    checks the file's own `asOfDate` against today's date and labels the
    figure as stale if they don't match, same pattern used in
    pos_payout_fee_auditor.py's staleness flag.
  - labor_efficiency_live.json: monthlyLaborPct is a list of
    {month, netSales, labor, laborPct} dicts ordered oldest-to-newest; the
    last entry is frequently a partial/MTD month (its `month` label says
    so, e.g. "Jul '26 (MTD thru 8/9)") and is excluded from threshold
    checks for that reason -- a partial month's labor % is not comparable
    to a full month's.
  - petty_cash_analysis_live.json: unreconciledGap and ledgerGapFlag (a plain
    sentence, not a boolean, despite the name) are top-level.
  - tourist_weather_forecast_live.json: sevenDayForecast is a list of
    daily dicts with trafficIndex (float) and staffingRecommendation (a
    plain-language string already written by tourist_weather_forecasting_
    agent.py -- passed through here, not re-derived).
  - discount_elasticity_live.json: overallDiscountRatePct and correlation
    (discount rate vs. units sold, -1 to 1) are top-level;
    topCategoriesByDiscountRate is a list of {category, discount, gross,
    ratePct} dicts.

Per the "surface facts, humans decide" model locked in this session:
recommendations are phrased as things worth considering, not directives to
execute. Every numeric threshold below is a starting proposal grounded in
the real data on file today, not an assertion of business fact -- flagged
as such in the header of each section, same convention as
cfo_executive_audit.py. This currently reaches the operator only.

2026-08-18 ADDITION -- seasonal threshold scaling: the three dollar/percent
thresholds that represent revenue-scale operational activity (missed sales
from stockouts, capital tied up in slow-moving stock, labor as % of net
sales) now scale by calendar month instead of using one flat number
year-round, via seasonal_thresholds.py. Rationale: this business runs at
0.32x an average month in January and 2.16x in July (real 4-year blended
index, historical_sales_patterns_live.json) -- a flat $25,000 "lost
sales" WARNING is nearly meaningless in July and overly aggressive in
January. Labor % is scaled differently (own-month historical average +
buffer, not a revenue multiplier) since it's already a ratio -- see that
module's header for why. Deliberately NOT applied to ratio/integrity
thresholds in this file (AT_RISK_STOCKOUT_PCT_WARNING, VENDOR_MARKUP_
WARNING, DISCOUNT_CORRELATION_WEAK) -- those aren't revenue-scale
problems. Every scaled threshold's `thresholdNote` states the base value,
the scaling method, and the resulting number actually applied this run,
so nothing is scaled silently.

2026-08-11 ADDITION -- history logging + pattern scan: cfo_executive_audit.py
got a "Patterns Worth a Look" section reading the real 16-month ledger
history via pattern_scan.py. COO can't do the same yet, because nothing in
its domain (inventory_velocity_live.json, stockout_alerts_live.json, etc.)
has ANY persisted history -- every one of those files gets overwritten on
every refresh. Per the operator's request that each agent be able to do this
independently, this script now appends a snapshot of its own key numeric
findings to dashboard_app/coo_metrics_history.csv (via metrics_history.py)
every time it runs, and runs the same pattern_scan.py search across
whatever history has accumulated so far. Idempotent by date -- reruns on
the same day overwrite that day's row rather than duplicating it. This
will report "not enough history yet" for a long stretch, honestly, since
it starts from zero real rows today and only grows one row per actual
pipeline run -- there is no shortcut to a real time series that doesn't
exist yet, and nothing here fabricates one.
"""

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2, "OPTIMAL": 3}

# Threshold assumptions -- starting proposals, not settled business
# judgment. Flagged individually below wherever they're applied.
# NOTE 2026-08-18: MISSED_SALES_CRITICAL/WARNING, MARKDOWN_CAPITAL_WARNING,
# and FULL_MONTH_LABOR_PCT_WARNING below are BASE values for an "average"
# month -- run_coo_audit() scales each to the actual current/target month
# via seasonal_thresholds.py before using it. See header comment.
MISSED_SALES_CRITICAL = 50000.0
MISSED_SALES_WARNING = 25000.0
AT_RISK_STOCKOUT_PCT_WARNING = 25.0
MARKDOWN_CAPITAL_WARNING = 50000.0
VENDOR_MARKUP_WARNING = 1.5
FULL_MONTH_LABOR_PCT_WARNING = 0.35
DISCOUNT_CORRELATION_WEAK = 0.10

# Pattern-scan-over-time config (2026-08-11 addition -- see header comment
# below the imports and the "5. Patterns Worth a Look" section for why this
# exists and what it will and won't show for a while).
COO_HISTORY_MIN_OVERLAP_RUNS = 10
COO_PATTERN_SURFACE_THRESHOLD = 0.6
MAX_COO_PATTERNS_SURFACED = 3


def load_json(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[WARN] Failed to load {filepath}: {e}")
    else:
        print(f"[WARN] Missing source file: {filepath}")
    return {}


def run_coo_audit():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    business_dir = os.path.abspath(os.path.join(base_dir, ".."))
    out_dir = os.path.join(business_dir, "dashboard_app")
    os.makedirs(out_dir, exist_ok=True)

    print(f"=== COO Synthesis [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===")

    inv_velocity = load_json(os.path.join(out_dir, "inventory_velocity_live.json"))
    stockouts = load_json(os.path.join(out_dir, "stockout_alerts_live.json"))
    markdown = load_json(os.path.join(out_dir, "markdown_optimization_live.json"))
    vendor_roi = load_json(os.path.join(out_dir, "vendor_roi_live.json"))
    margin_erosion = load_json(os.path.join(out_dir, "margin_erosion_alerts.json"))
    labor = load_json(os.path.join(out_dir, "labor_efficiency_live.json"))
    petty_cash = load_json(os.path.join(out_dir, "petty_cash_analysis_live.json"))
    weather = load_json(os.path.join(out_dir, "tourist_weather_forecast_live.json"))
    discount = load_json(os.path.join(out_dir, "discount_elasticity_live.json"))

    audit_timestamp = datetime.now().strftime("%B %d, %Y %H:%M")
    current_month_num = datetime.now().month

    # Seasonal scaling (2026-08-18) -- see header comment and
    # seasonal_thresholds.py for the method. Computed once here, applied
    # below wherever the base constants used to be used directly.
    missed_sales_warning_scaled, missed_sales_warning_note = seasonal_dollar_threshold(out_dir, MISSED_SALES_WARNING, current_month_num)
    missed_sales_critical_scaled, missed_sales_critical_note = seasonal_dollar_threshold(out_dir, MISSED_SALES_CRITICAL, current_month_num)
    markdown_capital_warning_scaled, markdown_capital_warning_note = seasonal_dollar_threshold(out_dir, MARKDOWN_CAPITAL_WARNING, current_month_num)

    # -------------------------------------------------------------------
    # 1. Inventory & Reorder Urgency
    # -------------------------------------------------------------------
    inventory_items = []

    missed_sales = inv_velocity.get("missedSales30Days")
    oos_demand = inv_velocity.get("oosDemandCount")
    if missed_sales is not None:
        if missed_sales > missed_sales_critical_scaled:
            sev = "CRITICAL"
        elif missed_sales > missed_sales_warning_scaled:
            sev = "WARNING"
        else:
            sev = "INFO"
        inventory_items.append({
            "severity": sev,
            "title": "Revenue Lost to Stockouts (Trailing 30 Days)",
            "metric": f"${missed_sales:,.2f}",
            "description": f"Estimated ${missed_sales:,.2f} in demand went unmet over the last 30 days because {oos_demand:,} instances of demand hit an out-of-stock item." if oos_demand else f"Estimated ${missed_sales:,.2f} in demand went unmet over the last 30 days due to out-of-stock items.",
            "worth_considering": "The urgent-stockout list below is the near-term fix for the biggest piece of this -- reordering those first would claw back the most missed revenue per dollar spent.",
            # Methodology caveat, kept out of the reader-facing fields above
            # (worth_considering is meant for business framing, not an
            # internal audit trail -- see coo_operations_audit.py header).
            "thresholdNote": (
                f"WARNING above ${missed_sales_warning_scaled:,.0f}, CRITICAL above ${missed_sales_critical_scaled:,.0f} this month "
                f"(base ${MISSED_SALES_WARNING:,.0f}/${MISSED_SALES_CRITICAL:,.0f}, {missed_sales_warning_note}) -- a starting proposal, not a settled number."
            ),
        })

    total_monitored = stockouts.get("totalMonitoredSKUs")
    at_risk = stockouts.get("atRiskStockoutSKUs")
    urgent = stockouts.get("urgentStockouts", [])
    at_risk_pct = 0.0
    urgent_po_cost = 0.0
    if total_monitored:
        at_risk_pct = (at_risk / total_monitored * 100) if at_risk else 0.0
        urgent_po_cost = sum(x.get("estimatedPOCost", 0) or 0 for x in urgent)
        inventory_items.append({
            "severity": "WARNING" if at_risk_pct > AT_RISK_STOCKOUT_PCT_WARNING else "INFO",
            "title": "Stockout Risk Across Catalog",
            "metric": f"{at_risk_pct:.1f}% of monitored SKUs",
            "description": f"{at_risk:,} of {total_monitored:,} monitored SKUs are at risk of stocking out; {len(urgent)} are flagged urgent, with a combined estimated reorder cost of ${urgent_po_cost:,.2f}.",
            "worth_considering": "The urgent list is the near-term reorder candidate set -- worth a look before the next PO batch." if urgent else None,
        })

    # -------------------------------------------------------------------
    # 2. Margin & Vendor Signal
    # -------------------------------------------------------------------
    margin_vendor_items = []

    slow_moving = markdown.get("totalSlowMovingSKUs")
    capital_tied = markdown.get("totalCapitalTiedUp")
    if capital_tied is not None:
        margin_vendor_items.append({
            "severity": "WARNING" if capital_tied > markdown_capital_warning_scaled else "INFO",
            "title": "Capital Tied Up in Slow-Moving (Not Dead) Stock",
            "metric": f"${capital_tied:,.2f}",
            "description": f"{slow_moving:,} SKUs are still selling but slowly enough to be markdown candidates, holding ${capital_tied:,.2f} in capital. This is separate from the dead-stock figure in the CFO synthesis -- these items still have some velocity.",
            "worth_considering": "A markdown pass on the slowest of these would free up cash before it becomes dead stock outright.",
            "thresholdNote": (
                f"WARNING above ${markdown_capital_warning_scaled:,.0f} this month (base ${MARKDOWN_CAPITAL_WARNING:,.0f}, "
                f"{markdown_capital_warning_note}) -- a starting proposal, not a settled number."
            ),
        })

    overall_markup = vendor_roi.get("overallMarkup")
    is_proxy = vendor_roi.get("isProxyMetric")
    bottom_vendors = vendor_roi.get("bottomVendors", [])
    low_markup_vendors = [v for v in bottom_vendors if (v.get("markup") or 99) < VENDOR_MARKUP_WARNING]
    if overall_markup is not None:
        desc = f"Overall wholesale-to-retail markup is {overall_markup:.2f}x"
        if is_proxy:
            desc += ", flagged by the source data itself as a proxy rather than an exact figure"
        if bottom_vendors:
            desc += f". Lowest-markup vendor on file: {bottom_vendors[0]['name']} at {bottom_vendors[0]['markup']:.2f}x."
        else:
            desc += "."
        margin_vendor_items.append({
            "severity": "WARNING" if low_markup_vendors else "INFO",
            "title": "Vendor Markup Health",
            "metric": f"{overall_markup:.2f}x overall" + (" (proxy metric)" if is_proxy else ""),
            "description": desc,
            "worth_considering": f"{len(low_markup_vendors)} vendor(s) below {VENDOR_MARKUP_WARNING:.2f}x -- worth a pricing review on those lines." if low_markup_vendors else None,
        })

    total_alerts = margin_erosion.get("totalAlerts")
    as_of_date_str = margin_erosion.get("asOfDate")
    is_stale = None
    if as_of_date_str:
        try:
            parsed = datetime.strptime(as_of_date_str, "%B %d, %Y").date()
            is_stale = parsed != date.today()
        except ValueError:
            is_stale = None
    top_anomalies = margin_erosion.get("topAnomalies", [])
    cost_impact = sum(a.get("cost_increase_amt", 0) or 0 for a in top_anomalies)
    if total_alerts is not None:
        desc = (
            f"{total_alerts} SKU(s) flagged for a wholesale cost increase not yet reflected in the POS platform's cost field, "
            f"~${cost_impact:,.2f}/unit combined margin impact. This is a passthrough summary, not new analysis -- "
            f"full detail already reaches the operator daily via margin_erosion_agent.py."
        )
        if is_stale:
            desc += f" NOTE: this figure is dated {as_of_date_str}, not today -- margin_erosion_agent.py only refreshes when daily_email_dispatcher.py runs, not as part of this suite refresh, so it may be up to a day old."
        margin_vendor_items.append({
            "severity": "INFO",
            "title": "Margin Erosion Alerts (Already in Daily Email)",
            "metric": f"{total_alerts} alert(s)",
            "description": desc,
            "worth_considering": None,
        })

    # -------------------------------------------------------------------
    # 3. Staffing & Traffic Outlook
    # -------------------------------------------------------------------
    staffing_items = []

    overtime_pct = labor.get("overtimeRatePct")
    monthly_labor = labor.get("monthlyLaborPct", [])
    full_months = [m for m in monthly_labor if "MTD" not in str(m.get("month", ""))]
    latest_full_month = full_months[-1] if full_months else None
    if latest_full_month:
        pct = latest_full_month.get("laborPct", 0) or 0
        month_label = latest_full_month.get("month")
        labor_threshold_scaled, labor_threshold_note = seasonal_labor_threshold(out_dir, FULL_MONTH_LABOR_PCT_WARNING, month_label)
        desc = f"Labor ran {pct*100:.1f}% of net sales in {month_label}."
        if overtime_pct is not None:
            desc += f" Overtime rate {overtime_pct:.1f}% of hours this window."
        labor_item = {
            "severity": "WARNING" if pct > labor_threshold_scaled else "INFO",
            "title": "Labor as % of Net Sales (Latest Complete Month)",
            "metric": f"{pct*100:.1f}% ({month_label})",
            "description": desc,
            "worth_considering": "Worth checking whether this month had a scheduling or staffing-level anomaly, given it's already running above what this same month has historically run, not just above a flat year-round number." if pct > labor_threshold_scaled else None,
        }
        if pct > labor_threshold_scaled:
            labor_item["thresholdNote"] = (
                f"WARNING above {labor_threshold_scaled*100:.1f}% for {month_label.split()[0]} specifically "
                f"({labor_threshold_note}) -- replaces the old flat {FULL_MONTH_LABOR_PCT_WARNING*100:.0f}% "
                f"year-round cutoff, itself a starting proposal, not a settled number."
            )
        staffing_items.append(labor_item)

    unreconciled_gap = petty_cash.get("unreconciledGap")
    ledger_gap_flag = petty_cash.get("ledgerGapFlag")
    if unreconciled_gap is not None and unreconciled_gap > 0:
        staffing_items.append({
            "severity": "INFO",
            "title": "Petty Cash Staff-Reported vs. Bank-Traceable Gap",
            "metric": f"${unreconciled_gap:,.2f}",
            "description": ledger_gap_flag or f"${unreconciled_gap:,.2f} of staff-reported petty cash spend isn't yet traceable to a bank transaction.",
            "worth_considering": None,
        })

    surge_days = [
        d for d in weather.get("sevenDayForecast", [])
        if "SURGE" in str(d.get("staffingRecommendation", "")).upper()
    ]
    if surge_days:
        staffing_items.append({
            "severity": "INFO",
            "title": "Upcoming High-Traffic Days (Next 7 Days)",
            "metric": f"{len(surge_days)} day(s) flagged",
            "description": "; ".join(f"{d.get('date')}: {d.get('staffingRecommendation')}" for d in surge_days),
            "worth_considering": "Worth confirming the schedule covers these before they arrive.",
        })

    # -------------------------------------------------------------------
    # 4. Pricing / Discount Health
    # -------------------------------------------------------------------
    pricing_items = []
    discount_rate = discount.get("overallDiscountRatePct")
    correlation = discount.get("correlation")
    top_discount_cats = discount.get("topCategoriesByDiscountRate", [])
    if discount_rate is not None and correlation is not None:
        weak = abs(correlation) < DISCOUNT_CORRELATION_WEAK
        top_cat_desc = ""
        if top_discount_cats:
            tc = top_discount_cats[0]
            top_cat_desc = f" Highest discount-rate category: {tc.get('category')} at {tc.get('ratePct')}%."
        pricing_items.append({
            "severity": "INFO",
            "title": "Discount Rate vs. Sales Volume Correlation",
            "metric": f"{discount_rate:.2f}% discounted, correlation {correlation:.3f}",
            "description": f"{discount_rate:.2f}% of gross is discounted; the correlation between discount depth and units sold is {correlation:.3f} (near zero to weak)." + top_cat_desc,
            "worth_considering": "Discounting doesn't appear to be meaningfully driving extra volume in this data -- worth questioning whether current discount levels are earning their keep, particularly in the highest-discount category above." if weak else None,
        })

    # -------------------------------------------------------------------
    # 5. Patterns Worth a Look (History-Based) -- 2026-08-11 addition,
    # see header comment above for why this is new/different from CFO's
    # version and why it'll be empty for a while.
    # -------------------------------------------------------------------
    pattern_items = []
    history_path = os.path.join(out_dir, "coo_metrics_history.csv")
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Only log real, already-computed numbers -- None where a source was
    # missing, never a fabricated 0 (same zero-fill lesson as
    # creative_data_insights_agent.py).
    snapshot_metrics = {
        "missedSales30Days": missed_sales,
        "atRiskStockoutPct": at_risk_pct if total_monitored else None,
        "urgentReorderCost": urgent_po_cost if total_monitored else None,
        "markdownCapitalTied": capital_tied,
        "slowMovingSkuCount": slow_moving,
        "overallVendorMarkup": overall_markup,
        "marginErosionAlertCount": total_alerts,
        "laborPctLatestFullMonth": latest_full_month.get("laborPct") if latest_full_month else None,
        "overtimeRatePct": overtime_pct,
        "pettyCashUnreconciledGap": unreconciled_gap,
        "highTrafficDayCount": len(surge_days),
        "discountRatePct": discount_rate,
        "discountVolumeCorrelation": correlation,
    }
    try:
        append_snapshot(history_path, today_str, snapshot_metrics)
        dates, history_series = load_history_series(history_path)
        scan = scan_correlations(history_series, min_overlap=COO_HISTORY_MIN_OVERLAP_RUNS, lags=(0,))
        candidates = [r for r in scan["results"] if abs(r["r"]) >= COO_PATTERN_SURFACE_THRESHOLD]
        seen_pairs, deduped = set(), []
        for res in candidates:
            pair_key = frozenset((res["a"], res["b"]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            deduped.append(res)
        for res in deduped[:MAX_COO_PATTERNS_SURFACED]:
            pattern_items.append({
                "severity": "INFO",
                "title": f"Statistical Lead: {res['a']} ↔ {res['b']}",
                "metric": f"r={res['r']:+.2f} (n={res['n']} runs)",
                "description": res["description"],
                "worth_considering": (
                    f"Found by scanning {scan['testsRun']} metric-pair combinations across "
                    f"{len(dates)} logged pipeline runs -- correlation, not proven causation, "
                    f"and a small/growing sample. Worth a look if it persists on future refreshes."
                ),
            })
        if not pattern_items:
            pattern_items.append({
                "severity": "INFO",
                "title": "Statistical Pattern Scan (History Still Building)",
                "metric": f"{len(dates)} run(s) logged so far, need {COO_HISTORY_MIN_OVERLAP_RUNS}+ before anything can be tested",
                "description": (
                    f"This is run #{len(dates)} to log history. Once at least {COO_HISTORY_MIN_OVERLAP_RUNS} "
                    f"real pipeline runs have accumulated, this section will start searching for genuine "
                    f"cross-metric patterns the same way the CFO synthesis already does against the ledger."
                ),
                "worth_considering": None,
            })
    except Exception as e:
        print(f"[WARN] History logging/pattern scan failed: {e}")

    # -------------------------------------------------------------------
    # 6. Summary
    # -------------------------------------------------------------------
    all_items = inventory_items + margin_vendor_items + staffing_items + pricing_items
    all_items.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 9))
    needs_attention = [i for i in all_items if i["severity"] in ("CRITICAL", "WARNING")]

    summary_bullets = []
    if missed_sales is not None:
        summary_bullets.append(f"${missed_sales:,.2f} in estimated lost sales from stockouts over the trailing 30 days.")
    if total_monitored:
        summary_bullets.append(f"{at_risk:,} of {total_monitored:,} SKUs ({at_risk_pct:.1f}%) at stockout risk; {len(urgent)} urgent, ~${urgent_po_cost:,.2f} to reorder.")
    if capital_tied is not None:
        summary_bullets.append(f"${capital_tied:,.2f} tied up in {slow_moving:,} slow-moving (not dead) SKUs.")
    if latest_full_month:
        summary_bullets.append(f"Labor ran {latest_full_month.get('laborPct',0)*100:.1f}% of net sales in {latest_full_month.get('month')}.")
    if surge_days:
        summary_bullets.append(f"{len(surge_days)} high-traffic day(s) in the next 7 days worth confirming staffing for.")

    audit_payload = {
        "asOfDate": audit_timestamp,
        "audience": "the operator (not sent to owners directly -- he decides what to pass on)",
        "summary": summary_bullets,
        "needsAttention": needs_attention,
        "inventoryAndReorder": inventory_items,
        "marginAndVendor": margin_vendor_items,
        "staffingAndTraffic": staffing_items,
        "pricingHealth": pricing_items,
        "patternsWorthALook": pattern_items,
    }

    out_file = os.path.join(out_dir, "coo_operations_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, indent=2)

    print("\n--- COO Synthesis: what needs attention ---")
    if needs_attention:
        for item in needs_attention:
            print(f"[{item['severity']}] {item['title']}: {item['metric']}")
            print(f"    {item['description']}")
            if item.get("worth_considering"):
                print(f"    Worth considering: {item['worth_considering']}")
    else:
        print("Nothing crossed a CRITICAL/WARNING threshold this run.")
    print("--- Full summary ---")
    for b in summary_bullets:
        print(f"  - {b}")
    print("--- Patterns worth a look (statistical leads, not verified facts) ---")
    for item in pattern_items:
        print(f"  {item['title']}: {item['metric']}")
        print(f"    {item['description']}")

    print(f"\n[SUCCESS] COO synthesis written -> {out_file}")
    return audit_payload


if __name__ == "__main__":
    run_coo_audit()

