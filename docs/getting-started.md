# Getting started

About twenty minutes. You end with one compiled document and a wiki you trust,
because you watched it being written.

## 1. Put it somewhere and make it yours

```bash
unzip wiki-father.zip -d ~ && mv ~/wiki-father ~/wiki   # or clone it
cd ~/wiki
git init && git add -A && git commit -m "empty wiki"
```

`~/wiki` is only a convention. Every script finds its own folder, so any path
works.

Check the basics:

```bash
python3 --version     # 3.9 or newer
make status
```

## 2. Tell it who you are

Open `schema/people.yml` and add yourself under `people:`, with every spelling a
transcriber has ever produced for your name:

```yaml
people:
  - canonical: Sam Rivera
    aliases: [Sam, Sammy, Sam R]
```

Add the colleagues and companies you already know will come up — people in
`schema/people.yml`, companies in `schema/orgs.yml`. You can start with nothing
but yourself; the agent proposes new entries as it meets them.

This roster is ground truth. When a document disagrees with it, the roster
wins, and the agent is never allowed to edit it.

**Optional:** `CLAUDE.md` calls you "the owner". Replace that with your name if
you like. It is the one file only you edit.

## 3. Pick your agent

Both work. Use whichever you already pay for.

### Claude Code

```bash
cd ~/wiki
claude
```

Accept the "trust this folder" prompt. **This step is required once**, even if
you only ever plan to use the automatic watcher: Claude Code ignores this
folder's permission list until the folder is trusted.

Claude reads `CLAUDE.md` automatically. The permission list in
`.claude/settings.json` lets it run the helper scripts without asking, and
blocks it from editing `raw/`, `schema/` and `CLAUDE.md`.

### Codex

```bash
cd ~/wiki
codex
```

Codex reads `AGENTS.md`, which points it at `CLAUDE.md`. When it asks to run
`python3 scripts/...`, approve it. The scripts only read and write inside this
folder.

## 4. Compile your first document by hand — and watch

Do not start the automatic watcher yet. The rules are tuned by watching them
work, and you cannot watch an unattended run.

Drop **one** document into `inbox/`. A meeting transcript is ideal. Name it the
way your transcriber does, ideally with a date and time:

```
inbox/acme-weekly 20261001 1015.txt
```

Transcripts work best with one speaker turn per line, like `Sam: text`.

Then tell the agent, in the session from step 3:

> Ingest the inbox, following CLAUDE.md.

It will:

1. Run `scripts/queue.py` to put the inbox in event order.
2. Run `scripts/file.py`, which dedupes, dates, renames and files the document
   into `raw/`, and checks the speakers.
3. Read the source in full and search the wiki.
4. Write `wiki/sources/<date>-<name>.md`, then update project, concept and
   people pages, the index, the timeline and the log.
5. Report what it touched — and anything in the document that read like an
   instruction aimed at it.

Read what it wrote. If a rule produced something you dislike, edit `CLAUDE.md`
and run again on the next document. Do this for about ten documents.

Then save:

```bash
make save MSG="first ten sources"
```

## 5. Turn on drag-and-drop (macOS)

When the hand-run pages look right:

```bash
make start                              # Claude Code, on Haiku
WIKI_HARNESS=codex make start           # or Codex, on its default model
```

Choose a model with `WIKI_MODEL=...` on the same line. To change your mind
later: `make stop`, delete `~/Library/LaunchAgents/com.wiki.ingest.plist`, then
`make start` with the new settings.

Now any file dropped in `inbox/` starts a run after 60 quiet seconds. Each run:

- commits anything outstanding first, then commits its own work, so `git log`
  is the full record and `git revert HEAD` undoes a run;
- makes `raw/`, `schema/` and `CLAUDE.md` read-only for its duration;
- logs to `.state/ingest.log` (`make watch` to follow it live);
- moves your original to `inbox/_done/` under its own name, never deletes it;
- ends with a desktop notification.

Not on macOS? Run `make ingest` whenever you have dropped files. It is the same
run, in the foreground.

## 6. Asking questions

Open a session in the folder and ask. The agent reads `wiki/index.md`, follows
the links and answers with `[[links]]` to the pages it used. Good answers get
filed back to `wiki/queries/`.

## 7. The weekly habits

- **`make todo`** — names the agent could not resolve. It writes them as tokens
  like `TEMP_PERSON_Mikko` until you decide. When you know who it is:

  ```bash
  make resolve TOKEN=TEMP_PERSON_Mikko NAME="Mikko Virtanen"
  ```

  That renames it everywhere and records it in the roster.

- **`inbox/_review/`** — files that looked like a duplicate or revision of
  something already ingested. Open a session and say *"look at the file in
  inbox/_review and decide whether it is a revision or a new document"*.

- **Hand-fixed transcripts** — if you correct speaker names in a transcript
  yourself, put `# speakers verified` near the top before dropping it. Those
  labels then outrank every machine check.

- **Lint** — ask the agent to *"lint the wiki, following CLAUDE.md"* now and
  then. `make lint` does the cheap structural part on its own.

## When something goes wrong

| Symptom | Fix |
|---|---|
| `make status` says `raw/` is READ-ONLY | A run was killed. `make unlock` |
| Drops do nothing | `make status`. Not loaded → `make start`. |
| Log says the workspace is not trusted | `cd ~/wiki && claude`, accept the prompt, quit. |
| A run never starts after a crash | `make unstick` |
| Log says `INCOMPLETE` or `STALL` | `make pending` compiles what is left. |
| A run wrote nonsense | `git revert HEAD` |

## What a run costs

Every headless Claude Code run pays about 50,000 tokens of system prompt before
it reads your document. On Haiku that is roughly $0.10 per cold start; on Sonnet
about $0.29; on Opus about $0.61. The ingest log prints `COST` after each Claude
run. Codex runs on your ChatGPT plan and does not report cost in the log.

Your global `~/.claude/CLAUDE.md`, if you have one, is loaded into every run
too. Keep it short, or it costs you on every document.
