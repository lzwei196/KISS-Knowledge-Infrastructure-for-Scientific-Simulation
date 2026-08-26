"""PyInstaller entry point.

kiss_cli/__main__.py uses a relative import, which works under `python -m
kiss_cli` but not when PyInstaller executes it as a top-level script — frozen
scripts have no parent package, so `from .cli import main` raises ImportError.
Caught by building locally before shipping the workflow. This absolute-import
shim exists solely for the frozen build; `python -m kiss_cli` stays canonical.
"""
import sys


def _reach_bundled_libraries() -> None:
    """Put the bundled ``ki_tools_common`` package on the import path.

    ``--add-data "ki_tools_common:ki_tools_common"`` copies the *repository*
    folder, because an install pip-installs it and needs the pyproject.toml
    beside it. That leaves the importable package one level deeper than the
    name suggests:

        sys._MEIPASS/ki_tools_common/                          <- on sys.path
        sys._MEIPASS/ki_tools_common/ki_tools_common/harness/  <- the package

    So ``import ki_tools_common`` resolved to the outer directory as a
    namespace package and ``ki_tools_common.harness`` did not exist. Bundled is
    not the same as reachable.
    """
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return                      # from source, the environment resolves it
    import os
    inner = os.path.join(base, "ki_tools_common")
    if os.path.isdir(os.path.join(inner, "ki_tools_common")) and inner not in sys.path:
        sys.path.insert(0, inner)


_reach_bundled_libraries()

from kiss_cli.cli import main

raise SystemExit(main())
