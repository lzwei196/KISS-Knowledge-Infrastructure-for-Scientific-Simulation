"""Compose authenticated raw Windows metadata with an exact staged main source.

The returned record belongs inside the updater's signed publication origin. It
is neither whole-KI trust nor authoring, installation, or scientific evidence.
No previous composed library supplies any input to this operation.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

from . import ki_platform_overlay as overlay
from . import published_kdt, raw_windows_guidance as raw


POLICY = "authenticated-raw-windows-composition-v1"


class CompositionError(ValueError):
    """Composition inputs or declared results no longer match their evidence."""


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def policy_digest() -> str:
    """Invalidate publication evidence when any composition implementation changes."""
    return _digest({"policy": POLICY,
        "wrapper": published_kdt._module_identity(sys.modules[__name__]),
        "overlay_policy": overlay.POLICY_VERSION,
        "overlay": published_kdt._module_identity(overlay),
        "raw_policy": raw.POLICY, "raw": raw._implementation()})


def _hex(value, size: int, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{%d}" % size, value) is None:
        raise CompositionError(f"Composition requires an exact {label}")
    return value


def _record(value) -> dict:
    if not isinstance(value, dict):
        raise CompositionError("Invalid composition file record")
    path = value.get("path")
    if (not isinstance(path, str) or not path or len(path) > 4096
            or any(c in path for c in "\\:\0") or path.startswith("/")
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or PurePosixPath(path).as_posix() != path):
        raise CompositionError("Unsafe composition file path")
    _hex(value.get("sha256"), 64, "file SHA256")
    if type(value.get("bytes")) is not int or not 0 <= value["bytes"] <= overlay.MAX_GUIDANCE_BYTES:
        raise CompositionError("Invalid composition file size")
    return {key: value[key] for key in ("path", "sha256", "bytes")}


def _actual(root: Path, relative: str) -> dict:
    path = root.joinpath(*PurePosixPath(relative).parts)
    body = overlay._read(root, path)
    return overlay._record(root, path, body)


def _capture(incoming: Path, names: list[str], architecture: str) -> dict[str, dict | None]:
    """Capture all generic inputs and potential output paths before any write."""
    result = {}
    for name in names:
        paths = [f"models/{name}/kiss.yaml", f"kiss/manifests/{name}.yaml",
                 f"models/{name}/kiss.windows.yaml",
                 f"models/{name}/kiss.windows.{architecture}.yaml",
                 f"models/{name}/docs/install.windows.md"]
        for relative in paths:
            path = overlay._safe(incoming, incoming.joinpath(*PurePosixPath(relative).parts))
            result[relative] = _actual(incoming, relative) if path.exists() else None
    return result


def _validate_result(result: dict, incoming: Path, source: Path, inputs: dict,
                     captured: dict, names: list[str], architecture: str) -> None:
    if not isinstance(result, dict) or not isinstance(result.get("files"), list):
        raise CompositionError("Composition has no declared output inventory")
    if len(result["files"]) > 2 * len(names):
        raise CompositionError("Composition output inventory exceeds its model bounds")
    allowed_outputs = {f"models/{name}/{suffix}" for name in names for suffix in
        ("docs/install.windows.md", "kiss.windows.yaml", f"kiss.windows.{architecture}.yaml")}
    outputs = {}
    for item in result["files"]:
        if not isinstance(item, dict):
            raise CompositionError("Invalid composition output entry")
        for key in ("source", "base_generic", "excluded_platform_duplicate"):
            if key not in item:
                if key == "source":
                    raise CompositionError("Composition output has no authenticated source")
                continue
            record = _record(item[key])
            signed = inputs.get(record["path"])
            if (signed is None or _record(signed) != record
                    or _actual(source, record["path"]) != record):
                raise CompositionError("Composition source differs from authenticated raw Windows metadata")
        if "upstream_generic" in item:
            record = _record(item["upstream_generic"])
            if (captured.get(record["path"]) != record
                    or _actual(incoming, record["path"]) != record):
                raise CompositionError("Composition generic input differs from the captured main source")
        output = _record(item.get("output"))
        path = output["path"]
        if (path not in allowed_outputs or path not in captured or captured[path] is not None
                or path.casefold() in outputs):
            raise CompositionError("Composition declares an unexpected or overwritten output")
        if _actual(incoming, path) != output:
            raise CompositionError("Composition output bytes differ from their declared hash")
        outputs[path.casefold()] = output
    # Generic inputs and existing upstream Windows guidance cannot be replaced;
    # every newly created guidance file must be declared in the signed origin.
    for path, before in captured.items():
        target = overlay._safe(incoming, incoming.joinpath(*PurePosixPath(path).parts))
        after = _actual(incoming, path) if target.exists() else None
        expected = before if before is not None else outputs.get(path.casefold())
        if after != expected:
            raise CompositionError("Composition changed undeclared or pre-existing main guidance")


def compose(component: dict, incoming: Path, *, source_commit: str,
            archive_sha256: str, source_content_sha256: str,
            platform: str = "windows", architecture: str | None = None) -> dict:
    """Compose raw metadata and retain verifiable input/output provenance.

    The updater authenticates and hashes the freshly extracted main archive
    before calling this function. Its existing publication gate signs and
    validates the complete resulting KI tree afterward. This wrapper checks
    each guidance input and output, including absent and unchanged files.
    """
    _hex(source_commit, 40, "main commit SHA1")
    _hex(archive_sha256, 64, "main archive SHA256")
    _hex(source_content_sha256, 64, "main source-content SHA256")
    if platform != "windows":
        raise CompositionError("Raw Windows guidance composition requires the Windows platform")
    if not isinstance(component, dict) or not isinstance(component.get("evidence"), dict):
        raise CompositionError("Composition requires an authenticated raw Windows component")
    try:
        source = Path(component["root"])
    except (KeyError, TypeError) as error:
        raise CompositionError("Composition has no raw Windows component root") from error
    evidence = copy.deepcopy(component["evidence"])
    raw.require_current(source, evidence)
    source, incoming = source.resolve(), Path(incoming).resolve()
    if source == incoming or source in incoming.parents or incoming in source.parents:
        raise CompositionError("Raw Windows component and main staging must be disjoint")
    implementation = policy_digest()
    proof_digest = _digest(evidence)
    windows = {key: _hex(evidence.get(key), size, "Windows " + key) for key, size in
               (("source_commit", 40), ("source_tree", 40), ("component_id", 64), ("content_sha256", 64))}
    windows["evidence_sha256"] = proof_digest
    names, inputs = evidence["models"], evidence["inputs"]
    # Match the pure composer's canonical architecture spelling before capture.
    architecture = (architecture or overlay.host_platform.machine()).lower()
    architecture = {"amd64": "x86_64", "aarch64": "arm64"}.get(architecture, architecture)
    if not architecture or not all(c.isalnum() or c in {"_", "-"} for c in architecture):
        raise CompositionError("Invalid composition architecture")
    captured = _capture(incoming, names, architecture)
    result = overlay.apply_windows_overlay(source, incoming, platform=platform,
        architecture=architecture, upstream_commit=source_commit,
        source_identity=windows["component_id"], source_models=names)
    expected = {"schema_version": 1, "policy": overlay.POLICY_VERSION,
                "platform": platform, "architecture": architecture,
                "upstream_commit": source_commit, "source_identity": windows["component_id"]}
    if not isinstance(result, dict) or any(result.get(key) != value for key, value in expected.items()):
        raise CompositionError("Composition result has inconsistent source or policy identity")
    _validate_result(result, incoming, source, inputs, captured, names, architecture)
    raw.require_current(source, evidence)
    if policy_digest() != implementation or _digest(evidence) != proof_digest:
        raise CompositionError("Composition implementation or authenticated evidence changed during composition")
    _validate_result(result, incoming, source, inputs, captured, names, architecture)
    result["composition"] = {"schema_version": 1, "policy": POLICY,
        "policy_sha256": implementation,
        "main": {"source_commit": source_commit, "archive_sha256": archive_sha256,
                 "source_content_sha256": source_content_sha256},
        "windows": windows, "whole_ki_trusted": False,
        "authoring_verification": False, "native_regression": "not_run"}
    # A host signature/cache path belongs in the sealed origin, but not in the
    # deterministic revision identity shared by identical immutable components.
    identity = copy.deepcopy(result)
    identity.pop("overlay_id", None)
    identity["composition"]["windows"].pop("evidence_sha256")
    result["overlay_id"] = _digest(identity)
    return result
