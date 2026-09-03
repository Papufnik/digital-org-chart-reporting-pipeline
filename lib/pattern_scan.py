"""
pattern_scan.py -- shared "dot-connector" utility, importable by any script
in this suite.

2026-08-11: extracted from dot_connector_poc.py (the proof-of-concept
the operator asked for -- see that script's original header for the full design
rationale) so the same correlation/lag/guardrail logic has ONE
implementation, not one copy per agent that could quietly drift apart.
Per the operator's follow-up ("I want the agents to be able to do this, each
independently"), this is meant to be imported by each Senior Manager's own
synthesis script and run against whatever time-series data exists in that
manager's domain -- NOT a single centralized script that owns all the
cross-referencing.

What this deliberately does NOT do: assert causation, generate a narrative,
or decide what's "interesting" beyond basic statistical guardrails (minimum
sample size, same-domain vs cross-domain tagging, multiple-comparisons
disclosure). Per the "surface facts, humans decide" model, a caller may
apply its OWN domain-specific filtering on top (e.g. cfo_executive_audit.py
deprioritizing anything trivially explained by revenue scale) -- that
judgment belongs in the caller, not buried in this shared utility.

Requires only numpy (already used elsewhere in this environment).
"""

from itertools import permutations, combinations
import numpy as np


def pearson(a, b, min_overlap):
    """Pearson r over paired, non-null values only.
    Returns (r, n). r is None if n < min_overlap or either series is constant
    (correlation undefined) over the overlap."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if n < min_overlap:
        return None, n
    xs = np.array([p[0] for p in pairs], dtype=float)
    ys = np.array([p[1] for p in pairs], dtype=float)
    if xs.std() == 0 or ys.std() == 0:
        return None, n
    r = float(np.corrcoef(xs, ys)[0, 1])
    return r, n


def _domain(key, domain_fn):
    if domain_fn:
        return domain_fn(key)
    return key.split("-")[0] if "-" in key else key


def scan_correlations(series, labels=None, min_overlap=10, lags=(0, 1, 2), domain_fn=None):
    """
    series: dict[key] -> list of values (or None), all lists the SAME length
            and index-aligned to the same time periods (e.g. same 16 months
            in the same order).
    labels: optional dict[key] -> human-readable label, for descriptions.
    min_overlap: minimum overlapping non-null data points required before a
            pair is reported at all -- the guardrail against small-sample
            noise. Callers with less history than this will legitimately
            get zero results, which is the correct behavior, not a bug.
    lags: which lag steps (in units of the series' own period, e.g. months)
            to test. lag=0 is same-period, symmetric. lag>0 tests both
            directions (A leads B, B leads A) since direction is a
            different claim.
    domain_fn: optional function(key) -> group label, used to tag
            "same-domain" (expected, less interesting) vs "cross-domain"
            (the non-obvious kind) pairs. Defaults to splitting on the
            first "-" in the key (matches this codebase's CODE-STYLE
            category naming, e.g. "LAB-WAGES" -> domain "LAB").

    Returns a dict:
      testsRun: total (pair, lag) combinations attempted
      results: all results clearing min_overlap, sorted by |r| descending,
               each a dict with a, b, lag, r, n, sameDomain, description
    """
    labels = labels or {}
    keys = sorted(series.keys())
    results = []
    tests_run = 0

    # lag 0: unordered pairs, symmetric
    for a, b in combinations(keys, 2):
        r, n = pearson(series[a], series[b], min_overlap)
        tests_run += 1
        if r is not None:
            results.append({"a": a, "b": b, "lag": 0, "r": r, "n": n})
    # lag > 0: ordered pairs, direction matters
    for lag in [l for l in lags if l > 0]:
        for a, b in permutations(keys, 2):
            a_series = series[a][: len(series[a]) - lag]
            b_series = series[b][lag:]
            r, n = pearson(a_series, b_series, min_overlap)
            tests_run += 1
            if r is not None:
                results.append({"a": a, "b": b, "lag": lag, "r": r, "n": n})

    for res in results:
        res["sameDomain"] = _domain(res["a"], domain_fn) == _domain(res["b"], domain_fn)
        a_label, b_label = labels.get(res["a"], res["a"]), labels.get(res["b"], res["b"])
        if res["lag"] == 0:
            res["description"] = f"{res['a']} ({a_label}) vs {res['b']} ({b_label}), same period"
        else:
            res["description"] = f"{res['a']} ({a_label}) vs {res['b']} ({b_label}) {res['lag']} period(s) later"

    results.sort(key=lambda x: abs(x["r"]), reverse=True)

    return {
        "testsRun": tests_run,
        "resultsWithEnoughData": len(results),
        "minOverlapRequired": min_overlap,
        "results": results,
    }
