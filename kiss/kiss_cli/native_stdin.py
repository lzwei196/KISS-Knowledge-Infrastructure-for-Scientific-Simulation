"""Plan-owned native prompt input; no caller-supplied stdin or shell expansion.

This first contract admits one numeric/menu answer or inventoried filename per
line. It is not a language for generating model decks or invoking commands.
"""
from __future__ import annotations

import hashlib
from pathlib import Path, PureWindowsPath
import re
import stat

POLICY = "native-stdin-v1"
MAX_BYTES = 4096
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eEdD][+-]?\d+)?\Z")
_MENU = {"y", "n", "yes", "no", "true", "false"}


def _ordinary(path: Path, project: Path, *, required: bool) -> None:
    if not path.is_relative_to(project) or path == project:
        raise ValueError("stdin filenames must stay inside the project")
    for item in (path, *path.parents):
        if item == project:
            break
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
                or item.resolve() != item):
            raise ValueError("stdin filenames must not contain links or aliases")
        if item == path and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise ValueError("stdin input must be an ordinary unshared file")
    if required and not path.is_file():
        raise ValueError("stdin input file does not exist: " + path.relative_to(project).as_posix())


def binding(step: dict, project: Path, ki_root: Path, inventory: dict | None,
            *, for_execution: bool = False) -> dict | None:
    """Validate the exact reviewed contract, including filename read authority."""
    if "stdin" not in step:
        return None
    value = step["stdin"]
    if not isinstance(value, dict) or set(value) != {"text"} or not isinstance(value["text"], str):
        raise ValueError("stdin must contain exactly one text string")
    text = value["text"]
    try:
        raw = text.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("stdin text must be valid UTF-8") from error
    if len(raw) > MAX_BYTES or any(ord(c) < 32 and c not in "\r\n" for c in text) or "\x7f" in text:
        raise ValueError("stdin text is limited to 4096 UTF-8 bytes; only CR/LF controls are allowed")
    if "${" in text:
        raise ValueError("stdin contains an unresolved placeholder; only literal input is supported")
    from ki_tools_common.flow import plan, tools
    if ("project_data_tool" in step or "calibration" in step
            or step.get("kind") in {"calibrate", "download"}
            or not step.get("tool") or Path(step["tool"]).suffix.casefold() not in {"", ".exe"}
            or not tools.is_declared_binary(ki_root, step["tool"])):
        raise ValueError("stdin is supported only for the selected KI's declared native model binary")
    if "command" not in step or "cwd" not in step:
        raise ValueError("stdin requires an explicit approved command array and cwd")
    _, cwd = plan.step_invocation(step, project)
    project = Path(project).resolve()
    paths = set()
    for item in (inventory or {}).get("items") or []:
        if isinstance(item, dict) and item.get("id") in (step.get("inputs") or []):
            for name in item.get("local_paths") or []:
                if isinstance(name, str):
                    candidate = Path(name)
                    candidate = candidate if candidate.is_absolute() else project / candidate
                    paths.add(candidate.absolute())
    inputs = set()
    for line in re.split(r"\r\n|\r|\n", text):
        if not line:
            continue
        candidate = Path(line)
        if (candidate.is_absolute() or PureWindowsPath(line).drive
                or ".." in line.replace("\\", "/").split("/")):
            raise ValueError("stdin filenames must be project-relative without traversal")
        path = cwd / candidate
        # A file named '1' or 'y' still requires file authority if it exists.
        if not path.exists() and (_NUMBER.fullmatch(line) or line.casefold() in _MENU):
            continue
        _ordinary(path, project, required=for_execution)
        if path.absolute() not in paths:
            raise ValueError("stdin filename must name an exact declared step input: " + line)
        inputs.add(path.relative_to(project).as_posix())
    return {"policy": POLICY, "encoding": "utf-8", "text": text,
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "input_files": sorted(inputs), "step_id": str(step.get("id")),
            "ki": str(step.get("ki")), "tool": str(Path(step["tool"]).resolve()),
            "cwd": str(cwd)}


def plan_errors(plan: dict, inventory: dict, project: Path, ki_roots: dict) -> list[str]:
    errors = []
    if not isinstance(plan, dict):
        return errors  # The shared plan validator owns the malformed document.
    for step in (plan or {}).get("steps") or []:
        if not isinstance(step, dict) or "stdin" not in step:
            continue
        try:
            root = ki_roots.get(step.get("ki"))
            if root is None:
                raise ValueError("stdin requires the selected KI root")
            binding(step, project, Path(root), inventory)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
            errors.append(f"step {step.get('id')!r}: {error}")
    return errors


def receipt_errors(project: Path, step: dict, inventory: dict, document: dict,
                   *, ki_root: Path | None = None) -> list[str]:
    """Read-only host extension to the unchanged shared receipt contract."""
    coverage = document.get("input_coverage") or {}
    recorded = coverage.get("native_stdin") if isinstance(coverage, dict) else None
    if "stdin" not in step:
        return ["receipt has unapproved native stdin"] if recorded is not None else []
    try:
        root = Path(ki_root) if ki_root is not None else Path(project) / "models" / str(step.get("ki")) / "ki"
        expected = binding(step, project, root, inventory, for_execution=True)
        if recorded != expected:
            raise ValueError("native stdin receipt differs from the exact approved bytes and file bindings")
        rows = {row.get("path"): row for row in document.get("inputs") or [] if isinstance(row, dict)}
        if any(name not in rows or not rows[name].get("sha256") or rows[name].get("missing")
               for name in expected["input_files"]):
            raise ValueError("native stdin filename lacks its signed input hash")
        logs = coverage.get("native_stdio_logs")
        if not isinstance(logs, dict) or set(logs) != {"stdout", "stderr"}:
            raise ValueError("native stdin receipt lacks full diagnostic streams")
        for label, row in logs.items():
            if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
                raise ValueError("native diagnostic log binding is invalid")
            if (not isinstance(row["path"], str) or type(row["bytes"]) is not int or row["bytes"] < 0
                    or not isinstance(row["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])):
                raise ValueError("native diagnostic log identity is invalid")
            path = Path(project) / row["path"]
            if not path.is_relative_to(Path(project) / "runs" / "logs"):
                raise ValueError("native diagnostic log is outside host logs")
            _ordinary(path, Path(project).resolve(), required=True)
            if str(path) != document.get(label + "_log"):
                raise ValueError("native diagnostic log location differs from the receipt")
            if path.stat().st_size != row["bytes"]:
                raise ValueError("native diagnostic log size changed")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                remaining = row["bytes"]
                while remaining:
                    chunk = stream.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("native diagnostic log shortened during verification")
                    digest.update(chunk)
                    remaining -= len(chunk)
                if stream.read(1):
                    raise ValueError("native diagnostic log grew during verification")
            if digest.hexdigest() != row["sha256"]:
                raise ValueError("native diagnostic log bytes changed")
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
        return [str(error)]
    return []


def evidence(flow, project: Path, plan: dict | None, approval: dict | None,
             *, ki_roots: dict | None = None, **kwargs) -> dict:
    """Retain shared evidence, then enforce Desktop's additional stdin proof."""
    proof = flow.receipts.evidence(project, plan, approval, **kwargs)
    steps = {str(s.get("id")): s for s in (plan or {}).get("steps") or [] if isinstance(s, dict)}
    if not any("stdin" in step for step in steps.values()):
        return proof
    project = Path(project).resolve()
    current = proof.get("approval_sha256")
    bound = {(row.get("run_id"), row.get("plan_step_id")) for row in proof.get("runs") or []}
    attempts = []
    for _, doc, verified in flow.receipts._read_all(project, flow.receipts.RUNS_SUB):
        sid = str(doc.get("plan_step_id"))
        if verified and doc.get("approval_sha256") == current and (doc.get("run_id"), sid) in bound:
            errors = receipt_errors(project, steps[sid], kwargs.get("inventory"), doc,
                ki_root=(ki_roots or {}).get(steps[sid].get("ki")))
            status = (doc.get("validation") or {}).get("status")
            rank = 2 if errors or status == "failed" else (0 if status == "passed" else 1)
            attempts.append((flow.receipts._finished_at(doc), rank, sid, doc, errors))
    latest = {}
    for _, _, sid, doc, errors in sorted(attempts, key=lambda row: (row[0], row[1])):
        latest[sid] = (doc, errors)
    failed = {sid: errors for sid, (_, errors) in latest.items() if errors}
    if not failed:
        return proof
    blocked = set(failed)
    dependencies = flow.receipts.plan_dependencies(plan)
    while True:
        expanded = blocked | {sid for sid, required in dependencies.items() if required & blocked}
        if expanded == blocked:
            break
        blocked = expanded
    proof["steps_passed"] = sorted(set(proof.get("steps_passed") or []) - blocked)
    proof["steps_missing"] = sorted(set(proof.get("steps_missing") or []) | blocked)
    proof["stale_steps"] = sorted(set(proof.get("stale_steps") or []) | blocked)
    reasons = proof.setdefault("stale_step_reasons", {})
    for sid in blocked:
        reasons.setdefault(sid, []).extend(failed.get(sid) or ["upstream native stdin evidence is invalid"])
    for sid, errors in failed.items():
        doc = latest[sid][0]
        proof.setdefault("current_failures", []).append({"plan_step_id": sid, "run_id": doc.get("run_id"),
            "exit_code": doc.get("exit_code"), "validation_reason": "; ".join(errors), "failed_checks": []})
        for row in proof.get("runs") or []:
            if row.get("run_id") == doc.get("run_id"):
                row.update(validation="failed", validation_reason="; ".join(errors))
    proof.update(validation="failed", receipts_verified=False)
    return proof
