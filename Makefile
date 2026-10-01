# Wiki management. Run `make` for the list.
#
# Every path below is absolute. WIKI is this Makefile's own directory, expanded
# once through pwd into a variable, so every target behaves the same whatever
# your shell's cwd is and whether you use `make -C`. Nothing here is relative:
# launchd and other unattended callers give you a cwd you cannot trust.

WIKI      := $(shell cd "$(dir $(firstword $(MAKEFILE_LIST)))" && pwd)
SCRIPTS   := $(WIKI)/scripts
STATE     := $(WIKI)/.state
RAW       := $(WIKI)/raw
SCHEMA    := $(WIKI)/schema
PAGES     := $(WIKI)/wiki
INBOX     := $(WIKI)/inbox
LOG       := $(STATE)/ingest.log

# Resolved to absolute paths once, at parse time. Override on the command line
# if you ever need a different interpreter: make PYTHON=/usr/bin/python3 status
PYTHON    ?= $(shell command -v python3)
GIT       ?= $(shell command -v git)
LAUNCHCTL := /bin/launchctl
FIND      := /usr/bin/find
GREP      := /usr/bin/grep
PGREP     := /usr/bin/pgrep
LABEL     ?= com.wiki.ingest
PLIST     := $(HOME)/Library/LaunchAgents/$(LABEL).plist

# Files waiting to be compiled: the inbox minus its three holding pens.
QUEUED = $(FIND) $(INBOX) -type f ! -name '.*' \
	-not -path '*/_review/*' -not -path '*/_done/*' -not -path '*/_hold/*' -not -path '*/_inflight/*'

.DEFAULT_GOAL := help
.PHONY: help status queue watch progress cost metrics running ingest ingest-claude ingest-codex \
        pending backlog export export-zip \
        start stop restart todo resolve timeline index check lint \
        unlock unstick save history sources orphans

## ---- everyday ----------------------------------------------------------

help:  ## show this list
	@echo "wiki: $(WIKI)"
	@echo
	@$(GREP) -hE '^[a-z][a-z-]*:.*## ' $(firstword $(MAKEFILE_LIST)) \
	  | sed -E 's/:.*## /|/' \
	  | awk -F'|' '{printf "  make %-14s %s\n", $$1, $$2}'
	@echo
	@echo "  args:  make resolve TOKEN=TEMP_PERSON_Greg NAME=\"Greg Smith\""
	@echo "         make backstory DATE=2026-07-02 PAGES=forge,attractor"

status:  ## where everything stands, one screen
	@echo "wiki       $(WIKI)"
	@printf "watcher    "; $(LAUNCHCTL) list 2>/dev/null | $(GREP) -q '$(LABEL)' \
	  && echo "loaded, watching $(INBOX)" || echo "NOT LOADED   -> make start"
	@printf "ingest     "; $(PGREP) -f '$(SCRIPTS)/ingest.sh' >/dev/null 2>&1 \
	  && echo "RUNNING now  -> make watch" || echo "idle"
	@printf "queued     "; $(QUEUED) 2>/dev/null | wc -l | tr -d ' '
	@printf "raw/       "; test -w $(RAW) \
	  && echo "writable" || echo "READ-ONLY — a run was killed  -> make unlock"
	@printf "sources    "; ls $(PAGES)/sources/*.md 2>/dev/null | wc -l | tr -d ' '
	@printf "pages      "; $(FIND) $(PAGES) -name '*.md' | wc -l | tr -d ' '
	@printf "raw files  "; $(FIND) $(RAW) -type f ! -name '.*' | wc -l | tr -d ' '
	@printf "unresolved "; $(GREP) -rhoE 'TEMP_(PERSON|ORG)_[A-Za-z]+' $(PAGES) 2>/dev/null \
	  | sort -u | wc -l | tr -d ' '
	@printf "git        "; cd $(WIKI) && test -z "$$($(GIT) status --porcelain)" \
	  && echo "clean at $$($(GIT) log --oneline -1)" || echo "DIRTY  -> make save"

queue:  ## what is waiting, in the order it will be ingested
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/queue.py --dir $(INBOX)

watch:  ## follow the ingest log live (ctrl-c to stop)
	@tail -f $(LOG)

running:  ## is an ingest in flight right now
	@$(PGREP) -lf '$(SCRIPTS)/ingest.sh' || echo "no ingest running"

progress:  ## last few lines of the current or most recent run
	@tail -20 $(LOG)

cost:  ## what the most recent run cost
	@cd $(WIKI) && awk '/  START  /{n=NR} END{print n}' $(LOG) \
	  | xargs -I{} tail -n +{} $(LOG) \
	  | $(GREP) -oE 'done — \$$[0-9.]+' | $(GREP) -oE '[0-9.]+' \
	  | awk '{s+=$$1} END{printf "  $$%.4f over %d turns\n", s, NR}'

metrics:  ## batch time, tokens and cost over the ingest history
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/metrics.py

## ---- the watcher -------------------------------------------------------

start:  ## turn drag-and-drop on (installs the watcher the first time)
	@test -f $(PLIST) || /bin/bash $(SCRIPTS)/watcher.sh install
	@$(LAUNCHCTL) load $(PLIST) 2>&1 | $(GREP) -v 'already loaded' || true
	@$(MAKE) --no-print-directory status

stop:  ## turn drag-and-drop off
	@$(LAUNCHCTL) unload $(PLIST) 2>&1 || true
	@echo "watcher stopped. Files dropped now wait until you: make start"

restart:  ## reload after editing the plist
	@$(LAUNCHCTL) unload $(PLIST) 2>/dev/null || true
	@$(LAUNCHCTL) load $(PLIST)
	@$(MAKE) --no-print-directory status

## ---- running an ingest by hand -----------------------------------------

ingest:  ## run the inbox now, in the foreground, on the configured model
	@cd $(WIKI) && WIKI_DEBOUNCE=2 /bin/bash $(SCRIPTS)/ingest.sh

pending:  ## compile raw/ sources that have no page yet, in batches
	@cd $(WIKI) && /bin/bash $(SCRIPTS)/ingest.sh --pending

backlog:  ## how many filed sources still have no page
	@cd $(WIKI) && $(FIND) $(RAW) -type f ! -name '.*' ! -name '*.png' \
	  -exec basename {} \; | sed 's/\.[^.]*$$//' | sort -u \
	  | while read b; do test -f $(PAGES)/sources/$$b.md || echo "  $$b"; done \
	  | tee /dev/stderr | wc -l | xargs echo "pending:"

ingest-codex:  ## same, but on Codex instead of Claude
	@cd $(WIKI) && WIKI_DEBOUNCE=2 WIKI_HARNESS=codex /bin/bash $(SCRIPTS)/ingest.sh

ingest-claude:  ## same, but force the Claude harness
	@cd $(WIKI) && WIKI_DEBOUNCE=2 WIKI_HARNESS=claude WIKI_MODEL= \
	  /bin/bash $(SCRIPTS)/ingest.sh

## ---- entities ----------------------------------------------------------

todo:  ## placeholder names still waiting on you, and where they appear
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/resolve.py list

resolve:  ## name one placeholder everywhere: TOKEN=... NAME="..."
	@test -n "$(TOKEN)" || { echo "need TOKEN=TEMP_PERSON_X"; exit 2; }
	@test -n "$(NAME)"  || { echo 'need NAME="Real Name"';  exit 2; }
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/resolve.py resolve "$(TOKEN)" "$(NAME)"

backstory:  ## does a source predate existing pages: DATE=... PAGES=a,b
	@test -n "$(DATE)"  || { echo "need DATE=2026-07-02";  exit 2; }
	@test -n "$(PAGES)" || { echo "need PAGES=forge,attractor"; exit 2; }
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/backstory.py --date "$(DATE)" --pages "$(PAGES)"

## ---- generated files ---------------------------------------------------

timeline:  ## regenerate wiki/timeline.md from the source pages
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/timeline.py

index:  ## regenerate index.md and the per-type indexes
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/index.py

check:  ## dry run both generators — shows drift without writing
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/timeline.py --check
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/index.py --check

lint:  ## structural problems: pages nothing links to, links to nothing
	@$(MAKE) --no-print-directory orphans
	@echo
	@cd $(WIKI) && echo "dangling links:" && \
	  $(GREP) -rhoE '\[\[[a-z0-9-]+\]\]' $(PAGES) | tr -d '[]' | sort -u \
	  | while read s; do \
	      test -n "$$($(FIND) $(PAGES) -name "$$s.md" -print -quit)" || echo "  [[$$s]]"; \
	    done

orphans:  ## pages that nothing links to
	@cd $(WIKI) && echo "orphan pages:" && \
	  $(FIND) $(PAGES) -name '*.md' -not -name 'index*' -not -name 'log.md' \
	    -not -name 'timeline.md' | while read f; do \
	      s=$$(basename "$$f" .md); \
	      $(GREP) -rq "\[\[$$s\]\]" $(PAGES) || echo "  $$s"; \
	    done

sources:  ## source pages by size — the unbloat watchlist
	@wc -l $(PAGES)/sources/*.md | sort -rn | head -20

## ---- handing it to someone else --------------------------------------

export:  ## copy the markdown out as a plain Obsidian vault (~/wiki-export-<date>)
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/export.py

export-zip:  ## same, plus a .zip ready to send
	@cd $(WIKI) && $(PYTHON) $(SCRIPTS)/export.py --zip

## ---- getting unstuck ---------------------------------------------------

unlock:  ## make raw/ writable again after a killed run
	@chmod -R u+w $(RAW) $(SCHEMA) $(WIKI)/CLAUDE.md
	@echo "raw/, schema/ and CLAUDE.md are writable again"

unstick:  ## clear a stale lock left by a run that was killed -9
	@rm -f $(STATE)/ingest.lock.pid
	@echo "lock cleared. Next drop will run."

## ---- git ---------------------------------------------------------------

save:  ## commit everything. MSG="..." to set the message
	@cd $(WIKI) && $(GIT) add -A && \
	  $(GIT) commit -m "$${MSG:-manual save}" && \
	  $(GIT) log --oneline -1

history:  ## recent commits
	@cd $(WIKI) && $(GIT) log --oneline -15
