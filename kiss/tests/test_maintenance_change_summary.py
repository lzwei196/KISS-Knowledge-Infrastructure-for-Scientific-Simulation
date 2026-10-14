"""Maintenance display uses a current gate's exact inventory, including aliases."""
from copy import deepcopy
from pathlib import Path

import pytest

from kiss_cli import ki_copy, ki_guard, ki_investigation as inv, ki_maintenance
from kiss_cli import ki_verification
from .test_ki_maintenance import case


@pytest.fixture
def linked_maintenance(case):
    base = case.root / "linked-base"
    ki_copy.copytree(case.base, base)
    (base / "run_alias.py").symlink_to(Path("tools/run.py"))
    (base / "tools_alias").symlink_to(Path("tools"), target_is_directory=True)
    ki_guard.enroll(base)
    source = ki_maintenance.capture_source(base, "Demo")
    candidate = case.root / "linked-candidate"
    ki_copy.copytree(Path(source["base_root"]), candidate)
    for relative, value in case.recipes.expected_changes(base, "Demo").items():
        (candidate / relative).write_bytes(value)
    report = ki_maintenance.verify_candidate(candidate, source=source, name="Demo")
    return {"draft": {"maintenance_source": source}}, candidate, report


def test_current_maintenance_summary_covers_unchanged_aliases(linked_maintenance):
    doc, candidate, report = linked_maintenance
    changes = inv._maintenance_candidate_changes(doc, candidate, report)
    assert changes["complete"] and not changes["uncompared_baseline_paths"]
    assert not changes["uncompared_candidate_paths"]
    assert changes["comparison_basis"] == "authenticated_maintenance_inventory"
    assert changes["candidate_digest"] == ki_verification.content_digest(candidate)
    assert changes["baseline_digest"] == report["base_digest"]
    assert changes["modified"] == ["knowledge_infrastructure.yaml"]
    assert changes["counts"] == {"added": 0, "removed": 0, "modified": 1}
    assert changes["added"] == changes["removed"] == []
    assert (candidate / "run_alias.py").is_symlink()
    assert (candidate / "tools_alias").is_symlink()


@pytest.mark.parametrize("damage", ["alias", "added", "removed", "report", "source"])
def test_complete_display_requires_current_authenticated_full_inventory(linked_maintenance, damage):
    doc, candidate, report = linked_maintenance
    if damage == "alias":
        (candidate / "run_alias.py").unlink()
        (candidate / "run_alias.py").symlink_to(Path("SKILL.md"))
    elif damage == "added":
        (candidate / "unreviewed.txt").write_text("unreviewed")
    elif damage == "removed":
        (candidate / "SKILL.md").unlink()
    elif damage == "report":
        report = deepcopy(report)
        report["changes"] = []
    else:
        doc = deepcopy(doc)
        doc["draft"]["maintenance_source"]["base_digest"] = "f" * 64
    with pytest.raises(ValueError):
        inv._maintenance_candidate_changes(doc, candidate, report)
