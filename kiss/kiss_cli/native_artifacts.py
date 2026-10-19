"""Classify exact host-verified engine links as execution material, never results.

This consumes an in-process runtime capability. Plan/request JSON and project
data tools cannot grant an external path or exempt an arbitrary output link.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import runtime_arguments


def capture(project, ki, outputs, *, before, authorization, arguments, cwd,
            input_snapshot, policy):
    """Return ordinary outputs and a copied input snapshot with signed aliases."""
    from .flowgate import load
    receipts = load().receipts
    if authorization is None:
        return outputs, input_snapshot
    if not isinstance(authorization, receipts.RuntimeArgumentCapture):
        raise ValueError("Execution aliases require the host runtime capability")
    rows = authorization.checked_bindings(project, arguments, cwd)
    if not authorization.expected_files:
        return outputs, input_snapshot
    if not isinstance(input_snapshot, dict):
        raise ValueError("Execution aliases require captured runtime inputs")
    coverage = input_snapshot.get("input_coverage") or {}
    if coverage.get("runtime_arguments") != rows:
        raise ValueError("Execution aliases differ from captured runtime authority")
    expected = {target: (size, digest) for target, size, digest in authorization.expected_files}
    engines = {row["target"]: row for row in rows
               if runtime_arguments._runtime_option(row["option"], ki)}
    project = Path(project).resolve()
    aliases, ordinary = [], []
    for output in outputs:
        path = Path(os.path.abspath(output))
        target = str(path.resolve())
        if (not path.is_symlink() or path.suffix.casefold() not in {"", ".exe"}
                or target not in engines or target not in expected):
            ordinary.append(output)
            continue
        # Existing links are not newly created execution material. Do not
        # relabel any existing result or grant paths outside tracked outputs.
        if str(path) in before:
            ordinary.append(output)
            continue
        relative = path.relative_to(project).as_posix()
        policy._execution_alias_path(project, relative)
        row = engines[target]
        size, digest = expected[target]
        aliases.append({"path": relative, "target": target, "bytes": size,
                        "sha256": digest, "argument_index": row["argument_index"],
                        "option": row["option"], "runtime_path": row["path"],
                        "link_text": os.readlink(path)})
    if not aliases:
        return outputs, input_snapshot
    snapshot = {**input_snapshot, "input_coverage": {**coverage,
                "runtime_executable_aliases": aliases}}
    errors = policy.execution_alias_errors(project, {
        "ki": ki, "inputs": snapshot["inputs"], "input_coverage": snapshot["input_coverage"]})
    if errors:
        raise ValueError("; ".join(errors))
    # Check the original executable/MPI aliases and bytes once more after the
    # newly created links have been inspected. Never infer authority from argv.
    authorization.checked_bindings(project, arguments, cwd)
    return ordinary, snapshot
