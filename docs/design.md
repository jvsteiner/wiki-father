# Personal LLM Wiki — design

Background: why the machinery is shaped the way it is. Read it when a rule
seems odd. Every number here was measured on a real wiki of a few hundred
sources.

## What this is

A personal knowledge base following the LLM Wiki pattern described by Andrej
Karpathy (gist, 2026). Documents are compiled once into a persistent, interlinked
markdown wiki, rather than re-read from scratch on every question as RAG does.
The knowledge compounds; the maintenance cost is carried by the agent.

Claude Code is the writer. Obsidian is the reader. Git is the safety net.

## Why not WikiBrain

WikiBrain (github.com/wikibrain-app/wikibrain) is a faithful, well-tested hosted
implementation of the same pattern — AGPL, ~5.2k lines of server code, ~3.1k
lines of tests, genuinely careful prompt-injection handling. It was assessed and
rejected for this use, not on quality, but because it stores notes in PostgreSQL
rather than files. That trades away git and Obsidian-as-editor, which are the two
things this setup already has. Its split of Lint into cheap structural checks
plus agent judgement was adopted here, as was its "pending source" trick.

## Scope

In scope as sources: call and meeting transcripts, web clippings, papers and
articles, and office documents (PDF, Word, PowerPoint).

Explicitly out of scope: anything that already lives somewhere better — an
existing notes vault, code repositories, chat history. This is a new and
separate vault.

Expected volume: 100–500 documents. This sits inside the range where a plain
`index.md` works, so no search engine is built. `ripgrep` is the fallback.
`qmd` is deferred until the index demonstrably fails.

## Location and privacy

The repository folder (`~/wiki` by convention), a local git repository with
**no remote** by default. Nothing to push, nothing to
leak. An off-machine backup would need a private remote added deliberately, as a
separate decision.

## Layout

```
<repo>/
  CLAUDE.md            the rules. human-owned. agents never edit it.
  inbox/               drop zone. any file type. empties as work completes.
  raw/                 sources, read-only forever
    transcripts/
    documents/         original pdf/docx/pptx + its .md twin
    clippings/
  wiki/                every page written by the agent
    index.md           catalog
    log.md             append-only diary
    projects/          status, decisions, open questions
    concepts/          the join between projects
    people/            decisions and commitments by person
    sources/           one summary page per raw source
    queries/           good answers, filed back
    lint/              health-check reports
  docs/design.md       this file
  .claude/settings.json  deny rules
```

## The spine: concepts join projects

Chosen over "projects are the spine" and "concepts only".

Project pages hold state. Concept pages hold shared ideas and name which projects
touch them. A concept page is where interrelation is written *down* rather than
re-derived per query, so it improves every time a source touches it.

The governing rule:

> A concept earns its own page the moment a second project touches it.
> Until then it lives as a section on the one project page that cares.

This is cheap to check, prevents concept sprawl, and points directly at the
stated need (cross-project recall). It is enforced mechanically by the lint
script, which finds concepts named on two or more project pages that have no
page of their own.

The highest-value section in the vault is `## Where they disagree` on a concept
page. It is the thing retrieval cannot produce.

## Document lifecycle

```
inbox/  ->  convert  ->  move to raw/  ->  compile wiki pages
```

The move happens **before** compiling, deliberately. If compiling fails, the file
is safely in `raw/` with no wiki page linking to it — which is itself the
definition of "not yet compiled". No status file, no flags, nothing to desync.
The lint pass finds these and picks them back up.

Office files are converted once. The original is kept; a `.md` twin sits beside
it with the same basename. The agent reads the twin.

## Automatic ingest

Chosen by the user over supervised ingest, with the risks stated and accepted.
It is made safe by construction rather than by supervision.

**Trigger:** `launchd` with `WatchPaths` on `inbox/`. Debounce ~60s so a batch
drag is one run. Fires `claude -p` headless in the wiki folder (or `codex exec`) with `--max-turns` set.

**Every run:** commit anything outstanding, do the work, commit again with
`ingest: <filename>`, notify on the desktop.

### Guard rails

1. **Every run is one git commit.** The user is not in the loop at the time, so
   they are in the loop afterwards. `git log` is the complete record. `git diff`
   shows any run. `git revert` undoes a bad one. Nothing is silently lost.

2. **Deny rules in `.claude/settings.json`**, not prompt requests. The agent
   cannot use Edit or Write on `CLAUDE.md`, on `raw/**`, or on `.claude/**`.
   `CLAUDE.md` matters most: it is read at the start of every future run, so a
   successful injection there would apply to every later document, including ones
   the attacker never touched.

3. **Source text is labelled as data** where it is handed over, and the agent is
   told to report anything that reads as an instruction. A label is not a
   guarantee; it is one more thing an attack must defeat, and it costs nothing.

4. **A step cap** via `--max-turns`, so a confused run burns a known amount.

### Residual risk, stated plainly

An agent with write tools processes documents the user did not write, unattended.
The guard rails reduce the blast radius to one revertible commit inside a folder
holding only notes. That is small, not zero. Mitigation depends on the wiki folder
containing no credentials and no secrets. Keep it that way.

Note also: the deny rules bind the Edit and Write tools. A Bash command could
still write to `raw/`. Git remains the backstop for that case.

## Deduplication

The user will re-drop files they have already ingested. This is expected, not an
edge case, so it is handled before anything else in the pipeline.

`scripts/dedupe.py` runs three checks, cheapest first:

| # | Check | Catches |
|---|---|---|
| 1 | SHA-256 of raw bytes | The same file dropped again |
| 2 | SHA-256 of normalised text | Re-exports, format changes, PDF → docx |
| 3 | Jaccard overlap of 4-word shingles | A name corrected, a paragraph edited |

Check 1 runs before conversion, so an obvious repeat costs nothing. Check 2
catches a re-wrapped or re-exported file whose bytes differ entirely.

The fuzzy check compares against the stored markdown in `raw/` directly rather
than against a stored sketch. At 100–500 documents this is fast, the scores are
exact rather than estimated, the manifest stays tiny, and a lost manifest costs
only the hashes — the fuzzy check still works from the files.

### Measured calibration

Tested on a real transcript and its variants:

| Case | Shingle score |
|---|---|
| Revision — one name corrected throughout | 0.77–0.86 |
| Sibling — next week's meeting, same series | 0.73 |
| Re-wrapped export | caught earlier, by check 2 |
| Unrelated document | 0.00 |

**Revision and sibling overlap. No threshold separates them**, at any shingle
length from 3 to 5. A verbatim-line-overlap signal was built as a tie-breaker and
rejected on measurement: it separated no better, and scored a re-wrapped export
at 0.235 where shingles correctly scored 1.000.

The conclusion is written into the script as a comment so nobody later wastes
time "tuning" it: the score reports confidence, not category. Deciding
revision-versus-sibling needs the content, which means an agent or a person.

Thresholds: `>= 0.95` NEAR, `>= 0.70` REVIEW, below that NEW. Both NEAR and
REVIEW mean *do not ingest silently*; the label only conveys how sure the script is.

### On a flag

**Unattended:** quarantine to `inbox/_review/`, log it, touch nothing in `wiki/`.
**Attended:** the agent reads both and decides — update the existing source page
in place for a revision (marking the old raw file superseded, never deleting it),
or ingest as new and cross-link for a sibling.

### What the manifest is, and is not

`.state/manifest.jsonl` answers exactly one question: *have I seen this content
before?* The filesystem genuinely cannot answer that, which is why the file
exists.

It does **not** record whether a source has been compiled. That stays derived
from links, exactly as designed elsewhere in this document: a file in `raw/` that
no `wiki/` page points at is not yet compiled.

These are two different questions. As long as no single file is asked to answer
both, they cannot drift apart. This is the one piece of state in the system and
it is deliberately scoped this narrowly.

## Query

Read `index.md`, drill into pages, answer with `[[links]]` to pages used.
`rg` over `wiki/` as fallback.

Answers worth keeping are written to `wiki/queries/`, indexed, and logged, so
exploration compounds the same way ingestion does.

## Lint

Split, so the cheap half costs no tokens.

Script (`scripts/lint.sh`, phase 3): orphan pages, dead `[[links]]`, pages
missing from the index, files in `raw/` with no inbound wiki link, malformed log
lines, and concepts on 2+ project pages lacking their own page.

Agent: contradictions, superseded claims, cross-links worth adding, gaps worth
sourcing. Report to `wiki/lint/<date>.md` plus a log line.

## Conventions

- `[[wiki links]]`, so Obsidian's graph view works.
- Log lines exactly `## [YYYY-MM-DD] <op> | <title>`. Grepped; do not vary.
- YAML frontmatter on every page. Enables Dataview tables later.
- ISO dates. Kebab-case filenames.
- Contradictions are recorded, never overwritten.

## Build order

| Phase | What | Gate |
|---|---|---|
| 0 | Scaffold: folders, git, `CLAUDE.md`, deny rules, seed index/log | done |
| 0b | `scripts/dedupe.py` + manifest, calibrated against real files | done |
| 1 | Ingest ~10 documents by hand, together. Read the output. Tune the rules. | quality proven |
| 2 | Backfill the rest in batches of ~10 | rules stable |
| 3 | `scripts/lint.sh` | a real wiki exists to lint |
| 4 | `launchd` watcher | the loop has been watched working |
| 5 | `qmd` search — only if the index fails | may never happen |

The watcher is last on purpose. Rules are tuned by watching them produce bad
pages, and an unattended process cannot be watched. Phase 1 is roughly an hour of
attention and is the difference between a wiki that gets trusted and one that
quietly stops being opened.
