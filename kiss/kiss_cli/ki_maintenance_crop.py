"""Versioned WOFOST crop-provider compatibility repair through the KDT gate.

This deliberately leaves the existing maintenance policy implementation intact:
already adopted site-routing repairs still use their original strict verifier.
Only one recognized stage-one adapter changes; no crop values or model run are
invented. Native fixtures call installed provider methods in an isolated child.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import ki_maintenance as core, ki_maintenance_wofost as native
from . import ki_verification, published_kdt, doctor

POLICY = "wofost-crop-provider-maintenance-v1"
RECIPE = "wofost_crop_provider"
SCOPE = "ki_maintenance_crop_candidate"
TOOL_PATH = "tools/s1_crop_params/load_crop_parameters.py"
OLD_AST_SHA256 = "63561e8c807e96f8cf841df4d2031bec777a3bd6522bb44c41155b4ae728f443"
# Both exact official PyPI wheels have this same provider source; package and
# __init__ version pins remain distinct. See PCSE_RELEASES in the native module.
_CROP_PIN = "71aa07ce4661ee373232499623cb40f5e8b8c6003b0d8e830ffb0da40395ed6c"
PCSE_RELEASES = {version: {**release, "pins": {
    **release["pins"], "input/yaml_cropdataprovider.py": _CROP_PIN}}
    for version, release in native.PCSE_RELEASES.items()}
_OLD_CROPS = "    available_crops = list(cropdata.get_crop_types())\n"
_NEW_CROPS = ("    crop_varieties = cropdata.get_crops_varieties()\n"
              "    available_crops = list(crop_varieties)\n")
_OLD_VARIETIES = "    available_varieties = list(cropdata.get_variety_names(CROP_NAME))\n"
_NEW_VARIETIES = "    available_varieties = list(crop_varieties[CROP_NAME])\n"
_OLD_IMPORT = "        import pcse\n"
_NEW_IMPORT = ("        import pcse\n"
               "        # PCSE configures logging on import; retain this tool's diagnostics.\n"
               "        logger.disabled = False\n")


def policy_digest():
    from . import ki_maintenance_dispatch
    return core._hash({"policy": POLICY, "core": core.policy_digest(),
        "implementation": published_kdt._module_identity(sys.modules[__name__]),
        "dispatch": published_kdt._module_identity(ki_maintenance_dispatch)})


def _ordinary(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("Crop maintenance requires a bounded ordinary source file")
    return path.read_bytes()


def expected_changes(base, name):
    try:
        if str(name).casefold() != "wofost":
            return {}
        source = _ordinary(Path(base) / TOOL_PATH).decode("utf-8")
        if native._hash(native._ast_value(ast.parse(source))) != OLD_AST_SHA256:
            return {}
        newline = "\r\n" if "\r\n" in source else "\n"
        if "\r" in source.replace("\r\n", "") or (newline == "\r\n" and "\n" in source.replace("\r\n", "")):
            return {}
        for before, after in ((_OLD_CROPS, _NEW_CROPS), (_OLD_VARIETIES, _NEW_VARIETIES),
                              (_OLD_IMPORT, _NEW_IMPORT)):
            before, after = before.replace("\n", newline), after.replace("\n", newline)
            if source.count(before) != 1:
                return {}
            source = source.replace(before, after, 1)
        return {TOOL_PATH: source.encode("utf-8")}
    except (ValueError, OSError, SyntaxError, UnicodeError):
        return {}


def apply_recipe(candidate, *, source, recipe, name, **unused):
    source, candidate = Path(source).resolve(), Path(candidate).resolve()
    if source == candidate or source in candidate.parents or candidate in source.parents:
        raise ValueError("Crop maintenance requires a separate draft")
    changes = expected_changes(source, name) if recipe == RECIPE else {}
    if not changes:
        raise ValueError("No supported crop-provider correction for this exact source")
    from . import ki_tree
    ki_tree.scan(candidate)
    if _ordinary(candidate / TOOL_PATH) != _ordinary(source / TOOL_PATH):
        raise ValueError("Crop draft changed before its deterministic projection")
    (candidate / TOOL_PATH).write_bytes(changes[TOOL_PATH])
    return {"recipe": RECIPE, "changed_files": [TOOL_PATH],
            "outputs": {TOOL_PATH: hashlib.sha256(changes[TOOL_PATH]).hexdigest()}}


def _changes(base, candidate, name):
    before, after = core._inventory(base), core._inventory(candidate)
    expected = expected_changes(base, name)
    if set(before) != set(after) or not expected:
        raise ValueError("Crop maintenance requires the exact original KI file inventory")
    changed = [path for path in before if before[path] != after[path]]
    if (changed != [TOOL_PATH] or before[TOOL_PATH]["kind"] != "file"
            or after[TOOL_PATH]["kind"] != "file"
            or _ordinary(candidate / TOOL_PATH) != expected[TOOL_PATH]):
        raise ValueError("Edit exceeds the exact crop-provider maintenance contract")
    return [{"path": TOOL_PATH, "before_sha256": before[TOOL_PATH]["sha256"],
             "after_sha256": after[TOOL_PATH]["sha256"]}]


def _cases():
    return [{"id": identifier, "crop": crop, "variety": variety, "valid": valid}
        for identifier, crop, variety, valid in (
            ("maize_requested_variety", "maize", "Grain_maize_201", True),
            ("wheat_default_variety", "wheat", "Winter_wheat_101", True),
            ("second_variety", "maize", "Grain_maize_202", True),
            ("unknown_crop", "barley", "Grain_maize_201", False),
            ("unknown_variety", "maize", "Missing", False),
            ("crop_case_sensitive", "Maize", "Grain_maize_201", False),
            ("variety_case_sensitive", "maize", "grain_maize_201", False),
            ("wrong_crop_variety", "wheat", "Grain_maize_201", False))]


def fixture_ids():
    return [row["id"] for row in _cases()] + ["own_failure_logging_restored"]


# Host-owned copy of the reviewed selection fragment. The exact source AST and
# projection above establish its correspondence; no candidate module is loaded.
_SELECTION = '''
crop_varieties = cropdata.get_crops_varieties()
available_crops = list(crop_varieties)
if CROP_NAME not in available_crops:
    logger.error(f"Crop '{CROP_NAME}' not found. Available: {available_crops}")
    logger.error("NOTE: crop names are CASE SENSITIVE (use lowercase)")
    sys.exit(2)
available_varieties = list(crop_varieties[CROP_NAME])
if VARIETY_NAME not in available_varieties:
    logger.error(f"Variety '{VARIETY_NAME}' not found. Available: {available_varieties}")
    logger.error("NOTE: variety names are CASE SENSITIVE")
    sys.exit(2)
cropdata.set_active_crop(CROP_NAME, VARIETY_NAME)
'''

# Reuse the unchanged reviewed child's isolation and runtime recording, not its
# routing fixtures. The dependency is included in core.policy_digest above.
_ISOLATION = native._CHILD.split("from pcse.input import WOFOST72SiteDataProvider", 1)[0]
_ISOLATION = _ISOLATION.replace("import pcse\n", '''import logging, io
logger = logging.getLogger("geoforge_crop_fixture")
other_logger = logging.getLogger("geoforge_untouched_fixture")
diagnostics = io.StringIO()
logger.addHandler(logging.StreamHandler(diagnostics))
logger.propagate = False
import pcse
assert logger.disabled and other_logger.disabled, "PCSE import logging behavior changed"
logger.disabled = False
''')
_NATIVE_CASES = r'''
from pcse.input import YAMLCropDataProvider
assert pcse.__version__ == version
assert Path(sys.modules["user_settings"].__file__).resolve() == settings_file
assert Path(pcse.util.get_user_home()).resolve() == scratch
assert Path(pcse.settings.PCSE_USER_HOME).resolve() == pcse_home
assert Path(sys.modules[YAMLCropDataProvider.__module__].__file__).resolve() == pcse_root / "input/yaml_cropdataprovider.py"
assert not hasattr(YAMLCropDataProvider, "get_crop_types")
assert not hasattr(YAMLCropDataProvider, "get_variety_names")
store = {
    "maize": {
        "Grain_maize_201": {"Metadata": {"fixture": True}, "TSUM1": [800.0], "TSUM2": [1100.0], "TDWI": [20.0], "SPAN": [35.0]},
        "Grain_maize_202": {"TSUM1": [825.0], "TSUM2": [1200.0], "TDWI": [25.0], "SPAN": [32.0]}},
    "wheat": {"Winter_wheat_101": {"TSUM1": [1050.0], "TSUM2": [900.0], "TDWI": [15.0], "SPAN": [30.0]}}}
before = copy.deepcopy(store)
rows = []
for case in payload["cases"]:
    # No constructor, cache, repository, download or model engine is needed to
    # exercise the real installed enumeration and active-crop methods.
    provider = dict.__new__(YAMLCropDataProvider)
    provider._store = copy.deepcopy(store)
    ns = {"cropdata": provider, "CROP_NAME": case["crop"], "VARIETY_NAME": case["variety"],
          "logger": logger, "sys": sys}
    try:
        exec(compile(payload["selection"], "<reviewed crop selection>", "exec"), ns)
        outcome = "passed"
        assert case["valid"]
        expected = {key: value[0] for key, value in store[case["crop"]][case["variety"]].items() if key != "Metadata"}
        assert dict(provider) == expected
        assert provider.current_crop_name == case["crop"]
        assert provider.current_variety_name == case["variety"]
        assert ns["available_crops"] == list(store)
        assert ns["available_varieties"] == list(store[case["crop"]])
    except SystemExit as error:
        assert not case["valid"] and error.code == 2
        assert not provider, "Invalid selection activated a crop"
        outcome = "exit_2"
    assert provider._store == store == before
    rows.append({"id": case["id"], "ok": True, "input_unchanged": True, "outcome": outcome})
logger.error("Processing failed: visible fixture error")
assert "Processing failed: visible fixture error" in diagnostics.getvalue()
assert "not found" in diagnostics.getvalue()
assert other_logger.disabled, "Repair changed an unrelated logger"
rows.append({"id": "own_failure_logging_restored", "ok": True, "input_unchanged": True})
'''
_RUNTIME_RECORD = native._CHILD[native._CHILD.index("assert pcse_inventory() == inventory_before"):]
_CHILD = (_ISOLATION + _NATIVE_CASES + _RUNTIME_RECORD).replace("GEOFORGE_WOFOST_ROUTING=", "GEOFORGE_WOFOST_CROP=")


def fixture_protocol_sha256():
    return core._hash({"policy": POLICY, "program": _CHILD, "selection": _SELECTION,
                       "cases": _cases(), "pcse_releases": PCSE_RELEASES})


def require_runtime_current(report):
    """Authenticate the containing gate first; this only checks exact freshness."""
    try:
        runtime, rows = report["runtime"], report["fixtures"]
        if (report.get("policy") != POLICY or report.get("recipe") != RECIPE
                or report.get("ok") is not True or report.get("status") != "passed"
                or report.get("native_provider_execution") is not True
                or report.get("model_execution") is not False or report.get("scientific_validation") is not False
                or report.get("fixture_protocol_sha256") != fixture_protocol_sha256()
                or report.get("fixture_ids") != fixture_ids() or report.get("fixture_count") != len(fixture_ids())
                or [row.get("id") for row in rows] != fixture_ids()
                or any(row.get("ok") is not True or row.get("input_unchanged") is not True for row in rows)
                or runtime.get("python_version", [])[:2] != [3, 12]
                or runtime.get("pcse_version") not in PCSE_RELEASES
                or report.get("runtime_identity") != core._hash(runtime)):
            raise ValueError("Incomplete or stale crop-provider fixture evidence")
        if report.get("isolation") != {"no_site": True, "isolated": True, "no_bytecode": True,
                "scratch_home": True, "scratch_user_settings": True, "candidate_imported": False, "model_executed": False}:
            raise ValueError("Missing crop-provider fixture isolation")
        selected = Path(runtime["selected_python"])
        if not selected.is_absolute() or str(selected.resolve()) != runtime["resolved_python"]:
            raise ValueError("Selected crop-provider interpreter changed")
        binding = native._venv_binding(selected)
        if binding != runtime.get("venv_binding") or (binding is not None and binding["site_packages"] != runtime["site_packages"]):
            raise ValueError("Selected crop-provider virtualenv binding changed")
        release = PCSE_RELEASES[runtime["pcse_version"]]
        root = Path(runtime["pcse_root"])
        if (runtime.get("pcse_wheel_sha256") != release["wheel_sha256"]
                or root != Path(runtime["site_packages"]) / "pcse" or root.resolve() != root):
            raise ValueError("Unrecognized selected crop-provider package")
        inventory = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts}
        if inventory != runtime["pcse_inventory"] or any(inventory.get(path) != pin for path, pin in release["pins"].items()):
            raise ValueError("Installed crop-provider source changed")
        files = runtime["files"]
        paths = [row["path"] for row in files]
        required = {str((root / relative).absolute()) for relative in release["pins"]}
        required.add(str(root.parent / ("pcse-" + runtime["pcse_version"] + ".dist-info") / "METADATA"))
        if binding is not None:
            required.update(binding[key]["path"] for key in ("config", "base_python"))
        if (not files or len(set(paths)) != len(paths) or not required <= set(paths)
                or not any(row["resolved_path"] == runtime["resolved_python"] for row in files)
                or any(not native._file_current(row) for row in files)):
            raise ValueError("Crop-provider runtime or loaded dependency changed")
    except (KeyError, TypeError, AttributeError, OSError) as error:
        raise ValueError("Incomplete crop-provider runtime evidence") from error
    return report


def validate_behavior(base, candidate, python):
    report = {"policy": POLICY, "recipe": RECIPE, "ok": False, "status": "failed",
        "native_provider_execution": False, "model_execution": False, "scientific_validation": False,
        "fixture_protocol_sha256": fixture_protocol_sha256(), "fixture_ids": fixture_ids(),
        "fixture_count": 0, "fixtures": []}
    try:
        base, candidate = Path(base), Path(candidate)
        expected = expected_changes(base, "WOFOST").get(TOOL_PATH)
        if expected is None or _ordinary(candidate / TOOL_PATH) != expected:
            raise ValueError("Candidate differs from the exact crop-provider projection")
        old = _ordinary(base / TOOL_PATH)
        executable = Path(python)
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("An absolute existing selected Python is required")
        executable = executable.absolute()
        selected_before = native._runtime_file(executable)
        payload = {"base": str(base.resolve()), "candidate": str(candidate.resolve()),
            "python": str(executable), "venv_binding": native._venv_binding(executable),
            "pcse_releases": PCSE_RELEASES, "cases": _cases(), "selection": _SELECTION}
        with tempfile.TemporaryDirectory(prefix="geoforge-crop-provider-") as folder:
            env = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE"}}
            env.update(HOME=folder, USERPROFILE=folder, TEMP=folder, TMP=folder, TMPDIR=folder,
                USERNAME="geoforge-fixture", USER="geoforge-fixture",
                PATH=os.pathsep.join([str(executable.parent), str(Path(env.get("SYSTEMROOT", "C:/Windows")) / "System32")]))
            result = subprocess.run([str(executable), "-I", "-S", "-B", "-c", _CHILD],
                input=json.dumps(payload), capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=folder, env=env, timeout=90)
        lines = [line.partition("=")[2] for line in result.stdout.splitlines() if line.startswith("GEOFORGE_WOFOST_CROP=")]
        if result.returncode or len(lines) != 1:
            detail = result.stderr.strip().splitlines()
            raise ValueError("Native crop-provider fixtures failed: " + (detail[-1][:300] if detail else "no complete result"))
        actual = json.loads(lines[0])
        if not native._file_current(selected_before) or _ordinary(base / TOOL_PATH) != old or _ordinary(candidate / TOOL_PATH) != expected:
            raise ValueError("Crop source, candidate or Python changed during fixtures")
        files = actual["runtime"]["files"] + [selected_before]
        actual["runtime"]["files"] = sorted({row["path"]: row for row in files}.values(), key=lambda row: row["path"])
        report.update(actual, ok=True, status="passed", native_provider_execution=True,
            fixture_count=len(actual["fixtures"]), runtime_identity=core._hash(actual["runtime"]),
            base_tool_sha256=hashlib.sha256(old).hexdigest(), candidate_tool_sha256=hashlib.sha256(expected).hexdigest())
        require_runtime_current(report)
    except (ValueError, OSError, SyntaxError, subprocess.SubprocessError) as error:
        report.update(ok=False, status="failed", error=str(error)[:600])
    return report


def verify_candidate(candidate, *, source, name, runtime_python=None, **unused):
    candidate = Path(candidate).absolute()
    base = core.require_source(source, name=name)
    if candidate == base or candidate.is_relative_to(base) or base.is_relative_to(candidate):
        raise ValueError("Crop maintenance requires separate source and candidate trees")
    digest, profile = ki_verification.content_digest(candidate), policy_digest()
    if not digest or name != "WOFOST" or ki_verification.detect_kind(candidate) != source["kind"]:
        raise ValueError("Crop maintenance requires matching WOFOST KI identity")
    changes = _changes(base, candidate, name)
    if not isinstance(runtime_python, (str, Path)) or not str(runtime_python).strip():
        raise ValueError("Crop maintenance requires the saved project Python runtime")
    interface = validate_behavior(base, candidate, runtime_python)
    report = ki_verification._check_candidate(candidate, name=name, kind=source["kind"], desktop=True,
        _gate_adapter=lambda gate: published_kdt.gate_view(gate, model_name=name))
    ok = bool(report["ok"] and interface["ok"])
    if not interface["ok"]:
        report["failures"] = [*report["failures"], "Crop-provider interface regression failed"]
    core.require_source(source, name=name)
    if ki_verification.content_digest(candidate) != digest or _changes(base, candidate, name) != changes or policy_digest() != profile:
        raise ValueError("Crop candidate or policy changed during verification")
    if interface["ok"]:
        require_runtime_current(interface)
    report.update(scope=SCOPE, gate_policy=POLICY, policy_digest=profile, ok=ok,
        state="MaintenanceVerified" if ok else "MaintenanceRejected", name=name,
        source=source, source_id=core._hash(source), base_digest=source["base_digest"],
        changes=changes, change_digest=core._hash(changes), authoring_verification=False,
        literature_evidence="unchanged_published_metadata_only", scientific_validation=False,
        local_only=True, maintenance_recipe=RECIPE, interface_regression=interface,
        native_regression={"status": "not_run", "verified": False})
    return core._sign(candidate, report)


def require_current(candidate, report, *, source=None):
    candidate = Path(candidate).absolute()
    if not core._authentic(candidate, report):
        raise ValueError("Crop maintenance verification is unauthenticated")
    embedded = report.get("source")
    if source is not None and source != embedded:
        raise ValueError("Crop maintenance report belongs to another source")
    base = core.require_source(embedded, name=report.get("name"))
    if (report.get("scope") != SCOPE or report.get("gate_policy") != POLICY
            or report.get("maintenance_recipe") != RECIPE or report.get("name") != "WOFOST"
            or report.get("ok") is not True or report.get("state") != "MaintenanceVerified"
            or report.get("policy_digest") != policy_digest() or report.get("source_id") != core._hash(embedded)
            or report.get("base_digest") != embedded["base_digest"] or report.get("kind") != embedded["kind"]
            or report.get("desktop_requested") is not True or report.get("doctor_policy") != doctor.VALIDATION_POLICY_VERSION
            or report.get("authoring_verification") is not False or report.get("scientific_validation") is not False
            or report.get("local_only") is not True or report.get("literature_evidence") != "unchanged_published_metadata_only"
            or any(report.get(key) != value for key, value in core._engine().items())
            or report.get("candidate_digest") != ki_verification.content_digest(candidate)):
        raise ValueError("Crop maintenance verification failed, changed or is stale")
    changes = _changes(base, candidate, report["name"])
    if report.get("changes") != changes or report.get("change_digest") != core._hash(changes):
        raise ValueError("Crop maintenance changes differ from verification")
    interface = require_runtime_current(report.get("interface_regression"))
    if (interface.get("base_tool_sha256") != changes[0]["before_sha256"]
            or interface.get("candidate_tool_sha256") != changes[0]["after_sha256"]):
        raise ValueError("Crop-provider fixture report belongs to another candidate")
    return report
