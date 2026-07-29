"""Setuptools hook for the production wheel.

The repository keeps the pipeline tests beside the runtime modules so that the
source checkout can run them without a second test package.  They are not part
of the installed Python surface, however.  The `.skill` archive has its own
explicit file filter; this hook applies the same policy to the wheel.
"""
from __future__ import annotations

from setuptools import setup
from setuptools.command.build_py import build_py


class ProductionBuildPy(build_py):
    """Do not copy test modules into the runtime wheel."""

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [
            (pkg, module, path)
            for pkg, module, path in modules
            if not module.startswith("test_") and not module.endswith("_test")
        ]


setup(cmdclass={"build_py": ProductionBuildPy})
