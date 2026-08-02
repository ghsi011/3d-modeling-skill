"""team_tools -- deterministic contract-automation package for the 3D team pipeline.

Depends only on the Python standard library, the already-installed ``trimesh``
and ``numpy`` (used for artifact mesh checks), and one stdlib-only module of the
``pipeline`` package: ``pipeline.findings``, which owns the ``Issue`` type both
packages report through. The dependency points that way and never back --
``team_tools`` is the older layer and ``pipeline`` is the one being built.

This package does not modify, and never imports, ``team_preflight.py`` -- it is a
separate, additive layer that operates on the structured-JSON contract
representation of the team contracts (added in Sprint 1A; see CHANGELOG.md).

Deliberately empty of re-exports: the canonical values live in ``common.py`` and
are imported package-relatively in the installed wheel. A compatibility fallback
keeps the source-checkout CLI and tests working when invoked as
``uv run --project <skill> --frozen python -m team_tools.contracts ...`` or the shorthand ``uv run --project <skill> --frozen python <skill>/scripts/dt.py validate|status <path>`` --
see the sys.path bootstrap at the top of contracts.py / test_contracts.py for
why. External callers import the submodule they need
(``from team_tools.status import compute_status``); an ``__init__`` re-export
would run that bare-import machinery a second time for no consumer.
"""
