"""PyInstaller entry point.

kiss_cli/__main__.py uses a relative import, which works under `python -m
kiss_cli` but not when PyInstaller executes it as a top-level script — frozen
scripts have no parent package, so `from .cli import main` raises ImportError.
Caught by building locally before shipping the workflow. This absolute-import
shim exists solely for the frozen build; `python -m kiss_cli` stays canonical.
"""
from kiss_cli.cli import main

raise SystemExit(main())
