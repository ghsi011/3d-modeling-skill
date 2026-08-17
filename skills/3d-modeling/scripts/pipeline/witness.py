#!/usr/bin/env python3
"""W1: the compact routine witness, with budgets that are enforced.

A witness level with no ceiling grows one view at a time until it is the dominant
cost, and every addition looks reasonable on its own. So the budgets below are
checked in code and exceeding one is a build failure, not a slow run.

W1 is what a clean `DIRECT` job produces and what the safety verifier gets first.
W2 and W3 are specified in the plan and **not built yet**: `generate` takes a
`level` and only ever receives the default. Escalation currently changes the
status, not the evidence.
"""
from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Any

from .analysis import MeasurementFailed

MAX_RESOLUTION_PX = 512
MAX_SECTIONS = 12
MAX_SECONDS = 2.0


class BudgetExceeded(RuntimeError):
    """A witness level outgrew its ceiling."""


@dataclasses.dataclass
class Witness:
    level: str
    images: tuple[str, ...]
    sections: tuple[dict[str, Any], ...]
    seconds: float
    renderer: str

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "images": list(self.images),
                "sections": list(self.sections), "renderer": self.renderer,
                "rendered": bool(self.images),
                "budgets": {"resolution_px": MAX_RESOLUTION_PX,
                            "sections": MAX_SECTIONS, "seconds": MAX_SECONDS}}


def _sections(ctx, contract, limit: int) -> tuple[dict[str, Any], ...]:
    """Uniformly spaced heights, plus one per declared feature that names a Z.

    Uniform coverage is what nobody had to anticipate; the feature heights are
    what somebody did. Both, capped, because a section list that grows with the
    feature count is the budget leaking out through the back.
    """
    marks: list[float] = []
    for feature in contract.features:
        exp = feature.expectation
        at = exp.get("at") or {}
        if "z" in at:
            marks.append(float(at["z"]))
        elif "z" in exp:
            marks.append(float(exp["z"]))

    low, high = float(ctx.bounds[0][2]), float(ctx.bounds[1][2])
    room = max(limit - len(marks), 0)
    if room:
        step = (high - low) / (room + 1)
        marks += [low + step * (i + 1) for i in range(room)]

    # Not truncated here. Silently trimming to the budget made the budget check
    # downstream structurally unreachable -- 500 declared features produced
    # exactly 12 rows and the guard compared 12 > 12. A budget that cannot fire
    # is a comment, and this module's docstring sells it as a build failure.
    rows = []
    for z in sorted(set(round(v, 3) for v in marks)):
        try:
            area = round(ctx.section_area(z), 3)
        except MeasurementFailed as exc:
            rows.append({"z": z, "area_mm2": None, "status": "UNAVAILABLE",
                         "error_code": exc.code, "error_message": str(exc)})
        else:
            rows.append({"z": z, "area_mm2": area, "status": "MEASURED"})
    return tuple(rows)


def generate(ctx, contract, out_dir: Path, *, level: str = "W1",
             render: bool = True) -> Witness:
    started = time.perf_counter()
    out_dir.mkdir(parents=True, exist_ok=True)

    sections = _sections(ctx, contract, MAX_SECTIONS)
    # Checked before anything is rendered: a part with more declared heights than
    # the level allows is a contract to fix, not a witness to quietly shorten.
    if len(sections) > MAX_SECTIONS:
        raise BudgetExceeded(
            f"{level}: {len(sections)} sections exceeds the {MAX_SECTIONS} budget. "
            "Raise the level or declare fewer heights -- trimming silently would "
            "drop exactly the sections somebody asked for.")
    images: list[str] = []
    renderer = "none"

    if render:
        try:
            import preview
            from designer_toolkit.render import section_render
            renderer = "preview+section"
            multi = out_dir / "multi.png"
            # `view_size`, not `resolution`. The keyword was wrong since this
            # call was written, so `render_multi_view` raised `TypeError` every
            # time and the except below turned it into
            # `renderer="unavailable: ..."` -- a reported state, so nothing
            # crashed and nothing rendered, on every run for the life of the
            # module. `preview.DEFAULT_VIEW_SIZE` documents itself as the
            # width/height of each sub-view, which is what this module's
            # `MAX_RESOLUTION_PX` budget is for, so the two line up by meaning
            # and not merely by type-checking.
            preview.render_multi_view(ctx.normalized, str(multi), view_size=MAX_RESOLUTION_PX)
            images.append(str(multi.name))
            section = out_dir / "section_x.png"
            section_render(str(ctx.path), str(section))
            images.append(str(section.name))
        except Exception as exc:            # noqa: BLE001 - a missing renderer is a
            renderer = f"unavailable: {exc}"  # reportable state, not a crash

    seconds = time.perf_counter() - started
    witness = Witness(level=level, images=tuple(images), sections=sections,
                      seconds=seconds, renderer=renderer)

    if seconds > MAX_SECONDS:
        raise BudgetExceeded(
            f"{level}: generation took {seconds:.2f}s against a {MAX_SECONDS}s budget. "
            "A witness level that quietly slows is how a route's cost doubles without "
            "any single change looking wrong.")
    return witness
