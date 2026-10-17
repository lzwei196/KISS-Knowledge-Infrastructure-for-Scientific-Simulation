"""Strict fresh-KI path projections; never retained maintenance or readiness.

Fresh and retained repairs share the strict source recognizer, while their
proof scopes and policy identities remain distinct.
"""
from __future__ import annotations
import ast
import copy
import hashlib
import os
from pathlib import Path
import re
import sys

from . import ki_path_contracts as retained
from .ki_path_contracts import (PREFLIGHT, MANIFEST, RUNNER, PREFLIGHT_AST_SHA256S,
    RUNNER_AST_SHA256, _CHANGED_NAMES, _ordinary, _inputs, _target, _recognized,
    _replace_rhs, _manifest, _helper_config, _config_values, _file_identity,
    _ast_value, _assignments, _hash, config_identity, projection_config)

FRESH_POLICY = "wofost-fresh-runtime-paths-v1"


def source_digest():
    from . import implementation_identity, port
    return _hash({"fresh_module": implementation_identity.module_digest(sys.modules[__name__]),
                  "retained_contract": retained.source_digest(),
                  "ordinary_port": implementation_identity.module_digest(port)})


def fresh_applicable(base, name):
    """A WOFOST package must match the supported contract or fail explicitly."""
    return name == "WOFOST"


def _fresh_inputs(base, cfg):
    """Predict exactly the existing port.materialise text-write contract.

    port reads universal-newline text, retains original bytes when nothing
    changes, and uses native newlines when it writes substituted text. This
    differs from the retained maintenance projection, which preserves bytes.
    Tests compare this prediction to real port.materialise on LF and CRLF.
    """
    from . import port
    raw = {name: _ordinary(Path(base) / name) for name in (PREFLIGHT, MANIFEST, RUNNER)}
    _inputs(base, cfg)  # Whole published AST and exact role bindings first.
    projected = {}
    for name, value in raw.items():
        text = value.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        result, _, unresolved = port.unsubstitute(text, cfg)
        if unresolved:
            raise ValueError("Fresh path projection has unresolved roles")
        projected[name] = value if result == text else result.replace("\n", os.linesep).encode("utf-8")
    return projected


def expected_fresh_changes(base, name, cfg, *, target_root):
    """Strict supported overlay; unknown published WOFOST fails explicitly."""
    if not fresh_applicable(base, name):
        return {}
    target = _target(cfg, target_root)
    inputs = _fresh_inputs(base, cfg)
    _, tree, _ = _recognized(inputs[PREFLIGHT], cfg)
    return {PREFLIGHT: _replace_rhs(inputs[PREFLIGHT], tree, cfg),
            MANIFEST: _manifest(inputs[MANIFEST], cfg, target)}


def _fresh_runtime(cfg):
    """Bind real runtime resources without looking for a future KI runner."""
    from . import helper_identity
    config_digest = config_identity(cfg)
    helper = Path(cfg.roles["ki_tools_common"])
    binding, files, legacy = helper_identity.checked_marker(helper)
    if legacy:
        raise ValueError("Fresh path projection requires a current source-bound helper marker")
    _helper_config(binding, cfg)
    return {"config_sha256": config_digest, "config": _config_values(cfg),
            "selected_python": _file_identity(Path(cfg.python)),
            "helper_root": str(helper), "helper_binding": binding, "helper_files": files,
            "helper_marker": _file_identity(helper / helper_identity.MARKER)}


def _tree_digest(root):
    from . import ki_tree
    result = ki_tree.digest(Path(root))
    if not result:
        raise ValueError("Fresh projection tree identity is unavailable")
    return result


def tree_files(root):
    """Content inventory of the real ordinary copy, including links/directories."""
    from . import ki_tree
    root = Path(root)
    inventory = ki_tree.scan(root)
    result, total = {}, 0
    for entry in inventory.entries:
        row = {"kind": entry.kind}
        if entry.kind == "link":
            row["target"] = entry.target
        elif entry.kind == "file":
            digest, size = hashlib.sha256(), 0
            with (root / entry.relative).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    size += len(chunk)
                    total += len(chunk)
                    if total > ki_tree.MAX_BYTES:
                        raise ValueError("Fresh projection inventory exceeds its bounded size")
                    digest.update(chunk)
            row.update(bytes=size, sha256=digest.hexdigest())
        result[entry.relative] = row
    return result


def validate_fresh_projection(base, candidate, cfg, *, target_root, ordinary_digest, ordinary_files):
    """Static staged proof, separate from retained repair/current readiness.

    The KI projection host additionally compares the whole ordinary inventory
    before and after the two-file overlay; its digest records that baseline.
    A physical candidate can be temporary. Its manifest names only the exact
    logical target, which need not exist and is never inspected as evidence.
    """
    base, candidate = Path(base).absolute(), Path(candidate).absolute()
    if base == candidate or base in candidate.parents or candidate in base.parents:
        raise ValueError("Fresh path source and candidate must be separate trees")
    if not isinstance(ordinary_digest, str) or re.fullmatch("[0-9a-f]{64}", ordinary_digest) is None:
        raise ValueError("Fresh path projection requires its ordinary tree identity")
    changes = expected_fresh_changes(base, "WOFOST", cfg, target_root=target_root)
    if not changes:
        raise ValueError("No supported fresh WOFOST path contract")
    inputs = _fresh_inputs(base, cfg)
    for name, expected in {**changes, RUNNER: inputs[RUNNER]}.items():
        if _ordinary(candidate / name) != expected:
            raise ValueError("Fresh candidate differs from the exact supported path projection")
    if not isinstance(ordinary_files, dict):
        raise ValueError("Fresh projection lacks its actual ordinary file inventory")
    wanted = copy.deepcopy(ordinary_files)
    for name, value in changes.items():
        if name not in wanted or wanted[name].get("kind") != "file":
            raise ValueError("Ordinary projection lacks a supported path file")
        if wanted[name] != {"kind": "file", "bytes": len(inputs[name]),
                            "sha256": hashlib.sha256(inputs[name]).hexdigest()}:
            raise ValueError("Ordinary file differs from the source's exact port projection")
        wanted[name] = {"kind": "file", "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    if tree_files(candidate) != wanted:
        raise ValueError("Fresh path overlay changed files outside its exact two-file scope")
    _, before, recognized = _recognized(inputs[PREFLIGHT], cfg)
    after = ast.parse(changes[PREFLIGHT].decode("utf-8"))
    old_names = _assignments(before)
    for name, node in _assignments(after).items():
        if name in _CHANGED_NAMES:
            node.value = copy.deepcopy(old_names[name].value)
    if _ast_value(after) != _ast_value(before):
        raise ValueError("Fresh path projection changed preflight decisions")
    return {"ok": True, "policy": FRESH_POLICY, "policy_sha256": source_digest(),
            "scope": "fresh_path_projection", "runtime_bound": False,
            "physical_root": str(candidate), "logical_target": str(_target(cfg, target_root)),
            "source_root": str(base), "source_digest": _tree_digest(base),
            "ordinary_digest": ordinary_digest, "candidate_digest": _tree_digest(candidate),
            "ordinary_files": ordinary_files,
            "runtime": _fresh_runtime(cfg), "model_execution": False, "native_execution": False,
            "scientific_validation": False, "preflight_passed": False,
            "recognized_ast_sha256": recognized, "runner_ast_sha256": RUNNER_AST_SHA256,
            "unchanged_decisions_sha256": _hash(_ast_value(before)),
            "source_files": {name: hashlib.sha256(_ordinary(base / name)).hexdigest()
                             for name in (PREFLIGHT, MANIFEST, RUNNER)},
            "candidate_files": {name: hashlib.sha256(_ordinary(candidate / name)).hexdigest()
                                for name in (PREFLIGHT, MANIFEST, RUNNER)}}


def require_fresh_current(report, *, candidate_root=None):
    """Recheck staged structural proof, never upgrade it to an active receipt."""
    if (not isinstance(report, dict) or report.get("ok") is not True
            or report.get("policy") != FRESH_POLICY or report.get("policy_sha256") != source_digest()
            or report.get("scope") != "fresh_path_projection" or report.get("runtime_bound") is not False
            or not isinstance(report.get("recognized_ast_sha256"), str)
            or report.get("recognized_ast_sha256") not in PREFLIGHT_AST_SHA256S
            or report.get("runner_ast_sha256") != RUNNER_AST_SHA256
            or any(report.get(key) is not False for key in
                   ("model_execution", "native_execution", "scientific_validation", "preflight_passed"))):
        raise ValueError("A current static fresh-path projection report is required")
    try:
        cfg = projection_config(report)
        logical = _target(cfg, report["logical_target"])
        physical = Path(report["physical_root"])
        current = physical if candidate_root is None else Path(candidate_root).absolute()
        if not physical.is_absolute() or current not in (physical, logical):
            raise ValueError("Fresh proof belongs to another candidate/target")
        if _fresh_runtime(cfg) != report["runtime"]:
            raise ValueError("Fresh projection runtime/helper identity changed")
        for key in ("source_digest", "ordinary_digest", "candidate_digest", "unchanged_decisions_sha256"):
            if not isinstance(report[key], str) or re.fullmatch("[0-9a-f]{64}", report[key]) is None:
                raise ValueError("Fresh projection tree/decision identity is incomplete")
        source = Path(report["source_root"])
        if (not source.is_absolute() or _tree_digest(source) != report["source_digest"]
                or _tree_digest(current) != report["candidate_digest"]):
            raise ValueError("Fresh projection source or candidate tree changed")
        reproduced = validate_fresh_projection(source, current, cfg, target_root=logical,
                                               ordinary_digest=report["ordinary_digest"],
                                               ordinary_files=report["ordinary_files"])
        reproduced["physical_root"] = report["physical_root"]
        if reproduced != report:
            raise ValueError("Fresh projection proof no longer reproduces exactly")
    except (OSError, KeyError, TypeError) as error:
        raise ValueError("Fresh projection proof is incomplete or its files changed") from error

