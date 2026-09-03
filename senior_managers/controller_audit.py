import os
import json
from datetime import datetime

"""
controller_audit.py -- the Controller role in the Senior Manager layer
(see DIGITAL_ORG_CHART.md, Layer 3), split out from cfo_executive_audit.py
on 2026-08-18 per the operator's decision on the doc's own "Controller vs. CFO
split" open question: two roles, not one.

SCOPE, stated honestly rather than aspirationally: books/payment-integrity
work only, and only the two pieces that actually have a live analyst
feeding them today --
  - POS processing fee-rate outlier check (pos_payout_fee_auditor.py) --
    the POS platform's own self-reported blended rate vs. an alert threshold.
  - Bank-vs-POS payout reconciliation (bank_pos_reconciliation_analyst.py,
    built 2026-08-18) -- whether every POS payout has a matching bank
    deposit and vice versa.
This is the exact same logic that used to live in cfo_executive_audit.py's
"3. Payment Integrity" section (added there 2026-08-18, moved here the same
day once the two-role decision was made) -- moved, not rewritten, so the
severity/threshold behavior is unchanged, just now under its own role.

The doc's open-gap note also floated "tax package status" and "ledger
health" as things that might belong under a Controller once there's more
of it. NEITHER has a live analyst producing real data today -- rather than
stub those out with fabricated placeholders, this file only covers what's
actually real right now (Rule 1/Rule 8: don't assert what isn't backed by
real data). Add them here when/if those analysts get built.

Wired into run_suite_refresh.py immediately after
bank_pos_reconciliation_analyst.py (its source data), and before
ceo_weekly_memo.py (which now reads CFO, COO, AND Controller).
"""

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2, "OPTIMAL": 3}


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


def run_controller_audit():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    business_dir = os.path.abspath(os.path.join(base_dir, ".."))
    out_dir = os.path.join(business_dir, "dashboard_app")
    os.makedirs(out_dir, exist_ok=True)

    print(f"=== Controller Synthesis [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===")

    payout_fee_audit = load_json(os.path.join(out_dir, "pos_payout_fee_audit_live.json"))
    bank_recon = load_json(os.path.join(out_dir, "bank_pos_reconciliation_live.json"))

    audit_timestamp = datetime.now().strftime("%B %d, %Y %H:%M")

    # -------------------------------------------------------------------
    # Books & Payment Integrity -- moved verbatim from cfo_executive_audit.py
    # -------------------------------------------------------------------
    integrity_items = []
    fee_rate = payout_fee_audit.get("last30DaysMetrics", {}).get("blendedFeeRatePct")
    fee_anomalies = payout_fee_audit.get("anomalies") or []
    fee_threshold = payout_fee_audit.get("feeAlertThresholdPct")
    if fee_rate is not None:
        integrity_items.append({
            "severity": "WARNING" if fee_anomalies else "INFO",
            "title": "POS Processing Fee Rate (Trailing 30 Days)",
            "metric": f"{fee_rate:.2f}%",
            "description": f"Blended rate across the last 30 days of POS payouts on file"
                            + (f" -- {len(fee_anomalies)} day(s) exceeded the {fee_threshold}% alert threshold."
                               if fee_anomalies else ", no outlier days."),
            "worth_considering": "Worth a look at the specific flagged day(s) in the POS payout export." if fee_anomalies else None,
        })
    else:
        integrity_items.append({
            "severity": "INFO",
            "title": "POS Processing Fee Rate",
            "metric": "N/A (source missing)",
            "description": "pos_payout_fee_audit_live.json is missing -- run pos_payout_fee_auditor.py.",
            "worth_considering": None,
        })

    match_rate = bank_recon.get("matchRatePct")
    pos_unmatched = bank_recon.get("totalPosUnmatched", 0.0) or 0.0
    bank_unmatched = bank_recon.get("totalBankUnmatched", 0.0) or 0.0
    if match_rate is not None:
        recon_severity = "CRITICAL" if pos_unmatched > 0 else ("WARNING" if bank_unmatched > 200 else "OPTIMAL")
        integrity_items.append({
            "severity": recon_severity,
            "title": "Bank-vs-POS Payout Reconciliation",
            "metric": f"{match_rate}% matched",
            "description": f"Of ${bank_recon.get('totalPosNetPayouts', 0):,.2f} in POS payouts "
                            f"({bank_recon.get('posExportWindow', {}).get('start')} to "
                            f"{bank_recon.get('posExportWindow', {}).get('end')}), "
                            f"${pos_unmatched:,.2f} has no matching bank deposit and "
                            f"${bank_unmatched:,.2f} in bank deposits aren't explained by a POS payout."
                            + (" POS export is stale -- see console warning." if bank_recon.get("posExportStale") else ""),
            "worth_considering": "Check the specific unmatched dates in bank_pos_reconciliation_live.json before assuming anything is actually missing." if (pos_unmatched > 0 or bank_unmatched > 200) else None,
        })
    else:
        integrity_items.append({
            "severity": "INFO",
            "title": "Bank-vs-POS Payout Reconciliation",
            "metric": "N/A (source missing)",
            "description": "bank_pos_reconciliation_live.json is missing -- run bank_pos_reconciliation_analyst.py.",
            "worth_considering": None,
        })

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    all_items = list(integrity_items)
    all_items.sort(key=lambda x: SEVERITY_ORDER.get(x["severity"], 9))
    needs_attention = [i for i in all_items if i["severity"] in ("CRITICAL", "WARNING")]

    summary_bullets = []
    if fee_rate is not None:
        summary_bullets.append(f"POS blended processing fee rate {fee_rate:.2f}% over the trailing 30 days" + (f", {len(fee_anomalies)} outlier day(s)." if fee_anomalies else ", no outliers."))
    if match_rate is not None:
        summary_bullets.append(f"Bank-vs-POS reconciliation {match_rate}% matched; ${pos_unmatched:,.2f} unmatched POS, ${bank_unmatched:,.2f} unmatched bank.")

    audit_payload = {
        "asOfDate": audit_timestamp,
        "audience": "the operator (not sent to owners directly -- he decides what to pass on)",
        "scopeNote": (
            "Books/payment-integrity only, limited to what has a live analyst today: POS fee-rate "
            "outlier check and bank-vs-POS reconciliation. Tax package status and ledger health are "
            "NOT covered -- no analyst produces that data yet."
        ),
        "summary": summary_bullets,
        "needsAttention": needs_attention,
        "booksAndPaymentIntegrity": integrity_items,
    }

    out_file = os.path.join(out_dir, "controller_audit.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(audit_payload, f, indent=2)

    print("\n--- Controller Synthesis: what needs attention ---")
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

    print(f"\n[SUCCESS] Controller synthesis written -> {out_file}")
    return audit_payload


if __name__ == "__main__":
    run_controller_audit()
