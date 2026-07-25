#!/usr/bin/env python3
"""What this interpreter can actually do, in one call.

An archived run spent turns discovering by trial which of several interpreters
had a CAD kernel, and another skipped a datum check after learning mid-run that
its environment lacked the `section` extra. Both are one import away from being
answerable before any work starts, and a capability discovered by failure costs
a round trip every time.

Reports rather than raises: a missing optional extra is a fact about the
environment, and the caller decides whether it matters for this commission.

    python -m designer_toolkit doctor
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys

# module -> (what it unlocks, what stops working without it)
_CAPABILITIES: dict[str, tuple[str, str]] = {
    "trimesh": ("mesh measurement, booleans, export", "nothing runs"),
    "manifold3d": ("robust booleans", "boolean results become unreliable"),
    "numpy": ("every measurement", "nothing runs"),
    "cadquery": ("the cadquery backend", "use build123d, or the trimesh templates"),
    "build123d": ("the build123d backend", "use cadquery, or the trimesh templates"),
    "scipy": ("cross-sections", "edge measurement and datum features report SKIPPED"),
    "networkx": ("cross-sections", "edge measurement and datum features report SKIPPED"),
    "shapely": ("cross-sections", "edge measurement and datum features report SKIPPED"),
    "rtree": ("fast nearest-surface queries", "the fit check falls back to a slower exact path"),
    "pyrender": ("rendering", "the section render reports SKIPPED and nothing can be looked at"),
    "PIL": ("evidence photo preparation", "crop_evidence cannot run"),
}

# A commission needs these; everything else changes what it can report, not
# whether it can run at all.
_REQUIRED = ("numpy", "trimesh", "manifold3d")


def _present(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def report() -> dict:
    found = {name: _present(name) for name in _CAPABILITIES}
    missing_required = [n for n in _REQUIRED if not found[n]]
    backends = [n for n in ("cadquery", "build123d") if found[n]]
    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        # The exact command to use, so it is never something to reconstruct.
        "launcher": str(pathlib.Path(__file__).resolve().parent.parent / "dt.py"),
        "can_run_commission": not missing_required,
        "missing_required": missing_required,
        "cad_backends": backends,
        "capabilities": {
            name: {
                "present": present,
                "enables": _CAPABILITIES[name][0],
                "without_it": _CAPABILITIES[name][1],
            }
            for name, present in found.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    data = report()
    if args.json:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
    else:
        sys.stdout.write(f"python {data['python']}\n{data['executable']}\n")
        sys.stdout.write(f"run the toolkit as: python {data['launcher']} <command>\n\n")
        for name, entry in data["capabilities"].items():
            mark = "yes" if entry["present"] else "NO "
            sys.stdout.write(f"  [{mark}] {name:<12} {entry['enables']}\n")
            if not entry["present"]:
                sys.stdout.write(f"       -> {entry['without_it']}\n")
        sys.stdout.write("\n")
        if data["missing_required"]:
            sys.stdout.write(
                f"commission CANNOT run here: missing {', '.join(data['missing_required'])}\n")
        elif not data["cad_backends"]:
            sys.stdout.write("commission can run, but no CAD kernel is installed -- build "
                             "with designer_toolkit.templates or install the `cad` extra.\n")
        else:
            sys.stdout.write(f"commission can run; CAD backends: "
                             f"{', '.join(data['cad_backends'])}\n")
    return 0 if data["can_run_commission"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
