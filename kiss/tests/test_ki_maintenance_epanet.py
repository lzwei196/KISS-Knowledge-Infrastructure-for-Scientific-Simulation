"""Exact EPANET path recipe, real signatures and copies; no model execution.

Published source fixtures are inert text. Runtime identities and the KDT engine
are explicit fixture files/doubles; these tests never claim native readiness.
"""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from kiss_cli import helper_identity, ki_copy, ki_guard, ki_maintenance as core
from kiss_cli import ki_maintenance_epanet as fix, ki_maintenance_gate as gate
from kiss_cli import ki_maintenance_dispatch as legacy, ki_maintenance_crop as crop
from kiss_cli import ki_verification, paths, port
from .test_ki_maintenance import metadata
from .test_ki_verification_boundaries import isolated_engine, write_package

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST_TEXT = '''# preserved package metadata
package:
  name: EPANET
  language: c
  implementation:
    version: 2.2.0
  binary:
    path: KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/EPANET/source/repo/SRC_engines/build/src/run/runepanet # preserved
    type: work_dir
tools:
  count: 2
  files: [tools/run.py, tools/run_epanet.py]
summary:
  total_tools: 2
'''


def prepare(tmp_path, *, newline="\n", project=False):
    root = tmp_path / "workspace with spaces 中文"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python = str(root / "venv" / "Scripts" / "python.exe")
    Path(cfg.python).parent.mkdir(parents=True)
    Path(cfg.python).write_bytes(b"fixture selected interpreter; never executed")
    active = root / "models" / "EPANET" / "ki" if project else root / "ki"
    write_package(active, "EPANET")
    metadata(active, "EPANET")
    texts = {fix.PREFLIGHT: (FIXTURES / "epanet_preflight_published.py").read_text(encoding="utf-8"),
             fix.RUNNER: (FIXTURES / "epanet_runner_published.py").read_text(encoding="utf-8"),
             fix.MANIFEST: MANIFEST_TEXT}
    for relative, text in texts.items():
        path = active / relative
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(port.unsubstitute(text, cfg)[0].replace("\r\n", "\n").replace("\n", newline).encode("utf-8"))
    (active / fix.CASE).parent.mkdir(parents=True)
    (active / fix.CASE).write_bytes((FIXTURES / "epanet_tutorial.inp").read_bytes())
    binary_root = cfg.roles["binaries"]
    binary_root.mkdir()
    for name in ("runepanet.exe", "libepanet2.dll"):
        (binary_root / name).write_bytes(b"fixture runtime identity; never executed " + name.encode())
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
    (active.parent / "kiss.yaml").write_text("name: EPANET\n", encoding="utf-8")
    (root / ".geoforge").mkdir()
    (root / ".geoforge" / "ki-library-selection.json").write_text('{"source_commit":"fixture"}')
    return cfg, active


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    with isolated_engine(tmp_path) as engine:
        cfg, active = prepare(tmp_path)
        ki_guard.enroll(active)
        source = core.capture_source(active, "EPANET")
        candidate = tmp_path / "candidate"
        ki_copy.copytree(Path(source["base_root"]), candidate)
        gate.apply_recipe(candidate, source=Path(source["base_root"]), recipe=fix.RECIPE,
            name="EPANET", runtime_config=cfg, target_root=active)
        yield SimpleNamespace(cfg=cfg, active=active, source=source, candidate=candidate, engine=engine)


def verify(c):
    return fix.verify_candidate(c.candidate, source=c.source, name="EPANET",
                                runtime_config=c.cfg, target_root=c.active)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("project", [False, True])
def test_exact_rhs_repair_preserves_every_check_and_case(tmp_path, newline, project):
    cfg, source = prepare(tmp_path, newline=newline, project=project)
    changes = fix.expected_changes(source, "EPANET", cfg, target_root=source)
    assert set(changes) == {fix.PREFLIGHT, fix.RUNNER, fix.MANIFEST}
    for relative, names in ((fix.PREFLIGHT, {"MODEL_DIR", "BINARY_CANDIDATES", "LIBEPANET_CANDIDATES", "TUTORIAL_INP"}),
                            (fix.RUNNER, {"SERVER_DEFAULT_BINARIES"})):
        before = ast.parse((source / relative).read_bytes())
        after = ast.parse(changes[relative])
        old, new = fix.paths_contract._assignments(before), fix.paths_contract._assignments(after)
        for name in names:
            new[name].value = deepcopy(old[name].value)
        assert fix.paths_contract._ast_value(before) == fix.paths_contract._ast_value(after)
    p = changes[fix.PREFLIGHT].decode()
    assert str(cfg.roles["binaries"] / "runepanet.exe").replace("\\", "/") in p
    assert str(cfg.roles["binaries"] / "libepanet2.dll").replace("\\", "/") in p
    assert 'KI_DIR / "test_cases/tutorial/inputs/tutorial.inp"' in p
    assert 'ok and "Usage:" in detail' in p
    assert "sys.exit(1 if critical_failed else 0)" in p
    assert b"# preserved" in changes[fix.MANIFEST]
    assert hashlib.sha256((source / fix.CASE).read_bytes()).hexdigest() == fix.CASE_SHA256
    assert fix.expected_changes(source, "SHAW", cfg, target_root=source) == {}


@pytest.mark.parametrize("relative,old,new", [
    (fix.PREFLIGHT, b'sys.exit(1 if critical_failed else 0)', b'sys.exit(0)'),
    (fix.PREFLIGHT, b'ok and "Usage:" in detail', b'True'),
    (fix.PREFLIGHT, b'"pandas", "numpy", "matplotlib"', b'"numpy"'),
    (fix.RUNNER, b'REQUIRED_SECTIONS = {"[JUNCTIONS]", "[OPTIONS]", "[TIMES]"}', b'REQUIRED_SECTIONS = set()'),
    (fix.RUNNER, b'return None', b'return "fake.exe"'),
])
def test_unknown_checks_or_runner_revisions_fail_before_kdt(tmp_path, relative, old, new):
    cfg, active = prepare(tmp_path)
    path = active / relative
    raw = path.read_bytes()
    assert old in raw
    path.write_bytes(raw.replace(old, new, 1))
    assert fix.expected_changes(active, "EPANET", cfg, target_root=active) == {}


@pytest.mark.parametrize("fault", ["case", "other_binding", "other_target", "mixed_newlines", "unresolved"])
def test_unrecognized_case_or_binding_does_not_get_a_projection(tmp_path, fault):
    cfg, active = prepare(tmp_path)
    target = active
    if fault == "case":
        path = active / fix.CASE
        path.write_bytes(path.read_bytes() + b"\n")
    elif fault == "other_binding":
        cfg.python += "other"
    elif fault == "other_target":
        target = Path(cfg.root) / "another-ki"
    elif fault == "mixed_newlines":
        path = active / fix.PREFLIGHT
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n", 1))
    else:
        (active / fix.PREFLIGHT).write_bytes((FIXTURES / "epanet_preflight_published.py").read_bytes())
    assert fix.expected_changes(active, "EPANET", cfg, target_root=target) == {}


def test_kdt_gate_and_guard_adoption_do_not_confer_readiness(case):
    report = verify(case)
    assert report["ok"] and case.engine.seen
    assert gate.verifier(report) is fix
    assert gate.require_current(case.candidate, report, source=case.source) == report
    assert report["literature_evidence"] == "unchanged_published_metadata_only"
    assert report["native_regression"] == {"status": "not_run", "verified": False}
    assert not report["scientific_validation"] and not report["authoring_verification"]
    assert all(report["path_binding_regression"][k] is False for k in
               ("model_execution", "native_execution", "scientific_validation", "preflight_passed"))
    ki_guard.activate_maintenance(case.active, case.candidate, report, source=case.source, quiescent=True)
    assert ki_guard.require_intact(case.active)["digest"] == report["candidate_digest"]
    assert gate.require_current(case.candidate, report) == report
    assert not (case.active.parent / "status.json").exists()


def test_kdt_rejection_cannot_be_replaced_by_valid_paths(case):
    case.engine.ok = False
    report = verify(case)
    assert not report["ok"] and "fixture KDT failure" in report["failures"]
    with pytest.raises(ValueError):
        gate.require_current(case.candidate, report)


@pytest.mark.parametrize("relative", ["SKILL.md", "docs/papers.json", fix.CASE, fix.PREFLIGHT, fix.RUNNER])
def test_extra_changes_fail_exact_diff_before_kdt(case, relative):
    path = case.candidate / relative
    path.write_bytes(path.read_bytes() + b"\n# extra\n")
    with pytest.raises(ValueError):
        verify(case)
    assert not case.engine.seen


@pytest.mark.parametrize("changed", ["python", "binary", "dll", "helper", "config", "manifest", "selection", "source"])
def test_post_verification_identity_drift_fails_currentness(case, changed):
    report = verify(case)
    choices = {"python": Path(case.cfg.python), "binary": case.cfg.roles["binaries"] / "runepanet.exe",
        "dll": case.cfg.roles["binaries"] / "libepanet2.dll",
        "helper": case.cfg.roles["ki_tools_common"] / "ki_tools_common" / "__init__.py",
        "config": case.active.parent / "kiss.toml", "manifest": case.active.parent / "kiss.yaml",
        "selection": Path(case.cfg.root) / ".geoforge" / "ki-library-selection.json",
        "source": Path(case.source["base_root"]) / fix.PREFLIGHT}
    path = choices[changed]
    path.write_bytes(path.read_bytes() + b"\n# changed\n")
    with pytest.raises(ValueError):
        gate.require_current(case.candidate, report)


def test_unauthenticated_and_wrong_policy_reports_never_fall_back(case):
    report = verify(case)
    for key, value in (("ok", False), ("candidate_digest", "0" * 64), ("scientific_validation", True)):
        bad = deepcopy(report)
        bad[key] = value
        with pytest.raises(ValueError):
            gate.require_current(case.candidate, bad)
    with pytest.raises(ValueError):
        gate.verifier({"gate_policy": fix.POLICY, "maintenance_recipe": crop.RECIPE})
    assert gate.recipe_verifier(crop.RECIPE) is crop
    assert gate.verifier({"gate_policy": core.POLICY}) is core
    assert gate.legacy is legacy


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


def test_additive_registry_accepts_existing_epanet_receipt_without_resigning(case):
    # Issue through the original, byte-preserved gate. Discovering an added
    # recipe must not change the receipt or silently grandfather stale proofs.
    report = verify(case)
    before = deepcopy(report)
    original_policy = fix.policy_digest()
    from kiss_cli import ki_maintenance_registry as registry
    assert registry.verifier(report) is fix
    assert registry.require_current(case.candidate, report, source=case.source) == before
    assert report == before and fix.policy_digest() == original_policy
    assert registry.recipe_verifier(fix.RECIPE) is fix
    ki_guard.activate_maintenance(case.active, case.candidate, report, source=case.source, quiescent=True)
    assert registry.require_current(case.candidate, report, source=case.source) == before
    assert ki_guard.require_intact(case.active)["digest"] == report["candidate_digest"]


def test_additive_registry_does_not_accept_stale_epanet_receipt(case):
    report = verify(case)
    from kiss_cli import ki_maintenance_registry as registry
    with (case.cfg.roles["binaries"] / "runepanet.exe").open("ab") as stream:
        stream.write(b"changed executable")
    with pytest.raises(ValueError):
        registry.require_current(case.candidate, report, source=case.source)


@pytest.mark.parametrize("autocrlf", ["true", "false", "input"])
def test_pinned_case_fixture_survives_windows_checkout(tmp_path, autocrlf):
    # A converting checkout once turned the LF case into CRLF on the release runner,
    # so every recipe test failed CASE_SHA256 there while passing locally.
    repo, checkout = tmp_path / "repo", tmp_path / "checkout"
    relative = Path("kiss/tests/fixtures/epanet_tutorial.inp")
    (repo / relative).parent.mkdir(parents=True)
    root = Path(__file__).resolve().parents[2]
    (repo / ".gitattributes").write_bytes((root / ".gitattributes").read_bytes())
    (repo / relative).write_bytes((FIXTURES / "epanet_tutorial.inp").read_bytes())

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)

    git("init", "--quiet")
    git("-c", "core.autocrlf=false", "add", "--", ".gitattributes", relative.as_posix())
    git("-c", f"core.autocrlf={autocrlf}", "checkout-index", "--all",
        "--prefix=" + checkout.as_posix() + "/")
    assert hashlib.sha256((checkout / relative).read_bytes()).hexdigest() == fix.CASE_SHA256
