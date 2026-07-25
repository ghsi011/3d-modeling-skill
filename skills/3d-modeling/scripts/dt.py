#!/usr/bin/env python3
"""Run the toolkit from wherever the job is.

`python -m designer_toolkit ...` only resolves when the interpreter's working
directory is this `scripts/` folder, but a commission's files live in its own
project directory. Every measured designer run resolved that by hand, and each
time the same way: a `verify.py` shim dropped into the job folder that hardcodes
this directory's absolute path, patches `sys.path`, and calls `commission.run`
itself. Those shims added no checks -- one was, in full, a re-implementation of
the CLI's own argument handling -- and writing one cost turns on every job.

So: invoke this file by absolute path from the job folder, and paths on the
command line resolve against the job folder because that is still the working
directory.

    python <skill>/scripts/dt.py commission --model model.py \
        --plan print_plan_checks.json --out . --job-id <job> --updated-utc <iso>
    python <skill>/scripts/dt.py doctor

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
