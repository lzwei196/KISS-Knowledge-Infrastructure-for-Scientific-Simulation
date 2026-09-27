"""Presentation caching must not turn changed evidence into current proof."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from kiss_cli import flowgate, project_status


@pytest.fixture
def cached_project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project_status._EVIDENCE_CACHE.clear()
    project = tmp_path / "project"
    data = project / "inputs" / "forcing.dat"
    data.parent.mkdir(parents=True)
    data.write_bytes(b"original fixture data")
    item = {"id": "forcing", "dataset_id": "source-a", "chosen_source": "source-a",
            "requirements": {"start": "2001-01-01"}}
    flow = flowgate.load()
    receipt = flow.receipts.record_download(
        project, item_id="forcing", source="fixture", request_url="https://example.test/data",
        http_status=200, raw_files=[data], inventory_item=item,
        approval_sha256="fixture-earlier-approval")
    inspect = flow.receipts.inspect_downloads
    calls = []

    def counted(*args, **kwargs):
        calls.append((args, kwargs))
        return inspect(*args, **kwargs)

    monkeypatch.setattr(flow.receipts, "inspect_downloads", counted)
    env = SimpleNamespace(project=project, data=data, receipt=receipt, flow=flow,
                          inventory={"items": [item]}, calls=calls)
    yield env
    project_status._EVIDENCE_CACHE.clear()


def _read(env, *, now=100.0, approval="MISSING", enforcement="none"):
    return project_status._checked_evidence(
        env.project, env.flow, {}, env.inventory, approval, enforcement, now)


def test_unchanged_evidence_is_reused_without_rehash_and_keeps_inspection_time(cached_project):
    env = cached_project
    first = _read(env)
    assert first[1][0].reusable
    second = _read(env, now=200.0)
    assert len(env.calls) == 1
    assert second[2] == first[2] == 100.0
    # A caller can annotate its own projection, never mutate the cached proof.
    first[1][0].receipt["source"] = "caller-local annotation"
    assert _read(env)[1][0].receipt["source"] == "fixture"


def test_same_size_change_with_restored_mtime_invalidates_cached_integrity(cached_project):
    env = cached_project
    assert _read(env)[1][0].reusable
    stat = env.data.stat()
    env.data.write_bytes(b"modified fixture data")
    os.utime(env.data, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert env.data.stat().st_size == stat.st_size
    inspected = _read(env, now=200.0)
    assert len(env.calls) == 2
    assert inspected[1][0].files == "changed"
    assert not inspected[1][0].reusable


def test_artifact_membership_and_receipt_changes_invalidate(cached_project):
    env = cached_project
    _read(env)
    output = env.project / "outputs" / "new.csv"
    output.parent.mkdir()
    output.write_text("time,value\n1,2\n", encoding="utf-8")
    _read(env)
    assert len(env.calls) == 2
    output.unlink()
    _read(env)
    assert len(env.calls) == 3
    doc = json.loads(env.receipt.read_text(encoding="utf-8"))
    doc["source"] = "tampered receipt"
    env.receipt.write_text(json.dumps(doc), encoding="utf-8")
    assert not _read(env)[1][0].reusable
    assert len(env.calls) == 4


def test_scope_approval_and_enforcement_changes_invalidate(cached_project):
    env = cached_project
    _read(env)
    _read(env, approval="DRIFT")
    _read(env, approval="DRIFT", enforcement="exact")
    assert len(env.calls) == 3
    env.inventory["items"][0]["requirements"]["start"] = "2002-01-01"
    result = _read(env, approval="DRIFT", enforcement="exact")
    assert len(env.calls) == 4
    assert not result[1][0].reusable


def test_signing_key_removal_invalidates_legacy_project_cache(cached_project):
    env = cached_project
    # A legacy/unmanaged project has no signed Flow state/approval to detect key
    # changes before the presentation cache. Receipt validity must still refresh.
    assert _read(env)[1][0].reusable
    key = env.flow.receipts.keys_dir() / f"{env.flow.receipts.project_id(env.project)}.key"
    key.unlink()
    assert not _read(env)[1][0].reusable
    assert len(env.calls) == 2


def test_retargeted_symlink_to_outside_hardlink_invalidates(cached_project, tmp_path):
    env = cached_project
    target = env.data.with_name("actual-forcing.dat")
    env.data.rename(target)
    outside = tmp_path / "outside-forcing.dat"
    os.link(target, outside)
    env.data.symlink_to(target)
    assert _read(env)[1][0].reusable
    target_stat = target.stat()
    env.data.unlink()
    env.data.symlink_to(outside)
    assert outside.stat().st_ino == target_stat.st_ino
    assert outside.stat().st_ctime_ns == target_stat.st_ctime_ns
    result = _read(env)
    assert len(env.calls) == 2
    assert result[1][0].files == "unsafe"
    assert not result[1][0].reusable


def test_files_changed_during_inspection_are_not_returned_or_cached(cached_project, monkeypatch):
    env = cached_project
    inspect = env.flow.receipts.inspect_downloads
    mutate_once = True

    def changing_inspection(*args, **kwargs):
        nonlocal mutate_once
        result = inspect(*args, **kwargs)
        if mutate_once:
            mutate_once = False
            assert result[0].reusable  # The just-computed evidence is about to become stale.
            env.data.write_bytes(b"modified fixture data")
        return result

    monkeypatch.setattr(env.flow.receipts, "inspect_downloads", changing_inspection)
    with pytest.raises(ValueError, match="changed during evidence inspection"):
        _read(env)
    assert str(env.project.resolve()) not in project_status._EVIDENCE_CACHE

    refreshed = _read(env, now=200.0)
    assert len(env.calls) == 2
    assert refreshed[1][0].files == "changed"
    assert not refreshed[1][0].reusable
    assert refreshed[2] == 200.0
    assert not _read(env, now=300.0)[1][0].reusable
    assert len(env.calls) == 2  # Only the stable, fresh negative verdict can be cached.
