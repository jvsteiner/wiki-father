"""Is a source page carrying evidence, or just assertions?

Written because the ad-hoc greps used on 2026-09-13 were wrong in both
directions and both of us drew conclusions from them. They matched only
straight ASCII quotes, so every page using typographic quotes scored zero --
including good ones -- and a page was called empty when it was fine. They also
compared quote text to the transcript literally, so a page trimming "um" out of
a quotation scored as unverified.

What it measures, per page:
  evidence    quoted passages, counting BOTH "..." and typographic quotes, plus
              blockquote lines, which is the form CLAUDE.md's template uses
  verified    of those, how many appear in the transcript the page names. The
              comparison is whitespace- and quote-normalised, and a hit needs a
              40-character run to match, so light trimming still counts
  links       [[targets]] outside the frontmatter -- compiling means writing
              ACROSS sources, and a page that links nothing integrated nothing

There is no pass mark here on purpose. Print the corpus, look at the spread,
and judge against pages you already trust.

Usage:
  quality.py                 every source page
  quality.py <slug> ...      just these
  quality.py --bad           only pages with no evidence at all
"""
import argparse, pathlib, re, sys, unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "wiki" / "sources"
FRONT = re.compile(r"^source_file:\s*(.+?)\s*$", re.M)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s)
    for a, b in (("“", '"'), ("”", '"'), ("‘", "'"),
                 ("’", "'"), ("—", " "), ("–", " "), ("…", " ")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).lower()


def evidence(text: str) -> list[str]:
    body = text.split("---", 2)[-1]          # drop frontmatter
    out = re.findall(r'["“]([^"”]{25,400})["”]', body)
    for line in body.splitlines():           # blockquotes are evidence too
        t = line.lstrip("> ").strip(" *_")
        if line.lstrip().startswith(">") and len(t) >= 25:
            out.append(t)
    seen, uniq = set(), []
    for q in out:
        k = norm(q)[:60]
        if k not in seen:
            seen.add(k); uniq.append(q)
    return uniq


def report(page: pathlib.Path):
    text = page.read_text(errors="replace")
    m = FRONT.search(text[:2000])
    raw = ROOT / m.group(1).strip() if m else None
    rt = norm(raw.read_text(errors="replace")) if raw and raw.exists() else ""
    ev = evidence(text)
    ver = sum(1 for q in ev if norm(q)[:40] in rt) if rt else 0
    body = text.split("---", 2)[-1]
    links = len(set(re.findall(r"\[\[([^\]]+)\]\]", body)))
    return (page.stem, len(text.splitlines()), len(ev), ver, links, bool(rt))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--bad", action="store_true", help="only pages with zero evidence")
    a = ap.parse_args()

    pages = [SRC / f"{s}.md" for s in a.slugs] if a.slugs else sorted(SRC.glob("*.md"))
    rows = [report(p) for p in pages if p.exists()]
    if a.bad:
        rows = [r for r in rows if r[2] == 0]

    print(f"{'page':<46} {'ln':>4} {'evid':>5} {'ver':>4} {'link':>5}  raw")
    print("-" * 78)
    for s, ln, ev, ver, lk, hr in rows:
        print(f"{s:<46} {ln:>4} {ev:>5} {ver:>4} {lk:>5}  {'ok' if hr else 'MISSING'}")
    if rows:
        n = len(rows)
        print("-" * 78)
        print(f"{n} page(s)   median evidence {sorted(r[2] for r in rows)[n//2]}   "
              f"zero-evidence {sum(1 for r in rows if r[2] == 0)}   "
              f"zero-links {sum(1 for r in rows if r[4] == 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
