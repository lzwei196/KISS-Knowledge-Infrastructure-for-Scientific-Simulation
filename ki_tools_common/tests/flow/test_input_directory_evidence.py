"""Directory declarations classify inputs without changing acquisition authority."""
from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from ki_tools_common.flow import receipts


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "host-keys"))
    root = tmp_path / "project"
    root.mkdir()
    return root


def _write(project: Path, relative: str, text="date,value\n2022-01-01,1\n") -> Path:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _evidence(project, local_paths, plan=None):
    return receipts.evidence(project, plan or {}, {}, inventory={"items": [
        {"id": "raw", "status": "ready", "local_paths": local_paths},
    ]})


@pytest.mark.parametrize("absolute", [False, True])
def test_declared_directory_covers_nested_inputs_only(project, absolute):
    _write(project, "inputs/observations/station/2021/data.csv")
    _write(project, "inputs/observations/station/2022/data.csv")
    _write(project, "inputs/observations/station-extra/data.csv")
    _write(project, "inputs/other/data.csv")
    _write(project, "outputs/result.csv")
    directory = "inputs/observations/station"
    local_paths = [str(project / directory) if absolute else directory]
    evidence = _evidence(project, local_paths)
    assert set(evidence["unreceipted_artifacts"]) == {
        "inputs/observations/station-extra/data.csv", "inputs/other/data.csv", "outputs/result.csv",
    }
    assert evidence["downloads_bound"] == 0


def test_results_and_undeclared_files_remain_visible(project):
    for relative in ("inputs/direct.csv", "inputs/extra.csv", "outputs/results/result.csv",
                     "artifacts/plots/report.json", "calibration/framework.json"):
        _write(project, relative)
    evidence = _evidence(project, ["inputs/direct.csv", "outputs/results", "artifacts/plots"])
    assert set(evidence["unreceipted_artifacts"]) == {
        "inputs/extra.csv", "outputs/results/result.csv", "artifacts/plots/report.json",
    }


def test_inventory_cannot_declare_all_inputs_with_bare_root(project):
    _write(project, "inputs/extra.csv")
    assert _evidence(project, ["inputs"])["unreceipted_artifacts"] == ["inputs/extra.csv"]


def test_linked_file_outside_project_is_not_a_declared_child(project):
    directory = project / "inputs" / "station"
    directory.mkdir(parents=True)
    outside = _write(project.parent, "outside.csv")
    link = directory / "outside.csv"
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"this host cannot create a symbolic link: {exc}")
    assert _evidence(project, ["inputs/station"])["unreceipted_artifacts"] == [
        "inputs/station/outside.csv",
    ]


def test_output_link_to_input_does_not_inherit_directory_exemption(project):
    raw = _write(project, "inputs/station/raw.csv")
    output = project / "outputs" / "copied.csv"
    output.parent.mkdir()
    try:
        output.symlink_to(raw)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"this host cannot create a symbolic link: {exc}")
    assert _evidence(project, ["inputs/station"])["unreceipted_artifacts"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction behavior")
def test_input_junction_cannot_declare_output_directory(project):
    import _winapi

    _write(project, "outputs/results/result.csv")
    (project / "inputs").mkdir()
    _winapi.CreateJunction(str(project / "outputs/results"), str(project / "inputs/station"))
    evidence = _evidence(project, ["inputs/station"])
    assert "outputs/results/result.csv" in evidence["unreceipted_artifacts"]


def test_historical_download_mismatch_stays_unbound(project):
    raw = _write(project, "inputs/station/2022.csv")
    old_item = {"id": "raw", "dataset_id": "observations", "chosen_source": "observations",
                "requirements": {"start": "2012", "end": "2023"}}
    receipt_path = receipts.record_download(
        project, item_id="raw", source="manual placement", request_url="", http_status=None,
        raw_files=[raw], approval_sha256="old-approval", inventory_item=old_item,
    )
    receipt_bytes = receipt_path.read_bytes()
    new_item = {k: v for k, v in old_item.items() if k != "requirements"}
    new_item["local_paths"] = ["inputs/station"]
    inventory = {"items": [new_item]}
    evidence = receipts.evidence(project, {}, {}, inventory=inventory)
    assert evidence["unreceipted_artifacts"] == []
    assert evidence["downloads_total"] == 1 and evidence["downloads_bound"] == 0
    assert any("requirements changed" in e["why"] for e in evidence["rejected_receipts"])
    inspected = receipts.inspect_downloads(project, inventory)[0]
    assert inspected.request_match == "mismatch" and inspected.files == "intact"
    assert not inspected.bound and not inspected.reusable
    assert receipt_path.read_bytes() == receipt_bytes
    assert json.loads(receipt_bytes)["approval_sha256"] == "old-approval"


def test_changed_download_bytes_stay_unbound(project):
    raw = _write(project, "inputs/station/2022.csv")
    item = {"id": "raw", "dataset_id": "observations", "local_paths": ["inputs/station"]}
    receipts.record_download(project, item_id="raw", source="manual placement", request_url="",
                             http_status=None, raw_files=[raw], approval_sha256="old",
                             inventory_item=item)
    raw.write_text("changed\n", encoding="utf-8")
    evidence = receipts.evidence(project, {}, {}, inventory={"items": [item]})
    assert evidence["downloads_bound"] == 0
    assert any("changed" in e["why"] for e in evidence["rejected_receipts"])


def test_typed_calibration_case_directory_keeps_existing_behavior(project):
    _write(project, "calibration/cases/reference/nested/data.csv")
    _write(project, "calibration/other/stray.csv")
    plan = {"steps": [{"id": "calibration", "kind": "calibrate", "calibration": {},
                        "inputs": ["raw"], "outputs": []}]}
    evidence = _evidence(project, ["calibration/cases/reference"], plan)
    assert evidence["unreceipted_artifacts"] == ["calibration/other/stray.csv"]
