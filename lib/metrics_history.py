"""
metrics_history.py -- generic append-only snapshot logger, for any Senior
Manager whose domain has NO durable historical time series to search for
patterns in (unlike CFO, which has the real bank ledger).

2026-08-11: built because COO's domain (stockouts, markdown, velocity,
labor, weather, discounts) only ever sees a fresh, overwritten snapshot
each pipeline run -- dashboard_app/*.json files have no memory of what they
said last time. the operator asked for every agent to independently be able to
find non-obvious patterns (see pattern_scan.py); that requires an actual
time series to search over, which for COO doesn't exist yet. This module
gives any script a durable, append-only CSV history of its own chosen
numeric fields, one row per time it runs -- and once enough real rows
accumulate, pattern_scan.scan_correlations() can search across them exactly
like it already does for CFO's ledger data.

Design notes:
  - Idempotent by date (Rule 7): if run_coo_audit() runs twice in one day
    (e.g. while testing), the second run OVERWRITES that day's row instead
    of adding a duplicate. Real accumulation happens one row per calendar
    day the pipeline actually runs, not per invocation.
  - Every row is a REAL snapshot from a REAL pipeline run, no synthetic or
    backfilled data -- there is no shortcut to a history that doesn't exist
    yet. Anything using this module should let the history build up
    naturally rather than fabricating past rows.
  - Missing metrics on a given run are written as empty (None), not zero
    -- consistent with the zero-fill fabrication bug already found and
    fixed once this session in creative_data_insights_agent.py.
"""

import csv
import os


def append_snapshot(csv_path, date_str, metrics: dict):
    """Append (or, if today's date already has a row, overwrite) one row of
    {metric_name: value} to the history CSV at csv_path. Columns grow
    automatically if a new metric name shows up that wasn't there before --
    existing rows just get a blank for it."""
    rows = []
    fieldnames = ["date"]
    if os.path.exists(csv_path):
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or ["date"]
            rows = [row for row in reader]

    for m in metrics:
        if m not in fieldnames:
            fieldnames.append(m)

    new_row = {"date": date_str}
    for k, v in metrics.items():
        new_row[k] = "" if v is None else v

    rows = [r for r in rows if r.get("date") != date_str]
    rows.append(new_row)
    rows.sort(key=lambda r: r["date"])

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def load_history_series(csv_path):
    """Returns (dates, series) where series is dict[metric_name] -> list of
    floats-or-None, aligned to dates (oldest first). Returns ([], {}) if the
    file doesn't exist yet (nothing has ever been logged)."""
    if not os.path.exists(csv_path):
        return [], {}

    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = [f_ for f_ in (reader.fieldnames or []) if f_ != "date"]
        rows = list(reader)

    dates = [r["date"] for r in rows]
    series = {}
    for field in fieldnames:
        values = []
        for r in rows:
            raw = r.get(field, "")
            if raw in (None, ""):
                values.append(None)
            else:
                try:
                    values.append(float(raw))
                except ValueError:
                    values.append(None)
        series[field] = values
    return dates, series
