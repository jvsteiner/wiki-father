#!/usr/bin/env python3
"""Is this source backstory? Which existing pages does it predate?

Sources arrive in whatever order they get dropped, which is not the order things
happened. A source that predates pages already written is BACKSTORY: it may
explain, qualify or overturn conclusions that were reached without it.

Nothing else catches this. The pending-source trick finds files nobody compiled;
it cannot find a conclusion that a newly-arrived older document undermines.

Walks TWO levels from the pages you name -- the pages themselves, then the pages
they link to. The owner's call: deep enough to catch the knock-on, shallow enough to
stay readable.

Usage:
  backstory.py --date 2026-07-02 --pages attractor,deterministic-policy-layer
"""

import argparse
import datetime as dt
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
LINK = re.compile(r"\[\[([^\]|#]+)")
ISO = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
DEPTH = 2


def page(slug: str):
    hits = list(WIKI.rglob(f"{slug.strip()}.md"))
    return hits[0] if hits else None


def source_date(p: pathlib.Path):
    m = re.search(r"^source_date:\s*(20\d{2}-\d{2}-\d{2})", p.read_text(), re.M)
    return dt.date.fromisoformat(m.group(1)) if m else None


def expand(slugs: list) -> dict:
    """slug -> how many links away it is (0 = you named it)."""
    seen, frontier = {}, [(s.strip(), 0) for s in slugs if s.strip()]
    while frontier:
        slug, d = frontier.pop(0)
        if slug in seen and seen[slug] <= d:
            continue
        seen[slug] = d
        if d >= DEPTH:
            continue
        p = page(slug)
        if not p:
            continue
        for t in LINK.findall(p.read_text()):
            t = t.strip()
            if not t.startswith("raw/"):
                frontier.append((t, d + 1))
    return seen


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="the new source's source_date")
    ap.add_argument("--pages", required=True, help="comma-separated slugs it touches")
    args = ap.parse_args()

    try:
        new = dt.date.fromisoformat(args.date)
    except ValueError:
        print(f"ERROR  {args.date} is not YYYY-MM-DD")
        return 2

    reach = expand(args.pages.split(","))
    findings = []
    for slug, depth in sorted(reach.items(), key=lambda x: (x[1], x[0])):
        p = page(slug)
        if not p:
            continue
        text = p.read_text()
        # frontmatter holds page metadata (updated:, source_date:), not claims.
        # Counting "updated:" as a claim the source predates is a false positive.
        body = text.split("---", 2)[2] if text.startswith("---") else text
        newer = sorted({d for d in ISO.findall(body)
                        if dt.date.fromisoformat(d) > new})
        sd = source_date(p)
        if sd and sd > new:
            newer.append(f"{sd.isoformat()} (this whole source)")
        if newer:
            findings.append((slug, depth, sorted(set(newer))))

    total_pages = len(list(WIKI.rglob("*.md")))
    print(f"New source dated {new.isoformat()}")
    print(f"Reached {len(reach)} page(s) within {DEPTH} links of what you named.")
    # This tool trusts the page list it is given. Hand it the wrong pages and it
    # produces confident noise -- which happened on the first real run.
    if total_pages and len(reach) > total_pages * 0.5:
        print(f"\n  WARNING  that is over half the wiki ({total_pages} pages).")
        print("  Did you actually search first? A source rarely touches everything.")
        print("  Re-run with only the pages the search returned.")
    print()
    if not findings:
        print("  NOT BACKSTORY -- nothing reached is newer. Compile normally.")
        return 0

    total = sum(len(f[2]) for f in findings)
    print(f"  BACKSTORY -- it predates {total} dated claim(s) on {len(findings)} page(s).")
    print("  Re-read these BEFORE writing. Ask of each: does this older source")
    print("  explain, qualify or overturn what is already written?\n")
    for slug, depth, dates in findings:
        near = "named" if depth == 0 else f"{depth} link{'s' if depth>1 else ''} away"
        print(f"    {slug}  ({near})")
        print(f"        newer dates on the page: {', '.join(dates[:6])}"
              + (" …" if len(dates) > 6 else ""))
    print("\n  Record what changed on each page you revise, and say in your report")
    print("  which conclusions survived the new evidence and which did not.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
