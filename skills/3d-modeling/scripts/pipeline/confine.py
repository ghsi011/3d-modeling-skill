#!/usr/bin/env python3
"""OS-enforced confinement for the build boundary. Windows primitives only.

`isolation.py` decides *what* crosses the boundary. This module is *how the
boundary is enforced*, and it enforces it with the operating system rather than
with the Python interpreter.

The previous boundary spawned a peer: same user, same filesystem, same
privileges, no lifetime bound. Separation was implemented as a different
interpreter and not as a confinement, and three attacks walked through it -- a
candidate that rewrote `backends/authored.py` while it built, which the parent
then imported and executed in the process holding the frozen contract; the same
thing through a `__pycache__` entry stamped to the real file's mtime and size,
leaving the `.py` byte-identical; and a `DETACHED_PROCESS` grandchild that
outlived `subprocess.run`'s timeout and rewrote `final_status.json` 25 s after
the run had reported `FAILED`.

None of those are import-graph problems. All three are *authority* problems, so
the answer is an authority the candidate does not hold.

**Three mechanisms, and what each one actually buys**, measured on this box
rather than assumed (`test_isolation.WhatTheConfinementEnforcesTest` re-measures
every row):

1. **A restricted token.** `CreateRestrictedToken` with a restricting-SID list
   that omits `NT AUTHORITY\\Authenticated Users`. Every access is then checked
   twice -- once against the ordinary token and once against the restricting SIDs
   -- and the *lesser* answer wins. The repository, the virtual environment and
   this package's source are writable by their `Authenticated Users: Modify` ACE
   and by nothing else the token carries, so the second check caps them at
   `BUILTIN\\Users: Read & Execute`. Measured: writes to the repo, to
   `site-packages` and to `pipeline/` are refused at *medium* integrity with no
   deny-only SIDs, which is to say by this mechanism alone.

   It does **not** refuse `socket.connect`. This module said it did, on the
   strength of a probe against `1.1.1.1:53` -- a port NordVPN Threat Protection
   filters on this machine, identically with no confinement at all. Re-measured
   under the real token: `1.1.1.1:443` connects, `1.1.1.1:80` connects,
   `93.184.215.14:80` connects. The network is open, not closed-except-DNS, and
   `docs/defects.md` D11 is where that is written down.
2. **Low integrity.** Every object with no explicit label is implicitly Medium,
   and a Low subject cannot write up. Measured: this is what refuses the project
   directory, the parent's `%TEMP%`, the Startup folder, the sandbox's own input
   directory, and `OpenProcess(PROCESS_VM_WRITE)` against the parent.
3. **A job object**, `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, neither kind of
   breakaway permitted. `DETACHED_PROCESS` never left a job -- the attack that
   used it worked because there was no job -- and a grandchild that passes
   `CREATE_BREAKAWAY_FROM_JOB`, which is the flag whose whole purpose is to
   leave one, is measured not to. The parent does not look at a single output
   byte until the job reports zero live processes, and it counts them by process
   id rather than by the job's own count, because a job keeps counting a process
   until its last handle closes.
4. **No child processes at all**, `PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY`
   with `PROCESS_CREATION_CHILD_PROCESS_RESTRICTED`. The job bounds what a
   candidate spawns; this is why it now spawns nothing. Measured before it was
   added: a candidate under the full boundary launched `cmd.exe`. Measured after:
   `WinError 367` out of `CreateProcess`, at zero geometry cost. Mechanisms 3 and
   4 are not redundant -- 3 is what makes a *failure* of 4 survivable, and it is
   the one that has already been walked through.

**A caution about the third**, because it cost a false positive on the first
honest build. `DETACHED_PROCESS` makes Windows start a `conhost.exe` *inside the
job*, where it lives for well under 100 ms; `CREATE_NO_WINDOW` does the same.
"Survivors" is therefore measured after `SURVIVOR_GRACE_S`, and no safety
property rides on the number -- the job is terminated and drained to zero either
way. The number only decides whether the run is additionally refused for having
spawned something.

Plus two things that are not mechanisms so much as the absence of a gift: the
child inherits exactly the handles named in a `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`
(a `NUL` stdin and one pipe it may write a transcript into), and it is handed a
constructed environment rather than the parent's.

**Every privilege is deleted except `SeChangeNotifyPrivilege`.** That one is
bypass-traverse-checking, which `Everyone` holds by default and which confers no
access to any object -- it only skips the check on the *intermediate* directories
of a path. Keeping it is what lets the sandbox live under the parent's `%TEMP%`
instead of somewhere world-traversable.

**What this does not do**, and why not, is `docs/defects.md` D9. In one line
each: **the network is open** -- an outbound TCP connect to any port other than
the one a third-party firewall happens to filter succeeds, and DNS resolves as
well, through the DNS Client service; `AppData\\LocalLow` and `%TEMP%\\Low` carry
an explicit *Low* label from Windows and are therefore writable by a Low subject;
and the candidate can still *read* whatever `BUILTIN\\Users` can read.
`AppContainer` is the mechanism that closes the first and the third -- network is
a capability (`internetClient`) enforced by the Windows Filtering Platform rather
than by an ACL -- and it needs the whole runtime ACL'd for a package SID.
Untrusted integrity closes the second and does not start: a process created with
an Untrusted primary token dies at `STATUS_DLL_INIT_FAILED`, measured, as does
one whose restricting SIDs omit the user's own.

`test_isolation.WhatTheConfinementEnforcesTest` carries the open network as an
`expectedFailure` rather than as a comment: the expectation that this boundary
denies outbound TCP is written down and *fails*, so the day it starts passing is
a reported event and not a line nobody updated.
"""
from __future__ import annotations

import ctypes
import dataclasses
import os
import subprocess                                 # for list2cmdline, and nothing
import sys                                        # else: see `command_line`
import threading
import time
from ctypes import wintypes
from pathlib import Path

WINDOWS = os.name == "nt"

# Raised immediately before the one call in this package that creates a process.
AUDIT_SPAWN = "pipeline.confine.spawn"


class ConfinementUnavailable(RuntimeError):
    """The confinement cannot be built here, so no candidate may be run here.

    Raised rather than degraded. A boundary that silently becomes an ordinary
    subprocess on a platform it was not written for is worse than no boundary,
    because the receipts do not say which one ran.
    """


@dataclasses.dataclass(frozen=True)
class Confined:
    """What the parent knows after the job object is dead."""

    returncode: int | None      # None when the job was killed rather than exited
    output: str                 # the child's merged stdout/stderr, untrusted text
    timed_out: bool
    seconds: float
    pid: int                    # the direct child, so `survivors` can exclude it
    # Processes still alive in the job when the direct child exited. Zero on an
    # honest build; anything else is a candidate that tried to outlive its own
    # run, and the number is a finding worth writing down.
    survivors: int


# --------------------------------------------------------------------------
# ctypes bindings. `pywin32` is not in the frozen runtime and adding a
# dependency to a security boundary to save fifty lines of declarations is the
# wrong trade: this way the boundary's surface is visible in this file.
# --------------------------------------------------------------------------
if WINDOWS:                                       # pragma: no branch - platform
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:                                             # pragma: no cover - platform
    _advapi32 = _kernel32 = None

TOKEN_ALL_ACCESS = 0xF01FF
TOKEN_INTEGRITY_LEVEL = 25
TOKEN_GROUPS = 2
TOKEN_PRIVILEGES = 3
TOKEN_USER = 1
TOKEN_RESTRICTED_SIDS = 11

SE_GROUP_INTEGRITY = 0x00000020
SE_GROUP_USE_FOR_DENY_ONLY = 0x00000010
SE_GROUP_LOGON_ID = 0xC0000000

CREATE_SUSPENDED = 0x00000004
CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000
# No console at all, rather than a console with no window: the candidate gets no
# handle on the parent's console, cannot read what is on it, and cannot signal
# the process group that owns it. All three standard handles are redirected, so
# there is nothing a console would be for.
#
# It has one measured consequence. Windows starts a `conhost.exe` for the new
# console session and starts it *inside the job*, where it lives for under
# 100 ms and exits. `CREATE_NO_WINDOW` does the same; passing neither flag
# happens to avoid it only because this parent already had a console to inherit,
# which is not a property a boundary may depend on. `SURVIVOR_GRACE_S` is the
# answer, and it is why "survivors" is measured after a settle rather than at
# the instant the direct child exits.
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
STARTF_USESTDHANDLES = 0x00000100

PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002

# D12. The job object bounds what the candidate spawns; this stops it spawning.
# Until it was added, a candidate under the full boundary could launch `cmd.exe`
# -- measured -- and every counter-measure was downstream of the process already
# existing: the job caught it, the survivor sweep counted it, the drain killed
# it. `PROCESS_CREATION_CHILD_PROCESS_RESTRICTED` moves the refusal to
# `CreateProcess` itself, where it comes back as `OSError: [WinError 367] The
# process creation has been blocked` -- measured, from a candidate calling
# `subprocess.run(["cmd", "/c", "exit"])` -- at zero measured geometry cost.
#
# It has one prerequisite and it is not optional: the process this policy applies
# to may not itself be a launcher. A virtual environment's `python.exe` is one --
# it spawns the base interpreter as a child -- so the boundary starts the base
# interpreter directly, with `PYTHONPATH` naming the environment's
# `site-packages`. See `isolation.base_executable`.
PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY = 0x0002000E
PROCESS_CREATION_CHILD_PROCESS_RESTRICTED = 0x00000001

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JobObjectBasicAccountingInformation = 1
JobObjectBasicProcessIdList = 3
JobObjectBasicUIRestrictions = 4
JobObjectExtendedLimitInformation = 9

JOB_OBJECT_UILIMIT_HANDLES = 0x00000001
JOB_OBJECT_UILIMIT_READCLIPBOARD = 0x00000002
JOB_OBJECT_UILIMIT_WRITECLIPBOARD = 0x00000004
JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS = 0x00000008
JOB_OBJECT_UILIMIT_DISPLAYSETTINGS = 0x00000010
JOB_OBJECT_UILIMIT_GLOBALATOMS = 0x00000020
JOB_OBJECT_UILIMIT_DESKTOP = 0x00000040
JOB_OBJECT_UILIMIT_EXITWINDOWS = 0x00000080

# A job the candidate cannot leave, cannot fill, and cannot use to reach the
# parent's windows, clipboard or desktop.
JOB_UI_RESTRICTIONS = (JOB_OBJECT_UILIMIT_HANDLES | JOB_OBJECT_UILIMIT_READCLIPBOARD
                       | JOB_OBJECT_UILIMIT_WRITECLIPBOARD
                       | JOB_OBJECT_UILIMIT_SYSTEMPARAMETERS
                       | JOB_OBJECT_UILIMIT_DISPLAYSETTINGS
                       | JOB_OBJECT_UILIMIT_GLOBALATOMS
                       | JOB_OBJECT_UILIMIT_DESKTOP
                       | JOB_OBJECT_UILIMIT_EXITWINDOWS)

# One geometry build. The kernel may thread, but nothing on this path forks a
# process, so a cap this low is a bound and not a budget.
JOB_ACTIVE_PROCESS_LIMIT = 8

# How long the job is watched, after the direct child has exited, before anything
# still in it is called a survivor. Windows' own `conhost.exe` is in there for
# well under 100 ms of every run and is not the candidate's doing; a process
# spawned to outlive the build is still there at the end of this. Nothing about
# safety rides on the number -- the job is terminated and drained to zero either
# way, before a single output byte is read -- it only decides whether the run is
# additionally *refused* for having spawned something.
SURVIVOR_GRACE_S = 1.5

DACL_SECURITY_INFORMATION = 0x00000004
LABEL_SECURITY_INFORMATION = 0x00000010
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
SE_FILE_OBJECT = 1

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
INFINITE = 0xFFFFFFFF

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# `RC` is `SDDL_RESTRICTED_CODE`, S-1-5-12: a SID that appears in restricted
# tokens and in nothing else, so an ACE naming it grants nothing to any ordinary
# process on this machine. `LW` is the Low mandatory level and `NW` is
# no-write-up, which is the only mandatory policy Windows applies by default.
SDDL_RESTRICTED_CODE = "RC"


class _SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class _LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", _LUID), ("Attributes", wintypes.DWORD)]


class _TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", _SID_AND_ATTRIBUTES)]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


class _SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wintypes.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wintypes.BOOL)]


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),            # ULONG_PTR, and the struct's
        ("PriorityClass", wintypes.DWORD),        # size is what the kernel checks
        ("SchedulingClass", wintypes.DWORD),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_longlong), ("TotalKernelTime", ctypes.c_longlong),
        ("ThisPeriodTotalUserTime", ctypes.c_longlong),
        ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD), ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _JOBOBJECT_BASIC_UI_RESTRICTIONS(ctypes.Structure):
    _fields_ = [("UIRestrictionsClass", wintypes.DWORD)]


class _JOBOBJECT_BASIC_PROCESS_ID_LIST(ctypes.Structure):
    _fields_ = [("NumberOfAssignedProcesses", wintypes.DWORD),
                ("NumberOfProcessIdsInList", wintypes.DWORD),
                ("ProcessIdList", ctypes.c_size_t * 256)]


def _bind() -> None:
    """Argument and result types, because a truncated HANDLE is a silent bug.

    `GetCurrentProcess()` returns `(HANDLE)-1`; with ctypes' default `c_int`
    result it becomes `-1` and is passed to a 64-bit parameter as four bytes of
    it. The first version of this module failed with "the handle is invalid" for
    exactly that reason, so every entry point used here is declared.
    """
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.GetCurrentProcess.argtypes = []
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE,
                                             ctypes.POINTER(wintypes.DWORD)]
    _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                  ctypes.c_void_p, wintypes.DWORD]
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    _kernel32.ResumeThread.restype = wintypes.DWORD
    _kernel32.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE),
                                     ctypes.POINTER(wintypes.HANDLE),
                                     ctypes.c_void_p, wintypes.DWORD]
    _kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                               wintypes.DWORD]
    _kernel32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                   ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    _kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)]
    _kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
    _kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    _kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                      wintypes.HANDLE]
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _kernel32.FindFirstStreamW.argtypes = [wintypes.LPCWSTR, ctypes.c_int,
                                           ctypes.c_void_p, wintypes.DWORD]
    _kernel32.FindFirstStreamW.restype = wintypes.HANDLE
    _kernel32.FindNextStreamW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _kernel32.FindClose.argtypes = [wintypes.HANDLE]

    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    _advapi32.SetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                              ctypes.c_void_p, wintypes.DWORD]
    _advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    _advapi32.GetLengthSid.restype = wintypes.DWORD
    _advapi32.ConvertStringSidToSidW.argtypes = [wintypes.LPCWSTR,
                                                 ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p,
                                                 ctypes.POINTER(wintypes.LPWSTR)]
    _advapi32.LookupPrivilegeNameW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                               wintypes.LPWSTR,
                                               ctypes.POINTER(wintypes.DWORD)]
    _advapi32.CreateRestrictedToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p,
        ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.CreateProcessAsUserW.argtypes = [
        wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p,
        wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p]
    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD)]
    _advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    _advapi32.GetSecurityDescriptorSacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)]
    _advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD


if WINDOWS:                                       # pragma: no branch - platform
    _bind()


def _fail(what: str) -> None:
    code = ctypes.get_last_error()
    raise ConfinementUnavailable(
        f"{what} failed with Windows error {code}: {ctypes.FormatError(code)}")


def unavailable_reason() -> str | None:
    """Why a candidate cannot be confined here, or `None` when it can.

    Called before the parent has committed to anything. A boundary that cannot
    be established is a refusal and never a downgrade.
    """
    if not WINDOWS:
        return (f"the confined build boundary is implemented with Windows "
                f"restricted tokens, mandatory integrity levels and job objects, "
                f"and this is {sys.platform}. There is no unconfined path: "
                f"candidate code is not executed at all where it cannot be "
                f"confined.")
    return None


def available() -> bool:
    return unavailable_reason() is None


# --------------------------------------------------------------------------
# Token
# --------------------------------------------------------------------------
def _own_token() -> wintypes.HANDLE:
    handle = wintypes.HANDLE()
    if not _advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(),
                                      TOKEN_ALL_ACCESS, ctypes.byref(handle)):
        _fail("OpenProcessToken")
    return handle


def _token_information(token: wintypes.HANDLE, kind: int) -> ctypes.Array:
    size = wintypes.DWORD()
    _advapi32.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
    buffer = ctypes.create_string_buffer(max(size.value, 1))
    if not _advapi32.GetTokenInformation(token, kind, buffer, size,
                                         ctypes.byref(size)):
        _fail(f"GetTokenInformation({kind})")
    return buffer


def _sid_text(sid: int) -> str:
    out = wintypes.LPWSTR()
    if not _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(out)):
        _fail("ConvertSidToStringSidW")
    return out.value


def _sid(text: str) -> ctypes.c_void_p:
    out = ctypes.c_void_p()
    if not _advapi32.ConvertStringSidToSidW(text, ctypes.byref(out)):
        _fail(f"ConvertStringSidToSidW({text})")
    return out


def user_sid() -> str:
    """The SID the sandbox directories are ACL'd for on the parent's side."""
    return _sid_text(_SID_AND_ATTRIBUTES.from_buffer(
        _token_information(_own_token(), TOKEN_USER)).Sid)


def _groups(token: wintypes.HANDLE,
            kind: int = TOKEN_GROUPS) -> list[tuple[str, int]]:
    """A `TOKEN_GROUPS` payload, which is also the shape of the restricting SIDs."""
    buffer = _token_information(token, kind)
    count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))[0]
    offset = ctypes.sizeof(ctypes.c_void_p)      # DWORD count, then padding
    entries = (_SID_AND_ATTRIBUTES * count).from_buffer(buffer, offset)
    return [(_sid_text(entry.Sid), entry.Attributes) for entry in entries]


def _privileges(token: wintypes.HANDLE) -> list[tuple[str, int, int]]:
    buffer = _token_information(token, TOKEN_PRIVILEGES)
    count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD))[0]
    entries = (_LUID_AND_ATTRIBUTES * count).from_buffer(buffer, 4)
    found = []
    for entry in entries:
        size = wintypes.DWORD(0)
        _advapi32.LookupPrivilegeNameW(None, ctypes.byref(entry.Luid), None,
                                       ctypes.byref(size))
        name = ctypes.create_unicode_buffer(max(size.value, 1))
        _advapi32.LookupPrivilegeNameW(None, ctypes.byref(entry.Luid), name,
                                       ctypes.byref(size))
        found.append((name.value, entry.Luid.LowPart, entry.Luid.HighPart))
    return found


# The restricting-SID set. Every access the child makes is checked against this
# list *as well as* against its ordinary token, and the smaller answer wins.
#
# What is deliberately absent is `NT AUTHORITY\Authenticated Users`, S-1-5-11.
# On this machine `C:\` carries `Authenticated Users:(OI)(CI)(IO)(M)`, so every
# inherited object below it -- the repository, the virtual environment,
# `site-packages`, this package's own source -- is writable through that ACE and
# through no other. Dropping it from the second check caps all of them at
# `BUILTIN\Users: Read & Execute`.
#
# What is deliberately *present*: the token's own user SID. Removing it is the
# stronger lockdown and it does not work as a primary token -- a process created
# with it dies at `STATUS_DLL_INIT_FAILED` before `main`, because image
# activation needs access that only the user SID grants. Chromium reaches that
# level by starting the target with a permissive *impersonation* token and having
# the target drop it after initialisation; that requires the confined program to
# cooperate in its own confinement, and it is recorded as the next step rather
# than pretended here.
RESTRICTING_SIDS = (
    "S-1-1-0",                                    # Everyone
    "S-1-5-32-545",                               # BUILTIN\Users
    "S-1-5-12",                                   # NT AUTHORITY\RESTRICTED
)

LOW_INTEGRITY_SID = "S-1-16-4096"

# Bypass traverse checking. It grants no access to any object; it only skips the
# check on intermediate directories, and `Everyone` holds it by default. Deleting
# it would mean the sandbox could not live under the parent's `%TEMP%`, whose
# ancestors grant the user alone.
KEPT_PRIVILEGE = "SeChangeNotifyPrivilege"


def _restricted_token() -> wintypes.HANDLE:
    """A restricted, low-integrity, privilege-stripped primary token."""
    token = _own_token()
    groups = _groups(token)
    logon = [sid for sid, attributes in groups
             if attributes & SE_GROUP_LOGON_ID == SE_GROUP_LOGON_ID]

    # The logon SID is what the window station and the desktop are ACL'd for.
    # Without it the child cannot connect to the window station and dies before
    # `main`, which is a startup requirement rather than a grant of anything.
    restricting = list(dict.fromkeys(list(RESTRICTING_SIDS) + logon + [user_sid()]))

    # Every remaining group becomes deny-only: it can still deny access through a
    # deny ACE and can no longer grant any. `Authenticated Users` is the one that
    # matters and it is removed twice over, here and by its absence above.
    keep = set(restricting)
    disable = [sid for sid, attributes in groups
               if not attributes & SE_GROUP_INTEGRITY
               and attributes & SE_GROUP_LOGON_ID != SE_GROUP_LOGON_ID
               and sid not in keep]

    drop = [(low, high) for name, low, high in _privileges(token)
            if name != KEPT_PRIVILEGE]

    disable_array = (_SID_AND_ATTRIBUTES * max(len(disable), 1))()
    for index, sid in enumerate(disable):
        disable_array[index].Sid = _sid(sid)
    restrict_array = (_SID_AND_ATTRIBUTES * max(len(restricting), 1))()
    for index, sid in enumerate(restricting):
        restrict_array[index].Sid = _sid(sid)
    privilege_array = (_LUID_AND_ATTRIBUTES * max(len(drop), 1))()
    for index, (low, high) in enumerate(drop):
        privilege_array[index].Luid.LowPart = low
        privilege_array[index].Luid.HighPart = high

    restricted = wintypes.HANDLE()
    if not _advapi32.CreateRestrictedToken(
            token, 0,
            len(disable), disable_array if disable else None,
            len(drop), privilege_array if drop else None,
            len(restricting), restrict_array,
            ctypes.byref(restricted)):
        _fail("CreateRestrictedToken")

    label_sid = _sid(LOW_INTEGRITY_SID)
    label = _TOKEN_MANDATORY_LABEL()
    label.Label.Sid = label_sid
    label.Label.Attributes = SE_GROUP_INTEGRITY
    if not _advapi32.SetTokenInformation(
            restricted, TOKEN_INTEGRITY_LEVEL, ctypes.byref(label),
            ctypes.sizeof(label) + _advapi32.GetLengthSid(label_sid)):
        _fail("SetTokenInformation(TokenIntegrityLevel)")
    return restricted


def describe_token(token: wintypes.HANDLE | None = None) -> dict[str, object]:
    """What a token *is*, read back out of the kernel.

    The point of reading rather than restating: called with no argument inside
    the confined child, this describes the token the child is actually running
    under. A test that asserted `RESTRICTING_SIDS` did not contain
    `Authenticated Users` would be asserting that a tuple equals itself; a probe
    model that reports this is evidence.

    `SE_GROUP_USE_FOR_DENY_ONLY` is 0x10: a group that can still deny access
    through a deny ACE and can no longer grant any.
    """
    token = token if token is not None else _own_token()
    groups = _groups(token)
    return {
        "restricting_sids": sorted(sid for sid, _ in _groups(token,
                                                             TOKEN_RESTRICTED_SIDS)),
        "deny_only": sorted(sid for sid, attributes in groups
                            if attributes & SE_GROUP_USE_FOR_DENY_ONLY),
        "integrity": next((sid for sid, attributes in groups
                           if attributes & SE_GROUP_INTEGRITY), None),
        "privileges": sorted(name for name, _low, _high in _privileges(token)),
    }


# --------------------------------------------------------------------------
# Directory security
# --------------------------------------------------------------------------
def _apply_sddl(path: Path, sddl: str, *, with_label: bool) -> None:
    descriptor = ctypes.c_void_p()
    if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None):
        _fail(f"ConvertStringSecurityDescriptorToSecurityDescriptorW({sddl})")

    try:
        present = wintypes.BOOL()
        defaulted = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        if not _advapi32.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present),
                                                   ctypes.byref(dacl),
                                                   ctypes.byref(defaulted)):
            _fail("GetSecurityDescriptorDacl")

        sacl = ctypes.c_void_p()
        information = DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
        if with_label:
            if not _advapi32.GetSecurityDescriptorSacl(
                    descriptor, ctypes.byref(present), ctypes.byref(sacl),
                    ctypes.byref(defaulted)):
                _fail("GetSecurityDescriptorSacl")
            information |= LABEL_SECURITY_INFORMATION

        status = _advapi32.SetNamedSecurityInfoW(
            str(path), SE_FILE_OBJECT, information, None, None, dacl,
            sacl if with_label else None)
        if status != 0:
            raise ConfinementUnavailable(
                f"SetNamedSecurityInfoW({path}) failed with Windows error {status}: "
                f"{ctypes.FormatError(status)}")
    finally:
        _kernel32.LocalFree(descriptor)


def seal_read_only(path: Path) -> None:
    """The candidate's inputs, after they have been staged.

    Read and execute for the parent and for restricted code, and write for
    nobody. `PROTECTED` so nothing is inherited from `%TEMP%`, and no mandatory
    label, which leaves the directory at the implicit Medium that a Low child
    cannot write to. Two mechanisms, and the DACL is the one that also holds if
    the integrity level is ever raised.

    The parent keeps ownership, so it can restore write access to clean up. It
    is not granted here, because a boundary whose inputs are writable by the
    process that also promotes the outputs is one edit away from not being one.
    """
    _apply_sddl(path,
                f"D:P(A;;FA;;;SY)(A;OICI;FRFX;;;{user_sid()})"
                f"(A;OICI;FRFX;;;{SDDL_RESTRICTED_CODE})",
                with_label=False)


def seal_writable(path: Path) -> None:
    """The one directory the candidate may write, and the only one.

    Labelled Low so a Low-integrity subject can write it -- every other object on
    the system is implicitly Medium and therefore cannot be. Nobody is granted
    `WRITE_DAC` or `WRITE_OWNER` by ACE; the parent holds both as owner.
    """
    _apply_sddl(path,
                f"D:P(A;;FA;;;SY)(A;OICI;FRFWFXSD;;;{user_sid()})"
                f"(A;OICI;FRFWFXSD;;;{SDDL_RESTRICTED_CODE})"
                f"S:(ML;OICI;NW;;;LW)",
                with_label=True)


def unseal(path: Path) -> None:
    """Give the parent write access back, so the sandbox can be deleted."""
    _apply_sddl(path, f"D:P(A;;FA;;;SY)(A;OICI;FA;;;{user_sid()})", with_label=False)


class _FIND_STREAM_DATA(ctypes.Structure):
    _fields_ = [("StreamSize", ctypes.c_longlong),
                ("cStreamName", ctypes.c_wchar * 296)]


def data_streams(path: Path) -> list[str]:
    """Every named data stream on a file, `::$DATA` included.

    A file's contents are one stream, and everything anyone hashes is that
    stream. `candidate.stl:payload` is a second one: invisible to `read_bytes`,
    to a digest, to `os.stat` and to a directory listing, and it travels with the
    file when it is copied. There is no reason for a build output to carry one,
    so the boundary refuses any that does rather than promoting a file whose
    receipt describes part of it.
    """
    if not WINDOWS:                               # pragma: no cover - platform
        return []
    data = _FIND_STREAM_DATA()
    handle = _kernel32.FindFirstStreamW(str(path), 0, ctypes.byref(data), 0)
    if handle == INVALID_HANDLE_VALUE:
        return []
    found = []
    try:
        while True:
            found.append(data.cStreamName)
            if not _kernel32.FindNextStreamW(handle, ctypes.byref(data)):
                break
    finally:
        _kernel32.FindClose(handle)
    return found


def is_reparse_point(path: Path) -> bool:
    """A symlink, junction, mount point or any other reparse tag.

    `os.path.islink` answers for symlinks; a directory junction is not a symlink
    and is the one a candidate can create with no privilege at all.
    """
    try:
        return bool(path.lstat().st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return False


# --------------------------------------------------------------------------
# Job object and process
# --------------------------------------------------------------------------
def _job() -> wintypes.HANDLE:
    """An unnamed job: no other process can open it, and nothing leaves it.

    Unnamed on purpose. A named job object is openable by name by anything with
    the name, and the name of the thing that bounds the candidate's lifetime is
    not a secret worth keeping.

    `JOB_OBJECT_LIMIT_BREAKAWAY_OK` and `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK`
    are both absent, which is what makes `CREATE_BREAKAWAY_FROM_JOB` fail rather
    than succeed. `DETACHED_PROCESS` was never a way out of a job; the attack
    that used it worked because there was no job.
    """
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        _fail("CreateJobObjectW")

    limits = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    limits.BasicLimitInformation.LimitFlags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS)
    limits.BasicLimitInformation.ActiveProcessLimit = JOB_ACTIVE_PROCESS_LIMIT
    if not _kernel32.SetInformationJobObject(
            handle, JobObjectExtendedLimitInformation, ctypes.byref(limits),
            ctypes.sizeof(limits)):
        _kernel32.CloseHandle(handle)
        _fail("SetInformationJobObject(ExtendedLimitInformation)")

    ui = _JOBOBJECT_BASIC_UI_RESTRICTIONS()
    ui.UIRestrictionsClass = JOB_UI_RESTRICTIONS
    if not _kernel32.SetInformationJobObject(
            handle, JobObjectBasicUIRestrictions, ctypes.byref(ui),
            ctypes.sizeof(ui)):
        _kernel32.CloseHandle(handle)
        _fail("SetInformationJobObject(BasicUIRestrictions)")
    return handle


def _active_processes(job: wintypes.HANDLE) -> int:
    accounting = _JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
    returned = wintypes.DWORD()
    if not _kernel32.QueryInformationJobObject(
            job, JobObjectBasicAccountingInformation, ctypes.byref(accounting),
            ctypes.sizeof(accounting), ctypes.byref(returned)):
        _fail("QueryInformationJobObject(BasicAccountingInformation)")
    return int(accounting.ActiveProcesses)


def _process_ids(job: wintypes.HANDLE) -> list[int]:
    """Which processes are in the job, by id, rather than how many.

    The count is not enough to answer "did anything outlive the build", because a
    job keeps counting a process until its last *handle* closes and not until it
    terminates -- the first honest build reported one survivor for that reason
    alone. The ids answer it exactly: the direct child's id is known, and
    anything else in the list is something the candidate started.

    `ERROR_MORE_DATA` means more processes than the buffer holds, which is
    already more than one; the truncated list is returned and the caller draws
    the same conclusion from it.
    """
    listing = _JOBOBJECT_BASIC_PROCESS_ID_LIST()
    returned = wintypes.DWORD()
    _kernel32.QueryInformationJobObject(
        job, JobObjectBasicProcessIdList, ctypes.byref(listing),
        ctypes.sizeof(listing), ctypes.byref(returned))
    return [int(pid) for pid in
            listing.ProcessIdList[:min(listing.NumberOfProcessIdsInList,
                                       len(listing.ProcessIdList))]]


def _environment_block(env: dict[str, str]) -> ctypes.Array:
    """A constructed environment, sorted, as `CREATE_UNICODE_ENVIRONMENT` wants.

    Constructed rather than inherited. The parent's environment names the
    project, the job and every path this machine happens to have, and none of it
    is a build input.
    """
    text = "".join(f"{name}={value}\0"
                   for name, value in sorted(env.items(), key=lambda kv: kv[0].upper()))
    return ctypes.create_unicode_buffer(text + "\0")


def command_line(argv: list[str]) -> str:
    """An argv joined the way `CreateProcessAsUserW` wants it, which is not a shell.

    `subprocess` is not on this path at all -- it cannot pass a token, a job or a
    handle list -- so the one thing it did for free has to be done here. It is
    done with `list2cmdline`, which is the stdlib's implementation of the
    quoting rules `CommandLineToArgvW` actually applies, rather than with a
    hand-rolled `f'"{x}"'` that a trailing backslash escapes its way out of.

    The executable is *also* passed separately as `lpApplicationName`, so the
    command line is never parsed to find out which program to run. There is no
    string here that any shell ever sees, and no code path that could give it
    one: the D8 mutation "launch the child with `shell=True`" has no expression
    to mutate.
    """
    return subprocess.list2cmdline(argv)


def _drain(handle: wintypes.HANDLE, sink: list[bytes]) -> None:
    buffer = ctypes.create_string_buffer(8192)
    read = wintypes.DWORD()
    while True:
        if not _kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None):
            return
        if read.value == 0:
            return
        sink.append(buffer.raw[:read.value])


def run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> Confined:
    """Run `argv` confined, and return only once the whole job object is dead.

    The order of the last three steps is the point of the function. The direct
    child is waited for; the job is terminated whether it exited or not; and the
    job's active-process count is polled to zero *before this returns*, so that
    when the caller reads the output directory there is no process left anywhere
    that could still be writing to it. The grandchild that rewrote
    `final_status.json` 25 s after the run reported `FAILED` did so because
    `subprocess.run`'s timeout bounds one process and this bounds all of them.
    """
    reason = unavailable_reason()
    if reason:
        raise ConfinementUnavailable(reason)

    started = time.perf_counter()
    token = _restricted_token()
    job = _job()

    attributes = _SECURITY_ATTRIBUTES()
    attributes.nLength = ctypes.sizeof(attributes)
    attributes.bInheritHandle = True
    read_end = wintypes.HANDLE()
    write_end = wintypes.HANDLE()
    if not _kernel32.CreatePipe(ctypes.byref(read_end), ctypes.byref(write_end),
                                ctypes.byref(attributes), 0):
        _fail("CreatePipe")
    # The read end is the parent's and is not the child's business.
    _kernel32.SetHandleInformation(read_end, 0x00000001, 0)   # HANDLE_FLAG_INHERIT off

    devnull = _kernel32.CreateFileW("NUL", 0x80000000, 3, ctypes.byref(attributes),
                                    3, 0, None)
    if devnull in (None, INVALID_HANDLE_VALUE):
        _fail("CreateFileW(NUL)")

    # Two attributes: the handle list, and the child-process policy.
    size = ctypes.c_size_t(0)
    _kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    attribute_list = ctypes.create_string_buffer(size.value)
    if not _kernel32.InitializeProcThreadAttributeList(attribute_list, 2, 0,
                                                       ctypes.byref(size)):
        _fail("InitializeProcThreadAttributeList")

    # Exactly two handles cross: a `NUL` the child may read and a pipe it may
    # write a transcript into. Without this list `bInheritHandles=TRUE` would
    # hand over every inheritable handle this process happens to hold.
    #
    # The pipe is the one writable handle and it is deliberate. A file inside the
    # output directory would be a handle to an object the child can already open
    # for itself, which reads better against "no inherited writable handles" --
    # and it would also be a transcript the child can rewrite at any point before
    # it exits, including after the failure it wants to hide. A pipe's only
    # capability is appending bytes to a buffer this process reads as untrusted
    # text, and what has been read cannot be taken back.
    inherited = (wintypes.HANDLE * 2)(devnull, write_end)
    if not _kernel32.UpdateProcThreadAttribute(
            attribute_list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherited,
            ctypes.sizeof(inherited), None, None):
        _fail("UpdateProcThreadAttribute(HANDLE_LIST)")

    # D12. The candidate creates no processes at all. Everything downstream of
    # this -- the job object, the survivor count, the drain to zero -- bounds a
    # process that already exists; this is the refusal that happens instead of
    # one existing. It is inherited by nothing, because there is nothing to
    # inherit it: the policy is on the one process the boundary starts, and that
    # process may not start another.
    policy = wintypes.DWORD(PROCESS_CREATION_CHILD_PROCESS_RESTRICTED)
    if not _kernel32.UpdateProcThreadAttribute(
            attribute_list, 0, PROC_THREAD_ATTRIBUTE_CHILD_PROCESS_POLICY,
            ctypes.byref(policy), ctypes.sizeof(policy), None, None):
        _fail("UpdateProcThreadAttribute(CHILD_PROCESS_POLICY)")

    startup = _STARTUPINFOEXW()
    startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    startup.StartupInfo.hStdInput = devnull
    startup.StartupInfo.hStdOutput = write_end
    startup.StartupInfo.hStdError = write_end
    startup.lpAttributeList = ctypes.cast(attribute_list, ctypes.c_void_p)

    information = _PROCESS_INFORMATION()
    block = _environment_block(env)
    # An audit event, because `subprocess.Popen` raises one and
    # `CreateProcessAsUserW` through ctypes raises nothing. `DIRECT` creating
    # zero processes is a release gate, and a gate proven by monkeypatching two
    # module attributes only covers process creation reached through those two
    # names. `test_isolation.DirectIsExemptTest` listens for this.
    sys.audit(AUDIT_SPAWN, argv[0], len(argv))
    # `lpApplicationName` is the executable, named separately, so the command
    # line is never parsed to decide which program runs.
    created = _advapi32.CreateProcessAsUserW(
        token, argv[0], ctypes.create_unicode_buffer(command_line(argv)), None, None,
        True,
        (CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | DETACHED_PROCESS
         | CREATE_NEW_PROCESS_GROUP | EXTENDED_STARTUPINFO_PRESENT),
        block, str(cwd), ctypes.byref(startup.StartupInfo), ctypes.byref(information))
    if not created:
        code = ctypes.get_last_error()
        for handle in (read_end, write_end, devnull, job, token):
            _kernel32.CloseHandle(handle)
        _kernel32.DeleteProcThreadAttributeList(attribute_list)
        raise ConfinementUnavailable(
            f"CreateProcessAsUserW failed with Windows error {code}: "
            f"{ctypes.FormatError(code)}")

    _kernel32.DeleteProcThreadAttributeList(attribute_list)
    child_pid = information.dwProcessId
    # The parent's copies of the child's ends. Held open, the pipe never reports
    # end-of-file and the reader thread never returns.
    _kernel32.CloseHandle(write_end)
    _kernel32.CloseHandle(devnull)

    chunks: list[bytes] = []
    try:
        # Suspended until it is inside the job. The window is not a race: a
        # suspended process has executed no instruction, so there is nothing it
        # can do in it. If it cannot be put in the job it is killed here rather
        # than resumed, because `KILL_ON_JOB_CLOSE` only reaches what is in the
        # job and a suspended process nobody resumes is a leak either way.
        if not _kernel32.AssignProcessToJobObject(job, information.hProcess):
            _kernel32.TerminateProcess(information.hProcess, 1)
            _fail("AssignProcessToJobObject")

        reader = threading.Thread(target=_drain, args=(read_end, chunks), daemon=True)
        reader.start()

        if _kernel32.ResumeThread(information.hThread) == 0xFFFFFFFF:
            _fail("ResumeThread")

        waited = _kernel32.WaitForSingleObject(
            information.hProcess, int(max(timeout, 0.0) * 1000))
        timed_out = waited == WAIT_TIMEOUT

        returncode: int | None = None
        if not timed_out:
            code = wintypes.DWORD()
            if _kernel32.GetExitCodeProcess(information.hProcess, ctypes.byref(code)):
                returncode = int(code.value)

        # By id and not by count, and after a settle rather than at the instant
        # the child exited. A candidate that spawned something to outlive the
        # build is still in the job at the end of this; Windows' own transient
        # `conhost.exe` is not. "The build finished" and "the build's processes
        # finished" are two different facts, and the second is the one the
        # grandchild attack turned on.
        settle = time.monotonic() + SURVIVOR_GRACE_S
        while True:
            others = [pid for pid in _process_ids(job) if pid != child_pid]
            if not others or time.monotonic() > settle:
                break
            time.sleep(0.02)
        survivors = len(others)
        _kernel32.TerminateJobObject(job, 1)

        # Released before the wait below, and this ordering cost a false positive
        # on the first honest build: a job keeps counting a process until its
        # last *handle* closes, so waiting for zero while still holding the
        # child's handle waits forever.
        _kernel32.CloseHandle(information.hThread)
        _kernel32.CloseHandle(information.hProcess)
        information.hThread = information.hProcess = None

        deadline = time.monotonic() + 30.0
        while _active_processes(job) > 0:
            if time.monotonic() > deadline:       # pragma: no cover - kernel refused
                raise ConfinementUnavailable(
                    "the job object still reports live processes 30 s after "
                    "TerminateJobObject; nothing may be read out of the build "
                    "directory while anything can still write to it")
            time.sleep(0.01)

        reader.join(timeout=5.0)
    finally:
        # Closing the job is the second net: `KILL_ON_JOB_CLOSE` fires here even
        # if `TerminateJobObject` was never reached.
        for handle in (information.hThread, information.hProcess, job, token,
                       read_end):
            if handle:
                _kernel32.CloseHandle(handle)

    return Confined(
        returncode=returncode,
        output=b"".join(chunks).decode("utf-8", "replace"),
        timed_out=timed_out,
        seconds=time.perf_counter() - started,
        pid=int(child_pid),
        survivors=survivors)
