#!/usr/bin/env python3
"""Record ingest batch measurements and report both new and legacy log history.

Run `make metrics` for a table or `python3 scripts/metrics.py --csv` for plotting.
Rows are batches (one model invocation), not individual documents. Token totals
include cache reads and writes and therefore represent cumulative tokens handled
across turns, not unique document text or billable uncached tokens.
"""

import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / ".state"
METRICS = STATE / "ingest-metrics.jsonl"
LOG = STATE / "ingest.log"
STAMP = "%Y-%m-%d %H:%M:%S"
FIELDS = ["started", "harness", "model", "wiki_sources", "wiki_pages",
          "requested", "compiled", "source_bytes", "seconds", "turns",
          "input_uncached", "cache_read", "cache_write", "input_total",
          "output", "cost_usd", "status"]


def integer(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def usage_from_result(path, harness):
    if harness == "omp":
        totals = dict(input_uncached=0, cache_read=0, cache_write=0,
                      output=0, turns=0, cost_usd=0.0)
        model = ""
        for line in path.open(errors="replace"):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") != "turn_end":
                continue  # message_end repeats the same usage
            message = event.get("message") or {}
            usage = message.get("usage") or {}
            if not usage:
                continue
            totals["turns"] += 1
            totals["input_uncached"] += integer(usage.get("input"))
            totals["cache_read"] += integer(usage.get("cacheRead"))
            totals["cache_write"] += integer(usage.get("cacheWrite"))
            totals["output"] += integer(usage.get("output"))
            totals["cost_usd"] += float((usage.get("cost") or {}).get("total") or 0)
            model = message.get("model") or model
        return totals, model

    result = json.loads(path.read_text())
    usage = result.get("usage") or {}
    return {
        "input_uncached": integer(usage.get("input_tokens")),
        "cache_read": integer(usage.get("cache_read_input_tokens")),
        "cache_write": integer(usage.get("cache_creation_input_tokens")),
        "output": integer(usage.get("output_tokens")),
        "turns": integer(result.get("num_turns")),
        "cost_usd": float(result.get("total_cost_usd") or 0),
    }, ""


def record(args):
    names = [name for name in args.names.splitlines() if name]
    source_bytes = 0
    for name in names:
        matches = sorted(p for p in (ROOT / "raw").rglob(name + ".*")
                         if p.is_file() and p.suffix != ".png")
        if matches:
            source_bytes += matches[0].stat().st_size
    try:
        usage, reported_model = usage_from_result(pathlib.Path(args.result), args.harness)
        status = "ok" if usage["turns"] else "no_usage"
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"METRICS: could not parse result: {exc}", file=sys.stderr)
        usage, reported_model, status = {}, "", "no_usage"
    row = {
        "started": dt.datetime.fromtimestamp(args.started).isoformat(timespec="seconds"),
        "round": args.round,
        "harness": args.harness,
        "model": args.model or reported_model or {"omp": "glm-5.3-flash", "codex": "codex-default"}.get(args.harness, "claude-haiku-4-5-20251001"),
        "wiki_sources": args.sources_before,
        "wiki_pages": args.pages_before,
        "pending_before": args.pending_before,
        "requested": args.requested,
        "compiled": args.compiled,
        "source_bytes": source_bytes,
        "seconds": max(0, int(time.time() - args.started)),
        **usage,
        "status": f"exit_{args.exit_code}" if args.exit_code else status,
    }
    row["input_total"] = sum(row.get(key, 0) for key in
                             ("input_uncached", "cache_read", "cache_write"))
    METRICS.parent.mkdir(exist_ok=True)
    with METRICS.open("a") as out:
        out.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"METRICS  {row['compiled']}/{row['requested']} sources, "
          f"{row['seconds']}s, {row['input_total']:,} input tokens")


def legacy_rows():
    """Recover comparable batch totals from the old human log where possible."""
    if not LOG.exists():
        return []
    batch = None
    rows = []
    cost_re = re.compile(r"^  COST  \$([\d.]+)\s+turns (\d+)\s+in ([\d,]+)\s+out ([\d,]+)")
    start_re = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  BATCH (\d+)  compiling (\d+)")
    done_re = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  BATCH (\d+) done  wrote (-?\d+)")
    harness_re = re.compile(r"^\d{4}-\d\d-\d\d .*  harness (\w+), model (.+)$")
    for line in LOG.open(errors="replace"):
        if match := start_re.match(line):
            batch = {"started": match[1].replace(" ", "T"), "round": int(match[2]),
                     "requested": int(match[3]), "status": "legacy"}
        elif batch and (match := harness_re.match(line)):
            batch["harness"], batch["model"] = match.groups()
        elif batch and (match := cost_re.match(line)):
            batch.update(cost_usd=float(match[1]), turns=int(match[2]),
                         input_total=int(match[3].replace(",", "")),
                         output=int(match[4].replace(",", "")))
        elif batch and (match := done_re.match(line)) and int(match[2]) == batch["round"]:
            if "input_total" in batch:
                started = dt.datetime.fromisoformat(batch["started"])
                batch["seconds"] = int((dt.datetime.strptime(match[1], STAMP) - started).total_seconds())
                batch["compiled"] = int(match[3])
                rows.append(batch)
            batch = None
    return rows


def report(csv_output):
    rows = []
    if METRICS.exists():
        for line in METRICS.open():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    # The log and JSONL both describe future runs; retain the richer JSONL row.
    for old in legacy_rows():
        if not any(abs((dt.datetime.fromisoformat(old["started"]) -
                        dt.datetime.fromisoformat(new["started"])).total_seconds()) < 5
                   and old["round"] == new.get("round") for new in rows):
            rows.append(old)
    rows.sort(key=lambda row: row["started"])
    if csv_output:
        writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return
    if not rows:
        print("No measured ingest batches yet.")
        return
    print("Date/time         Model                     Wiki sources  Done  Minutes  Input M  Output k   Cost")
    for row in rows:
        size = str(row["wiki_sources"]) if "wiki_sources" in row else "?"
        print(f"{row['started'][:16]:16}  {row.get('model', '?')[:24]:24}  {size:>12}  "
              f"{row.get('compiled', 0):>2}/{row.get('requested', 0):<2}  "
              f"{row.get('seconds', 0)/60:>7.1f}  "
              f"{row.get('input_total', 0)/1_000_000:>7.1f}  "
              f"{row.get('output', 0)/1_000:>8.1f}  ${row.get('cost_usd', 0):.4f}")
    print("Input M includes cache reads/writes. Older rows lack wiki size and cache breakdown;")
    print("compare similar models, batch sizes, and source lengths before judging growth.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", action="store_true", help="machine-readable history")
    sub = parser.add_subparsers(dest="command")
    rec = sub.add_parser("record", help="append one measured batch")
    rec.add_argument("--result", required=True)
    rec.add_argument("--harness", required=True)
    rec.add_argument("--model", required=True)
    rec.add_argument("--started", required=True, type=int)
    rec.add_argument("--round", required=True, type=int)
    rec.add_argument("--requested", required=True, type=int)
    rec.add_argument("--compiled", required=True, type=int)
    rec.add_argument("--pending-before", required=True, type=int)
    rec.add_argument("--sources-before", required=True, type=int)
    rec.add_argument("--pages-before", required=True, type=int)
    rec.add_argument("--exit-code", required=True, type=int)
    rec.add_argument("--names", required=True)
    args = parser.parse_args()
    if args.command == "record":
        record(args)
    else:
        report(args.csv)


if __name__ == "__main__":
    main()
