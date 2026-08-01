#!/usr/bin/env python3
"""The `CUSTOM` lane's source API: a model module the pipeline can build.

**Where this runs.** In the child process, and only there. `load` calls
`spec.loader.exec_module`, which runs the designer's module-level code; the
parent -- which freezes the acceptance contract, commissions the artifact and
decides the final status -- never imports this module.
`pipeline/build_child.py` is its only caller and is itself reached through
`sys.executable`, so there is no ordering of the parent's code that executes a
model file. Freezing the contract first was necessary and was not sufficient: an
import *is* an execution, and `status.decide`, `commission._tol`,
`contract.area_tolerance` and `AcceptanceSource.expectations` were all one
assignment away from the first line of `model.py`.

A model module declares the numbers its shape is built from, and returns the
solid:

    PARAMS = {...}                      # the numbers the shape is built from
    def build(): ...                    # or a module-level `part`

and optionally `COMPONENTS`, `INTERFACES` and `PROVENANCE`.

**Where `PROVENANCE` goes**, since D10: into `candidate_declaration.json`, which
the parent writes and nothing reads. It used to be copied onto the model
contract, which is handed verbatim to the safety reviewer and the verification
reviewer -- so a designer could address the party whose PASS decides the run, and
a designer who had also read the frozen contract could do it in the gate's own
vocabulary. It is still recorded, because a declaration nothing keeps is a
declaration nobody should write. It is no longer forwarded.

**What is deliberately not here.** `EXPECTED`, `BBOX_MM`, `BODIES`,
`VOLUME_MM3`, `PROFILE_MARKS` and any acceptance tolerance used to be read out of
this file on every run, and the contract was overwritten with what was found. A
designer could read a failure, widen the expectation and be commissioned on the
next run with nothing recording that the expectation had moved -- a model
declaring a 24x18 pad, building a 10x8 one, with a self-declared 500 mm2 band,
was commissioned `PASS` on a 352 mm2 miss. Those declarations now live in
`design_proposal.json`, which `acceptance.py` freezes into
`acceptance_contract.json` before this module is executed at all.

The separation is structural rather than checked: `AuthoredModel` has no
`expectations`, no `bbox` and no `bodies`, so the object the builder came out of
cannot be handed to the function that writes the contract. A module that still
carries the old names is refused as well, but only so that a designer who has
not read this docstring is told where the declarations went -- the refusal is not
what makes the property hold.

What is also deliberately not here: a validity domain. An authored model is not
certified and never routes `DIRECT`, so there is no bound to check a parameter
against and pretending otherwise would sell an assurance nobody produced.
"""
from __future__ import annotations

import dataclasses
import importlib.util
import sys
from pathlib import Path
from typing import Any

from . import schemas as S

# Every declaration a model must carry before anything is built from it.
REQUIRED = ("PARAMS",)

# Declarations a model may no longer carry, and where each one went. Refused
# rather than ignored: a designer who edits a number that nothing reads is
# iterating against a file the gate does not consult, which is a worse failure
# than being told to move it.
RELOCATED = {
    "EXPECTED": "features",
    "BBOX_MM": "bbox_mm",
    "BODIES": "bodies",
    "PROFILE_MARKS": "profile_marks",
    "VOLUME_MM3": None,
    "TOLERANCE": None,
}


class ModelError(S.SchemaError):
    """The model module does not declare what the pipeline has to be given."""


@dataclasses.dataclass(frozen=True)
class AuthoredModel:
    """A loaded model module, reduced to who built the geometry.

    Identity and provenance, and nothing the gate reads. Every acceptance field
    this dataclass used to carry is now on the frozen acceptance contract, and
    the absence of the fields -- not a validator in front of them -- is what makes
    the built artifact unable to influence what it is judged against.
    """

    name: str
    module_path: Path
    module_sha256: str
    params: dict[str, Any]
    components: tuple[dict[str, Any], ...] = ()
    interfaces: tuple[dict[str, Any], ...] = ()
    provenance: dict[str, Any] = dataclasses.field(default_factory=dict)


def _finite(value: Any, what: str) -> float:
    """A finite number, or a `ModelError` naming the declaration.

    Re-raised rather than passed through: `require_finite_number` raises the
    generic schema error, and a caller catching `ModelError` to report "this
    model cannot be commissioned" would let a NaN escape as something else.
    """
    try:
        return S.require_finite_number(value, what=what)
    except S.SchemaError as exc:
        raise ModelError(str(exc)) from None


def load(module_path: Path) -> tuple[AuthoredModel, Any]:
    """Import a model module and return its identity and its builder.

    Executes the designer's code. Call it from the child process and from nowhere
    else: what it returns crosses back to the parent as JSON, and what the import
    did to *this* interpreter dies with the process.

    Returns identity separately from anything the contract is written out of,
    which is the other half of the arrangement: the acceptance contract is frozen
    from `design_proposal.json` before this runs, and nothing this function
    returns can reach it.
    """
    module_path = Path(module_path)
    if not module_path.is_file():
        raise ModelError(f"no such model module: {module_path}")

    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    if spec is None or spec.loader is None:
        raise ModelError(f"cannot import {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:                          # noqa: BLE001 - a model that
        raise ModelError(                             # cannot import is a finding
            f"{module_path.name} raised on import: {type(exc).__name__}: {exc}") from exc

    missing = [name for name in REQUIRED if not hasattr(module, name)]
    if missing:
        raise ModelError(
            f"{module_path.name} does not declare {', '.join(missing)}. A model the "
            "pipeline can build declares PARAMS and returns the solid; what it must "
            "measure is declared in design_proposal.json and frozen into "
            "acceptance_contract.json before this file is executed.")

    relocated = [name for name in RELOCATED if hasattr(module, name)]
    if relocated:
        where = ", ".join(
            f"{name} -> design_proposal.json.{RELOCATED[name]}"
            if RELOCATED[name] else
            f"{name} -> nowhere; it is not an acceptance input on this lane"
            for name in sorted(relocated))
        raise ModelError(
            f"{module_path.name} declares {', '.join(sorted(relocated))}, which the "
            f"model may not own. {where}. Acceptance criteria are frozen from the "
            "proposal before this file runs, so a number here would be read by "
            "nothing -- and when it was read, a model declaring a 24x18 pad and "
            "building a 10x8 one was commissioned PASS on a 352 mm2 miss.")

    builder = getattr(module, "part", None)
    if builder is None:
        builder = getattr(module, "build", None)
    if builder is None:
        raise ModelError(f"{module_path.name} must define `part` or `build()`")

    params = getattr(module, "PARAMS")
    if not isinstance(params, dict):
        raise ModelError(f"{module_path.name}: PARAMS must be an object")
    for key, value in params.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            _finite(value, f"PARAMS.{key}")

    return AuthoredModel(
        name=module_path.stem,
        module_path=module_path,
        module_sha256=S.sha256_file(module_path),
        params=dict(params),
        components=tuple(getattr(module, "COMPONENTS", ()) or ()),
        interfaces=tuple(getattr(module, "INTERFACES", ()) or ()),
        provenance=dict(getattr(module, "PROVENANCE", {}) or {}),
    ), builder
