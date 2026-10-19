"""Derive a fresh project from an exact, KDT-adopted setup path repair.

The setup approval authorizes only the same recognized path recipe. A new
project candidate still passes its own KDT gate and guarded adoption. Neither
the installed readiness nor scientific results are inherited. Original ordinary
projection records remain unchanged; this separate signed record composes them.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tomllib
import uuid

from . import (helper_identity, implementation_identity, install, ki_adaptations as adapt,
               ki_copy, ki_guard, ki_investigation as investigation,
               ki_maintenance as core, ki_maintenance_registry as registry,
               ki_path_contracts as contracts, ki_verification, paths,
               project_paths, setup, setup_ki_repair)
from .manifest import document as manifest_document

POLICY = "project-from-setup-path-maintenance-v1"


def _policy():
    return implementation_identity.module_digest(sys.modules[__name__])


def _ordinary_path(path):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise ValueError("Project maintenance refuses aliased paths")
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Project maintenance refuses links and reparse points")
    return path


def _location(live):
    return adapt._home() / "project-setups" / adapt._hash(
        os.path.normcase(str(Path(live).absolute())))[:24] / "record.json"


def _read(live):
    path = _ordinary_path(_location(live))
    if not path.exists():
        if path.parent.exists():
            raise ValueError("Project maintenance derivation record is missing; its authority was preserved")
        return None
    if not path.is_file() or path.stat().st_size > adapt.MAX_RECORD_BYTES:
        raise ValueError("Invalid project maintenance derivation record")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(doc, dict) or not adapt._receipts().verify(adapt._home(), doc)
            or doc.get("policy") != POLICY or doc.get("implementation") != _policy()):
        raise ValueError("Project maintenance derivation is unauthenticated or stale")
    return doc


def _write(live, doc):
    path = _ordinary_path(_location(live))
    sealed = adapt._receipts().sign(adapt._home(), dict(doc))
    raw = json.dumps(sealed, ensure_ascii=False, indent=2).encode("utf-8")
    if len(raw) > adapt.MAX_RECORD_BYTES:
        raise ValueError("Project maintenance derivation exceeds its size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(raw)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return sealed


def has_setup_adoption(setup_root) -> bool:
    """Whether a setup maintenance pointer exists; only then is helper identity consulted."""
    return (investigation._base(Path(setup_root)) / "setup-adoption.json").exists()


def _setup(source, model, setup_root, library_root, manifest):
    # Legacy/unmaintained installations impose no new prerequisites. Once a
    # pointer exists, the strict adapter owns all validation and never falls back.
    if not has_setup_adoption(setup_root):
        return None
    record = setup_ki_repair.require_adoption(setup_root, source_root=source,
        library_root=library_root, manifest=manifest)
    if record is None:
        return None
    doc = investigation._load(Path(setup_root), record["job_id"])
    report = doc["verification"]["report"]
    recipe = report.get("maintenance_recipe")
    supported = {"SHAW": "shaw_runtime_paths", "EPANET": "epanet_runtime_paths"}
    if supported.get(model) != recipe or report.get("name") != model:
        raise ValueError("Setup maintenance has no supported project path derivation")
    verifier = registry.recipe_verifier(recipe)
    return record, report, verifier, setup.load_runtime_config(Path(setup_root))


def _project(live, cfg, model, shared):
    root, live = _ordinary_path(cfg.root), _ordinary_path(live)
    if live != project_paths._model_home(root, model) / "ki" or root == Path(shared.root):
        raise ValueError("Project derivation requires its own exact models/<KI>/ki target")
    contracts.config_identity(cfg)
    if str(cfg.python) != str(shared.python) or any(
            cfg.roles.get(role) != shared.roles.get(role)
            for role in ("binaries", "python_env", "home")):
        raise ValueError("Project runtime does not match the maintained installation")
    project_paths._overrides(cfg, root, model, project_paths._known_models(root), strict=True)
    helper = _ordinary_path(cfg.roles["ki_tools_common"])
    if not helper.is_relative_to(live.parent) or helper.is_relative_to(live):
        raise ValueError("Project helpers must belong to this model outside its KI")
    helper_identity.checked_marker(helper)
    return root, live


def _assets(setup_report, cfg, shared, model):
    if model != "SHAW":
        return {}
    from . import ki_maintenance_shaw
    distribution = setup_report["path_binding_regression"]["runtime"]["distribution"]
    origin = _ordinary_path(Path(shared.root) / "model/shaw/Shaw303")
    if (distribution.get("root") != str(origin)
            or set(distribution.get("inputs", {})) != set(ki_maintenance_shaw.CASE_SHA256S)):
        raise ValueError("Unsupported setup reference-asset inventory")
    result = {}
    for name, identity in distribution["inputs"].items():
        source = origin / name
        raw = contracts._ordinary(source)
        if contracts._file_identity(source) != identity:
            raise ValueError("Setup reference assets changed")
        relative = "model/shaw/Shaw303/" + name
        destination = _ordinary_path(Path(cfg.root) / relative)
        result[relative] = {"source": str(source), "destination": str(destination),
            "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return result


def _check_assets(assets):
    for item in assets.values():
        for key in ("source", "destination"):
            raw = contracts._ordinary(_ordinary_path(item[key]))
            if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                raise ValueError("Project reference assets changed")


def _saved_config(path):
    # Do not use KissConfig._parse: its compatibility recovery can rewrite TOML.
    # Maintenance admission must leave a malformed or differently bound file
    # untouched, exactly like the sealed path recipe's saved-config reader.
    document = tomllib.loads(contracts._ordinary(path).decode("utf-8"))
    kiss = document.get("kiss", {})
    cfg = paths.KissConfig.default(Path(kiss.get("root", path.parent)))
    cfg.roles.update({key: Path(value).expanduser()
                      for key, value in document.get("paths", {}).items()})
    cfg.python = kiss.get("python", cfg.python)
    cfg.relocation = kiss.get("relocation", cfg.relocation)
    return cfg


def _context(source, live, cfg, model, setup_root, library_root, manifest, authority):
    record, report, verifier, shared = authority
    _project(live, cfg, model, shared)
    context = adapt._context(source, cfg, model=model, library_root=library_root, manifest=manifest)
    if context != record["binding"]["context"] or context.get("helper_source_digest") is None:
        raise ValueError("Project source or shared-helper source differs from setup maintenance")
    recipe = manifest_document(manifest) if not isinstance(manifest, dict) else manifest
    # Readiness/preflight records may be refreshed without re-adopting code.
    # Authenticate the complete current record above, but retain only the
    # immutable approval/activation authority, never installed readiness.
    adoption = {key: record[key] for key in ("policy", "status", "root", "active_root",
        "job_id", "verification_id", "old_digest", "adopted_digest", "binding",
        "created_at", "applied_at")}
    return {"model": model, "live_root": str(live), "project_root": str(cfg.root),
        "source_root": str(Path(source).absolute()), "setup_root": str(Path(setup_root).absolute()),
        "library_root": str(Path(library_root).absolute()), "effective_manifest": recipe,
        "setup_adoption_digest": adapt._hash(adoption), "setup_report_digest": adapt._hash(report),
        "context": context, "project_config": contracts._config_values(cfg),
        "recipe": report["maintenance_recipe"], "recipe_policy": verifier.policy_digest(),
        "assets": _assets(report, cfg, shared, model)}


def _validate(live, cfg, *, source, model, setup_root, library_root, manifest,
              historical=False, retained=None):
    live = _ordinary_path(live)
    doc = _read(live)
    if doc is None:
        return None
    if doc.get("status") != "complete":
        raise ValueError("Project maintenance derivation is incomplete; start a fresh project or recover it")
    authority = _setup(source, model, setup_root, library_root, manifest)
    if authority is None or doc.get("binding") != _context(
            source, live, cfg, model, setup_root, library_root, manifest, authority):
        raise ValueError("Project maintenance origin or runtime binding changed")
    baseline = doc["ordinary_projection"]
    if adapt._read(adapt._location(live)) != baseline:
        raise ValueError("Original project projection changed after derivation")
    adapt._auth(baseline)
    if (baseline.get("live_root") != str(live) or baseline.get("logical_target") != str(live)
            or baseline.get("context") != doc["binding"]["context"]
            or baseline.get("projected_digest") != doc["project_source"]["base_digest"]):
        raise ValueError("Project derivation does not match its ordinary baseline")
    adapt._retained(baseline["upstream_root"], baseline["upstream_digest"])
    adapt._retained(baseline["portable_root"], baseline["portable_digest"])
    adapt.require_path_binding(baseline, cfg)
    if baseline.get("portable_report"):
        ki_verification.require_current(Path(baseline["portable_root"]), baseline["portable_report"])
    if baseline.get("path_projection") is not None:
        raise ValueError("Runtime fingerprint overlays require a separate supported derivation")
    ki_guard.require_intact(live)
    if doc.get("preflight_passed") is not False or doc.get("native_verified") is not False:
        raise ValueError("Project maintenance bytes or assurance changed")
    verifier = authority[2]
    if historical:
        # A later authenticated project edit can legitimately change the active
        # digest. The immutable complete record attests that this exact earlier
        # candidate passed its own KDT gate. Recheck every non-active binding and
        # exact path-only delta; the caller separately proves the later chain.
        candidate = _ordinary_path(retained if retained is not None else
                                   _location(live).parent / "candidate")
        if candidate == live or candidate.is_relative_to(live):
            raise ValueError("Historical derivation requires a separate retained candidate")
        report = doc["project_report"]
        base = core.require_source(doc["project_source"], name=model)
        runtime = report["path_binding_regression"]
        if (ki_verification.content_digest(candidate) != doc["projected_digest"]
                or not core._authentic(candidate, report)
                or report.get("policy_digest") != verifier.policy_digest()
                or report.get("source") != doc["project_source"]
                or report.get("candidate_digest") != doc["projected_digest"]
                or any(report.get(k) != v for k, v in core._engine().items())
                or verifier._runtime(cfg, live) != runtime["runtime"]
                or runtime.get("policy_digest") != verifier.policy_digest()):
            raise ValueError("Historical project KDT evidence or runtime changed")
        changes = verifier._changes(base, candidate, model, cfg, live)
        if changes != report["changes"] or changes != runtime["changes"]:
            raise ValueError("Retained project derivation exceeds its exact path recipe")
    else:
        if doc.get("projected_digest") != ki_verification.content_digest(live):
            raise ValueError("Project maintenance bytes changed; validate subsequent adoption lineage")
        verifier.require_current(live, doc["project_report"], source=doc["project_source"])
    _check_assets(doc["binding"]["assets"])
    return {**doc, "protected_inventory": doc["project_source"]["protected_inventory"]}


def require_current(live, cfg, *, source, model, setup_root, library_root, manifest):
    """Authenticate exact current derivation; absence alone returns None."""
    return _validate(live, cfg, source=source, model=model, setup_root=setup_root,
        library_root=library_root, manifest=manifest)


def require_baseline(live, cfg, model, *, retained=None):
    """Authenticate a historical derived baseline, never current-live authority.

    A caller accepting a later revision MUST independently validate the complete
    signed project-adoption chain from current guarded bytes to this digest.
    """
    doc = _read(live)
    if doc is None:
        return None
    binding = doc.get("binding", {})
    if binding.get("model") != model:
        raise ValueError("Project maintenance belongs to another model")
    return _validate(live, cfg, source=Path(binding["source_root"]), model=model,
        setup_root=Path(binding["setup_root"]), library_root=Path(binding["library_root"]),
        manifest=binding["effective_manifest"], historical=True, retained=retained)


def require_record(live, cfg, *, model):
    """Read exact signed origins without trusting a caller's ad hoc path fields."""
    doc = _read(live)
    if doc is None:
        return None
    binding = doc.get("binding", {})
    if binding.get("model") != model:
        raise ValueError("Project maintenance belongs to another model")
    return require_current(live, cfg, source=Path(binding["source_root"]), model=model,
        setup_root=Path(binding["setup_root"]), library_root=Path(binding["library_root"]),
        manifest=binding["effective_manifest"])


def materialise(source, live, cfg, *, model, setup_root, library_root, manifest):
    """Return (ordinary PortReport, derivation), or None when no setup repair exists.

    Only fresh targets are accepted. A failed transaction leaves signed pending
    evidence and intact guarded files; continuation cannot treat it as readiness.
    """
    source, live = Path(source).absolute(), _ordinary_path(live)
    authority = _setup(source, model, setup_root, library_root, manifest)
    if authority is None:
        if _read(live) is not None:
            raise ValueError("Project maintenance lost its setup authority")
        return None
    with ki_guard.operation(live):
        install.check_cancelled()
        if _read(live) is not None or live.exists() or ki_guard.is_managed(live):
            raise ValueError("Setup maintenance derivation requires a fresh project KI")
        binding = _context(source, live, cfg, model, setup_root, library_root, manifest, authority)
        assets = binding["assets"]
        for item in assets.values():
            if _ordinary_path(item["destination"]).exists():
                raise ValueError("Project reference asset already exists; nothing will be overwritten")
        if assets and _ordinary_path(Path(cfg.root) / "model/shaw/Shaw303").exists():
            raise ValueError("Project reference-asset directory must be new")
        config_path = _ordinary_path(live.parent / paths.CONFIG_NAME)
        if config_path.exists():
            saved = _saved_config(config_path)
            if contracts._config_values(saved) != contracts._config_values(cfg):
                raise ValueError("Saved project configuration differs; it was preserved")
        pending = {"policy": POLICY, "implementation": _policy(), "status": "pending",
            "binding": binding, "preflight_passed": False, "native_verified": False}
        _write(live, pending)
        live.parent.mkdir(parents=True, exist_ok=True)
        if not config_path.exists():
            with config_path.open("x", encoding="utf-8") as stream:
                stream.write(cfg.dumps())
        for item in assets.values():
            install.check_cancelled()
            destination = _ordinary_path(item["destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(contracts._ordinary(item["source"]))
        _check_assets(assets)
        report = adapt.materialise(source, live, cfg, model=model,
            library_root=library_root, manifest=manifest)
        if report.unresolved or report.corrupted:
            raise ValueError("Project ordinary role projection failed")
        ordinary = adapt.projection(live, cfg)
        if ordinary.get("path_projection") is not None:
            raise ValueError("Unsupported runtime fingerprint overlay")
        project_source = core.capture_source(live, model)
        candidate = _location(live).parent / "candidate"
        ki_copy.copytree(Path(project_source["base_root"]), candidate)
        verifier = authority[2]
        verifier.apply_recipe(candidate, source=Path(project_source["base_root"]),
            recipe=binding["recipe"], name=model, runtime_config=cfg, target_root=live)
        project_report = verifier.verify_candidate(candidate, source=project_source,
            name=model, runtime_config=cfg, target_root=live)
        verifier.require_current(candidate, project_report, source=project_source)
        install.check_cancelled()
        current = _setup(source, model, setup_root, library_root, manifest)
        if current is None or binding != _context(
                source, live, cfg, model, setup_root, library_root, manifest, current):
            raise ValueError("Setup or project context changed during KDT derivation")
        _check_assets(assets)
        ki_guard.activate_maintenance(live, candidate, project_report,
            source=project_source, quiescent=True)
        install.check_cancelled()
        completed = {**pending, "status": "complete", "ordinary_projection": ordinary,
            "project_source": project_source, "project_report": project_report,
            "projected_digest": ki_verification.content_digest(live)}
        _write(live, completed)
        return report, require_current(live, cfg, source=source, model=model,
            setup_root=setup_root, library_root=library_root, manifest=manifest)
