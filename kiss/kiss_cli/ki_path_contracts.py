"""Source-bound WOFOST runtime path normalization, with no check execution.

This deliberately recognizes two reviewed published preflights, not arbitrary Python.
The same three RHS replacements serve fresh portable projection and an
explicitly reviewed retained-KI maintenance candidate. Callers retain KDT,
approval, exact saved-config binding and post-adoption project verification.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import SimpleNamespace

import yaml

POLICY = "wofost-static-runtime-paths-v1"
RECIPE = "wofost_runtime_paths"
PREFLIGHT = "preflight_check.py"
MANIFEST = "knowledge_infrastructure.yaml"
RUNNER = "run_and_score.py"
OLD_AST_SHA256 = "07a4c645f3f3f6b5f10950191c085ce91cb879cc3437206c5f89dedf68c4f9ad"
# The shipped catalogue checks the VIC weather converter; the retained
# published variant checks build_pcse_weather_from_source instead. Both whole
# ASTs are reviewed. Do not normalize away their different required tools.
BUNDLED_AST_SHA256 = "3d7d7758e58cf35e97eb54171ab9b6b682b5a6de6a49f425c47dab432618d913"
PREFLIGHT_AST_SHA256S = frozenset((OLD_AST_SHA256, BUNDLED_AST_SHA256))
RUNNER_AST_SHA256 = "f64acc94038b51bc3a4b06def5307218483d4bd2bafd5dabbb1d927c25a3f928"
MAX_BYTES = 1024 * 1024
_DATA_TOKENS = ("KISSPATH_OBS", "KISSPATH_FORCING", "KISSPATH_DATA/elev", "KISSPATH_STATIC")
_CHANGED_NAMES = ("PYTHON", "MODEL_ENTRYPOINT", "KI_TOOLS_COMMON")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def source_digest():
    from . import implementation_identity
    return implementation_identity.module_digest(sys.modules[__name__])


def _ast_value(node):
    if isinstance(node, ast.AST):
        return [type(node).__name__, [(k, _ast_value(v)) for k, v in ast.iter_fields(node)
                                     if not (k == "type_params" and v == [])]]
    if isinstance(node, list):
        return [_ast_value(v) for v in node]
    return node


def _ordinary(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        info = parent.lstat()
        if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
            raise ValueError("Path normalization refuses aliased source paths")
    info = path.stat()
    if not path.is_file() or info.st_nlink != 1 or info.st_size > MAX_BYTES:
        raise ValueError("Path normalization requires a bounded ordinary unshared file")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Path normalization source grew beyond its size limit")
    return raw


def config_identity(cfg):
    """Identity of the caller-supplied saved bindings, without loading config."""
    if cfg is None:
        raise ValueError("A retained runtime repair requires exact saved configuration")
    root = Path(cfg.root)
    python = Path(cfg.python)
    if not root.is_absolute() or not python.is_absolute():
        raise ValueError("Runtime root and selected Python must be absolute")
    roles = dict(cfg.roles)
    for key in ("server_root", "ki_root", "ki_tools_common", "obs", "forcing", "data", "static"):
        if key not in roles or not Path(roles[key]).is_absolute():
            raise ValueError("Runtime path normalization requires all explicit role bindings")
    if Path(roles["server_root"]).absolute() != root.absolute():
        raise ValueError("Scenario server_root must remain the configured project root")
    return _hash(_config_values(cfg))


def _config_values(cfg):
    return {"root": str(cfg.root), "python": str(cfg.python),
            "roles": {key: str(value) for key, value in cfg.roles.items()},
            "relocation": getattr(cfg, "relocation", None)}


def projection_config(report):
    """Reconstruct signed projection values; caller checks the real saved cfg."""
    try:
        values = report["runtime"]["config"]
        if not isinstance(values, dict) or set(values) != {"root", "python", "roles", "relocation"}:
            raise ValueError("Incomplete path projection config")
        if not isinstance(values["roles"], dict) or not all(isinstance(v, str) for v in values["roles"].values()):
            raise ValueError("Invalid path projection roles")
        cfg = SimpleNamespace(root=Path(values["root"]), python=values["python"],
                              roles={k: Path(v) for k, v in values["roles"].items()},
                              relocation=values["relocation"])
        if config_identity(cfg) != report["runtime"]["config_sha256"]:
            raise ValueError("Path projection configuration identity changed")
        return cfg
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Path report lacks its exact projection configuration") from error


def _expand(value, cfg):
    if cfg is None:
        return value
    from . import port
    result, _, unresolved = port.unsubstitute(value, cfg)
    if unresolved:
        raise ValueError("Runtime path has an unresolved role")
    return result


def _assignments(tree):
    return {n.targets[0].id: n for n in tree.body
            if isinstance(n, ast.Assign) and len(n.targets) == 1
            and isinstance(n.targets[0], ast.Name)}


def _recognized(raw, cfg):
    text = raw.decode("utf-8")
    normalized = text.replace("\r\n", "\n")
    if "\r" in normalized or ("\r\n" in text and "\n" in text.replace("\r\n", "")):
        raise ValueError("Path normalization refuses mixed newlines")
    tree = ast.parse(text)
    canonical = copy.deepcopy(tree)
    assignments = _assignments(canonical)
    # Only these five originally portable literals may differ after the
    # existing role substitution. Whole-AST identity protects every other
    # expression, definition, import, check, flag and version requirement.
    root = assignments.get("HYDROCRAFT_ROOT")
    data = assignments.get("COMMON_DATA_PATHS")
    if not root or not isinstance(root.value, ast.Constant):
        raise ValueError("Unrecognized WOFOST root declaration")
    if root.value.value != _expand("KISSPATH_ROOT", cfg):
        raise ValueError("Preflight root does not match its exact saved binding")
    root.value.value = "KISSPATH_ROOT"
    if not data or not isinstance(data.value, ast.List) or len(data.value.elts) != 4:
        raise ValueError("Unrecognized WOFOST data declarations")
    for item, token in zip(data.value.elts, _DATA_TOKENS):
        if (not isinstance(item, ast.Tuple) or len(item.elts) != 3
                or not isinstance(item.elts[0], ast.Constant)
                or item.elts[0].value != _expand(token, cfg)):
            raise ValueError("Preflight data path differs from its exact saved binding")
        item.elts[0].value = token
    recognized = _hash(_ast_value(canonical))
    if recognized not in PREFLIGHT_AST_SHA256S:
        raise ValueError("Unrecognized WOFOST preflight; path repair cannot change checks")
    return text, tree, recognized


def _replace_rhs(raw, tree, cfg):
    lines = raw.splitlines(keepends=True)
    offsets, count = [], 0
    for line in lines:
        offsets.append(count)
        count += len(line)
    replacements = {
        "PYTHON": json.dumps(_expand("KISSPATH_PYTHON", cfg), ensure_ascii=False),
        "MODEL_ENTRYPOINT": 'os.path.join(KI_DIR, "run_and_score.py")',
        "KI_TOOLS_COMMON": json.dumps(_expand("KISSPATH_KI_TOOLS_COMMON", cfg), ensure_ascii=False),
    }
    spans = []
    for name, node in _assignments(tree).items():
        if name in replacements:
            value = node.value
            spans.append((offsets[value.lineno - 1] + value.col_offset,
                          offsets[value.end_lineno - 1] + value.end_col_offset,
                          replacements[name].encode("utf-8")))
    if len(spans) != 3:
        raise ValueError("Path repair requires exactly three recognized declarations")
    for start, end, value in sorted(spans, reverse=True):
        raw = raw[:start] + value + raw[end:]
    return raw


def _mapping(node):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError("Manifest path contract must use mappings")
    result = {}
    for key, value in node.value:
        if (not isinstance(key, yaml.ScalarNode) or key.tag != "tag:yaml.org,2002:str"
                or key.value in result):
            raise ValueError("Manifest path contract has ambiguous mapping keys")
        result[key.value] = value
    return result


def _manifest(raw, cfg, target_root):
    text = raw.decode("utf-8")
    for token in yaml.scan(text):
        if isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken, yaml.tokens.TagToken)):
            raise ValueError("Manifest path normalization refuses aliases and explicit tags")
    document = yaml.compose(text, Loader=yaml.SafeLoader)
    package = _mapping(_mapping(document).get("package"))
    for key, expected in (("name", "WOFOST"), ("language", "python")):
        if not isinstance(package.get(key), yaml.ScalarNode) or package[key].value != expected:
            raise ValueError("Manifest does not identify the recognized WOFOST Python package")
    binary = _mapping(package.get("binary"))
    if (set(binary) != {"path", "type"} or not isinstance(binary.get("type"), yaml.ScalarNode)
            or binary["type"].value != "Python"):
        raise ValueError("Manifest binary path contract changed")
    path = binary.get("path")
    if (not isinstance(path, yaml.ScalarNode) or path.tag != "tag:yaml.org,2002:str"
            or path.value != _expand("KISSPATH_KI_ROOT/WOFOST/run_and_score.py", cfg)):
        raise ValueError("Manifest path does not match the recognized declaration")
    # Current tool authorization requires an absolute declared entrypoint.
    # Bind only this target KI's own shipped file, never a shared copied runner.
    replacement = json.dumps(str(target_root / RUNNER).replace("\\", "/"), ensure_ascii=False)
    return (text[:path.start_mark.index] + replacement + text[path.end_mark.index:]).encode("utf-8")


def _target(cfg, target_root):
    config_identity(cfg)
    if target_root is None or not Path(target_root).is_absolute():
        raise ValueError("An explicit absolute target KI is required")
    target = Path(target_root).absolute()
    root = Path(cfg.root).absolute()
    if target not in (root / "ki", root / "models" / "WOFOST" / "ki"):
        raise ValueError("Runtime repair target must be this model's exact saved workspace")
    if target.resolve() != target:
        raise ValueError("Runtime repair target may not be aliased")
    return target


def _runner(raw, cfg):
    tree = ast.parse(raw.decode("utf-8"))
    tokens = ("KISSPATH_KI_TOOLS_COMMON", "KISSPATH_KI_ROOT/WOFOST/detached/verify_1")
    for token in tokens:
        matches = [n for n in ast.walk(tree) if isinstance(n, ast.Constant)
                   and n.value == _expand(token, cfg)]
        if len(matches) != 1:
            raise ValueError("Shipped runner path literals do not match its bindings")
        matches[0].value = token
    if _hash(_ast_value(tree)) != RUNNER_AST_SHA256:
        raise ValueError("Unrecognized shipped WOFOST entrypoint")


def _inputs(base, cfg):
    """Recognize portable bytes or their exact existing role projection."""
    from . import port
    raw = {name: _ordinary(Path(base) / name) for name in (PREFLIGHT, MANIFEST, RUNNER)}
    root = _assignments(ast.parse(raw[PREFLIGHT].decode("utf-8"))).get("HYDROCRAFT_ROOT")
    portable = bool(root and isinstance(root.value, ast.Constant) and root.value.value == "KISSPATH_ROOT")
    _recognized(raw[PREFLIGHT], None if portable else cfg)
    _runner(raw[RUNNER], None if portable else cfg)
    if portable:
        # This is the existing literal role expansion used by port.materialise,
        # not a new interpretation of model logic. Retained bytes skip it.
        for name, value in raw.items():
            text, _, unresolved = port.unsubstitute(value.decode("utf-8"), cfg)
            if unresolved:
                raise ValueError("Portable path source has unresolved runtime roles")
            raw[name] = text.encode("utf-8")
    return raw


def _projection(base, name, cfg, target_root):
    if name != "WOFOST":
        raise ValueError("Unsupported model runtime path contract")
    target = _target(cfg, target_root)
    base = Path(base)
    inputs = _inputs(base, cfg)
    raw = inputs[PREFLIGHT]
    _, tree, _ = _recognized(raw, cfg)
    return {PREFLIGHT: _replace_rhs(raw, tree, cfg),
            MANIFEST: _manifest(inputs[MANIFEST], cfg, target)}


def expected_changes(base, name, cfg=None, *, target_root=None):
    """Offer only the recognized repair; {} never certifies a requested edit.

    For fresh portable sources this is a two-file overlay onto the ordinary
    port.materialise result, not a complete KI copy. The runner and other files
    still require their normal, unchanged role projection before validation.
    Retained sources already contain those exact materialized role values.
    """
    try:
        return _projection(base, name, cfg, target_root)
    except (ValueError, OSError, SyntaxError, TypeError, yaml.YAMLError):
        return {}


def _file_identity(path):
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Recorded runtime file is missing or not absolute")
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            if size > 256 * 1024 * 1024:
                raise ValueError("Runtime identity file exceeds the bounded size")
            digest.update(chunk)
    return {"path": str(path), "resolved": str(path.resolve(strict=True)),
            "bytes": size, "sha256": digest.hexdigest()}


def _runtime(cfg, target_root, runner_hash):
    from . import helper_identity
    config_digest = config_identity(cfg)
    target = _target(cfg, target_root)
    runner = _ordinary(target / RUNNER)
    if hashlib.sha256(runner).hexdigest() != runner_hash:
        raise ValueError("Target KI runner differs from the reviewed source")
    helper = Path(cfg.roles["ki_tools_common"])
    binding, files, legacy = helper_identity.checked_marker(helper)
    if legacy:
        raise ValueError("Runtime repair requires a current, source-bound shared helper marker")
    _helper_config(binding, cfg)
    return {"config_sha256": config_digest, "config": _config_values(cfg),
            "selected_python": _file_identity(Path(cfg.python)),
            "target_ki": str(target), "runner": _file_identity(target / RUNNER),
            "helper_root": str(helper), "helper_binding": binding, "helper_files": files,
            "helper_marker": _file_identity(helper / helper_identity.MARKER)}


def _helper_config(binding, cfg):
    expected_roles = {key: str(value) for key, value in cfg.roles.items() if key != "ki_tools_common"}
    if (binding.get("python") != str(cfg.python)
            or binding.get("relocation") != getattr(cfg, "relocation", None)
            or binding.get("roles") != expected_roles):
        raise ValueError("Pinned helpers were projected for a different saved runtime")


def validate_behavior(base, candidate, cfg=None, *, target_root=None):
    """Prove exact source/path preservation; never execute any preflight/model."""
    base, candidate = Path(base).absolute(), Path(candidate).absolute()
    if base == candidate or base in candidate.parents or candidate in base.parents:
        raise ValueError("Path contract source and candidate must be separate trees")
    changes = _projection(base, "WOFOST", cfg, target_root)
    for relative, wanted in changes.items():
        if _ordinary(candidate / relative) != wanted:
            raise ValueError("Candidate differs from the exact runtime path projection")
    inputs = _inputs(base, cfg)
    runner = inputs[RUNNER]
    if _ordinary(candidate / RUNNER) != runner:
        raise ValueError("Path normalization cannot change the shipped runner")
    _, before, recognized = _recognized(inputs[PREFLIGHT], cfg)
    after = ast.parse(changes[PREFLIGHT].decode("utf-8"))
    old_names = _assignments(before)
    for name, node in _assignments(after).items():
        if name in _CHANGED_NAMES:
            node.value = copy.deepcopy(old_names[name].value)
    if _ast_value(after) != _ast_value(before):
        raise ValueError("Preflight decisions changed outside the path declarations")
    runtime = _runtime(cfg, target_root, hashlib.sha256(runner).hexdigest())
    return {"ok": True, "policy": POLICY, "policy_sha256": source_digest(),
            "scope": "path_binding_regression", "runtime_bound": runtime is not None,
            "runtime": runtime, "model_execution": False, "native_execution": False,
            "scientific_validation": False, "preflight_passed": False,
            "recognized_ast_sha256": recognized, "runner_ast_sha256": RUNNER_AST_SHA256,
            "unchanged_decisions_sha256": _hash(_ast_value(before)),
            "source_root": str(base),
            "source_files": {name: hashlib.sha256(_ordinary(base / name)).hexdigest()
                             for name in (PREFLIGHT, MANIFEST, RUNNER)},
            "candidate_files": {name: hashlib.sha256(_ordinary(candidate / name)).hexdigest()
                                for name in (PREFLIGHT, MANIFEST, RUNNER)}}


def require_runtime_current(report):
    """Recheck runtime bytes only; portable-only reports cannot authorize apply."""
    from . import helper_identity
    if (not isinstance(report, dict) or report.get("ok") is not True
            or report.get("policy") != POLICY or report.get("policy_sha256") != source_digest()
            or report.get("scope") != "path_binding_regression"
            or report.get("runtime_bound") is not True
            or not isinstance(report.get("recognized_ast_sha256"), str)
            or report.get("recognized_ast_sha256") not in PREFLIGHT_AST_SHA256S
            or report.get("runner_ast_sha256") != RUNNER_AST_SHA256
            or any(report.get(key) is not False for key in
                   ("model_execution", "native_execution", "scientific_validation", "preflight_passed"))):
        raise ValueError("A current runtime-bound path report is required")
    try:
        runtime = report["runtime"]
        cfg = projection_config(report)
        for key in ("source_files", "candidate_files"):
            files = report[key]
            if (not isinstance(files, dict) or set(files) != {PREFLIGHT, MANIFEST, RUNNER}
                    or any(not isinstance(digest, str) or re.fullmatch("[0-9a-f]{64}", digest) is None
                           for digest in files.values())):
                raise ValueError("Path report source inventory is incomplete")
        if (not isinstance(report["unchanged_decisions_sha256"], str)
                or re.fullmatch("[0-9a-f]{64}", report["unchanged_decisions_sha256"]) is None
                or report["candidate_files"][RUNNER] != runtime["runner"]["sha256"]):
            raise ValueError("Path report does not bind the unchanged runner and check decisions")
        # Maintenance keeps its captured source. Re-read it so a report cannot
        # relabel one accepted preflight as the other or lose its exact source
        # binding merely because both identities are supported by this policy.
        source = Path(report["source_root"])
        if not source.is_absolute():
            raise ValueError("Path report requires its absolute captured source")
        inputs = _inputs(source, cfg)
        _, before, recognized = _recognized(inputs[PREFLIGHT], cfg)
        if (report["recognized_ast_sha256"] != recognized
                or report["unchanged_decisions_sha256"] != _hash(_ast_value(before))
                or report["source_files"] != {name: hashlib.sha256(_ordinary(source / name)).hexdigest()
                                              for name in (PREFLIGHT, MANIFEST, RUNNER)}):
            raise ValueError("Path report no longer matches its recognized source")
        _target(cfg, runtime["target_ki"])
        if (str(Path(cfg.python)) != runtime["selected_python"]["path"]
                or str(Path(cfg.roles["ki_tools_common"])) != runtime["helper_root"]):
            raise ValueError("Runtime file paths differ from their exact saved projection")
        for key in ("selected_python", "runner", "helper_marker"):
            saved = runtime[key]
            if _file_identity(Path(saved["path"])) != saved:
                raise ValueError("Runtime path identity changed")
        _ordinary(Path(runtime["runner"]["path"]))
        if Path(runtime["runner"]["path"]) != Path(runtime["target_ki"]) / RUNNER:
            raise ValueError("Runner is no longer bound to the exact target KI")
        helper = Path(runtime["helper_root"])
        if Path(runtime["helper_marker"]["path"]) != helper / helper_identity.MARKER:
            raise ValueError("Shared helper marker belongs to another path")
        binding, files, legacy = helper_identity.checked_marker(helper)
        if legacy or binding != runtime["helper_binding"] or files != runtime["helper_files"]:
            raise ValueError("Shared helper runtime identity changed")
        _helper_config(binding, cfg)
        if not isinstance(runtime["config_sha256"], str) or len(runtime["config_sha256"]) != 64:
            raise ValueError("Saved configuration identity is missing")
    except (OSError, KeyError, TypeError) as error:
        raise ValueError("Runtime path report is incomplete or its files changed") from error
