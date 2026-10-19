"""SHAW exact Windows path maintenance; no native model or preflight execution.

Real published source/case bytes, host signatures and guarded copies are used.
The PE/Python files and KDT engine are explicitly synthetic, not runtime proofs.
"""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import helper_identity, ki_copy, ki_guard, ki_maintenance as core
from kiss_cli import ki_maintenance_shaw as fix
from kiss_cli import ki_verification, paths, port
from .test_ki_maintenance import metadata
from .test_ki_verification_boundaries import isolated_engine, write_package

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST_TEXT = '''# preserved package metadata
package:
  name: SHAW
  language: fortran
  implementation:
    version: v3.03
  binary:
    path: KISSPATH_BINARIES/shaw/shaw # preserved
    type: ELF
tools:
  count: 2
  files: [tools/run.py, s6_execution/tools/run_shaw.py]
summary:
  total_tools: 2
'''


def synthetic_pe():
    """Inert header fixture sufficient for format identity; never executable."""
    data = bytearray(512)
    data[:2] = b"MZ"
    data[60:64] = (64).to_bytes(4, "little")
    data[64:68] = b"PE\0\0"
    data[68:70] = (0x8664).to_bytes(2, "little")
    data[86:88] = (0x0002).to_bytes(2, "little")
    return bytes(data)


def prepare(tmp_path, *, newline="\n", project=False):
    root = tmp_path / "workspace with spaces 中文"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python = str(root / "venv" / "Scripts" / "python.exe")
    Path(cfg.python).parent.mkdir(parents=True)
    Path(cfg.python).write_bytes(b"fixture selected interpreter; never executed")
    active = root / "models" / "SHAW" / "ki" if project else root / "ki"
    write_package(active, "SHAW")
    metadata(active, "SHAW")
    texts = {fix.PREFLIGHT: (FIXTURES / "shaw_preflight_published.py").read_text(encoding="utf-8"),
             fix.RUNNER: (FIXTURES / "shaw_runner_published.py").read_text(encoding="utf-8"),
             fix.MANIFEST: MANIFEST_TEXT}
    for relative, text in texts.items():
        path = active / relative
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(port.unsubstitute(text, cfg)[0].replace("\r\n", "\n").replace("\n", newline).encode("utf-8"))
    for relative in ("manifest.json", "expected.json", *("inputs/" + name for name in fix.CASE_SHA256S)):
        destination = active / "test_cases/trial" / relative
        destination.parent.mkdir(exist_ok=True, parents=True)
        destination.write_bytes((FIXTURES / "shaw_trial" / relative).read_bytes())
    distribution = root / "model" / "shaw" / "Shaw303"
    distribution.mkdir(parents=True)
    for name in fix.CASE_SHA256S:
        (distribution / name).write_bytes((active / fix.CASE_ROOT / name).read_bytes())
    binary = cfg.roles["binaries"] / "shaw" / "shaw303.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(synthetic_pe())
    helper = cfg.roles["ki_tools_common"]
    (helper / "ki_tools_common").mkdir(parents=True)
    (helper / "ki_tools_common" / "__init__.py").write_text("# fixture identity only\n")
    files = helper_identity.package_files(helper)
    binding = {"source_files": files, "fixture": "no execution", "python": cfg.python,
        "relocation": cfg.relocation,
        "roles": {key: str(value) for key, value in cfg.roles.items() if key != "ki_tools_common"}}
    marker = {"schema_version": 2, "binding": binding, "files": files,
        "binding_sha256": hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()}
    (helper / helper_identity.MARKER).write_text(json.dumps(marker))
    (active.parent / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    (active.parent / "kiss.yaml").write_text("name: SHAW\n", encoding="utf-8")
    (root / ".geoforge").mkdir()
    (root / ".geoforge" / "ki-library-selection.json").write_text('{"source_commit":"fixture"}')
    return cfg, active


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    with isolated_engine(tmp_path) as engine:
        cfg, active = prepare(tmp_path)
        ki_guard.enroll(active)
        source = core.capture_source(active, "SHAW")
        candidate = tmp_path / "candidate"
        ki_copy.copytree(Path(source["base_root"]), candidate)
        fix.apply_recipe(candidate, source=Path(source["base_root"]), recipe=fix.RECIPE,
            name="SHAW", runtime_config=cfg, target_root=active)
        yield SimpleNamespace(cfg=cfg, active=active, source=source, candidate=candidate, engine=engine)


def verify(c):
    return fix.verify_candidate(c.candidate, source=c.source, name="SHAW",
                                runtime_config=c.cfg, target_root=c.active)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("project", [False, True])
def test_exact_repair_preserves_checks_science_and_case(tmp_path, newline, project):
    cfg, source = prepare(tmp_path, newline=newline, project=project)
    changes = fix.expected_changes(source, "SHAW", cfg, target_root=source)
    assert set(changes) == {fix.PREFLIGHT, fix.RUNNER, fix.MANIFEST}
    for relative, names in ((fix.PREFLIGHT, {"PYTHON_ENV", "MANIFEST_BINARY", "TOOL_DEFAULT_BINARY"}),
                            (fix.RUNNER, {"SHAW_EXE"})):
        before = ast.parse((source / relative).read_bytes())
        after = ast.parse(changes[relative])
        old, new = fix.paths_contract._assignments(before), fix.paths_contract._assignments(after)
        for name in names:
            new[name].value = deepcopy(old[name].value)
        assert fix.paths_contract._ast_value(before) == fix.paths_contract._ast_value(after)
    p = changes[fix.PREFLIGHT].decode()
    binary = cfg.roles["binaries"] / "shaw" / "shaw303.exe"
    assert str(binary).replace("\\", "/") in p
    assert str(cfg.python).replace("\\", "/") in p
    assert 'SHAW_DIST_DIR = HYDROCRAFT_ROOT / "model" / "shaw" / "Shaw303"' in p
    assert '"Simultaneous Heat And Water" in output and "Enter the file" in output' in p
    assert 'sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in report_checks) else 1)' in p
    document = yaml.safe_load(changes[fix.MANIFEST])
    assert document["package"]["binary"] == {"path": str(binary).replace("\\", "/"), "type": "PE"}
    assert b"# preserved" in changes[fix.MANIFEST]
    for name, digest in fix.CASE_SHA256S.items():
        assert hashlib.sha256((source / fix.CASE_ROOT / name).read_bytes()).hexdigest() == digest
    expected = json.loads((source / "test_cases/trial/expected.json").read_text())
    assert expected["output_line_counts"]["out.out"] == 599
    assert fix.expected_changes(source, "EPANET", cfg, target_root=source) == {}


@pytest.mark.parametrize("relative,old,new", [
    (fix.PREFLIGHT, b'else 1)', b'else 0)'),
    (fix.PREFLIGHT, b'critical=True, executable=True, nonempty=True', b'critical=False, executable=True, nonempty=True'),
    (fix.PREFLIGHT, b'"Simultaneous Heat And Water" in output', b'True'),
    (fix.PREFLIGHT, b'"ki_tools_common.soil_utils",', b''),
    (fix.RUNNER, b'if result.returncode == 0 and produced:', b'if True:'),
    (fix.RUNNER, b'args.mtstep', b'1'),
])
def test_unknown_checks_or_runner_changes_fail_before_kdt(tmp_path, relative, old, new):
    cfg, active = prepare(tmp_path)
    path = active / relative
    raw = path.read_bytes()
    assert old in raw
    path.write_bytes(raw.replace(old, new, 1))
    assert fix.expected_changes(active, "SHAW", cfg, target_root=active) == {}


@pytest.mark.parametrize("fault", ["case", "distribution", "other_binding", "other_target", "mixed_newlines", "unresolved"])
def test_unrecognized_case_or_binding_gets_no_projection(tmp_path, fault):
    cfg, active = prepare(tmp_path)
    target = active
    if fault in ("case", "distribution"):
        path = (active / fix.CASE_ROOT if fault == "case" else cfg.root / "model/shaw/Shaw303") / "Trial.303.inp"
        path.write_bytes(path.read_bytes() + b"\n")
    elif fault == "other_binding":
        cfg.roles["server_root"] = cfg.root / "different"
    elif fault == "other_target":
        target = Path(cfg.root) / "another-ki"
    elif fault == "mixed_newlines":
        path = active / fix.PREFLIGHT
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n", 1))
    else:
        (active / fix.PREFLIGHT).write_bytes((FIXTURES / "shaw_preflight_published.py").read_bytes())
    assert fix.expected_changes(active, "SHAW", cfg, target_root=target) == {}


@pytest.mark.parametrize("fault", ["missing", "directory", "elf", "dll", "wrong_machine", "bad_offset"])
def test_pe_type_requires_ordinary_native_executable(tmp_path, fault):
    cfg, active = prepare(tmp_path)
    binary = cfg.roles["binaries"] / "shaw/shaw303.exe"
    if fault in ("missing", "directory"):
        binary.unlink()
        if fault == "directory":
            binary.mkdir()
    else:
        data = bytearray(binary.read_bytes())
        if fault == "elf":
            data[:4] = b"\x7fELF"
        elif fault == "dll":
            data[86:88] = (0x2002).to_bytes(2, "little")
        elif fault == "wrong_machine":
            data[68:70] = (0).to_bytes(2, "little")
        else:
            data[60:64] = (2**31).to_bytes(4, "little")
        binary.write_bytes(data)
    assert fix.expected_changes(active, "SHAW", cfg, target_root=active) == {}


def test_real_signatures_require_kdt_and_do_not_confer_readiness(case):
    report = verify(case)
    assert report["ok"] and case.engine.seen
    assert fix.require_current(case.candidate, report, source=case.source) == report
    assert report["literature_evidence"] == "unchanged_published_metadata_only"
    assert report["native_regression"] == {"status": "not_run", "verified": False}
    assert not report["scientific_validation"] and not report["authoring_verification"]
    assert all(report["path_binding_regression"][key] is False for key in
               ("model_execution", "native_execution", "scientific_validation", "preflight_passed"))
    assert not (case.active.parent / "status.json").exists()


def test_registry_guard_adoption_retains_current_shaw_proof(case):
    from kiss_cli import ki_maintenance_registry as gate
    report = verify(case)
    assert gate.verifier(report) is fix
    assert gate.recipe_verifier(fix.RECIPE) is fix
    ki_guard.activate_maintenance(case.active, case.candidate, report, source=case.source, quiescent=True)
    assert ki_guard.require_intact(case.active)["digest"] == report["candidate_digest"]
    assert gate.require_current(case.candidate, report) == report
    assert not (case.active.parent / "status.json").exists()


def test_registry_rejects_mismatched_shaw_recipe_without_fallback():
    from kiss_cli import ki_maintenance_registry as gate
    with pytest.raises(ValueError):
        gate.verifier({"gate_policy": fix.POLICY, "maintenance_recipe": "epanet_runtime_paths"})
    with pytest.raises(ValueError):
        gate.recipe_verifier("shaw_runtime_paths_unreviewed")


def test_vendor_control_is_distinct_retained_binding_not_case_rewrite(case):
    vendor = (FIXTURES / "shaw_trial/vendor_Trial.303.inp").read_bytes()
    assert hashlib.sha256(vendor).hexdigest() == fix.VENDOR_CONTROL_SHA256
    assert fix.VENDOR_CONTROL_SHA256 != fix.CASE_SHA256S["Trial.303.inp"]
    distribution_file = case.cfg.root / "model/shaw/Shaw303/Trial.303.inp"
    distribution_file.write_bytes(vendor)
    report = verify(case)
    recorded = report["path_binding_regression"]["runtime"]["distribution"]["inputs"]["Trial.303.inp"]
    assert recorded["sha256"] == fix.VENDOR_CONTROL_SHA256
    assert fix.require_current(case.candidate, report) == report
    original_case = (case.active / fix.CASE_ROOT / "Trial.303.inp").read_bytes()
    assert (case.candidate / fix.CASE_ROOT / "Trial.303.inp").read_bytes() == original_case
    distribution_file.write_bytes(original_case)
    # Both are recognized sources, but an already signed proof binds one exactly.
    with pytest.raises(ValueError):
        fix.require_current(case.candidate, report)
    (case.active / fix.CASE_ROOT / "Trial.303.inp").write_bytes(vendor)
    assert fix.expected_changes(case.active, "SHAW", case.cfg, target_root=case.active) == {}


def test_missing_kdt_cannot_create_path_maintenance_authority(case):
    case.engine.installed = False
    with pytest.raises(ValueError):
        verify(case)


def test_kdt_rejection_cannot_be_replaced_by_valid_paths(case):
    case.engine.ok = False
    report = verify(case)
    assert not report["ok"] and "fixture KDT failure" in report["failures"]
    with pytest.raises(ValueError):
        fix.require_current(case.candidate, report)


@pytest.mark.parametrize("relative", ["SKILL.md", "docs/papers.json", "test_cases/trial/expected.json",
                                    "test_cases/trial/inputs/Trial.30.wea", fix.PREFLIGHT, fix.RUNNER])
def test_extra_changes_fail_exact_diff_before_kdt(case, relative):
    path = case.candidate / relative
    path.write_bytes(path.read_bytes() + b"\n# extra\n")
    with pytest.raises(ValueError):
        verify(case)
    assert not case.engine.seen


@pytest.mark.parametrize("changed", ["python", "binary", "distribution", "helper", "config", "manifest", "selection", "source"])
def test_post_verification_identity_drift_fails_currentness(case, changed):
    report = verify(case)
    choices = {"python": Path(case.cfg.python), "binary": case.cfg.roles["binaries"] / "shaw/shaw303.exe",
        "distribution": case.cfg.root / "model/shaw/Shaw303/Trial.30.wea",
        "helper": case.cfg.roles["ki_tools_common"] / "ki_tools_common" / "__init__.py",
        "config": case.active.parent / "kiss.toml", "manifest": case.active.parent / "kiss.yaml",
        "selection": Path(case.cfg.root) / ".geoforge" / "ki-library-selection.json",
        "source": Path(case.source["base_root"]) / fix.PREFLIGHT}
    path = choices[changed]
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    with pytest.raises(ValueError):
        fix.require_current(case.candidate, report)


def test_forged_and_wrong_source_reports_reject(case):
    report = verify(case)
    for key, value in (("ok", False), ("candidate_digest", "0" * 64), ("scientific_validation", True)):
        bad = deepcopy(report)
        bad[key] = value
        with pytest.raises(ValueError):
            fix.require_current(case.candidate, bad)
    with pytest.raises(ValueError):
        fix.require_current(case.candidate, report, source={})


def test_candidate_change_during_kdt_is_not_signed(case, monkeypatch):
    original = ki_verification._check_candidate
    def change(*args, **kwargs):
        report = original(*args, **kwargs)
        with (case.candidate / fix.RUNNER).open("ab") as stream:
            stream.write(b"\npass\n")
        return report
    monkeypatch.setattr(ki_verification, "_check_candidate", change)
    with pytest.raises(ValueError):
        verify(case)
