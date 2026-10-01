#!/usr/bin/env python3
"""Resolve who is actually speaking in a transcript.

Transcription tools guess speaker names and get them wrong. Observed in real
files: one label claiming two identities ("Austin" says both "I'm Adam Rawlins"
and "I'm Alex Morgan"), and the same person spelled differently by different
tools ("Adam Rawlins" / "Adam Rollins", both wrong -- the name is Adam Rowlands).

A wiki that says "Alex Morgan said X" when they did not is worse than no wiki,
because it is wrong AND it looks certain. So this script does the arithmetic and
refuses to guess: it reports what it can prove and flags what it cannot.

The agent does the judgement. schema/people.yml always wins.

Usage:
  speakers.py <transcript> [--json]
"""

import argparse
import difflib
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROSTER = ROOT / "schema" / "people.yml"

LINE = re.compile(r"^([A-Z][A-Za-z .'-]{0,30}):\s*(.*)$")
ANON = re.compile(r"^(?:[A-Z]|Speaker ?\d+|S\d+)$")  # "A", "B", "Speaker 1"

# The owner hand-tags speakers when the transcriber fails, and marks the file. They
# will forget sometimes, so this is deliberately forgiving: any of these, in any
# case, anywhere in the first few lines.
VERIFIED = re.compile(
    r"speakers?[ _-]?(?:verified|checked|tagged|fixed)|"
    r"^\s*(?:#+\s*)?\[?verified\]?\s*$", re.I)
VERIFIED_SCAN_LINES = 6
# The trigger phrase is case-insensitive ("My name is" starts a sentence); the
# NAME must still be capitalised, or "I'm going" yields a person called Going.
SELF = [
    re.compile(r"(?i:\bi'm )([A-Z][a-z]+(?: [A-Z][a-z]+)?)"),
    re.compile(r"(?i:\bi am )([A-Z][a-z]+(?: [A-Z][a-z]+)?)"),
    re.compile(r"(?i:\bmy name(?:'?s| is) )([A-Z][a-z]+(?: [A-Z][a-z]+)?)"),
    re.compile(r"(?i:\bthis is )([A-Z][a-z]+(?: [A-Z][a-z]+)?)(?i: (?:here|speaking))"),
]
# words that follow "I'm" but are not names
STOP = {"Not", "Sure", "Going", "Just", "Sorry", "Happy", "Afraid", "Good",
        "Fine", "Okay", "Core", "Looking", "About", "Still", "Here"}


def load_roster() -> list:
    """Parse the roster. Deliberately a tiny parser -- no yaml dependency."""
    if not ROSTER.exists():
        return []
    people, cur = [], None
    for raw in ROSTER.read_text().splitlines():
        line = raw.strip()
        if line.startswith("#") or not line:
            continue
        if line.startswith("- canonical:"):
            cur = {"canonical": line.split(":", 1)[1].strip(), "aliases": []}
            people.append(cur)
        elif cur and line.startswith("aliases:"):
            body = line.split(":", 1)[1].strip().strip("[]")
            cur["aliases"] = [a.strip() for a in body.split(",") if a.strip()]
    return people


def canonical_for(name: str, roster: list):
    """Exact match against canonical names and aliases."""
    for p in roster:
        if name == p["canonical"] or name in p["aliases"]:
            return p["canonical"]
    return None


def near_matches(name: str, roster: list) -> list:
    known = []
    for p in roster:
        known.append(p["canonical"])
        known.extend(p["aliases"])
    return [m for m in difflib.get_close_matches(name, known, n=3, cutoff=0.82)
            if m != name]


def agrees(label: str, claim: str) -> bool:
    """Does the diariser's label agree with what the speaker calls themselves?

    "Adam Rollins" vs "Adam Rollins" -> yes.  "Gurjeet" vs "Gurjeet Atwell" -> yes.
    "Austin" vs "Adam Rawlins" -> no.        "Rob" vs "Reena Pathak" -> no.
    """
    a, b = label.lower().split(), claim.lower().split()
    if a[0] == b[0]:
        return True
    return difflib.SequenceMatcher(None, label.lower(), claim.lower()).ratio() > 0.85


# A turn that begins mid-sentence means the diariser cut someone off and gave the
# tail to the next speaker. This is the one failure it can hide from every other
# check here: the NAMES all agree, and the ATTRIBUTION is still wrong. Measured
# across six real transcripts, a clean file sits at 2-7% and a badly split one at
# 12%. That gap is real but narrow, so this warns -- it never decides.
CLEAN_START = re.compile(r"^[A-Z\"'(\[0-9]")
FRAGMENT_WARN = 0.10


def fragmentation(texts: list) -> float:
    if not texts:
        return 0.0
    return sum(1 for t in texts if not CLEAN_START.match(t)) / len(texts)


def hand_verified(text: str) -> bool:
    head = text.splitlines()[:VERIFIED_SCAN_LINES]
    return any(VERIFIED.search(line) for line in head)


def analyse(path: pathlib.Path) -> dict:
    roster = load_roster()
    text = path.read_text(errors="replace")
    verified = hand_verified(text)
    labels = Counter()
    claims = defaultdict(set)
    turn_texts = []

    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        who, said = m.group(1), m.group(2)
        labels[who] += 1
        if said.strip():
            turn_texts.append(said.strip())
        for pat in SELF:
            for name in pat.findall(said):
                if name.split()[0] not in STOP:
                    claims[who].add(name)

    # Calibrate on the file before judging any individual speaker. Every
    # self-introduction is a test of the diariser: if they all agree with their
    # labels, the tool worked here and unlabelled speakers can be trusted. If
    # any contradicts, the tool is merging or mislabelling turns across the
    # whole file, so nothing in it can be trusted -- not just that one speaker.
    evidence, broken = [], []
    for label, names in claims.items():
        if len(names) > 1:
            broken.append(f"{label} claims to be {' and '.join(sorted(names))}")
            continue
        name = next(iter(names))
        if ANON.match(label):
            # A bare letter that introduces itself is the diariser not KNOWING a
            # name, not getting one wrong. That is a resolution, not a failure --
            # counting it as a contradiction would condemn the whole file.
            evidence.append(label)
        elif agrees(label, name):
            evidence.append(label)
        else:
            broken.append(f"{label} claims to be {name}")

    anon = bool(labels) and all(ANON.match(l) for l in labels)
    if verified:
        verdict = "verified"          # a human fixed the names. Nothing outranks this.
    elif anon:
        verdict = "anonymous"
    elif broken:
        verdict = "broken"
    elif evidence:
        verdict = "reliable"
    else:
        # Nobody introduced themselves. That is normal for a recurring internal
        # meeting and is NOT evidence the tool failed. Absence of evidence is
        # not evidence of absence -- so the labels are usable, but unproven,
        # and every page built from them must say so.
        verdict = "unverified"
    reliable = verdict == "reliable"

    speakers = []
    for label, turns in labels.most_common():
        said_names = sorted(claims.get(label, ()))
        entry = {"label": label, "turns": turns, "self_claims": said_names}

        if ANON.match(label) and not said_names:
            entry.update(status="ANONYMOUS", resolved=None,
                         handle=f"{label}@{path.stem}",
                         why="a letter, not a name. Letters are assigned per run by "
                             "speaking order, so this one means nothing outside "
                             "this file")
        elif len(said_names) > 1:
            entry.update(status="CONFLICT", resolved=None,
                         why="claims to be more than one person")
        elif said_names:
            name = said_names[0]
            canon = canonical_for(name, roster)
            if not agrees(label, name):
                entry.update(status="MISLABELLED", resolved=canon or name,
                             why=f"labelled {label!r} but says they are {name!r}; "
                                 "trust the self-introduction, not the label")
            elif canon:
                entry.update(status="CONFIRMED", resolved=canon,
                             why="self-introduced, and in schema/people.yml")
            else:
                near = near_matches(name, roster)
                entry.update(status="NEAR" if near else "NEW", resolved=name,
                             why="self-introduced; not in the roster" if not near
                                 else f"self-introduced; close to roster: {', '.join(near)}")
                if near:
                    entry["near"] = near
        else:
            canon = canonical_for(label, roster)
            if canon:
                entry.update(status="CONFIRMED", resolved=canon,
                             why="no self-introduction; label is in the roster")
            elif verdict == "verified":
                entry.update(status="HAND_VERIFIED",
                             resolved=canonical_for(label, roster) or label,
                             why="the owner tagged this file by hand; the label is "
                                 "ground truth and outranks every machine signal")
            elif verdict == "unverified":
                entry.update(status="LABEL_UNVERIFIED", resolved=label,
                             why="nobody introduced themselves in this file, so the "
                                 "label is unproven -- usable, but say so on the page")
            elif reliable:
                entry.update(status="LABEL_TRUSTED", resolved=label,
                             why="no self-introduction, but every self-introduction "
                                 "in this file matched its label, so the diarisation "
                                 "is reliable here")
            else:
                near = near_matches(label, roster)
                entry.update(status="UNVERIFIED", resolved=None,
                             why="no self-introduction, and this file's diarisation "
                                 "is not trustworthy")
                if near:
                    entry["near"] = near
        speakers.append(entry)

    bad = sum(1 for s in speakers
              if s["status"] in ("CONFLICT", "UNVERIFIED", "ANONYMOUS"))
    if verdict == "verified":
        bad = 0
    return {
        "file": path.name,
        "speakers": speakers,
        "diarisation": verdict,
        "evidence": f"{len(evidence)} self-introduction(s) matched their label",
        "contradictions": broken,
        "hand_verified": verified,
        "fragmentation": round(fragmentation(turn_texts), 3),
        "trustworthy": bad == 0,
        "unresolved": bad,
    }


def report(r: dict) -> None:
    print(f"=== {r['file']}")
    note = {
        "reliable":   r["evidence"],
        "broken":     f"{len(r['contradictions'])} contradiction(s) found",
        "anonymous":  "labels are letters, not names",
        "unverified": "nobody introduced themselves; labels unproven, not disproven",
        "verified":   "hand-tagged by the owner -- labels are ground truth",
    }[r["diarisation"]]
    print(f"    diarisation: {r['diarisation'].upper()}  ({note})")
    for c in r["contradictions"]:
        print(f"      contradiction: {c}")
    if r["unresolved"]:
        print(f"    {r['unresolved']} speaker(s) cannot be attributed")
    print()
    for s in r["speakers"]:
        to = s["resolved"] or s.get("handle") or "(do not attribute)"
        print(f"  {s['status']:<11} {s['label']:<18} {s['turns']:>4} turns  ->  {to}")
        print(f"              {s['why']}")
    if r.get("fragmentation", 0) >= FRAGMENT_WARN:
        print(f"\n  WARNING  {r['fragmentation']:.0%} of turns begin mid-sentence.")
        print("  The diariser is cutting turns and giving the tail to the next")
        print("  speaker. Names can all look right while attribution is wrong.")
        print("  Quote sparingly, and attribute only where the sense is obvious.")
    if any(sp["status"] == "ANONYMOUS" for sp in r["speakers"]):
        print("\n  Rule: for lettered speakers, compile the CONTENT and attribute")
        print("  NOTHING to a person. Do not guess identities from context.")
        print("  Letters are per-file. \"C\" here is NOT \"C\" in any other")
        print("  transcript -- the transcriber reassigns them by speaking order.")
        print("  Use the file-scoped handle above, never the bare letter.")
    elif r["diarisation"] == "unverified":
        print("\n  Labels are usable but unproven -- say so on the page.")
        print("  If YOU tagged this file by hand, add a line near the top saying")
        print("  \"# speakers verified\" and re-run. Lint will keep asking until")
        print("  you do, so forgetting is recoverable, not permanent.")
    elif not r["trustworthy"]:
        print("\n  Rule: do not write \"X said Y\" for any unresolved speaker.")
        print("  Attribute to the label, flag it, and propose a roster addition.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    p = pathlib.Path(args.transcript)
    if not p.exists():
        print(f"ERROR  {p} does not exist")
        return 2

    r = analyse(p)
    print(json.dumps(r, indent=2)) if args.json else report(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
