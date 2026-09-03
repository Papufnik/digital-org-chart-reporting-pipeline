import os
import json
from datetime import datetime

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.pattern_scan import scan_correlations
from lib.ledger_monthly_series import load_ledger_monthly_series

"""
cfo_executive_audit.py -- the CFO role in the Senior Manager layer
(see DIGITAL_ORG_CHART.md). Reads the financial analysts' live JSON output,
applies real thresholds, and surfaces what actually needs the operator's attention
this week. Wired into run_suite_refresh.py, runs automatically.

2026-08-11 REWRITE: this file already existed as a first attempt at the CFO
role, but audited before building anything further on top of it (per this
session's "trust but verify" pattern) -- every single field it read had a
schema-mismatch bug against the real JSON files:
  - GMROI: read `overall_gmroi`, real key is `overall`
  - Dead stock cost: read `totalDeadStockCost`, real key is `deadStockCost`
  - Cash runway: read a nested `ending_cash` dict that doesn't exist at all;
    the real file has flat `baseCaseDecCash`/`conservativeCaseDecCash` keys
  - Ordering allowance: tried `weekly_ordering_allowance` and
    `recommended_allowance`, real key is `recommendedAllowance`
  - MCA balance: read `current_balance`, real key is `currentBalance`
  - MCA weekly payment: HARDCODED as the literal string "$1,180.40/week"
    instead of reading the real `weeklyPayment` field sitting right there
    (Rule 1 violation) -- would have gone stale silently if the payment
    terms ever changed
  - Cross-sell: assumed `crossSellMetrics` was a list; it's actually a dict
    with `topAttachmentPairs` (a list) and `topPairDetail` inside it
Every one of these bugs defaults to 0.0/empty on failure (`.get(key, 0.0)`),
so nothing ever crashed or printed a warning -- this ran on every scheduled
refresh, wrote a JSON file, and every number in it was silently wrong the
entire time. Nothing downstream ever read the output file either, so this
was simultaneously broken AND dead code. All field names fixed below and
verified against the real files' actual keys before shipping this version.

Per the "surface facts, humans decide" model locked in this session:
recommendations are phrased as things worth considering, not directives to
execute, and are not assigned to fictional roles ("Ordering Manager", "Floor
Manager") that don't exist at a one-person department. This currently
reaches the operator only -- he decides what, if anything, goes to the owners.

2026-08-11 ADDITION -- "Patterns Worth a Look": the operator asked for the agents
to be able to find genuinely non-obvious relationships in the data, the way
a chess engine finds moves by checking combinations no human would bother
with -- NOT by having an LLM write speculative prose (that's exactly what
creative_data_insights_agent.py had to be rewritten to stop doing). The
real analog is systematic statistical search: pattern_scan.py runs Pearson
correlation across every pair of the ledger's real 16-month category
history (via ledger_monthly_series.py), at 0/1/2-month lags, with a hard
minimum-sample-size guardrail. This is CFO's domain because the ledger's
categories (income, labor, occupancy, inventory purchases, opex, financing)
ARE financial data -- COO's domain doesn't have persisted history yet to
do the same (see DIGITAL_ORG_CHART.md).

Two curated filters on top of the raw scan, both because a same-day POC run
against real data showed the raw results are dominated by one boring
finding repeated many ways -- almost everything correlates with revenue
because this is a small seasonal business and revenue drives scale
everywhere:
  1. Anything trivially explained by revenue (either side is INC-RETAIL or
     INC-ONLINE) is excluded from what's surfaced here -- it's real, but
     it's not a finding, it's "the store had a big month."
  2. Only relationships at or above CORRELATION_SURFACE_THRESHOLD are shown
     -- a proposal-level number, not a statistically rigorous cutoff.
Severity is always INFO, never CRITICAL/WARNING -- these are statistical
leads across a small sample, not verified facts, and must never carry the
same visual urgency as a real threshold breach. They never feed into
needsAttention for the same reason.

2026-08-18 -- seasonal threshold scaling considered and deliberately NOT
applied here (coo_operations_audit.py's revenue-scale thresholds were
scaled the same day, via seasonal_thresholds.py -- see that module's
header). None of this file's thresholds are good candidates for the same
treatment, for three different reasons:
  - Dead stock >$10,000 and GMROI >5.0x are stock-level/ratio measures,
    not a monthly revenue flow -- "how much capital is trapped right now"
    doesn't get less concerning just because this month is seasonally
    slow, the way "how much revenue did stockouts cost this month" does.
  - Conservative cash <$20,000 is actively backwards to scale the way
    revenue-multiplier scaling would: the low season (Jan multiplier
    0.32x) is exactly when MORE cash buffer is needed, not less, since
    that's when the business is burning down reserves rather than
    building them. A real seasonal cash floor would need a different
    model (e.g. months-of-runway-remaining against the forecast itself)
    than a simple multiplier, and hasn't been built -- flagged here
    rather than shipping something backwards.
  - The two Payment Integrity thresholds (POS fee-rate outlier,
    bank-vs-POS match) are data-integrity checks, not revenue-scale
    figures -- a discrepancy is exactly as concerning in July as January.
    (These two now live in controller_audit.py as of the same-day split
    below -- reasoning kept here since it was decided before the split.)

2026-08-18 (later same day) -- Payment Integrity split out to
controller_audit.py: per the operator's decision on DIGITAL_ORG_CHART.md's
"Controller vs. CFO split" open question ("two roles"), the POS fee-rate
outlier check and bank-vs-POS reconciliation that briefly lived in this
file's own "3. Payment Integrity" section (added earlier the same day) have
been moved, unchanged, to a new controller_audit.py -- a sibling Senior
Manager, not a CFO subsection. This file no longer loads
pos_payout_fee_audit_live.json or bank_pos_reconciliation_live.json.
ceo_weekly_memo.py now reads three Senior Managers, not two.
"""

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2, "OPTIMAL": 3}
CORRELATION_SURFACE_THRESHOLD = 0.6
PATTERN_MIN_OVERLAP_MONTHS = 10
REVENUE_CODES = {"INC-RETAIL", "INC-ONLINE"}
MAX_PATTERNS_SURFACED = 3


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


def run_cfo_audit():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    business_dir = os.path.abspath(os.path.join(base_dir, ".."))
    out_dir = os.path.join(business_dir, "dashboard_app")
    os.makedirs(out_dir, exist_ok=True)

    print(f"=== CFO Synthesis [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===")

    gmroi_data = load_json(os.path.join(out_dir, "gmroi_live.json"))
    cash_forecast = load_json(os.path.join(out_dir, "cash_forecast_live.json"))
    phantom_inv = load_json(os.path.join(out_dir, "phantom_inventory_live.json"))
    weekly_budget = load_json(os.path.join(out_dir, "weekly_budget_model.json"))
    basket_insights = load_json(os.path.join(out_dir, "pos_data_mining_insights.json"))
    wholesale_ap = load_json(os.path.join(out_dir, "wholesale_ap_schedule.json"))
    mca_payoff = load_json(os.path.join(out_dir, "mca_payoff_live.json"))
    # Dropped from this version: retail_item_cleanup_live.json (catalog
    # cleanup is COO/merchandising territory per DIGITAL_ORG_CHART.md, not
    # CFO) and dashboard_data.json (the already-aggregated master file --
    # reading it here would mean synthesizing a synthesis, not the source
    # analyst data). Neither was ever actually used in the prior version
    # either; removing the dead loads rather than leaving them unused.

    audit_timestamp = datetime.now().strftime("%B %d, %Y %H:%M")

    # -------------------------------------------------------------------
    # 1. Capital Efficiency
    # -------------------------------------------------------------------
    dead_stock_cost = phantom_inv.get("deadStockCost", 0.0) or 0.0
    dead_stock_count = phantom_inv.get("deadStockCount", 0) or 0
    overall_gmroi = gmroi_data.get("overall", 0.0) or 0.0

    capital_items = []
    if dead_stock_cost > 10000:
        capital_items.append({
            "severity": "CRITICAL",
            "title": "Trapped Capital in Dead Stock",
            "metric": f"${dead_stock_cost:,.2f}",
            "description": f"{dead_stock_count:,} SKUs have generated $0 in sales over the last 90 days, holding ${dead_stock_cost:,.2f} in working capital.",
            "worth_considering": "A targeted clearance or bundling pass on the slowest SKUs would free up cash currently sitting on shelves."
        })

    if overall_gmroi > 5.0:
        capital_items.append({
            "severity": "OPTIMAL",
            "title": "Strong Inventory Return (GMROI)",
            "metric": f"{overall_gmroi:.2f}x",
            "description": f"Annualized Gross Margin Return on Inventory is {overall_gmroi:.2f}x.",
            "worth_considering": "Current reorder buffer sizes for top-tier categories appear to be working -- no change indicated."
        })
    elif overall_gmroi > 0:
        capital_items.append({
            "severity": "WARNING",
            "title": "Moderate GMROI Performance",
            "metric": f"{overall_gmroi:.2f}x",
            "description": "Inventory return is moderate -- some slow-turning categories are weighing down the total.",
            "worth_considering": "Worth checking which categories are dragging the average down before the next open-to-buy decision."
        })

    # -------------------------------------------------------------------
    # 2. Cash, Debt & Terms
    # -------------------------------------------------------------------
    conservative_cash = cash_forecast.get("conservativeCaseDecCash")
    base_cash = cash_forecast.get("baseCaseDecCash")
    ordering_allowance = weekly_budget.get("recommendedAllowance", 0.0) or 0.0
    mca_balance = mca_payoff.get("currentBalance", 0.0) or 0.0
    mca_weekly_payment = mca_payoff.get("weeklyPayment")
    wholesale_ap_total = wholesale_ap.get("totalWholesaleAP")

    cash_items = []
    if conservative_cash is not None:
        cash_items.append({
            "severity": "WARNING" if conservative_cash < 20000 else "OPTIMAL",
            "title": "Cash Forecast (Conservative Case)",
            "metric": f"${conservative_cash:,.2f}",
            "description": (
                f"Projected cash at the end of the current 6-month forecast window, conservative case "
                f"(base case: ${base_cash:,.2f})."
            ),
            "worth_considering": "Below $20,000 conservative, the weekly ordering ceiling below is worth holding to strictly." if conservative_cash < 20000 else None,
        })
    else:
        cash_items.append({
            "severity": "INFO",
            "title": "Cash Forecast",
            "metric": "N/A (source missing)",
            "description": "cash_forecast_live.json is missing or unreadable -- run build_cash_forecast.py.",
            "worth_considering": None,
        })

    cash_items.append({
        "severity": "INFO",
        "title": "Weekly Ordering Allowance",
        "metric": f"${ordering_allowance:,.2f}/wk",
        "description": f"Recommended inventory spend ceiling for this week, based on seasonal revenue weighting: ${ordering_allowance:,.2f}.",
        "worth_considering": "Applies across the wholesale marketplace and direct vendor POs combined, not per-vendor.",
    })

    if wholesale_ap_total is not None:
        cash_items.append({
            "severity": "INFO",
            "title": "Wholesale Accounts Payable Outstanding",
            "metric": f"${wholesale_ap_total:,.2f}",
            "description": f"{wholesale_ap.get('totalSource', 'source unspecified')}.",
            "worth_considering": wholesale_ap.get("reconciliationNote"),
        })

    if mca_balance > 0:
        payment_str = f"${mca_weekly_payment:,.2f}/week" if mca_weekly_payment is not None else "an unknown weekly amount (source field missing)"
        cash_items.append({
            "severity": "INFO",
            "title": "MCA (merchant cash advance) Payoff",
            "metric": f"${mca_balance:,.2f}",
            "description": f"Remaining MCA debt balance, servicing at {payment_str}.",
            "worth_considering": "Factor the weekly auto-debit into cash buffer before placing large open-account vendor orders.",
        })

    # -------------------------------------------------------------------
    # 3. Basket & Merchandising Signal (CFO gets the summary; full detail
    #    is the COO's territory once that role exists)
    # -------------------------------------------------------------------
    merch_items = []
    cross_sell = basket_insights.get("crossSellMetrics")
    top_pairs = cross_sell.get("topAttachmentPairs") if isinstance(cross_sell, dict) else None
    if basket_insights.get("dataAvailable") and top_pairs:
        top = top_pairs[0]
        merch_items.append({
            "severity": "INFO",
            "title": "Top Basket Attachment",
            "metric": f"{top.get('attachmentRatePct', 0)}% attachment",
            "description": (
                f"Orders containing '{top.get('primaryCategory')}' show a {top.get('attachmentRatePct')}% "
                f"attachment rate with '{top.get('attachedCategory')}' ({top.get('ordersWithBoth')} of "
                f"{top.get('ordersWithPrimary')} orders)."
            ),
            "worth_considering": "Floor placement adjacent to each other could capitalize on this, if not already done.",
        })
    else:
        merch_items.append({
            "severity": "INFO",
            "title": "Basket Attachment Analytics",
            "metric": "N/A (source missing or not yet available)",
            "description": "pos_data_mining_insights.json has no cross-sell data available this run.",
            "worth_considering": None,
        })

    # -------------------------------------------------------------------
    # 4. Patterns Worth a Look (2026-08-11 addition -- see header comment)
    # -------------------------------------------------------------------
    pattern_items = []
    ledger_path = os.path.join(business_dir, "01 - Ledger & Chart of Accounts", "business_transaction_ledger.xlsx")
    if os.path.exists(ledger_path):
        try:
            months, ledger_series, ledger_labels = load_ledger_monthly_series(ledger_path)
            scan = scan_correlations(ledger_series, ledger_labels, min_overlap=PATTERN_MIN_OVERLAP_MONTHS, lags=(0, 1, 2))
            candidates = [
                r for r in scan["results"]
                if not r["sameDomain"]
                and r["a"] not in REVENUE_CODES and r["b"] not in REVENUE_CODES
                and abs(r["r"]) >= CORRELATION_SURFACE_THRESHOLD
            ]
            # Dedup by unordered category pair, keeping only the strongest
            # lag/direction per pair -- otherwise the same underlying
            # relationship (e.g. A-vs-B at lag 1 AND lag 2) can eat multiple
            # of the few slots surfaced, crowding out a genuinely different
            # finding underneath it.
            seen_pairs = set()
            deduped = []
            for res in candidates:
                pair_key = frozenset((res["a"], res["b"]))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                deduped.append(res)
            for res in deduped[:MAX_PATTERNS_SURFACED]:
                pattern_items.append({
                    "severity": "INFO",
                    "title": f"Statistical Lead: {res['a']} ↔ {res['b']}",
                    "metric": f"r={res['r']:+.2f} (n={res['n']} months)",
                    "description": res["description"],
                    "worth_considering": (
                        f"Found by scanning {scan['testsRun']} category-pair/lag combinations across "
                        f"{len(months)} months of real ledger history -- correlation, not proven causation, "
                        f"and a small sample besides. Worth a look if it keeps showing up on future refreshes, "
                        f"not something to act on from one run."
                    ),
                })
            if not pattern_items:
                pattern_items.append({
                    "severity": "INFO",
                    "title": "Statistical Pattern Scan",
                    "metric": f"{scan['resultsWithEnoughData']} testable, 0 above threshold",
                    "description": (
                        f"Scanned {scan['testsRun']} category-pair/lag combinations across {len(months)} months "
                        f"of ledger history; nothing non-revenue-driven cleared |r| >= {CORRELATION_SURFACE_THRESHOLD:.1f} this run."
                    ),
                    "worth_considering": None,
                })
        except Exception as e:
            print(f"[WARN] Pattern scan failed: {e}")
    else:
        print(f"[WARN] Missing source file: {ledger_path}")

    # -------------------------------------------------------------------
    # 5. Summary
    # -------------------------------------------------------------------
    all_items = capital_items + cash_items + merch_items
    all_items.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 9))
    critical_or_warning = [i for i in all_items if i["severity"] in ("CRITICAL", "WARNING")]

    summary_bullets = []
    summary_bullets.append(f"Trailing GMROI {overall_gmroi:.2f}x; ${dead_stock_cost:,.2f} in 90-day dead stock ({dead_stock_count:,} SKUs).")
    if conservative_cash is not None:
        summary_bullets.append(f"Conservative-case cash forecast ends the window at ${conservative_cash:,.2f}; weekly ordering ceiling ${ordering_allowance:,.2f}.")
    if wholesale_ap_total is not None:
        summary_bullets.append(f"${wholesale_ap_total:,.2f} outstanding on wholesale marketplace terms.")
    if mca_balance > 0:
        summary_bullets.append(f"MCA balance ${mca_balance:,.2f} remaining.")

    audit_payload = {
        "asOfDate": audit_timestamp,
        "audience": "the operator (not sent to owners directly -- he decides what to pass on)",
        "summary": summary_bullets,
        "needsAttention": critical_or_warning,
        "capitalEfficiency": capital_items,
        "cashDebtAndTerms": cash_items,
        "merchandisingSignal": merch_items,
        "patternsWorthALook": pattern_items,
    }

    out_file = os.path.join(out_dir, "cfo_executive_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, indent=2)

    # Readable console summary -- this currently reaches the operator by him running
    # the script and reading this, not by email (Phase 4 territory).
    print("\n--- CFO Synthesis: what needs attention ---")
    if critical_or_warning:
        for item in critical_or_warning:
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

    print(f"\n[SUCCESS] CFO synthesis written -> {out_file}")
    return audit_payload


if __name__ == "__main__":
    run_cfo_audit()

