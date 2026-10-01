---
name: wiki-query
description: "Use when reading from or doing bookkeeping on the LLM wiki in this repository — answering what was decided, who said what, a project's status, what contradicts what, when something happened; and when the human names an entity mid-conversation ('TEMP_PERSON_Cam is Cameron Doyle', 'that org is Aleria'). Covers the index-first route that keeps a question cheap, the four traps that make a confident answer wrong, and the scripts that do renames correctly so you never hand-edit. Read this BEFORE opening any page or changing any name."
---

# Reading and maintaining the wiki

Two jobs live here: answering questions, and the bookkeeping that comes up while
answering them. The second matters because a name you fix by hand will be fixed
wrongly — there are scripts that do it exactly, and they update things you will
forget.

---

# Part 1 — Answering

## The one rule

**Never read the corpus.** It is ~355,000 tokens. Read `wiki/index.md` (170
tokens), pick the one index you need, open the three to five pages it names.

| file | tokens | holds |
|---|---|---|
| `wiki/index.md` | ~170 | the front door |
| `wiki/index-projects.md` | ~730 | 27 projects |
| `wiki/index-concepts.md` | ~770 | 27 concepts |
| `wiki/index-people.md` | ~640 | 26 people |
| `wiki/index-sources.md` | ~3,800 | 110 sources — expensive, skip unless you need provenance |
| `wiki/timeline.md` | ~650 | what happened when |

A well-aimed question costs a few thousand tokens. Past about eight pages you
took a wrong turn at the index — go back to it.

`rg` over `wiki/` is the fallback, and it is the *better* tool for exact
strings: a name, a quoted phrase, a token like `TEMP_PERSON_Greg`.

## Where the answer lives

The spine tells you which folder to open before you look at anything:

> A concept earns its own page the moment a **second project** touches it.
> Until then it lives as a section on the one project page that cares.

> A person earns a page when they appear in a **second source**, or when they
> decide or commit to something.

- **"Status of X?"** -> `projects/`
- **"How do these two relate?"** -> `concepts/`. Concepts are the joins; the
  reconciliation between two projects lives there, not on either project.
- **"What does this person think?"** -> `people/`
- **"Where did this claim come from?"** -> `sources/`. A source page is a
  **receipt, not a copy** — under 60 lines by design. The full text is at the
  path in its `source_file:` frontmatter.
- **"When did this happen?"** -> `timeline.md`

## Four traps

**1. `log.md` is not `timeline.md`.** `log.md` is INGEST order — when a document
was dropped. `timeline.md` is EVENT order — when the thing happened. They
diverge wildly. Reading ingest order as a causal story gives the wrong answer.

**2. Letter speakers are file-scoped.** `C@2026-09-11-acme-sync` means
"speaker C in that one transcript". The transcriber assigns letters by speaking
order, per run. **`C` in one file is not `C` in another.** Never merge them,
never guess a letter's identity from context.

**3. `TEMP_PERSON_` / `TEMP_ORG_` are placeholders.** 17 are unresolved. Report
them as unresolved; never quietly treat one as a real name, and never assume two
similar tokens are the same entity.

**4. Speaker labels may be unproven.** Look near the top of a source page for
`diarisation: UNVERIFIED`, `ANONYMOUS` or `BROKEN`, and for per-speaker
statuses. `LABEL_UNVERIFIED` means the transcriber's guess was never confirmed
by a self-introduction. Say when a label is unproven. `schema/people.yml` is
ground truth and always wins.

## Answering well

1. Link with `[[page]]` to everything you used.
2. Quote the wiki's own quotations. The evidence is the point.
3. Cite the source **page**, not the raw file.
4. If two pages disagree, say so and name both. Contradictions are content here.
5. Never invent a fact. Mark inferences as inferences.

---

# Part 2 — Bookkeeping

**Never hand-edit a rename.** Every script below touches things you will miss —
other pages, the page filename, the index, the roster. A find-and-replace that
looks right leaves the wiki inconsistent in ways nobody notices for weeks.

## Naming an entity the human just identified

This is the common one. Mid-conversation they say "TEMP_PERSON_Cam is Cameron
Doyle" or "that org is Aleria".

```bash
python3 scripts/resolve.py list
```
Shows every unresolved token and which pages carry it. Run it when you spot one,
so you can tell them what is outstanding.

```bash
python3 scripts/resolve.py resolve TEMP_PERSON_Cam "Cameron Doyle"
```
One command does all of it: replaces the token on every page, renames the
entity's own page, repoints the links, and moves the `unresolved:` entry in
`schema/people.yml` into the real list. It backs the roster up first, every time.
`TEMP_ORG_` tokens route to `orgs.yml` automatically.

Add `--no-roster` to leave `schema/` alone and print the entry to paste instead.

**The rule that matters: you may never decide the name.** The canonical name has
to come from the human, on the command line. `schema/` is their ground truth.
The script transcribes a decision they already made — it does not make one.
If you are not sure, ask; do not guess from context.

## A name that is wrong but is not a placeholder

An organisation spelled five different ways by the transcriber — Illyria,
Elyria, Valyria — is an **alias** problem, not a placeholder problem. Aliases
live in `schema/orgs.yml` and `schema/people.yml`, which are human-owned.

**Propose the alias, do not add it.** Show them the line to paste. Then:

```bash
python3 scripts/orgs.py <raw file>
```
checks a source against the roster and reports organisations found under a wrong
spelling.

## After any rename, regenerate

```bash
python3 scripts/index.py
python3 scripts/timeline.py
```
The indexes and the timeline are generated from the pages, so they go stale the
moment a page is renamed. Both take `--check` to preview without writing.

## Checking the wiki's health

```bash
python3 scripts/quality.py --bad
```
Source pages carrying no evidence — no quotations at all. Should be zero. It
counts straight quotes, typographic quotes and blockquotes, and verifies each
against the transcript the page names.

```bash
python3 scripts/index.py --audit
```
Pages the generator cannot summarise, and people pages resting on a single
source — which by the people rule should not have a page yet.

```bash
python3 scripts/pending.py --count
```
Raw sources with no page. Decided from each page's `source_file:` frontmatter,
not from filenames.

```bash
python3 scripts/backstory.py --date 2026-07-02 --pages forge,attractor
```
Does a source predate pages already written? Walks two levels of links. Use it
when an old document turns up and you need to know what it might overturn.

```bash
python3 scripts/speakers.py <raw transcript>
```
Who is actually speaking, and how far to trust each label.

## No script exists for these — ask first

Merging two pages, splitting one, renaming a concept, deleting a page. There is
no tool, so it would be hand-work, and hand-work is what this section exists to
prevent. Describe what you would do and let the human decide.

## What you must never touch

`raw/`, `schema/` and `CLAUDE.md` are read-only to you. `raw/` is the wiki's copy
of record; `schema/` is the human's ground truth — `resolve.py` is the only
thing that writes it, and only to transcribe a name they supplied.

---

# Part 3 — File good answers back

`wiki/queries/` holds **zero** pages. Every answer so far has died in a chat log.

If an answer is worth keeping — a comparison, a synthesis, a connection nobody
had drawn — write `wiki/queries/<slug>.md` with `type: query` in the
frontmatter, append one line to `wiki/log.md` in exactly this form:

```
## [YYYY-MM-DD] query | <title>
```

then run `python3 scripts/index.py`.

That log format is grepped. Do not vary it. A saved query is a first-class page:
later questions can link to it, and the same work is not redone.
