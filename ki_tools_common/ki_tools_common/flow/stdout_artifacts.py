"""Explicit stdout JSON artifacts for shipped KI checks, never model evidence.

The size limit bounds a persisted artifact after the existing process collector
returns. It is not a streaming or process-memory limit. Text-mode collection
normalizes newlines; the artifact preserves the complete decoded stdout text.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re

POLICY = "ki-check-stdout-json-v1"
MAX_BYTES = 1_048_576
FIELDS = {"version", "output_id", "path", "format", "max_bytes"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def source_digest():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def contract(step, project, inventory):
    from .project_tools import output_path
    if not isinstance(step, dict) or step.get("kind") != "check" or any(
            key in step for key in ("project_data_tool", "calibration")):
        raise ValueError("stdout_artifact supports only shipped KI check steps")
    if not isinstance(step.get("tool"), str) or not Path(step["tool"]).is_absolute():
        raise ValueError("stdout check requires its approved absolute KI tool")
    if Path(step["tool"]).resolve() != Path(step["tool"]) or Path(step["tool"]).is_symlink():
        raise ValueError("stdout check v1 requires the canonical KI tool path")
    value = step.get("stdout_artifact")
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError("stdout_artifact requires version, output_id, path, format and max_bytes")
    if type(value["version"]) is not int or value["version"] != 1 or value["format"] != "json_v1":
        raise ValueError("unsupported stdout artifact version or format")
    if type(value["max_bytes"]) is not int or not 1 <= value["max_bytes"] <= MAX_BYTES:
        raise ValueError("stdout artifact max_bytes must be an integer from 1 to 1048576")
    ident = value["output_id"]
    if not isinstance(ident, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", ident):
        raise ValueError("stdout output_id must be a short literal identifier")
    if not isinstance(step.get("outputs"), list) or step["outputs"].count(ident) != 1:
        raise ValueError("stdout output_id must appear exactly once in step.outputs")
    name = value["path"]
    if (not isinstance(name, str) or len(name) > 1024 or any(ord(c) < 32 for c in name)
            or any(c in name for c in ("\\", ":", "${")) or not name.endswith(".json")):
        raise ValueError("stdout artifact requires a literal project-relative .json path")
    if project is None:
        raise ValueError("stdout artifact requires the current project")
    destination = output_path(project, name)
    items = (inventory or {}).get("items")
    if not isinstance(items, list):
        raise ValueError("stdout artifact requires an approved inventory")
    matches = [row for row in items if isinstance(row, dict) and row.get("id") == ident]
    if len(matches) != 1 or matches[0].get("local_paths") != [name]:
        raise ValueError("stdout output_id must match exactly one inventory item with the declared local_paths")
    if ident in (step.get("inputs") or []):
        raise ValueError("stdout artifact cannot also be an input")
    for row in items:
        if not isinstance(row, dict) or row is matches[0]:
            continue
        for raw in row.get("local_paths") or []:
            p = Path(raw)
            p = (p if p.is_absolute() else Path(project) / p).resolve()
            if destination == p or (p.is_dir() and destination.is_relative_to(p)):
                raise ValueError("stdout destination collides with another inventory item")
    args = step.get("command")
    if not isinstance(args, list) or len(args) > 100 or any(
            not isinstance(a, str) or len(a) > 4000 or "\0" in a or "${" in a for a in args):
        raise ValueError("stdout check requires an explicit literal command argument array")
    cwd = step.get("cwd", ".")
    if not isinstance(cwd, str) or cwd != ".":
        raise ValueError("stdout check v1 requires cwd '.' (the project root)")
    return value, matches[0], destination


def step_errors(step, project, inventory):
    try:
        contract(step, project, inventory)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as error:
        return [str(error)]
    return []


def binding(step, project, inventory):
    value, _, _ = contract(step, project, inventory)
    return {"policy": POLICY, "policy_sha256": source_digest(), "step_sha256": _digest(step),
            "contract": value, "inventory_sha256": _digest(inventory)}


def before_launch(step, project, inventory, arguments, cwd):
    _, _, path = contract(step, project, inventory)
    if arguments != step["command"] or Path(cwd).resolve() != Path(project).resolve():
        raise ValueError("stdout check invocation differs from the approved arguments/cwd")
    if path.exists():
        raise ValueError("stdout capture requires a fresh destination; existing files are never reused")


def _json_bytes(text, maximum):
    if not isinstance(text, str):
        raise ValueError("complete stdout text was not collected")
    data = text.encode("utf-8", errors="strict")
    if not 0 < len(data) <= maximum:
        raise ValueError("stdout JSON is empty or exceeds its artifact byte limit")
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                raise ValueError("stdout JSON contains a duplicate key")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("stdout JSON contains a nonfinite constant: " + value)
    try:
        parsed = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
        if not isinstance(parsed, (dict, list)) or not parsed:
            raise ValueError("stdout JSON must be a nonempty object or array")
        pending, count = [parsed], 0
        while pending:
            value = pending.pop()
            count += 1
            if count > 100_000:
                raise ValueError("stdout JSON has too many values")
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, float) and not math.isfinite(value):
                raise ValueError("stdout JSON contains an overflowed/nonfinite number")
    except RecursionError:
        raise ValueError("stdout JSON nesting exceeds the parser limit") from None
    return data


def capture(step, project, inventory, stdout, *, exit_code, execution_status, process_started,
            command, cwd):
    """Persist only a complete successful check; failed attempts still get receipts."""
    checks = []
    proof = None
    try:
        value, _, path = contract(step, project, inventory)
        if (not isinstance(command, list) or not (command == [step["tool"], *step["command"]]
                or len(command) >= 2 and command[1:] == [step["tool"], *step["command"]])
                or Path(cwd).resolve() != Path(project).resolve()):
            raise ValueError("stdout capture invocation differs from the approved check")
        if exit_code != 0 or execution_status != "succeeded" or process_started is not True:
            raise ValueError("stdout check did not finish successfully; no artifact was published")
        data = _json_bytes(stdout, value["max_bytes"])
        # Recheck after the process: a child-created file or alias cannot be
        # overwritten or promoted as if it were the host's capture.
        from .project_tools import output_path
        path = output_path(project, value["path"])
        if path.exists():
            raise ValueError("stdout destination was created during execution; capture refused")
        path.parent.mkdir(parents=True, exist_ok=True)
        path = output_path(project, value["path"])
        with path.open("xb") as stream:
            stream.write(data)
        proof = {"output_id": value["output_id"], "path": value["path"], "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(), "complete": True,
                 "stream": "stdout", "encoding": "utf-8", "format": "json_v1"}
        checks.append({"check": "stdout_json_capture", "ok": True, "level": "fail",
                       "detail": "Complete decoded stdout JSON; structure only, not scientific validation"})
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as error:
        checks.append({"check": "stdout_json_capture", "ok": False, "level": "fail", "detail": str(error)})
    return {"status": "passed" if proof else "failed", "checks": checks,
            "scope": "ki_check_stdout_artifact", "scientific_validation": "not_performed",
            "model_execution_evidence": False, "artifact": proof}


def receipt_errors(project, step, inventory, receipt):
    """Recheck signed binding/current bytes; never accept a legacy diagnostic log."""
    try:
        expected = binding(step, project, inventory)
        if receipt.get("stdout_artifact") != expected:
            raise ValueError("stdout artifact binding or validation policy changed")
        if (receipt.get("execution_scope") != "ki_check_stdout_artifact"
                or receipt.get("model_executed") is not False):
            raise ValueError("stdout check receipt cannot certify model execution")
        if (receipt.get("exit_code") != 0 or receipt.get("execution_status") != "succeeded"
                or receipt.get("process_started") is not True):
            raise ValueError("stdout check execution did not succeed")
        tool = step["tool"]
        command = receipt.get("command")
        if (not isinstance(command, list) or command not in ([tool, *step["command"]],
                [receipt.get("executable"), tool, *step["command"]])
                or Path(receipt.get("cwd", "")).resolve() != Path(project).resolve()):
            raise ValueError("stdout receipt invocation differs from the approved check")
        validation = receipt.get("validation") or {}
        if (validation.get("status") != "passed" or validation.get("scope") != "ki_check_stdout_artifact"
                or validation.get("model_execution_evidence") is not False
                or validation.get("scientific_validation") != "not_performed"
                or not validation.get("checks") or any(c.get("ok") is not True for c in validation["checks"])):
            raise ValueError("stdout artifact did not pass all checks")
        value, _, path = contract(step, project, inventory)
        with path.open("rb") as stream:
            data = stream.read(value["max_bytes"] + 1)
        if not 0 < len(data) <= value["max_bytes"]:
            raise ValueError("stdout artifact size is no longer valid")
        proof = {"output_id": value["output_id"], "path": value["path"], "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest(), "complete": True,
                 "stream": "stdout", "encoding": "utf-8", "format": "json_v1"}
        if validation.get("artifact") != proof:
            raise ValueError("stdout artifact bytes differ from the validated capture")
        outputs = receipt.get("outputs") or []
        matching = [out for out in outputs if out.get("path") == value["path"]]
        if (len(matching) != 1 or matching[0].get("missing") or any(
                matching[0].get(key) != proof[key] for key in ("bytes", "sha256"))):
            raise ValueError("stdout artifact is missing from the exact signed output inventory")
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError) as error:
        return [str(error)]
    return []
