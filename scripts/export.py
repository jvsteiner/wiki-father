"""Copy the wiki out as a plain Obsidian vault, for someone else to read.

Markdown only, in the folders it already lives in. Nothing that is machinery:
no scripts, no raw sources, no manifest, no git, and not your .obsidian folder
either -- that carries your themes, your plugins and your open-tab layout, and
the recipient's Obsidian will make its own on first open.

Links survive the trip because every one of them is a bare [[wikilink]]. There
are no relative paths pointing outside wiki/, so nothing dangles once the folder
moves to another machine.

Usage:
  export.py                 -> ~/wiki-export-<date>/
  export.py --out DIR       somewhere else
  export.py --zip           also make DIR.zip, ready to send
"""
import argparse, datetime, pathlib, re, shutil, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "wiki"
SKIP_DIRS = {".obsidian", ".git", ".trash"}
SKIP_NAMES = {".DS_Store", ".gitkeep"}


def wanted(p: pathlib.Path) -> bool:
    if p.suffix != ".md":
        return False
    if p.name in SKIP_NAMES or ".bak" in p.name:
        return False
    return not any(part in SKIP_DIRS for part in p.relative_to(SRC).parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="destination folder")
    ap.add_argument("--zip", action="store_true", help="also write a .zip beside it")
    a = ap.parse_args()

    out = pathlib.Path(a.out).expanduser() if a.out else \
        pathlib.Path.home() / f"wiki-export-{datetime.date.today().isoformat()}"
    if out.exists():
        print(f"ERROR  {out} already exists — move it or pass --out")
        return 1

    files = sorted(p for p in SRC.rglob("*.md") if wanted(p))
    if not files:
        print("ERROR  nothing to export")
        return 1

    by_dir, total = {}, 0
    for f in files:
        rel = f.relative_to(SRC)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
        by_dir[rel.parent.as_posix()] = by_dir.get(rel.parent.as_posix(), 0) + 1
        total += f.stat().st_size

    print(f"EXPORTED  {len(files)} page(s), {total/1e6:.1f} MB")
    print(f"          {out}")
    for d in sorted(by_dir):
        print(f"            {'(root)' if d == '.' else d + '/':<12} {by_dir[d]:>4}")

    if a.zip:
        archive = out.with_suffix(".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out.rglob("*.md")):
                z.write(f, pathlib.Path(out.name) / f.relative_to(out))
        print(f"  ZIPPED  {archive}  ({archive.stat().st_size/1e6:.1f} MB)")

    # Say what the reader will trip over. Not a file in the vault -- the ask was
    # markdown only -- but the sender should know before they hand it over.
    text = " ".join(f.read_text(errors="replace") for f in files)
    temps = sorted(set(re.findall(r"TEMP_(?:PERSON|ORG)_[A-Za-z]+", text)))
    if temps:
        print()
        print(f"  NOTE  {len(temps)} unresolved placeholder(s) are visible in the export:")
        print(f"        {', '.join(temps[:6])}{' ...' if len(temps) > 6 else ''}")
        print("        They are real entities whose names are not confirmed. Say so,")
        print("        or resolve them first with scripts/resolve.py.")
    print()
    print("  Open the folder itself as a vault in Obsidian.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
