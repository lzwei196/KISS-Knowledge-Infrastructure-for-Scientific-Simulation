"""Real bounded projections through signed maintenance acceptance.

KDT's structural engine/profile are explicit doubles from isolated_engine;
recipes, source/candidate inventory, published metadata, behavior fixtures,
doctor, signatures and receipt identity use production implementations.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from kiss_cli import ki_copy, ki_guard, ki_maintenance as maintenance
from kiss_cli import ki_maintenance_recipes as recipes, ki_verification
from .test_ki_maintenance import metadata
from .test_ki_maintenance_recipes import _DSSAT_SKILL, _OPTIONAL
from .test_ki_verification_boundaries import isolated_engine, write_package


@contextmanager
def model_case(tmp_path, monkeypatch, *, name="DSSAT", combined=False):
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    monkeypatch.setattr(ki_verification, "_preflight_interpreter", lambda: sys.executable)
    with isolated_engine(tmp_path) as engine:
        base = tmp_path / "active"
        write_package(base, name=name, skill=_DSSAT_SKILL.replace("\n", "\r\n"))
        metadata(base, name=name)
        # The helper's generic tool is replaced while constructing the fixture,
        # before host enrollment. No protected/source KI is ever modified.
        (base / "tools/run.py").unlink()
        for filename in ("calib_run.py", "dssat_workdir_setup.py", "run_reference_case.py"):
            (base / "tools" / filename).write_text(
                "raise RuntimeError('indexing must not execute model tools')\n", encoding="utf-8")
        (base / "knowledge_infrastructure.yaml").write_text(
            "tools: {count: 19, files: [tools/calib_run.py, tools/dssat_workdir_setup.py]}\n"
            "summary: {total_tools: 19}\nvalidation: {best_nse: 0.9486}\n", encoding="utf-8")
        if combined:
            # WRF-Hydro's one mandatory executable and optional project data.
            body = "\n".join(line for line in _OPTIONAL.split("\n")
                             if '\"Routing\", executable=True)' not in line)
            body = body.replace("C:/Model Files/测验/vic.exe",
                "KISSPATH_BINARIES/wrf_hydro/source/trunk/NDHMS/Run/wrf_hydro_NoahMP.exe")
            (base / "preflight_check.py").write_text(
                "import os\nimport sys\nimport shutil\nimport subprocess\n"
                "PASS = 0\nFAIL = 0\n" + recipes._CHECK_FILE + body, encoding="utf-8")
        ki_guard.enroll(base)
        source = maintenance.capture_source(base, name)
        frozen = Path(source["base_root"])
        candidate = tmp_path / "candidate"
        ki_copy.copytree(frozen, candidate)
        applied = recipes.apply_recipe(candidate, source=frozen, name=name,
                                       recipe="package_contract" if combined else "tool_inventory")
        yield SimpleNamespace(base=base, frozen=frozen, candidate=candidate, source=source,
                              engine=engine, applied=applied, name=name)


def test_dssat_two_file_recipe_gets_exact_current_maintenance_receipt(tmp_path, monkeypatch):
    with model_case(tmp_path, monkeypatch) as case:
        assert case.applied["changed_files"] == ["SKILL.md", "knowledge_infrastructure.yaml"]
        report = maintenance.verify_candidate(case.candidate, source=case.source, name=case.name)
        assert report["ok"] and report["state"] == "MaintenanceVerified"
        assert len(case.engine.seen) == 1 and case.engine.seen[0][1] == "process_model"
        assert [change["path"] for change in report["changes"]] == case.applied["changed_files"]
        assert report["engine_source_digest"] == "f" * 64  # Explicit structural-engine double.
        assert report["preflight_regression"]["status"] == "not_required"
        assert report["authoring_verification"] is False and report["scientific_validation"] is False
        assert report["native_regression"] == {"status": "not_run", "verified": False}
        assert maintenance.require_current(case.candidate, report, source=case.source) == report
        assert ki_verification.current_report(case.candidate) is None
        for relative in ("docs/papers.json", "docs/validation_convention.yaml", "dag.yaml",
                         "preflight_check.py", "tools/run_reference_case.py"):
            assert (case.candidate / relative).read_bytes() == (case.base / relative).read_bytes()
        assert ki_guard.require_intact(case.base)["digest"] == case.source["base_digest"]


def test_extra_human_skill_edit_rejected_before_kdt_even_with_valid_generated_index(tmp_path, monkeypatch):
    with model_case(tmp_path, monkeypatch) as case:
        skill = case.candidate / "SKILL.md"
        skill.write_bytes(skill.read_bytes().replace(b"NSE >= 0.8", b"NSE >= -10"))
        with pytest.raises(ValueError, match=r"maintenance contract: SKILL\.md"):
            maintenance.verify_candidate(case.candidate, source=case.source, name=case.name)
        assert case.engine.seen == []


def test_wrf_three_file_bundle_requires_real_behavior_and_binds_same_receipt(tmp_path, monkeypatch):
    with model_case(tmp_path, monkeypatch, name="WRF_Hydro", combined=True) as case:
        assert case.applied["changed_files"] == ["SKILL.md", "knowledge_infrastructure.yaml", "preflight_check.py"]
        report = maintenance.verify_candidate(case.candidate, source=case.source, name=case.name)
        assert report["ok"] and report["state"] == "MaintenanceVerified"
        behavior = report["preflight_regression"]
        assert behavior["ok"] is True and behavior["status"] == "fixture_checked"
        assert behavior["model_execution"] == "not_run" and behavior["filesystem"] == "in_memory"
        assert len(behavior["fixtures"]) == 5
        assert [row["returncode"] for row in behavior["fixtures"]] == [0, 0, 1, 1, None]
        assert all(row["ok"] and row["report_count"] == 1 for row in behavior["fixtures"])
        assert behavior["fixtures"][-1]["error"] == "OSError: fixture access failure"
        assert len(case.engine.seen) == 1 and case.engine.seen[0][1] == "process_model"
        assert report["engine_source_digest"] == "f" * 64
        assert report["candidate_digest"] == ki_verification.content_digest(case.candidate)
        assert report["base_digest"] == ki_verification.content_digest(case.frozen)
        assert [change["path"] for change in report["changes"]] == case.applied["changed_files"]
        assert maintenance.require_current(case.candidate, report, source=case.source) == report
        assert report["scientific_validation"] is False
        assert report["native_regression"] == {"status": "not_run", "verified": False}


def test_valid_wrf_behavior_does_not_override_kdt_rejection(tmp_path, monkeypatch):
    with model_case(tmp_path, monkeypatch, name="WRF_Hydro", combined=True) as case:
        case.engine.ok = False
        report = maintenance.verify_candidate(case.candidate, source=case.source, name=case.name)
        assert report["preflight_regression"]["ok"] is True
        assert report["state"] == "MaintenanceRejected" and report["ok"] is False
        assert "fixture KDT failure" in report["failures"]
        assert len(case.engine.seen) == 1
        with pytest.raises(ValueError):
            maintenance.require_current(case.candidate, report, source=case.source)
