"""Investigation boundaries; maintenance gate/recipe unit tests live separately."""
import json
from pathlib import Path

import pytest

from kiss_cli import flowgate, ki_guard, ki_investigation as inv, ki_verification as gate
from .test_ki_investigation import case, new, reviewer


@pytest.fixture
def maintenance(monkeypatch):
    from kiss_cli import ki_maintenance, ki_maintenance_recipes
    calls = []
    def capture(root, *, name):
        ki_guard.require_intact(root)
        calls.append(("capture", name))
        return {"fixture": True, "base_digest": gate.content_digest(root), "name": name,
                "original_root": str(root)}
    def recipe(candidate, *, source, recipe, name):
        assert gate.content_digest(candidate) == gate.content_digest(source)
        calls.append(("recipe", recipe))
        (candidate / "SKILL.md").write_text("Fixture recipe repair\n", encoding="utf-8")
        return {"recipe": recipe, "changed_files": ["SKILL.md"]}
    def require(root, report, *, source=None):
        if (not report.get("fixture_maintenance") or report.get("source") != source or
                report.get("candidate_digest") != gate.content_digest(root)):
            raise ValueError("Fixture maintenance evidence is stale or not maintenance")
        return report
    def verify(root, *, source, name):
        calls.append(("verify", name))
        return {"ok": True, "fixture_maintenance": True, "source": source, "gate_policy": ki_maintenance.POLICY,
                "candidate_digest": gate.content_digest(root), "base_digest": source["base_digest"],
                "changes": [{"path": "SKILL.md"}]}
    monkeypatch.setattr(ki_maintenance, "capture_source", capture)
    monkeypatch.setattr(ki_maintenance, "verify_candidate", verify)
    monkeypatch.setattr(ki_maintenance, "require_current", require)
    monkeypatch.setattr(ki_maintenance_recipes, "apply_recipe", recipe)
    return calls


def reviewed(case):
    job = new(case)
    inv.run_reviews(case[0], job["id"], reviewer)
    return job


def draft(case, recipe="tool_inventory"):
    job = reviewed(case)
    return inv.create_draft(case[0], job["id"], "M", repair_mode="maintenance", maintenance_recipe=recipe)


@pytest.mark.parametrize("recipe", ["tool_inventory", "preflight_reporting", "package_contract"])
def test_maintenance_recipe_follows_three_reviews_and_keeps_live_bytes(case, maintenance, recipe):
    original = gate.content_digest(case[1])
    job = draft(case, recipe)
    assert job["draft"]["repair_mode"] == "maintenance"
    assert job["draft"]["authoring_scope"] == "local"
    assert job["draft"]["base_digest"] == original
    assert gate.content_digest(case[1]) == original
    assert maintenance == [("capture", "M"), ("recipe", recipe)]
    assert (Path(job["draft"]["path"]).parent / "evidence/maintenance-scope.json").is_file()


def test_maintenance_cannot_skip_three_reviews(case, maintenance):
    job = new(case)
    with pytest.raises(ValueError, match="three reviews"):
        inv.create_draft(case[0], job["id"], "M", repair_mode="maintenance", maintenance_recipe="tool_inventory")
    assert maintenance == []


@pytest.mark.parametrize("mode,recipe", [("published", "tool_inventory"), ("maintenance", "arbitrary"),
                                         ("authoring", "tool_inventory")])
def test_unknown_profile_or_recipe_cannot_enter_maintenance(case, maintenance, mode, recipe):
    job = reviewed(case)
    with pytest.raises(ValueError):
        inv.create_draft(case[0], job["id"], "M", repair_mode=mode, maintenance_recipe=recipe)
    assert not maintenance


def test_maintenance_dispatches_separate_gate_and_rejects_later_drift(case, maintenance, monkeypatch):
    job = draft(case)
    monkeypatch.setattr(gate, "verify_candidate", lambda *a, **k: pytest.fail("Must not call the authoring gate"))
    verified = inv.verify_draft(case[0], job["id"])
    assert verified["can_apply"] and verified["verification"]["repair_mode"] == "maintenance"
    assert verified["verification"]["native_regression"]["verified"] is False
    (Path(job["draft"]["path"]) / "SKILL.md").write_text("Changed after gate\n")
    assert not inv.get(case[0], job["id"])["can_apply"]
    with pytest.raises(ValueError):
        inv.apply(case[0], job["id"], verified["verification"]["id"])


def test_unsigned_mode_change_cannot_authorize_maintenance(case, maintenance):
    job = draft(case)
    path = inv._root(case[0], job["id"]) / "job.json"
    unsigned = json.loads(path.read_text(encoding="utf-8"))
    unsigned["draft"]["maintenance_source"] = {"scope": "official_published_package", "ok": True}
    path.write_text(json.dumps(unsigned), encoding="utf-8")
    with pytest.raises(ValueError, match="authentic|signature|trusted"):
        inv.verify_draft(case[0], job["id"])


def test_publication_report_cannot_substitute_maintenance_verification(case, maintenance):
    job = draft(case)
    saved = inv._load(case[0], job["id"])
    saved.update(status="verified", verification={"ok": True, "id": "fake", "report": {
        "ok": True, "scope": "official_published_package", "candidate_digest": gate.content_digest(Path(job["draft"]["path"]))}})
    inv._save(case[0], saved)
    assert not inv.get(case[0], job["id"])["can_apply"]


def test_maintenance_adoption_preserves_normal_replan_and_preflight_requirements(case, maintenance, monkeypatch):
    job = draft(case)
    verified = inv.verify_draft(case[0], job["id"])
    monkeypatch.setattr(ki_guard, "activate", lambda *a, **k: pytest.fail("Must use separate maintenance adoption"))
    applied = inv.apply(case[0], job["id"], verified["verification"]["id"])
    assert applied["status"] == "applied"
    assert (case[1] / "SKILL.md").read_text() == "Fixture recipe repair\n"
    assert ki_guard.require_intact(case[1])["origin"] == "verified_maintenance_candidate"
    assert inv.pending_preflight(case[0])["pending"]
    assert flowgate.load().approval.check(case[0]) != "OK"
    assert applied["apply"]["requires_preflight"] and applied["apply"]["requires_plan_review"]
    assert not applied["apply"].get("reusable", False)


def test_audit_edit_outside_selected_recipe_is_blocked_before_gate(case, maintenance):
    job = draft(case)
    (Path(job["draft"]["path"]) / "tools/reader.py").write_text("def read(): return 9\n")
    with pytest.raises(ValueError, match="selected recipe"):
        inv.verify_draft(case[0], job["id"])
    assert not any(action == "verify" for action, _ in maintenance)

