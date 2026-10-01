#!/bin/bash
# Unattended ingest. Fired by launchd when inbox/ changes.
#
# Safety, in order of importance:
#   1. Every run is bracketed by git commits, so `git log` is the complete record
#      and `git revert` undoes a bad run. You are not in the loop at the time;
#      you are in the loop afterwards.
#   2. A lock file stops concurrent runs.
#   3. Debounce: wait for the inbox to stop changing before starting.
#   4. --max-turns caps a confused run.
#   5. Deny rules in .claude/settings.json keep the agent out of CLAUDE.md,
#      schema/ and raw/.
#
# Everything is logged to .state/ingest.log.
#
# Note: archiving to inbox/_done/ writes inside the watched folder, so every run
# re-fires the watcher once. That second fire sees an empty inbox and exits in
# milliseconds. Harmless, and the price of keeping your original somewhere you
# will actually look for it.

set -uo pipefail
WIKI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # wherever this repo lives
LOCK="$WIKI/.state/ingest.lock"
LOG="$WIKI/.state/ingest.log"
DEBOUNCE=${WIKI_DEBOUNCE:-60}   # seconds of quiet before starting; override for testing
MAX_TURNS=${WIKI_MAX_TURNS:-120}
BATCH=${WIKI_BATCH:-18}          # sources handed to the model per invocation
# Measured 2026-09-13, both on deepseek-v4-flash:
#   88 sources, one invocation: read 36, then hit the context ceiling and quit.
#     23 pages, 9 concepts, 7 projects, 81 backstory checks. 8.5 tools/page.
#   6 per batch: 6 pages, 0 concepts, 0 projects, 0 backstory. 39.3 tools/page.
# Small batches are WORSE, not safer. Each one re-orients in the wiki from
# scratch, and six sources never repay that; the model spends its turns
# re-reading instead of compiling, and stops writing across sources at all --
# which is where concept and project updates come from. 18 is under the 36 that
# filled context, and large enough that orientation is amortised.
# Measured 2026-09-12, same prompt, cold cache, from an empty folder:
#   opus-5 $0.61   sonnet-5 $0.29   haiku-4.5 $0.10
# The model is the whole story. Every run also pays ~50k tokens of Claude Code
# system prompt, tool definitions and the global CLAUDE.md before it reads a
# word of your document -- headless does not avoid that, it is the same runtime.
# Reconciling concepts is worth a better model; routine ingest is not.
HARNESS=${WIKI_HARNESS:-claude}          # claude | codex | omp
MODEL=${WIKI_MODEL:-}                    # blank = the harness default below

# --pending: ignore the inbox, compile raw/ sources that still have no page.
# Needed because the manifest records what has been SEEN. A file that was filed
# but never compiled is therefore skipped as a duplicate forever if you re-drop
# it -- the only way back in is from raw/.
PENDING_ONLY=0
[ "${1:-}" = "--pending" ] && PENDING_ONLY=1

cd "$WIKI" || exit 1
mkdir -p .state

# API keys live in ~/.zshrc, which only sources for INTERACTIVE shells. launchd
# gives none, so an unattended run would reach a provider with no credential and
# fail in a way that looks like a model problem. Pull just the key exports --
# not the whole profile, which would drag in prompts and plugins.
if [ -f "$HOME/.zshrc" ]; then
  eval "$(grep -E '^[[:space:]]*export [A-Z0-9_]+(API_KEY|_TOKEN|_KEY)=' "$HOME/.zshrc" 2>/dev/null || true)" 2>/dev/null || true
fi
# If a previous run was killed -9 its EXIT trap never fired and raw/ is still
# read-only. Clear that first, every time, so a stuck state cannot compound.
chmod -R u+w raw schema CLAUDE.md 2>/dev/null
say() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG"; }

# --- 2. one at a time ---
exec 9>"$LOCK"
if ! flock -n 9 2>/dev/null; then
  # macOS has no flock(1); fall back to a pid file
  if [ -f "$LOCK.pid" ] && kill -0 "$(cat "$LOCK.pid" 2>/dev/null)" 2>/dev/null; then
    say "SKIP  a run is already in progress"; exit 0
  fi
fi
echo $$ > "$LOCK.pid"
trap 'rm -f "$LOCK.pid"' EXIT

# --- 3. debounce: wait for the drop to finish ---
count() { find inbox -type f ! -name '.*' -not -path '*/_review/*' -not -path '*/_done/*' -not -path '*/_hold/*' -not -path '*/_inflight/*' | wc -l | tr -d ' '; }

# What still needs COMPILING, which is not what has been SEEN. The link is a
# page's `source_file:` frontmatter, not a filename match: four sources are
# compiled under a different slug, and matching on basename reported them as
# pending -- work that would be redone and then measured as zero progress.
pending_list() { python3 "$WIKI/scripts/pending.py" --stems; }
pending_count() { python3 "$WIKI/scripts/pending.py" --count; }
if [ "$(count)" -eq 0 ] && [ "$PENDING_ONLY" -eq 0 ]; then
  # An empty inbox is not the same as nothing to do: sources filed by an earlier
  # run may still have no page. Say so rather than exiting silently.
  still=$(pending_count)
  if [ "$still" -gt 0 ]; then
    say "SKIP  inbox empty, but $still filed source(s) have no page — make pending"
  else
    say "SKIP  inbox empty"
  fi
  exit 0
fi
n=$(count)
# --pending compiles raw/, not the inbox, so it has no drop to wait for and an
# empty inbox is its normal case.
if [ "$PENDING_ONLY" -eq 0 ]; then
  prev=-1
  while [ "$(count)" -ne "$prev" ]; do
    prev=$(count); sleep "$DEBOUNCE"
  done
  n=$(count)
  [ "$n" -eq 0 ] && { say "SKIP  inbox emptied while waiting"; exit 0; }
fi

# --- 0. preflight: an untrusted workspace silently discards the allow-list ---
# Claude Code ignores permissions.allow in a workspace that has never been
# trusted, so every script asks for approval a headless run cannot give. The
# agent then does nothing useful and says so. Better to not start.
if [ "$HARNESS" = "claude" ] && ! python3 - "$WIKI" <<'PYEOF'
import json, pathlib, sys
try:
    d = json.loads((pathlib.Path.home()/".claude.json").read_text())
    sys.exit(0 if d.get("projects", {}).get(sys.argv[1], {}).get("hasTrustDialogAccepted") else 1)
except Exception:
    sys.exit(1)
PYEOF
then
  say "ABORT  $WIKI is not a trusted workspace."
  say "       Claude Code discards permissions.allow there, so every helper"
  say "       script would ask for approval this run cannot give."
  say "       Fix once, by hand:  cd $WIKI && claude   (accept the trust prompt)"
  osascript -e 'display notification "Workspace not trusted — run claude in the wiki folder once" with title "wiki ingest blocked"' 2>/dev/null
  exit 1
fi

say "START  $n file(s) in inbox"

# --- 1a. clean slate ---
if [ -n "$(git status --porcelain)" ]; then
  git add -A && git commit -q -m "wip: uncommitted changes before automatic ingest" \
    && say "committed pre-existing changes"
fi

# --- the order matters: oldest event first ---
ORDER=$(python3 scripts/queue.py 2>&1)
say "queue:"; printf '%s\n' "$ORDER" >> "$LOG"

# --- file everything BEFORE the model starts ---
# file.py is deterministic: dedupe, convert, move, date, resolve orgs and
# speakers. None of it needs an LLM, and having the agent shell out to it cost a
# round trip per document. Doing it here also means raw/ can be locked before
# the model exists, which is a guard no harness has to provide.
if [ "$PENDING_ONLY" -eq 1 ]; then
  say "PENDING MODE  ignoring the inbox, compiling raw/ sources with no page"
  FILED=""
else
say "filing:"
FILED=""
while IFS= read -r f; do
  [ -f "$f" ] || continue
  out=$(python3 scripts/file.py "$f" 2>&1)
  printf '%s\n' "$out" >> "$LOG"
  dest=$(printf '%s\n' "$out" | sed -n 's/^ *-> *\(raw\/[^ ]*\).*/\1/p' | head -1)
  [ -n "$dest" ] && FILED="$FILED$out"$'\n\n'
done < <(python3 scripts/queue.py --json | python3 -c "
import json,sys
for r in json.load(sys.stdin): print('inbox/' + r['file'])
")

# Every dropped file was a duplicate. That says nothing about the backlog: a
# source filed by an earlier run that never got a page is still waiting, and
# re-dropping it can never help because the manifest already has its hash.
if [ -z "$FILED" ] && [ "$(pending_count)" -eq 0 ]; then
  say "NOTHING TO COMPILE  every file was a duplicate or quarantined"
  if [ -n "$(git status --porcelain)" ]; then
    git add -A && git commit -q -m "ingest: $n file(s), all skipped or quarantined"
    say "COMMIT  skips recorded"
  fi
  osascript -e "display notification \"$n file(s), nothing new to compile\" with title \"wiki ingest\"" 2>/dev/null
  exit 0
fi
[ -z "$FILED" ] && say "all dropped files were duplicates — compiling the backlog instead"

fi

# --- lock the layers the model must never write ---
# raw/ is read-only forever, schema/ is the owner's, CLAUDE.md is the rules. This is
# the OS enforcing it, not a permission list any harness may or may not honour.
chmod -R a-w raw schema CLAUDE.md 2>/dev/null
restore_perms() { chmod -R u+w raw schema CLAUDE.md 2>/dev/null; }
trap 'restore_perms; rm -f "$LOCK.pid"' EXIT
say "locked raw/ schema/ CLAUDE.md read-only for the duration"

# --- one agent invocation over one batch -----------------------------------
# This was inline and ran exactly once. It is a function now because a large
# drop must become several bounded runs: on 2026-09-13 a single invocation read
# 36 transcripts into context, hit 18.4M input tokens against 65K output, and
# spent its last 100 seconds emitting 200-token turns while writing nothing.
# Context was the limit, not money or the turn cap. Bounded batches are the fix.
run_agent() {
PROMPT="$1"
RESULT=$(mktemp)
case "$HARNESS" in
  omp)
    # Measured 2026-09-12: omp's floor is 10,322 tokens against Claude Code's
    # 53,272, because --tools= actually removes the tool definitions rather than
    # just filtering permissions. That difference is paid on every turn.
    # --no-rules keeps omp from discovering any OTHER rules file; CLAUDE.md is
    # appended explicitly so we know exactly what is loaded.
    # omp reads Claude Code's MCP config (.claude.json, .claude/mcp.json,
    # .claude/plugins) and hands the agent every server it finds. Measured: 29
    # chrome-devtools tools -- click, fill, evaluate_script -- in a run that had
    # --tools=read,write,edit,bash and --no-extensions. --profile does not help.
    # Pointing CLAUDE_CONFIG_DIR at an empty directory takes it to 0.
    export CLAUDE_CONFIG_DIR="$WIKI/.state/no-claude-config"
    mkdir -p "$CLAUDE_CONFIG_DIR"

    # omp matches a model id fuzzily, and with no key for the named provider it
    # silently routes to OpenRouter's copy instead. Check the CATALOGUE, not by
    # sending a prompt -- the first version of this guard sent "ok", which the
    # agent treated as a task and answered by browsing the filesystem.
    WANT_PROVIDER="${MODEL%%/*}"
    WANT_MODEL="${MODEL##*/}"
    if [ -n "$MODEL" ] && [ "$WANT_PROVIDER" != "$MODEL" ]; then
      if ! omp models 2>/dev/null | awk -v p="$WANT_PROVIDER" -v m="$WANT_MODEL" '
            /^[a-z0-9-]+ \([0-9]+\)$/ { s=$1 }
            index($0, m) && s==p { found=1 }
            END { exit(found?0:1) }'; then
        say "ABORT  provider '$WANT_PROVIDER' does not list model '$WANT_MODEL'."
        say "       Usually a missing API key — omp would fall back to another"
        say "       provider's copy without saying so. Refusing to run a batch"
        say "       down a route that was not chosen."
        exit 1
      fi
      say "provider check: $WANT_MODEL confirmed under '$WANT_PROVIDER'"
    fi
    say "harness omp, model ${MODEL:-glm-5.3-flash}"
    timeout 3600 omp -p "$PROMPT" \
      --model "${MODEL:-glm-5.3-flash}" \
      --tools=read,write,edit,bash \
      --no-skills --no-rules --no-extensions --no-lsp --no-pty \
      --no-session --auto-approve \
      --append-system-prompt "$WIKI/CLAUDE.md" \
      --max-time 3300 \
      --mode=json \
      < /dev/null 2>>"$LOG" | python3 scripts/progress.py > "$RESULT" 2>>"$LOG"
    rc=${PIPESTATUS[0]}
    python3 - "$RESULT" >> "$LOG" 2>&1 <<'PYEOF'
import json, sys
tot_in = tot_out = 0; cost = 0.0; turns = 0; model = "?"; last = ""
for line in open(sys.argv[1], errors="replace"):
    try: d = json.loads(line)
    except Exception: continue
    m = d.get("message") or {}
    u = m.get("usage")
    if u and d.get("type") == "turn_end":   # usage repeats on message_end too
        turns += 1; model = m.get("model", model)
        tot_in += u.get("input", 0) + u.get("cacheRead", 0) + u.get("cacheWrite", 0)
        tot_out += u.get("output", 0)
        cost += (u.get("cost") or {}).get("total", 0)
    if m.get("role") == "assistant":
        for c in m.get("content", []):
            if c.get("type") == "text": last = c["text"]
print(f"  COST  ${cost:.4f}   turns {turns}   in {tot_in:,}  out {tot_out:,}   model {model}")
print("  ---- agent report ----"); print(last[:4000])
PYEOF
    ;;
  codex)
    # Codex reads AGENTS.md, which points it at CLAUDE.md. workspace-write lets
    # it edit inside the repo and nowhere else; exec mode never stops to ask.
    # The chmod above is what actually protects raw/, schema/ and CLAUDE.md.
    say "harness codex, model ${MODEL:-(codex default)}"
    timeout 3600 codex exec "$PROMPT" \
      -C "$WIKI" \
      --sandbox workspace-write \
      --ephemeral \
      ${MODEL:+--model "$MODEL"} \
      --output-last-message "$RESULT.last" \
      < /dev/null >> "$LOG" 2>&1
    rc=$?
    { echo "  COST  (codex does not report cost here)"
      echo "  ---- agent report ----"
      head -c 4000 "$RESULT.last" 2>/dev/null; echo; } >> "$LOG"
    rm -f "$RESULT.last"
    ;;
  *)
    # Claude Code. --strict-mcp-config and --disable-slash-commands trim ~13%,
    # and stop this unattended agent reaching Gmail, Drive or the browser.
    say "harness claude, model ${MODEL:-claude-haiku-4-5-20251001}"
    timeout 3600 claude -p "$PROMPT" \
      --model "${MODEL:-claude-haiku-4-5-20251001}" \
      --max-turns "$MAX_TURNS" \
      --permission-mode acceptEdits \
      --strict-mcp-config \
      --disable-slash-commands \
      --output-format json \
      < /dev/null > "$RESULT" 2>>"$LOG"
    rc=$?
    # claude -p --output-format json emits one object at the end, so there is
    # nothing to stream; use --output-format stream-json if progress matters.
    python3 - "$RESULT" >> "$LOG" 2>&1 <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1])); u = d.get("usage", {})
    cw = u.get("cache_creation_input_tokens", 0); cr = u.get("cache_read_input_tokens", 0)
    print(f"  COST  ${d.get('total_cost_usd',0):.4f}   turns {d.get('num_turns','?')}   "
          f"in {u.get('input_tokens',0)+cw+cr:,}  out {u.get('output_tokens',0):,}   "
          f"{d.get('duration_ms',0)/1000:.0f}s")
    print("  ---- agent report ----"); print(d.get("result","")[:4000])
except Exception as e:
    print(f"  could not read the run result: {e}")
PYEOF
    ;;
esac
say "$HARNESS exited $rc"
AGENT_RC=$rc
return 0
}

# --- the prompt for one batch ----------------------------------------------
batch_prompt() {
  local names="$1" filed="$2" paths="" f
  while IFS= read -r b; do
    [ -z "$b" ] && continue
    f=$(find "$WIKI/raw" -name "$b.*" ! -name '*.png' | head -1)
    # Name the DESTINATION explicitly. CLAUDE.md says only "wiki/sources/<slug>.md"
    # and leaves the slug to judgement; on 2026-09-13 a batch wrote six pages as
    # <name>-<date> instead of <date>-<name>, so completion measured as zero and
    # the loop stalled on work that had actually been done.
    [ -n "$f" ] && paths="${paths}  ${f#$WIKI/}  ->  wiki/sources/$b.md
"
  done <<< "$names"

  cat <<PROMPTEOF
Compile these sources into the wiki, following CLAUDE.md exactly. Oldest event
first. They are ALREADY filed, dated and entity-resolved into raw/. Do NOT run
file.py. Do NOT touch inbox/.

$paths
${filed:+Filing produced this. Use these dates and resolutions verbatim:

$filed
}
Start at step 2 of CLAUDE.md -- read the source in full -- for EVERY source
listed above. raw/, schema/ and CLAUDE.md are read-only. You write only in wiki/.

Each line above gives the source and the EXACT page path to create for it. Use
that path verbatim -- do not invent a slug, do not reorder the date.

A source is COMPILED when all four of these are true, not when the file exists:
  1. Its page carries the evidence -- direct quotations from the transcript,
     copied exactly, not paraphrase dressed as a quote. A page with no quotes
     has not been compiled.
  2. The backstory check has been RUN for it -- scripts/backstory.py with
     --date set to the source date and --pages set to the slugs it touches --
     and what it returned is reflected on the page.
  3. Every concept and project the source touches has been updated with what
     this source adds. Compiling means writing ACROSS sources; a batch that
     creates source pages and changes nothing else has not done the work.
  4. The source page stays a receipt, under 60 lines. Facts belong on the
     concept, project and person pages -- not duplicated onto the source.

Read the transcript IN FULL before writing about it.

If you cannot finish one, say which and why. An honest short batch is fine; a
silent one is not. Do not pad a page to look finished.

Do not skip the backstory check: sorting fixes order within this batch only.
Finish by regenerating the timeline and appending one log line per source.
PROMPTEOF
}

# --- compile until done, or until a batch achieves nothing ------------------
compile_loop() {
  local filed="$1" before after did round=0 names nb started sources_before pages_before
  while :; do
    before=$(pending_count)
    if [ "$before" -eq 0 ]; then say "ALL COMPILED  nothing pending"; break; fi
    round=$((round + 1))
    names=$(pending_list | head -"$BATCH")
    nb=$(printf '%s\n' "$names" | grep -c . || true)
    say "BATCH $round  compiling $nb of $before pending"
    started=$(date +%s)
    sources_before=$(find wiki/sources -name '*.md' -type f | wc -l | tr -d ' ')
    pages_before=$(find wiki -name '*.md' -type f | wc -l | tr -d ' ')
    run_agent "$(batch_prompt "$names" "$filed")"
    filed=""                      # the filing notes apply to the first batch only
    after=$(pending_count)
    did=$((before - after))
    say "BATCH $round done  wrote $did page(s), $after still pending"
    python3 scripts/metrics.py record --result "$RESULT" --harness "$HARNESS" \
      --model "${MODEL:-}" --started "$started" --round "$round" \
      --requested "$nb" --compiled "$did" --pending-before "$before" \
      --sources-before "$sources_before" --pages-before "$pages_before" \
      --exit-code "$AGENT_RC" \
      --names "$names" >> "$LOG" 2>&1
    rm -f "$RESULT"
    if [ "$did" -le 0 ]; then
      say "STALL  that batch produced no page. Stopping rather than spending more"
      say "       on a loop that is not progressing.  Resume with:  make pending"
      break
    fi
    if [ -n "$(git status --porcelain)" ]; then
      git add -A && git commit -q -m "ingest: batch $round, $did source(s) compiled"
    fi
  done
}

PENDING_START=$(pending_count)
compile_loop "$FILED"

# --- commit: the manifest and the _done archive, now that pages exist --------
# Filing only prepared. Anything without a page goes back to inbox/ and is
# retried by the next run, instead of being marked seen and locked out.
say "commit:"
python3 scripts/commit.py >> "$LOG" 2>&1
PENDING_END=$(pending_count)

rm -f "$RESULT"

# --- 1b. commit whatever happened, good or bad ---
if [ -n "$(git status --porcelain)" ]; then
  files=$(git status --porcelain | wc -l | tr -d ' ')
  git add -A
  git commit -q -m "ingest: automatic run, $n source(s), $files file(s) changed

Unattended run fired by the inbox watcher. Review with:
  git show --stat HEAD
Undo with:
  git revert HEAD"
  say "COMMIT  $files file(s) changed"
  msg="$(( PENDING_START - PENDING_END )) page(s) written, $files files changed"
else
  say "NO CHANGES"
  msg="$n file(s) seen, nothing changed"
fi

# Report what was COMPILED, never what was filed. Filing is shell work and
# always succeeds; on 2026-09-13 that let a run which wrote 23 pages out of 88
# sources announce "98 source(s) ingested". The number that matters is how many
# raw sources still have no page.
left=$(count)
[ "$left" -gt 0 ] && msg="$msg — $left still in inbox"
if [ "$PENDING_END" -gt 0 ]; then
  msg="INCOMPLETE — $msg — $PENDING_END source(s) still have no page"
  say "INCOMPLETE  $PENDING_END of $PENDING_START source(s) still uncompiled."
  say "            Resume with:  make pending"
fi
osascript -e "display notification \"$msg\" with title \"wiki ingest\"" 2>/dev/null
say "END  $msg"
