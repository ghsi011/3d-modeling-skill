#!/usr/bin/env python3
"""Where an agent-driven run's wall clock went, from the session transcripts.

`ARCHITECTURE.md` 15.6 and `MISSION.md` make efficiency a first-class objective,
and `pipeline/cost.py` measures the half of it this program owns: dispatch
count, context bytes, deterministic seconds. The other half was never measured
because it happens outside the process -- an agent reading, thinking and writing
between two invocations of `design-tool run`. On the first agent-driven live F1
commission that half was **99.68%** of the wall clock: 33.99 s of deterministic
pipeline against a 2 h 57 m run. A number that large and that unmeasured is not
a footnote.

The session transcripts already hold what is needed: one line per message, each
with a timestamp and, on assistant messages, a `usage` block. This reads them.

**What it decomposes, and why the split is the whole point.** Between two
adjacent events exactly one party is being waited on:

* an assistant message that asked for a tool, followed by its result, is time
  the *harness* spent -- `TOOL`;
* anything followed by an assistant message is time the *model* spent -- `MODEL`.

Every gap lands in exactly one bucket and the buckets sum to the span, which
`test_the_parts_add_up_to_the_span` asserts, because a decomposition that loses
time can be wrong in the direction that flatters whichever fix is proposed.

**The residual, and the proxy that had to be thrown away first.** `usage`
reports `output_tokens` for a whole message but does not break it down, so the
obvious move is to apportion those tokens across the message's blocks by
character count. That proxy was tried and it failed its own sanity check: it
credited `Bash` with 419,701 output tokens across a run whose every Bash command
concatenated is 159,619 characters, about 44,000 tokens -- a tenfold
disagreement with a direct count of the same text. It fails because a reasoning
model's billed output includes reasoning the transcript does not store as text
(only 31.2% of assistant messages carried a stored thinking block at all), so
apportionment shovels those tokens onto whatever else happened to be in the
message.

So nothing here is apportioned. Characters are counted per block kind directly,
and the difference between billed tokens and visible ones is reported as a
**residual**: a subtraction of two measured quantities, not a model of anything.
On that same run the residual was 71.6% of all billed output, stable between
66.6% and 75.3% across a +/-15% sweep of the chars-per-token constant -- which is
why `report` prints the sweep rather than a single number. A residual computed
from a wrong constant is a units error wearing a conclusion's clothes.

`residual` deliberately returns a negative number when visible output exceeds
billed output. That can only mean the constant is wrong, and it is the single
signal that says so; clamping it to zero would delete the instrument's own
error term.

Usage:

    uv run python tools/agent_postmortem.py <session-dir> [--since ISO8601]

where `<session-dir>` holds `agent-*.jsonl` subagent transcripts.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import io
import json
from pathlib import Path
from typing import Any, Iterable

# Measured on this repository's own transcripts. Every figure derived from it is
# reported alongside a sweep, because it is a calibration and not a constant of
# nature.
CHARS_PER_TOKEN = 3.6

AUTHORING_TOOLS = frozenset({"Write", "Edit", "NotebookEdit"})


def _timestamp(row: dict) -> dt.datetime | None:
    raw = row.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _tool_calls(row: dict) -> list[dict]:
    message = row.get("message") or {}
    return [b for b in message.get("content") or ()
            if isinstance(b, dict) and b.get("type") == "tool_use"]


@dataclasses.dataclass
class Decomposition:
    """One transcript's wall clock and output, decomposed and never apportioned."""

    span_s: float = 0.0
    model_s: float = 0.0
    tool_s: float = 0.0
    other_s: float = 0.0
    turns: int = 0
    events: int = 0
    billed_output: int = 0
    visible_chars: dict[str, int] = dataclasses.field(
        default_factory=lambda: {"thinking": 0, "prose": 0, "tool_args": 0})
    tool_seconds: dict[str, float] = dataclasses.field(default_factory=dict)
    tool_calls: dict[str, int] = dataclasses.field(default_factory=dict)
    tool_arg_chars: dict[str, int] = dataclasses.field(default_factory=dict)
    turns_with_stored_thinking: int = 0
    started: str = ""
    ended: str = ""

    @property
    def visible_total_chars(self) -> int:
        return sum(self.visible_chars.values())

    def generation_rate(self) -> float:
        """Billed output tokens per second of model time.

        The term that turns tokens into wall clock, and the reason token counts
        are a speed measurement here rather than a cost one.
        """
        return self.billed_output / self.model_s if self.model_s else 0.0


def decompose(rows: Iterable[dict]) -> Decomposition:
    """Split one transcript's span into who was being waited on.

    Rows are sorted by timestamp first. Transcripts are appended by concurrent
    writers and a later line can land earlier in the file; unsorted, the
    resulting negative gaps cancel silently against real ones.
    """
    timed = [(t, r) for r in rows if (t := _timestamp(r)) is not None]
    timed.sort(key=lambda pair: pair[0])
    out = Decomposition(events=len(timed))
    if not timed:
        return out

    out.started = timed[0][0].isoformat()
    out.ended = timed[-1][0].isoformat()
    out.span_s = (timed[-1][0] - timed[0][0]).total_seconds()

    for _, row in timed:
        if row.get("type") != "assistant":
            continue
        out.turns += 1
        message = row.get("message") or {}
        usage = message.get("usage") or {}
        out.billed_output += int(usage.get("output_tokens") or 0)
        stored_thinking = False
        for block in message.get("content") or ():
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "thinking":
                out.visible_chars["thinking"] += len(block.get("thinking") or "")
                stored_thinking = True
            elif kind == "text":
                out.visible_chars["prose"] += len(block.get("text") or "")
            elif kind == "tool_use":
                size = len(json.dumps(block.get("input") or {}))
                name = str(block.get("name") or "?")
                out.visible_chars["tool_args"] += size
                out.tool_arg_chars[name] = out.tool_arg_chars.get(name, 0) + size
                out.tool_calls[name] = out.tool_calls.get(name, 0) + 1
        if stored_thinking:
            out.turns_with_stored_thinking += 1

    for (t_prev, prev), (t_cur, cur) in zip(timed, timed[1:]):
        gap = (t_cur - t_prev).total_seconds()
        calls = _tool_calls(prev)
        if calls and cur.get("type") == "user":
            out.tool_s += gap
            for call in calls:
                name = str(call.get("name") or "?")
                out.tool_seconds[name] = out.tool_seconds.get(name, 0.0) + gap
        elif cur.get("type") == "assistant":
            out.model_s += gap
        else:
            out.other_s += gap
    return out


def residual(d: Decomposition, *, chars_per_token: float = CHARS_PER_TOKEN) -> float:
    """Billed output tokens minus the ones visible in the transcript.

    Negative is meaningful and is returned as such -- see the module docstring.
    """
    if chars_per_token <= 0:
        raise ValueError("chars_per_token must be positive")
    return d.billed_output - d.visible_total_chars / chars_per_token


def read_transcript(path: Path) -> list[dict]:
    rows: list[dict] = []
    with io.open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def report(session_dir: Path, *, since: str = "") -> dict[str, Any]:
    """Every subagent transcript in one session, slowest first."""
    rows: list[tuple[str, Decomposition]] = []
    for path in sorted(Path(session_dir).glob("agent-*.jsonl")):
        d = decompose(read_transcript(path))
        if d.events < 2:
            continue
        if since and d.ended < since:
            continue
        rows.append((path.name, d))
    rows.sort(key=lambda pair: pair[1].span_s, reverse=True)

    print(f"{len(rows)} transcript(s) in {session_dir}"
          + (f" ending at or after {since}" if since else ""))
    print()
    span = model = tool = 0.0
    billed = 0
    visible = 0
    for name, d in rows:
        span += d.span_s; model += d.model_s; tool += d.tool_s
        billed += d.billed_output; visible += d.visible_total_chars
        pct = lambda x: 100.0 * x / d.span_s if d.span_s else 0.0
        print(f"--- {name}  {d.span_s/60:.1f} min")
        print(f"    MODEL {d.model_s/60:6.1f} min ({pct(d.model_s):4.1f}%)   "
              f"TOOL {d.tool_s/60:6.1f} min ({pct(d.tool_s):4.1f}%)")
        print(f"    turns {d.turns:4d}   billed_out {d.billed_output:>9,}   "
              f"{d.generation_rate():5.1f} tok/s   "
              f"stored thinking on {d.turns_with_stored_thinking}/{d.turns} turns")
        busiest = sorted(d.tool_seconds.items(), key=lambda kv: kv[1], reverse=True)[:5]
        if busiest:
            print("    tools: " + ", ".join(
                f"{k} {v/60:.1f}m x{d.tool_calls.get(k, 0)}" for k, v in busiest))
    print()
    print("=" * 72)
    if span:
        print(f"span {span/3600:.2f} h   MODEL {model/3600:.2f} h "
              f"({100*model/span:.1f}%)   TOOL {tool/3600:.2f} h ({100*tool/span:.1f}%)")
    print(f"billed output {billed:,} tok   visible in transcript "
          f"{visible/CHARS_PER_TOKEN:,.0f} tok")
    print("residual (billed - visible), swept over the chars/token calibration:")
    for cpt in (CHARS_PER_TOKEN * 0.85, CHARS_PER_TOKEN, CHARS_PER_TOKEN * 1.15):
        left = billed - visible / cpt
        share = 100.0 * left / billed if billed else 0.0
        print(f"  {cpt:.2f} chars/tok -> {left:>12,.0f} tok ({share:5.1f}% of billed)")
    return {"transcripts": len(rows), "span_s": span, "model_s": model,
            "tool_s": tool, "billed_output": billed}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("session_dir", type=Path,
                        help="directory holding agent-*.jsonl transcripts")
    parser.add_argument("--since", default="",
                        help="ignore transcripts that ended before this ISO 8601 instant")
    args = parser.parse_args(argv)
    if not args.session_dir.is_dir():
        parser.error(f"{args.session_dir} is not a directory")
    report(args.session_dir, since=args.since)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
