"""Portable, reviewed repairs and their exact host runtime projections.

This is host provenance, not a readiness receipt or an OS sandbox. Only an
explicitly adopted repair can become reusable; old machine-bound repairs are
never reverse-translated. A changed source/context requires a new review.
"""
from __future__ import annotations

from dataclasses import is_dataclass
from .manifest import document as manifest_document
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import tempfile
import uuid

from . import firstrun, helper_identity, ki_copy, ki_guard, ki_tree, ki_verification, port
from . import software_verification
from .catalog import KI, installation_platform
from .manifest import Manifest

POLICY = "portable-ki-adaptation-v1"
PROJECTION_POLICY = "kiss-role-projection-v2"
MAX_RECORD_BYTES = 8 * 1024 * 1024


class AdaptationError(ValueError):
    pass


def _home():
    return Path(os.environ.get("GEOFORGE_KI_ADAPTATION_HOME") or
                firstrun.data_dir() / "ki-adaptations").resolve()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _digest(root):
    value = ki_verification.content_digest(Path(root))
    if not value:
        raise AdaptationError(f"Cannot fingerprint a contained KI tree: {root}")
    return value


def _receipts():
    from . import flowgate
    return flowgate.load().receipts


def _seal(value):
    return _receipts().sign(_home(), dict(value))


def _auth(value):
    if (not isinstance(value, dict) or not _receipts().verify(_home(), value)
            or value.get("policy") != POLICY or value.get("schema_version") != 1):
        raise AdaptationError("Adaptation provenance is missing, invalid or from another policy")
    return value


def _read(path):
    path = ki_guard._io(path)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > MAX_RECORD_BYTES:
        raise AdaptationError("Invalid adaptation record")
    try:
        return _auth(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, TypeError, ValueError) as exc:
        raise AdaptationError(f"Cannot read authentic adaptation provenance: {exc}") from exc


def _write(path, value):
    doc = _seal(value)
    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    if len(payload.encode()) > MAX_RECORD_BYTES:
        raise AdaptationError("Adaptation record is too large")
    path = ki_guard._io(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return doc


def _base():
    return {"schema_version": 1, "policy": POLICY}


def _location(live):
    return _home() / "projections" / (_hash(os.path.normcase(str(Path(live).absolute()))) + ".json")


def _separate(root):
    root = Path(root).absolute()
    if root == _home() or root in _home().parents:
        raise AdaptationError("Adaptation authority must stay outside KI trees")


def _remember(root):
    """Retain bounded exact bytes once; a modified cache never repairs itself."""
    root = Path(root)
    _separate(root)
    digest = _digest(root)
    target = _home() / "sources" / digest
    with ki_guard.operation(target):
        if target.exists():
            if _digest(target) != digest:
                raise AdaptationError("Retained portable KI was modified; restore its exact source")
        else:
            ki_guard._io(target.parent).mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(".incoming-" + uuid.uuid4().hex)
            ki_copy.copytree(ki_guard._io(root), ki_guard._io(temporary))
            if _digest(root) != digest or _digest(temporary) != digest:
                raise AdaptationError("KI changed while retaining its portable source")
            ki_guard._io(temporary).rename(ki_guard._io(target))
    return target, digest


def _retained(path, digest):
    expected = _home() / "sources" / str(digest)
    if Path(path) != expected or _digest(expected) != digest:
        raise AdaptationError("Retained portable KI no longer matches its signed identity")
    return expected


def _prepared_helper(cfg, helper_root=None):
    helper = cfg.roles.get("ki_tools_common")
    if helper_root is not None and (helper is None or Path(helper_root).absolute() != Path(helper).absolute()):
        raise AdaptationError("Supplied helpers are not the runtime's saved shared-helper binding")
    return (helper_identity.prepared_source_identity(Path(helper))
            if helper and (Path(helper) / helper_identity.MARKER).exists() else None)


def _context(source, cfg, *, model=None, library_root=None, manifest=None, helper_root=None):
    model = model or Path(source).name
    ki = KI(model, Path(source))
    manifest = manifest if manifest is not None else (Manifest.load(ki.manifest) if ki.manifest else None)
    if manifest is not None and getattr(manifest, "model", model) != model:
        raise AdaptationError("Adaptation manifest belongs to another model")
    recipe = manifest_document(manifest) if is_dataclass(manifest) else manifest
    prepared = _prepared_helper(cfg, helper_root)
    expected = (helper_identity.source_identity(Path(library_root))
                if library_root is not None and (Path(library_root) / "ki_tools_common").is_dir() else None)
    if expected is not None and prepared is not None and prepared != expected:
        raise AdaptationError("Prepared shared helpers differ from the selected portable helper source")
    # The cache marker only proves local consistency. Reuse additionally needs
    # the host-selected source comparison, captured in signed provenance here.
    helpers = prepared if prepared is not None and expected == prepared else None
    from . import ki_fresh_paths
    return {"model": model, "upstream_digest": _digest(source),
            "platform": installation_platform(), "architecture": platform.machine().casefold(),
            "effective_manifest_digest": _hash(recipe), "helper_source_digest": helpers,
            "projection_policy": PROJECTION_POLICY,
            "path_normalizer": ki_fresh_paths.source_digest() if model == "WOFOST" else None}


def _selected(context):
    if context["helper_source_digest"] is None:
        return None, None
    path = _home() / "registry" / (_hash(context) + ".json")
    doc = _read(path)
    if doc is None:
        registry = _home() / "registry"
        records = list(registry.glob("*.json")) if registry.exists() else []
        if len(records) > 1000:
            raise AdaptationError("Portable adaptation registry exceeds its bounded inventory")
        previous_adaptations = []
        for prior_path in sorted(records):
            prior = _read(prior_path)
            previous = prior.get("context", {})
            if all(previous.get(key) == context[key] for key in ("model", "platform", "architecture")):
                previous_adaptations.append({key: prior[key] for key in
                    ("adaptation_id", "context", "portable_root", "portable_digest")})
        notice = ({"reason": "The upstream KI, installation recipe, shared helpers or projection "
                   "policy changed. The previous repair was retained but was not replayed; "
                   "the newly selected upstream requires normal project verification.",
                   "previous_adaptations": previous_adaptations} if previous_adaptations else None)
        return None, notice
    if doc.get("context") != context:
        raise AdaptationError("Portable adaptation context does not match this source/runtime")
    root = _retained(doc["portable_root"], doc["portable_digest"])
    ki_verification.require_current(root, doc["portable_report"], kind=ki_verification.detect_kind(root))
    return doc, None


def inspection_models() -> frozenset[str]:
    """Authenticate the bounded repair index without creating keys or copies."""
    registry = _home() / "registry"
    records = list(registry.glob("*.json")) if registry.exists() else []
    if len(records) > 1000:
        raise AdaptationError("Portable adaptation registry exceeds its bounded inventory")
    names = set()
    for path in records:
        doc = _read(path)
        context = doc.get("context") if isinstance(doc, dict) else None
        model = context.get("model") if isinstance(context, dict) else None
        if (not isinstance(doc, dict) or doc.get("kind") != "portable_adaptation" or not isinstance(model, str)
                or not model or model.strip() != model or any(c in model for c in "/\\\0")
                or model in {".", ".."}):
            raise AdaptationError("Invalid portable adaptation registry identity")
        names.add(model)
    return frozenset(names)


def inspection_source(source, cfg, *, model, library_root=None, manifest=None) -> dict:
    """Resolve a known repair for read-only intake, never grant runtime readiness.

    Matches the portable source/helper/recipe context, before runtime projection.
    A checked legacy installation marker can support inspection against the
    host-selected helper SOURCE, but never proves prepared runtime readiness.
    Missing setup/changed contexts are explicit upstream views; invalid
    provenance is an error. Enumerate inspection_models to avoid hashing all KIs.
    """
    source = Path(source).absolute()
    ki_guard.require_intact(source, required=False)
    base = {"model": model, "source_root": str(source), "root": str(source),
            "source_digest": _digest(source), "origin": "upstream", "adaptation_id": None,
            "portable_report": None, "can_run": False, "notice": ""}
    if cfg is None:
        return {**base, "notice": "A previous approved repair exists, but no saved installation is available "
                "to check its compatibility. Inspecting upstream KI; setup and reconciliation are still required."}
    # Validate any saved marker, including its exact file inventory. A legacy
    # marker has no source identity, while a new project will prepare current
    # helpers later. Neither absence nor corrupt metadata creates authority.
    prepared = _prepared_helper(cfg)
    helper = cfg.roles.get("ki_tools_common")
    marker_exists = helper is not None and (Path(helper) / helper_identity.MARKER).is_file()
    expected = (helper_identity.source_identity(Path(library_root)) if library_root is not None
                and (Path(library_root) / "ki_tools_common").is_dir() else None)
    if not marker_exists or expected is None:
        return {**base, "notice": "A previous approved repair exists, but its shared-helper context is "
                "unavailable or changed. Inspecting upstream KI; reconcile the saved setup before reusing the repair."}
    # Inspection is portable-source selection, not runtime materialisation.
    # Keep _context/materialise's prepared-helper checks unchanged: derive the
    # common fields without a library, then bind the trusted selected SOURCE.
    context = _context(source, cfg, model=model, manifest=manifest)
    context["helper_source_digest"] = expected
    selected, reconciliation = _selected(context)
    if selected is None:
        return {**base, "notice": (reconciliation or {}).get("reason") or
                "No compatible approved repair exists for this installation context. Inspecting upstream KI; "
                "the retained repair requires reconciliation before reuse."}
    return {**base, "root": selected["portable_root"], "origin": "approved_portable_repair",
            "adaptation_id": selected["adaptation_id"], "portable_digest": selected["portable_digest"],
            "portable_report": selected["portable_report"], "context": context,
            "helper_context": "selected_source", "saved_helper_source": prepared,
            "notice": ("KDT-approved compatible portable repair for inspection only. Its placeholders are "
                      "portable; current runtime helper preparation, project path adaptation, preflight "
                      "and plan approval happen later." +
                      (" Inspection uses the current host-selected helper source; the saved installation "
                       "helpers are legacy or older and do not prove current runtime readiness."
                       if prepared != expected else ""))}


def require_inspection_current(view: dict) -> None:
    """A captured intake view cannot hide changed package/report bytes."""
    if view.get("source_digest") and _digest(view["source_root"]) != view["source_digest"]:
        raise AdaptationError("Upstream KI changed during intake; refresh the effective read view")
    if view.get("origin") == "approved_portable_repair":
        root = _retained(view["root"], view["portable_digest"])
        ki_verification.require_current(root, view["portable_report"], kind=ki_verification.detect_kind(root))


def _projection_doc(source, dest, cfg, context, selected, *, library_root=None, reconciliation=None,
                    path_projection=None, target_root=None):
    upstream, upstream_digest = _remember(source)
    if upstream_digest != context["upstream_digest"]:
        raise AdaptationError("Portable source changed before its projection provenance was recorded")
    portable = selected["portable_root"] if selected else str(upstream)
    portable_digest = selected["portable_digest"] if selected else upstream_digest
    if path_projection is not None:
        from . import ki_fresh_paths
        # Persist evidence against retained exact source bytes, never a
        # disposable download/draft which may disappear after adoption.
        path_projection = ki_fresh_paths.validate_fresh_projection(Path(portable), dest, cfg,
            target_root=target_root or dest, ordinary_digest=path_projection["ordinary_digest"],
            ordinary_files=path_projection["ordinary_files"])
        ki_fresh_paths.require_fresh_current(path_projection)
    return {**_base(), "kind": "projection", "live_root": str(Path(dest).absolute()),
            "context": context, "context_id": _hash(context),
            "upstream_root": str(upstream), "upstream_digest": upstream_digest,
            "portable_root": portable, "portable_digest": portable_digest,
            "portable_report": selected["portable_report"] if selected else None,
            "adaptation_id": selected["adaptation_id"] if selected else None,
            "projected_digest": _digest(dest),
            "runtime_identity": software_verification.runtime_identity(cfg),
            "source_root": str(Path(source).absolute()),
            "library_root": str(Path(library_root).absolute()) if library_root else None,
            "reconciliation_needed": reconciliation is not None,
            "reconciliation": reconciliation,
            "logical_target": str(Path(target_root or dest).absolute()),
            "path_projection": path_projection,
            "reusable": context["helper_source_digest"] is not None}


def materialise(source, dest, cfg, *, model=None, library_root=None, manifest=None, helper_root=None,
                target_root=None):
    """Host-only fresh projection; never update an existing active KI or grant readiness."""
    with ki_guard.operation(Path(dest)):
        return _materialise(source, dest, cfg, model=model, library_root=library_root,
                            manifest=manifest, helper_root=helper_root, target_root=target_root)


def _materialise(source, dest, cfg, *, model=None, library_root=None, manifest=None, helper_root=None,
                 target_root=None):
    source, dest = Path(source), port.validate_materialisation_destination(Path(dest))
    _separate(dest)
    if dest.exists() and any(dest.iterdir()):
        raise AdaptationError("Active KI is preserved; projection requires a new empty destination")
    ki_guard.require_intact(source, required=False)
    context = _context(source, cfg, model=model, library_root=library_root,
                       manifest=manifest, helper_root=helper_root)
    runtime_before = software_verification.runtime_identity(cfg)
    selected, reconciliation = _selected(context)
    portable = Path(selected["portable_root"]) if selected else source
    report, path_projection = project_runtime(portable, dest, cfg, model=context["model"],
                                               target_root=target_root or dest)
    if report.unresolved or report.corrupted:
        return report
    if (context != _context(source, cfg, model=model, library_root=library_root,
                            manifest=manifest, helper_root=helper_root)
            or runtime_before != software_verification.runtime_identity(cfg)):
        raise AdaptationError("Portable KI context changed during projection")
    if selected is not None:
        ki_verification.require_current(portable, selected["portable_report"])
    doc = _projection_doc(source, dest, cfg, context, selected, library_root=library_root,
                          reconciliation=reconciliation, path_projection=path_projection,
                          target_root=target_root)
    if doc["runtime_identity"] != runtime_before:
        raise AdaptationError("Runtime configuration changed before its projection provenance was recorded")
    ki_guard.enroll(dest)
    _write(_location(dest), doc)
    return report


def project_runtime(source, dest, cfg, *, model, target_root):
    """Materialise a new KI with one exact host path overlay, without approval.

    Physical staging and logical deployment paths are separate. This helper
    neither enrolls a KI nor grants KDT, setup, preflight or model readiness.
    All KI projection callers use it; shared helper packages still use port.
    """
    from . import ki_fresh_paths
    source = Path(source).absolute()
    dest = port.validate_materialisation_destination(Path(dest).absolute())
    if dest.exists() and any(dest.iterdir()):
        raise AdaptationError("KI projection requires a new empty destination; active files were preserved")
    ki_guard.require_intact(source, required=False)
    source_before = _digest(source)
    runtime_before = software_verification.runtime_identity(cfg)
    try:
        changes = ki_fresh_paths.expected_fresh_changes(source, model, cfg, target_root=target_root)
        runtime_paths = ki_fresh_paths._fresh_runtime(cfg) if changes else None
    except (ValueError, OSError, SyntaxError, TypeError) as error:
        raise AdaptationError(f"Unsupported {model} fresh path contract; verify a reconciled KI before use: {error}") from error
    report = port.materialise(source, dest, cfg)
    if report.unresolved or report.corrupted:
        return report, None
    path_projection = None
    if changes:
        ordinary_digest = ki_fresh_paths._tree_digest(dest)
        ordinary_files = ki_fresh_paths.tree_files(dest)
        for name, value in changes.items():
            target = dest / name
            ki_fresh_paths._ordinary(target)  # Ordinary, unshared files only.
            target.write_bytes(value)
        path_projection = ki_fresh_paths.validate_fresh_projection(
            source, dest, cfg, target_root=target_root,
            ordinary_digest=ordinary_digest, ordinary_files=ordinary_files)
        if path_projection["runtime"] != runtime_paths:
            raise AdaptationError("Runtime/helper bytes changed during fresh path projection")
        ki_fresh_paths.require_fresh_current(path_projection)
    if (_digest(source) != source_before
            or software_verification.runtime_identity(cfg) != runtime_before):
        raise AdaptationError("Source or saved runtime context changed during KI projection")
    return report, path_projection


def projection(live, cfg):
    """Read authentic current lineage. Legacy absence is None; corruption is an error."""
    live = Path(live).absolute()
    doc = _read(_location(live))
    if doc is None:
        return None
    if (doc.get("kind") != "projection" or doc.get("live_root") != str(live)
            or doc.get("projected_digest") != _digest(live)
            or doc.get("runtime_identity") != software_verification.runtime_identity(cfg)
            or doc.get("context_id") != _hash(doc.get("context"))):
        raise AdaptationError("KI projection or its runtime binding changed; retained provenance is stale")
    ki_guard.require_intact(live)
    _retained(doc["upstream_root"], doc["upstream_digest"])
    root = _retained(doc["portable_root"], doc["portable_digest"])
    expected_helpers = doc["context"].get("helper_source_digest")
    prepared_helpers = _prepared_helper(cfg)
    if expected_helpers is not None and prepared_helpers != expected_helpers:
        raise AdaptationError("Prepared shared helpers no longer match the signed portable lineage")
    if doc.get("portable_report"):
        ki_verification.require_current(root, doc["portable_report"])
    if doc.get("path_projection") is not None:
        from . import ki_fresh_paths
        report = doc["path_projection"]
        if (report.get("logical_target") != doc.get("logical_target")
                or report.get("policy_sha256") != doc["context"].get("path_normalizer")):
            raise AdaptationError("Fresh projection policy/target differs from its signed lineage")
        ki_fresh_paths.require_fresh_current(report, candidate_root=live)
    return doc


# Only path spellings newly introduced into executable/configuration text are
# rejected. Existing upstream provenance is not rewritten, and quoted URLs are
# not mistaken for file paths. Bound values are checked independently below.
_ABSOLUTE = re.compile(r'''(?<![\w:/<])(?:[A-Za-z]:[/\\][^\s\"'<>|]+|\\\\[^\s\"'<>|]+|/(?:[^/\s\"'<>]+/)*[^/\s\"'<>]+)''')
_KI_DOC_PATH = re.compile(r'''(?<![\w{])\{KI\}/(?P<relative>[\w./-]+)(?=$|[\s`"'|])''')
_RUNTIME_SUFFIXES = port.TEXT_SUFFIXES | {".ps1", ".bat", ".cmd", ".prj", ".xml", ".ctl"}


def _path_spellings(root):
    result = {}
    for entry in ki_tree.scan(root).entries:
        rel = Path(entry.relative)
        if entry.kind != "file" or rel.suffix.casefold() not in _RUNTIME_SUFFIXES:
            continue
        raw = (Path(root) / rel).read_bytes()
        # This is lexical inspection only; source/test-case bytes are never
        # transcoded. Latin-1 scientific inputs may contain a degree symbol
        # next to an ASCII machine path. Do not silently skip the whole file.
        if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
            text = raw.decode("utf-32", errors="replace")
        elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = raw.decode("utf-16", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
        result[entry.relative] = text.replace("\0", "")
    return result


def _portable_changes(base, candidate, cfg):
    previous = _path_spellings(base)
    bound = {str(value).replace("\\", "/") for value in
             [cfg.root, cfg.python, *cfg.roles.values()] if len(str(value)) > 3}
    for name, text in _path_spellings(candidate).items():
        before = previous.get(name, "")
        introduced = _absolute_literals(name, text) - _absolute_literals(name, before)
        normalized, old = text.replace("\\", "/"), before.replace("\\", "/")
        if introduced or any(value in normalized and value not in old for value in bound):
            raise AdaptationError(f"Portable repair introduces a machine path in {name}; use KI path roles")


def _absolute_literals(name, text):
    if not text:
        return set()
    invalid_doc_paths = set()
    if Path(name).suffix.casefold() == ".md":
        # The generated tool index documents paths as {KI}/tools/example.py.
        # This is a relative documentation spelling, not a runtime expansion.
        # Mask only that exact canonical span; adjacent machine paths and
        # traversal/drive/backslash spellings remain subject to the guard.
        def doc_path(match):
            parts = match["relative"].split("/")
            if any(p in ("", ".", "..") for p in parts):
                invalid_doc_paths.add(match[0])
                return match[0]
            return " " * len(match[0])
        text = _KI_DOC_PATH.sub(doc_path, text)
    if Path(name).suffix.casefold() != ".py":
        return set(_ABSOLUTE.findall(text)) | invalid_doc_paths
    # Inspect values, not operators: Python `value /2` is division. A later
    # '/suffix' fragment in an f-string is not an independent absolute path.
    values = []
    def collect(node):
        if isinstance(node, ast.JoinedStr):
            prefix = ""
            for value in node.values:
                if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                    break
                prefix += value.value
            values.append(prefix)
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    collect(value)
            return
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            values.append(node.value)
        for child in ast.iter_child_nodes(node):
            collect(child)
    try:
        collect(ast.parse(text))
    except SyntaxError as exc:
        raise AdaptationError(f"Portable repair has invalid Python in {name}") from exc
    return {path for value in values for path in _ABSOLUTE.findall(value)}


def _adds_same_engine_data_requirements(before, after):
    """Only strengthen file requirements from the already pinned engine source.

    This does not authorize a new source, relocation, engine recipe or replacement
    contract. KDT acceptance and exact runtime projection/adoption remain separate.
    Keep registry lookup bound to the original upstream context: the new required
    files belong to the reviewed repair, not an invented upstream revision.
    """
    from . import runtime_data
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    contract = after.get("runtime_data")
    unchanged = {key: value for key, value in after.items() if key != "runtime_data"}
    if before.get("runtime_data") is not None or contract is None or unchanged != before:
        return False
    try:
        runtime_data.validate_contract(contract)
        acquire = before.get("acquire")
        if (not isinstance(acquire, dict) or acquire.get("strategy") != "build"
                or acquire.get("repo") != contract["source"]["repo"]
                or acquire.get("ref") != contract["source"]["commit"]):
            return False
        # The contract parser already requires an exact 40-hex commit. Require
        # an explicit canonical checkout path instead of guessing the model name.
        install_dir = PurePosixPath(runtime_data._relative(before.get("install_dir")))
        target = PurePosixPath(contract["target"]["path"])
        subtree = target.relative_to(install_dir)
        if not subtree.parts:
            return False
        return all(item["source"] == (subtree / item["path"]).as_posix()
                   for item in contract["files"])
    except (ValueError, TypeError, KeyError):
        return False


def _same_recipe(base, candidate, model):
    def identity(root):
        path = KI(model, Path(root)).manifest
        return manifest_document(Manifest.load(path)) if path else None
    before, after = identity(base), identity(candidate)
    if before != after and not _adds_same_engine_data_requirements(before, after):
        raise AdaptationError("Reusable repair changes the effective installation recipe; "
                              "only new required data from the same pinned engine checkout may "
                              "be added without a separate setup-recipe review")


def prepare_registration(live, cfg, portable, portable_report, runtime_candidate, runtime_report):
    """Prepare exact evidence before adoption; this does not publish reuse authority."""
    origin = projection(live, cfg)
    if origin is None or not origin.get("reusable"):
        raise AdaptationError("Reusable repair requires proven portable KI and helper provenance")
    from . import ki_fresh_paths
    if (origin["context"].get("projection_policy") != PROJECTION_POLICY
            or (origin["context"].get("model") == "WOFOST"
                and origin["context"].get("path_normalizer") != ki_fresh_paths.source_digest())):
        raise AdaptationError("Portable lineage uses an older path projection policy; reconcile and review its source before reuse")
    portable, runtime_candidate = Path(portable), Path(runtime_candidate)
    ki_verification.require_current(portable, portable_report, kind=ki_verification.detect_kind(portable))
    ki_verification.require_current(runtime_candidate, runtime_report, kind=ki_verification.detect_kind(runtime_candidate))
    _same_recipe(Path(origin["portable_root"]), portable, origin["context"]["model"])
    _portable_changes(Path(origin["portable_root"]), portable, cfg)
    _home().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="projection-check-", dir=_home()) as scratch:
        expected = Path(scratch) / "ki"
        result, expected_paths = project_runtime(portable, expected, cfg,
            model=origin["context"]["model"], target_root=live)
        if result.unresolved or result.corrupted or _digest(expected) != _digest(runtime_candidate):
            raise AdaptationError("Runtime candidate is not the exact projection of the portable repair")
        path_projection = None
        if expected_paths is not None:
            from . import ki_fresh_paths
            path_projection = ki_fresh_paths.validate_fresh_projection(portable, runtime_candidate, cfg,
                target_root=live, ordinary_digest=expected_paths["ordinary_digest"],
                ordinary_files=expected_paths["ordinary_files"])
    retained, digest = _remember(portable)
    ki_verification.require_current(retained, portable_report)
    if path_projection is not None:
        path_projection = ki_fresh_paths.validate_fresh_projection(retained, runtime_candidate, cfg,
            target_root=live, ordinary_digest=path_projection["ordinary_digest"],
            ordinary_files=path_projection["ordinary_files"])
        ki_fresh_paths.require_fresh_current(path_projection)
    ki_verification.require_current(runtime_candidate, runtime_report)
    if projection(live, cfg) != origin:
        raise AdaptationError("Project lineage changed while preparing its reusable repair")
    return _seal({**_base(), "kind": "prepared_registration", "id": uuid.uuid4().hex,
                  "origin": origin, "portable_root": str(retained), "portable_digest": digest,
                  "portable_report": portable_report, "runtime_report": runtime_report,
                  "path_projection": path_projection,
                  "runtime_digest": _digest(runtime_candidate)})


def register(prepared, live, cfg):
    """Publish reusable portable bytes only after exact reviewed runtime adoption."""
    _auth(prepared)
    if prepared.get("kind") != "prepared_registration":
        raise AdaptationError("No prepared portable repair registration")
    live = Path(live).absolute()
    origin = prepared["origin"]
    if (origin.get("live_root") != str(live)
            or origin.get("runtime_identity") != software_verification.runtime_identity(cfg)):
        raise AdaptationError("Portable repair belongs to another project/runtime binding")
    if _prepared_helper(cfg) != origin["context"].get("helper_source_digest"):
        raise AdaptationError("Prepared shared helpers no longer match the signed portable lineage")
    with ki_guard.operation(live):
        previous = _read(_location(live))
        if previous != origin:
            raise AdaptationError("Projection lineage changed before repair registration")
        baseline = ki_guard.require_intact(live)
        if (baseline.get("origin") != "verified_candidate"
                or baseline.get("digest") != prepared["runtime_digest"]):
            raise AdaptationError("Portable repair has not been adopted as the exact verified runtime KI")
        ki_verification.require_current(live, prepared["runtime_report"])
        portable = _retained(prepared["portable_root"], prepared["portable_digest"])
        ki_verification.require_current(portable, prepared["portable_report"])
        context = origin["context"]
        record = {**_base(), "kind": "portable_adaptation", "context": context,
                  "adaptation_id": prepared["id"], "portable_root": str(portable),
                  "portable_digest": prepared["portable_digest"],
                  "portable_report": prepared["portable_report"]}
        updated = {key: value for key, value in origin.items() if key != "signature"}
        updated.update(portable_root=str(portable), portable_digest=prepared["portable_digest"],
                       portable_report=prepared["portable_report"], adaptation_id=prepared["id"],
                       projected_digest=prepared["runtime_digest"], reconciliation_needed=False,
                       reconciliation=None, path_projection=prepared.get("path_projection"),
                       logical_target=str(live))
        if updated["path_projection"] is not None:
            from . import ki_fresh_paths
            ki_fresh_paths.require_fresh_current(updated["path_projection"], candidate_root=live)
        # Publish reuse authority last. A failed projection write cannot leave
        # a new repair available to unrelated projects. If publication fails,
        # keep the valid local lineage and report failure; no new registry
        # authority was issued and the adopted local repair remains intact.
        result = _write(_location(live), updated)
        _write(_home() / "registry" / (_hash(context) + ".json"), record)
        return result
