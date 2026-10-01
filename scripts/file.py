#!/usr/bin/env python3
"""Do every mechanical ingest step for one file, in one call.

Steps 1-7 of CLAUDE.md: dedupe on bytes, convert, dedupe on text, move into raw/
preserving mtime, record in the manifest, date it, and resolve organisations.
Then it prints what the agent needs to write the page.

Why this exists as one command rather than several: an unattended run needs
permission for every shell command it issues. Ten steps meant permitting cp, mv,
rm and a pile of scripts -- a wide grant for a process nobody is watching. One
command means one narrow grant: `Bash(python3 scripts/*.py:*)`. The deny rules
on CLAUDE.md, schema/ and raw/ still stand above it.

It never overwrites and never deletes anything but the inbox copy it just moved.

Usage:
  file.py <inbox-file>
"""

import argparse
import datetime as dt
import json
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
CONVERTIBLE = {".pdf", ".pptx", ".docx"}
TEXT = {".md", ".txt", ".markdown"}
DATE_IN_NAME = re.compile(r"\b(20\d{2})[-_]?(\d{2})[-_]?(\d{2})\b")


def run(*cmd) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True)


def helper(name, *args):
    return run(sys.executable, SCRIPTS / name, *args)


def archive(src: pathlib.Path) -> pathlib.Path:
    """Move the inbox copy to inbox/_done/, under its ORIGINAL name and time.

    This used to be an unlink. That was wrong: if you MOVE a file into the inbox
    rather than copying it, deleting it destroys your only copy -- and the wiki
    then renamed it too, so you could not even find it by name.

    raw/ is the wiki's copy of record. It is not your canonical source, and the
    wiki must never be the only place a document exists.
    """
    done = ROOT / "inbox" / "_done"
    done.mkdir(exist_ok=True)
    dest = done / src.name
    n = 1
    while dest.exists():
        dest = done / f"{src.stem} ({n}){src.suffix}"
        n += 1
    shutil.move(str(src), dest)
    shutil.copystat(dest, dest)          # move already preserves mtime
    return dest


def hold(src: pathlib.Path, raw: pathlib.Path) -> pathlib.Path:
    """Park the inbox copy in inbox/_inflight/ and record that it is unfinished.

    Filing used to archive to _done and write the manifest in the same breath,
    before the agent had run. A source that was filed and then never compiled
    was therefore marked as seen forever: re-dropping it hit the byte hash and
    was skipped, and the only copy in the inbox had already moved to _done.
    Measured 2026-09-13 -- 64 sources in exactly that state.

    So filing now only PREPARES. commit.py decides afterwards, from whether the
    page exists, whether this becomes a manifest entry and an _done archive, or
    goes back in the inbox to be tried again.
    """
    hold_dir = ROOT / "inbox" / "_inflight"
    hold_dir.mkdir(exist_ok=True)
    dest = hold_dir / src.name
    n = 1
    while dest.exists():
        dest = hold_dir / f"{src.stem} ({n}){src.suffix}"
        n += 1
    shutil.move(str(src), dest)
    rec = {"stem": raw.stem, "raw": str(raw.relative_to(ROOT)),
           "held": str(dest.relative_to(ROOT)), "origin": src.name}
    with open(ROOT / ".state" / "inflight.jsonl", "a") as fh:
        fh.write(json.dumps(rec) + "\n")
    return dest


def looks_like_transcript(path: pathlib.Path, text: str) -> bool:
    if path.suffix.lower() != ".txt":
        return False
    lines = [l for l in text.splitlines()[:40] if l.strip()]
    if not lines:
        return False
    speakers = sum(1 for l in lines if re.match(r"^[A-Z][A-Za-z .'-]{0,30}:\s", l))
    return speakers > len(lines) * 0.5


def destination(src: pathlib.Path, text: str, source_date: str) -> pathlib.Path:
    """Where it lands. Keeps the arriving extension unless we converted it.

    A .txt transcript does not read better as .md -- that rename bought nothing
    and cost recognition. Only a binary gets a .md twin, and there the original
    is kept beside it. The date-first rename stays: sortable filenames are half
    the reason the timeline works.

    The TIME is kept too, and that is a change made 2026-09-13. It used to be
    stripped, so two meetings on the same day about the same thing both wanted
    the name `2026-09-10-acme-planning.txt`. That happened with an 11:56 and
    a 15:11 planning call -- different meetings, four hours and 50KB apart. The
    second was refused, correctly, but it should never have collided: the
    transcriber's filename already carried the time and this function threw it
    away. Uniqueness was being discarded and then missed.
    """
    if src.suffix.lower() in CONVERTIBLE:
        return ROOT / "raw" / "documents" / f"{src.stem}.md"
    ext = src.suffix or ".txt"
    if looks_like_transcript(src, text):
        stem = src.stem
        m = re.search(r"[\s_-](\d{3,4})\s*$", stem)      # the transcriber's HHMM
        hhmm = m.group(1).zfill(4) if m else None
        slug = DATE_IN_NAME.sub("", stem)
        slug = re.sub(r"[\s_-]\d{3,4}\s*$", "", slug).strip(" -_")
        slug = re.sub(r"[^A-Za-z0-9]+", "-", slug).strip("-").lower()
        stamp = f"{source_date}-{hhmm}" if hhmm else source_date
        return ROOT / "raw" / "transcripts" / f"{stamp}-{slug}{ext}"
    return ROOT / "raw" / "clippings" / f"{src.stem}{ext}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    args = ap.parse_args()

    src = pathlib.Path(args.file)
    if not src.is_absolute():
        src = ROOT / src
    if not src.exists():
        print(f"ERROR  {src} does not exist")
        return 2

    print(f"=== {src.name}")

    # --- 1. dedupe on bytes, before paying for a conversion ---
    r = helper("dedupe.py", "check", src)
    first = r.stdout.splitlines()[0] if r.stdout else "ERROR"
    if first.startswith("EXACT"):
        print(f"  SKIP  {first}")
        kept = archive(src)
        print(f"  archived  {kept.relative_to(ROOT)}  (original name kept)")
        print("  Append a `skip` log line naming the match.")
        return 0

    # --- 2. convert ---
    twin = src
    if src.suffix.lower() in CONVERTIBLE:
        c = helper("convert.py", src, "--out-dir", ROOT / ".state" / "twins")
        print(f"  {c.stdout.strip() or c.stderr.strip()}")
        twin = ROOT / ".state" / "twins" / f"{src.stem}.md"
        if not twin.exists():
            print("  ERROR  conversion produced nothing")
            return 1

    text = twin.read_text(errors="replace") if twin.suffix.lower() in TEXT else ""

    # --- 3. dedupe on text ---
    r = helper("dedupe.py", "check", src, "--text", twin)
    first = r.stdout.splitlines()[0] if r.stdout else "ERROR"
    if first.startswith("EXACT"):
        print(f"  SKIP  {first}")
        kept = archive(src)
        print(f"  archived  {kept.relative_to(ROOT)}  (original name kept)")
        print("  Same content in a different wrapper. Append a `skip` log line.")
        return 0
    if first.split()[0] in ("NEAR", "REVIEW"):
        review = ROOT / "inbox" / "_review"
        review.mkdir(exist_ok=True)
        shutil.move(str(src), review / src.name)
        print(f"  QUARANTINE  {first}")
        print(f"  moved to inbox/_review/. Do NOT compile it. Append a")
        print("  `quarantine` log line naming the match and the score.")
        return 0

    # --- 6. date it (before the move; the filename and mtime are the evidence) ---
    d = helper("datefor.py", src, "--json",
               *(["--content-from", str(twin)] if twin != src else []))
    info = json.loads(d.stdout)

    # --- 4. move into raw/, preserving mtime ---
    dest = destination(src, text, info["source_date"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"  ERROR  {dest.relative_to(ROOT)} already exists — not overwriting")
        return 1
    shutil.copy2(twin, dest)                     # copy2 preserves mtime
    original = None
    if src.suffix.lower() in CONVERTIBLE:
        original = dest.parent / src.name
        shutil.copy2(src, original)
        figs = twin.parent / f"{src.stem}-figures"
        if figs.is_dir():
            shutil.copytree(figs, dest.parent / figs.name, dirs_exist_ok=True)
    # the twin was written by the converter today; give it the original's time
    shutil.copystat(src, dest)

    # --- 5. hold, do not record ---
    # The manifest entry and the _done archive are COMMITTED by commit.py once
    # wiki/sources/<stem>.md exists. Doing them here marked work as finished
    # before the agent had even started.
    arrived = src.name
    kept = hold(src, dest)

    changed = []
    if pathlib.Path(arrived).stem != dest.stem:
        changed.append("renamed")
    if pathlib.Path(arrived).suffix.lower() != dest.suffix.lower():
        changed.append(f"{pathlib.Path(arrived).suffix} -> {dest.suffix}")
    note = f"   ({', '.join(changed)})" if changed else ""

    print(f"  FILED     {arrived}")
    print(f"        ->  {dest.relative_to(ROOT)}{note}")
    print(f"  held      {kept.relative_to(ROOT)}  (returns to inbox/ if no page is written)")
    if original:
        print(f"  original  {original.relative_to(ROOT)}")
    print(f"  date      {info['source_date']}  via {info['date_from']}  "
          f"({info['date_confidence']})")
    print(f"  FRONTMATTER  original_filename: {arrived}")
    for n in info["notes"]:
        if info["date_confidence"] != "high":
            print(f"            ! {n}")

    # --- 7. organisations ---
    o = helper("orgs.py", dest)
    body = [l for l in o.stdout.splitlines()[1:] if l.strip()]
    if body:
        print("  orgs:")
        for l in body:
            print(f"  {l}")

    # --- speakers, for transcripts ---
    if "transcripts" in dest.parts:
        sp = helper("speakers.py", dest)
        print("  speakers:")
        for l in sp.stdout.splitlines()[1:]:
            if l.strip():
                print(f"  {l}")

    print()
    print("  Next: search the wiki, then run")
    print(f"    python3 scripts/backstory.py --date {info['source_date']} --pages <slugs>")
    print("  before writing anything.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
