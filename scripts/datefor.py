#!/usr/bin/env python3
"""Work out when a source actually happened, and say how confident that is.

The order things are dropped into the inbox is not the order they happened in,
so every source needs an event date that does not come from the ingest.

Four signals, and the useful thing is that they check each other:

  1. A date in the FILENAME     a transcriber's own timestamp. Exact.
  2. A date in the CONTENT      the author's own claim. May be coarse ("Sept 2026").
  3. The file's MTIME           an UPPER BOUND -- a file cannot be written before
                                the thing it describes.
  4. The INGEST date            last resort. Always too late, but bounded.

Because mtime is an upper bound, it is informative even when wrong: a large gap
between a stated date and the mtime means the document was revised after it was
written. Measured on real files here, 6 of 7 mtimes landed on the same day as
another signal; the one that did not had "(WIP)" in its name.

Usage:
  datefor.py <file> [--json]
"""

import argparse
import datetime as dt
import json
import pathlib
import re
import sys

MONTHS = ("january february march april may june july august september "
          "october november december").split()
ABBR = [m[:3] for m in MONTHS]

FILENAME_PATTERNS = [
    (re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})"), "ymd"),
]
CONTENT_PATTERNS = [
    # "16 April 2026" / "7 August 2026"
    (re.compile(r"\b(\d{1,2})\s+([A-Z][a-z]{2,8})\.?\s+(20\d{2})\b"), "dmy"),
    # "April 16, 2026"
    (re.compile(r"\b([A-Z][a-z]{2,8})\.?\s+(\d{1,2}),?\s+(20\d{2})\b"), "mdy"),
    # "2026-04-16"
    (re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b"), "iso"),
    # coarse: "Sept 2026" -- month precision only
    (re.compile(r"\b([A-Z][a-z]{2,8})\.?\s+(20\d{2})\b"), "my"),
]
CONTENT_SCAN_CHARS = 1200   # only the top of a document states its own date


def month_num(word: str):
    w = word.lower().rstrip(".")
    if w in MONTHS:
        return MONTHS.index(w) + 1
    if w[:3] in ABBR:
        return ABBR.index(w[:3]) + 1
    return None


def safe(y, m, d):
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def from_filename(name: str):
    for pat, _ in FILENAME_PATTERNS:
        m = pat.search(name)
        if m:
            d = safe(m.group(1), m.group(2), m.group(3))
            if d:
                return d, False          # precise
    return None, False


def from_content(text: str):
    head = text[:CONTENT_SCAN_CHARS]
    for pat, kind in CONTENT_PATTERNS:
        for m in pat.finditer(head):
            if kind == "dmy":
                mn = month_num(m.group(2))
                if mn:
                    d = safe(m.group(3), mn, m.group(1))
                    if d:
                        return d, False
            elif kind == "mdy":
                mn = month_num(m.group(1))
                if mn:
                    d = safe(m.group(3), mn, m.group(2))
                    if d:
                        return d, False
            elif kind == "iso":
                d = safe(*m.groups())
                if d:
                    return d, False
            elif kind == "my":
                mn = month_num(m.group(1))
                if mn:
                    d = safe(m.group(2), mn, 1)
                    if d:
                        return d, True   # COARSE: month precision only
    return None, False


def decide(path: pathlib.Path, content_from: pathlib.Path = None) -> dict:
    """`path` supplies the filename and the mtime. `content_from` supplies the
    text, when the original is a binary that has been converted to a twin.

    They must come from different files for PDF and PowerPoint: the twin was
    written by the converter today, so its mtime is worthless, while the original
    cannot be read for a date. Take each signal from wherever it is real."""
    reader = content_from or path
    text = ""
    if reader.suffix.lower() in (".md", ".txt", ".markdown"):
        text = reader.read_text(errors="replace")
    fname, _ = from_filename(path.name)
    content, coarse = from_content(text)
    mtime = dt.date.fromtimestamp(path.stat().st_mtime)
    ingest = dt.date.today()

    sig = {"filename": fname, "content": content, "mtime": mtime, "ingest": ingest}
    notes = []

    # --- choose ---
    if fname:
        chosen, src = fname, "filename"
        if abs((mtime - fname).days) <= 2:
            conf = "high"; notes.append("filename and mtime agree")
        else:
            conf = "medium"
            notes.append(f"mtime is {(mtime - fname).days}d from the filename date")
    elif content and coarse:
        # a coarse content date plus an mtime inside it = same period, better precision
        if content.year == mtime.year and content.month == mtime.month:
            chosen, src, conf = mtime, "mtime", "high"
            notes.append("content gives the month, mtime gives the day inside it")
        else:
            chosen, src, conf = content, "content", "low"
            notes.append("content month only, and mtime falls outside it")
    elif content:
        gap = (mtime - content).days
        if gap < 0:
            chosen, src, conf = content, "content", "low"
            notes.append("mtime is BEFORE the stated date -- impossible, check it")
        elif gap <= 2:
            chosen, src, conf = content, "content", "high"
            notes.append("content and mtime agree")
        elif gap <= 14:
            chosen, src, conf = content, "content", "medium"
            notes.append(f"file modified {gap}d after its stated date")
        else:
            chosen, src, conf = content, "content", "low"
            notes.append(f"file modified {gap}d after its stated date "
                         "-- probably revised since; the content date is the event, "
                         "but the document may no longer match it")
    else:
        chosen, src, conf = mtime, "mtime", "medium"
        notes.append("no date in the filename or the content; mtime is an upper bound")

    return {
        "file": path.name,
        "source_date": chosen.isoformat(),
        "date_from": src,
        "date_confidence": conf,
        "signals": {k: (v.isoformat() if v else None) for k, v in sig.items()},
        "notes": notes,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="supplies the filename and the mtime")
    ap.add_argument("--content-from", help="read the text from here instead "
                                           "(the converted twin of a binary)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    p = pathlib.Path(args.file)
    if not p.exists():
        print(f"ERROR  {p} does not exist")
        return 2
    cf = pathlib.Path(args.content_from) if args.content_from else None
    if cf and not cf.exists():
        print(f"ERROR  {cf} does not exist")
        return 2
    r = decide(p, cf)
    if args.json:
        print(json.dumps(r, indent=2))
        return 0
    print(f"=== {r['file']}")
    print(f"    source_date:     {r['source_date']}")
    print(f"    date_from:       {r['date_from']}")
    print(f"    date_confidence: {r['date_confidence']}")
    print("    signals:")
    for k, v in r["signals"].items():
        print(f"      {k:<9} {v or '-'}")
    for n in r["notes"]:
        print(f"    note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
