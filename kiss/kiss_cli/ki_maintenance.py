"""Exact, local maintenance of an intact KI with unchanged published evidence.

This is deliberately separate from full KDT authoring acceptance. A maintenance
receipt proves current package checks and a bounded generated change against a
frozen host source. It never upgrades bibliography metadata into fetched/read
paper evidence, scientific validation, native readiness or official publication.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

from . import doctor, kdtstudio, ki_copy, ki_guard, ki_tree, ki_verification
from . import published_acceptance, published_kdt, published_literature

POLICY = "ki-maintenance-unchanged-published-evidence-v1"
SOURCE_SCOPE = "ki_maintenance_source"
SCOPE = "ki_maintenance_candidate"
VerificationError = ki_verification.VerificationError


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def policy_digest() -> str:
    from . import ki_maintenance_recipes, ki_maintenance_wofost, ki_path_contracts
    return _hash({"policy": POLICY,
                  "implementation": published_kdt._module_identity(sys.modules[__name__]),
                  "recipes": published_kdt._module_identity(ki_maintenance_recipes),
                  "wofost_interface": published_kdt._module_identity(ki_maintenance_wofost),
                  "runtime_paths": published_kdt._module_identity(ki_path_contracts),
                  "publication_profile": published_kdt.profile_source_digest(),
                  "host_gate": ki_verification.GATE_POLICY,
                  "doctor": doctor.VALIDATION_POLICY_VERSION})


def _home(root: Path) -> Path:
    return ki_verification._authority(root) / "maintenance"


def _sign(root: Path, value: dict) -> dict:
    return ki_verification._receipts().sign(_home(root), value)


def _authentic(root: Path, value: dict) -> bool:
    return isinstance(value, dict) and ki_verification._receipts().verify(_home(root), value)


def _inventory(root: Path) -> dict:
    result = {}
    for entry in ki_tree.scan(root).entries:
        row = {"kind": entry.kind}
        if entry.kind == "file":
            row["sha256"] = hashlib.sha256((root / entry.relative).read_bytes()).hexdigest()
        elif entry.kind == "link":
            row["target"] = entry.target
        result[entry.relative] = row
    return result


def _engine() -> dict:
    if os.environ.get("GEOFORGE_KDT_ENGINE"):
        raise VerificationError("Maintenance requires the reviewed installed KDT engine")
    engine = kdtstudio.engine_status()
    if (not engine.get("installed") or not engine.get("source_digest")
            or engine.get("source_digest") != kdtstudio.engine_source_digest()):
        raise VerificationError("Maintenance requires an unchanged reviewed KDT engine")
    return {"engine_policy": kdtstudio.REVIEWED_COMMIT,
            "engine_source_digest": engine["source_digest"], "engine_override": False}


def _published_source(root: Path, report: dict, name: str, kind: str) -> dict:
    """An authentic rejection can prove source identity, never acceptance."""
    from . import ki_updates
    update_home = ki_updates.update_root().resolve()
    relative = root.relative_to(update_home) if root.is_relative_to(update_home) else None
    if (relative is None or len(relative.parts) < 4
            or relative.parts[0] not in ("quarantine", "snapshots")
            or not published_acceptance._authentic(root, report)
            or report.get("scope") != published_acceptance.SCOPE
            or report.get("gate_policy") != published_acceptance.POLICY
            or report.get("state") not in ("PublishedPackageAccepted", "PublicationRejected")
            or report.get("state") != ("PublishedPackageAccepted" if report.get("ok") is True else "PublicationRejected")
            or type(report.get("ok")) is not bool
            or report.get("name") != name or report.get("kind") != kind
            or report.get("authoring_verification") is not False
            or report.get("literature_evidence") != "published_metadata_only"
            or report.get("engine_override") is not False
            or report.get("desktop_requested") is not True
            or report.get("profile_digest") != published_acceptance.profile_digest()
            or report.get("doctor_policy") != doctor.VALIDATION_POLICY_VERSION
            or report.get("engine_policy") != kdtstudio.REVIEWED_COMMIT
            or report.get("engine_source_digest") != kdtstudio.engine_source_digest()
            or not re.fullmatch(r"[0-9a-f]{40}", report.get("source_commit", ""))
            or not re.fullmatch(r"[0-9a-f]{64}", report.get("origin_id", ""))
            or report.get("package_path") != Path(*relative.parts[2:]).as_posix()
            or report.get("candidate_digest") != ki_verification.content_digest(root)):
        raise VerificationError("Maintenance source has no current exact signed publication provenance")
    return {"source_scope": "signed_official_publication_source",
            "source_report": report, "source_commit": report["source_commit"]}


def capture_source(base: Path, name: str, *, publication_report: dict | None = None) -> dict:
    """Freeze trusted source bytes outside the active KI and its repair draft.

    A host baseline proves identity only; it does not claim upstream provenance
    or scientific acceptance. The optional publication route additionally proves
    exact official source identity but permits a structurally rejected source.
    """
    base = Path(base).absolute()
    if not isinstance(name, str) or not name.strip():
        raise VerificationError("Maintenance requires the KI identity")
    # Inspect before resolve so a root alias cannot hide from tree validation.
    inventory = _inventory(base)
    base = base.resolve()
    kind = ki_verification.detect_kind(base)
    engine = _engine()
    profile = policy_digest()
    digest = ki_verification.content_digest(base)
    if not digest:
        raise VerificationError("Cannot fingerprint maintenance source")
    if publication_report is None:
        baseline = ki_guard.require_intact(base)
        provenance = {"source_scope": "intact_host_baseline", "baseline": baseline}
    else:
        provenance = _published_source(base, publication_report, name, kind)
    literature = published_literature.check(base, model_name=name, kind=kind)
    if not literature["ok"]:
        raise VerificationError("Existing published evidence is invalid: " + "; ".join(literature["failures"]))
    home = _home(base)
    if home == base or home.is_relative_to(base):
        raise VerificationError("Maintenance evidence must remain outside the source KI")
    frozen = home / "sources" / uuid.uuid4().hex / "base"
    frozen.parent.mkdir(parents=True)
    ki_copy.copytree(base, frozen)
    if (ki_verification.content_digest(base) != digest
            or ki_verification.content_digest(frozen) != digest
            or _inventory(frozen) != inventory):
        raise VerificationError("Source changed while freezing maintenance evidence")
    if publication_report is None:
        if ki_guard.require_intact(base) != baseline:
            raise VerificationError("Source baseline changed while freezing maintenance evidence")
    else:
        _published_source(base, publication_report, name, kind)
    if policy_digest() != profile or _engine() != engine:
        raise VerificationError("Maintenance verifier changed while capturing source")
    source = _sign(frozen, {
        "scope": SOURCE_SCOPE, "policy": POLICY, "policy_digest": profile,
        "name": name, "kind": kind, "original_root": str(base),
        "base_root": str(frozen), "base_digest": digest,
        "protected_inventory": inventory, "literature": literature,
        "authoring_verification": False, "literature_evidence": "published_metadata_only",
        "scientific_validation": False, "captured_at": time.time(),
        **engine, **provenance,
    })
    (frozen.parent / "source.json").write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    return source


def require_source(source: dict, *, name: str | None = None) -> Path:
    if not isinstance(source, dict) or not isinstance(source.get("base_root"), str):
        raise VerificationError("Missing maintenance source context")
    base = Path(source["base_root"]).absolute()
    home = _home(base)
    expected_parent = home / "sources"
    if (base.name != "base" or base.parent.parent != expected_parent
            or not re.fullmatch(r"[0-9a-f]{32}", base.parent.name)
            or not _authentic(base, source) or source.get("scope") != SOURCE_SCOPE
            or source.get("policy") != POLICY or source.get("policy_digest") != policy_digest()
            or source.get("kind") not in ki_verification.KINDS
            or (name is not None and source.get("name") != name)
            or source.get("source_scope") not in ("intact_host_baseline", "signed_official_publication_source")
            or source.get("authoring_verification") is not False
            or source.get("literature_evidence") != "published_metadata_only"
            or source.get("scientific_validation") is not False
            or any(source.get(key) != value for key, value in _engine().items())):
        raise VerificationError("Maintenance source context is unauthenticated or stale")
    if (ki_verification.content_digest(base) != source.get("base_digest")
            or _inventory(base) != source.get("protected_inventory")):
        raise VerificationError("Frozen maintenance evidence changed; capture the intact source again")
    return base


def _changes(base: Path, candidate: Path, name: str, *, maintenance_recipe=None,
             runtime_config=None, target_root=None) -> list[dict]:
    from . import ki_maintenance_recipes
    before, after = _inventory(base), _inventory(candidate)
    if set(before) != set(after):
        raise VerificationError("Maintenance cannot add or remove KI files; use full KDT authoring")
    if maintenance_recipe is not None:
        from . import ki_path_contracts
        if maintenance_recipe != ki_path_contracts.RECIPE:
            raise VerificationError("Unsupported runtime-bound maintenance recipe")
        expected = ki_path_contracts.expected_changes(base, name, runtime_config, target_root=target_root)
        if not expected:
            raise VerificationError("Runtime path repair needs a recognized source, saved configuration and exact active KI target")
    else:
        expected = ki_maintenance_recipes.expected_changes(base, name)
    changes = []
    for relative, old in before.items():
        if old == after[relative]:
            continue
        generated = expected.get(relative)
        if (old["kind"] != "file" or after[relative]["kind"] != "file"
                or not isinstance(generated, bytes)
                or (candidate / relative).read_bytes() != generated):
            raise VerificationError(f"Edit exceeds the maintenance contract: {relative}; use full KDT authoring")
        changes.append({"path": relative, "before_sha256": old["sha256"],
                        "after_sha256": after[relative]["sha256"]})
    if maintenance_recipe is not None and {row["path"] for row in changes} != set(expected):
        raise VerificationError("Runtime path repair must apply its exact complete projection")
    return sorted(changes, key=lambda row: row["path"])


def _path_context(source, name, cfg, target_root):
    """A retained path repair can bind only its intact prepared project KI."""
    from . import ki_path_contracts
    if cfg is None or target_root is None:
        raise VerificationError("Runtime path maintenance requires the exact saved project configuration and active KI target")
    ki_path_contracts.config_identity(cfg)
    target = Path(target_root)
    if (name != "WOFOST" or not target.is_absolute()
            or target != Path(cfg.root) / "models" / name / "ki"
            or target != Path(source.get("original_root", ""))
            or source.get("source_scope") != "intact_host_baseline"):
        raise VerificationError("Runtime path maintenance is restricted to its intact prepared project KI")
    return target


def _require_path_report(report, cfg, target):
    from . import ki_path_contracts
    ki_path_contracts.require_runtime_current(report)
    reconstructed = ki_path_contracts.projection_config(report)
    if (ki_path_contracts.config_identity(reconstructed) != ki_path_contracts.config_identity(cfg)
            or Path(report["runtime"]["target_ki"]) != Path(target)):
        raise VerificationError("Runtime path report does not match the selected project bindings")


def verify_candidate(candidate: Path, *, source: dict, name: str, runtime_python=None,
                     maintenance_recipe=None, runtime_config=None, target_root=None) -> dict:
    from . import ki_maintenance_recipes, ki_maintenance_wofost, ki_path_contracts
    candidate = Path(candidate).absolute()
    base = require_source(source, name=name)
    if candidate == base or candidate.is_relative_to(base) or base.is_relative_to(candidate):
        raise VerificationError("Maintenance source and candidate must be separate trees")
    digest = ki_verification.content_digest(candidate)
    if not digest or ki_verification.detect_kind(candidate) != source["kind"]:
        raise VerificationError("Maintenance candidate has no valid matching KI identity")
    profile = policy_digest()
    path_repair = maintenance_recipe == ki_path_contracts.RECIPE
    if path_repair:
        target_root = _path_context(source, name, runtime_config, target_root)
    elif runtime_config is not None or target_root is not None:
        raise VerificationError("Runtime path bindings require their explicit maintenance recipe")
    change_args = ({"maintenance_recipe": maintenance_recipe, "runtime_config": runtime_config,
                    "target_root": target_root} if maintenance_recipe is not None else {})
    changes = _changes(base, candidate, name, **change_args)
    behavior = {"ok": True, "status": "not_required", "native_execution": False}
    path_binding = {"ok": True, "status": "not_required", "native_execution": False,
                    "model_execution": False, "scientific_validation": False}
    if path_repair:
        path_binding = ki_path_contracts.validate_behavior(base, candidate, runtime_config, target_root=target_root)
        if not isinstance(path_binding, dict) or type(path_binding.get("ok")) is not bool:
            raise VerificationError("Maintenance runtime path regression returned an invalid report")
        if path_binding["ok"]:
            _require_path_report(path_binding, runtime_config, target_root)
    elif any(row["path"] == "preflight_check.py" for row in changes):
        behavior = ki_maintenance_recipes.validate_preflight_behavior(base, candidate)
        if not isinstance(behavior, dict) or type(behavior.get("ok")) is not bool:
            raise VerificationError("Maintenance preflight regression returned an invalid report")
    interface = {"ok": True, "status": "not_required", "model_execution": False,
                 "scientific_validation": False}
    requires_runtime = any(row["path"] == ki_maintenance_wofost.TOOL_PATH for row in changes)
    if requires_runtime:
        if not isinstance(runtime_python, (str, Path)) or not str(runtime_python).strip():
            raise VerificationError("WOFOST parameter routing requires the saved project Python runtime")
        interface = ki_maintenance_wofost.validate_behavior(base, candidate, str(runtime_python))
        if not isinstance(interface, dict) or type(interface.get("ok")) is not bool:
            raise VerificationError("Maintenance interface regression returned an invalid report")
        if interface["ok"]:
            ki_maintenance_wofost.require_runtime_current(interface)
    report = ki_verification._check_candidate(candidate, name=name, kind=source["kind"],
        desktop=True, _gate_adapter=lambda gate: published_kdt.gate_view(gate, model_name=name))
    ok = bool(report["ok"] and behavior["ok"] and interface["ok"] and path_binding["ok"])
    if not behavior["ok"]:
        report["failures"] = [*report["failures"], "Maintenance preflight behavior regression failed"]
    if not interface["ok"]:
        report["failures"] = [*report["failures"], "Maintenance parameter interface regression failed"]
    if not path_binding["ok"]:
        report["failures"] = [*report["failures"], "Maintenance runtime path regression failed"]
    require_source(source, name=name)
    if (ki_verification.content_digest(candidate) != digest or _changes(base, candidate, name, **change_args) != changes
            or policy_digest() != profile):
        raise VerificationError("Maintenance candidate or verifier changed during verification")
    if requires_runtime and interface["ok"]:
        # Recheck the selected interpreter and provider bytes after the KDT gate;
        # its result cannot bless a runtime that changed while checks were running.
        ki_maintenance_wofost.require_runtime_current(interface)
    if path_repair and path_binding["ok"]:
        _require_path_report(path_binding, runtime_config, target_root)
    report.update(scope=SCOPE, gate_policy=POLICY, policy_digest=profile, ok=ok,
        state="MaintenanceVerified" if ok else "MaintenanceRejected", name=name,
        source=source, source_id=_hash(source), base_digest=source["base_digest"],
        changes=changes, change_digest=_hash(changes), authoring_verification=False,
        literature_evidence="unchanged_published_metadata_only", scientific_validation=False,
        local_only=True, preflight_regression=behavior, interface_regression=interface,
        path_binding_regression=path_binding, maintenance_recipe=maintenance_recipe,
        native_regression={"status": "not_run", "verified": False})
    return _sign(candidate, report)


def require_current(candidate: Path, report: dict, *, source: dict | None = None) -> dict:
    """Validate only the explicit maintenance scope; no authoring store entry."""
    candidate = Path(candidate).absolute()
    if not _authentic(candidate, report):
        raise VerificationError("Maintenance verification is missing or unauthenticated")
    embedded = report.get("source")
    if source is not None and source != embedded:
        raise VerificationError("Maintenance report belongs to another source context")
    base = require_source(embedded, name=report.get("name"))
    if (report.get("scope") != SCOPE or report.get("gate_policy") != POLICY
            or report.get("ok") is not True or report.get("state") != "MaintenanceVerified"
            or report.get("policy_digest") != policy_digest()
            or report.get("source_id") != _hash(embedded)
            or report.get("base_digest") != embedded["base_digest"]
            or report.get("kind") != embedded["kind"]
            or report.get("desktop_requested") is not True
            or report.get("doctor_policy") != doctor.VALIDATION_POLICY_VERSION
            or report.get("authoring_verification") is not False
            or report.get("literature_evidence") != "unchanged_published_metadata_only"
            or report.get("scientific_validation") is not False or report.get("local_only") is not True
            or any(report.get(key) != value for key, value in _engine().items())
            or ki_verification.content_digest(candidate) != report.get("candidate_digest")):
        raise VerificationError("Maintenance verification failed, changed or is stale; verify again")
    from . import ki_path_contracts
    change_args = {}
    if report.get("maintenance_recipe") is not None:
        if report["maintenance_recipe"] != ki_path_contracts.RECIPE:
            raise VerificationError("Unsupported signed maintenance recipe")
        path_binding = report.get("path_binding_regression")
        ki_path_contracts.require_runtime_current(path_binding)
        cfg = ki_path_contracts.projection_config(path_binding)
        target = _path_context(embedded, report["name"], cfg, path_binding["runtime"]["target_ki"])
        _require_path_report(path_binding, cfg, target)
        change_args = {"maintenance_recipe": report["maintenance_recipe"], "runtime_config": cfg,
                       "target_root": target}
    changes = _changes(base, candidate, report["name"], **change_args)
    if report.get("changes") != changes or report.get("change_digest") != _hash(changes):
        raise VerificationError("Maintenance changes differ from their verification")
    from . import ki_maintenance_wofost
    if any(row["path"] == ki_maintenance_wofost.TOOL_PATH for row in changes):
        # This is a read-only identity/completeness check. Interface fixtures do
        # not establish model readiness, and are never silently rerun on apply.
        ki_maintenance_wofost.require_runtime_current(report.get("interface_regression"))
    return report
