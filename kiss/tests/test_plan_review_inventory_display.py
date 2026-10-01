"""Review distinguishes existing inputs from paths a future run will create."""
import pytest

from kiss_cli import plan_review
from ki_tools_common.flow import declared


def test_future_output_paths_are_generated_and_real_uploads_are_on_disk(tmp_path):
    upload_dir = tmp_path / "inputs/uploads"
    upload_dir.mkdir(parents=True)
    inputs = []
    for name in ("control", "forcing"):
        path = upload_dir / (name + ".txt")
        path.write_text("authentic input\n", encoding="utf-8")
        inputs.append({"id": name, "status": "ready",
                       "local_paths": [path.relative_to(tmp_path).as_posix()]})
    outputs = [{"id": f"output_{i}", "status": "missing",
                "local_paths": [f"outputs/model/result_{i}.txt"]} for i in range(16)]
    plan = {"steps": [{"id": "run", "outputs": [item["id"] for item in outputs]}]}
    inventory = {"items": inputs + outputs}
    groups = plan_review.input_groups(plan, inventory, tmp_path)
    assert groups["total"] == 18
    assert not groups["fetch"] and not groups["you"]
    assert [row["id"] for row in groups["run"] if row["how"] == "on_disk"] == ["control", "forcing"]
    assert sum(row["how"] == "generated" for row in groups["run"]) == 16
    summary = plan_review._data_summary(plan, inventory, tmp_path)
    assert "2 already on disk, 16 made by a step" in summary
    assert "18 already on disk" not in summary
    assert not (tmp_path / "outputs").exists()


@pytest.mark.parametrize("status, exists, expected", [
    ("missing", False, "prepared"),
    ("ready", False, "prepared"),
    ("missing", True, "prepared"),
    ("ready", True, "on_disk"),
])
def test_on_disk_needs_ready_input_and_existing_path(tmp_path, status, exists, expected):
    path = tmp_path / "input.txt"
    if exists:
        path.write_text("input\n", encoding="utf-8")
    item = {"id": "input", "status": status, "local_paths": ["input.txt"]}
    assert declared.classify(item, (), set(), project=tmp_path)["how"] == expected


def test_generated_item_stays_generated_when_previous_output_exists(tmp_path):
    (tmp_path / "result.txt").write_text("old output\n", encoding="utf-8")
    item = {"id": "result", "status": "ready", "local_paths": ["result.txt"]}
    assert declared.classify(item, (), {"result"}, project=tmp_path)["how"] == "generated"


def test_path_without_project_context_does_not_prove_readiness():
    item = {"id": "future", "status": "missing", "local_paths": ["outputs/future.txt"]}
    assert declared.classify(item, (), set())["how"] == "prepared"
