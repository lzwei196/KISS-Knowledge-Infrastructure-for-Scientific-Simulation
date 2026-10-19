"""Browser origin prevents false orphan results, never grants producer evidence."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from kiss_cli import flowgate, flowrun, project_status, sessions
from .test_execution_evidence_currentness import case, run


@pytest.fixture
def upload_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    workroot = tmp_path / "work"
    session = sessions.create(workroot)
    project = sessions.project_path(workroot, session)
    return workroot, session, project, flowgate.load().receipts


def upload(c, name="reference.json", data=b'{"reference":true}'):
    return sessions.save_upload(c.project.parent,
        {"id": "abcdef123456", "project_dir": c.project.name}, name, data)


def evidence(env, plan=None, inventory=None):
    _, _, project, receipts = env
    return receipts.evidence(project, plan, None, inventory=inventory)


def test_real_browser_storage_reference_does_not_block_actual_receipted_completion(case):
    c = case
    run(c, "produce")
    run(c, "consume")
    saved = upload(c, "wrf-gridded-build-independent-audit.json")
    assert saved.relative_to(c.project).as_posix() in c.fs.flow.receipts.uploaded_input_files(c.project)
    assert c.fs.evidence()["receipts_verified"]
    verdict = flowrun.after(c.project, c.turn, "Finished; uploaded audit is reference material.")
    assert c.fs.state.value == "COMPLETED"
    assert "regenerate or remove" not in verdict.message


def test_same_name_repeat_upload_reconfirms_only_identical_original_without_overwrite(upload_project):
    work, session, project, receipts = upload_project
    old = project / "inputs/uploads/reference.json"
    old.write_bytes(b'{"legacy":"reference"}')
    sibling = old.with_name("unconfirmed.json")
    sibling.write_bytes(old.read_bytes())
    assert not receipts.uploaded_input_files(project)
    saved = sessions.save_upload(work, session, "reference.json", old.read_bytes())
    assert saved != old and old.read_bytes() == saved.read_bytes()
    assert receipts.uploaded_input_files(project) == {
        old.relative_to(project).as_posix(), saved.relative_to(project).as_posix()}
    assert "inputs/uploads/unconfirmed.json" in evidence(upload_project)["unreceipted_artifacts"]


def test_different_collision_body_never_attests_original(upload_project):
    work, session, project, receipts = upload_project
    old = project / "inputs/uploads/reference.json"
    old.write_bytes(b'{"old":1}')
    saved = sessions.save_upload(work, session, "reference.json", b'{"new":2}')
    assert receipts.uploaded_input_files(project) == {saved.relative_to(project).as_posix()}
    assert old.read_bytes() == b'{"old":1}'


@pytest.mark.parametrize("kind", ["manual", "forged_manifest", "changed", "missing_origin", "tampered_origin"])
def test_unproved_or_changed_inputs_remain_orphans(upload_project, kind):
    work, session, project, receipts = upload_project
    target = project / "inputs/uploads/reference.json"
    if kind in {"manual", "forged_manifest"}:
        target.write_bytes(b'{"reference":true}')
        if kind == "forged_manifest":
            directory = receipts.upload_origin_dir(project, create=True)
            (directory / (hashlib.sha256(b"inputs/uploads/reference.json").hexdigest() + ".json")).write_text(
                json.dumps({"kind": "browser-input-upload", "version": 1,
                            "project_id": receipts.project_id(project),
                            "file": {"path": "inputs/uploads/reference.json", "bytes": target.stat().st_size,
                                     "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}}))
    else:
        target = sessions.save_upload(work, session, "reference.json", b'{"reference":true}')
        origin, = receipts.upload_origin_dir(project).glob("*.json")
        if kind == "changed":
            target.write_bytes(b'{"reference":false}')
        elif kind == "missing_origin":
            origin.unlink()
        else:
            doc = json.loads(origin.read_text(encoding="utf-8"))
            doc["uploaded_at"] = "forged"
            origin.write_text(json.dumps(doc), encoding="utf-8")
    assert not receipts.uploaded_input_files(project)
    assert "inputs/uploads/reference.json" in evidence(upload_project)["unreceipted_artifacts"]


@pytest.mark.parametrize("raw", ["outputs/generated.csv", "inputs/uploads/generated.csv"])
def test_unreceipted_model_result_still_blocks_completion(case, raw):
    c = case
    run(c, "produce")
    run(c, "consume")
    output = c.project / raw
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"time,flow\n1,4\n2,6\n")
    proof = c.fs.evidence()
    assert raw in proof["unreceipted_artifacts"] and not proof["receipts_verified"]
    verdict = flowrun.after(c.project, c.turn, "All results passed.")
    assert "not complete" in verdict.message and c.fs.state.value != "COMPLETED"


@pytest.mark.parametrize("declared", ["file", "parent", "ancestor"])
def test_signed_upload_never_satisfies_declared_output_even_in_input_namespace(upload_project, declared):
    work, session, project, receipts = upload_project
    saved = sessions.save_upload(work, session, "result.json", b'{"fake_result":1}')
    rel = saved.relative_to(project).as_posix()
    output = {"file": rel, "parent": "inputs/uploads", "ancestor": "inputs"}[declared]
    plan = {"steps": [{"id": "model", "kind": "run", "outputs": ["generated"]}]}
    inv = {"items": [{"id": "generated", "local_paths": [output]},
                     {"id": "same_alias", "local_paths": ["inputs"]}]}
    proof = evidence(upload_project, plan, inv)
    assert rel in receipts.uploaded_input_files(project)
    assert rel in proof["unreceipted_artifacts"] and not proof["receipts_verified"]


@pytest.mark.parametrize("status,approval", [("passed", "old"), ("failed", "old"), ("failed", "current")])
def test_recorded_output_cannot_be_laundered_by_repeat_upload(upload_project, status, approval):
    work, session, project, receipts = upload_project
    result = project / "inputs/uploads/result.json"
    result.write_bytes(b'{"old_result":1}')
    receipts.record_run(project, ki="M", executable=sys.executable, command=[sys.executable],
        cwd=str(project), started_at=time.time(), finished_at=time.time(), exit_code=0,
        inputs=[], outputs=[result], approval_sha256=approval, plan_step_id="model",
        validation={"status": status, "checks": []})
    result.write_bytes(b'{"new_result":2}')
    sessions.save_upload(work, session, result.name, result.read_bytes())
    rel = result.relative_to(project).as_posix()
    assert rel in receipts.uploaded_input_files(project)
    proof = receipts.evidence(project, {"selected_kis": ["M"], "steps": []},
                              {"signature": {"value": "current"}})
    assert rel in proof["unreceipted_artifacts"]


def test_output_symlink_to_signed_upload_does_not_inherit_input_origin(upload_project):
    work, session, project, receipts = upload_project
    saved = sessions.save_upload(work, session, "reference.json", b'{"reference":1}')
    alias = project / "outputs/fake.json"
    alias.symlink_to(saved)
    assert saved.relative_to(project).as_posix() in receipts.uploaded_input_files(project)
    assert evidence(upload_project)["unreceipted_artifacts"]


@pytest.mark.parametrize("kind", ["hardlink", "symlink"])
def test_collision_with_link_never_attests_existing_target(upload_project, tmp_path, kind):
    work, session, project, receipts = upload_project
    outside = tmp_path / "original.json"
    outside.write_bytes(b'{"reference":1}')
    candidate = project / "inputs/uploads/reference.json"
    if kind == "hardlink":
        os.link(outside, candidate)
    else:
        candidate.symlink_to(outside)
    try:
        saved = sessions.save_upload(work, session, candidate.name, outside.read_bytes())
    except (ValueError, OSError):
        pass
    else:
        assert saved != candidate
    assert "inputs/uploads/reference.json" not in receipts.uploaded_input_files(project)
    assert outside.read_bytes() == b'{"reference":1}'


@pytest.mark.parametrize("change", ["delete", "tamper", "bytes"])
def test_status_cache_rechecks_external_origin_and_uploaded_bytes(case, change):
    c = case
    run(c, "produce")
    run(c, "consume")
    saved = upload(c)
    project_status._EVIDENCE_CACHE.clear()
    def checked():
        return project_status._checked_evidence(c.project, c.fs.flow, c.fs.plan, c.fs.inventory,
                                               "OK", "exact", time.time())[0]
    assert checked()["receipts_verified"]
    manifest, = c.fs.flow.receipts.upload_origin_dir(c.project).glob("*.json")
    if change == "delete":
        manifest.unlink()
    elif change == "tamper":
        stat = manifest.stat()
        data = manifest.read_text(encoding="utf-8").replace("browser-input-upload", "browser-input-uploae")
        manifest.write_text(data, encoding="utf-8")
        os.utime(manifest, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    else:
        stat = saved.stat()
        saved.write_bytes(saved.read_bytes().replace(b"true", b"null"))
        os.utime(saved, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = checked()
    assert not second["receipts_verified"] and saved.relative_to(c.project).as_posix() in second["unreceipted_artifacts"]


def test_upload_origin_does_not_validate_or_approve_missing_model_steps(upload_project):
    work, session, project, _ = upload_project
    sessions.save_upload(work, session, "all-results.json", b'{"status":"passed"}')
    proof = evidence(upload_project, {"steps": [{"id": "model", "kind": "run"}]})
    assert proof["steps_missing"] == ["model"]
    assert not proof["receipts_verified"] and not (project / "runs/approval.json").exists()


def test_source_is_rechecked_after_hash_before_origin_issue(upload_project, monkeypatch):
    work, session, project, receipts = upload_project
    original = receipts._upload_file
    count = 0
    def changed(*args):
        nonlocal count
        result = original(*args)
        count += 1
        if count == 1:
            (project / result["path"]).write_bytes(b"changed after initial capture")
        return result
    monkeypatch.setattr(receipts, "_upload_file", changed)
    with pytest.raises(ValueError, match="changed before origin"):
        sessions.save_upload(work, session, "reference.json", b'{"reference":true}')
    assert not receipts.uploaded_input_files(project)
