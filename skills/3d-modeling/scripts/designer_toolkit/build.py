#!/usr/bin/env python3
"""Write the model file for a template-covered part.

The catalogue could be printed but not instantiated: an agent that had already
chosen `c_clip` and knew every parameter still had to hand-write the six-line
module that calls it. Under `DIRECT` that meant the orchestrator picked the
template and then paid a four-to-six minute dispatch for someone to type its
arguments in.

The output is still a real `model.py` -- generated, not hidden. Editable source
is a requirement of the role, and a part that later needs a feature no template
offers should start from the file rather than from nothing.

    python <skill>/scripts/dt.py build --template c_clip \
        --param bore_d=12.0 --param wall=3.0 --param height=9.0 \
        --param mouth_gap=9.0 --param 'flange=(40.0, 22.0, 5.0)' \
        --param screw_d=4.5 --param 'screw_at=(8.0, 11.0)' \
        --param countersink_d=9.0 --out model.py
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Any

from .templates import CATALOGUE


def parse_param(text: str) -> tuple[str, Any]:
    """`name=value`, where value is any Python literal.

    Literals rather than floats-only because the useful templates take tuples --
    `flange=(40, 22, 5)`, `inner=(120, 80, 60)`. `literal_eval` accepts those and
    refuses anything executable.
    """
    if "=" not in text:
        raise ValueError(f"expected name=value, got {text!r}")
    name, _, raw = text.partition("=")
    name = name.strip()
    if not name.isidentifier():
        raise ValueError(f"{name!r} is not a parameter name")
    try:
        return name, ast.literal_eval(raw.strip())
    except (ValueError, SyntaxError) as exc:
        raise ValueError(f"{name}: {raw.strip()!r} is not a literal ({exc})") from exc


def render_model(template: str, params: dict[str, Any], *, title: str | None = None) -> str:
    """The module a designer would have typed, with the arguments filled in."""
    if template not in CATALOGUE:
        raise ValueError(f"no template named {template!r}; have "
                         f"{', '.join(sorted(CATALOGUE))}")
    arguments = ",\n    ".join(f"{k}={v!r}" for k, v in sorted(params.items()))
    heading = title or f"{template} candidate, parameters from dimensions.md."
    return (
        f'"""{heading}"""\n'
        f"from designer_toolkit.templates import {template}\n"
        "\n"
        f"_built = {template}(\n"
        f"    {arguments},\n"
        ")\n"
        "\n"
        "# The template computes these from the same arithmetic that built the\n"
        "# solid, so they cannot drift from the geometry they describe.\n"
        "PARAMS = _built.params\n"
        "part = _built.part\n"
        "\n"
        "# What the solid must measure, derived from the parameters above rather\n"
        "# than from the geometry. Do not edit these to make a failing check pass:\n"
        "# the number is worth something only because nothing measured the part to\n"
        "# arrive at it.\n"
        "EXPECTED = _built.expected\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", required=True,
                        help=f"one of: {', '.join(sorted(CATALOGUE))}")
    parser.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                        help="repeatable; VALUE is any Python literal, including tuples")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--title", help="the module docstring")
    args = parser.parse_args(argv)

    try:
        params = dict(parse_param(text) for text in args.param)
        source = render_model(args.template, params, title=args.title)
    except ValueError as exc:
        sys.stderr.write(f"build: {exc}\n")
        return 2

    # Build it once here so a bad parameter set fails now, with the template's
    # own error, rather than inside the gate one command later.
    namespace: dict[str, Any] = {}
    try:
        exec(compile(source, str(args.out), "exec"), namespace)  # noqa: S102
    except Exception as exc:  # noqa: BLE001 - any template error belongs to the caller
        sys.stderr.write(f"build: {args.template} rejected these parameters: {exc}\n")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(source, encoding="utf-8")
    built = namespace["PARAMS"]
    sys.stdout.write(f"{args.out}\n")
    sys.stdout.write(f"  overall_mm {built.get('overall_mm')}\n")
    if "wall_mm" in built:
        sys.stdout.write(f"  wall_mm    {built['wall_mm']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
