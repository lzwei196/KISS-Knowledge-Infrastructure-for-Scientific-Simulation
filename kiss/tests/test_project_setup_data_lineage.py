"""Bundled-data consumers of real signed Setup-to-project derivation fixtures.

The imported fixture uses explicit reviewer/KDT doubles and inert runtimes.
These tests do not execute models or grant scientific/preflight acceptance.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import uuid

import pytest

from kiss_cli import (ki_adaptations as adapt, ki_data_lineage, ki_guard,
                     ki_copy, ki_investigation as investigation,
                     ki_maintenance as maintenance, ki_maintenance_recipes as recipes,
                     project_data_tools, project_setup_repair as derivation,
                     setup_ki_repair)
from ki_tools_common.flow import project_inputs
from .test_project_setup_repair import case as derived_case, make
from .test_project_bundled_data_inputs import bundled


def proof(case):
    return project_data_tools.require_ki_data_source(
        case["cfg"].root, case["model"], case["live"])


def grant(case, relative):
    return project_inputs.grant(case["cfg"].root, case["model"],
        case["live"] / relative, selected_ki_root=case["live"],
        authority=project_data_tools.require_ki_data_source)


def test_current_derived_project_keeps_only_unchanged_bundled_data(derived_case):
    c = derived_case
    _, record = make(c)
    original = adapt._location(c["live"]).read_bytes()
    baseline = ki_guard.require_intact(c["live"])
    with pytest.raises(adapt.AdaptationError, match="stale"):
        adapt.projection(c["live"], c["cfg"])
    data = proof(c)
    assert data["kind"] == "maintenance_data_lineage"
    assert data["original_projection"] == record["ordinary_projection"]
    assert data["projected_digest"] == record["projected_digest"]
    assert data["project_derivation"]["setup_adoption_digest"] == record["binding"]["setup_adoption_digest"]
    for name, item in record["protected_inventory"].items():
        if name.startswith("test_cases/") and item["kind"] == "file":
            assert data["unchanged_ki_data_sha256"][name] == hashlib.sha256((c["live"] / name).read_bytes()).hexdigest()
    files, directory, root = grant(c, "docs/papers.json")
    assert files == [c["live"] / "docs/papers.json"]
    assert directory is None and root == c["live"]
    with pytest.raises(ValueError, match="changed during maintenance"):
        grant(c, "knowledge_infrastructure.yaml")
    assert adapt._location(c["live"]).read_bytes() == original
    assert ki_guard.require_intact(c["live"]) == baseline
    assert record["preflight_passed"] is False and record["native_verified"] is False


def test_pending_derivation_never_falls_back_to_valid_ordinary_bytes(derived_case, monkeypatch):
    c = derived_case
    c["engine"].ok = False
    with pytest.raises((ValueError, RuntimeError)):
        make(c)
    assert adapt.projection(c["live"], c["cfg"]), "ordinary projection remains intact after rejected KDT"
    monkeypatch.setattr(adapt, "projection", lambda *a, **k: pytest.fail("pending derivation fell back"))
    with pytest.raises(ValueError, match="incomplete"):
        proof(c)


@pytest.mark.parametrize("damage", ["signature", "record_missing", "setup_missing", "source",
    "config", "helpers", "input", "protected_inventory"])
def test_stale_or_incomplete_derivation_cannot_grant_bundled_reads(derived_case, damage):
    c = derived_case
    _, record = make(c)
    if damage == "signature":
        derivation._location(c["live"]).write_text("{}", encoding="utf-8")
    elif damage == "record_missing":
        derivation._location(c["live"]).unlink()
    elif damage == "setup_missing":
        setup_ki_repair._pointer(c["shared"].root).unlink()
    elif damage == "source":
        (c["source"] / "SKILL.md").write_text("changed source", encoding="utf-8")
    elif damage == "config":
        with (c["live"].parent / "kiss.toml").open("a", encoding="utf-8") as stream:
            stream.write("\n# no longer the exact reviewed configuration\n")
    elif damage == "helpers":
        (c["cfg"].roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("changed", encoding="utf-8")
    elif damage == "input":
        (c["live"] / "docs/papers.json").write_text("changed", encoding="utf-8")
    else:
        # Even a new outer host envelope cannot replace the independently
        # signed protected inventory captured by the maintenance verifier.
        altered = deepcopy(record)
        altered.pop("protected_inventory")
        altered["project_source"]["protected_inventory"]["docs/papers.json"]["sha256"] = "0" * 64
        derivation._write(c["live"], altered)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        grant(c, "docs/papers.json")


def test_derived_proof_cannot_be_requested_for_another_project(derived_case):
    c = derived_case
    make(c)
    with pytest.raises(ValueError, match="another project binding"):
        ki_data_lineage.require_projection(c["cfg"].root.parent / "other", c["model"], c["live"], c["cfg"])


def test_missing_derivation_cannot_downgrade_optional_gui_or_preflight_gate(derived_case, monkeypatch):
    c = derived_case
    make(c)
    # Simulate absence of the entire optional authority store, not only a lost
    # record file. The existing signed KI guard must still require a chain.
    monkeypatch.setattr(derivation, "require_baseline", lambda *a, **k: None)
    with pytest.raises(ValueError, match="matching host project record"):
        ki_data_lineage.require_setup_projection(c["cfg"].root, c["model"], c["live"], c["cfg"])


def test_absent_derivation_preserves_ordinary_projection_route(bundled):
    model, project = bundled[:2]
    result = project_data_tools.require_ki_data_source(project, "M", model.root)
    assert result["kind"] == "projection"
    assert "project_derivation" not in result


def later_maintenance(case, monkeypatch):
    """Real signed KDT/adoption/journal fixture; only the generated edit is doubled."""
    live, model, project = case["live"], case["model"], case["cfg"].root
    monkeypatch.setattr(recipes, "expected_changes", lambda base, name: {
        "knowledge_infrastructure.yaml": (base / "knowledge_infrastructure.yaml").read_bytes().replace(
            b"total_tools: 2", b"total_tools: 1")})
    source = maintenance.capture_source(live, model)
    candidate = project / "later-candidate"
    ki_copy.copytree(Path(source["base_root"]), candidate)
    (candidate / "knowledge_infrastructure.yaml").write_bytes(
        recipes.expected_changes(candidate, model)["knowledge_infrastructure.yaml"])
    report = maintenance.verify_candidate(candidate, source=source, name=model)
    assert report["ok"]
    adopted = ki_guard.activate_maintenance(live, candidate, report, source=source, quiescent=True)
    ident, verification_id = uuid.uuid4().hex[:16], uuid.uuid4().hex[:16]
    doc = {"id": ident, "policy": investigation.POLICY, "project": str(project), "status": "applied",
        "ki_roots": {model: str(live)}, "baseline_digests": {model: source["base_digest"]},
        "draft": {"repair_mode": "maintenance", "authoring_scope": "local", "project_local": True,
            "ki_name": model, "active_root": str(live), "path": str(candidate),
            "maintenance_source": source, "maintenance_projection_digest": adopted["digest"]},
        "verification": {"id": verification_id, "ok": True, "report": report},
        "apply": {"status": "complete", "ki_name": model, "verification_id": verification_id,
            "old_digest": source["base_digest"], "new_digest": adopted["digest"],
            "adopted_digest": adopted["digest"]}}
    investigation._save(project, doc)
    investigation._signed(investigation._pending_path(project), {"project": str(project),
        "kis": {model: {"job_id": ident, "verification_id": verification_id,
                       "digest": adopted["digest"], "passed": False}}})
    return doc, source


def test_later_authenticated_maintenance_composes_to_setup_derived_baseline(derived_case, monkeypatch):
    c = derived_case
    _, original = make(c)
    original_bytes = adapt._location(c["live"]).read_bytes()
    derived_bytes = derivation._location(c["live"]).read_bytes()
    doc, _source = later_maintenance(c, monkeypatch)
    with pytest.raises(ValueError):
        derivation.require_record(c["live"], c["cfg"], model=c["model"])
    data = proof(c)
    assert data["adoptions"] == [doc["id"]]
    assert data["projected_digest"] == doc["apply"]["adopted_digest"]
    assert data["original_projection"] == original["ordinary_projection"]
    assert grant(c, "docs/papers.json")[0] == [c["live"] / "docs/papers.json"]
    with pytest.raises(ValueError, match="changed during maintenance"):
        grant(c, "knowledge_infrastructure.yaml")
    assert adapt._location(c["live"]).read_bytes() == original_bytes
    assert derivation._location(c["live"]).read_bytes() == derived_bytes
    assert investigation.pending_preflight(c["cfg"].root)["pending"] is True


@pytest.mark.parametrize("damage", ["journal", "pending", "frozen", "wrong_parent"])
def test_later_maintenance_needs_exact_authenticated_chain(derived_case, monkeypatch, damage):
    c = derived_case
    make(c)
    doc, source = later_maintenance(c, monkeypatch)
    if damage == "journal":
        investigation._root(c["cfg"].root, doc["id"]).joinpath("job.json").write_text("{}")
    elif damage == "pending":
        investigation._pending_path(c["cfg"].root).write_text("{}")
    elif damage == "frozen":
        (Path(source["base_root"]) / "SKILL.md").write_text("changed retained parent")
    else:
        doc["apply"]["old_digest"] = "0" * 64
        investigation._save(c["cfg"].root, doc)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        grant(c, "docs/papers.json")
