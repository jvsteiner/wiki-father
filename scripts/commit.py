"""Decide, after the agent has run, which sources actually got compiled.

Filing prepares. This commits. The split exists because they used to be one
step: file.py wrote the manifest entry and archived the inbox copy to _done
before the model had started. A source that was filed and never compiled was
then marked as seen forever -- re-dropping it matched the byte hash and was
skipped, while the inbox copy had already been moved away. Measured 2026-09-13:
64 sources sat in exactly that state, invisible to the only path the owner uses.

The test is pending.py's, imported rather than reimplemented. This file
originally asked "does wiki/sources/<raw stem>.md exist" -- a filename match,
which is the exact bug already fixed once in pending.py and then rewritten here
from scratch. It cost three finished sources: the model had compiled
2026-07-30-acme-sync as `2026-07-30-acme-governance-layers`, a better
name, and the filename test called that a failure and pushed the file back into
the inbox. Re-dropping it would have produced a second page for one transcript.

A page records the raw file it came from in its `source_file:` frontmatter. That
is the only link that survives the model choosing its own slug, so it is the only
test either script may use.

  compiled     -> write the manifest entry, move the held copy to inbox/_done/
  not compiled -> move the held copy back to inbox/, record nothing

Putting it back in the inbox is the point. The next watcher run picks it up
without anyone having to know it failed, and there is no second code path to
maintain for recovering from a half-finished run.

Usage:
  commit.py            commit what is in .state/inflight.jsonl
  commit.py --check    say what it would do, change nothing
"""
import argparse, json, pathlib, shutil, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pending import compiled_sources          # one definition of "compiled"

ROOT = pathlib.Path(__file__).resolve().parent.parent
INFLIGHT = ROOT / ".state" / "inflight.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only")
    args = ap.parse_args()

    if not INFLIGHT.exists():
        print("  nothing in flight")
        return 0

    records = [json.loads(l) for l in INFLIGHT.read_text().splitlines() if l.strip()]
    if not records:
        print("  nothing in flight")
        return 0

    done_dir = ROOT / "inbox" / "_done"
    inbox = ROOT / "inbox"
    kept, returned = [], []
    claimed = compiled_sources()      # every raw path named by a page

    for r in records:
        held = ROOT / r["held"]
        raw = ROOT / r["raw"]
        # compiled means SOME page claims this raw file, whatever it called
        # itself -- not that a page happens to share its filename
        if r["raw"] in claimed:
            kept.append(r["stem"])
            if args.check:
                continue
            subprocess.run([sys.executable, str(ROOT / "scripts" / "dedupe.py"),
                            "add", str(raw), "--bytes", str(held),
                            "--origin", r["origin"]],
                           capture_output=True, text=True)
            if held.exists():
                done_dir.mkdir(exist_ok=True)
                dest = done_dir / held.name
                n = 1
                while dest.exists():
                    dest = done_dir / f"{held.stem} ({n}){held.suffix}"
                    n += 1
                shutil.move(str(held), dest)
        else:
            returned.append(r["stem"])
            if args.check:
                continue
            # No page, so nothing is recorded and the original goes back where
            # the owner put it. Leaving raw/ in place is deliberate: it costs a few
            # KB and saves re-converting a PDF on the retry.
            if held.exists():
                dest = inbox / held.name
                n = 1
                while dest.exists():
                    dest = inbox / f"{held.stem} ({n}){held.suffix}"
                    n += 1
                shutil.move(str(held), dest)

    verb = "would commit" if args.check else "COMMITTED"
    print(f"  {verb}  {len(kept)} compiled")
    for s in kept[:5]:
        print(f"      {s}")
    if len(kept) > 5:
        print(f"      ... and {len(kept) - 5} more")
    if returned:
        verb = "would return" if args.check else "RETURNED TO INBOX"
        print(f"  {verb}  {len(returned)} with no page — they will be retried")
        for s in returned[:5]:
            print(f"      {s}")
        if len(returned) > 5:
            print(f"      ... and {len(returned) - 5} more")

    if not args.check:
        INFLIGHT.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
