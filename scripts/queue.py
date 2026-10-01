#!/usr/bin/env python3
"""Decide what order to ingest the inbox in: oldest event first.

The order files are dropped in is not the order things happened. Ingesting
newest-first means every source afterwards is backstory, and every one needs
reconciliation -- we measured that: ten sources, ten out of sequence, nine
reconciliations, and one confident error written before the older evidence
arrived that would have prevented it.

Sorting ascending makes each source build forward on what came before. The
backstory check still runs, because sorting only helps WITHIN a batch: an old
document found next month, or a low-confidence date, still arrives out of order.

Within one day, orders by time from the filename (e.g. "... 20260908 1454") and
falls back to the file's modification time -- the day-granularity blind spot in
backstory.py.

Usage:
  queue.py [--dir inbox] [--json]
"""

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
TIME_IN_NAME = re.compile(r"\b(20\d{2})[-_]?(\d{2})[-_]?(\d{2})[ _-]+(\d{2})(\d{2})\b")
CONVERTIBLE = {".pdf", ".pptx", ".docx"}


def day_time(path: pathlib.Path) -> str:
    """HH:MM within the day, from the filename if it carries one, else mtime."""
    m = TIME_IN_NAME.search(path.name)
    if m:
        return f"{m.group(4)}:{m.group(5)}"
    return dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%H:%M")


def date_for(path: pathlib.Path, twin: pathlib.Path = None) -> dict:
    cmd = [sys.executable, str(ROOT / "scripts" / "datefor.py"), str(path), "--json"]
    if twin:
        cmd += ["--content-from", str(twin)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        return {"source_date": "9999-12-31", "date_from": "error",
                "date_confidence": "low", "notes": [out.stderr.strip()[:120]]}
    return json.loads(out.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default="inbox")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    inbox = (ROOT / args.dir) if not pathlib.Path(args.dir).is_absolute() else pathlib.Path(args.dir)
    files = [f for f in sorted(inbox.iterdir())
             if f.is_file() and not f.name.startswith(".")]
    if not files:
        print("Inbox is empty.") if not args.json else print("[]")
        return 0

    rows = []
    for f in files:
        twin = None
        if f.suffix.lower() in CONVERTIBLE:
            # convert to a scratch twin so the content date can be read
            scratch = ROOT / ".state" / "queue-twins"
            scratch.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, str(ROOT / "scripts" / "convert.py"),
                            str(f), "--out-dir", str(scratch)],
                           capture_output=True, text=True)
            cand = scratch / f"{f.stem}.md"
            twin = cand if cand.exists() else None
        d = date_for(f, twin)
        rows.append({
            "file": f.name,
            "source_date": d["source_date"],
            "time": day_time(f),
            "date_from": d["date_from"],
            "date_confidence": d["date_confidence"],
            "twin": str(twin.relative_to(ROOT)) if twin else None,
            "notes": d.get("notes", []),
        })

    rows.sort(key=lambda r: (r["source_date"], r["time"], r["file"]))
    for i, r in enumerate(rows, 1):
        r["order"] = i

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"Ingest order — oldest event first ({len(rows)} file(s)):\n")
    print(f"  {'#':<3}{'event':<12}{'time':<7}{'via':<10}{'conf':<8}file")
    print("  " + "-" * 74)
    for r in rows:
        flag = "" if r["date_confidence"] == "high" else "  <-- check"
        print(f"  {r['order']:<3}{r['source_date']:<12}{r['time']:<7}"
              f"{r['date_from']:<10}{r['date_confidence']:<8}{r['file'][:34]}{flag}")
    low = [r for r in rows if r["date_confidence"] != "high"]
    if low:
        print("\n  Dates not confirmed by two agreeing signals — these may sort wrong:")
        for r in low:
            for n in r["notes"]:
                print(f"    {r['file'][:32]}: {n[:92]}")
    print("\n  Ingest strictly in this order. The backstory check still runs on each:")
    print("  sorting fixes the order WITHIN this batch, not across batches.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
