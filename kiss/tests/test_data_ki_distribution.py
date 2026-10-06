"""Bundled readers remain visible, separately attributed, and executable as data work."""
import ast
import csv
import json
from pathlib import Path
import shutil
import sys

import pytest

from kiss_cli import api, catalog, ki_guard, sessions
from .test_flowgate import _session, _plan, _cfg
from .test_project_status_data_scope import progress

SOURCE = Path(__file__).resolve().parents[1]
PACKAGES = {"HYDAT_Observations", "Agrometeo_Quebec_Observations"}


def test_data_kis_are_available_beside_external_models_and_not_shadowed(tmp_path):
    models, user = tmp_path / "models", tmp_path / "user"
    (models / "M").mkdir(parents=True)
    (models / "M/SKILL.md").write_text("# model")
    (user / "HYDAT_Observations").mkdir(parents=True)
    (user / "HYDAT_Observations/SKILL.md").write_text("shadow")
    source = catalog.bundled_data_dir()
    cat = catalog.Catalog(models, user_dir=user, data_dir=source)
    assert set(cat.packages) == PACKAGES | {"M"}
    assert set(catalog.Catalog(models).packages) == {"M"}
    for name in PACKAGES:
        ki = cat.get(name)
        assert ki.root.parent == source
        assert ki.meta["package_kind"] == "task_workflow"
        assert ki.meta["package_role"] == "data_reader"
        assert ki.meta["impl_id"].startswith("geoforge-")
        assert str(ki.skill) in sessions.catalogue_block(cat)
    # A model snapshot switch and refresh must retain the app's data KIs.
    cat.refresh()
    assert cat.get("HYDAT_Observations").root.parent == source


@pytest.mark.parametrize("spec_name", ["GeoForgeDesktopWindows.spec", "GeoForgeDesktop.spec", "KISS.spec"])
def test_actual_frozen_data_layout_preserves_reader_packages(spec_name, tmp_path, monkeypatch):
    spec = SOURCE / spec_name
    tree = ast.parse(spec.read_text(encoding="utf-8"))
    assignments = {target.id: n.value for n in tree.body if isinstance(n, ast.Assign)
                   for target in n.targets if isinstance(target, ast.Name)}
    datas = next(k.value for k in assignments["a"].keywords if k.arg == "datas")
    if isinstance(datas, ast.Name):
        datas = assignments[datas.id]
    entries = [n for n in datas.elts if isinstance(n, ast.Tuple)
               and any(isinstance(v, ast.Constant) and v.value == "data_kis" for v in ast.walk(n))]
    assert len(entries) == 1
    source, dest = eval(compile(ast.Expression(entries[0]), str(spec), "eval"),
                        {"__builtins__": {}, "str": str, "SOURCE": SOURCE})
    bundle = tmp_path / "bundle"
    shutil.copytree(source, bundle / dest)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    root = catalog.bundled_data_dir()
    assert root == bundle / "data_kis"
    for name in PACKAGES:
        for relative in ("SKILL.md", "knowledge_infrastructure.yaml", "docs/format_spec.yaml",
                         "tools/read_observations.py"):
            assert (root / name / relative).read_bytes() == (Path(source) / name / relative).read_bytes()


def test_shipped_reader_runs_through_approved_tool_proxy_without_model_claim(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    root = tmp_path / "ki"
    shutil.copytree(SOURCE / "data_kis/Agrometeo_Quebec_Observations", root)
    ki = catalog.KI("Agrometeo_Quebec_Observations", root)
    ki_guard.enroll(root)
    project, fs = _session(tmp_path, ki, [("task_received", None),
                         ("kis_resolved", {"selected_kis": [ki.name]})])
    raw = project / "inputs/soilTemp10cm_2022.csv"
    raw.parent.mkdir()
    with raw.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Station", "date", "latitude", "longitude", "soil temp(°C)"])
        for hour in range(24):
            writer.writerow(["Fixture", f"2022-01-01 {hour:02}:00:00", "45.25", "-71.8", "1.25"])
    before = raw.read_bytes()
    plan, inventory = _plan(ki)
    plan["steps"][0].update(id="read", kind="prepare", tool=str(root / "tools/read_observations.py"))
    inventory["items"][0].update(chosen_source="existing_local", acceptable_sources=["existing_local"],
                                 local_paths=[str(raw)])
    assert fs.write_plan(plan, inventory) == []
    fs.flow.approval.approve(project, by="user")
    fs.reload_artifacts()
    fs.move("plan_written", {"plan_valid": True})
    fs.move("approved", {"approval": "OK"})
    fs.move("execution_started", {"setup_verified": True})
    response = api.execute_tool("run_ki_tool", {"tool_path": "tools/read_observations.py",
                        "plan_step_id": "read", "arguments": ["--source", str(raw), "--station", "Fixture",
                        "--start", "2022-01-01", "--end", "2022-01-01", "--output-dir", "outputs/read"]},
                        ki, _cfg(project), project_mode=True, flow=fs)
    answer = json.loads(next(line.removeprefix("[RECEIPT] ") for line in response.splitlines()
                             if line.startswith("[RECEIPT] ")))
    assert answer["execution_status"] == "succeeded", answer
    evidence = fs.evidence()
    assert evidence["validation"] == "passed", evidence
    assert evidence["runs"][0]["execution_scope"] == "data_ki"
    assert evidence["runs"][0]["model_executed"] is False
    assert raw.read_bytes() == before
    audit = json.loads((project / "outputs/read/audit.json").read_text(encoding="utf-8"))
    assert audit["rows"] == 24 and audit["status"] == "extracted"
    status = progress(runs=evidence["runs"])
    assert status["data_preparation_complete"] and not status["science_complete"]
