# wiki-father

An empty personal knowledge base that an AI agent writes and you read.

You drop documents in a folder — meeting transcripts, PDFs, slide decks, web
clippings. An agent (Claude Code or Codex) reads each one and compiles it into a
wiki of linked markdown pages: one page per project, per recurring idea, per
person who matters, and a short receipt per source. You read it in Obsidian, or
in any editor. Git records every change, so any bad run can be undone.

This follows the **LLM Wiki** pattern (Andrej Karpathy, 2026): compile each
document once into a persistent wiki, instead of re-reading a pile of files
every time you ask a question. The knowledge compounds; the agent does the
upkeep.

This repository is the machinery only. It has no content.

**Start here: [docs/getting-started.md](docs/getting-started.md)** — about
twenty minutes from unzip to your first compiled document.

## What you get

| Path | What it is | Who writes it |
|---|---|---|
| `inbox/` | Drop zone. Files land here and leave. | You |
| `raw/` | Every source, filed and renamed by date. Read-only after filing. | Scripts |
| `wiki/` | The wiki itself. | The agent |
| `schema/` | Ground truth: the real names of people and organisations. | You only |
| `CLAUDE.md` | The rules the agent follows. | You only |
| `scripts/` | Small Python and shell helpers that do the mechanical work. | — |
| `docs/design.md` | Why it is built this way. Read it when a rule seems odd. | — |

## Why it is more than "ask an AI to take notes"

Most of the scripts exist because of a specific failure seen on a real wiki of a
few hundred documents:

- **Transcribers get speaker names wrong.** `scripts/speakers.py` checks every
  label against self-introductions and your roster before anything is
  attributed. If the label cannot be trusted, the wiki says "a participant
  said", never a guessed name.
- **Drop order is not event order.** Every source is dated from its filename,
  its content and its file time, and ingested oldest-first. A document that
  predates existing pages triggers a "backstory" check before anything is
  written.
- **Duplicates and revisions.** Files are compared by bytes, by text, and by
  fuzzy overlap. Near-matches are held for you in `inbox/_review/` instead of
  being written twice.
- **Contradictions are kept, not overwritten.** Both claims stay, each with its
  date and source.
- **Pages do not sprawl.** A concept gets its own page only when a second
  project touches it; a person only when they show up twice or decide
  something.

## Requirements

- macOS for the automatic drag-and-drop watcher. Everything else runs on any
  machine with `bash`, `python3` and `git`.
- [Claude Code](https://claude.com/claude-code) **or** [Codex](https://developers.openai.com/codex/cli).
- Optional: [Obsidian](https://obsidian.md) to read it. Open `wiki/` as a vault.
- Optional, for office files: `pdftotext` (poppler), `pandoc`, `python-pptx`.
  Plain `.txt` and `.md` need nothing.

## Everyday commands

```
make              list every command
make status       where everything stands, one screen
make ingest       compile the inbox now, in the foreground
make start        turn on drag-and-drop (macOS)
make watch        follow a run live
make todo         names the agent could not resolve, waiting on you
make history      what each run did
```

Undo the last run: `git revert HEAD`.

## Privacy

Everything stays on your machine. The repository has no remote. The agent sends
document text to whichever model provider you use (Anthropic or OpenAI), the
same as any other chat with it. Never put passwords or keys in this folder.
