"""Actual signed adoption/input checks; only KDT's engine/recipe are fixture doubles."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import pytest

from kiss_cli import (ki_adaptations as adapt, ki_copy, ki_data_lineage, ki_guard,
                     ki_investigation as investigation, ki_maintenance as maintenance,
                     ki_maintenance_recipes as recipes, paths, project_data_tools, project_paths)
from kiss_cli.manifest import Manifest
from ki_tools_common.flow import project_inputs
from .test_ki_adaptations import prepare_helpers
from .test_ki_maintenance import metadata
from .test_ki_verification_boundaries import isolated_engine, write_package
from .test_project_bundled_data_inputs import SOURCE, review, request
from .test_project_data_tools import case as worker_case, approve, run


@pytest.fixture
def adopted(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "adaptation"))
    monkeypatch.setenv("GEOFORGE_KI_INVESTIGATION_HOME", str(tmp_path / "investigation"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    with isolated_engine(tmp_path):
        c = list(worker_case(tmp_path, SOURCE))
        library = tmp_path / "library"
        source = library / "models/M"
        write_package(source, "M")
        metadata(source, "M")
        data = source / "outputs/example/weather.csv"
        data.parent.mkdir(parents=True)
        data.write_text("date,value\n2020-01-01,2\n2020-01-02,3\n")
        helpers = library / "ki_tools_common"
        helpers.mkdir()
        (helpers / "helper.py").write_text("VALUE=1\n")
        prepared = tmp_path / "prepared"
        prepare_helpers(library, prepared)
        cfg = project_paths.model_config(c[1], "M", paths.KissConfig.default(tmp_path / "installed"))
        cfg.python, cfg.relocation = sys.executable, "none"
        cfg.roles["ki_tools_common"] = prepared
        live = c[1] / "models/M/ki"
        adapt.materialise(source, live, cfg, model="M", library_root=library, manifest=Manifest(model="M"))
        (live.parent / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
        c[0] = SimpleNamespace(name="M", root=live)
        c[2].ki_roots["M"] = live
        c[3]["steps"][0]["project_data_tool"]["arguments"] = []
        c[4]["items"][0]["local_paths"] = ["models/M/ki/outputs/example/weather.csv"]
        origin = adapt.projection(live, cfg)
        monkeypatch.setattr(recipes, "expected_changes", lambda base, name: {
            "knowledge_infrastructure.yaml": (base / "knowledge_infrastructure.yaml").read_bytes().replace(
                b"total_tools: 2", b"total_tools: 1")})
        frozen = maintenance.capture_source(live, "M")
        candidate = tmp_path / "candidate"
        ki_copy.copytree(Path(frozen["base_root"]), candidate)
        (candidate / "knowledge_infrastructure.yaml").write_bytes(recipes.expected_changes(candidate, "M")["knowledge_infrastructure.yaml"])
        report = maintenance.verify_candidate(candidate, source=frozen, name="M")
        assert report["ok"]
        baseline = ki_guard.activate_maintenance(live, candidate, report, source=frozen, quiescent=True)
        ident, verification_id = uuid.uuid4().hex[:16], uuid.uuid4().hex[:16]
        doc = {"id": ident, "policy": investigation.POLICY, "project": str(c[1]), "status": "applied",
               "ki_roots": {"M": str(live)}, "baseline_digests": {"M": frozen["base_digest"]},
               "draft": {"repair_mode": "maintenance", "authoring_scope": "local", "project_local": True,
                         "ki_name": "M", "active_root": str(live), "path": str(candidate),
                         "maintenance_source": frozen, "maintenance_projection_digest": baseline["digest"]},
               "verification": {"id": verification_id, "ok": True, "report": report},
               "apply": {"status": "complete", "ki_name": "M", "verification_id": verification_id,
                         "old_digest": frozen["base_digest"], "new_digest": baseline["digest"],
                         "adopted_digest": baseline["digest"]}}
        investigation._save(c[1], doc)
        pending = {"project": str(c[1]), "kis": {"M": {"job_id": ident, "verification_id": verification_id,
                                                        "digest": baseline["digest"], "passed": False}}}
        investigation._signed(investigation._pending_path(c[1]), pending)
        yield SimpleNamespace(c=c, cfg=cfg, live=live, origin=origin, doc=doc, pending=pending,
                              report=report, frozen=frozen, candidate=candidate, prepared=prepared)


def test_completed_maintenance_keeps_unchanged_bundled_data_usable_without_rewriting_authority(adopted):
    a = adopted
    projection_bytes = adapt._location(a.live).read_bytes()
    baseline = ki_guard.require_intact(a.live)
    with pytest.raises(ValueError, match="stale"):
        adapt.projection(a.live, a.cfg)
    assert review(a.c) == []
    grant = request(a.c)
    assert grant["read_roots"] == [str(a.live / "outputs/example/weather.csv")]
    assert grant["list_roots"] == [] and grant["non_executable_roots"] == [str(a.live)]
    approve(a.c)
    assert run(a.c).startswith("exit_code=0")
    assert json.loads((a.c[1] / "outputs/inspection.json").read_text())["count"] == 2
    assert adapt._location(a.live).read_bytes() == projection_bytes
    assert ki_guard.require_intact(a.live) == baseline
    assert investigation.pending_preflight(a.c[1])["pending"] is True, "data provenance grants no readiness"


def test_maintenance_changed_metadata_cannot_use_unchanged_data_allowance(adopted):
    a = adopted
    a.c[4]["items"][0]["local_paths"] = ["models/M/ki/knowledge_infrastructure.yaml"]
    assert any("changed during maintenance" in error for error in review(a.c))
    with pytest.raises(ValueError, match="changed during maintenance"):
        request(a.c)


@pytest.mark.parametrize("damage", ["journal_signature", "pending_signature", "incomplete", "wrong_root",
    "wrong_old_digest", "wrong_verification", "missing_candidate", "changed_candidate", "changed_frozen",
    "changed_live", "changed_config", "changed_helpers", "changed_source", "missing_projection",
    "non_maintenance", "malformed"])
def test_incomplete_or_stale_maintenance_lineage_fails_review_and_runtime(adopted, damage):
    a = adopted
    if damage == "journal_signature":
        investigation._root(a.c[1], a.doc["id"]).joinpath("job.json").write_text("{}")
    elif damage == "pending_signature":
        investigation._pending_path(a.c[1]).write_text("{}")
    elif damage in {"incomplete", "wrong_root", "wrong_old_digest", "wrong_verification", "non_maintenance", "malformed"}:
        doc = deepcopy(a.doc)
        if damage == "incomplete": doc["apply"]["status"] = "adopted"
        elif damage == "wrong_root": doc["draft"]["active_root"] += "-other"
        elif damage == "wrong_old_digest": doc["apply"]["old_digest"] = "0" * 64
        elif damage == "wrong_verification": doc["apply"]["verification_id"] = "other"
        elif damage == "non_maintenance": doc["draft"]["repair_mode"] = "authoring"
        else: doc["draft"] = ["invalid"]
        investigation._save(a.c[1], doc)
    elif damage == "missing_candidate":
        (a.candidate / "SKILL.md").unlink()
    elif damage == "changed_candidate":
        (a.candidate / "SKILL.md").write_text("unreviewed")
    elif damage == "changed_frozen":
        (Path(a.frozen["base_root"]) / "SKILL.md").write_text("unreviewed")
    elif damage == "changed_live":
        (a.live / "outputs/example/weather.csv").write_text("unreviewed")
    elif damage == "changed_config":
        cfg = project_paths.load_model_config(a.c[1], "M")
        cfg.roles["outputs"] = a.c[1] / "other-output"
        (a.live.parent / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    elif damage == "changed_helpers":
        (a.prepared / "helper.py").write_text("VALUE=99\n")
    elif damage == "changed_source":
        (Path(a.origin["upstream_root"]) / "SKILL.md").write_text("unreviewed source")
    else:
        adapt._location(a.live).unlink()
    assert review(a.c)
    with pytest.raises((ValueError, OSError)):
        request(a.c)


def test_two_completed_maintenance_adoptions_trace_to_one_original_projection(adopted, monkeypatch):
    a = adopted
    def changes(base, name):
        raw = (base / "knowledge_infrastructure.yaml").read_bytes()
        return {"knowledge_infrastructure.yaml": raw.replace(b"total_tools: 2", b"total_tools: 1")
                if b"total_tools: 2" in raw else raw.replace(b"total_tools: 1", b"total_tools: 3")}
    monkeypatch.setattr(recipes, "expected_changes", changes)
    source = maintenance.capture_source(a.live, "M")
    candidate = a.candidate.with_name("candidate-second")
    ki_copy.copytree(Path(source["base_root"]), candidate)
    (candidate / "knowledge_infrastructure.yaml").write_bytes(changes(candidate, "M")["knowledge_infrastructure.yaml"])
    report = maintenance.verify_candidate(candidate, source=source, name="M")
    assert report["ok"]
    current = ki_guard.activate_maintenance(a.live, candidate, report, source=source, quiescent=True)
    doc = deepcopy(a.doc)
    doc["id"] = uuid.uuid4().hex[:16]
    doc["baseline_digests"]["M"] = source["base_digest"]
    doc["draft"].update(path=str(candidate), maintenance_source=source, maintenance_projection_digest=current["digest"])
    doc["verification"] = {"id": uuid.uuid4().hex[:16], "ok": True, "report": report}
    doc["apply"].update(verification_id=doc["verification"]["id"], old_digest=source["base_digest"],
                        new_digest=current["digest"], adopted_digest=current["digest"])
    investigation._save(a.c[1], doc)
    pending = deepcopy(a.pending)
    pending["kis"]["M"].update(job_id=doc["id"], verification_id=doc["verification"]["id"], digest=current["digest"])
    investigation._signed(investigation._pending_path(a.c[1]), pending)
    proof = project_data_tools.require_ki_data_source(a.c[1], "M", a.live)
    assert proof["adoptions"] == [doc["id"], a.doc["id"]]
    assert review(a.c) == []
    assert request(a.c)["list_roots"] == []
    # Removing the authentic predecessor cannot silently treat the new baseline
    # as a fresh projection.
    investigation._root(a.c[1], a.doc["id"]).joinpath("job.json").unlink()
    with pytest.raises(ValueError, match="incomplete or ambiguous"):
        request(a.c)


def test_original_fresh_path_proof_can_be_checked_on_retained_bytes_without_retargeting(tmp_path, monkeypatch):
    from .test_fresh_path_projection import case
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "adaptation"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    source, cfg, live = case(tmp_path)
    adapt.materialise(source, live, cfg, model="WOFOST")
    origin = adapt.projection(live, cfg)
    retained = tmp_path / "frozen"
    ki_copy.copytree(live, retained)
    before = deepcopy(origin)
    ki_data_lineage._retained_projection(origin, live, retained, cfg)
    assert origin == before
    Path(cfg.python).write_bytes(b"changed executable identity")
    with pytest.raises(ValueError, match="runtime/helper"):
        ki_data_lineage._retained_projection(origin, live, retained, cfg)
