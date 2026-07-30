#!/usr/bin/env python3
"""Build an authored model, and say which kernel actually did it.

The certified backends know their kernel because they *are* the kernel. An
authored model calls whichever one it wants, so this backend detects what came
back and records it rather than asserting it. A receipt that names the wrong
engine is worse than one that names none.

The model module is never rewritten. The certified backends drop a `model.py`
beside the STL as a record of what was built; doing that here would overwrite
the authored source with a summary of itself.
"""
from __future__ import annotations

import time
from pathlib import Path

from . import BuildArtifacts

NAME = "authored"


def _export(part, stl_path: Path, step_path: Path | None) -> tuple[str, str, dict]:
    """Export whatever the model returned, naming the kernel that produced it."""
    # A trimesh mesh, or something that quacks like one.
    if hasattr(part, "export") and hasattr(part, "faces"):
        import trimesh
        part.export(stl_path)
        tessellation = {"kernel": "trimesh",
                        "faces": int(len(part.faces)),
                        "note": "the model returned a mesh; nothing was tessellated here"}
        return "trimesh", f"trimesh {trimesh.__version__}", tessellation

    # A build123d / OCCT solid.
    from build123d import export_step, export_stl  # noqa: PLC0415 - kernel is lazy
    import build123d

    shape = getattr(part, "part", part)
    export_stl(shape, str(stl_path))
    if step_path is not None:
        export_step(shape, str(step_path))
    tessellation = {"kernel": "build123d",
                    "note": "exported through build123d's own tessellator"}
    return "build123d", f"build123d {build123d.__version__}", tessellation


class AuthoredBackend:
    name = NAME

    def __init__(self, builder=None) -> None:
        # Injected by the runner, which has already loaded and validated the
        # module to write the contract. Loading it a second time here would mean
        # the thing that was checked and the thing that was built are two
        # separate imports of a file that could have changed between them.
        self._builder = builder

    def build(self, contract, output_dir: Path) -> BuildArtifacts:
        if self._builder is None:
            raise ValueError(
                "the authored backend must be handed the builder the contract was "
                "written from; re-loading the module here would build something "
                "other than what was checked")
        started = time.perf_counter()
        output_dir.mkdir(parents=True, exist_ok=True)

        part = self._builder() if callable(self._builder) else self._builder
        stl_path = output_dir / "candidate.stl"
        step_path = output_dir / "candidate.step" if contract.step_required else None
        kernel, version, tessellation = _export(part, stl_path, step_path)

        source = contract.source or {}
        source_path = output_dir / str(source.get("module") or "model.py")
        if not source_path.is_file():
            raise ValueError(
                f"{source_path.name} is the contract's declared source and is not on "
                "disk; the artifact manifest would bind to a file that does not exist")

        return BuildArtifacts(
            stl_path=stl_path,
            step_path=step_path,
            source_path=source_path,
            backend=self.name,
            backend_version=version,
            tessellation=tessellation,
            boolean_ops=(),
            # Not "manifold3d". The certified backends select the engine at every
            # call site and can therefore name it; an authored model was not asked
            # to declare its booleans, and asserting an engine nobody observed is
            # the kind of receipt this pipeline exists to not write.
            boolean_engine=("n/a (B-rep)" if kernel == "build123d" else
                            "unrecorded: an authored mesh model selects its own "
                            "engine and this build did not observe the call"),
            build_seconds=time.perf_counter() - started,
        )
