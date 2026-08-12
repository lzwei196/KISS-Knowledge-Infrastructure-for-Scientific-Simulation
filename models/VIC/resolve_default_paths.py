#!/usr/bin/env python3
"""
resolve_default_paths.py
=========================

Centralized, host-portable default-path resolver for the VIC KI.

Replaces hard-coded literals such as ``/Volumes/Expansion2t`` (macOS host)
and ``/Users/yc`` (per-user macOS home) that previously appeared in
``check_data.py`` and ``run_vic_pipeline_enhanced.py``. Callers obtain a
case root and four conventional subdirectories (forcing / soil / veg /
output) without baking any single host's filesystem layout into source.

Resolution order for ``case_root`` (first existing directory wins):

    1. Explicit ``case_root`` argument passed to the function.
    2. ``$VIC_CASE_ROOT`` environment variable.
    3. ``$KDT_CASE_ROOT`` environment variable.
    4. The current working directory.

If none of the four candidates points to an existing directory, a
``FileNotFoundError`` is raised whose message lists every candidate that
was tried (including unset env vars, which are reported as ``<unset>``)
so the caller can act on the diagnostic without re-running.

Subdirectory names default to ``forcing`` / ``soil`` / ``veg`` /
``output`` but each can be overridden via keyword argument. Subdirs are
*not* required to exist — they are merely joined onto ``case_root``,
so this resolver is safe to call before a case has been fully
provisioned.

CLI
---
Run as a script to print the resolved dictionary as JSON, which is
convenient for shell pipelines and smoke tests::

    python3 resolve_default_paths.py                       # use env/CWD
    python3 resolve_default_paths.py --case-root /tmp/case # explicit
    VIC_CASE_ROOT=/data/vic python3 resolve_default_paths.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


_ENV_VARS = ("VIC_CASE_ROOT", "KDT_CASE_ROOT")


def _candidate_roots(case_root: str | None) -> list[tuple[str, str | None]]:
    """Build the ordered list of (source-label, path-or-None) candidates."""
    return [
        ("explicit arg",        case_root),
        ("$VIC_CASE_ROOT",      os.environ.get("VIC_CASE_ROOT")),
        ("$KDT_CASE_ROOT",      os.environ.get("KDT_CASE_ROOT")),
        ("current working dir", os.getcwd()),
    ]


def resolve_default_paths(
    case_root: str | None = None,
    *,
    forcing_subdir: str = "forcing",
    soil_subdir: str = "soil",
    veg_subdir: str = "veg",
    output_subdir: str = "output",
) -> dict[str, str]:
    """Resolve VIC default paths in a host-portable way.

    Parameters
    ----------
    case_root
        Explicit case-root path. If ``None``, fall back to environment
        variables and finally CWD as documented in the module docstring.
    forcing_subdir, soil_subdir, veg_subdir, output_subdir
        Subdirectory names under ``case_root``. Override only when the
        case layout deviates from the KI convention.

    Returns
    -------
    dict[str, str]
        Mapping with keys ``case_root``, ``forcing_dir``, ``soil_dir``,
        ``veg_dir``, ``output_dir`` — all as absolute string paths.

    Raises
    ------
    FileNotFoundError
        If none of the four candidate roots resolves to an existing
        directory. The exception message lists every candidate tried.
    """
    candidates = _candidate_roots(case_root)

    chosen: Path | None = None
    for _label, value in candidates:
        if value is None or value == "":
            continue
        path = Path(value).expanduser()
        if path.is_dir():
            chosen = path.resolve()
            break

    if chosen is None:
        # Build an actionable diagnostic that names every candidate.
        lines = ["Could not resolve a VIC case root. Tried:"]
        for label, value in candidates:
            shown = value if value not in (None, "") else "<unset>"
            lines.append(f"  - {label:<22s} -> {shown}")
        lines.append(
            "Pass an existing directory via --case-root, or export "
            "VIC_CASE_ROOT / KDT_CASE_ROOT to point at one."
        )
        raise FileNotFoundError("\n".join(lines))

    return {
        "case_root":   str(chosen),
        "forcing_dir": str(chosen / forcing_subdir),
        "soil_dir":    str(chosen / soil_subdir),
        "veg_dir":     str(chosen / veg_subdir),
        "output_dir":  str(chosen / output_subdir),
    }


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="resolve_default_paths",
        description=(
            "Resolve VIC KI default paths from explicit arg, "
            "$VIC_CASE_ROOT, $KDT_CASE_ROOT, or CWD (in that order). "
            "Prints the result as JSON."
        ),
    )
    p.add_argument(
        "--case-root",
        default=None,
        help="Explicit case-root directory (highest priority).",
    )
    p.add_argument("--forcing-subdir", default="forcing")
    p.add_argument("--soil-subdir",    default="soil")
    p.add_argument("--veg-subdir",     default="veg")
    p.add_argument("--output-subdir",  default="output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    try:
        paths = resolve_default_paths(
            case_root=args.case_root,
            forcing_subdir=args.forcing_subdir,
            soil_subdir=args.soil_subdir,
            veg_subdir=args.veg_subdir,
            output_subdir=args.output_subdir,
        )
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    json.dump(paths, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
