#!/bin/bash
# Install, remove or inspect the inbox watcher.
#
# The watcher is deliberately the LAST thing built. You only automate a loop you
# have watched work, and this one was run by hand over ten real sources first.
#
#   watcher.sh install     copy the plist into LaunchAgents and load it
#   watcher.sh uninstall   unload and remove it
#   watcher.sh status      is it loaded, and what did it last do
#   watcher.sh run         run one ingest now, in the foreground, no launchd

set -uo pipefail
WIKI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # wherever this repo lives
LABEL="${WIKI_LABEL:-com.wiki.ingest}"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SRC="$WIKI/ops/wiki-ingest.plist"

case "${1:-status}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents"
    sed -e "s|__HOME__|$HOME|g" -e "s|__WIKI__|$WIKI|g" -e "s|__LABEL__|$LABEL|g" \
      -e "s|__HARNESS__|${WIKI_HARNESS:-claude}|g" -e "s|__MODEL__|${WIKI_MODEL:-}|g" \
      "$SRC" > "$PLIST"
    launchctl unload "$PLIST" 2>/dev/null
    launchctl load "$PLIST" && echo "loaded $LABEL"
    echo
    echo "Watching: $WIKI/inbox"
    echo "Log:      $WIKI/.state/ingest.log"
    echo
    echo "Drop a file in the inbox. A run starts once the folder stops changing"
    echo "for 60 seconds, and finishes with a desktop notification."
    ;;
  uninstall)
    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST" && echo "removed $LABEL — the inbox is now a plain folder again"
    ;;
  run)
    echo "running one ingest in the foreground…"
    bash "$WIKI/scripts/ingest.sh"
    echo "done — see $WIKI/.state/ingest.log"
    ;;
  status)
    # `launchctl list` exits non-zero even when it prints. With pipefail that
    # made a successful grep look like a failure, so status reported NOT LOADED
    # while the job was live. Capture first, then test.
    loaded=$(launchctl list 2>/dev/null | grep "$LABEL" || true)
    if [ -n "$loaded" ]; then
      echo "LOADED    $loaded"
    else
      echo "NOT LOADED   install with: scripts/watcher.sh install"
    fi
    echo "plist:    $([ -f "$PLIST" ] && echo "$PLIST" || echo '(not installed)')"
    n=$(find "$WIKI/inbox" -type f ! -name '.*' -not -path '*/_review/*' -not -path '*/_done/*' -not -path '*/_hold/*' 2>/dev/null | wc -l | tr -d ' ')
    d=$(find "$WIKI/inbox/_done" -type f ! -name '.*' 2>/dev/null | wc -l | tr -d ' ')
    echo "inbox:    $n file(s)   (_done archive holds $d)"
    if [ ! -w "$WIKI/raw" ]; then
      echo "perms:    raw/ IS READ-ONLY — a run was killed before it restored them."
      echo "          fix: make unlock"
    fi
    if python3 -c "
import json,pathlib,sys
d=json.loads((pathlib.Path.home()/'.claude.json').read_text())
sys.exit(0 if d.get('projects',{}).get('$WIKI',{}).get('hasTrustDialogAccepted') else 1)" 2>/dev/null; then
      echo "trust:    workspace trusted"
    else
      echo "trust:    NOT TRUSTED — unattended runs will do nothing."
      echo "          Fix once: cd $WIKI && claude   (accept the prompt, then quit)"
    fi
    if [ -f "$WIKI/.state/ingest.log" ]; then
      echo
      echo "last activity:"
      tail -6 "$WIKI/.state/ingest.log" | sed 's/^/  /'
    fi
    ;;
  *) echo "usage: watcher.sh {install|uninstall|status|run}"; exit 2 ;;
esac
