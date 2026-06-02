---
description: Call The Planning Patrol and show plan-mode stats with verdic for the current project.
allowed-tools: [Bash]
---

# /call

Run the bundled stats script and print its output verbatim — do NOT reformat, summarize, or add commentary around it.

## Instructions

1. Execute: `PY="$(command -v python3 || command -v python)"; "$PY" "${CLAUDE_PLUGIN_ROOT}/scripts/compute_stats.py"` (resolves `python3` on macOS/Linux, falls back to `python` on Windows)
2. Print the script's stdout to the user exactly as-is, inside a fenced code block.
3. If the script exits non-zero, surface the stderr so the user can see the error.
