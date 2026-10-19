"""Exact, local SHAW Windows path repair; never a readiness receipt.

The published preflight and runner are recognized in full before replacing only
their path declarations. Existing literature, cases, checks and numeric rules
remain byte-for-byte protected by the maintenance source and KDT package gate.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
import tomllib
from types import SimpleNamespace

import yaml

from . import doctor, helper_identity, ki_maintenance as core, ki_path_contracts as paths_contract
from . import ki_verification, port, published_kdt, software_verification

POLICY = "shaw-windows-runtime-path-maintenance-v1"
RECIPE = "shaw_runtime_paths"
SCOPE = "ki_maintenance_shaw_runtime_candidate"
PREFLIGHT = "preflight_check.py"
RUNNER = "s6_execution/tools/run_shaw.py"
MANIFEST = "knowledge_infrastructure.yaml"
CASE_ROOT = "test_cases/trial/inputs"
CASE_SHA256S = {
    "Trial.30.sit": "924909e7b55c9def43d63882279dfa89358583e63b68cfa5ccb29bb525447fbc",
    "Trial.30.wea": "5643a5d3ddaeda2637730b847b02e462734786545e46fb642ce028fb1604a460",
    "Trial.303.inp": "acbbad31af19d8cea1da8148ad3e3c9144f291d9c4a53b98f6e510cbb11c6e1f",
    "Trial.moi": "e763b117dd1b4570dacf6f03287f20b70a48d69dc23c9d8712396a51f3bf25c9",
    "Trial.tem": "50dfc0d4ad7bb48bcbf2c9b42a526f557e93499761c2f29c354aac2cd56b4b51",
}
# The official Shaw303.zip uses differently cased input/output filenames in its
# control file. Recognize those exact vendor bytes without rewriting the vendor
# distribution or broadening the unchanged KI reference-case input contract.
VENDOR_CONTROL_SHA256 = "1053f1242b51123e3e6453db13c702f8e86b262a8e32e760d63056b26615c20b"
AST_PINS = {
    PREFLIGHT: "8a73235916b77f16f1e7f90c76592f121ee5245b44e50ea61f3b92e4e77b2923",
    RUNNER: "d8e7f5ff9dbb511a29c93d9453e3acc3c487ce04eae3581218aadbf86e23a6bd",
}
_LITERALS = ('KISSPATH_ROOT', 'KISSPATH_FORCING', '\nrun_shaw.py — Execute SHAW model with progress monitoring and input validation.\n\nGenerates the .inp (input/output list) file, validates all input files exist,\nruns SHAW, and checks for successful completion.\n\nUsage:\n    python run_shaw.py         --workdir /path/to/shaw/run         --sit_file site.sit --wea_file weather.wea         --moi_file init.moi --tem_file init.tem         [--mtstep 1] [--iflagsi 1]         [--shaw_exe KISSPATH_BINARIES/shaw/Code/shaw303]\n')


def policy_digest():
    # A later additive dispatcher must not invalidate this validator's receipts.
    return core._hash({"policy": POLICY, "core": core.policy_digest(),
        "implementation": published_kdt._module_identity(sys.modules[__name__]),
        "path_helpers": published_kdt._module_identity(paths_contract),
        "port": published_kdt._module_identity(port),
        "helpers": published_kdt._module_identity(helper_identity)})


def config_identity(cfg):
    result = paths_contract.config_identity(cfg)
    if any(key not in cfg.roles or not Path(cfg.roles[key]).is_absolute()
           for key in ("binaries", "python_env")):
        raise ValueError("SHAW repair requires explicit binary and Python roles")
    if any("KISSPATH_" in str(value) for value in (cfg.root, cfg.python, *cfg.roles.values())):
        raise ValueError("SHAW runtime bindings contain unresolved roles")
    return result


def _target(cfg, target_root):
    config_identity(cfg)
    if target_root is None or not Path(target_root).is_absolute():
        raise ValueError("SHAW repair requires an explicit absolute active KI")
    target, root = Path(target_root).absolute(), Path(cfg.root).absolute()
    if target not in (root / "ki", root / "models" / "SHAW" / "ki") or target.resolve() != target:
        raise ValueError("SHAW repair must bind this setup/project's own KI")
    return target


def _literal(value):
    return json.dumps(str(value).replace("\\", "/"), ensure_ascii=False)


def _recognized(raw, relative, cfg):
    text = raw.decode("utf-8")
    if "\r" in text.replace("\r\n", "") or ("\r\n" in text and "\n" in text.replace("\r\n", "")):
        raise ValueError("SHAW repair refuses mixed newlines")
    tree, canonical = ast.parse(text), ast.parse(text)
    if any(isinstance(node, ast.Constant) and isinstance(node.value, str)
           and "KISSPATH_" in node.value for node in ast.walk(tree)):
        raise ValueError("SHAW maintenance requires the retained materialized KI")
    literals = {port.unsubstitute(value, cfg)[0]: value for value in _LITERALS}
    for node in ast.walk(canonical):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in literals:
            node.value = literals[node.value]
    if paths_contract._hash(paths_contract._ast_value(canonical)) != AST_PINS[relative]:
        raise ValueError("Unrecognized SHAW implementation; path repair cannot change checks")
    return tree


def _replace_rhs(raw, tree, replacements):
    offsets, count = [], 0
    for line in raw.splitlines(keepends=True):
        offsets.append(count)
        count += len(line)
    assignments = paths_contract._assignments(tree)
    if not set(replacements) <= set(assignments):
        raise ValueError("Missing recognized SHAW path declarations")
    spans = []
    for name, replacement in replacements.items():
        node = assignments[name].value
        spans.append((offsets[node.lineno - 1] + node.col_offset,
                      offsets[node.end_lineno - 1] + node.end_col_offset, replacement.encode("utf-8")))
    for start, end, replacement in sorted(spans, reverse=True):
        raw = raw[:start] + replacement + raw[end:]
    return raw


def _binary(cfg):
    # This already-installed native Windows executable is deliberately distinct
    # from the case-insensitive Shaw303 distribution directory. Never search PATH.
    binary = Path(cfg.roles["binaries"]) / "shaw" / "shaw303.exe"
    for path in (binary, *binary.parents):
        info = path.lstat()
        if path.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("SHAW native binding cannot use aliased paths")
    if not binary.is_file() or binary.stat().st_nlink != 1:
        raise ValueError("SHAW repair requires an ordinary installed native file")
    with binary.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError("SHAW manifest PE type requires a real PE executable")
        offset = int.from_bytes(header[60:64], "little")
        if not 64 <= offset <= 1024 * 1024 or offset + 24 > binary.stat().st_size:
            raise ValueError("SHAW PE executable header is malformed")
        stream.seek(offset)
        pe = stream.read(24)
        if (pe[:4] != b"PE\0\0" or int.from_bytes(pe[4:6], "little") not in (0x14c, 0x8664)
                or not int.from_bytes(pe[22:24], "little") & 0x0002
                or int.from_bytes(pe[22:24], "little") & 0x2000):
            raise ValueError("SHAW binding must be an x86/x64 PE executable, not a DLL")
    return binary


def _case_files(base):
    for filename, digest in CASE_SHA256S.items():
        raw = paths_contract._ordinary(Path(base) / CASE_ROOT / filename)
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("SHAW official Trial input bytes changed")


def _distribution(cfg):
    folder = Path(cfg.root) / "model" / "shaw" / "Shaw303"
    files = {}
    for filename, digest in CASE_SHA256S.items():
        path = folder / filename
        raw = paths_contract._ordinary(path)
        allowed = {digest, VENDOR_CONTROL_SHA256} if filename == "Trial.303.inp" else {digest}
        if hashlib.sha256(raw).hexdigest() not in allowed:
            raise ValueError("SHAW installed distribution inputs differ from the official Trial")
        files[filename] = paths_contract._file_identity(path)
    return {"root": str(folder), "inputs": files}


def _manifest(raw, cfg, binary):
    text = raw.decode("utf-8")
    for token in yaml.scan(text):
        if isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken, yaml.tokens.TagToken)):
            raise ValueError("SHAW manifest cannot contain aliases or tags")
    package = paths_contract._mapping(paths_contract._mapping(yaml.compose(text, Loader=yaml.SafeLoader)).get("package"))
    for key, wanted in (("name", "SHAW"), ("language", "fortran")):
        if not isinstance(package.get(key), yaml.ScalarNode) or package[key].value != wanted:
            raise ValueError("SHAW manifest identity changed")
    declared = paths_contract._mapping(package.get("binary"))
    if (set(declared) != {"path", "type"} or not isinstance(declared["type"], yaml.ScalarNode)
            or declared["type"].value != "ELF"):
        raise ValueError("SHAW binary declaration changed")
    path = declared["path"]
    expected = port.unsubstitute("KISSPATH_BINARIES/shaw/shaw", cfg)[0]
    if not isinstance(path, yaml.ScalarNode) or path.tag != "tag:yaml.org,2002:str" or path.value != expected:
        raise ValueError("SHAW manifest path differs from its saved binding")
    edits = [(path.start_mark.index, path.end_mark.index, _literal(binary)),
             (declared["type"].start_mark.index, declared["type"].end_mark.index, "PE")]
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    return text.encode("utf-8")


def _projection(base, name, runtime_config, target_root):
    if name != "SHAW":
        raise ValueError("This exact path recipe applies only to SHAW")
    cfg, base = runtime_config, Path(base)
    _target(cfg, target_root)
    binary = _binary(cfg)
    _case_files(base)
    _distribution(cfg)
    preflight, runner = (paths_contract._ordinary(base / name) for name in (PREFLIGHT, RUNNER))
    p_tree, r_tree = _recognized(preflight, PREFLIGHT, cfg), _recognized(runner, RUNNER, cfg)
    return {
        PREFLIGHT: _replace_rhs(preflight, p_tree, {
            "PYTHON_ENV": "Path(" + _literal(cfg.python) + ")",
            "MANIFEST_BINARY": "Path(" + _literal(binary) + ")",
            "TOOL_DEFAULT_BINARY": "Path(" + _literal(binary) + ")",
        }),
        RUNNER: _replace_rhs(runner, r_tree, {"SHAW_EXE": _literal(binary)}),
        MANIFEST: _manifest(paths_contract._ordinary(base / MANIFEST), cfg, binary),
    }


def expected_changes(base, name, runtime_config=None, *, target_root=None):
    try:
        return _projection(base, name, runtime_config, target_root)
    except (OSError, ValueError, TypeError, AttributeError, SyntaxError, yaml.YAMLError):
        return {}


def apply_recipe(candidate, *, source, recipe, name, runtime_config=None, target_root=None, **unused):
    source, candidate = Path(source).absolute(), Path(candidate).absolute()
    if source == candidate or source in candidate.parents or candidate in source.parents:
        raise ValueError("SHAW maintenance requires a separate draft")
    if recipe != RECIPE:
        raise ValueError("Unsupported SHAW maintenance recipe")
    changes = _projection(source, name, runtime_config, target_root)
    if core._inventory(source) != core._inventory(candidate):
        raise ValueError("SHAW draft differs from its exact source before repair")
    for relative, raw in changes.items():
        (candidate / relative).write_bytes(raw)
    return {"recipe": RECIPE, "changed_files": list(changes),
            "outputs": {path: hashlib.sha256(raw).hexdigest() for path, raw in changes.items()}}


def _changes(base, candidate, name, cfg, target):
    expected = _projection(base, name, cfg, target)
    before, after = core._inventory(base), core._inventory(candidate)
    changed = {path for path in before if before[path] != after.get(path)}
    if set(before) != set(after) or changed != set(expected):
        raise ValueError("Edit exceeds the exact SHAW path maintenance contract")
    for relative, raw in expected.items():
        if paths_contract._ordinary(candidate / relative) != raw:
            raise ValueError("Candidate differs from the exact SHAW path projection")
    return [{"path": p, "before_sha256": before[p]["sha256"], "after_sha256": after[p]["sha256"]}
            for p in sorted(expected)]


def _saved_config(cfg, target):
    # Parsing must never repair or write a user's config while checking evidence.
    from .paths import KissConfig
    path = target.parent / "kiss.toml"
    document = tomllib.loads(paths_contract._ordinary(path).decode("utf-8"))
    saved = KissConfig.default(Path(document.get("kiss", {}).get("root", path.parent)))
    for role, value in document.get("paths", {}).items():
        saved.roles[role] = Path(value).expanduser()
    saved.python = document.get("kiss", {}).get("python", saved.python)
    saved.relocation = document.get("kiss", {}).get("relocation", saved.relocation)
    if config_identity(saved) != config_identity(cfg):
        raise ValueError("SHAW configuration differs from the exact saved runtime")
    return paths_contract._file_identity(path)


def _runtime(cfg, target):
    target = _target(cfg, target)
    helper = Path(cfg.roles["ki_tools_common"])
    binding, files, legacy = helper_identity.checked_marker(helper)
    if legacy:
        raise ValueError("SHAW repair requires current source-bound shared helpers")
    paths_contract._helper_config(binding, cfg)
    manifest = target.parent / "kiss.yaml"
    selection = Path(cfg.root) / ".geoforge" / "ki-library-selection.json"
    return {
        "config": paths_contract._config_values(cfg), "config_sha256": config_identity(cfg),
        "saved_config": _saved_config(cfg, target), "target_ki": str(target),
        "runtime_identity": software_verification.runtime_identity(cfg),
        "selected_python": paths_contract._file_identity(Path(cfg.python)),
        "binary": paths_contract._file_identity(_binary(cfg)),
        "distribution": _distribution(cfg),
        "helper_root": str(helper), "helper_binding": binding, "helper_files": files,
        "helper_marker": paths_contract._file_identity(helper / helper_identity.MARKER),
        "installation_manifest": paths_contract._file_identity(manifest) if manifest.exists() else None,
        "library_selection": paths_contract._file_identity(selection) if selection.exists() else None,
    }


def projection_config(report):
    try:
        value = report["runtime"]["config"]
        if not isinstance(value, dict) or set(value) != {"root", "python", "roles", "relocation"}:
            raise ValueError("Incomplete SHAW configuration evidence")
        cfg = SimpleNamespace(root=Path(value["root"]), python=value["python"],
            roles={k: Path(v) for k, v in value["roles"].items()}, relocation=value["relocation"])
        if config_identity(cfg) != report["runtime"]["config_sha256"]:
            raise ValueError("SHAW configuration identity changed")
        return cfg
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Malformed SHAW runtime evidence") from error


def validate_behavior(base, candidate, cfg, *, target_root):
    """Static exact-path/unchanged-check proof; no candidate or model execution."""
    base, candidate = Path(base).absolute(), Path(candidate).absolute()
    target = _target(cfg, target_root)
    changes = _changes(base, candidate, "SHAW", cfg, target)
    runtime = _runtime(cfg, target)
    source_digest, candidate_digest = ki_verification.content_digest(base), ki_verification.content_digest(candidate)
    if ki_verification.content_digest(target) not in (source_digest, candidate_digest):
        raise ValueError("Active SHAW KI differs from the reviewed source/candidate")
    return {"ok": True, "scope": "shaw_static_path_binding", "policy": POLICY,
        "policy_digest": policy_digest(), "source_root": str(base), "source_digest": source_digest,
        "candidate_digest": candidate_digest, "changes": changes, "runtime": runtime,
        "model_execution": False, "native_execution": False,
        "scientific_validation": False, "preflight_passed": False}


def require_runtime_current(report):
    try:
        if (not isinstance(report, dict) or report.get("ok") is not True
                or report.get("scope") != "shaw_static_path_binding" or report.get("policy") != POLICY
                or report.get("policy_digest") != policy_digest()
                or any(report.get(key) is not False for key in
                       ("model_execution", "native_execution", "scientific_validation", "preflight_passed"))):
            raise ValueError("SHAW requires current exact path-binding evidence")
        cfg = projection_config(report)
        target = _target(cfg, report["runtime"]["target_ki"])
        if _runtime(cfg, target) != report["runtime"]:
            raise ValueError("SHAW runtime, helpers, manifest or saved bindings changed")
        base = Path(report["source_root"])
        if (not base.is_absolute() or ki_verification.content_digest(base) != report["source_digest"]
                or ki_verification.content_digest(target) not in (report["source_digest"], report["candidate_digest"])):
            raise ValueError("SHAW retained/active KI source changed")
        _projection(base, "SHAW", cfg, target)
    except (OSError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("SHAW runtime evidence is incomplete or changed") from error
    return report


def verify_candidate(candidate, *, source, name, runtime_config=None, target_root=None, **unused):
    candidate = Path(candidate).absolute()
    base = core.require_source(source, name=name)
    target = _target(runtime_config, target_root)
    if (Path(source["original_root"]) != target or candidate == base or base in candidate.parents
            or candidate in base.parents or candidate == target or target in candidate.parents
            or candidate in target.parents):
        raise ValueError("SHAW maintenance requires separate draft and exact source target")
    digest, profile = ki_verification.content_digest(candidate), policy_digest()
    if not digest or name != "SHAW" or ki_verification.detect_kind(candidate) != source["kind"]:
        raise ValueError("SHAW maintenance identity does not match")
    changes = _changes(base, candidate, name, runtime_config, target)
    path_report = validate_behavior(base, candidate, runtime_config, target_root=target)
    report = ki_verification._check_candidate(candidate, name=name, kind=source["kind"], desktop=True,
        _gate_adapter=lambda gate: published_kdt.gate_view(gate, model_name=name))
    core.require_source(source, name=name)
    require_runtime_current(path_report)
    if (ki_verification.content_digest(candidate) != digest or policy_digest() != profile
            or _changes(base, candidate, name, runtime_config, target) != changes):
        raise ValueError("SHAW candidate or policy changed during KDT verification")
    ok = report["ok"] is True
    report.update(scope=SCOPE, gate_policy=POLICY, policy_digest=profile, ok=ok,
        state="MaintenanceVerified" if ok else "MaintenanceRejected", name=name,
        source=source, source_id=core._hash(source), base_digest=source["base_digest"],
        changes=changes, change_digest=core._hash(changes), authoring_verification=False,
        literature_evidence="unchanged_published_metadata_only", scientific_validation=False,
        local_only=True, maintenance_recipe=RECIPE, path_binding_regression=path_report,
        native_regression={"status": "not_run", "verified": False})
    return core._sign(candidate, report)


def require_current(candidate, report, *, source=None):
    candidate = Path(candidate).absolute()
    if not core._authentic(candidate, report):
        raise ValueError("SHAW maintenance verification is unauthenticated")
    embedded = report.get("source")
    if source is not None and source != embedded:
        raise ValueError("SHAW maintenance report belongs to another source")
    base = core.require_source(embedded, name=report.get("name"))
    if (report.get("scope") != SCOPE or report.get("gate_policy") != POLICY
            or report.get("maintenance_recipe") != RECIPE or report.get("name") != "SHAW"
            or report.get("ok") is not True or report.get("state") != "MaintenanceVerified"
            or report.get("policy_digest") != policy_digest() or report.get("source_id") != core._hash(embedded)
            or report.get("base_digest") != embedded["base_digest"] or report.get("kind") != embedded["kind"]
            or report.get("desktop_requested") is not True or report.get("doctor_policy") != doctor.VALIDATION_POLICY_VERSION
            or report.get("authoring_verification") is not False or report.get("scientific_validation") is not False
            or report.get("local_only") is not True or report.get("literature_evidence") != "unchanged_published_metadata_only"
            or any(report.get(key) != value for key, value in core._engine().items())
            or report.get("candidate_digest") != ki_verification.content_digest(candidate)):
        raise ValueError("SHAW maintenance verification failed, changed or is stale")
    binding = require_runtime_current(report.get("path_binding_regression"))
    cfg = projection_config(binding)
    target = _target(cfg, binding["runtime"]["target_ki"])
    changes = _changes(base, candidate, "SHAW", cfg, target)
    if (Path(embedded["original_root"]) != target or binding["source_root"] != str(base)
            or binding["source_digest"] != embedded["base_digest"]
            or binding["candidate_digest"] != report["candidate_digest"]
            or binding["changes"] != changes or report.get("changes") != changes
            or report.get("change_digest") != core._hash(changes)):
        raise ValueError("SHAW path evidence belongs to another source or candidate")
    return report
