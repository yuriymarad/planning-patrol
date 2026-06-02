# 🚨 The Planning Patrol

Did you *plan* that code... or did you just wing it?

The Planning Patrol pulls you over, checks your record, and hands down a verdict —
from **UNDER ARREST** 🚔 to **CAPTAIN OF THE PATROL** 🎖️.

## Safety 🔒

The plugin is safe — it's strictly **read-only**. It only reads the session
transcripts Claude Code already saves under `~/.claude/projects/`. It never writes, deletes, renames, or modifies any
file, runs no other programs, and makes no network calls.

## Install

```
/plugin marketplace add yuriymarad/planning-patrol
/plugin install planning-patrol@planning-patrol
```

## Use it

In any project, run:

```
/planning-patrol
```

Wing it, and the Patrol throws the book at you 🚔:

```
╭─ ✻ The Planning Patrol ───────────────────────────────────────────────╮
│ /Users/you/www/proj                                                   │
│                                                                       │
│ Sessions                                            1                 │
│ All tasks                                           2                 │
│ Tasks in plan mode                          0  (0.0%)                 │
│                                                                       │
│ Plans created                                       0                 │
│ Plans sent back for changes    n/a — no plans created                 │
│ Plans rejected                 n/a — no plans created                 │
├───────────────────────────────────────────────────────────────────────┤
│ 🚔 Patrol verdict: 0.0% — UNDER ARREST — you planned exactly nothing. │
╰───────────────────────────────────────────────────────────────────────╯
```

Plan like a pro, and you make Captain 🏆:

```
╭─ ✻ The Planning Patrol ─────────────────────────────────────────────────────────╮
│ /Users/you/www/proj                                                             │
│                                                                                 │
│ Sessions                                  6                                     │
│ All tasks                                73                                     │
│ Tasks in plan mode             73  (100.0%)                                     │
│                                                                                 │
│ Plans created                            18                                     │
│ Plans sent back for changes      6  (33.3%)                                     │
│ Plans rejected                    1  (5.6%)                                     │
├─────────────────────────────────────────────────────────────────────────────────┤
│ 🏆 Patrol verdict: 100.0% — CAPTAIN OF THE PATROL — a flawless planning record. │
╰─────────────────────────────────────────────────────────────────────────────────╯
```

## How the score works

It reads the session transcripts Claude Code already saves and tallies:

- **Plan mode usage** — how often you planned before typing prompts.
- **Plans sent back** — plans you bounced back with a tweak (a little diligence bonus 👍).
- **Plans rejected** — plans you threw out and kept planning.

**Score** = plan-mode % + a quarter-point for every plan you sent back, capped at 100.
Higher score, better rap sheet.

No background process. No extra files. It only looks when you ask.

## Debugging

```
CLAUDE_PROJECT_DIR=/path/to/project python3 scripts/compute_stats.py
```

Python 3, stdlib only. That's it. 🚓
