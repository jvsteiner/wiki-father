"""Which raw sources have no wiki page yet.

The obvious test -- does wiki/sources/<raw basename>.md exist -- is wrong, and
wrongly in both directions. It reported 25 pending when 21 were: four sources
had pages under a different slug (`omnigent-report.md` is compiled as
`2026-08-08-omnigent-report.md`, and a .pptx becomes a slugged title), so the
loop would have recompiled finished work and then stalled when the page it
expected never appeared.

Every source page carries `source_file:` in its frontmatter naming the raw file
it was compiled from. That is the authoritative link. Checked 2026-09-13: all
91 pages have it.

Usage:
  pending.py            one raw path per line, oldest first
  pending.py --count    just the number
  pending.py --stems    basenames instead of paths
"""
import argparse, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRONT = re.compile(r"^source_file:\s*(.+?)\s*$", re.M)


def compiled_sources() -> set[str]:
    out = set()
    for p in (ROOT / "wiki" / "sources").glob("*.md"):
        m = FRONT.search(p.read_text(errors="replace")[:2000])
        if m:
            out.add(m.group(1).strip().strip('"').strip("'"))
    return out


def pending() -> list[pathlib.Path]:
    done = compiled_sources()
    out = []
    for p in sorted((ROOT / "raw").rglob("*")):
        if not p.is_file() or p.name.startswith(".") or p.suffix == ".png":
            continue
        rel = str(p.relative_to(ROOT))
        if rel in done:
            continue
        # a converted twin and its original are one source: if either is
        # claimed by a page, neither is pending
        if any(str(pathlib.Path(d).with_suffix("")) == str(p.with_suffix("").relative_to(ROOT))
               for d in done):
            continue
        out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", action="store_true")
    ap.add_argument("--stems", action="store_true")
    a = ap.parse_args()
    ps = pending()
    if a.count:
        print(len(ps))
    else:
        for p in ps:
            print(p.stem if a.stems else p.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
