"""Static path adaptation: no preflight, runtime probe or model is launched."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from kiss_cli import helper_identity, ki_path_contracts as paths_fix, paths, port

FIXTURES = Path(__file__).parent / "fixtures"
MANIFEST = '''# preserved metadata
package:
  name: WOFOST
  language: python
  implementation:
    version: PCSE 6.0.12 / WOFOST 7.2
  binary:
    path: KISSPATH_KI_ROOT/WOFOST/run_and_score.py # preserved comment
    type: Python
pipeline:
  stages: [s6_execution]
'''


def prepare(tmp_path, *, portable=False, newline="\n"):
    project = tmp_path / "project"
    project.mkdir()
    cfg = paths.KissConfig.default(project)
    cfg.python = str(project / "runtime" / "python.exe")
    Path(cfg.python).parent.mkdir()
    Path(cfg.python).write_bytes(b"fixture runtime identity, never executed")
    helper = project / "models" / "WOFOST" / "ktc" / "fixture"
    helper.mkdir(parents=True)
    (helper / "ki_tools_common").mkdir()
    (helper / "ki_tools_common" / "__init__.py").write_text("# fixture identity only\n")
    cfg.roles["ki_tools_common"] = helper
    files = helper_identity.package_files(helper)
    binding = {"source_files": files, "fixture": "no execution", "python": cfg.python,
               "relocation": cfg.relocation,
               "roles": {key: str(value) for key, value in cfg.roles.items() if key != "ki_tools_common"}}
    marker = {"schema_version": 2, "binding": binding, "files": files,
              "binding_sha256": hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()}
    (helper / helper_identity.MARKER).write_text(json.dumps(marker))
    base, candidate = tmp_path / "source", tmp_path / "candidate"
    base.mkdir(); candidate.mkdir()
    target = project / "models" / "WOFOST" / "ki"
    target.mkdir(parents=True)
    texts = {
        paths_fix.PREFLIGHT: (FIXTURES / "wofost_preflight_published.py").read_text(encoding="utf-8"),
        paths_fix.RUNNER: (FIXTURES / "wofost_entrypoint_published.py").read_text(encoding="utf-8"),
        paths_fix.MANIFEST: MANIFEST,
    }
    for name, original in texts.items():
        text = original if portable else port.unsubstitute(original, cfg)[0]
        (base / name).write_bytes(text.replace("\n", newline).encode("utf-8"))
        (candidate / name).write_bytes(port.unsubstitute(original, cfg)[0].replace("\n", newline).encode("utf-8"))
    (target / paths_fix.RUNNER).write_bytes((candidate / paths_fix.RUNNER).read_bytes())
    return base, candidate, cfg, target


def apply(base, candidate, cfg, target):
    changes = paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target)
    assert set(changes) == {paths_fix.PREFLIGHT, paths_fix.MANIFEST}
    for name, body in changes.items():
        (candidate / name).write_bytes(body)
    return changes


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_exact_portable_and_retained_normalization_share_one_bound_transform(tmp_path, portable, newline):
    base, candidate, cfg, target = prepare(tmp_path, portable=portable, newline=newline)
    originals = {p.name: p.read_bytes() for p in base.iterdir()}
    changes = apply(base, candidate, cfg, target)
    report = paths_fix.validate_behavior(base, candidate, cfg, target_root=target)
    assert report["ok"] and report["runtime_bound"]
    assert all(report[key] is False for key in ("native_execution", "model_execution", "preflight_passed", "scientific_validation"))
    assert report["runtime"]["target_ki"] == str(target)
    paths_fix.require_runtime_current(report)
    assert paths_fix.config_identity(paths_fix.projection_config(report)) == paths_fix.config_identity(cfg)
    projected = port.unsubstitute(originals[paths_fix.PREFLIGHT].decode(), cfg)[0].encode()
    text = changes[paths_fix.PREFLIGHT].decode()
    tree = ast.parse(text)
    values = paths_fix._assignments(tree)
    assert ast.literal_eval(values["PYTHON"].value) == cfg.python.replace("\\", "/")
    assert ast.literal_eval(values["KI_TOOLS_COMMON"].value) == str(cfg.roles["ki_tools_common"]).replace("\\", "/")
    assert ast.dump(values["MODEL_ENTRYPOINT"].value) == ast.dump(ast.parse('os.path.join(KI_DIR, "run_and_score.py")', mode="eval").body)
    # Restore exactly the three RHS spans to prove every other byte survives,
    # including comments and Windows CRLF. The ordinary role expansion is
    # already the baseline for portable fresh materialization.
    old = paths_fix._assignments(ast.parse(projected.decode()))
    restored = text
    for name in reversed(paths_fix._CHANGED_NAMES):
        new_fragment = ast.get_source_segment(text, values[name].value)
        old_fragment = ast.get_source_segment(projected.decode(), old[name].value)
        assert restored.count(new_fragment) == 1
        restored = restored.replace(new_fragment, old_fragment, 1)
    assert restored.encode() == projected
    assert b"# preserved comment" in changes[paths_fix.MANIFEST]
    assert str(target / paths_fix.RUNNER).replace("\\", "/").encode() in changes[paths_fix.MANIFEST]
    assert originals == {p.name: p.read_bytes() for p in base.iterdir()}


@pytest.mark.parametrize("name", ["SHAW", "VIC", "DSSAT", "WOFOST-unknown"])
def test_other_model_inventory_is_unchanged(tmp_path, name):
    assert paths_fix.expected_changes(tmp_path, name) == {}


@pytest.mark.parametrize("old,new", [
    ('"(3, 12)"', '"(3, 13)"'),
    ('check_import(checks, module, critical=True)', 'check_import(checks, module, critical=False)'),
    ('import subprocess', 'import subprocess\nos = fake_os'),
    ('import subprocess', 'import subprocess\nside_effect()'),
    ('os.path.join(HYDROCRAFT_ROOT, "python_env", "bin", "python")', 'os.path.join(discover_root(), "python")'),
    ('"pcse.models",', '"unrelated.models",'),
    ('sys.exit(1 if critical_failed else 0)', 'sys.exit(0)'),
])
def test_changed_or_shadowed_preflight_decisions_never_qualify(tmp_path, old, new):
    base, candidate, cfg, target = prepare(tmp_path)
    path = base / paths_fix.PREFLIGHT
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    assert paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target) == {}
    with pytest.raises(ValueError):
        paths_fix.validate_behavior(base, candidate, cfg, target_root=target)


@pytest.mark.parametrize("suffix", ["\nside_effect()\n", "\nHERE = 'other'\n", "\nimport evil\n"])
def test_runner_whole_ast_is_bound_before_activating_entrypoint(tmp_path, suffix):
    base, _, cfg, target = prepare(tmp_path)
    runner = base / paths_fix.RUNNER
    runner.write_bytes(runner.read_bytes() + suffix.encode())
    assert paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target) == {}


@pytest.mark.parametrize("change", [
    lambda text: text.replace("type: Python", "type: Python\n    type: Python"),
    lambda text: text.replace("binary:", "binary: &entry"),
    lambda text: text.replace("run_and_score.py", "other_runner.py"),
    lambda text: text.replace("language: python", "language: fortran"),
    lambda text: text.replace("name: WOFOST", "name: DSSAT"),
])
def test_ambiguous_or_wrong_manifest_is_refused(tmp_path, change):
    base, _, cfg, target = prepare(tmp_path)
    path = base / paths_fix.MANIFEST
    path.write_text(change(path.read_text()), encoding="utf-8")
    assert paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target) == {}


def test_missing_runner_wrong_target_or_missing_configuration_is_not_supported(tmp_path):
    base, _, cfg, target = prepare(tmp_path)
    assert not paths_fix.expected_changes(base, "WOFOST", cfg)
    assert not paths_fix.expected_changes(base, "WOFOST", None, target_root=target)
    assert not paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target.parent / "other")
    wrong = copy.deepcopy(cfg); wrong.roles["server_root"] = tmp_path / "shared"
    assert not paths_fix.expected_changes(base, "WOFOST", wrong, target_root=target)
    (base / paths_fix.RUNNER).unlink()
    assert not paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target)


@pytest.mark.parametrize("relative", [paths_fix.PREFLIGHT, paths_fix.MANIFEST, paths_fix.RUNNER])
def test_candidate_extra_edit_never_passes_exact_projection(tmp_path, relative):
    base, candidate, cfg, target = prepare(tmp_path)
    apply(base, candidate, cfg, target)
    path = candidate / relative
    path.write_bytes(path.read_bytes() + b"\n# another edit\n")
    with pytest.raises(ValueError):
        paths_fix.validate_behavior(base, candidate, cfg, target_root=target)


@pytest.mark.parametrize("drift", ["python", "helper", "marker", "runner", "policy", "config", "target"])
def test_current_report_checks_exact_runtime_and_helper_bytes(tmp_path, drift):
    base, candidate, cfg, target = prepare(tmp_path)
    apply(base, candidate, cfg, target)
    report = paths_fix.validate_behavior(base, candidate, cfg, target_root=target)
    if drift == "python":
        Path(cfg.python).write_bytes(b"changed runtime")
    elif drift == "helper":
        (cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("changed")
    elif drift == "marker":
        (cfg.roles["ki_tools_common"] / helper_identity.MARKER).write_text("{}")
    elif drift == "runner":
        (target / paths_fix.RUNNER).write_text("changed")
    elif drift == "policy":
        report["policy_sha256"] = "0" * 64
    elif drift == "config":
        report["runtime"]["config"]["python"] = str(tmp_path / "other.exe")
    else:
        report["runtime"]["target_ki"] = str(tmp_path / "wrong")
    with pytest.raises(ValueError):
        paths_fix.require_runtime_current(report)


@pytest.mark.parametrize("report", [None, {}, [], {"ok": True}, {"runtime": None}])
def test_incomplete_report_or_portable_only_claim_is_not_current(report):
    with pytest.raises(ValueError):
        paths_fix.require_runtime_current(report)


def test_source_bounds_and_newline_ambiguity_fail_closed(tmp_path, monkeypatch):
    base, _, cfg, target = prepare(tmp_path)
    path = base / paths_fix.PREFLIGHT
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n", 1))
    assert not paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target)
    monkeypatch.setattr(paths_fix, "MAX_BYTES", 32)
    assert not paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target)


def test_internally_consistent_helper_for_another_python_is_rejected(tmp_path):
    base, candidate, cfg, target = prepare(tmp_path)
    apply(base, candidate, cfg, target)
    marker = cfg.roles["ki_tools_common"] / helper_identity.MARKER
    doc = json.loads(marker.read_text())
    doc["binding"]["python"] = str(tmp_path / "old-python.exe")
    doc["binding_sha256"] = hashlib.sha256(json.dumps(doc["binding"], sort_keys=True).encode()).hexdigest()
    marker.write_text(json.dumps(doc))
    helper_identity.checked_marker(marker.parent)  # Internal consistency alone passes.
    with pytest.raises(ValueError, match="different saved runtime"):
        paths_fix.validate_behavior(base, candidate, cfg, target_root=target)


@pytest.mark.parametrize("key", ["source_files", "candidate_files", "unchanged_decisions_sha256"])
def test_missing_structural_proof_never_counts_as_current(tmp_path, key):
    base, candidate, cfg, target = prepare(tmp_path)
    apply(base, candidate, cfg, target)
    report = paths_fix.validate_behavior(base, candidate, cfg, target_root=target)
    del report[key]
    with pytest.raises(ValueError):
        paths_fix.require_runtime_current(report)


@pytest.mark.parametrize("relative", [paths_fix.PREFLIGHT, paths_fix.RUNNER])
def test_shared_hardlinked_source_is_rejected(tmp_path, relative):
    base, _, cfg, target = prepare(tmp_path)
    os.link(base / relative, tmp_path / "shared-source.py")
    assert not paths_fix.expected_changes(base, "WOFOST", cfg, target_root=target)
