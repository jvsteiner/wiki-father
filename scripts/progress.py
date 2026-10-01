#!/usr/bin/env python3
"""Turn an omp/claude JSON event stream into one readable progress line per action.

Eleven minutes of silence is indistinguishable from a hang. The first runs hit exactly
that and reasonably concluded the run was dead. The stream passes through
unchanged on stdout; a short human line goes to stderr, which the caller appends
to the log as it happens rather than after the run ends.
"""
import json, sys, time

start = time.time()
seen_tools = []
seen_ids = set()
turns = [0]
def note(s):
    print(f"    [{int(time.time()-start):>4}s] {s}", file=sys.stderr, flush=True)

for line in sys.stdin:
    sys.stdout.write(line)          # pass the stream through untouched
    sys.stdout.flush()
    try:
        d = json.loads(line)
    except Exception:
        continue
    t = d.get("type")
    m = d.get("message") or {}

    # omp: tool calls arrive as deltas; claude: as content blocks
    # omp calls them "toolCall"; claude calls them "tool_use". The first version
    # only matched claude's, so a whole run logged zero tool calls and the
    # question "why so many turns?" could not be answered afterwards.
    # Content blocks repeat across message_start / message_end / turn_end, so
    # counting them wherever they appear multiplied every tool call by ~3.5.
    # Second failed attempt at this. Dedupe by the tool call's own id.
    ev = d.get("assistantMessageEvent") or {}
    if ev.get("type") == "tool_start":
        seen_tools.append(ev.get("name", "tool"))
        note(f"#{len(seen_tools)} {ev.get('name','tool')} {str(ev.get('input',''))[:70]}")
    for c in (m.get("content") or []):
        if c.get("type") in ("tool_use", "toolCall"):
            cid = c.get("id") or f"{c.get('name')}:{str(c.get('input') or c.get('arguments'))[:80]}"
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            name = c.get("name")
            a = c.get("input") or c.get("arguments") or {}
            if isinstance(a, str):
                a = {}
            arg = a.get("file_path") or a.get("path") or a.get("command") or a.get("pattern") or ""
            seen_tools.append(name)
            note(f"#{len(seen_tools)} {name} {str(arg)[:70]}")
        elif c.get("type") == "text" and c.get("text", "").strip() and m.get("role") == "assistant":
            note("   " + c["text"].strip().split("\n")[0][:100])

    # count a turn once. Both message_end and turn_end carry usage, which was
    # doubling every line.
    if m.get("usage") and d.get("type") == "turn_end":
        u = m["usage"]
        turns[0] += 1
        cost = (u.get("cost") or {}).get("total", 0)
        note(f"   turn {turns[0]} done — ${cost:.4f}  "
             f"out {u.get('output', 0)}  tools so far {len(seen_tools)}")
