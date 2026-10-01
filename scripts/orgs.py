#!/usr/bin/env python3
"""Resolve organisation names in a source against schema/orgs.yml.

Transcribers mangle company names harder than personal names, because company
names are often unusual words. One customer appeared as five different spellings
across three transcripts -- Illyria, Elyria, Valyria, Alleria, Olivia -- and all
five were wrong. The correct name is Aleria.

A wiki that files the same customer under five names is not a wiki, it is five
customers. So the arithmetic is done here and the judgement is left to the agent.

Usage:
  scripts/orgs.py <file>
"""

import argparse
import difflib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROSTER = ROOT / "schema" / "orgs.yml"
# a capitalised word, or two, that is not at the start of a sentence
CANDIDATE = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{3,})\b", re.M)


def load() -> list:
    """Tiny parser -- deliberately no yaml dependency."""
    if not ROSTER.exists():
        return []
    orgs, cur = [], None
    for raw in ROSTER.read_text().splitlines():
        line = raw.strip()
        if line.startswith("#") or not line:
            continue
        if line.startswith("- canonical:"):
            cur = {"canonical": line.split(":", 1)[1].strip(), "aliases": []}
            orgs.append(cur)
        elif cur and line.startswith("aliases:"):
            body = line.split(":", 1)[1].strip().strip("[]")
            cur["aliases"] = [a.strip() for a in body.split(",") if a.strip()]
    return orgs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    args = ap.parse_args()

    src = pathlib.Path(args.file)
    if not src.exists():
        print(f"ERROR  {src} does not exist")
        return 2

    orgs = load()
    if not orgs:
        print("No roster at schema/orgs.yml -- nothing to resolve against.")
        return 0

    text = src.read_text(errors="replace")
    known = {a: o["canonical"] for o in orgs for a in o["aliases"]}
    known.update({o["canonical"]: o["canonical"] for o in orgs})

    hits, near = {}, {}
    for word in set(CANDIDATE.findall(text)):
        if word in known:
            if known[word] != word:
                hits.setdefault(known[word], set()).add(word)
        else:
            m = difflib.get_close_matches(word, list(known), n=1, cutoff=0.80)
            if m:
                near.setdefault(known[m[0]], set()).add(word)

    print(f"=== {src.name}")
    if hits:
        print("\n  RESOLVED  a known misspelling -- use the canonical name:")
        for canon, spellings in sorted(hits.items()):
            print(f"    {', '.join(sorted(spellings)):<32} -> {canon}")
    if near:
        print("\n  NEAR  looks like a roster entry but is not listed.")
        print("        Judgement needed -- propose a roster addition, do not assume:")
        for canon, spellings in sorted(near.items()):
            print(f"    {', '.join(sorted(spellings)):<32} ~= {canon}?")
    if not hits and not near:
        print("  No roster organisations found under a wrong spelling.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
