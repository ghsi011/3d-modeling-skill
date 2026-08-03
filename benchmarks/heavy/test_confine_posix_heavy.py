"""What the Linux confinement actually enforces, re-measured rather than asserted.

`pipeline/confine_posix.py` makes four claims. Every one of them is a claim
about the kernel, and a comment saying the kernel does something is worth
nothing -- `docs/defects.md` D11 is the record of what happens when a boundary's
documentation outruns its measurement: the Windows implementation claimed a
restricted token refused `socket.connect`, on the strength of a probe against a
port a local filter happened to block, and the network had been open the whole
time.

So each test here *runs a real confined child* and has it try the thing, then
asserts on what the kernel did to it. The child is a small script written into
the sandbox, not a mock -- what is being tested is the boundary, and a mock of
the boundary would be testing this file against itself.

Heavy rather than L0 for the ordinary reason: every one of these pays for a
fresh interpreter behind the boundary, about 1.7 s each on the reference
machine, and `conftest.py` keeps that out of the commit gate.
"""
from __future__ import annotations

import errno
import json
import os
import tempfile
import time
import textwrap
import unittest
from pathlib import Path

from pipeline import confine
from pipeline import confine_posix as CP

REASON = CP.unavailable_reason()


def _run(body: str, *, timeout: float = 60.0) -> tuple[CP.Confined, dict]:
    """Run `body` inside the boundary and return what it reported.

    The script writes its findings as JSON into the one directory it is allowed
    to write, which is also a test of that directory being writable: a body that
    could not write would produce no findings and fail every assertion below for
    the wrong reason, so `probe.json` existing is itself part of the measurement.
    """
    with tempfile.TemporaryDirectory() as raw:
        sandbox = Path(raw)
        build = sandbox / "build"
        build.mkdir()
        script = sandbox / "probe.py"
        script.write_text(textwrap.dedent(f"""
            import json, os, socket, sys
            from pathlib import Path
            BUILD = Path(sys.argv[1])
            found = {{}}
            def check(name, fn):
                try:
                    fn()
                    found[name] = "ALLOWED"
                except BaseException as exc:
                    found[name] = f"{{type(exc).__name__}}:{{getattr(exc,'errno',None)}}"
            {textwrap.indent(textwrap.dedent(body), '            ').strip()}
            (BUILD / "probe.json").write_text(json.dumps(found))
        """), encoding="utf-8")
        confine.seal_read_only(script)
        confine.seal_writable(build)
        result = confine.run([os.sys.executable, str(script), str(build)],
                             cwd=build, env={"PATH": "/usr/bin:/bin"},
                             timeout=timeout)
        probe = build / "probe.json"
        found = json.loads(probe.read_text(encoding="utf-8")) if probe.is_file() else {}
        confine.unseal(sandbox)
        return result, found


@unittest.skipIf(REASON is not None, f"the Linux boundary is unavailable: {REASON}")
class WhatTheLinuxConfinementEnforcesTest(unittest.TestCase):

    def test_the_only_writable_place_is_the_build_directory(self) -> None:
        """Property 1, and the failure is the filesystem's rather than a check.

        `EROFS` specifically. A `PermissionError` would mean a permission bit
        refused the write, which is a different and weaker statement: it depends
        on who the candidate is, and `EROFS` does not.
        """
        repo = Path(__file__).resolve().parents[2]
        result, found = _run(f"""
            check("build", lambda: (BUILD / "ok").write_text("y"))
            check("repo", lambda: Path({str(repo)!r}, "CANARY").write_text("x"))
            check("sitepkgs", lambda: Path(
                {str(repo / '.venv')!r}, "evil.py").write_text("x"))
            check("tmp", lambda: Path("/tmp/evil").write_text("x"))
            check("etc", lambda: Path("/etc/evil").write_text("x"))
            check("home", lambda: Path("/root/evil").write_text("x"))
        """)
        self.assertEqual("ALLOWED", found.get("build"),
                         "the one writable hole must actually be writable")
        for where in ("repo", "sitepkgs", "tmp", "etc", "home"):
            with self.subTest(where=where):
                self.assertEqual(f"OSError:{errno.EROFS}", found.get(where),
                                 f"{where} must be refused by the read-only "
                                 "mount, with EROFS rather than a permission bit")
        self.assertEqual(0, result.survivors)

    def test_the_network_is_absent_rather_than_filtered(self) -> None:
        """Property 2, and the thing the Windows boundary cannot claim.

        `ENETUNREACH` is the assertion, not "the connection failed". D11's whole
        lesson is that a connection failing proves nothing about a boundary:
        something else on the machine may be refusing it. An unreachable network
        is the kernel saying there is no route because there is no interface.
        """
        _, found = _run("""
            check("connect", lambda: socket.create_connection(("1.1.1.1", 443), 5))
            check("dns", lambda: socket.gethostbyname("example.com"))
            check("udp", lambda: socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM).connect(("8.8.8.8", 53)))
        """)
        self.assertEqual("OSError:101", found.get("connect"),
                         "ENETUNREACH: there is no interface, not a filtered port")
        self.assertEqual("OSError:101", found.get("udp"))
        self.assertTrue(str(found.get("dns", "")).startswith("gaierror"),
                        f"DNS must not resolve: {found.get('dns')}")

    def test_a_candidate_cannot_unmake_the_boundary_it_is_inside(self) -> None:
        """The capability drop, which is what stops property 1 being undone.

        A candidate that kept `CAP_SYS_ADMIN` would be root inside its own mount
        namespace and could simply remount it read-write. This is the test that
        the drop happened, and it asserts on the capability set as well as on the
        refusal -- a `mount` that failed for some other reason would pass a test
        that only looked at the exception.
        """
        repo = Path(__file__).resolve().parents[2]
        _, found = _run(f"""
            import ctypes
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            found["caps"] = open("/proc/self/status").read().split(
                "CapEff:")[1].split()[0]
            MS_REMOUNT, MS_BIND = 32, 4096
            def remount():
                if libc.mount(None, b"/", None,
                              ctypes.c_ulong(MS_REMOUNT | MS_BIND), None) != 0:
                    raise OSError(ctypes.get_errno(), "mount refused")
            check("remount_root", remount)

            # The one way back to CAP_SYS_ADMIN that does not need to hold it
            # first: a new user namespace grants a full capability set *within
            # itself*. The kernel's answer is that mounts inherited from an
            # ancestor namespace are locked, so the capability is real and there
            # is nothing in reach to use it on. Measured rather than trusted.
            def newuserns():
                if libc.unshare(0x10000000 | 0x00020000) != 0:
                    raise OSError(ctypes.get_errno(), "unshare refused")
            check("new_user_namespace", newuserns)
            found["caps_after_userns"] = open("/proc/self/status").read().split(
                "CapEff:")[1].split()[0]
            check("remount_after_userns", remount)
            check("write_repo_after_userns",
                  lambda: Path({str(repo)!r}, "CANARY").write_text("x"))
        """)
        self.assertEqual("0000000000000000", found.get("caps"),
                         "the candidate must hold no effective capability")
        self.assertEqual("PermissionError:1", found.get("remount_root"),
                         "remounting / must be refused with EPERM -- no "
                         "CAP_SYS_ADMIN is what makes property 1 un-undoable")
        # Whether a new user namespace can be created at all is the kernel's
        # choice and not this boundary's, so it is recorded rather than
        # asserted. What is asserted is that it buys nothing: the capability
        # set inside it may be full, and the mount stays read-only regardless,
        # because a mount inherited from an ancestor namespace is locked.
        self.assertEqual("PermissionError:1", found.get("remount_after_userns"),
                         f"a candidate that reached a user namespace "
                         f"(caps {found.get('caps_after_userns')}) still may not "
                         "remount the tree it inherited")
        self.assertEqual(f"OSError:{errno.EROFS}",
                         found.get("write_repo_after_userns"),
                         "and the repository is still read-only afterwards")

    def test_nothing_the_candidate_starts_outlives_the_run(self) -> None:
        """Property 3, measured on a grandchild that actively tries to survive.

        `setsid()` detaches it from the process group, which on a system with no
        PID namespace is enough to outlive the parent -- that is exactly how the
        original Windows incident happened, a `DETACHED_PROCESS` grandchild that
        rewrote `final_status.json` 25 s after the run reported FAILED. Here the
        namespace's init exiting is what kills it, and the kernel offers nothing
        that opts out.
        """
        with tempfile.TemporaryDirectory() as raw:
            sandbox = Path(raw)
            build = sandbox / "build"
            build.mkdir()
            script = sandbox / "probe.py"
            # os.fork rather than a spawn: the syscall filter is not installed on
            # this path (the parent has not handed over to `build_child`), so this
            # measures the namespace and not the filter.
            script.write_text(textwrap.dedent("""
                import os, sys, time
                from pathlib import Path
                build = Path(sys.argv[1])
                if os.fork() == 0:
                    os.setsid()
                    (build / "started").write_text("1")
                    time.sleep(20)
                    (build / "SURVIVED").write_text("the boundary failed")
                    os._exit(0)
                time.sleep(0.4)
                os._exit(0)
            """), encoding="utf-8")
            confine.seal_writable(build)
            result = confine.run([os.sys.executable, str(script), str(build)],
                                 cwd=build, env={"PATH": "/usr/bin:/bin"},
                                 timeout=60.0)
            self.assertTrue((build / "started").is_file(),
                            "the grandchild must actually have run, or this "
                            "measures nothing")
            self.assertEqual(1, result.survivors,
                             "a process that tried to outlive the run is a "
                             "finding, and must be counted before it is killed")
            # The whole point: by the time `run` returned there is nothing left
            # anywhere that could still be writing into the build directory.
            self.assertFalse((build / "SURVIVED").is_file())
            time.sleep(1.0)
            self.assertFalse((build / "SURVIVED").is_file(),
                             "and it is still gone a second later")
            confine.unseal(sandbox)

    def test_a_timeout_kills_the_whole_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sandbox = Path(raw)
            build = sandbox / "build"
            build.mkdir()
            script = sandbox / "probe.py"
            script.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")
            confine.seal_writable(build)
            result = confine.run([os.sys.executable, str(script)], cwd=build,
                                 env={"PATH": "/usr/bin:/bin"}, timeout=2.0)
            self.assertTrue(result.timed_out)
            self.assertIsNone(result.returncode)
            self.assertLess(result.seconds, 30.0)
            confine.unseal(sandbox)


@unittest.skipIf(REASON is not None, f"the Linux boundary is unavailable: {REASON}")
class TheSyscallFilterTest(unittest.TestCase):
    """Property 4, which is installed by the child rather than by the parent."""

    def test_after_seal_syscalls_nothing_can_be_executed(self) -> None:
        _, found = _run("""
            from pipeline import confine as C
            check("exec_before", lambda: os.posix_spawn(
                "/bin/true", ["/bin/true"], {}))
            C.seal_syscalls()
            check("exec_after", lambda: os.posix_spawn(
                "/bin/true", ["/bin/true"], {}))
            check("execv_after", lambda: os.execv("/bin/true", ["/bin/true"]))
            check("still_writable", lambda: (BUILD / "after").write_text("y"))
            import trimesh
            check("still_builds", lambda: trimesh.creation.box(
                extents=(10, 10, 10)).export(str(BUILD / "box.stl")))
        """)
        self.assertEqual("PermissionError:1", found.get("exec_after"),
                         "execve must be refused with EPERM once sealed")
        self.assertEqual("PermissionError:1", found.get("execv_after"))
        # And the filter must not have broken the thing the child is for.
        self.assertEqual("ALLOWED", found.get("still_writable"))
        self.assertEqual("ALLOWED", found.get("still_builds"))

    def test_the_filter_is_installed_before_any_candidate_byte_runs(self) -> None:
        """Read off `build_child.py` rather than inferred.

        The ordering is the property: `seal_syscalls` has to come after this
        package's own imports have resolved and before `authored.load`, which is
        the call that imports the candidate. A test that only checked the filter
        works would pass with the call in the wrong place.
        """
        source = (Path(__file__).resolve().parents[2] / "skills" / "3d-modeling"
                  / "scripts" / "pipeline" / "build_child.py"
                  ).read_text(encoding="utf-8")
        sealed = source.index("seal_syscalls()")
        loaded = source.index("A.load(model_path)")
        self.assertLess(sealed, loaded,
                        "the syscall filter must be installed before the "
                        "candidate module is imported")


if __name__ == "__main__":
    unittest.main()
