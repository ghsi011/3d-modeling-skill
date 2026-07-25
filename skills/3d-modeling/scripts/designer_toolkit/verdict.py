"""The verdict vocabulary every check speaks.

One definition, because two modules producing checks that merely look alike is
how a receipt starts disagreeing with the gate that wrote it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIPPED"


@dataclass
class Check:
    """One deterministic verdict, with the action to take when it fails.

    `action` is not decoration. A failure that does not say what to change sends
    the agent back to guessing, and guessing costs a full build/export/measure
    cycle per guess.
    """

    id: str
    title: str
    result: str
    detail: str
    action: str = ""

    def as_dict(self) -> dict[str, Any]:
        out = {"id": self.id, "title": self.title, "result": self.result, "detail": self.detail}
        if self.action:
            out["next_action"] = self.action
        return out
