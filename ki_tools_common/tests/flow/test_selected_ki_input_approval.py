"""Approval binds exact newly admitted KI data bytes, not file timestamps."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ki_tools_common.flow import approval, plan, receipts


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "host-keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "host-registry"))
    project = tmp_path / "project"
    root = project / "models/M/ki"
    raw = root / "outputs/example/weather.csv"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"date,value\n1980-01-01,1\n")
    tool = project / "project_tools/reader.py"
    tool.parent.mkdir()
    tool.write_text("# reviewed reader fixture; never executed\n", encoding="utf-8")
    document = {"schema_version": "1.0", "goal": "fixture", "selected_kis": ["M"],
        "scientific_choices": [], "unresolved_questions": [], "coupling": [], "created_at": "now",
        "steps": [{"id": "read", "ki": "M", "kind": "check", "status": "planned",
                   "tool": str(tool), "project_data_tool": {}, "inputs": ["weather"], "outputs": []}]}
    inventory = {"schema_version": "1.0", "items": [{"id": "weather", "status": "ready",
                  "local_paths": [str(raw)]}]}
    plan.write_artifacts(project, document, inventory)
    return project, root, raw, document, inventory


def signed_legacy(project, document):
    document = copy.deepcopy(document)
    document.pop("selected_ki_input_sha256")
    document = receipts.sign(project, document)
    (project / "runs/approval.json").write_text(json.dumps(document), encoding="utf-8")
    receipts.publish_current(project, "approval", document)


def test_only_explicit_consumed_selected_ki_files_get_byte_bindings(case):
    project, root, raw, document, inventory = case
    untouched = root / "outputs/example/unused.json"
    untouched.write_text("{}", encoding="utf-8")
    conventional = root / "test_cases/demo/inputs/legacy.csv"
    conventional.parent.mkdir(parents=True)
    conventional.write_text("legacy", encoding="utf-8")
    ordinary = project / "inputs/external.csv"
    ordinary.parent.mkdir()
    ordinary.write_text("external", encoding="utf-8")
    inventory["items"] += [{"id": "unused", "local_paths": [str(untouched)]},
                           {"id": "legacy", "local_paths": [str(conventional)]},
                           {"id": "external", "local_paths": [str(ordinary)]}]
    document["steps"][0]["inputs"] += ["legacy", "external"]
    plan.write_artifacts(project, document, inventory)
    approved = approval.approve(project)
    assert approved["selected_ki_input_sha256"] == {
        "read": {"weather": [{"path": str(raw), "sha256": hashlib.sha256(raw.read_bytes()).hexdigest()}]}}
    assert approval.check(project) == "OK"
    untouched.write_text('{"not_consumed":true}', encoding="utf-8")
    assert approval.check(project) == "OK"


def test_same_size_same_mtime_input_mutation_is_drift_and_requires_reapproval(case):
    project, root, raw, document, inventory = case
    initial = approval.approve(project)
    info = raw.stat()
    raw.write_bytes(raw.read_bytes().replace(b",1", b",2"))
    os.utime(raw, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert raw.stat().st_size == info.st_size and raw.stat().st_mtime_ns == info.st_mtime_ns
    assert approval.check(project) == "DRIFT"
    renewed = approval.approve(project)
    assert renewed["selected_ki_input_sha256"] != initial["selected_ki_input_sha256"]
    assert approval.check(project) == "OK"


@pytest.mark.parametrize("damage", ["missing", "directory", "executable_magic", "hardlink", "symlink"])
def test_input_replacement_cannot_retain_prior_approval(case, tmp_path, damage):
    project, root, raw, document, inventory = case
    approval.approve(project)
    raw.unlink()
    if damage == "directory": raw.mkdir()
    if damage == "executable_magic": raw.write_bytes(b"#!python\nprint('not data')")
    if damage in {"hardlink", "symlink"}:
        other = tmp_path / "other.csv"
        other.write_text("outside", encoding="utf-8")
        try:
            if damage == "hardlink": os.link(other, raw)
            else: raw.symlink_to(other)
        except OSError as error:
            pytest.skip(str(error))
    assert approval.check(project) == "DRIFT"


@pytest.mark.parametrize("raw_kind", ["missing", "directory", "code", "traversal"])
def test_ineligible_ki_file_cannot_receive_initial_approval(case, raw_kind):
    project, root, raw, document, inventory = case
    if raw_kind == "missing": raw.unlink()
    if raw_kind == "directory":
        raw.unlink()
        raw.mkdir()
    if raw_kind == "code":
        target = root / "tools/script.py"
        target.parent.mkdir()
        target.write_text("pass", encoding="utf-8")
        inventory["items"][0]["local_paths"] = [str(target)]
    if raw_kind == "traversal":
        inventory["items"][0]["local_paths"] = [str(raw.parent / ".." / "example" / raw.name)]
    plan.write_artifacts(project, document, inventory)
    with pytest.raises((ValueError, FileNotFoundError)):
        approval.approve(project)
    assert not (project / "runs/approval.json").exists()


def test_legacy_approval_for_new_ki_input_requires_reapproval(case):
    project, _, _, _, _ = case
    signed_legacy(project, approval.approve(project))
    assert approval.check(project) == "DRIFT"


@pytest.mark.parametrize("mode", ["none", "case", "non_adapter", "skipped"])
def test_legacy_approvals_without_newly_bound_inputs_remain_valid(case, mode):
    project, root, raw, document, inventory = case
    if mode == "none": document["steps"][0]["inputs"] = []
    if mode == "case":
        target = root / "test_cases/demo/inputs/weather.csv"
        target.parent.mkdir(parents=True)
        target.write_bytes(raw.read_bytes())
        inventory["items"][0]["local_paths"] = [str(target)]
    if mode == "non_adapter": document["steps"][0].pop("project_data_tool")
    if mode == "skipped": document["steps"][0]["status"] = "skipped"
    plan.write_artifacts(project, document, inventory)
    signed = approval.approve(project)
    assert signed["selected_ki_input_sha256"] == {}
    signed_legacy(project, signed)
    assert approval.check(project) == "OK"


def test_relative_and_project_placeholder_paths_bind_same_exact_file(case):
    project, root, raw, document, inventory = case
    for spelling in [raw.relative_to(project).as_posix(), "${PROJECT}/" + raw.relative_to(project).as_posix()]:
        inventory["items"][0]["local_paths"] = [spelling]
        plan.write_artifacts(project, document, inventory)
        signed = approval.approve(project)
        assert signed["selected_ki_input_sha256"]["read"]["weather"][0]["path"] == str(raw)
        assert approval.check(project) == "OK"


def test_transient_input_read_error_is_not_misreported_as_drift(case, monkeypatch):
    project, root, raw, document, inventory = case
    approval.approve(project)
    original = receipts.sha256_file
    def fail(path):
        if Path(path) == raw: raise OSError("temporary volume read failure")
        return original(path)
    monkeypatch.setattr(receipts, "sha256_file", fail)
    with pytest.raises(RuntimeError, match="selected KI data input"):
        approval.check(project)
