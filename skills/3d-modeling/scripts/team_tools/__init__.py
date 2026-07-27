"""team_tools -- deterministic contract-automation package for the 3D team pipeline.

Net-new, self-contained package. Depends only on the Python standard library plus
the already-installed ``trimesh`` and ``numpy`` (used for artifact mesh checks).

This package does not modify, and never imports, ``team_preflight.py`` -- it is a
separate, additive layer that operates on the structured-JSON contract
representation of the team contracts (added in Sprint 1A; see CHANGELOG.md).

Deliberately empty of re-exports: the canonical values live in ``common.py`` and
are imported bare (without a ``team_tools.`` prefix) everywhere inside the
package, so the CLI and tests work whether invoked as
``uv run --project <skill> --frozen python -m team_tools.contracts ...`` or the shorthand ``uv run --project <skill> --frozen python <skill>/scripts/dt.py validate|status <path>`` --
see the sys.path bootstrap at the top of contracts.py / test_contracts.py for
why. External callers import the submodule they need
(``from team_tools.status import compute_status``); an ``__init__`` re-export
would run that bare-import machinery a second time for no consumer.
"""
