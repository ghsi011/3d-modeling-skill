#!/usr/bin/env python3
"""L0 -- the post-mortem instrument has to be able to report the wrong answer.

This measures where an agent-driven run's wall clock went, and every number it
produces is one somebody will later use to justify a change to how roles are
dispatched. So the properties that matter are the ones that would let it lie
quietly: a gap attributed to the wrong side, a residual that is really a units
error, a total that does not add up to the span it decomposed.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent_postmortem as PM                                     # noqa: E402


def assistant(at: str, *, out: int = 0, tools=(), thinking: str = "",
              text: str = "") -> dict:
    content: list[dict] = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking})
    if text:
        content.append({"type": "text", "text": text})
    for name, payload in tools:
        content.append({"type": "tool_use", "name": name, "input": payload})
    return {"type": "assistant", "timestamp": at,
            "message": {"content": content, "usage": {"output_tokens": out}}}


def result(at: str) -> dict:
    return {"type": "user", "timestamp": at,
            "message": {"content": [{"type": "tool_result", "content": "ok"}]}}


class GapsAreAttributedToTheSideThatSpentThemTest(unittest.TestCase):
    def test_waiting_for_a_tool_result_is_tool_time(self) -> None:
        rows = [assistant("2026-08-17T10:00:00Z", tools=[("Bash", {"command": "x"})]),
                result("2026-08-17T10:00:30Z")]
        d = PM.decompose(rows)
        self.assertAlmostEqual(30.0, d.tool_s, places=3)
        self.assertAlmostEqual(0.0, d.model_s, places=3)

    def test_waiting_for_the_next_assistant_message_is_model_time(self) -> None:
        rows = [result("2026-08-17T10:00:00Z"),
                assistant("2026-08-17T10:00:45Z", out=10)]
        d = PM.decompose(rows)
        self.assertAlmostEqual(45.0, d.model_s, places=3)
        self.assertAlmostEqual(0.0, d.tool_s, places=3)

    def test_an_assistant_message_with_no_tool_call_does_not_book_tool_time(self) -> None:
        """The discriminating case. A plain answer followed by anything is not
        the harness running a tool, and booking it as tool time would inflate
        exactly the number that decides whether tools are worth optimising."""
        rows = [assistant("2026-08-17T10:00:00Z", out=5, text="done"),
                result("2026-08-17T10:00:20Z")]
        d = PM.decompose(rows)
        self.assertAlmostEqual(0.0, d.tool_s, places=3)

    def test_the_parts_add_up_to_the_span(self) -> None:
        """Conservation. Any misclassification that loses time shows up here."""
        rows = [assistant("2026-08-17T10:00:00Z", out=5, tools=[("Bash", {"c": "1"})]),
                result("2026-08-17T10:00:10Z"),
                assistant("2026-08-17T10:00:25Z", out=7, tools=[("Read", {"p": "a"})]),
                result("2026-08-17T10:00:31Z"),
                assistant("2026-08-17T10:01:00Z", out=9, text="fin")]
        d = PM.decompose(rows)
        self.assertAlmostEqual(60.0, d.span_s, places=3)
        self.assertAlmostEqual(d.span_s, d.model_s + d.tool_s + d.other_s, places=6)

    def test_a_trailing_tool_call_with_no_result_books_nothing(self) -> None:
        rows = [assistant("2026-08-17T10:00:00Z", tools=[("Bash", {"c": "1"})])]
        d = PM.decompose(rows)
        self.assertAlmostEqual(0.0, d.tool_s, places=3)
        self.assertAlmostEqual(0.0, d.span_s, places=3)

    def test_out_of_order_lines_are_sorted_before_decomposition(self) -> None:
        """Transcripts are appended concurrently; a later line can be written
        first. Unsorted, this produces negative gaps that silently cancel."""
        rows = [result("2026-08-17T10:00:30Z"),
                assistant("2026-08-17T10:00:00Z", tools=[("Bash", {"c": "1"})])]
        d = PM.decompose(rows)
        self.assertAlmostEqual(30.0, d.tool_s, places=3)


class AParentsToolTimeIsItsChildrensSpanTest(unittest.TestCase):
    """The correction that changed the headline number.

    An orchestrator waiting on `Agent` is not waiting on the harness in the
    sense a leaf role is -- that gap *is* the child's whole span, which appears
    again in the child's own transcript. Summing the two double-counts, and it
    double-counts in the direction that makes tool time look like the lever:
    over one real run it reported 59.7% model time where the roles that do the
    work were at 87.1%.
    """

    def test_a_transcript_that_dispatches_children_is_a_parent(self) -> None:
        rows = [assistant("2026-08-17T10:00:00Z", tools=[("Agent", {"p": "go"})]),
                result("2026-08-17T10:30:00Z")]
        self.assertTrue(PM.decompose(rows).is_parent)

    def test_a_transcript_that_only_runs_tools_is_a_leaf(self) -> None:
        rows = [assistant("2026-08-17T10:00:00Z", tools=[("Bash", {"c": "1"})]),
                result("2026-08-17T10:00:10Z")]
        self.assertFalse(PM.decompose(rows).is_parent)

    def test_the_two_classes_are_summarised_apart(self) -> None:
        parent = PM.decompose(
            [assistant("2026-08-17T10:00:00Z", tools=[("Agent", {"p": "go"})]),
             result("2026-08-17T10:30:00Z")])
        leaf = PM.decompose(
            [result("2026-08-17T10:00:00Z"),
             assistant("2026-08-17T10:10:00Z", out=1)])
        summary = PM.summarise([("p.jsonl", parent), ("l.jsonl", leaf)])
        self.assertAlmostEqual(1800.0, summary["parent"]["tool_s"], places=3)
        self.assertAlmostEqual(600.0, summary["leaf"]["model_s"], places=3)
        # The leaf aggregate must not carry the parent's waiting-on-children time.
        self.assertAlmostEqual(0.0, summary["leaf"]["tool_s"], places=3)


class TheSinceCutoffIsAnInstantNotATest(unittest.TestCase):
    """**This proves `--since` filters by time, because it fails when the cutoff
    is compared as text.**

    `_timestamp` normalises a transcript's `Z` to `+00:00`. Compared as strings,
    `"...+00:00" < "...Z"` is true on spelling alone -- `+` sorts below `Z` -- so
    a transcript ending exactly at a `Z`-spelled cutoff was dropped from a filter
    documented as inclusive, and two equal instants written with different
    offsets ordered by spelling rather than by time.
    """

    def test_the_z_suffix_and_the_offset_are_the_same_instant(self) -> None:
        self.assertEqual(PM.parse_instant("2026-08-17T06:00:00Z"),
                         PM.parse_instant("2026-08-17T06:00:00+00:00"))

    def test_a_naive_cutoff_is_read_as_utc(self) -> None:
        """`--since 2026-08-17T06:00` is the form a person types."""
        self.assertEqual(PM.parse_instant("2026-08-17T06:00:00"),
                         PM.parse_instant("2026-08-17T06:00:00Z"))

    def test_equal_instants_do_not_order_by_spelling(self) -> None:
        z = PM.parse_instant("2026-08-17T06:00:00Z")
        offset = PM.parse_instant("2026-08-17T08:00:00+02:00")
        self.assertEqual(z, offset)
        self.assertFalse(z < offset)
        # The string comparison this replaced gets it backwards.
        self.assertTrue("2026-08-17T06:00:00+00:00" < "2026-08-17T06:00:00Z")


class TheResidualIsASubtractionAndSaysSoTest(unittest.TestCase):
    def test_visible_characters_are_counted_per_block_kind(self) -> None:
        rows = [assistant("2026-08-17T10:00:00Z", out=100,
                          thinking="a" * 36, text="b" * 18,
                          tools=[("Bash", {"command": "c" * 10})])]
        d = PM.decompose(rows)
        self.assertEqual(36, d.visible_chars["thinking"])
        self.assertEqual(18, d.visible_chars["prose"])
        self.assertGreaterEqual(d.visible_chars["tool_args"], 10)

    def test_the_residual_is_billed_minus_visible(self) -> None:
        rows = [assistant("2026-08-17T10:00:00Z", out=100, thinking="a" * 360)]
        d = PM.decompose(rows)
        # 360 chars at 3.6 chars/token is 100 tokens visible against 100 billed.
        self.assertAlmostEqual(0.0, PM.residual(d, chars_per_token=3.6), places=6)

    def test_more_visible_than_billed_is_reported_and_not_clamped(self) -> None:
        """A negative residual means the constant is wrong, and that is a fact
        about the instrument. Clamping it to zero would hide the one signal
        that says so."""
        rows = [assistant("2026-08-17T10:00:00Z", out=1, thinking="a" * 3600)]
        self.assertLess(PM.residual(PM.decompose(rows), chars_per_token=3.6), 0.0)


if __name__ == "__main__":
    unittest.main()
