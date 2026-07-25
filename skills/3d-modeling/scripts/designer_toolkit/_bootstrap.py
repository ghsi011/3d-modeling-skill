"""Side-effect import: put the ``scripts/`` dir (this package's parent) on
``sys.path`` so ``designer_toolkit`` modules can ``import mesh_io`` /
``from preview import ...`` whether they are run as ``python -m
designer_toolkit.x``, imported by the test bootstrap, or vendored into the
standalone skill repo. Import this first, before any sibling-script import.
"""

import os
import sys

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)
