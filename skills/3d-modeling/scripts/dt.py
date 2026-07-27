#!/usr/bin/env python3
"""Run the toolkit from wherever the job is.

`uv run --project <skill> --frozen python -m designer_toolkit ...` resolves from the repo root; from an
installed skill use `uv run --project <skill> --frozen python <skill>/scripts/dt.py ...` which patches
sys.path automatically. A commission's files live in its own project directory,
so invoke this file by absolute path from the job folder, and paths on the
command line resolve against the job folder because that is still the working
directory.

    uv run --project <skill> --frozen python <skill>/scripts/dt.py commission --model model.py \
        --plan print_plan_checks.json --out . --job-id <job> --updated-utc <iso8601>
    uv run --project <skill> --frozen python <skill>/scripts/dt.py doctor

`doctor` prints this file's own path, so the command to use is never something
the agent has to reconstruct.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from designer_toolkit.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
