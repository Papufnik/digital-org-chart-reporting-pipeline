import os
import json
from datetime import datetime

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.validate_narrative_numbers import collect_allowed_numbers_from_data, check_narrative

"""
ceo_weekly_memo.py -- the CEO capstone in the C-Suite layer (Layer 4, see
DIGITAL_ORG_CHART.md Phase 3). Reads all THREE Senior Managers' output
(cfo_executive_audit.json, coo_operations_audit.json, controller_audit.json),
picks the handful of things that actually matter this week, and writes them
up as a short, plain-language memo -- the "brilliant AND accessible"
artifact OPERATOR_BRIEFING.md's philosophy section describes ("Dirty Loops,
not Jacob Collier... Nobody logs into a dashboard they didn't ask for").

2026-08-18 ADDITION -- third Senior Manager: per the operator's decision on the
org chart's "Controller vs. CFO split" open question ("two roles"), Payment
Integrity (POS fee-rate outlier, bank-vs-POS reconciliation) moved out
of cfo_executive_audit.py into its own controller_audit.py the same day.
This script now reads three Senior Managers, not two. Unlike CFO/COO
(required -- this script refuses to write a memo without both), Controller
is read leniently: if controller_audit.json is missing, its watch items are
simply absent rather than blocking the whole memo, since it's the newest of
the three and shouldn't be a single point of failure for the memo the operator
actually reads every week.

Design notes (2026-08-11):
  - Per the org chart's Layer 4 design, this reads each Senior Manager's
    already-filtered `needsAttention` list rather than re-deriving priority
    from their raw category sections -- the CFO, COO, and Controller
    scripts already did the "does this cross a threshold" judgment call;
    re-doing it here would just be a second, possibly-inconsistent opinion
    on the same facts.
  - ONE deliberate, narrow exception: this script also reads
    cash_forecast_live.json (a Layer 2 analyst file, not a Senior Manager's
    output) directly for a single figure -- trailing-12-month revenue growth
    trend -- because neither Senior Manager's JSON currently carries that
    number, and "is the business growing" is exactly the kind of framing
    fact a business owner needs before reading a list of watch items, not
    after. Documented here rather than silently reaching past the layering.
  - Per the locked "templated, not LLM-authored" decision, every sentence
    below is an f-string built from real fields already present in the two
    Senior Manager JSONs (their own `description`/`worth_considering`
    fields, verbatim or lightly stitched) -- nothing here is generated or
    paraphrased by a model. If a field is missing, the sentence referencing
    it is simply omitted (fail honest, not fabricate -- Rule 8).
  - Per "surface facts, humans decide": this memo states what's true and
    why it matters, and explicitly does NOT issue directives. No section
    tells the owners or the operator what to DO -- each watch item just carries
    forward whatever "worth considering" language its Senior Manager already
    wrote, and the memo closes by handing the decision back to the operator.
  - Output is deliberately BOTH a structured JSON (ceo_weekly_memo.json, for
    any future automation) and a plain-text memo (ceo_weekly_memo.md) --
    the .md file is the actual reader-facing artifact per the operator's original
    ask for "reports in mostly written form." Phase 4 (how/whether this
    reaches an inbox) is still undecided -- for now this reaches the operator only,
    as a file in dashboard_app/ he can open.

2026-08-12 ADDITION -- optional narrative layer: the operator asked for genuinely
connective prose, not just a bulleted fact list, and gave the go-ahead to
try a bounded LLM narrative step on top of the (unchanged) verified facts
below. This is the ONE narrow, deliberate exception to "templated, not
LLM-authored" in this whole suite, and it's bounded on purpose:
  - The model (Haiku -- this is synthesis over already-verified facts, not
    a task that needs a heavier one) NEVER computes or looks up a number.
    It's handed the same facts already assembled below (framing_lines,
    watch_items, positive_note) as its only source material.
  - Every number in what it writes gets checked against those same facts
    by validate_narrative_numbers.check_narrative() before it's trusted.
    Anything that doesn't match gets the whole narrative discarded, full
    stop -- no partial-trust, no "close enough."
  - The prompt requires interpretive/causal claims to be marked inline as
    "[READ, NOT FACT: ...]" -- the same convention from the chat sample
    the operator approved, so a reader can always tell a computed fact from a
    read on it.
  - On ANY failure -- no ANTHROPIC_API_KEY set, API error, rate limit,
    failed number validation -- this falls back to the plain terser
    "Big Picture" framing that already existed, silently and safely. The
    "Worth a Look This Week" structured section (the real backbone) is
    NEVER touched by any of this; it's built the same deterministic way
    either way. Rule 16: the JSON output honestly records whether
    narrative actually ran this time (narrativeGenerated) or fell back
    (narrativeFallbackReason), never claims success it didn't earn.
  - Reads the key from the ANTHROPIC_API_KEY environment variable only --
    never hardcoded, never logged, never printed.
"""

SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2, "OPTIMAL": 3}
MAX_WATCH_ITEMS = 5
NARRATIVE_MODEL = "claude-haiku-4-5-20251001"
NARRATIVE_MAX_TOKENS = 900


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


def item_sentence(item):
    """Turn a Senior Manager's item dict into one plain-language sentence,
    stitched from its own real fields -- never inventing new claims."""
    sentence = item.get("description", "").strip()
    if item.get("worth_considering"):
        sentence += f" Worth considering: {item['worth_considering']}"
    return sentence


def _build_facts_packet(framing_lines, watch_items, positive_note):
    """Plain-text dump of every fact the narrative step is allowed to see
    and reference -- nothing here is new information, it's the same
    framing/watch_items/positive_note already assembled for the templated
    memo, just handed over as prose the model can read."""
    lines = ["BIG PICTURE:"]
    for fl in framing_lines:
        lines.append(f"- {fl}")
    lines.append("")
    lines.append("THIS WEEK'S WATCH ITEMS (already severity-ranked, do not re-rank or add your own):")
    for item in watch_items:
        lines.append(f"- [{item.get('severity')}] {item.get('title')} ({item.get('source')}): {item.get('metric')}. {item_sentence(item)}")
    if positive_note:
        lines.append("")
        lines.append("ALSO WORTH NOTING (a genuine positive, not manufactured balance):")
        lines.append(f"- {positive_note.get('title')} ({positive_note.get('source')}): {positive_note.get('metric')}. {item_sentence(positive_note)}")
    return "\n".join(lines)


def generate_narrative(framing_lines, watch_items, positive_note, allowed_numbers):
    """Returns narrative text on success, or None on ANY failure (missing
    key, API error, failed number validation) -- callers must treat None
    as "fall back to the templated framing," never as an error to raise.
    See the 2026-08-12 header note above for why this is bounded the way
    it is."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("[INFO] ANTHROPIC_API_KEY not set -- skipping narrative step, using templated framing.")
        return None

    try:
        import anthropic
    except ImportError:
        print("[WARN] `anthropic` package not installed -- skipping narrative step, using templated framing.")
        return None

    facts_packet = _build_facts_packet(framing_lines, watch_items, positive_note)
    system_prompt = (
        "You write a short connective narrative for the owner of a small seasonal retail business, "
        "based ONLY on the facts given to you below. Rules, no exceptions:\n"
        "1. Never state a number that isn't in the facts provided, verbatim or rounded to the nearest whole dollar/point.\n"
        "2. Never compute a new number (no totals, no averages, no percentages you derive yourself).\n"
        "3. Any interpretive or causal claim -- anything that isn't a fact stated below -- must be wrapped "
        "inline exactly like this: [READ, NOT FACT: your interpretation here]. Plain facts need no wrapper.\n"
        "4. Plain, warm, direct language -- this reader has no finance background. No jargon, no bullet points, "
        "prose paragraphs only.\n"
        "5. Never issue a directive or tell the reader what to do -- frame things as worth considering, not commands.\n"
        "6. 3-4 short paragraphs. No headers, no title, just the paragraphs."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=NARRATIVE_MODEL,
            max_tokens=NARRATIVE_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": facts_packet}],
        )
        narrative = "".join(block.text for block in response.content if hasattr(block, "text")).strip()
    except Exception as e:
        print(f"[WARN] Narrative API call failed ({e}) -- falling back to templated framing.")
        return None

    if not narrative:
        print("[WARN] Narrative API call returned empty text -- falling back to templated framing.")
        return None

    is_valid, unmatched = check_narrative(narrative, allowed_numbers)
    if not is_valid:
        print(f"[WARN] Narrative failed number validation (unmatched: {unmatched}) -- discarding, falling back to templated framing.")
        return None

    print(f"[OK] Narrative generated via {NARRATIVE_MODEL} and passed number validation.")
    return narrative


def run_ceo_memo():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    business_dir = os.path.abspath(os.path.join(base_dir, ".."))
    out_dir = os.path.join(business_dir, "dashboard_app")
    os.makedirs(out_dir, exist_ok=True)

    print(f"=== CEO Weekly Memo [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ===")

    cfo = load_json(os.path.join(out_dir, "cfo_executive_audit.json"))
    coo = load_json(os.path.join(out_dir, "coo_operations_audit.json"))
    controller = load_json(os.path.join(out_dir, "controller_audit.json"))
    cash_forecast = load_json(os.path.join(out_dir, "cash_forecast_live.json"))

    if not cfo or not coo:
        print("[ERROR] Missing CFO or COO synthesis -- cannot write a CEO memo without both. "
              "Run cfo_executive_audit.py and coo_operations_audit.py first.")
        return None
    if not controller:
        print("[WARN] Missing Controller synthesis (controller_audit.json) -- memo will proceed "
              "without Payment Integrity items this run. Run controller_audit.py to include them.")

    memo_date = datetime.now().strftime("%B %d, %Y")

    # -------------------------------------------------------------------
    # Framing: growth trend + cash health, so watch items land with
    # context instead of in isolation (per OPERATOR_BRIEFING.md: "never
    # interpret any period in isolation" given this business's seasonality).
    # -------------------------------------------------------------------
    growth_pct = cash_forecast.get("growthTrendPct")
    ttm_base = cash_forecast.get("ttmBaseRevenue")
    framing_lines = []
    if growth_pct is not None and ttm_base is not None:
        direction = "up" if growth_pct >= 0 else "down"
        framing_lines.append(
            f"Trailing-12-month revenue is ${ttm_base:,.0f}, {direction} {abs(growth_pct)*100:.1f}% "
            f"year over year -- the growth trend the whole forecast is built on right now."
        )
    # Pull the CFO's own cash item verbatim rather than re-deriving it.
    cfo_cash_item = next((i for i in cfo.get("cashDebtAndTerms", []) if i.get("title", "").startswith("Cash Forecast")), None)
    if cfo_cash_item:
        framing_lines.append(item_sentence(cfo_cash_item))

    # -------------------------------------------------------------------
    # Watch items: both Senior Managers' already-filtered needsAttention
    # lists, combined and severity-sorted. This IS the 3-5 things that
    # matter -- no separate re-ranking logic on top of what CFO/COO already
    # decided crossed a threshold.
    # -------------------------------------------------------------------
    cfo_watch = [dict(i, source="CFO") for i in cfo.get("needsAttention", [])]
    coo_watch = [dict(i, source="COO") for i in coo.get("needsAttention", [])]
    controller_watch = [dict(i, source="Controller") for i in controller.get("needsAttention", [])]
    combined = cfo_watch + coo_watch + controller_watch
    combined.sort(key=lambda x: SEVERITY_ORDER.get(x.get("severity"), 9))
    watch_items = combined[:MAX_WATCH_ITEMS]
    overflow_count = max(0, len(combined) - MAX_WATCH_ITEMS)

    # -------------------------------------------------------------------
    # One honest positive note, if the data actually supports one -- not
    # manufactured balance, a real OPTIMAL-flagged item from either manager.
    # -------------------------------------------------------------------
    all_optimal = [
        dict(i, source="CFO") for i in (cfo.get("capitalEfficiency", []) + cfo.get("cashDebtAndTerms", []))
        if i.get("severity") == "OPTIMAL"
    ] + [
        dict(i, source="COO") for i in (
            coo.get("inventoryAndReorder", []) + coo.get("marginAndVendor", []) +
            coo.get("staffingAndTraffic", []) + coo.get("pricingHealth", [])
        )
        if i.get("severity") == "OPTIMAL"
    ] + [
        dict(i, source="Controller") for i in controller.get("booksAndPaymentIntegrity", [])
        if i.get("severity") == "OPTIMAL"
    ]
    positive_note = all_optimal[0] if all_optimal else None

    # -------------------------------------------------------------------
    # Optional narrative step (2026-08-12) -- see header comment. Reads
    # ONLY the facts already assembled above; falls back to None (silently,
    # safely) on any failure. allowed_numbers is built from the raw source
    # JSONs, not just the trimmed watch_items/framing_lines, so a narrative
    # referencing a real number that didn't make the top-5 watch list still
    # validates correctly.
    # -------------------------------------------------------------------
    allowed_numbers = collect_allowed_numbers_from_data(cfo, coo, controller, cash_forecast)
    narrative = generate_narrative(framing_lines, watch_items, positive_note, allowed_numbers)
    narrative_fallback_reason = None if narrative else (
        "no ANTHROPIC_API_KEY configured, an API error, or failed number validation -- see console log for which"
    )

    # -------------------------------------------------------------------
    # Compose the memo (markdown -- plain-language, no jargon, no directive
    # language; every sentence traces to a real field above).
    # -------------------------------------------------------------------
    lines = []
    lines.append(f"# the business -- Weekly Business Memo")
    lines.append(f"*{memo_date}*")
    lines.append("")
    lines.append(
        "This is a plain-language pull from this week's numbers -- not a directive, just what's "
        "actually true right now and why it might matter. the operator's reviewing this before anything "
        "goes further."
    )
    lines.append("")
    if narrative:
        lines.append("## This Week, In Plain Terms")
        lines.append("")
        lines.append(narrative)
        lines.append("")
    elif framing_lines:
        lines.append("## The Big Picture")
        lines.append("")
        for fl in framing_lines:
            lines.append(fl)
        lines.append("")
    if watch_items:
        lines.append(f"## Worth a Look This Week ({len(watch_items)}{'+' if overflow_count else ''})")
        lines.append("")
        for idx, item in enumerate(watch_items, start=1):
            lines.append(f"**{idx}. {item.get('title')}** ({item.get('source')}, {item.get('severity')}) -- {item.get('metric')}")
            lines.append("")
            lines.append(item_sentence(item))
            lines.append("")
        if overflow_count:
            lines.append(f"*({overflow_count} additional lower-priority item(s) flagged in the underlying CFO/COO reports, not repeated here.)*")
            lines.append("")
    else:
        lines.append("## Worth a Look This Week")
        lines.append("")
        lines.append("Nothing crossed a CRITICAL or WARNING threshold on either the finance or operations side this run.")
        lines.append("")
    if positive_note:
        lines.append("## Also Worth Noting")
        lines.append("")
        lines.append(f"**{positive_note.get('title')}** ({positive_note.get('source')}) -- {positive_note.get('metric')}. {item_sentence(positive_note)}")
        lines.append("")
    lines.append("---")
    lines.append(
        f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} by ceo_weekly_memo.py, reading "
        f"cfo_executive_audit.py, coo_operations_audit.py, and controller_audit.py's output. "
        f"Reaches the operator only -- he decides what, if anything, goes to the owners.*"
    )
    memo_text = "\n".join(lines)

    memo_payload = {
        "asOfDate": memo_date,
        "audience": "the operator (not sent to owners directly -- he decides what to pass on)",
        "framing": framing_lines,
        "narrativeGenerated": narrative is not None,
        "narrative": narrative,
        "narrativeModel": NARRATIVE_MODEL if narrative else None,
        "narrativeFallbackReason": narrative_fallback_reason,
        "watchItems": watch_items,
        "watchItemOverflowCount": overflow_count,
        "positiveNote": positive_note,
    }

    json_out_file = os.path.join(out_dir, "ceo_weekly_memo.json")
    with open(json_out_file, "w", encoding="utf-8") as f:
        json.dump(memo_payload, f, indent=2)

    md_out_file = os.path.join(out_dir, "ceo_weekly_memo.md")
    with open(md_out_file, "w", encoding="utf-8") as f:
        f.write(memo_text)

    print("\n--- CEO Weekly Memo ---\n")
    print(memo_text)
    print(f"\n[SUCCESS] CEO memo written -> {md_out_file}")
    print(f"[SUCCESS] CEO memo JSON written -> {json_out_file}")
    return memo_payload


if __name__ == "__main__":
    run_ceo_memo()
