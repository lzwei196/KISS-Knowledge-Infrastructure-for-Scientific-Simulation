"""Reviewed WOFOST72 interface repair, not scientific authoring or model validation.

Only the recognized stage-six runner is projected. Native fixtures exercise
PCSE parameter providers, never a model engine or an imported candidate module.
The caller owns source provenance, whole-package checks and signed acceptance.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap

POLICY = "wofost72-site-routing-maintenance-v1"
RECIPE = "wofost_parameter_routing"
TOOL_PATH = "tools/s6_execution/run_wofost_simulation.py"
OLD_AST_SHA256 = "625e0346586bd55e580943fe31d2c4f5004e99f3b53837b789b3b9d75e6b1d18"
SITE_KEYS = ("IFUNRN", "NOTINF", "SSI", "SSMAX", "WAV", "SMLIM")
MAX_BYTES = 1024 * 1024
PCSE_VERSION = "6.0.13"
PCSE_PINS = {
    "__init__.py": "24a9f1815abd202597d8b4ef364c3d8cd8504e6be0ab2003119f89222017a2ed",
    "input/sitedataproviders.py": "d534ae971e78f17b8dd303c99733dd7304cffefb43c7617a26f5087919532f66",
    "base/parameter_providers.py": "97157986c4934175d0b731fcc789702067ca43ba9b38d73716e0aee3ce67ede1",
    "exceptions.py": "88edff141c2d35f9d257a70ad0d579127c973c5d5f1f3255cd3c51e4f9eda90a",
    "settings/__init__.py": "e33eb2fdce4d950b954f44f14f0f3c551997b544abe8a34d23087116b7297050",
    "settings/default_settings.py": "355d4b0a133e89107744dae71453ef70bf1711272f1595dff14e0b06a17d0684",
    "util.py": "fdaf896a9a2c95782904607d83c93522dc2288028665e7acb91280df8a34b6dc",
}
_OLD_BLOCK = """    # PCSE 6.0+: CO2 no longer accepted by SiteDataProvider; handled internally
    # via crop CO2 tables (dt_v002). Use WAV only.
    sitedata = WOFOST72SiteDataProvider(WAV=WAV)
"""
_NEW_BLOCK = """    # Route supplied WOFOST72 site values without changing their values or
    # native defaults. CO2 remains handled by crop tables (dt_v002).
    site_keys = ("IFUNRN", "NOTINF", "SSI", "SSMAX", "WAV", "SMLIM")
    site_values = {key: soildata[key] for key in site_keys if key in soildata}
    soildata = {key: value for key, value in soildata.items() if key not in site_keys}
    site_values.setdefault("WAV", WAV)
    sitedata = WOFOST72SiteDataProvider(**site_values)
"""
_PARAMS = "    params = ParameterProvider(cropdata=cropdata, soildata=soildata, sitedata=sitedata)\n"


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def _ast_value(node):
    if isinstance(node, ast.AST):
        # Python 3.12 adds an empty type_params field; no source semantics are
        # omitted. Nonempty type parameters remain part of the identity.
        return [type(node).__name__, [(key, _ast_value(value))
                for key, value in ast.iter_fields(node)
                if not (key == "type_params" and value == [])]]
    if isinstance(node, list):
        return [_ast_value(value) for value in node]
    return node


def _ordinary(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError("WOFOST routing requires an ordinary source file")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("WOFOST routing source exceeds the bounded size")
    return raw


def _projection(base: Path, name: str) -> dict[str, bytes]:
    if str(name).casefold() != "wofost":
        raise ValueError("The WOFOST routing recipe does not support this model")
    raw = _ordinary(Path(base) / TOOL_PATH)
    source = raw.decode("utf-8")
    if _hash(_ast_value(ast.parse(source))) != OLD_AST_SHA256:
        raise ValueError("Unrecognized WOFOST stage-six runner; use full authoring")
    newline = "\r\n" if "\r\n" in source else "\n"
    normalized = source.replace("\r\n", "\n")
    if "\r" in normalized or (newline == "\r\n" and "\n" in source.replace("\r\n", "")):
        raise ValueError("WOFOST routing refuses mixed source newlines")
    old = (_OLD_BLOCK + _PARAMS).replace("\n", newline)
    if source.count(old) != 1:
        raise ValueError("The recognized WOFOST parameter block has changed")
    updated = source.replace(old, (_NEW_BLOCK + _PARAMS).replace("\n", newline), 1)
    return {TOOL_PATH: updated.encode("utf-8")}


def expected_changes(base: Path, name: str) -> dict[str, bytes]:
    """Return only a recognized projection; unsupported inputs stay unavailable.

    The generic maintenance chooser calls this across models. An empty result
    must never certify a requested routing repair; validate_behavior rejects it.
    """
    try:
        return _projection(base, name)
    except (ValueError, OSError, SyntaxError, UnicodeError):
        return {}


def _cases() -> list[dict]:
    soil = {"SMW": .13, "SMFCF": .31, "SM0": .47, "CRAIRC": .04,
            "K0": 13., "SOPE": 1., "KSUB": 1., "RDMSOL": 120.}
    supplied = {"IFUNRN": 1, "NOTINF": .12, "SSI": 2., "SSMAX": 3.,
                "WAV": 50., "SMLIM": .31}
    rows = []
    def add(identifier, extra=None, *, crop=None, old_valid=False, error=False):
        rows.append({"id": identifier, "soil": {**soil, **(extra or {})},
                     "crop": crop if crop is not None else {"TSUM1": 800.},
                     "old_valid": old_valid, "expect_error": error})
    add("old_valid_no_site", old_valid=True)
    add("old_valid_unknown_soil_preserved", {"UNCHANGED_EXTRA": 17}, old_valid=True)
    for key in SITE_KEYS:
        add("single_" + key, {key: supplied[key]})
    add("all_six_original_site_values", {**supplied, "IFUNRN": 0, "NOTINF": 0., "SSI": 0., "SSMAX": 0.})
    add("all_six_nondefault", supplied)
    add("native_lower_boundaries", dict.fromkeys(SITE_KEYS, 0))
    add("native_upper_boundaries", {"IFUNRN": 1, "NOTINF": 1., "SSI": 100., "SSMAX": 100., "WAV": 100., "SMLIM": 1.})
    add("native_string_conversions", {key: str(value) for key, value in supplied.items()})
    add("native_IFUNRN_integer_conversion", {"IFUNRN": .9})
    for key in SITE_KEYS:
        for suffix, value in [("below", -1), ("above", 101), ("null", None),
                              ("text", "invalid"), ("nan", "nan"), ("infinity", "inf")]:
            add("invalid_" + key + "_" + suffix, {key: value}, error=True)
    add("unrelated_soil_crop_duplicate", crop={"SMFCF": .5}, old_valid=True, error=True)
    add("unrelated_site_crop_duplicate", crop={"WAV": 40.}, old_valid=True, error=True)
    add("mixed_site_and_unrelated_duplicate", {"WAV": 50.}, crop={"SMFCF": .5}, error=True)
    return rows


def fixture_ids() -> list[str]:
    return [row["id"] for row in _cases()]


# This is a host-owned program, never candidate or KI module execution.
_CHILD = r'''
import copy, hashlib, importlib.metadata, json, os, pathlib, sys, sysconfig
from pathlib import Path
payload = json.loads(sys.stdin.read())
scratch = Path.cwd().resolve()
sys.pycache_prefix = str(scratch / "unused-pycache")  # do not read installed .pyc files
assert Path.home().resolve() == scratch
assert sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
assert sys.version_info[:2] == (3, 12), "Reviewed fixtures require Python 3.12"
site = Path(sysconfig.get_path("purelib")).resolve()
assert site.is_dir(), "Selected runtime has no installed site-packages"
assert site not in (scratch, Path(payload["base"]).resolve(), Path(payload["candidate"]).resolve())
sys.path.append(str(site))  # no .pth, user-site, sitecustomize or caller PYTHONPATH
pcse_root = site / "pcse"
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def file_record(path):
    path = Path(path).absolute()
    return {"path": str(path), "resolved_path": str(path.resolve()),
            "size": path.stat().st_size, "sha256": sha(path)}
def pcse_inventory():
    return {p.relative_to(pcse_root).as_posix(): sha(p)
            for p in sorted(pcse_root.rglob("*.py")) if "__pycache__" not in p.parts}
inventory_before = pcse_inventory()
for relative, expected in payload["pcse_pins"].items():
    assert inventory_before.get(relative) == expected, "Reviewed PCSE source changed: " + relative
assert importlib.metadata.version("pcse") == "6.0.13"
pcse_home = scratch / ".pcse"
pcse_home.mkdir()
settings_file = pcse_home / "user_settings.py"
settings_file.write_text("# Isolated GeoForge provider fixtures; native defaults only.\n", encoding="utf-8")
# Avoid PCSE's first-import demo-database generation; no fixture needs it.
(pcse_home / "pcse.db").touch()
import pcse
from pcse.input import WOFOST72SiteDataProvider
from pcse.base import ParameterProvider
assert pcse.__version__ == "6.0.13"
assert Path(sys.modules["user_settings"].__file__).resolve() == settings_file
assert Path(pcse.util.get_user_home()).resolve() == scratch
assert Path(pcse.settings.PCSE_USER_HOME).resolve() == pcse_home
assert Path(sys.modules[WOFOST72SiteDataProvider.__module__].__file__).resolve() == (pcse_root / "input/sitedataproviders.py").resolve()
assert Path(sys.modules[ParameterProvider.__module__].__file__).resolve() == (pcse_root / "base/parameter_providers.py").resolve()
assert WOFOST72SiteDataProvider._defaults == {
    "IFUNRN": (0, {0, 1}, int), "NOTINF": (0, [0., 1.], float),
    "SSI": (0., [0., 100.], float), "SSMAX": (0., [0., 100.], float),
    "WAV": (None, [0., 100.], float), "SMLIM": (.4, [0., 1.], float)}
assert WOFOST72SiteDataProvider._required == ["WAV"]

def evaluate(fragment, soil, crop):
    ns = {"soildata": soil, "cropdata": crop, "WAV": 20,
          "WOFOST72SiteDataProvider": WOFOST72SiteDataProvider,
          "ParameterProvider": ParameterProvider}
    try:
        exec(compile(fragment, "<reviewed routing fragment>", "exec"), ns)
        params = ns["params"]
        return {"kind": "success", "site": dict(params._sitedata),
                "soil": dict(params._soildata),
                "parameters": {key: params[key] for mapping in params._maps for key in mapping}}
    except Exception as exc:
        return {"kind": "error", "type": type(exc).__name__, "message": str(exc)}

def oracle(soil, crop):
    # Independently assemble PCSE's two documented providers. This does not
    # execute/reuse the candidate's projection or comprehensions.
    remaining = copy.deepcopy(soil)
    arguments = {"WAV": 20}
    for key in ("WAV", "SSI", "SSMAX", "SMLIM", "NOTINF", "IFUNRN"):
        if key in soil:
            arguments[key] = copy.deepcopy(soil[key])
            del remaining[key]
    try:
        site_data = WOFOST72SiteDataProvider(**arguments)
        params = ParameterProvider(sitedata=site_data, soildata=remaining,
                                   cropdata=copy.deepcopy(crop))
        return {"kind": "success", "site": dict(params._sitedata),
                "soil": dict(params._soildata),
                "parameters": {key: params[key] for mapping in params._maps for key in mapping}}
    except Exception as exc:
        return {"kind": "error", "type": type(exc).__name__, "message": str(exc)}

rows = []
for case in payload["cases"]:
    soil, crop = copy.deepcopy(case["soil"]), copy.deepcopy(case["crop"])
    before = copy.deepcopy((soil, crop))
    actual = evaluate(payload["new_fragment"], soil, crop)
    expected = oracle(case["soil"], case["crop"])
    assert actual == expected, "Native oracle differs: " + case["id"]
    assert (soil, crop) == before, "Input dictionary mutated: " + case["id"]
    assert (actual["kind"] == "error") == case["expect_error"], case["id"] + ": " + json.dumps(actual)
    if case["old_valid"]:
        old = evaluate(payload["old_fragment"], copy.deepcopy(soil), copy.deepcopy(crop))
        assert old == actual, "Previously valid behavior changed: " + case["id"]
    elif not case["expect_error"]:
        old = evaluate(payload["old_fragment"], copy.deepcopy(soil), copy.deepcopy(crop))
        assert old["kind"] == "error" and "Duplicate parameter" in old["message"], case["id"]
    rows.append({"id": case["id"], "ok": True, "native_outcome": actual,
                 "input_unchanged": True, "old_valid_equivalent": case["old_valid"]})

assert pcse_inventory() == inventory_before, "Native PCSE source changed during fixtures"
files = {}
for name, module in list(sys.modules.items()):
    filename = getattr(module, "__file__", None)
    if not filename:
        continue
    path = Path(filename).absolute()
    if path.is_file() and not path.resolve().is_relative_to(scratch):
        files[str(path)] = file_record(path)
for path in [Path(sys.executable), site / "pcse-6.0.13.dist-info/METADATA"]:
    files[str(path.absolute())] = file_record(path)
for pattern in ("python*.dll", "python*.zip", "python*._pth", "pyvenv.cfg"):
    for directory in {Path(sys.executable).parent, Path(sys.prefix), Path(sys.base_prefix)}:
        for path in directory.glob(pattern):
            if path.is_file():
                files[str(path.absolute())] = file_record(path)
runtime = {"selected_python": payload["python"],
           "resolved_python": str(Path(sys.executable).resolve()),
           "python_version": list(sys.version_info[:3]), "pcse_version": pcse.__version__,
           "site_packages": str(site), "pcse_root": str(pcse_root),
           "pcse_inventory": inventory_before,
           "files": [files[key] for key in sorted(files)]}
print("GEOFORGE_WOFOST_ROUTING=" + json.dumps({"runtime": runtime, "fixtures": rows,
    "isolation": {"no_site": True, "isolated": True, "no_bytecode": True,
                  "scratch_home": True, "scratch_user_settings": True,
                  "candidate_imported": False, "model_executed": False}}))
'''


def fixture_protocol_sha256() -> str:
    return _hash({"policy": POLICY, "program": _CHILD, "cases": _cases(),
                  "pcse_pins": PCSE_PINS, "old": _OLD_BLOCK + _PARAMS,
                  "new": _NEW_BLOCK + _PARAMS})


def _file_current(row: dict) -> bool:
    path = Path(row["path"])
    return (path.is_file() and str(path.resolve()) == row["resolved_path"]
            and path.stat().st_size == row["size"]
            and hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"])


def _reject_virtualenv(executable: Path) -> None:
    # On Python 3.12, -S bypasses venv prefix initialization. Until a reviewed
    # isolated venv loader exists, never certify its base environment instead.
    for path in {executable.absolute(), executable.resolve()}:
        if any((directory / "pyvenv.cfg").exists()
               for directory in (path.parent, path.parent.parent)):
            raise ValueError("WOFOST isolated provider fixtures do not yet support virtualenv runtimes")


def require_runtime_current(report: dict) -> dict:
    """Read-only freshness check. Caller must first authenticate its receipt."""
    try:
        rows = report["fixtures"]
        runtime = report["runtime"]
        if (report.get("policy") != POLICY or report.get("recipe") != RECIPE
                or report.get("ok") is not True or report.get("status") != "passed"
                or report.get("native_provider_execution") is not True
                or report.get("model_execution") is not False
                or report.get("scientific_validation") is not False
                or report.get("fixture_protocol_sha256") != fixture_protocol_sha256()
                or report.get("fixture_ids") != fixture_ids()
                or report.get("fixture_count") != len(fixture_ids())
                or [r.get("id") for r in rows] != fixture_ids()
                or any(r.get("ok") is not True or r.get("input_unchanged") is not True for r in rows)
                or runtime.get("python_version", [])[:2] != [3, 12]
                or runtime.get("pcse_version") != PCSE_VERSION
                or report.get("runtime_identity") != _hash(runtime)):
            raise ValueError("Incomplete or outdated WOFOST native fixture report")
        if report.get("isolation") != {"no_site": True, "isolated": True,
                "no_bytecode": True, "scratch_home": True, "scratch_user_settings": True,
                "candidate_imported": False, "model_executed": False}:
            raise ValueError("Missing WOFOST fixture isolation evidence")
        selected = Path(runtime["selected_python"])
        if not selected.is_absolute() or str(selected.resolve()) != runtime["resolved_python"]:
            raise ValueError("The selected WOFOST runtime path changed")
        _reject_virtualenv(selected)
        pcse_root = Path(runtime["pcse_root"])
        inventory = {p.relative_to(pcse_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in sorted(pcse_root.rglob("*.py")) if "__pycache__" not in p.parts}
        if (inventory != runtime["pcse_inventory"]
                or any(inventory.get(rel) != pin for rel, pin in PCSE_PINS.items())):
            raise ValueError("Native PCSE source changed; verify WOFOST routing again")
        files = runtime["files"]
        paths = [row["path"] for row in files]
        required = {str((pcse_root / relative).absolute()) for relative in PCSE_PINS}
        if (not files or len(set(paths)) != len(paths)
                or not required <= set(paths)
                or not any(row["resolved_path"] == runtime["resolved_python"] for row in files)
                or any(not _file_current(row) for row in files)):
            raise ValueError("Native runtime/module content changed; verify WOFOST routing again")
    except (KeyError, TypeError, AttributeError, OSError) as exc:
        raise ValueError("WOFOST native fixture evidence is incomplete or unavailable") from exc
    return report


def validate_behavior(base: Path, candidate: Path, python: str | Path) -> dict:
    """Run real provider-only fixtures; unavailable dependencies fail closed."""
    report = {"policy": POLICY, "recipe": RECIPE, "ok": False, "status": "failed",
              "native_provider_execution": False, "model_execution": False,
              "scientific_validation": False,
              "fixture_protocol_sha256": fixture_protocol_sha256(),
              "fixture_ids": fixture_ids(), "fixture_count": 0, "fixtures": [],
              "scope": "WOFOST72 stage-six parameter routing only; stage five is unchanged"}
    try:
        expected = expected_changes(Path(base), "WOFOST").get(TOOL_PATH)
        if expected is None:
            raise ValueError("No recognized WOFOST routing projection is available")
        old = _ordinary(Path(base) / TOOL_PATH)
        actual = _ordinary(Path(candidate) / TOOL_PATH)
        if actual != expected:
            raise ValueError("Candidate differs from the exact WOFOST routing projection")
        executable = Path(python)
        if not executable.is_absolute():
            raise ValueError("WOFOST fixtures require an absolute selected Python path")
        executable = executable.absolute()
        if not executable.is_file():
            raise ValueError("An existing selected Python runtime is required")
        _reject_virtualenv(executable)
        selected_before = {"path": str(executable), "resolved_path": str(executable.resolve()),
                           "size": executable.stat().st_size,
                           "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}
        payload = {"base": str(Path(base).resolve()), "candidate": str(Path(candidate).resolve()),
                   "python": str(executable), "pcse_pins": PCSE_PINS, "cases": _cases(),
                   "old_fragment": textwrap.dedent(_OLD_BLOCK + _PARAMS),
                   "new_fragment": textwrap.dedent(_NEW_BLOCK + _PARAMS)}
        with tempfile.TemporaryDirectory(prefix="geoforge-wofost-routing-") as folder:
            scratch = Path(folder)
            env = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE"}}
            env.update(HOME=folder, USERPROFILE=folder, TEMP=folder, TMP=folder, TMPDIR=folder,
                       USERNAME="geoforge-fixture", USER="geoforge-fixture",
                       PATH=os.pathsep.join([str(executable.parent),
                           str(Path(env.get("SYSTEMROOT", "C:/Windows")) / "System32")]))
            result = subprocess.run([str(executable), "-I", "-S", "-B", "-c", _CHILD],
                input=json.dumps(payload), capture_output=True, text=True,
                encoding="utf-8", errors="replace", cwd=scratch, env=env, timeout=90)
        lines = [line.partition("=")[2] for line in result.stdout.splitlines()
                 if line.startswith("GEOFORGE_WOFOST_ROUTING=")]
        if result.returncode or len(lines) != 1:
            # No inherited credentials are passed to the child. Still return a
            # bounded diagnostic instead of arbitrary captured command output.
            error = result.stderr.strip().splitlines()
            detail = error[-1][:300] if error else "no complete native fixture result"
            raise ValueError("Native WOFOST provider fixtures failed: " + detail)
        native = json.loads(lines[0])
        if (not _file_current(selected_before)
                or _ordinary(Path(base) / TOOL_PATH) != old
                or _ordinary(Path(candidate) / TOOL_PATH) != actual):
            raise ValueError("Source, candidate or Python changed during native fixtures")
        native["runtime"]["files"].append(selected_before)
        # Alias and canonical selected paths can already be the same entry.
        native["runtime"]["files"] = list({row["path"]: row for row in native["runtime"]["files"]}.values())
        native["runtime"]["files"].sort(key=lambda row: row["path"])
        report.update(native, ok=True, status="passed", native_provider_execution=True,
                      fixture_count=len(native["fixtures"]),
                      base_tool_sha256=hashlib.sha256(old).hexdigest(),
                      candidate_tool_sha256=hashlib.sha256(actual).hexdigest(),
                      runtime_identity=_hash(native["runtime"]))
        require_runtime_current(report)
    except (ValueError, OSError, SyntaxError, subprocess.SubprocessError) as exc:
        report.update(ok=False, status="failed", error=str(exc)[:600])
    return report
