"""Exact crop API repair, real provider fixtures and versioned gate boundaries."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import ki_copy, ki_guard, ki_maintenance as core, ki_maintenance_crop as crop
from kiss_cli import ki_maintenance_dispatch as dispatch, ki_verification, ki_review_agents
from .test_ki_maintenance import case as legacy_case, metadata, verify as verify_legacy
from .test_ki_verification_boundaries import isolated_engine, write_package
from .test_maintenance_interface_runtime import project_interface, investigation_case, investigation_maintenance

ORIGINAL = Path(__file__).parent / "fixtures/wofost_stage1_published.py"
NATIVE_PYTHON = os.environ.get("GEOFORGE_WOFOST_TEST_PYTHON",
    "D:/GeoForge-Setup-Tracer-20261010/workroot/wofost/python_env/bin/python.exe")


def trees(root, raw=None):
    base, candidate = root / "base", root / "candidate"
    for path in (base, candidate):
        (path / crop.TOOL_PATH).parent.mkdir(parents=True)
        (path / crop.TOOL_PATH).write_bytes(ORIGINAL.read_bytes() if raw is None else raw)
    crop.apply_recipe(candidate, source=base, name="WOFOST", recipe=crop.RECIPE)
    return base, candidate


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_projection_changes_only_three_exact_api_diagnostic_spans(tmp_path, newline):
    raw = ORIGINAL.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
    base, candidate = trees(tmp_path, raw)
    after = (candidate / crop.TOOL_PATH).read_bytes()
    for before, new in ((crop._OLD_CROPS, crop._NEW_CROPS),
                        (crop._OLD_VARIETIES, crop._NEW_VARIETIES), (crop._OLD_IMPORT, crop._NEW_IMPORT)):
        after = after.replace(new.encode().replace(b"\n", newline), before.encode().replace(b"\n", newline), 1)
    assert after == raw
    assert list(crop.expected_changes(base, "WOFOST")) == [crop.TOOL_PATH]
    assert crop.expected_changes(candidate, "WOFOST") == {}
    assert crop.expected_changes(base, "DSSAT") == {}


@pytest.mark.parametrize("old,new", [
    (b'CROP_NAME = "wheat"', b'CROP_NAME = "maize"'),
    (b'VARIETY_NAME = sys.argv[2]', b'VARIETY_NAME = "Different"'),
    (b'CROP_DIR = sys.argv[3]', b'CROP_DIR = "Different"'),
    (b'cropdata.set_active_crop(CROP_NAME, VARIETY_NAME)', b'cropdata.set_active_crop("maize", VARIETY_NAME)'),
    (b'print(json.dumps(result, indent=2, default=str))', b'print(result)'),
    (b'sys.exit(2)', b'sys.exit(0)'),
])
def test_unknown_scientific_or_cli_or_output_variants_have_no_recipe(tmp_path, old, new):
    path = tmp_path / crop.TOOL_PATH
    path.parent.mkdir(parents=True)
    raw = ORIGINAL.read_bytes()
    assert old in raw
    path.write_bytes(raw.replace(old, new, 1))
    assert crop.expected_changes(tmp_path, "WOFOST") == {}


def test_mixed_newlines_are_unrecognized(tmp_path):
    path = tmp_path / crop.TOOL_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(ORIGINAL.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n", 1))
    assert crop.expected_changes(tmp_path, "WOFOST") == {}


def test_unapproved_candidate_never_launches_python(tmp_path, monkeypatch):
    base, candidate = trees(tmp_path)
    path = candidate / crop.TOOL_PATH
    path.write_bytes(path.read_bytes() + b"\nprint('unreviewed')\n")
    monkeypatch.setattr(crop.subprocess, "run", lambda *a, **kw: pytest.fail("Must not run"))
    report = crop.validate_behavior(base, candidate, NATIVE_PYTHON)
    assert not report["ok"] and report["fixture_count"] == 0
    assert "exact crop-provider projection" in report["error"]


@pytest.fixture(scope="module")
def native_report(tmp_path_factory):
    base, candidate = trees(tmp_path_factory.mktemp("crop-native"))
    report = crop.validate_behavior(base, candidate, NATIVE_PYTHON)
    assert report["ok"], report.get("error")
    return report


def test_real_provider_contract_and_failure_diagnostics(native_report):
    report = crop.require_runtime_current(native_report)
    assert report["fixture_count"] == 9
    assert report["runtime"]["pcse_version"] in {"6.0.12", "6.0.13"}
    assert report["model_execution"] is False
    assert report["isolation"]["candidate_imported"] is False
    assert report["isolation"]["no_site"] and report["isolation"]["no_bytecode"]
    assert all(row["ok"] and row["input_unchanged"] for row in report["fixtures"])
    assert next(row for row in report["fixtures"] if row["id"] == "unknown_variety")["outcome"] == "exit_2"


@pytest.mark.parametrize("field,value", [
    ("policy", core.POLICY), ("recipe", "wofost_parameter_routing"), ("fixture_count", 0),
    ("fixture_protocol_sha256", "0" * 64), ("model_execution", True), ("ok", False),
])
def test_incomplete_or_wrong_native_evidence_rejected(native_report, field, value):
    report = deepcopy(native_report)
    report[field] = value
    with pytest.raises(ValueError):
        crop.require_runtime_current(report)


def test_same_size_same_timestamp_dependency_mutation_invalidates_fixture(native_report, tmp_path):
    report = deepcopy(native_report)
    path = tmp_path / "loaded_dependency.py"
    path.write_bytes(b"a=1\n")
    saved = path.stat()
    report["runtime"]["files"].append(crop.native._runtime_file(path))
    report["runtime_identity"] = core._hash(report["runtime"])
    crop.require_runtime_current(report)
    path.write_bytes(b"a=2\n")
    os.utime(path, ns=(saved.st_atime_ns, saved.st_mtime_ns))
    with pytest.raises(ValueError, match="dependency changed"):
        crop.require_runtime_current(report)


@pytest.fixture
def case(tmp_path, monkeypatch, native_report):
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    with isolated_engine(tmp_path) as engine:
        active = tmp_path / "active"
        write_package(active, "WOFOST")
        metadata(active, "WOFOST")
        (active / crop.TOOL_PATH).parent.mkdir(parents=True)
        (active / crop.TOOL_PATH).write_bytes(ORIGINAL.read_bytes())
        ki_guard.enroll(active)
        source = core.capture_source(active, "WOFOST")
        candidate = tmp_path / "candidate"
        ki_copy.copytree(Path(source["base_root"]), candidate)
        dispatch.apply_recipe(candidate, source=Path(source["base_root"]), recipe=crop.RECIPE, name="WOFOST")
        # Native execution is tested once against actual installed providers;
        # these gate cases reuse that exact result to exercise real signatures.
        monkeypatch.setattr(crop, "validate_behavior", lambda *a: deepcopy(native_report))
        yield SimpleNamespace(active=active, source=source, candidate=candidate, engine=engine)


def verify(case):
    return crop.verify_candidate(case.candidate, source=case.source, name="WOFOST", runtime_python=NATIVE_PYTHON)


def test_crop_gate_runs_kdt_and_does_not_claim_authoring_or_model_readiness(case):
    report = verify(case)
    assert report["ok"] and case.engine.seen
    assert report["gate_policy"] == crop.POLICY and report["scope"] == crop.SCOPE
    assert report["native_regression"] == {"status": "not_run", "verified": False}
    assert report["authoring_verification"] is False and report["scientific_validation"] is False
    assert report["literature_evidence"] == "unchanged_published_metadata_only"
    assert dispatch.require_current(case.candidate, report, source=case.source) == report
    with pytest.raises(ValueError):
        core.require_current(case.candidate, report)
    with pytest.raises(ValueError):
        ki_verification.require_current(case.candidate, report)


def test_existing_signed_maintenance_still_uses_unchanged_legacy_gate(legacy_case):
    report = verify_legacy(legacy_case)
    assert dispatch.verifier(report) is core
    assert dispatch.require_current(legacy_case.candidate, report, source=legacy_case.source) == report
    assert core.require_current(legacy_case.candidate, report) == report


@pytest.mark.parametrize("policy,recipe", [("unknown", crop.RECIPE), (crop.POLICY, "unknown"), (None, crop.RECIPE)])
def test_unknown_policy_or_recipe_never_falls_back(policy, recipe):
    with pytest.raises(ValueError):
        dispatch.verifier({"gate_policy": policy, "maintenance_recipe": recipe})


@pytest.mark.parametrize("relative", ["SKILL.md", "docs/papers.json", "docs/validation_convention.yaml", "tools/run.py"])
def test_unrelated_changes_cannot_reuse_published_evidence(case, relative):
    path = case.candidate / relative
    path.write_bytes(path.read_bytes() + b"\n# unauthorized\n")
    with pytest.raises(ValueError, match="maintenance contract"):
        verify(case)
    assert case.engine.seen == []


def test_kdt_failure_still_blocks_even_when_native_provider_fixtures_pass(case):
    case.engine.ok = False
    report = verify(case)
    assert not report["ok"] and "fixture KDT failure" in report["failures"]
    with pytest.raises(ValueError):
        dispatch.require_current(case.candidate, report)


def test_current_runtime_required_for_adoption_and_whole_candidate_checked(case, monkeypatch):
    report = verify(case)
    with monkeypatch.context() as changed:
        changed.setattr(crop, "require_runtime_current", lambda *_: (_ for _ in ()).throw(ValueError("runtime stale")))
        with pytest.raises(ValueError, match="runtime stale"):
            ki_guard.activate_maintenance(case.active, case.candidate, report, source=case.source, quiescent=True)
    assert (case.active / crop.TOOL_PATH).read_bytes() == ORIGINAL.read_bytes()
    accepted = ki_guard.activate_maintenance(case.active, case.candidate, report, source=case.source, quiescent=True)
    assert accepted["origin"] == "verified_maintenance_candidate"
    assert (case.active / crop.TOOL_PATH).read_bytes() == (case.candidate / crop.TOOL_PATH).read_bytes()


def test_report_forgery_and_stale_policy_do_not_dispatch_to_weaker_gate(case, monkeypatch):
    report = verify(case)
    changed = deepcopy(report)
    changed["gate_policy"] = core.POLICY
    with pytest.raises(ValueError):
        dispatch.require_current(case.candidate, changed)
    monkeypatch.setattr(crop, "policy_digest", lambda: "0" * 64)
    with pytest.raises(ValueError, match="stale"):
        dispatch.require_current(case.candidate, report)


def test_source_and_candidate_swaps_are_rejected(case, tmp_path):
    report = verify(case)
    other_source = deepcopy(case.source)
    other_source["base_digest"] = "0" * 64
    with pytest.raises(ValueError, match="another source"):
        dispatch.require_current(case.candidate, report, source=other_source)
    other_candidate = tmp_path / "swapped-candidate"
    ki_copy.copytree(case.candidate, other_candidate)
    path = other_candidate / crop.TOOL_PATH
    path.write_bytes(path.read_bytes().replace(b'CROP_NAME = "wheat"', b'CROP_NAME = "maize"'))
    with pytest.raises(ValueError):
        dispatch.require_current(other_candidate, report)


def test_review_capabilities_describe_current_contracts_without_granting_execution():
    from kiss_cli import flowgate
    message = ki_review_agents._instructions("contract_runtime", "f" * 64)
    for name in flowgate.load().project_data_formats.FORMAT_IDS:
        assert name in message
    assert "missing declaration is distinct from an unsupported format" in message
    assert "Reviewers remain read-only" in message
    assert "campaign_start='YYYY-MM-DD'" in message


def test_crop_gui_workflow_binds_selected_runtime_and_retains_post_adoption_gates(project_interface, monkeypatch):
    from kiss_cli import ki_investigation as inv, ki_maintenance_recipes, software_verification
    from .test_ki_investigation import new, reviewer
    case = project_interface
    monkeypatch.setattr(crop, "apply_recipe", ki_maintenance_recipes.apply_recipe)
    monkeypatch.setattr(crop, "require_current", core.require_current)
    old_verify = core.verify_candidate
    def verify_crop(root, **kwargs):
        report = old_verify(root, **kwargs)
        report.update(gate_policy=crop.POLICY, maintenance_recipe=crop.RECIPE,
                      changes=[{"path": crop.TOOL_PATH}])
        return report
    monkeypatch.setattr(crop, "verify_candidate", verify_crop)
    job = new(case.pair)
    inv.run_reviews(case.project, job["id"], reviewer)
    inv.create_draft(case.project, job["id"], "M", repair_mode="maintenance", maintenance_recipe=crop.RECIPE)
    result = inv.verify_draft(case.project, job["id"])
    expected = inv._project_runtime_config(case.project, "M", case.active)
    assert case.calls == [case.cfg.python]
    assert result["verification"]["runtime_identity"] == software_verification.runtime_identity(expected)
    assert result["can_apply"]
    applied = inv.apply(case.project, job["id"], result["verification"]["id"])
    assert applied["apply"]["requires_preflight"] and applied["apply"]["requires_plan_review"]
