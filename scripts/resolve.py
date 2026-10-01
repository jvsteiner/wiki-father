#!/usr/bin/env python3
"""Placeholders for entities you cannot name yet, and the rename that fixes them.

The problem this solves: when a transcript garbles a name, writing "a customer
said" loses the thread. Two pages saying "a customer" cannot be linked, and you
cannot tell later whether they meant the same one.

So instead of prose, use a token: TEMP_ORG_Veltrona, TEMP_PERSON_Mikko. Every
page that means that entity uses the same token, the roster holds the candidate
spellings and where each was seen, and the whole thing accumulates facts about
an entity nobody has named yet.

When the owner confirms the real name, resolution is a mechanical replacement across
the wiki -- including renaming the entity's page -- not a rewrite.

Usage:
  resolve.py list                        what is still unresolved, and where
  resolve.py resolve <TOKEN> "<Name>"    replace everywhere, rename the page
"""

import argparse
import pathlib
import datetime
import re
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
TOKEN = re.compile(r"\bTEMP_(ORG|PERSON)_([A-Za-z0-9_]+)\b")


# A token stays "unresolved" only where it is still standing in for the entity.
# Two kinds of mention are history, not a live placeholder, and counting them
# meant a resolved entity never left the list:
#   - wiki/log.md is an append-only record of what happened
#   - `TEMP_PERSON_X` in backticks is talking ABOUT the token, e.g. the name note
#     left on the page after resolution
HISTORY = {"log.md", "timeline.md"}


def scan() -> dict:
    found = {}
    for p in sorted(WIKI.rglob("*.md")):
        if p.name in HISTORY:
            continue
        text = p.read_text(errors="replace")
        for m in TOKEN.finditer(text):
            i, j = m.span()
            quoted = (text[i-1:i] == "`" and text[j:j+1] == "`")
            if quoted:
                continue
            found.setdefault(m.group(0), set()).add(p.relative_to(ROOT).as_posix())
    return found


def candidates(token: str) -> list:
    """Candidate spellings recorded for a token in either roster."""
    out = []
    for roster in ("people.yml", "orgs.yml"):
        f = ROOT / "schema" / roster
        if not f.exists():
            continue
        block, hit = [], False
        for line in f.read_text().splitlines():
            if line.strip().startswith("- placeholder:"):
                hit = line.split(":", 1)[1].strip() == token
                block = []
            elif hit and line.strip().startswith("candidates:"):
                body = line.split(":", 1)[1].strip().strip("[]")
                out += [c.strip() for c in body.split(",") if c.strip()]
                hit = False
    return out


def cmd_list(args) -> int:
    found = scan()
    if not found:
        print("Nothing unresolved. Every entity in the wiki has a real name.")
        return 0
    print(f"{len(found)} unresolved entit{'y' if len(found)==1 else 'ies'}:\n")
    for token, files in sorted(found.items()):
        cands = candidates(token)
        print(f"  {token}")
        if cands:
            print(f"      seen spelled: {', '.join(cands)}")
        print(f"      on {len(files)} page(s): {', '.join(sorted(files)[:4])}")
        print()
    print("Resolve one with:")
    print('  python3 scripts/resolve.py resolve <TOKEN> "The Real Name"')
    return 0


def roster_for(token: str):
    """(file, list-key) for a token's roster."""
    if token.startswith("TEMP_ORG_"):
        return ROOT / "schema" / "orgs.yml", "orgs"
    return ROOT / "schema" / "people.yml", "people"


def merge_pages(token_page, target_page, token: str, name: str) -> None:
    """Fold a placeholder page into the real one, losing nothing, deciding nothing.

    The two pages are separate accounts of one entity, written at different
    times from different sources. They can contradict each other, and on this
    wiki a contradiction is content: it gets recorded, dated and left visible,
    not smoothed away. So this does the mechanical half only -- both pages are
    backed up, the placeholder's body is appended under a heading that says it
    is unreconciled, and the placeholder file is removed so the sweep that
    follows does not trip over it.

    Reading the two accounts and reconciling them is a judgement call, and it
    stays with a person.
    """
    stamp = datetime.date.today().isoformat()
    for f in (token_page, target_page):
        shutil.copy2(f, f.with_suffix(f".md.bak-{stamp}"))

    body = token_page.read_text(errors="replace")
    # drop the placeholder's frontmatter; the target page keeps its own
    if body.startswith("---"):
        parts = body.split("---", 2)
        body = parts[2] if len(parts) > 2 else body
    # its H1 becomes a sub-heading so the merged page keeps one title
    body = re.sub(r"^#\s+.*$", "", body, count=1, flags=re.M).strip()

    target_page.write_text(
        target_page.read_text(errors="replace").rstrip()
        + f"\n\n## Merged from `{token}` — NOT YET RECONCILED *({stamp})*\n\n"
        + f"> Everything below arrived under the placeholder `{token}` before\n"
        + f"> anyone knew it was {name}. It has not been checked against what is\n"
        + f"> above it. Where the two disagree, both readings stand until someone\n"
        + f"> settles it -- do not delete either side to make the page tidy.\n\n"
        + body + "\n")

    token_page.unlink()
    print(f"  MERGED    {token_page.relative_to(ROOT)}")
    print(f"         -> {target_page.relative_to(ROOT)}  "
          f"(both backed up as .md.bak-{stamp})")
    print(f"         section '## Merged from `{token}` — NOT YET RECONCILED' "
          f"awaits a human")


def update_roster(token: str, name: str) -> tuple:
    """Move an `unresolved:` entry into the real list.

    schema/ is the owner's ground truth and an agent may never DECIDE what goes in
    it. This is not that: the canonical name arrived on the command line, from
    them. The script transcribes a decision they already made.

    Requiring a flag to do it would just recreate the friction it removes -- a
    paste you have to remember is a paste that does not happen -- so this runs by
    default. `--no-roster` opts out. The file is backed up first, every time.
    """
    path, key = roster_for(token)
    if not path.exists():
        return None, "no roster file"
    text = path.read_text()
    lines = text.splitlines()

    # pull the unresolved block, keeping its candidates and role
    start = next((i for i, l in enumerate(lines)
                  if l.strip() == f"- placeholder: {token}"), None)
    cands, role = "", ""
    if start is not None:
        end = start + 1
        while end < len(lines) and not (
                lines[end].strip().startswith("- placeholder:")
                or (lines[end] and not lines[end][0].isspace())):
            end += 1
        block = lines[start:end]
        for l in block:
            t = l.strip()
            if t.startswith("candidates:"):
                cands = t.split(":", 1)[1].strip()
            elif t.startswith("role:"):
                role = t.split(":", 1)[1].strip()
        del lines[start:end]

    entry = [f"  - canonical: {name}"]
    if cands:
        entry.append(f"    aliases: {cands}")
    entry.append("    note: |")
    entry.append(f"      Confirmed by the owner. Resolved from {token}.")
    if role:
        entry.append(f"      {role}")

    # insert at the end of the real list: just before the next top-level key,
    # or the "Unresolved" comment banner, whichever comes first
    anchor = next((i for i, l in enumerate(lines) if l.strip() == f"{key}:"), None)
    if anchor is None:
        return None, f"no `{key}:` key in {path.name}"
    i = anchor + 1
    while i < len(lines):
        l = lines[i]
        if l.strip().startswith("# ──") or (l and not l[0].isspace() and l.strip()):
            break
        i += 1
    while i > anchor + 1 and not lines[i - 1].strip():
        i -= 1
    lines[i:i] = entry + [""]

    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(text)
    path.write_text("\n".join(lines).rstrip() + "\n")
    return path, backup


def cmd_resolve(args) -> int:
    token, name = args.token, args.name
    if not TOKEN.fullmatch(token):
        print(f"ERROR  {token} is not a TEMP_ORG_x / TEMP_PERSON_x token")
        return 2
    found = scan()
    if token not in found:
        print(f"ERROR  {token} does not appear anywhere in wiki/")
        return 2

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    # A placeholder can turn out to be someone the wiki ALREADY has a page for.
    # TEMP_PERSON_Philippe is Filipe Martins, who has a 197-line page. The
    # rename below used pathlib.rename, which silently replaces its target, so
    # a 24-line stub would have overwritten that page with no error and no
    # backup. Refuse instead, and offer the merge explicitly.
    do_merge = False
    token_page = next(iter(WIKI.rglob(f"{token}.md")), None)
    target_page = next((q for q in WIKI.rglob(f"{slug}.md")), None)
    if token_page and target_page and token_page != target_page:
        if not args.merge:
            print(f"REFUSED  {name} already has a page:")
            print(f"           {target_page.relative_to(ROOT)}  "
                  f"({len(target_page.read_text().splitlines())} lines)")
            print(f"         and {token} has one too:")
            print(f"           {token_page.relative_to(ROOT)}  "
                  f"({len(token_page.read_text().splitlines())} lines)")
            print()
            print("  These are two accounts of one entity and they may disagree,")
            print("  which is content, not error. Nothing has been changed.")
            print()
            print("  To merge, re-run with --merge. That keeps the existing page,")
            print("  appends the placeholder's content to it under a heading that")
            print("  says it is unreconciled, backs both up, and then does the")
            print("  usual sweep. Reconciling the two accounts is YOUR job after,")
            print("  not the script's -- it will not silently pick a winner.")
            return 3
        do_merge = True

    cands = ""
    changed = []
    for p in sorted(WIKI.rglob("*.md")):
        s = p.read_text(errors="replace")
        if token not in s:
            continue
        # [[TEMP_x]] becomes [[slug]]; bare TEMP_x becomes the display name
        s = s.replace(f"[[{token}]]", f"[[{slug}]]").replace(token, name)
        p.write_text(s)
        changed.append(p.relative_to(ROOT).as_posix())

    # rename the entity's own page, and stop it claiming to be unresolved.
    # The first version only swapped text, so the page kept its "Name not
    # confirmed" banner and its placeholder frontmatter after being resolved --
    # real cleanup the script left silent and the operator nearly missed.
    renamed = None
    if do_merge:
        merge_pages(token_page, target_page, token, name)
        token_page = None
    for pg in list(WIKI.rglob(f"{token}.md")):
        target = pg.with_name(f"{slug}.md")
        pg.rename(target)
        body = target.read_text()
        cands = ""
        m = re.search(r"^candidates:\s*(\[.*?\])", body, re.M)
        if m:
            cands = m.group(1)
        # frontmatter: placeholder -> canonical
        body = re.sub(r"^status:\s*unresolved\n", "", body, flags=re.M)
        body = re.sub(r"^placeholder:.*\n", f"canonical: {name}\n", body, flags=re.M)
        body = re.sub(r"^candidates:\s*\[(.*?)\]",
                      lambda mm: f"aliases: [{name}, {mm.group(1)}]", body, flags=re.M)
        # body: swap the "not confirmed" banner for a name note
        body = re.sub(
            r"> \*\*Name not confirmed\.\*\*.*?(?=\n\n)",
            f"> **Name note.** Confirmed by the owner. Seen in sources as {cands or 'variants'};\n"
            f"> resolved from `{token}`. The roster now carries those as aliases, so\n"
            f"> future sources resolve on their own.",
            body, flags=re.S)
        target.write_text(body)
        renamed = target.relative_to(ROOT).as_posix()

    print(f"RESOLVED  {token}  ->  {name}")
    print(f"  {len(changed)} page(s) updated")
    for c in changed:
        print(f"    {c}")
    if renamed:
        print(f"  page renamed -> {renamed}")
    if args.no_roster:
        path, key = roster_for(token)
        print(f"  roster    NOT updated (--no-roster). Paste into {path.name}:")
        print(f"              - canonical: {name}")
        if cands:
            print(f"                aliases: {cands}")
    else:
        path, backup = update_roster(token, name)
        if path is None:
            print(f"  roster    NOT updated: {backup}")
        else:
            print(f"  roster    {path.relative_to(ROOT)} updated "
                  f"(backup: {backup.name})")
            print(f"            future sources now resolve these on their own")

    print()
    print("STILL TO DO, because it is judgement rather than replacement:")
    print()
    print("  1. `wiki/index.md` still groups this entity under \"names")
    print("     unconfirmed\". Move it to the right line.")
    print()
    print("  2. Append a log line. Use the `lint` op — `resolve` is not one of")
    print("     the ops CLAUDE.md allows:")
    print(f"       ## [<today>] lint | {token} resolved to {name}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list", help="show unresolved entities")
    l.set_defaults(fn=cmd_list)
    r = sub.add_parser("resolve", help="replace a token with the real name")
    r.add_argument("token")
    r.add_argument("name")
    r.add_argument("--no-roster", action="store_true",
                   help="do not touch schema/; print the entry to paste instead")
    r.add_argument("--merge", action="store_true",
                   help="the name already has a page: fold the placeholder page "
                        "into it instead of refusing. Backs both up first and "
                        "marks the joined section as unreconciled.")
    r.set_defaults(fn=cmd_resolve)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
