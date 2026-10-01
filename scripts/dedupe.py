#!/usr/bin/env python3
"""Duplicate detection for the wiki inbox.

Three checks, cheapest first:
  1. SHA-256 of the raw bytes          -> the same file dropped again
  2. SHA-256 of the normalised text    -> re-export, format change, pdf -> docx
  3. Jaccard overlap of word shingles  -> one name changed, a paragraph edited

The manifest at .state/manifest.jsonl answers exactly one question:
"have I seen this content before?" It does NOT record whether a source has been
compiled. That stays derived from links -- a file in raw/ that no wiki/ page
links to is not yet compiled. Two different questions, so they cannot drift.

The fuzzy check reads the stored markdown directly rather than a stored sketch,
so scores are exact and a lost manifest costs only the hashes.

Usage:
  dedupe.py check <file> [--text <converted.md>]
  dedupe.py add <raw_md_path> --bytes <original_file> [--origin <name>]
  dedupe.py list
"""

import argparse
import hashlib
import json
import pathlib
import re
import sys
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / ".state" / "manifest.jsonl"

SHINGLE = 4           # words per shingle
NEAR = 0.95           # at or above: almost certainly the same document
REVIEW = 0.70         # at or above: a human or agent must look
WIDTH = 0.40          # only compare against docs within +/- 40% word count

# CALIBRATION, MEASURED -- do not "tune" this without new evidence.
#
# A revision (one name corrected throughout) scores 0.73-0.86.
# A sibling (next week's meeting, same series) scores 0.73.
# These OVERLAP. No threshold separates them, at any shingle length; varying
# SHINGLE from 3 to 5 moved both together and changed nothing that matters.
#
# A verbatim-line-overlap signal was tried as a tie-breaker and rejected: it
# separated no better AND scored a re-wrapped export at 0.235 where shingles
# correctly scored 1.000. It would have made things worse.
#
# So the score reports CONFIDENCE, not category. Both NEAR and REVIEW mean
# "do not ingest silently". Unattended runs quarantine either. Deciding
# revision-vs-sibling needs the content, which means an agent or a person.


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def shingles(text: str) -> set:
    words = normalise(text).split()
    if len(words) < SHINGLE:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def load() -> list:
    if not MANIFEST.exists():
        return []
    out = []
    for line in MANIFEST.read_text().splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def read_text(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def cmd_check(args) -> int:
    src = pathlib.Path(args.file)
    if not src.exists():
        print(f"ERROR  {src} does not exist")
        return 2

    entries = load()
    digest = sha(src.read_bytes())

    for e in entries:
        if e["byte_sha"] == digest:
            print(f"EXACT  {e['raw_path']}  1.000")
            print(f"Identical bytes to a source ingested on {e['added']}. Skip it.")
            return 0

    if not args.text:
        print("NEW")
        print("No byte match. Convert it, then check again with --text.")
        return 0

    tpath = pathlib.Path(args.text)
    if not tpath.exists():
        print(f"ERROR  {tpath} does not exist")
        return 2

    text = read_text(tpath)
    tsha = sha(normalise(text).encode())

    for e in entries:
        if e.get("text_sha") == tsha:
            print(f"EXACT  {e['raw_path']}  1.000")
            print(f"Same text in a different container. Ingested {e['added']}. Skip it.")
            return 0

    mine = shingles(text)
    words = len(normalise(text).split())
    lo, hi = words * (1 - WIDTH), words * (1 + WIDTH)

    best, best_entry = 0.0, None
    for e in entries:
        if not (lo <= e.get("words", 0) <= hi):
            continue
        other = ROOT / e["raw_path"]
        if not other.exists():
            continue
        score = jaccard(mine, shingles(read_text(other)))
        if score > best:
            best, best_entry = score, e

    if best_entry and best >= NEAR:
        print(f"NEAR  {best_entry['raw_path']}  {best:.3f}")
        print("Almost certainly the same document. Do not ingest silently.")
        print("Unattended: quarantine to inbox/_review/.")
    elif best_entry and best >= REVIEW:
        print(f"REVIEW  {best_entry['raw_path']}  {best:.3f}")
        print("Overlaps heavily with an existing source. The score CANNOT tell")
        print("you whether this is a revision of it or a sibling document --")
        print("that needs the content. Unattended: quarantine to inbox/_review/.")
        print("Attended: read both, then decide.")
    else:
        print("NEW")
        print(f"Closest existing source scores {best:.3f}. Safe to ingest.")
    return 0


def cmd_add(args) -> int:
    raw = pathlib.Path(args.raw)
    original = pathlib.Path(args.bytes)
    if not raw.exists():
        print(f"ERROR  {raw} does not exist")
        return 2
    if not original.exists():
        print(f"ERROR  {original} does not exist")
        return 2

    try:
        rel = raw.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        print(f"ERROR  {raw} is outside the wiki")
        return 2

    text = read_text(raw)
    entry = {
        "raw_path": rel,
        "byte_sha": sha(original.read_bytes()),
        "text_sha": sha(normalise(text).encode()),
        "words": len(normalise(text).split()),
        "added": date.today().isoformat(),
        "origin": args.origin or original.name,
    }
    MANIFEST.parent.mkdir(exist_ok=True)
    with MANIFEST.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    print(f"ADDED  {rel}  ({entry['words']} words)")
    return 0


def cmd_list(args) -> int:
    entries = load()
    if not entries:
        print("Manifest is empty.")
        return 0
    print(f"{len(entries)} sources recorded")
    for e in entries:
        print(f"  {e['added']}  {e['words']:>6}w  {e['raw_path']}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="is this a duplicate?")
    c.add_argument("file")
    c.add_argument("--text", help="converted markdown, enables checks 2 and 3")
    c.set_defaults(fn=cmd_check)

    a = sub.add_parser("add", help="record a source after filing it")
    a.add_argument("raw", help="path to the markdown in raw/")
    a.add_argument("--bytes", required=True, help="the original file as dropped")
    a.add_argument("--origin", help="original filename, if different")
    a.set_defaults(fn=cmd_add)

    l = sub.add_parser("list", help="show recorded sources")
    l.set_defaults(fn=cmd_list)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
