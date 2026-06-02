#!/usr/bin/env python3
"""Compute plan-mode usage stats for the current Claude Code project.

Reads every session JSONL transcript in
~/.claude/projects/<encoded-cwd>/ and prints project-wide totals. A "turn"
is a real prompt the user typed; slash-command invocations ('/...') and their
stdout/caveat records are excluded. Metrics:

  * total turns, and the % of them spent in plan mode
  * % of presented plans (ExitPlanMode tool uses) that the user sent back
    with a typed change, instead of accepting via auto-accept / manually
    approve
  * % of presented plans the user rejected outright (kept planning) without
    typing a change

From these it derives a curved 0–10 planning score (square-root curve on
plan-mode usage plus a small diligence bonus for refined plans) and the
Patrol's verdict for that score.

Stdlib only.
"""

from __future__ import annotations

import json
import os
import sys
import unicodedata
from pathlib import Path


def display_width(text: str) -> int:
    """Terminal column width of 'text', accounting for wide glyphs.

    len() under-counts emoji (the verdict line uses them): they occupy two
    columns but one code point. Variation selectors / combining marks add no
    width; an emoji base — or any char wearing an emoji-presentation selector
    (U+FE0F) — and East-Asian wide/fullwidth chars take two.
    """
    chars = list(text)
    width = 0
    for i, ch in enumerate(chars):
        cp = ord(ch)
        if 0xFE00 <= cp <= 0xFE0F or unicodedata.combining(ch):
            continue
        emoji_presentation = i + 1 < len(chars) and ord(chars[i + 1]) == 0xFE0F
        if (
            emoji_presentation
            or cp >= 0x1F000
            or unicodedata.east_asian_width(ch) in ("W", "F")
        ):
            width += 2
        else:
            width += 1
    return width


def encode_cwd(cwd: str) -> str:
    """Mirror Claude Code's project-dir naming.

    Observed encoding: path separators and '.' are replaced with '-'.
    Example (POSIX):   '/Users/me/www/foo' -> '-Users-me-www-foo'.
    Example (Windows): 'C:\\Users\\me\\foo' -> 'C--Users-me-foo' — the
    backslash separators and the drive-letter colon are encoded too.
    """
    encoded = cwd
    for ch in ("/", "\\", ".", ":"):
        encoded = encoded.replace(ch, "-")
    return encoded


def find_transcripts() -> list[Path]:
    """All session transcripts for the current project, oldest-first."""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    encoded = encode_cwd(project_dir)
    projects_root = Path.home() / ".claude" / "projects" / encoded
    if not projects_root.is_dir():
        return []

    jsonls = [p for p in projects_root.glob("*.jsonl") if p.is_file()]
    return sorted(jsonls, key=lambda p: p.stat().st_mtime)


def is_real_user_turn(record: dict) -> bool:
    """A real user-typed prompt, not a tool-result echoed back as a user message.

    In the transcript every tool result is also stored as type='user' with
    role='user' and a content list containing tool_result blocks. We exclude
    those by requiring the content to be a plain string OR a list of blocks
    that does not include any tool_result.
    """
    if record.get("type") != "user":
        return False
    if record.get("isSidechain") is True:
        return False
    # isMeta marks injected, non-typed records: a slash command's expanded body
    # (e.g. '# /planning-patrol ...') and the local-command caveat.
    if record.get("isMeta") is True:
        return False
    msg = record.get("message") or {}
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return False
        return True
    return False


_COMMAND_MARKERS = (
    "<command-name>",
    "<command-message>",
    "<command-args>",
    "<local-command-stdout>",
    "<local-command-caveat>",
)


def is_slash_command(record: dict) -> bool:
    """True for a '/'-command invocation or its stdout/caveat wrapper records.

    These are stored as type='user' string-content messages carrying the
    command markers Claude Code writes; they are not prompts the user typed.
    """
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        return any(m in content for m in _COMMAND_MARKERS)
    return False


def is_interrupt_marker(record: dict) -> bool:
    """True for a harness-written interruption record, not a typed prompt.

    Interrupting a running tool call (or Claude mid-response) writes a
    type='user' message like '[Request interrupted by user for tool use]'.
    These are synthetic and must not count as turns. The text may be stored as
    a plain string or as a list of {"type":"text",...} blocks, so both are
    normalized. The prefix covers both observed variants ('...for tool use]'
    and the bare '...by user]').
    """
    content = (record.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = "".join(
            b.get("text", "")
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        return False
    return text.startswith("[Request interrupted by user")


def exit_plan_mode_tool_use_ids(record: dict) -> list[str]:
    """IDs of every ExitPlanMode tool_use in an assistant record (a presented plan)."""
    if record.get("type") != "assistant":
        return []
    msg = record.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, list):
        return []
    ids = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use" and block.get("name") == "ExitPlanMode":
            tid = block.get("id")
            if tid:
                ids.append(tid)
    return ids


def tool_results(record: dict):
    """Yield (tool_use_id, text) for every tool_result block in a user record.

    A block's content may be a plain string or a list of {"type":"text",...}
    blocks; both are normalized to a single string.
    """
    if record.get("type") != "user":
        return
    msg = record.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tid = block.get("tool_use_id")
        if not tid:
            continue
        raw = block.get("content")
        if isinstance(raw, list):
            text = " ".join(
                b.get("text", "") for b in raw if isinstance(b, dict)
            )
        else:
            text = raw if isinstance(raw, str) else ""
        yield tid, text


def is_typed_plan_feedback(text: str) -> bool:
    """True when the user typed a change into the plan-approval dialog.

    Only ever applied to tool_results whose id matches a known ExitPlanMode
    call. An approval reads 'User has approved your plan.'; a bare 'keep
    planning' rejection has no typed text; only a typed change carries the
    'the user said:' marker.
    """
    return "the user said:" in text


_REJECTION_MARKER = "The tool use was rejected"


def is_plan_rejected_outright(text: str) -> bool:
    """True when the user rejected the plan without typing a change.

    Distinct from a typed change (is_typed_plan_feedback, 'the user said:')
    and from approval ('User has approved your plan.'). Only applied to
    tool_results whose id matches a known ExitPlanMode call.
    """
    return _REJECTION_MARKER in text and not is_typed_plan_feedback(text)


def pct(num: int, denom: int) -> str:
    if denom == 0:
        return "n/a"
    return f"{(num / denom) * 100:.1f}%"


def verdict(score: float, total_turns: int) -> tuple[str, str]:
    """The Planning Patrol's ruling: an (emoji, headline) for the score.

    'score' is the curved 0–10 planning score; 'total_turns' guards the
    no-evidence case so an empty project doesn't get arrested on a 0 score.
    Each band is one point of the /10 scale.
    """
    if total_turns == 0:
        return "🕵️", "Case pending — not enough evidence yet."
    if score <= 0:
        return "🚔", "UNDER ARREST — you planned exactly nothing."
    if score < 2:
        return "🚓", "WANTED for reckless coding. The Patrol is closing in."
    if score < 4:
        return "⚠️", "ON PROBATION — caught winging it more than planning."
    if score < 6:
        return "🧐", "PERSON OF INTEREST — borderline responsible."
    if score < 8:
        return "🎖️", "MODEL CITIZEN — the Patrol salutes you."
    if score < 10:
        return "🏅", "DEPUTY OF THE MONTH — basically running the precinct."
    return "🏆", "CAPTAIN OF THE PATROL — a flawless planning record."


# Sentinel row: render a full-width horizontal divider inside the panel.
DIVIDER = object()


def render_panel(title: str, subtitle: str, rows: list) -> str:
    """Render a Claude-style bordered panel.

    'rows' is an ordered list whose items are one of:
      * a (label, value) pair — label left-aligned, value right-aligned in a
        shared value column;
      * a plain str — a full-width line spanning the panel;
      * None — a blank spacer line;
      * DIVIDER — a full-width horizontal rule across the panel.
    All glyphs used here are width-1, so len() is a correct measure of display
    width.
    """
    pairs = [r for r in rows if isinstance(r, tuple)]
    label_w = max((len(lbl) for lbl, _ in pairs), default=0)
    value_w = max((len(val) for _, val in pairs), default=0)
    gap = 4  # minimum spaces between the label column and the value column

    # Each body line is (is_divider, text); dividers ignore the text.
    body_lines = []
    for row in rows:
        if row is None:
            body_lines.append((False, ""))
        elif row is DIVIDER:
            body_lines.append((True, ""))
        elif isinstance(row, tuple):
            label, value = row
            body_lines.append(
                (False, f"{label.ljust(label_w)}{' ' * gap}{value.rjust(value_w)}")
            )
        else:
            body_lines.append((False, str(row)))

    title_seg = f"✻ {title}"
    # Inner width between the side paddings, shared by every line and both
    # borders so the right edge always lines up. Measured in terminal columns
    # so wide glyphs (e.g. the verdict emoji) don't push the edge out.
    content_w = max(
        display_width(subtitle),
        display_width(title_seg),
        *(display_width(t) for _, t in body_lines),
    )

    def pad(text: str) -> str:
        return text + " " * (content_w - display_width(text))

    out = [f"╭─ {title_seg} " + "─" * (content_w - display_width(title_seg) - 1) + "╮"]
    out.append(f"│ {pad(subtitle)} │")
    out.append(f"│ {' ' * content_w} │")
    for is_divider, text in body_lines:
        if is_divider:
            out.append("├" + "─" * (content_w + 2) + "┤")
        else:
            out.append(f"│ {pad(text)} │")
    out.append("╰" + "─" * (content_w + 2) + "╯")
    return "\n".join(out)


def main() -> int:
    # The panel uses box-drawing glyphs and emoji; force UTF-8 so they encode
    # on legacy Windows consoles (non-UTF-8 codepage) instead of raising.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass  # older Python / non-reconfigurable stream — leave as-is

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    transcripts = find_transcripts()
    if not transcripts:
        print("planning-patrol: no transcripts found for this project.")
        print("Tried: ~/.claude/projects/" + encode_cwd(project_dir))
        return 0

    total_user_turns = 0
    plan_mode_user_turns = 0
    plans_created = 0
    plans_sent_back = 0
    plans_rejected = 0

    try:
        for transcript in transcripts:
            # A plan left un-answered at the end of one session must not be
            # credited to a result in the next, so reset per file.
            pending_plan_ids: set[str] = set()
            with transcript.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if (
                        is_real_user_turn(record)
                        and not is_slash_command(record)
                        and not is_interrupt_marker(record)
                    ):
                        total_user_turns += 1
                        if record.get("permissionMode") == "plan":
                            plan_mode_user_turns += 1

                    for tid, text in tool_results(record):
                        if tid not in pending_plan_ids:
                            continue
                        if is_typed_plan_feedback(text):
                            plans_sent_back += 1
                        elif is_plan_rejected_outright(text):
                            plans_rejected += 1
                        pending_plan_ids.discard(tid)

                    ids = exit_plan_mode_tool_use_ids(record)
                    plans_created += len(ids)
                    pending_plan_ids.update(ids)
    except OSError as e:
        print(f"planning-patrol: could not read transcript: {e}", file=sys.stderr)
        return 1

    rows = [
        ("Sessions", str(len(transcripts))),
        ("All tasks", str(total_user_turns)),
        (
            "Tasks in plan mode",
            f"{plan_mode_user_turns}  ({pct(plan_mode_user_turns, total_user_turns)})",
        ),
        None,
        ("Plans created", str(plans_created)),
    ]
    if plans_created == 0:
        rows.append(("Plans sent back for changes", "n/a — no plans created"))
        rows.append(("Plans rejected", "n/a — no plans created"))
    else:
        rows.append(
            (
                "Plans sent back for changes",
                f"{plans_sent_back}  ({pct(plans_sent_back, plans_created)})",
            )
        )
        rows.append(
            ("Plans rejected", f"{plans_rejected}  ({pct(plans_rejected, plans_created)})")
        )

    # Curved 0–10 planning score: plan-mode usage is the base, run through a
    # square-root curve so steady planning is rewarded instead of only a
    # perfect 100%. Refining a plan (sending it back for changes) adds a small
    # diligence bonus (up to +1.5), which keeps the top tier reachable with
    # strong-but-real planning.
    plan_mode_frac = (
        plan_mode_user_turns / total_user_turns if total_user_turns else 0.0
    )
    sent_back_frac = plans_sent_back / plans_created if plans_created else 0.0
    score = min(10.0, (plan_mode_frac ** 0.5) * 10 + 1.5 * sent_back_frac)
    emoji, headline = verdict(score, total_user_turns)

    rows.append(DIVIDER)
    rows.append(("🎯 Your score", f"{score:.1f} / 10"))
    rows.append(f"{emoji} Patrol verdict: {headline}")
    print(render_panel("The Planning Patrol", project_dir, rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
