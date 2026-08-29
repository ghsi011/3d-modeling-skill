#!/usr/bin/env python3
"""OS-enforced confinement for the build boundary: the interface, and the choice.

`isolation.py` decides *what* crosses the boundary. This package is *how the
boundary is enforced*, and it enforces it with the operating system rather than
with the Python interpreter. There are two implementations and they are peers:
`windows.py` builds the boundary from a restricted token, a low integrity level
and a job object; `posix.py` builds it from mount, network and PID namespaces
plus a seccomp filter. Neither imports the other and neither knows the other
exists. This module is the only place that knows both.

**The interface, which is the whole of what a caller may use.** Nine names, and
what each one owes on any platform that has an adapter at all:

* `unavailable_reason()` -- why a candidate may not be executed here, or `None`.
  Called before the parent has committed to anything. A boundary that cannot be
  established is a refusal and never a downgrade.
* `available()` -- `unavailable_reason() is None`.
* `seal_read_only(path)` -- the candidate's inputs, after staging: readable by
  the candidate, writable by nobody. The parent keeps ownership so it can
  clean up.
* `seal_writable(path)` -- the one directory the candidate may write.
* `unseal(path)` -- give the parent write access back, so the sandbox can be
  deleted.
* `is_reparse_point(path)` -- whether a path is an instruction to read somewhere
  else rather than a file. `isolation.py` refuses those, because the somewhere
  else was never staged.
* `data_streams(path)` -- bytes attached to a file that reading the file does
  not reveal. A build output has no business carrying any.
* `run(argv, *, cwd, env, timeout) -> Confined` -- run `argv` confined, and
  return only once nothing anywhere can still be writing into `cwd`. Raises
  `ConfinementUnavailable` rather than degrading to an ordinary subprocess.
* `seal_syscalls()` -- refuse process creation for the rest of *this* process's
  life, where that is a separate act from building the boundary. Called by
  `build_child.py` immediately before the first candidate import, so that the
  child has one thing to call and neither platform's child carries a branch
  about which boundary it is inside. On Windows the boundary is already set on
  the process before it starts, so there it is a no-op.

The two adapters keep those nine with primitives that share nothing, and each
one's own module docstring is where its mechanisms are written down and
measured.
"""
from __future__ import annotations

import dataclasses
import os

# Raised by the Windows adapter's `run` before `CreateProcessAsUserW`, which
# raises no audit event of its own. The POSIX adapter does not raise it: its
# `os.fork` and `os.execve` are audited by the interpreter already. `DIRECT`
# creating zero processes is a release gate, and
# `test_isolation.DirectIsExemptTest` watches this name beside those.
AUDIT_SPAWN = "pipeline.confine.spawn"


class ConfinementUnavailable(RuntimeError):
    """The confinement cannot be built here, so no candidate may be run here.

    Raised rather than degraded. A boundary that silently becomes an ordinary
    subprocess on a platform it was not written for is worse than no boundary,
    because the receipts do not say which one ran.
    """


@dataclasses.dataclass(frozen=True)
class Confined:
    """What the parent knows after the confinement is dead."""

    returncode: int | None      # None when the child was killed rather than exited
    output: str                 # the child's merged stdout/stderr, untrusted text
    timed_out: bool
    seconds: float
    pid: int                    # the direct child, so `survivors` can exclude it
    # Processes still alive inside the confinement when the direct child exited.
    # Zero on an honest build; anything else is a candidate that tried to outlive
    # its own run, and the number is a finding worth writing down.
    survivors: int


def adapter_name(os_name: str = os.name) -> str:
    """Which adapter implements the boundary on `os_name`.

    The whole of the platform decision, as a function of a string rather than of
    the machine it is running on -- so that what it answers for *both* platforms
    can be asserted from either one, without patching a flag anything else reads.
    """
    return "windows" if os_name == "nt" else "posix"


# Spelled as a branch rather than as an `importlib.import_module` of the name
# above, so that a static reader sees both adapters: `test_isolation`'s import
# graph walks this package to decide what the process that owns acceptance is
# allowed to reach, and a module reached only through a computed string is a
# module that guard cannot see.
if adapter_name() == "windows":                   # pragma: no branch - platform
    from . import windows as _impl
else:                                             # pragma: no cover - platform
    from . import posix as _impl

# The interface, bound to the selected implementation. `test_isolation`'s
# selection test asserts that every one of these came from the adapter
# `adapter_name()` names.
unavailable_reason = _impl.unavailable_reason
available = _impl.available
seal_read_only = _impl.seal_read_only
seal_writable = _impl.seal_writable
unseal = _impl.unseal
is_reparse_point = _impl.is_reparse_point
data_streams = _impl.data_streams
run = _impl.run
seal_syscalls = _impl.seal_syscalls
