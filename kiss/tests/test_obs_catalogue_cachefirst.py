"""Discovery reads populated metadata snapshots without blocking on authentication.

Network and password-store access are forbidden unless a test explicitly installs
a tiny fake catalogue server for the existing missing-cache/forced-refresh path.
"""
from __future__ import annotations

import json
import time

import pytest

from kiss_cli import obs_access


@pytest.fixture
def cache(tmp_path, monkeypatch):
    store = tmp_path / "app/catalogue.json"
    monkeypatch.setattr(obs_access, "catalogue_store_path", lambda: store)

    def forbidden(*_args, **_kwargs):
        pytest.fail("cached discovery must not construct a Client or read the password store")

    monkeypatch.setattr(obs_access, "Client", forbidden)
    monkeypatch.setattr(obs_access.secret_store, "get_secret", forbidden)
    payload = {
        "schema_version": obs_access.CATALOGUE_SNAPSHOT_SCHEMA,
        "ok": True, "service": "GeoForge Database", "etag": "fixture-v1",
        "generated_at": "2020-01-01T00:00:00+00:00", "generated_at_epoch": 1,
        "total": 7, "returned": 5, "truncated": True,
        "datasets": [{"id": f"forcing-{index}", "name": "Fixture forcing", "variables": ["prec"]}
                     for index in range(5)],
    }
    obs_access._atomic_json(store, payload)
    return store, payload


def test_expired_populated_cache_search_never_refreshes_and_keeps_pagination(cache):
    store, payload = cache
    before = store.read_bytes()
    result = obs_access.search_catalogue(q="forcing", variable="prec", offset=1, limit=2)
    assert [row["id"] for row in result["datasets"]] == ["forcing-1", "forcing-2"]
    assert result["source"] == "local" and result["stale"] is True
    assert result["total"] == 5 and result["offset"] == 1 and result["limit"] == 2
    assert result["returned"] == 2 and result["has_more"] is True
    assert result["catalogue_total"] == 5
    assert result["catalogue_reported_total"] == 7 and result["catalogue_truncated"] is True
    assert result["catalogue_generated_at"] == payload["generated_at"]
    assert result["acquisition_evidence"]["authentication"] == "not_checked"
    assert result["acquisition_evidence"]["source_schema"] == "not_checked"
    assert store.read_bytes() == before


@pytest.mark.parametrize("error", ["expired_token", "network_error"])
def test_cached_records_keep_last_refresh_error_without_rechecking_credentials(cache, error):
    store, payload = cache
    payload.update(ok=False, stale=True, error={"code": error, "message": obs_access.ERROR_MESSAGES[error]})
    obs_access._atomic_json(store, payload)
    result = obs_access.search_catalogue(q="forcing")
    assert result["ok"] is True  # local query succeeded, not authentication
    assert result["catalogue_last_refresh_ok"] is False
    assert result["catalogue_error"] == payload["error"]
    assert result["stale"] is True and payload["error"]["message"] in result["warning"]
    assert result["acquisition_evidence"]["authentication"] == "not_checked"


def test_fresh_metadata_cache_still_does_not_prove_live_auth_or_file_schema(cache):
    store, payload = cache
    payload.update(generated_at_epoch=time.time(), total=5, truncated=False)
    obs_access._atomic_json(store, payload)
    result = obs_access.search_catalogue(q="forcing", offset=4, limit=2)
    assert result["stale"] is False and result["has_more"] is False
    assert result["returned"] == 1 and result["catalogue_truncated"] is False
    assert result["acquisition_evidence"]["authentication"] == "not_checked"
    assert result["acquisition_evidence"]["source_schema"] == "not_checked"


def test_no_local_matches_does_not_trigger_a_refresh_or_mean_complete_catalogue(cache):
    result = obs_access.search_catalogue(q="no matching record")
    assert result["datasets"] == [] and result["total"] == 0
    assert result["returned"] == 0 and result["has_more"] is False
    assert result["catalogue_total"] == 5 and result["catalogue_reported_total"] == 7
    assert result["catalogue_truncated"] is True


def test_project_snapshot_is_immediate_and_retains_cache_age_and_completeness(cache, tmp_path):
    store, payload = cache
    before = store.read_bytes()
    path = obs_access.prepare_catalogue_snapshot(tmp_path / "project")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert snapshot["datasets"] == payload["datasets"]
    assert snapshot["generated_at_epoch"] == payload["generated_at_epoch"]
    assert snapshot["total"] == 7 and snapshot["returned"] == 5 and snapshot["truncated"] is True
    assert snapshot["stale"] is True
    assert store.read_bytes() == before
    prompt = obs_access.planning_snapshot_prompt(path)
    assert "cached" in prompt.lower() and "current (" not in prompt
    assert "authentication" in prompt.lower() and "not checked" in prompt.lower()


def test_existing_project_snapshot_is_usable_when_app_cache_is_missing(cache, tmp_path):
    store, payload = cache
    project = tmp_path / "project"
    path = project / obs_access.CATALOGUE_SNAPSHOT
    obs_access._atomic_json(path, payload)
    store.unlink()
    result = obs_access.prepare_catalogue_snapshot(project)
    assert result == path
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert snapshot["datasets"] == payload["datasets"] and snapshot["stale"] is True


def test_project_snapshot_does_not_hide_known_authentication_failure(cache, tmp_path):
    store, payload = cache
    payload.update(ok=False, stale=True, error={"code": "expired_token", "message": "Fixture token expired"})
    obs_access._atomic_json(store, payload)
    path = obs_access.prepare_catalogue_snapshot(tmp_path / "project")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert snapshot["ok"] is False and snapshot["error"] == payload["error"]
    assert snapshot["stale"] is True and snapshot["datasets"] == payload["datasets"]
    prompt = obs_access.planning_snapshot_prompt(path)
    assert "cached metadata" in prompt and "last refresh failed (Fixture token expired)" in prompt


@pytest.mark.parametrize("cached", [None, {"datasets": []}, {"datasets": "invalid"}])
def test_missing_or_unusable_cache_keeps_existing_refresh_fallback(cache, monkeypatch, cached):
    store, _payload = cache
    if cached is None:
        store.unlink()
    else:
        obs_access._atomic_json(store, cached)
    calls = []

    class Server:
        def catalogue(self, **kwargs):
            calls.append(kwargs)
            return {"total": 1, "datasets": [{"id": "downloadable-record"}]}

    monkeypatch.setattr(obs_access, "Client", Server)
    result = obs_access.search_catalogue()
    assert [row["id"] for row in result["datasets"]] == ["downloadable-record"]
    assert len(calls) == 1


def test_forced_project_snapshot_refreshes_even_with_populated_cache(cache, monkeypatch, tmp_path):
    store, _payload = cache
    calls = []

    class Server:
        def catalogue(self, **kwargs):
            calls.append(kwargs)
            return {"total": 1, "etag": "fixture-v2", "datasets": [{"id": "fresh-record"}]}

    monkeypatch.setattr(obs_access, "Client", Server)
    path = obs_access.prepare_catalogue_snapshot(tmp_path / "project", force=True)
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert calls and snapshot["datasets"][0]["id"] == "fresh-record"
    assert json.loads(store.read_text(encoding="utf-8"))["etag"] == "fixture-v2"


def test_explicit_refresh_entrypoint_still_refreshes(cache):
    store, _payload = cache
    calls = []

    class Server:
        def catalogue(self, **kwargs):
            calls.append(kwargs)
            return {"total": 1, "etag": "fixture-v3", "datasets": [{"id": "new-record"}]}

    result = obs_access.refresh_catalogue(client=Server(), force=True)
    assert calls and result["datasets"][0]["id"] == "new-record"
    assert json.loads(store.read_text(encoding="utf-8"))["etag"] == "fixture-v3"
