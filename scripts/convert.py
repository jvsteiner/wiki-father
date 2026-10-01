#!/usr/bin/env python3
"""Convert a dropped file to markdown for compiling.

The original is never modified and never discarded. Binary formats get a `.md`
twin beside them with the same basename; the agent reads the twin.

Tools chosen against real files, no new dependencies:
  .pdf   pdftotext -layout, plus pdfimages for figures that text extraction drops
  .pptx  python-pptx -- slides, tables AND speaker notes, which markitdown misses
  .docx  pandoc
  .md .txt  passthrough

Usage:
  convert.py <file> [--out-dir DIR]
"""

import argparse
import pathlib
import shutil
import subprocess
import sys

TEXT = {".md", ".txt", ".markdown"}


def pdf(src: pathlib.Path, out: pathlib.Path) -> str:
    subprocess.run(["pdftotext", "-layout", str(src), str(out)],
                   check=True, capture_output=True)
    body = out.read_text(errors="replace")
    # Diagrams are lost by text extraction. Pull them out beside the markdown so
    # they can be viewed separately -- an LLM cannot read a markdown file and its
    # inline images in one pass anyway, so a sidecar folder is the honest shape.
    figs = out.parent / f"{out.stem}-figures"
    figs.mkdir(exist_ok=True)
    try:
        subprocess.run(["pdfimages", "-png", "-p", str(src), str(figs / "fig")],
                       check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    imgs = sorted(figs.glob("*.png"))
    if imgs:
        body += ("\n\n---\n\n## Figures\n\n"
                 "Extracted from the PDF; text extraction drops them.\n\n"
                 + "\n".join(f"- `{i.relative_to(out.parent)}`" for i in imgs) + "\n")
    else:
        shutil.rmtree(figs, ignore_errors=True)
    out.write_text(body)
    return f"{len(body.split())} words, {len(imgs)} figures"


def pptx(src: pathlib.Path, out: pathlib.Path) -> str:
    from pptx import Presentation
    deck, parts, notes, count = Presentation(str(src)), [], 0, 0
    for i, slide in enumerate(deck.slides, 1):
        count = i
        parts.append(f"## Slide {i}")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text.strip())
            if shape.has_table:
                rows = [" | ".join(c.text.strip() for c in r.cells)
                        for r in shape.table.rows]
                if rows:
                    parts.append(rows[0])
                    parts.append(" | ".join("---" for _ in shape.table.columns))
                    parts.extend(rows[1:])
        if slide.has_notes_slide:
            n = slide.notes_slide.notes_text_frame.text.strip()
            if n:
                parts.append(f"_Speaker notes:_ {n}")
                notes += 1
    out.write_text("\n\n".join(parts) + "\n")
    return f"{count} slides, {notes} with notes"


def docx(src: pathlib.Path, out: pathlib.Path) -> str:
    subprocess.run(["pandoc", "-t", "gfm", "-o", str(out), str(src)],
                   check=True, capture_output=True)
    return f"{len(out.read_text(errors='replace').split())} words"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--out-dir")
    args = ap.parse_args()

    src = pathlib.Path(args.file)
    if not src.exists():
        print(f"ERROR  {src} does not exist")
        return 2
    out_dir = pathlib.Path(args.out_dir) if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()

    if ext in TEXT:
        print(f"PASSTHROUGH  {src.name}  (already text)")
        return 0

    out = out_dir / f"{src.stem}.md"
    handler = {".pdf": pdf, ".pptx": pptx, ".docx": docx}.get(ext)
    if not handler:
        print(f"ERROR  no converter for {ext}")
        return 2
    try:
        detail = handler(src, out)
    except Exception as e:
        print(f"FAILED  {src.name}: {e}")
        return 1
    print(f"CONVERTED  {src.name} -> {out.name}  ({detail})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
