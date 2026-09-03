# Digital Org Chart -- AI-Orchestrated Executive Reporting Pipeline

Anonymized portfolio version of a four-layer reporting system I directed the AI-assisted development of for a real, seasonal small retail business I run the finance/ops function for. It turns ~20 single-domain "analyst" scripts (inventory, cash, labor, vendor, payment integrity, etc.) into one short weekly memo an actual human will read, without ever letting a model assert a number that isn't real.

Business name, real dollar figures, and file paths below are illustrative, not real. The architecture, the logic, and the engineering discipline are exactly what runs in production.

## Why this exists

A one-person finance/ops function can build dozens of scripts that each analyze one thing well -- inventory velocity, stockout risk, vendor markup, labor cost, payment reconciliation -- but nothing reads *across* them and tells the actual business owners what matters **this week**. Most of that work just sits in JSON files nobody opens.

This pipeline is the layer that does that reading-across, deliberately structured like a small company's chain of command because that's a mental model the business owners already understand, even though under the hood it's still Python reading JSON:

```
Layer 1  Data Grunts     ETL / ingestion -- no judgment, just pull and normalize
Layer 2  Analysts        ~20 single-domain scripts, each an expert in one thing
Layer 3  Senior Managers  CFO / COO / Controller -- read 3-6 analysts each,
                          apply real thresholds, decide what needs attention
Layer 4  CEO              Reads all three Senior Managers, picks the handful
                          of things that actually matter, writes the memo
```

Three decisions, locked in early and enforced throughout the codebase:

1. **Recommendations surface facts; humans decide.** No layer issues a one-click-approve directive. Every output states what's true and why it might matter, and leaves the call to the business owner.
2. **Synthesis is templated, not LLM-authored, by default.** The "writing" at every layer is Python logic -- real thresholds, real numbers, an f-string. This codebase already tried "let an AI write the insight" once (in a sibling analyst script, not included here) and it invented roughly 90% of its claims. It got rewritten specifically to stop doing that.
3. **The one narrow exception is bounded and verified, not trusted.** The CEO memo (`capstone/ceo_weekly_memo.py`) optionally asks a small model to write connective prose *on top of* the already-computed facts -- and every number that model writes gets checked against the verified source data before it's used. See "The guardrail," below.

## The four Senior Manager / CEO scripts

| Script | Reads | Answers |
|---|---|---|
| `senior_managers/cfo_executive_audit.py` | GMROI, cash forecast, dead stock, wholesale AP, MCA debt, basket analytics, + a live statistical pattern scan of 16 months of real ledger history | Is capital trapped in the wrong inventory, is a cash problem coming, and when |
| `senior_managers/coo_operations_audit.py` | Inventory velocity, stockouts, markdown candidates, vendor ROI, margin erosion, labor efficiency, weather/traffic forecast, discount elasticity | What to reorder, what to discount, what's quietly losing money, staffing for the week ahead |
| `senior_managers/controller_audit.py` | Payment-processor fee-rate audit, bank-vs-payout reconciliation | Does the money reported match the money that actually landed |
| `capstone/ceo_weekly_memo.py` | All three Senior Managers' already-filtered `needsAttention` lists | Picks the 3-5 things that actually matter this week and writes the memo a non-finance business owner will actually read |

## The guardrail (`lib/validate_narrative_numbers.py`)

This is the piece I'm proudest of. When the CEO memo's optional narrative step asks a model to write a paragraph of connective prose over the week's facts, that generated text is never trusted at face value. Before it's used:

1. Every number that appears anywhere in the verified source JSON (metrics, descriptions, "worth considering" notes) is extracted into an "allowed" set.
2. Every number in the model's generated narrative is extracted the same way.
3. Anything in the narrative that doesn't match an allowed number -- exactly, rounded to the nearest whole unit, or within a small rounding tolerance -- fails validation.
4. **On any failure, the whole narrative is discarded, full stop.** The memo falls back to its plain templated framing rather than shipping a partially-trusted paragraph.

This isn't a promise in a comment, it's a script that actually checks. It caught a real rounding slip in the first hand-written test sample before this was ever wired to a live model call. The model is also required to wrap any interpretive or causal claim -- as opposed to a stated fact -- in `[READ, NOT FACT: ...]`, so a reader can always tell a computed number from a read on it.

## A real bug this caught (see `cfo_executive_audit.py`'s own header)

The CFO script had a prior version already running before I audited it. Every single field it read had a schema-mismatch bug against the real source JSON -- it read `overall_gmroi` where the real key was `overall`, read a nested `ending_cash` dict that didn't exist at all, and had a dollar figure **hardcoded as a literal string** instead of reading the live field sitting right next to it. Every one of these bugs defaulted silently to `0.0` on failure, so the script ran on every scheduled refresh, wrote a JSON file, and every number in it was silently wrong the entire time -- and nothing downstream even consumed the file, so it was simultaneously broken *and* dead code. Every field name was verified against the real data's actual keys before this version shipped. The full bug list is preserved in the script's own header comment, not scrubbed out, because that history is the point: a system that fails loudly and gets checked against real data, rather than one that looks like it's working.

## Other things worth noticing in the code

- **Seasonal threshold scaling** (`lib/seasonal_thresholds.py`) -- this business runs at 0.32x an average month in the off-season and over 2x in peak season. A flat "$25,000 lost sales" warning is nearly meaningless in the peak month and overly aggressive in the slow one, so revenue-scale thresholds scale by a real historical seasonal index instead of one flat number year-round. Two different scaling methods are used deliberately (revenue-multiplier vs. own-month historical average), because a labor % ratio and a dollar-flow number don't seasonally distort the same way -- the module's header explains why applying the wrong method to the wrong metric would silently produce a backwards threshold.
- **Cross-domain statistical pattern scanning** (`lib/pattern_scan.py`) -- rather than asking a model to write "insights" (the exact approach that produced fabricated claims elsewhere in this codebase), this runs real Pearson correlation across every pair of a time series at multiple lags, with a hard minimum-sample-size guardrail and same-domain vs. cross-domain tagging. It doesn't assert causation and is always surfaced as `INFO` severity, never with the visual urgency of a real threshold breach -- a statistical lead across a small sample is not a verified fact, and the code treats it that way.
- **"Two competing sources of truth" avoidance** -- the COO script's own header documents deliberately *not* re-reporting a dead-stock figure the CFO script already reports from a different source file, even though both files happen to contain the same number today, specifically to avoid two Senior Managers ever printing conflicting numbers from two different files as a codebase drifts.
- **Idempotent by design** -- both the pattern-scan history logger (`lib/metrics_history.py`) and the Senior Manager scripts are safe to re-run on the same day; a second run overwrites that day's row/output rather than duplicating it.

## Run it

```bash
pip install -r requirements.txt
python build_sample_data.py   # writes illustrative dashboard_app/*.json fixtures
python demo.py                 # runs all four layers, prints the CEO memo
```

No real business data is required or included -- `build_sample_data.py` generates realistic-but-fabricated fixtures so the whole pipeline runs end to end out of the box.

## Tests

```bash
pytest tests/
```

25 tests covering the parts of this pipeline where being wrong is expensive: `test_validate_narrative_numbers.py` pins down the guardrail's exact real catch (a hand-written narrative said "$59,417" where the verified source fact was "$54,830.25" -- a plausible-looking but fabricated number, correctly rejected), `test_pattern_scan.py` checks the correlation math and its minimum-sample-size guardrail directly, and `test_seasonal_thresholds.py` locks in why the two seasonal scaling methods aren't interchangeable (a labor-% threshold built with revenue-multiplier scaling instead of own-month-history scaling would silently come out backwards).

## My role

I specified every threshold, every field mapping, and the "surface facts, humans decide" design constraint up front, then reviewed the AI-assisted implementation against the real data it was supposed to be reading -- which is how the CFO schema-mismatch bug above was found before it shipped further. I designed the guardrail approach for the one place a model is allowed to generate prose, and made the call on where LLM involvement was and wasn't appropriate in the rest of the pipeline.

## Stack

Python, JSON, `openpyxl` for reading the live ledger, `numpy` for the correlation scan, and the Anthropic API (optional, gracefully degrades without it) for the CEO memo's bounded narrative step.
