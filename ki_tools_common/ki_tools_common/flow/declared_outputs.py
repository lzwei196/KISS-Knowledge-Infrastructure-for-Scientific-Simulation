"""Bind result validation to exact approved outputs; retain other run artifacts.

This classifies evidence, not process filesystem permissions. The existing
scientific validator still checks every declared numeric result.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat

POLICY = "approved-declared-outputs-v1"
REPORT = "json_report_v1"
MAX_REPORT_BYTES = 4 * 1024 * 1024
PHYSICAL = {"run", "model_run", "route", "calibrate"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _policy_hash():
    here = Path(__file__)
    return _hash({p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (here, here.with_name("receipts.py"))})


def ordinary(step):
    return (isinstance(step, dict) and bool(step.get("tool")) and step.get("kind") != "download"
            and not any(key in step for key in ("project_data_tool", "calibration", "stdout_artifact")))


def _path(project, raw):
    if not isinstance(raw, str) or not raw or len(raw) > 4096 or any(c in raw for c in "\0\r\n*?[]$"):
        raise ValueError("Declared outputs require literal project file paths")
    project = Path(project).resolve()
    value = Path(raw)
    if not value.is_absolute() and PureWindowsPath(raw).drive:
        raise ValueError("Declared output paths cannot use Windows drive syntax")
    # Validate before abspath: Windows can normalize away a trailing dot or
    # space, and a colon must never be interpreted as an alternate data stream.
    if os.name == "nt" and any(
            part.endswith((".", " ")) or any(c in part for c in ':<>"|')
            or any(ord(c) < 32 for c in part) or PureWindowsPath(part).is_reserved()
            for part in value.parts if part != value.anchor):
        raise ValueError("Declared output uses a nonordinary Windows filename")
    if value.drive and not value.is_absolute() or ".." in value.parts or "~" in value.parts:
        raise ValueError("Declared output paths cannot traverse or use drive-relative/home paths")
    path = Path(os.path.abspath(value if value.is_absolute() else project / value))
    try:
        relative = path.relative_to(project)
    except ValueError:
        raise ValueError("Declared output must stay inside the project") from None
    parts = relative.parts
    if os.name == "nt" and any(":" in part or part.endswith((".", " ")) for part in parts):
        raise ValueError("Declared output uses a nonordinary filename")
    if not parts or not (parts[0] in {"inputs", "outputs", "artifacts"}
                        or len(parts) > 2 and parts[:2] == ("runs", "logs")):
        raise ValueError("Declared output must be a file in a tracked project output directory")
    for ancestor in (path, *path.parents):
        if ancestor.resolve() != ancestor:
            raise ValueError("Declared output path is aliased")
        if ancestor == project:
            break
    if path.exists():
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Declared output must be an ordinary, unlinked file")
    return path, relative.as_posix()


def _execution_alias_path(project, raw):
    """The sole link exception is execution metadata, never an output path."""
    if (not isinstance(raw, str) or not raw or len(raw) > 4096
            or any(c in raw for c in "\0\r\n*?[]$\\")):
        raise ValueError("Invalid execution alias path")
    relative = Path(raw)
    if (relative.is_absolute() or PureWindowsPath(raw).drive
            or relative.as_posix() != raw or any(p in {"..", "~"} for p in relative.parts)
            or len(relative.parts) < 2 or relative.parts[0] not in {"outputs", "artifacts"}
            or relative.suffix.casefold() not in {"", ".exe"}):
        raise ValueError("Execution alias must be an exact native path under project outputs")
    # Reuse ordinary parent/path spelling checks without admitting the link
    # itself as a scientific or supporting output.
    _path(project, (relative.parent / ".execution-alias-parent-check").as_posix())
    path = Path(project).resolve() / relative
    info = path.lstat()
    if not stat.S_ISLNK(info.st_mode) or info.st_nlink != 1:
        raise ValueError("Execution alias is not an ordinary symbolic link")
    return path


def _engine_option(option, ki):
    model = re.sub(r"[^a-z0-9]+", "_", str(ki).casefold()).strip("_")
    allowed = {"--binary", "--executable", "--exe"}
    for spelling in {model, model.replace("_", "-")} - {""}:
        for suffix in ("exe", "binary", "executable"):
            allowed.update({f"--{spelling}_{suffix}", f"--{spelling}-{suffix}"})
    return option in allowed


def execution_alias_errors(project, receipt):
    """Validate host-signed engine aliases without broadening output paths."""
    try:
        coverage = receipt.get("input_coverage") or {}
        aliases = coverage.get("runtime_executable_aliases")
        if aliases is None:
            return []
        if not isinstance(aliases, list) or not 0 < len(aliases) <= 100:
            raise ValueError("Invalid execution alias metadata")
        bindings = coverage.get("runtime_arguments")
        if not isinstance(bindings, list):
            raise ValueError("Execution alias lacks runtime argument authority")
        seen = set()
        for row in aliases:
            if (not isinstance(row, dict) or set(row) != {"path", "target", "bytes", "sha256",
                    "argument_index", "option", "runtime_path", "link_text"}
                    or not _engine_option(row["option"], receipt.get("ki"))):
                raise ValueError("Invalid engine alias role or metadata")
            path = _execution_alias_path(project, row["path"])
            key = row["path"].casefold() if os.name == "nt" else row["path"]
            if key in seen:
                raise ValueError("Duplicate execution alias")
            seen.add(key)
            binding = {"argument_index": row["argument_index"], "option": row["option"],
                       "path": row["runtime_path"], "target": row["target"]}
            if sum(item == binding for item in bindings) != 1:
                raise ValueError("Execution alias does not match a captured engine argument")
            target = Path(row["target"])
            if (not target.is_absolute() or target.resolve(strict=True) != target
                    or path.resolve(strict=True) != target or os.readlink(path) != row["link_text"]):
                raise ValueError("Execution alias target changed")
            size, digest = row["bytes"], row["sha256"]
            if (type(size) is not int or not 0 < size <= 256 * 1024 * 1024
                    or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
                raise ValueError("Invalid engine alias byte identity")
            from . import receipts
            name = receipts._rel(target, Path(project))
            entries = [entry for entry in receipt.get("inputs", [])
                       if isinstance(entry, dict) and entry.get("path") == name]
            if (len(entries) != 1 or entries[0].get("bytes") != size
                    or entries[0].get("sha256") != digest or entries[0].get("missing")):
                raise ValueError("Execution alias lacks the exact signed engine input hash")
            info = target.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size != size:
                raise ValueError("Execution alias engine bytes changed")
            observed, remaining = hashlib.sha256(), size + 1
            with target.open("rb") as stream:
                while remaining:
                    block = stream.read(min(1024 * 1024, remaining))
                    if not block:
                        break
                    remaining -= len(block)
                    observed.update(block)
            if remaining != 1 or observed.hexdigest() != digest:
                raise ValueError("Execution alias engine bytes changed")
        return []
    except (OSError, ValueError, TypeError, KeyError, RuntimeError, AttributeError) as error:
        return [str(error)]


def binding(project, step, inventory):
    if not ordinary(step) or not step.get("outputs"):
        return None
    ids = step["outputs"]
    if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Declared output IDs must be unique nonempty strings")
    items = inventory.get("items") if isinstance(inventory, dict) else None
    if not isinstance(items, list):
        raise ValueError("Declared outputs need the approved inventory")
    # Older plans used symbolic output IDs without inventory declarations.
    # They receive the original all-changed-files validation, never exemptions.
    if (not any(isinstance(item, dict) and item.get("id") in ids for item in items)
            and not any(isinstance(item, dict) and "output_validation" in item for item in items)):
        return None
    rows, seen = [], set()
    for item_id in ids:
        matches = [item for item in items if isinstance(item, dict) and item.get("id") == item_id]
        if len(matches) != 1:
            raise ValueError(f"Declared output {item_id!r} needs exactly one inventory item")
        item = matches[0]
        mode = item.get("output_validation", "scientific")
        if "output_validation" in item and mode != REPORT:
            raise ValueError(f"Output {item_id!r} has unknown output_validation; only {REPORT!r} is supported")
        paths = item.get("local_paths")
        if not isinstance(paths, list) or not paths or len(paths) > 1024:
            raise ValueError(f"Declared output {item_id!r} needs exact local_paths")
        for raw in paths:
            _absolute, relative = _path(project, raw)
            if relative.casefold() in seen:
                raise ValueError("Declared output paths must be unique across output IDs")
            seen.add(relative.casefold())
            rows.append({"id": item_id, "path": relative, "validation": mode})
    if step.get("kind", "process") in PHYSICAL and not any(r["validation"] == "scientific" for r in rows):
        raise ValueError("A physical model step needs at least one declared scientific result; JSON reports are not model evidence")
    return {"version": 1, "policy": POLICY, "policy_sha256": _policy_hash(),
            "step_sha256": _hash(step), "inventory_sha256": _hash(inventory), "outputs": rows}


def plan_errors(plan, inventory, project):
    errors = []
    steps = plan.get("steps") or []
    items = inventory.get("items") or []
    for item in items:
        if not isinstance(item, dict) or "output_validation" not in item:
            continue
        item_id = item.get("id")
        producers = [st for st in steps if isinstance(st, dict) and item_id in (st.get("outputs") or [])]
        if item.get("output_validation") != REPORT:
            errors.append(f"inventory item {item_id!r}: output_validation supports only {REPORT!r}")
        if not producers or any(not ordinary(st) for st in producers):
            errors.append(f"inventory item {item_id!r}: output_validation belongs only to ordinary KI-produced results")
    if project is not None:
        for step in steps:
            if ordinary(step) and step.get("outputs"):
                try:
                    binding(project, step, inventory)
                except (ValueError, OSError, TypeError, RuntimeError) as error:
                    errors.append(f"step {step.get('id')!r}: {error}")
    return errors


def _json_report(path):
    size = path.stat().st_size
    if not 0 < size <= MAX_REPORT_BYTES:
        raise ValueError("JSON report must contain 1 byte through 4 MiB")
    with path.open("rb") as stream:
        data = stream.read(size + 1)
    if len(data) != size:
        raise ValueError("JSON report changed during validation")
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("JSON report contains duplicate keys")
            result[key] = value
        return result
    def constant(value):
        raise ValueError("JSON report contains a nonfinite value")
    doc = json.loads(data.decode("utf-8", errors="strict"), object_pairs_hook=pairs, parse_constant=constant)
    if not isinstance(doc, (dict, list)) or not doc:
        raise ValueError("JSON report must be a nonempty object or array")
    stack = [doc]
    while stack:
        value = stack.pop()
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("JSON report contains a nonfinite value")
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)


def validate(project, ki_root, step, inventory, changed, *, run_facts, physical):
    """Return validation plus signed binding; errors remain failed run evidence."""
    checks = []
    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail, "level": "fail"})
    try:
        contract = binding(project, step, inventory)
    except (ValueError, OSError, TypeError, RuntimeError) as error:
        add("declared_output_binding", False, str(error))
        return {"status": "failed", "checks": checks}, {"version": 1, "policy": POLICY, "error": str(error)}
    if contract is None:
        from . import receipts
        return receipts.validate_outputs(ki_root, changed, physical=physical,
            run_facts={**run_facts, "output_nonempty": any(
                Path(p).is_file() and Path(p).stat().st_size > 0 for p in changed)}), None
    fresh = {str(Path(os.path.abspath(p))) for p in changed}
    numeric = []
    for row in contract["outputs"]:
        try:
            path, _ = _path(project, row["path"])
            exists = path.is_file()
            add("declared_output_fresh:" + row["path"], exists and str(path) in fresh,
                "Every approved output must be produced or changed by this attempt")
            add("declared_output_nonempty:" + row["path"], exists and path.stat().st_size > 0)
            if row["validation"] == REPORT:
                _json_report(path)
                add("json_report:" + row["path"], True, "Structured report only; contributes no numeric model evidence")
            else:
                numeric.append(path)
        except (ValueError, OSError, TypeError, RuntimeError, RecursionError) as error:
            add("declared_output:" + row["path"], False, str(error))
    if numeric or physical:
        from . import receipts
        scientific = receipts.validate_outputs(ki_root, numeric, physical=physical,
            run_facts={**run_facts, "output_nonempty": any(p.is_file() and p.stat().st_size > 0 for p in numeric)})
        checks.extend(scientific["checks"])
    else:
        add("run_affirmed_error_free", run_facts.get("errored") is False)
    failed = any(not c["ok"] and c["level"] == "fail" for c in checks)
    warned = any(not c["ok"] and c["level"] == "warn" for c in checks)
    return {"status": "failed" if failed else "warning" if warned else "passed", "checks": checks}, contract


def receipt_errors(project, step, inventory, receipt, *, check_files=True):
    """Keep invalid authentic attempts in latest-attempt ordering as failures."""
    try:
        alias_errors = execution_alias_errors(project, receipt)
        if alias_errors:
            return alias_errors
        current = binding(project, step, inventory)
        recorded = receipt.get("declared_outputs")
        if current is None:
            return ["Unexpected declared output contract"] if recorded is not None else []
        if current != recorded:
            return ["Declared outputs differ from the approved plan/inventory or validator policy"]
        rows = receipt.get("outputs")
        if not isinstance(rows, list):
            return ["Declared output receipt has no file evidence"]
        files = {}
        roles = {row["path"]: ("declared_json_report" if row["validation"] == REPORT
                              else "declared_scientific_result") for row in current["outputs"]}
        for row in rows:
            raw = row.get("path") if isinstance(row, dict) else None
            path, relative = _path(project, raw)
            if relative.casefold() in {key.casefold() for key in files}:
                return ["Ambiguous output file evidence"]
            files[relative] = row
            if row.get("output_role") != roles.get(relative, "supporting_execution_artifact"):
                return ["Recorded output classification differs from the approved binding"]
            expected_size = row.get("bytes")
            if not check_files:
                # evidence() checks bytes once, after resolving the current
                # owner of each path. An intermediate version may legitimately
                # have been replaced by another approved step.
                if (type(expected_size) is not int or expected_size < 0
                        or not isinstance(row.get("sha256"), str) or not row["sha256"]):
                    return ["Recorded output has incomplete file evidence: " + relative]
                continue
            if (type(expected_size) is not int or expected_size < 0 or not path.is_file()
                    or path.stat().st_size != expected_size):
                return ["Recorded output or supporting execution artifact changed: " + relative]
            digest = hashlib.sha256()
            read = 0
            with path.open("rb") as stream:
                while chunk := stream.read(min(1024 * 1024, expected_size - read + 1)):
                    read += len(chunk)
                    if read > expected_size:
                        return ["Recorded output grew during inspection: " + relative]
                    digest.update(chunk)
            if read != expected_size or digest.hexdigest() != row.get("sha256"):
                return ["Recorded output or supporting execution artifact changed: " + relative]
        for output in current["outputs"]:
            row = files.get(output["path"])
            if not row or row.get("missing") or not row.get("bytes"):
                return ["Required declared output is missing from fresh attempt evidence: " + output["path"]]
        return []
    except (ValueError, OSError, TypeError, RuntimeError, KeyError, RecursionError) as error:
        return [str(error)]
