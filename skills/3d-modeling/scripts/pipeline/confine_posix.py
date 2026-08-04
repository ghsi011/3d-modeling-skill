#!/usr/bin/env python3
"""OS-enforced confinement for the build boundary. Linux primitives only.

`isolation.py` decides *what* crosses the boundary. `confine.py` decides which
implementation enforces it. This module is the Linux one, and it enforces the
boundary with the kernel rather than with the Python interpreter -- the same rule
`confine.py` states for Windows, kept with different primitives.

**The four properties, and what enforces each here.** Every row is re-measured
by `benchmarks/heavy/test_confine_posix_heavy.py`, which runs a real confined
child and has it try the thing, rather than trusting this comment. That file
exists because of `docs/defects.md` D11: a boundary whose documentation outran
its measurement claimed the network was closed when it was open.

1. **The filesystem is read-only except for one directory.** A mount namespace,
   detached from the host's propagation (`MS_REC|MS_PRIVATE`), then
   `mount_setattr(AT_RECURSIVE, MOUNT_ATTR_RDONLY)` over `/`. That is an
   allow-list of exactly one hole: the build directory is bind-mounted back
   read-write afterwards. Measured: writes to the repository, to
   `site-packages`, to `/tmp` and to `/etc` all fail `EROFS`, and the failure is
   the filesystem's, not a check this code performs.

   This is deliberately *not* a uid question. `EROFS` is returned before any
   permission check, so it holds no matter who the candidate manages to become.

2. **The network is closed.** A network namespace with no interfaces configured
   -- not even loopback is brought up. Measured: `connect()` to a routable
   address fails `ENETUNREACH` and DNS fails to resolve.

   Worth naming because the Windows boundary cannot say this. `docs/defects.md`
   D11 records that a restricted token does not refuse `socket.connect`, and
   that the original claim it did rested on a probe against a port a local
   filter happened to block. Here the network is genuinely absent.

3. **Lifetime is bounded, and nothing can break out of it.** A PID namespace
   whose init process is this module's supervisor. When init exits the kernel
   `SIGKILL`s every remaining process in the namespace -- there is no equivalent
   of `CREATE_BREAKAWAY_FROM_JOB` to attempt, because the namespace is a property
   of the process tree rather than a handle a process holds. Measured: a
   grandchild that calls `setsid()` and sleeps is dead before the parent reads a
   single output byte.

   The supervisor counts what is still alive *before* it exits, so `survivors`
   means the same thing it means on Windows: a candidate that tried to outlive
   its own run, reported as a finding rather than silently reaped.

4. **No child processes.** A seccomp-BPF filter returning `EPERM` for `execve`
   and `execveat`, installed with `PR_SET_NO_NEW_PRIVS` so it cannot be dropped.

   Unlike the other three this one cannot be installed by the parent, because
   the parent's last act is itself an `execve`. It is installed by
   `build_child.py` immediately before the first candidate byte is imported, and
   `seal_syscalls` is that entry point. A filter is irrevocable once set, so the
   candidate cannot lift it; what it does mean is that this property begins one
   function call later than the other three, and the honest statement is that it
   covers candidate code rather than the whole child process.

**Authority is dropped, and identity is kept.** After the mounts are made --
which needs `CAP_SYS_ADMIN` -- the candidate clears its entire capability
bounding set, then its effective, permitted and inheritable sets, and sets
`SECBIT_NOROOT` and `PR_SET_NO_NEW_PRIVS`. Measured: `CapEff` is
`0000000000000000` and `mount(MS_REMOUNT)` over `/` answers `EPERM`.

The first version of this dropped to `nobody` instead, and that was wrong for a
reason worth keeping. A `MODIFY` job's model legitimately reads the supplied
artifact out of the project directory, which the parent owns; becoming a
different user does not confine that read -- the read-only mount already did --
it only breaks it, and the breakage surfaces as `trimesh` reporting the source
file does not exist, which reads like a broken fixture rather than like a
boundary that took away something the job needs. Keeping the identity is also
the shape the Windows implementation has, where the child runs as the same user
under a restricted token.

What the empty capability set buys is the one thing a root candidate could
otherwise do: without `CAP_SYS_ADMIN` it cannot call `mount`, so it cannot
remount its own namespace read-write and undo property 1 from the inside.
Without `CAP_DAC_OVERRIDE` it is subject to ordinary permission bits like anyone
else. A capability cleared from the bounding set cannot be reacquired by any
means.

The remaining route back to `CAP_SYS_ADMIN` is a *new user namespace*, which
grants a full capability set inside itself and needs no capability to create.
The kernel's answer is that mounts inherited from an ancestor namespace are
locked against attribute changes, so the capability is real and there is nothing
in reach to use it on. That is measured too, rather than trusted: the boundary
test creates one, records the capability set inside it, and asserts that the
remount is still `EPERM` and the repository is still `EROFS`.

**Refused rather than degraded.** `unavailable_reason` probes every mechanism
this module needs and names the first one missing. A boundary that quietly
becomes an ordinary subprocess is worse than no boundary, because the receipts do
not say which one ran. Landlock, for instance, is absent on some kernels that
have everything else; this module does not use it, and if it did, its absence
would have to refuse rather than skip.
"""
from __future__ import annotations

import ctypes
import dataclasses
import errno
import os
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - the runtime import is inside `run`
    # Imported inside `run` at runtime, because importing the Windows module at
    # module scope would make this file's importability depend on it. The
    # annotation still has to resolve for a checker, and an unresolvable one is
    # a name a reader cannot follow.
    from .confine import Confined

LINUX = sys.platform.startswith("linux")

# Long enough for a transient the kernel is already tearing down, short enough
# that a real survivor is still alive to be counted. The Windows boundary needs
# the same grace for `conhost.exe`; here it is for the reaping of a process that
# has already been killed.
SURVIVOR_GRACE_S = 0.25

_libc = ctypes.CDLL("libc.so.6", use_errno=True) if LINUX else None

# ---------------------------------------------------------------------------
# Kernel constants. Declared here rather than pulled from a package for the
# reason `confine.py` gives for its ctypes bindings: adding a dependency to a
# security boundary to save fifty lines of declarations is the wrong trade, and
# this way the boundary's whole surface is visible in one file.
# ---------------------------------------------------------------------------
CLONE_NEWNS = 0x00020000
CLONE_NEWPID = 0x20000000
CLONE_NEWNET = 0x40000000
CLONE_NEWIPC = 0x08000000
CLONE_NEWUTS = 0x04000000
CONFINED_NAMESPACES = (CLONE_NEWNS | CLONE_NEWPID | CLONE_NEWNET
                       | CLONE_NEWIPC | CLONE_NEWUTS)

MS_RDONLY = 0x1
MS_NOSUID = 0x2
MS_NODEV = 0x4
MS_NOEXEC = 0x8
MS_BIND = 0x1000
MS_REC = 0x4000
MS_PRIVATE = 0x40000

# mount_setattr(2), x86_64. The modern way to set mount attributes recursively:
# `MS_REMOUNT` through mount(2) does not recurse, so a read-only remount of `/`
# would leave every submount writable -- including the one the repository is on.
NR_mount_setattr = 442
NR_seccomp = 317
AT_FDCWD = -100
AT_RECURSIVE = 0x8000
MOUNT_ATTR_RDONLY = 0x00000001

PR_SET_NO_NEW_PRIVS = 38
PR_SET_PDEATHSIG = 1
PR_CAPBSET_DROP = 24
PR_SET_SECUREBITS = 28
SECBIT_NOROOT = 1 << 0
SECBIT_NOROOT_LOCKED = 1 << 1

_LINUX_CAPABILITY_VERSION_3 = 0x20080522
# A ceiling rather than a count. `prctl(PR_CAPBSET_DROP)` answers EINVAL for a
# capability the running kernel does not define, which the loop treats as the
# end rather than as a failure -- so this only has to be at least as large as
# the kernel's own last capability, and never has to match it.
_CAP_LAST_CAP = 63

SECCOMP_SET_MODE_FILTER = 1
SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_ERRNO = 0x00050000
SECCOMP_RET_ALLOW = 0x7FFF0000
AUDIT_ARCH_X86_64 = 0xC000003E
AUDIT_ARCH_AARCH64 = 0xC00000B7

BPF_LD, BPF_W, BPF_ABS = 0x00, 0x00, 0x20
BPF_JMP, BPF_JEQ, BPF_K, BPF_RET = 0x05, 0x10, 0x00, 0x06
BPF_JGE = 0x30

# `__X32_SYSCALL_BIT`. An x32 call is x86-64 by arch token and carries this bit
# in its number, which is why the arch check alone does not see it.
_X32_SYSCALL_BIT = 0x40000000

# The syscalls a build has no business making. Per architecture, because the
# numbers differ and a filter written for the wrong one either blocks nothing or
# blocks something else entirely.
_EXEC_SYSCALLS = {
    AUDIT_ARCH_X86_64: (59, 322),        # execve, execveat
    AUDIT_ARCH_AARCH64: (221, 281),      # execve, execveat
}

_ARCH = {"x86_64": AUDIT_ARCH_X86_64, "aarch64": AUDIT_ARCH_AARCH64}.get(
    os.uname().machine if LINUX else "")


class _CapHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _CapData(ctypes.Structure):
    _fields_ = [("effective", ctypes.c_uint32), ("permitted", ctypes.c_uint32),
                ("inheritable", ctypes.c_uint32)]


class _MountAttr(ctypes.Structure):
    _fields_ = [("attr_set", ctypes.c_uint64), ("attr_clr", ctypes.c_uint64),
                ("propagation", ctypes.c_uint64), ("userns_fd", ctypes.c_uint64)]


class _SockFilter(ctypes.Structure):
    _fields_ = [("code", ctypes.c_uint16), ("jt", ctypes.c_uint8),
                ("jf", ctypes.c_uint8), ("k", ctypes.c_uint32)]


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort),
                ("filter", ctypes.POINTER(_SockFilter))]


def _oserror(what: str) -> OSError:
    code = ctypes.get_errno()
    return OSError(code, f"{what}: {os.strerror(code)}")


# ---------------------------------------------------------------------------
# Is the boundary available here at all
# ---------------------------------------------------------------------------

def unavailable_reason() -> str | None:
    """Why a candidate may not be executed here, or None when it may.

    Every mechanism the boundary rests on is probed rather than assumed. The
    order is the order in which a missing one would be discovered anyway; what
    this buys is that it is discovered *before* a candidate is staged, and named.
    """
    if not LINUX:
        return (f"this module implements the boundary with Linux namespaces, "
                f"mount attributes and seccomp, and this is {sys.platform}")
    if _ARCH is None:
        return (f"no seccomp filter is defined for {os.uname().machine!r}, so "
                "the no-child-processes property cannot be enforced")
    if os.geteuid() != 0:
        # Unprivileged user namespaces would be the alternative and are not used
        # here: they are disabled on a good fraction of hardened kernels, and a
        # boundary with two construction paths has two things to keep measured.
        return ("building the confinement needs CAP_SYS_ADMIN to create a mount "
                f"namespace, and this process runs as uid {os.geteuid()}")
    for probe, what in ((NR_mount_setattr, "mount_setattr(2)"),
                        (NR_seccomp, "seccomp(2)")):
        if not _syscall_present(probe):
            return f"{what} is not available on this kernel"
    if not Path("/proc/self/ns/pid").exists():
        return "this kernel has no PID namespaces"
    return None


def _syscall_present(number: int) -> bool:
    """Whether a syscall exists, distinguished from failing on its arguments.

    Called with arguments chosen to be invalid, so the answer is `ENOSYS` (the
    kernel does not have it) against anything else (it does, and rejected the
    call). Probing by success would need the boundary to be half-built to find
    out whether it can be built.
    """
    _libc.syscall(number, ctypes.c_long(-1), None, ctypes.c_uint(0), None,
                  ctypes.c_size_t(0))
    return ctypes.get_errno() != errno.ENOSYS


def available() -> bool:
    return unavailable_reason() is None


def describe_confinement() -> dict[str, object]:
    """What this boundary is, for a receipt and for the tests that re-measure it."""
    return {
        "platform": sys.platform,
        "mechanism": "namespaces(mount,pid,net,ipc,uts) + "
                     "mount_setattr(rdonly,recursive) + empty capability set + "
                     "seccomp(no exec)",
        "arch": os.uname().machine if LINUX else None,
        "euid": os.geteuid() if LINUX else None,
        "network": "namespaced, no interfaces configured",
        "available": available(),
        "unavailable_reason": unavailable_reason(),
    }


# ---------------------------------------------------------------------------
# Sealing. On Windows this writes ACLs; here the mount namespace does the
# enforcing at run time, so these carry the *discretionary* half only.
# ---------------------------------------------------------------------------

def seal_read_only(path: Path) -> None:
    """The candidate's inputs, after they have been staged.

    Read and traverse for the candidate, write for nobody -- the same two
    sentences the Windows `D:P(A;;FA;;;SY)(A;OICI;FRFX;;;<restricted>)` says,
    in the vocabulary this platform has. The parent keeps ownership so it can
    restore write access to clean up.

    Discretionary, and the second mechanism rather than the first: the read-only
    mount is what actually refuses a write, with `EROFS`, before any permission
    check happens. This is what also holds outside the namespace, which is the
    case a mount attribute cannot speak about.

    The candidate keeps the parent's identity and holds no capability, so
    `CAP_DAC_OVERRIDE` is not there to step past these bits -- which is what
    makes clearing the write bit mean something to a uid-0 process.
    """
    for target in [Path(path), *Path(path).rglob("*")]:
        mode = target.stat().st_mode & 0o7777
        os.chmod(target, mode & ~0o222)


def seal_writable(path: Path) -> None:
    """The one directory the candidate may write, and the only one.

    Nothing to do to the directory itself: the candidate runs as the parent, so
    the parent's own ownership is what lets it write here, and the read-write
    bind mount in `_seal_filesystem` is what makes this the only place that is
    true of. Kept as a named call rather than deleted because the boundary's
    surface is the same on both platforms, and because *which* directory is the
    writable one is a decision worth having a place to state.

    The write bits are restored in case a previous `seal_read_only` cleared
    them, which happens when a build directory is reused.
    """
    for target in [Path(path), *Path(path).rglob("*")]:
        mode = target.stat().st_mode & 0o7777
        os.chmod(target, mode | 0o200)


def unseal(path: Path) -> None:
    """Give a sealed directory back, so the parent can clean it up."""
    target_root = Path(path)
    if not target_root.exists():
        return
    for target in [target_root, *target_root.rglob("*")]:
        try:
            os.chown(target, os.geteuid(), os.getegid())
            mode = target.stat().st_mode & 0o7777
            os.chmod(target, mode | 0o200)
        except OSError:                      # pragma: no cover - best effort
            pass


def is_reparse_point(path: Path) -> bool:
    """A symlink: the Linux member of the class NTFS reparse points belong to.

    `isolation.py` uses this to refuse an artifact that is a link rather than a
    file, because a link is an instruction to read somewhere else and the
    somewhere else was never staged.
    """
    return Path(path).is_symlink()


def data_streams(path: Path) -> list[str]:
    """Extended attributes: data attached to a file and not in its contents.

    The Windows implementation lists NTFS alternate data streams and excludes
    the unnamed one. There is no ADS here, and the honest analogue is xattrs --
    the way to hang bytes off a file that a reader of its contents will not see.
    An artifact carrying them is refused for the same reason.
    """
    try:
        return sorted(os.listxattr(str(path)))
    except (OSError, AttributeError):
        return []


# ---------------------------------------------------------------------------
# The syscall filter, installed by the child immediately before candidate code
# ---------------------------------------------------------------------------

def seal_syscalls() -> None:
    """Refuse `execve` for the rest of this process's life. Irrevocable.

    Called by `build_child.py` after its own imports have resolved and before
    the candidate's module is loaded, which is the last moment at which the
    boundary still controls what is running. `PR_SET_NO_NEW_PRIVS` is set first
    because seccomp requires it for an unprivileged caller and because it is
    what makes the filter survive anything the candidate does afterwards.

    A candidate cannot undo this. Filters compose by intersection: a process may
    add another, never remove one.
    """
    if not LINUX or _ARCH is None:            # pragma: no cover - platform
        return
    execve, execveat = _EXEC_SYSCALLS[_ARCH]
    program = [
        # 0: A = the architecture the call was made on. A filter that did not
        # check this could be stepped around on a multi-arch kernel by making
        # the same call under a different personality, where the numbers mean
        # other syscalls entirely.
        _SockFilter(BPF_LD | BPF_W | BPF_ABS, 0, 0, 4),
        # 1: equal -> 3, otherwise -> 2.
        _SockFilter(BPF_JMP | BPF_JEQ | BPF_K, 1, 0, _ARCH),
        _SockFilter(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_KILL_PROCESS),
        # 3: A = the syscall number.
        _SockFilter(BPF_LD | BPF_W | BPF_ABS, 0, 0, 0),
        # 4: the x32 ABI, and checking the arch token is not enough to catch it.
        # An x32 call carries the *same* `AUDIT_ARCH_X86_64` token with
        # `__X32_SYSCALL_BIT` OR'd into the number, so x32 `execve` arrives as
        # 0x4000003B -- not equal to 59 or 322, and the first version of this
        # filter fell straight through to ALLOW. Found by review. Nothing in
        # this build has any business issuing an x32 call, so the whole range is
        # killed rather than picked over. x32 -> 9.
        _SockFilter(BPF_JMP | BPF_JGE | BPF_K, 4, 0, _X32_SYSCALL_BIT),
        _SockFilter(BPF_JMP | BPF_JEQ | BPF_K, 2, 0, execve),      # 5 -> 8
        _SockFilter(BPF_JMP | BPF_JEQ | BPF_K, 1, 0, execveat),    # 6 -> 8
        _SockFilter(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_ALLOW),     # 7
        # 8: EPERM rather than a kill: a model that shells out gets an exception
        # it can report, and the manifest says what it tried. A killed process
        # writes no manifest and looks like a crash.
        _SockFilter(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_ERRNO | errno.EPERM),
        _SockFilter(BPF_RET | BPF_K, 0, 0, SECCOMP_RET_KILL_PROCESS),   # 9
    ]
    block = (_SockFilter * len(program))(*program)
    prog = _SockFprog(len(program), ctypes.cast(block,
                                                ctypes.POINTER(_SockFilter)))
    if _libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise _oserror("prctl(PR_SET_NO_NEW_PRIVS)")
    if _libc.syscall(NR_seccomp, ctypes.c_int(SECCOMP_SET_MODE_FILTER),
                     ctypes.c_uint(0), ctypes.byref(prog)) != 0:
        raise _oserror("seccomp(SECCOMP_SET_MODE_FILTER)")


# ---------------------------------------------------------------------------
# Building the namespace
# ---------------------------------------------------------------------------

def _mount(source: str | None, target: str, fstype: str | None,
           flags: int) -> None:
    if _libc.mount(source.encode() if source else None, target.encode(),
                   fstype.encode() if fstype else None,
                   ctypes.c_ulong(flags), None) != 0:
        raise _oserror(f"mount({source} -> {target}, {flags:#x})")


def _mount_setattr(target: str, *, attr_set: int = 0, attr_clr: int = 0) -> None:
    attributes = _MountAttr(attr_set, attr_clr, 0, 0)
    if _libc.syscall(NR_mount_setattr, ctypes.c_int(AT_FDCWD), target.encode(),
                     ctypes.c_uint(AT_RECURSIVE), ctypes.byref(attributes),
                     ctypes.c_size_t(ctypes.sizeof(attributes))) != 0:
        raise _oserror(f"mount_setattr({target}, set={attr_set:#x}, "
                       f"clr={attr_clr:#x})")


def _seal_filesystem(writable: Path) -> None:
    """Everything read-only, then exactly one hole. In that order.

    The order is the property. Making the tree read-only first and punching the
    hole second means the writable set is *stated* rather than *left over*: a
    mount this code has never heard of is read-only because it is under `/`, not
    because somebody remembered to name it.
    """
    # Detach from the host's propagation before touching anything, or every
    # change here would propagate back out to the process that spawned us.
    _mount(None, "/", None, MS_REC | MS_PRIVATE)
    _mount_setattr("/", attr_set=MOUNT_ATTR_RDONLY)
    # A fresh bind of the build directory, then clear read-only on that mount
    # alone. Binding first matters: attributes are per-mount, so the new mount is
    # the thing whose attribute can be cleared without touching its parent.
    _mount(str(writable), str(writable), None, MS_BIND | MS_REC)
    _mount_setattr(str(writable), attr_clr=MOUNT_ATTR_RDONLY)


def _drop_privilege() -> None:
    """Strip every capability, and keep the identity.

    **Why capabilities and not a uid.** The obvious drop is to become `nobody`,
    and it was what this did first. It is wrong here, and the reason is worth
    keeping: a `MODIFY` job's model legitimately reads the supplied artifact out
    of the project directory, which the parent owns. Dropping to a different
    identity does not confine that read -- the read-only mount already did -- it
    just breaks it, and the failure arrives as `trimesh` reporting the source
    file does not exist, which reads like a broken fixture rather than a boundary
    that took away something the job needs.

    So the identity stays and the *authority* goes, which is also the shape the
    Windows implementation has: there the child runs as the same user under a
    restricted token, not as another user. An empty capability set is what makes
    that safe. Without `CAP_SYS_ADMIN` the candidate cannot call `mount`, so it
    cannot remount its own namespace read-write and undo property 1 from the
    inside -- which is the one thing a root candidate could otherwise do. Without
    `CAP_DAC_OVERRIDE`, uid 0 is subject to ordinary permission bits like anyone
    else; it keeps only what the parent's own ownership already grants, which is
    exactly the read the job needs and no write the mount would have allowed.

    The bounding set is cleared as well as the effective one. A capability
    missing from the bounding set cannot be reacquired by any means, including a
    setuid-root binary -- and `SECBIT_NOROOT` says the same thing a second way.
    """
    # The bounding set first, and this order is the whole of it. Clearing the
    # effective set also clears `CAP_SETPCAP`, which is the capability
    # `PR_CAPBSET_DROP` needs -- so doing it the other way round leaves the
    # bounding set full and every drop after the first answering EPERM. It is
    # the same shape as writing a setuid drop uid-first, and it fails the same
    # way: loudly here, because the drop is verified below, and silently in any
    # version of this that does not verify.
    for capability in range(0, _CAP_LAST_CAP + 1):
        # EINVAL for a capability this kernel does not define is the loop's
        # terminating condition rather than a failure: the constant is a
        # ceiling, and a kernel with fewer capabilities is not one with a hole.
        if _libc.prctl(PR_CAPBSET_DROP, capability, 0, 0, 0) != 0 \
                and ctypes.get_errno() != errno.EINVAL:
            raise _oserror(f"prctl(PR_CAPBSET_DROP, {capability})")
    if _libc.prctl(PR_SET_SECUREBITS,
                   SECBIT_NOROOT | SECBIT_NOROOT_LOCKED, 0, 0, 0) != 0:
        raise _oserror("prctl(PR_SET_SECUREBITS)")
    header = _CapHeader(_LINUX_CAPABILITY_VERSION_3, 0)
    empty = (_CapData * 2)()
    if _libc.capset(ctypes.byref(header), ctypes.byref(empty)) != 0:
        raise _oserror("capset(empty)")
    if _libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        raise _oserror("prctl(PR_SET_NO_NEW_PRIVS)")
    if _effective_capabilities() != 0:                 # pragma: no cover
        raise OSError(errno.EPERM, "the capability drop did not take")


def _effective_capabilities() -> int:
    """The effective set, read back. A drop nobody verified is a drop nobody made."""
    header = _CapHeader(_LINUX_CAPABILITY_VERSION_3, 0)
    data = (_CapData * 2)()
    if _libc.capget(ctypes.byref(header), ctypes.byref(data)) != 0:
        raise _oserror("capget")
    return data[0].effective | (data[1].effective << 32)


def _namespace_pids() -> list[int]:
    """Every process alive in this PID namespace, from its own `/proc`."""
    return sorted(int(entry.name) for entry in os.scandir("/proc")
                  if entry.name.isdigit())


@dataclasses.dataclass(frozen=True)
class _Outcome:
    returncode: int | None
    timed_out: bool
    survivors: int
    pid: int
    error: str


def _supervise(argv: list[str], cwd: Path, env: dict[str, str], timeout: float,
               output_fd: int, status_fd: int) -> None:
    """PID 1 of the new namespace. Sets the boundary up, then holds it open.

    It is a supervisor rather than the candidate itself for one reason:
    `survivors` has to be counted by something inside the namespace, after the
    candidate has exited and before the namespace dies. The candidate cannot
    count itself, and the parent cannot see in.

    Never returns. Everything it can fail at is reported down `status_fd` and
    then it exits, which kills the namespace and anything the candidate left in
    it.
    """
    import json
    result: dict[str, object] = {"returncode": None, "timed_out": False,
                                 "survivors": 0, "pid": 0, "error": ""}
    try:
        # If the process that created this namespace dies, so does this. The
        # namespace outliving its creator would be a build nobody is waiting for
        # and nobody will reap.
        _libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0)
        _seal_filesystem(cwd)
        # A `/proc` for *this* namespace, so the survivor count below is of this
        # namespace's processes and not of the host's.
        #
        # **Read-only, and this is a repaired escape rather than tidiness.** The
        # first version mounted it with flags `0`, after `_seal_filesystem` had
        # already run -- so the recursive read-only attribute did not cover it,
        # and the tree had two writable mounts while the docstring claimed one.
        # The candidate keeps the parent's identity by design, so it was uid 0
        # over root-owned procfs tunables with nothing but that mount to stop it:
        # write `|/path/in/the/build/dir/evil` into `/proc/sys/kernel/core_pattern`,
        # fork, crash, and the kernel runs that helper through
        # `call_usermodehelper` as root on the *host*, outside every namespace
        # and outside the seccomp filter. `/proc/sys/kernel/modprobe` is the same
        # move. An empty capability set does not help: a uid-0 owner writing a
        # 0644 sysctl needs no capability.
        #
        # `nosuid`/`nodev`/`noexec` beside read-only because this mount is the
        # one surface in the namespace that is not plain file data.
        _mount("proc", "/proc", "proc",
               MS_RDONLY | MS_NOSUID | MS_NODEV | MS_NOEXEC)
        # Belt and braces: the flags above are the mount's own, and a re-seal
        # costs nothing and covers any submount procfs brings with it.
        _mount_setattr("/proc", attr_set=MOUNT_ATTR_RDONLY)

        child = os.fork()
        if child == 0:                                    # the candidate
            try:
                os.setsid()
                os.dup2(output_fd, 1)
                os.dup2(output_fd, 2)
                devnull = os.open(os.devnull, os.O_RDONLY)
                os.dup2(devnull, 0)
                for fd in (output_fd, status_fd):
                    if fd > 2:
                        os.close(fd)
                os.chdir(str(cwd))
                _drop_privilege()
                os.execve(argv[0], list(argv), dict(env))
            except BaseException as exc:                  # noqa: BLE001
                try:
                    os.write(2, f"confine: {type(exc).__name__}: {exc}\n"
                             .encode())
                finally:
                    os._exit(127)

        result["pid"] = child
        deadline = time.monotonic() + timeout
        status = None
        while True:
            done, raw = os.waitpid(child, os.WNOHANG)
            if done == child:
                status = raw
                break
            if time.monotonic() > deadline:
                result["timed_out"] = True
                try:
                    os.kill(child, signal.SIGKILL)
                except ProcessLookupError:                # pragma: no cover
                    pass
                os.waitpid(child, 0)
                break
            time.sleep(0.01)

        if status is not None:
            result["returncode"] = (os.waitstatus_to_exitcode(status)
                                    if os.WIFEXITED(status) else None)

        # Counted after a settle and before this process exits, which is the
        # only window in which the answer exists. Exiting is what kills them.
        time.sleep(SURVIVOR_GRACE_S)
        alive = [pid for pid in _namespace_pids() if pid not in (1, child)]
        result["survivors"] = len(alive)
    except BaseException as exc:                          # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            os.write(status_fd, json.dumps(result).encode())
            os.close(status_fd)
        except OSError:                                   # pragma: no cover
            pass
        # Exit, and the kernel kills everything still in this namespace. There
        # is no flag a process can hold that lets it survive this.
        os._exit(0)


def run(argv: list[str], *, cwd: Path, env: dict[str, str],
        timeout: float) -> "Confined":
    """Run `argv` confined, and return only once the namespace is gone.

    The order of the last steps is the point of the function, and it is the same
    order the Windows implementation keeps for the same reason: the supervisor is
    waited for, and a supervisor that has exited is a namespace the kernel has
    already emptied. So when this returns there is no process anywhere that could
    still be writing into the build directory -- not a detached grandchild, not
    something that called `setsid`, not anything. The parent does not have to
    poll for that, because the kernel does not offer a way to opt out of it.
    """
    from .confine import Confined, ConfinementUnavailable

    reason = unavailable_reason()
    if reason:
        raise ConfinementUnavailable(reason)

    import json

    started = time.perf_counter()
    output_r, output_w = os.pipe()
    status_r, status_w = os.pipe()

    outer = os.fork()
    if outer == 0:                                        # pragma: no cover
        # Between the two forks. `unshare(CLONE_NEWPID)` puts the *children* of
        # this process into the new namespace rather than this process, so the
        # supervisor has to be forked after it -- that second child is PID 1.
        try:
            os.close(output_r)
            os.close(status_r)
            if _libc.unshare(CONFINED_NAMESPACES) != 0:
                raise _oserror("unshare")
            supervisor = os.fork()
            if supervisor == 0:
                _supervise(argv, Path(cwd), dict(env), timeout,
                           output_w, status_w)            # never returns
            os.close(output_w)
            os.close(status_w)
            os.waitpid(supervisor, 0)
        except BaseException as exc:                      # noqa: BLE001
            try:
                os.write(status_w, json.dumps(
                    {"returncode": None, "timed_out": False, "survivors": 0,
                     "pid": 0,
                     "error": f"{type(exc).__name__}: {exc}"}).encode())
            except OSError:
                pass
        os._exit(0)

    os.close(output_w)
    os.close(status_w)

    # Read to EOF. Every copy of the write end lives inside the namespace, so
    # EOF is itself evidence that the namespace is empty -- but it is not what
    # this waits on, because a survivor holding the pipe open would then hang the
    # parent. The supervisor's exit is the authority; this just drains.
    chunks: list[bytes] = []
    try:
        while True:
            block = os.read(output_r, 65536)
            if not block:
                break
            chunks.append(block)
    finally:
        os.close(output_r)

    raw = b""
    try:
        while True:
            block = os.read(status_r, 65536)
            if not block:
                break
            raw += block
    finally:
        os.close(status_r)
    os.waitpid(outer, 0)

    seconds = time.perf_counter() - started
    output = b"".join(chunks).decode("utf-8", "replace")
    try:
        status = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ConfinementUnavailable(
            "the confinement supervisor reported nothing, so what the candidate "
            "did and whether anything of it is still running are both unknown. "
            "Nothing is read out of the build directory on this path.")
    if status.get("error"):
        raise ConfinementUnavailable(
            f"the confinement could not be established: {status['error']}")

    return Confined(returncode=status["returncode"], output=output,
                    timed_out=bool(status["timed_out"]), seconds=seconds,
                    pid=int(status["pid"]), survivors=int(status["survivors"]))
