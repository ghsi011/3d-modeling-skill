"""Side-effect import: put the ``scripts/`` dir (this package's parent) on
``sys.path`` so ``designer_toolkit`` modules can ``import mesh_io`` /
``from preview import ...`` whether they are run as ``uv run --project <skill> --frozen python -m
designer_toolkit.x``, imported by the test bootstrap, or vendored into the
standalone skill repo. Import this first, before any sibling-script import.
"""

import os
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import mesh_io  # noqa: E402  (needs the sys.path insert above)


def as_mesh(mesh_or_path: Any):
    """Coerce a path-or-mesh argument to a ``trimesh.Trimesh``.

    Every toolkit entry point takes either, and all of them want the
    merged/repaired load: a raw STL parse is an unwelded vertex soup that
    booleans unreliably, renders with faceted seams, and reads as non-watertight.
    Lives here (rather than in one of the callers) so fit/metrics/render cannot
    drift apart on which side of that choice they take.
    """
    if isinstance(mesh_or_path, (str, Path)):
        return mesh_io.load_mesh(mesh_or_path)
    return mesh_or_path
