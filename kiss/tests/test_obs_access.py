from __future__ import annotations

import hashlib
import http.client
import io
import json
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "kiss"))

from kiss_cli import obs_access, settings  # noqa: E402


class Response(io.BytesIO):
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class Opener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout=0):
        self.requests.append((request, timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class InterruptedResponse(Response):
    """Yield one partial block, then emulate a broken HTTP stream."""

    def __init__(self):
        super().__init__(b"", {
            "Content-Type": "application/octet-stream",
            "Content-Disposition": 'attachment; filename="data.bin"',
            "X-Content-SHA256": hashlib.sha256(b"complete").hexdigest(),
        })
        self.calls = 0

    def read(self, _size=-1):
        self.calls += 1
        if self.calls == 1:
            return b"partial"
        raise http.client.IncompleteRead(b"", 10)


def json_response(payload: dict) -> Response:
    return Response(json.dumps(payload).encode(), {"Content-Type": "application/json"})


def test_local_discovery_is_explicitly_not_live_acquisition_evidence():
    result = obs_access.local_search([{'id': 'a', 'name': 'example', 'delivery': 'served'}])
    assert result['datasets'][0]['delivery'] == 'served'
    evidence = result['acquisition_evidence']
    assert evidence['catalogue_only'] is True
    assert evidence['live_delivery'] == evidence['subset_estimate'] == 'not_checked'
    assert evidence['model_ready'] is False


def test_sparse_search_does_not_claim_catalogue_is_empty():
    records = [{'id': 'global_dem', 'name': 'Global elevation', 'bbox': [-180,-90,180,90]},
               {'id': 'local_statistics', 'name': 'Hengshui statistics'}]
    sparse = obs_access.local_search(records, q='Hengshui', bbox=[115,37,116,38])
    assert sparse['total'] == 1 and sparse['catalogue_total'] == 2
    assert sparse['query']['keywords'] == 'Hengshui'
    assert sparse['query']['bbox'] == (115.,37.,116.,38.)
    broader = obs_access.local_search(records, q='elevation', bbox=[115,37,116,38])
    assert [d['id'] for d in broader['datasets']] == ['global_dem']


def test_gateway_http_status_reaches_client_without_private_response():
    failure = HTTPError('https://example.invalid', 530, 'down', {},
                        io.BytesIO(b'PRIVATE token or source path'))
    c = obs_access.Client(opener=Opener(failure), token_getter=lambda: 'fake')
    with pytest.raises(obs_access.ObsAccessError) as raised:
        c._json('/subsets/estimate', method='POST', body={})
    result = raised.value.payload()
    assert result['error'] == 'server_unavailable' and result['http_status'] == 530
    assert 'HTTP 530' in result['message'] and 'PRIVATE' not in str(result)


def test_resolver_uses_documented_query_and_persists_only_real_public_children(monkeypatch):
    from urllib.parse import urlparse, parse_qs
    parent = "cmfd_china_daily_010"
    child = parent + "__prec_1989"
    raw = {"total": 1, "coverage_complete": True, "gaps": [], "estimated_bytes": 390000000,
           "spatial_filter_applied": False, "delivery_extent": [70,15,140,55],
           "requested_bbox": [115,37,117,39], "covers_requested_bbox": True,
           "baidu_url": "PRIVATE", "items": [{"id": child, "parent_id": parent,
           "variable": "prec", "year": 1989, "time_step": "daily", "delivery": "manual",
           "size_hint": 390000000, "bbox": [70,15,140,55], "baidu_pwd": "PRIVATE"}]}
    opener = Opener(json_response(raw))
    result = obs_access.search_catalogue(resolve_dataset_id=parent, variable="prec", start="1989-01-01",
        end="1989-12-31", bbox=[115,37,117,39], time_step="daily",
        client=obs_access.Client(opener=opener, token_getter=lambda: "test-only-token"))
    request = opener.requests[0][0]
    query = parse_qs(urlparse(request.full_url).query)
    assert query["dataset_id"] == [parent] and query["variable"] == ["prec"]
    assert query["bbox"] == ["115.0,37.0,117.0,39.0"]
    assert result["spatial_filter_applied"] is False
    assert "PRIVATE" not in json.dumps(result)
    monkeypatch.setattr(obs_access, "refresh_catalogue", lambda: {"datasets": [{"id": parent}]})
    inventory = {"items": [{"id": "rain", "dataset_id": child, "status": "missing"}]}
    assert obs_access.stamp_inventory(inventory) == []
    record = inventory["items"][0]["catalogue"]
    assert record["size"] == 390000000
    assert record["resolution"]["delivery_extent"] == [70,15,140,55]
    assert obs_access.stamp_inventory({"items": [{"id": "bad", "dataset_id": parent + "__unicorn_9999"}]})
    cached = list((obs_access.catalogue_store_path().parent / "resolved").glob("*.json"))
    assert cached and "PRIVATE" not in cached[0].read_text()


def test_resolver_rejects_partial_or_foreign_results():
    for raw in ({"total": 2, "items": []}, {"total": 1, "items": [{"id": "x", "parent_id": "wrong"}]}):
        client = obs_access.Client(opener=Opener(json_response(raw)), token_getter=lambda: "test")
        with pytest.raises(obs_access.ObsAccessError):
            obs_access.resolve_dataset("parent", client=client)


def test_resolver_preserves_unknown_coverage():
    client = obs_access.Client(opener=Opener(json_response({"total": 0, "items": [],
        "coverage_complete": None, "spatial_filter_applied": False})), token_getter=lambda: "test")
    assert obs_access.resolve_dataset("parent", client=client)["coverage_complete"] is None


def binary_response(body: bytes, *, name="data.bin", checksum: str | None = None):
    return Response(body, {
        "Content-Type": "application/octet-stream",
        "Content-Length": str(len(body)),
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Content-SHA256": checksum or hashlib.sha256(body).hexdigest(),
    })


def test_catalogue_uses_bearer_in_backend_only():
    opener = Opener(json_response({"total": 1, "datasets": [{"id": "obs-1"}]}))
    result = obs_access.Client(opener=opener, token_getter=lambda: "private-token").catalogue(
        q="discharge", limit=5)

    assert result["datasets"][0]["id"] == "obs-1"
    request, timeout = opener.requests[0]
    assert request.get_header("Authorization") == "Bearer private-token"
    assert request.get_header("User-agent") == "GeoForge-Desktop/obs-v1"
    assert "private-token" not in request.full_url
    assert timeout == 90


def test_native_token_is_loaded_once_per_desktop_process(monkeypatch):
    calls = []
    monkeypatch.setattr(obs_access, "_token_cache", obs_access._TOKEN_NOT_LOADED)
    monkeypatch.setattr(obs_access, "_token_error_cache", None)
    monkeypatch.setattr(
        obs_access.secret_store, "get_secret",
        lambda *_args: calls.append(_args) or "private-token")

    assert obs_access.token() == "private-token"
    assert obs_access.token() == "private-token"
    assert len(calls) == 1


def test_setting_native_token_replaces_cached_value(monkeypatch):
    writes = []
    monkeypatch.setattr(obs_access, "_token_cache", "old-token")
    monkeypatch.setattr(obs_access, "_token_error_cache", None)
    monkeypatch.setattr(
        obs_access.secret_store, "set_secret",
        lambda *_args: writes.append(_args))

    obs_access.set_token("new-token")

    assert obs_access.token() == "new-token"
    assert writes == [(obs_access.TOKEN_SERVICE, obs_access.TOKEN_ACCOUNT,
                       "new-token")]


def test_denied_native_token_is_not_retried_by_automatic_queries(monkeypatch):
    calls = []
    monkeypatch.setattr(obs_access, "_token_cache", obs_access._TOKEN_NOT_LOADED)
    monkeypatch.setattr(obs_access, "_token_error_cache", None)

    def denied(*_args):
        calls.append(_args)
        raise obs_access.secret_store.SecretStoreError("user denied access")

    monkeypatch.setattr(obs_access.secret_store, "get_secret", denied)

    for _ in range(2):
        with pytest.raises(obs_access.ObsAccessError) as caught:
            obs_access.token()
        assert "user denied access" in str(caught.value)
    assert len(calls) == 1


def test_explicit_retry_reopens_native_token_access_once(monkeypatch):
    calls = []
    monkeypatch.setattr(obs_access, "_token_cache", obs_access._TOKEN_NOT_LOADED)
    monkeypatch.setattr(obs_access, "_token_error_cache", None)

    def load(*_args):
        calls.append(_args)
        if len(calls) == 1:
            raise obs_access.secret_store.SecretStoreError("user denied access")
        return "private-token"

    monkeypatch.setattr(obs_access.secret_store, "get_secret", load)

    with pytest.raises(obs_access.ObsAccessError):
        obs_access.token()
    with pytest.raises(obs_access.ObsAccessError):
        obs_access.token()
    assert len(calls) == 1

    obs_access.retry_token_access()
    assert obs_access.token() == "private-token"
    assert len(calls) == 2


def test_public_catalogue_removes_delivery_secrets_but_keeps_scientific_metadata():
    payload = obs_access.public_catalogue({
        "total": 1,
        "datasets": [{
            "id": "cmfd-grid-51080",
            "name": "CMFD Bengbu cells",
            "variables": ["prec", "temp"],
            "applicable_domains": ["hydrology"],
            "spatial_extent": {"bbox": [116, 32, 118, 34],
                               "signed_url": "https://private.example"},
            "baidu_url": "https://pan.baidu.com/private",
            "baidu_pwd": "1234",
            "download_url": "https://signed.example/file",
            "unknown_backend_field": "internal",
        }],
    })

    record = payload["datasets"][0]
    assert record["id"] == "cmfd-grid-51080"
    assert record["variables"] == ["prec", "temp"]
    assert record["applicable_domains"] == ["hydrology"]
    assert record["spatial_extent"]["bbox"] == [116, 32, 118, 34]
    assert "signed_url" not in record["spatial_extent"]
    assert "baidu_url" not in record and "baidu_pwd" not in record
    assert "download_url" not in record and "unknown_backend_field" not in record


def test_complete_catalogue_pages_and_deduplicates_records():
    class PagedClient:
        def __init__(self):
            self.offsets = []

        def catalogue(self, **kwargs):
            offset = kwargs["offset"]
            self.offsets.append(offset)
            if offset == 0:
                return {"total": 101, "datasets": [
                    {"id": f"d-{index}", "variables": ["flow"]}
                    for index in range(100)
                ]}
            return {"total": 101, "datasets": [
                {"id": "d-99", "variables": ["flow"]},
                {"id": "d-100", "variables": ["flow"]},
            ]}

    client = PagedClient()
    result = obs_access.complete_catalogue(client=client)

    assert client.offsets == [0, 100]
    assert result["total"] == 101 and result["returned"] == 101
    assert result["datasets"][-1]["id"] == "d-100"


def test_snapshot_is_provider_neutral_and_records_unavailability(tmp_path):
    class MissingTokenClient:
        def catalogue(self, **_kwargs):
            raise obs_access.ObsAccessError("missing_token")

    path = obs_access.prepare_catalogue_snapshot(
        tmp_path, client=MissingTokenClient(), force=True)
    payload = json.loads(path.read_text())
    prompt = obs_access.planning_snapshot_prompt(path)

    assert path == tmp_path / ".geoforge/database/catalogue.json"
    assert payload["ok"] is False and payload["error"]["code"] == "missing_token"
    assert "HOST-OWNED DATA SERVICE" in prompt
    assert "never invent availability" in prompt
    assert "private-token" not in path.read_text()

    class ConfiguredClient:
        def catalogue(self, **_kwargs):
            return {"total": 1, "datasets": [
                {"id": "cmfd-cell-1", "variables": ["prec"]},
            ]}

    # Adding a token must take effect on the next plan; an earlier auth failure
    # is never held in the normal catalogue cache.
    obs_access.prepare_catalogue_snapshot(tmp_path, client=ConfiguredClient())
    refreshed = json.loads(path.read_text())
    assert refreshed["ok"] is True and refreshed["datasets"][0]["id"] == "cmfd-cell-1"


@pytest.mark.parametrize("code,message", list(obs_access.ERROR_MESSAGES.items())[:5])
def test_server_error_codes_have_clear_messages(code, message):
    body = json.dumps({"detail": {"error": code}}).encode()
    error = HTTPError("https://server", 401, "no", {}, io.BytesIO(body))
    client = obs_access.Client(opener=Opener(error), token_getter=lambda: "x")
    with pytest.raises(obs_access.ObsAccessError) as caught:
        client.catalogue()
    assert caught.value.code == code
    assert str(caught.value) == message


def test_missing_token_never_sends_request():
    opener = Opener()
    with pytest.raises(obs_access.ObsAccessError, match="Paste your activation"):
        obs_access.Client(opener=opener, token_getter=lambda: None).catalogue()
    assert opener.requests == []


def test_verified_file_download_is_atomic_and_project_scoped(tmp_path):
    project = tmp_path / "project"
    body = b"time,flow\n1,2\n"
    client = obs_access.Client(
        opener=Opener(binary_response(body, name="flow.csv")),
        token_getter=lambda: "x")

    result = client.download("obs-1", project, destination="observations/flow")

    target = project / "inputs" / "observations" / "flow" / "flow.csv"
    assert target.read_bytes() == body
    assert result["destination"] == str(target)
    assert not list((project / ".geoforge" / "tmp").rglob("*.part"))
    with pytest.raises(obs_access.ObsAccessError, match="inside this project's inputs"):
        client.download("obs-1", project, destination="../outside")


def test_checksum_mismatch_retries_once_then_removes_part_file(tmp_path):
    project = tmp_path / "project"
    wrong = "0" * 64
    opener = Opener(binary_response(b"one", checksum=wrong),
                    binary_response(b"two", checksum=wrong))
    with pytest.raises(obs_access.ObsAccessError) as caught:
        obs_access.Client(opener=opener, token_getter=lambda: "x").download(
            "obs-2", project)
    assert caught.value.code == "checksum_mismatch"
    assert len(opener.requests) == 2
    assert not list((project / ".geoforge" / "tmp").rglob("*.part"))


def test_interrupted_stream_retries_without_leaving_partial_input(tmp_path):
    project = tmp_path / "project"
    opener = Opener(InterruptedResponse(), binary_response(b"complete"))

    result = obs_access.Client(opener=opener, token_getter=lambda: "x").download(
        "obs-network", project)

    assert Path(result["destination"]).read_bytes() == b"complete"
    assert len(opener.requests) == 2
    assert not list((project / ".geoforge" / "tmp").rglob("*.part"))


def test_manual_delivery_returns_exact_destination_without_writing(tmp_path):
    payload = {"served": False, "name": "Large forcing", "size": "18 GB",
               "baidu_url": "https://pan.baidu.com/s/example", "baidu_pwd": "1234"}
    result = obs_access.Client(
        opener=Opener(json_response(payload)), token_getter=lambda: "x").download(
            "large-1", tmp_path, destination="forcing/cmfd")
    assert result["served"] is False
    assert result["destination"] == str(tmp_path / "inputs" / "forcing" / "cmfd")
    assert not (tmp_path / "inputs").exists()


def _zip(entries: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as bundle:
        for name, content in entries.items():
            bundle.writestr(name, content)
    return stream.getvalue()


def test_zip_is_verified_safely_unpacked_and_archive_retained(tmp_path):
    body = _zip({"nested/a.txt": b"real data"})
    result = obs_access.Client(
        opener=Opener(binary_response(body, name="dataset.zip")),
        token_getter=lambda: "x").download("zip-1", tmp_path)

    assert (tmp_path / "inputs" / "observations" / "zip-1" /
            "nested" / "a.txt").read_bytes() == b"real data"
    assert Path(result["raw_file"]).is_file()
    assert Path(result["raw_file"]).name == "dataset.zip"


def test_zip_path_traversal_is_rejected(tmp_path):
    body = _zip({"../escape.txt": b"bad"})
    with pytest.raises(obs_access.ObsAccessError) as caught:
        obs_access.Client(
            opener=Opener(binary_response(body, name="bad.zip")),
            token_getter=lambda: "x").download("bad-zip", tmp_path)
    assert caught.value.code == "unsafe_archive"
    assert not (tmp_path / "inputs" / "escape.txt").exists()
    assert not list((tmp_path / ".geoforge" / "downloads").rglob("*.zip"))


def test_opaque_dataset_id_cannot_escape_internal_cache(tmp_path):
    body = _zip({"data.txt": b"real"})
    result = obs_access.Client(
        opener=Opener(binary_response(body, name="dataset.zip")),
        token_getter=lambda: "x").download(
            "../../opaque/id", tmp_path, destination="observations/safe")

    archive = Path(result["raw_file"])
    assert archive.is_relative_to(tmp_path / ".geoforge" / "downloads")
    assert (tmp_path / "inputs" / "observations" / "safe" / "data.txt").is_file()


def test_settings_only_returns_masked_observation_token(tmp_path, monkeypatch):
    stored = {"value": None}
    monkeypatch.setattr(settings, "_path", lambda: tmp_path / "settings.json")
    monkeypatch.setattr(obs_access.secret_store, "get_secret",
                        lambda *_args: stored["value"])
    monkeypatch.setattr(obs_access.secret_store, "set_secret",
                        lambda *_args: stored.update(value=_args[-1]))
    monkeypatch.setattr(obs_access.secret_store, "delete_secret",
                        lambda *_args: stored.update(value=None))

    settings.update({"obs_activation_token": "secret-value"})
    shown = settings.masked()
    assert stored["value"] == "secret-value"
    assert shown["obs_token_configured"] is True
    assert shown["obs_activation_token"].startswith("…")
    assert "secret-value" not in (tmp_path / "settings.json").read_text()


# ---------------------------------------------------------------- app-level store + local search

_RECORDS = [
    {"id": "cmfd_china_daily_010", "name": "CMFD V2.0 Daily (China, 0.1deg)", "dataset_kind": "forcing",
     "delivery": "manual", "bbox": [70, 15, 140, 55], "start_date": "1951-01-01", "end_date": "2024-12-31",
     "variables": [{"name": "prec"}, {"name": "temp"}]},
    {"id": "cmfd_huai_daily_025", "name": "CMFD Huai River subset (0.25deg)", "dataset_kind": "forcing",
     "delivery": "manual", "parent_id": "cmfd_china_daily_010", "bbox": [112, 31, 120, 35],
     "start_date": "1960", "end_date": "2020", "variables": [{"name": "prec"}],
     "notes": "Pre-clipped to Huai basin extent"},
    {"id": "bengbu_51080", "name": "Bengbu", "dataset_kind": "gauge", "delivery": "served",
     "point": [32.93, 117.38], "start_date": "1950-01-01", "end_date": "1997-12-31",
     "variables": [{"name": "discharge_m3s"}]},
    {"id": "huaihe_basin", "name": "Full Huai River basin", "dataset_kind": "static_dataset",
     "delivery": "served", "format": "vector"},
    {"id": "red_deer_51", "name": "Red Deer gauge", "dataset_kind": "gauge", "delivery": "served",
     "lat": 52.3, "lon": -113.8, "start_date": "1980-01-01", "end_date": "2000-12-31",
     "variables": [{"name": "discharge_m3s"}]},
]


def test_local_search_filters_by_bbox_period_variable_and_ranks_geometry():
    hits = obs_access.local_search(_RECORDS, bbox="116,31,119,34", start="1980-01-01", end="1990-12-31")
    ids = [d["id"] for d in hits["datasets"]]
    assert "red_deer_51" not in ids                 # outside the box
    assert ids.index("bengbu_51080") < ids.index("huaihe_basin")   # geometry match ranks above no-geometry
    assert "huaihe_basin" in ids                    # no geometry -> kept, ranked last
    assert hits["source"] == "local" and hits["total"] == 4

    discharge = obs_access.local_search(_RECORDS, variable="discharge", bbox="116,31,119,34")
    assert [d["id"] for d in discharge["datasets"]] == ["bengbu_51080"]

    late = obs_access.local_search(_RECORDS, q="cmfd", start="2021-06-01", end="2022-01-01")
    assert [d["id"] for d in late["datasets"]] == ["cmfd_china_daily_010"]   # Huai ends 2020-12-31

    words = obs_access.local_search(_RECORDS, q="huai basin")
    assert {d["id"] for d in words["datasets"]} == {"cmfd_huai_daily_025", "huaihe_basin"}

    manual = obs_access.local_search(_RECORDS, delivery="manual", category="forcing")
    assert {d["id"] for d in manual["datasets"]} == {"cmfd_china_daily_010", "cmfd_huai_daily_025"}


def test_refresh_catalogue_keeps_copy_and_repages_only_when_etag_changes(tmp_path):
    class Server:
        def __init__(self):
            self.calls = []
            self.etag = "e1"

        def catalogue(self, **kwargs):
            self.calls.append(kwargs)
            page = _RECORDS[kwargs["offset"]:kwargs["offset"] + kwargs["limit"]]
            return {"total": len(_RECORDS), "etag": self.etag, "datasets": page}

    server = Server()
    store = tmp_path / "catalogue.json"
    first = obs_access.refresh_catalogue(client=server, path=store)
    assert first["ok"] and first["etag"] == "e1" and len(first["datasets"]) == 5
    assert server.calls[0]["limit"] == obs_access.CATALOGUE_PAGE_SIZE

    # within ttl: no request at all
    server.calls.clear()
    assert obs_access.refresh_catalogue(client=server, path=store)["etag"] == "e1"
    assert server.calls == []

    # after ttl, unchanged etag: one cheap request, no re-page
    obs_access.refresh_catalogue(client=server, path=store, ttl=0)
    assert [c["limit"] for c in server.calls] == [1]

    # changed etag: re-page
    server.calls.clear()
    server.etag = "e2"
    assert obs_access.refresh_catalogue(client=server, path=store, ttl=0)["etag"] == "e2"
    assert [c["limit"] for c in server.calls][0] == 1 and len(server.calls) >= 2

    # server down: previous copy kept, marked stale with the error
    class Down:
        def catalogue(self, **_kwargs):
            raise obs_access.ObsAccessError("network_error")

    stale = obs_access.refresh_catalogue(client=Down(), path=store, ttl=0)
    assert stale["ok"] is False and stale["stale"] is True and len(stale["datasets"]) == 5
    assert stale["error"]["code"] == "network_error"


def test_search_catalogue_answers_from_local_store_and_raises_without_data(tmp_path, monkeypatch):
    store = tmp_path / "catalogue.json"
    monkeypatch.setattr(obs_access, "catalogue_store_path", lambda: store)

    class Server:
        def catalogue(self, **kwargs):
            return {"total": len(_RECORDS), "etag": "e1",
                    "datasets": _RECORDS[kwargs["offset"]:kwargs["offset"] + kwargs["limit"]]}

    monkeypatch.setattr(obs_access, "Client", lambda *a, **k: Server())
    hits = obs_access.search_catalogue(q="bengbu", variable="discharge")
    assert [d["id"] for d in hits["datasets"]] == ["bengbu_51080"]
    assert hits["source"] == "local" and hits["catalogue_generated_at"]

    # store empty + token missing: the caller sees the same error as before
    store.unlink()

    class NoToken:
        def catalogue(self, **_kwargs):
            raise obs_access.ObsAccessError("missing_token")

    monkeypatch.setattr(obs_access, "Client", lambda *a, **k: NoToken())
    with pytest.raises(obs_access.ObsAccessError) as caught:
        obs_access.search_catalogue(q="bengbu")
    assert caught.value.code == "missing_token"


def test_stamp_inventory_pins_catalogue_facts_and_flags_unknown_ids():
    catalogue = {"datasets": _RECORDS}
    inventory = {"items": [
        {"id": "obs", "status": "missing", "chosen_source": "bengbu_51080", "acceptable_sources": [],
         "needs_user": True, "agent_resolvable": False},
        {"id": "forcing", "status": "missing", "chosen_source": None,
         "acceptable_sources": ["cmfd_huai_daily_025 (manual, 0.98 GB)"]},
        {"id": "dem", "status": "missing", "chosen_source": "some free text",
         "acceptable_sources": ["user provides"]},
        {"id": "made", "status": "missing", "chosen_source": None, "acceptable_sources": ["produced by s1"]},
    ]}
    assert obs_access.stamp_inventory(inventory, catalogue=catalogue) == []
    obs, forcing, dem, made = inventory["items"]
    assert obs["dataset_id"] == "bengbu_51080" and obs["delivery"] == "served"
    assert obs["status"] == "resolved" and obs["needs_user"] is False
    assert obs["catalogue"]["point"] == [32.93, 117.38]
    assert "dataset_id" not in forcing  # an alternative is not a user/agent selection
    assert "dataset_id" not in dem and dem["status"] == "missing"
    assert "dataset_id" not in made

    bad = {"items": [{"id": "x", "status": "missing", "dataset_id": "nope_123"}]}
    errors = obs_access.stamp_inventory(bad, catalogue=catalogue)
    assert len(errors) == 1 and "nope_123" in errors[0]
    # no catalogue copy at all: nothing is invented, nothing is rejected
    assert obs_access.stamp_inventory(bad, catalogue={"datasets": []})

    # a whole-product parent is refused with its subsets named; a child id is accepted
    parent = {"items": [{"id": "f", "status": "missing", "chosen_source": "cmfd_china_daily_010"}]}
    errors = obs_access.stamp_inventory(parent, catalogue=catalogue)
    assert len(errors) == 1 and "cmfd_huai_daily_025" in errors[0] and "estimate_clip" in errors[0]
    child = {"items": [{"id": "p80", "status": "missing", "dataset_id": "cmfd_china_daily_010__prec_1980"}]}
    assert obs_access.stamp_inventory(child, catalogue=catalogue)  # parent existence is not child proof


def test_stamp_inventory_matches_display_names_to_a_unique_id():
    catalogue = {"datasets": [*_RECORDS,
                              {"id": "avhrr_landcover", "name": "AVHRR 1km land cover", "delivery": "manual"},
                              {"id": "hwsd_china", "delivery": "manual"},
                              {"id": "hwsd_china_raster", "delivery": "manual"}]}
    inventory = {"items": [
        {"id": "lc", "status": "missing", "chosen_source": "AVHRR_1km_LANDCOVER_1981_1994"},
        {"id": "soil", "status": "missing", "chosen_source": "HWSD China soil (HWSD_RASTER/hwsd.bil)"},
        {"id": "cmfd_huai_daily_025", "status": "missing", "chosen_source": "GeoForge Database (manual)"},
    ]}
    assert obs_access.stamp_inventory(inventory, catalogue=catalogue) == []
    assert inventory["items"][2]["dataset_id"] == "cmfd_huai_daily_025"     # named after the dataset
    assert inventory["items"][0]["dataset_id"] == "avhrr_landcover"
    # both hwsd_china and hwsd_china_raster fit; the more specific one covers the other
    assert inventory["items"][1]["dataset_id"] == "hwsd_china_raster"
    ambiguous = {"items": [{"id": "x", "status": "missing", "chosen_source": "cmfd china daily huai"}]}
    obs_access.stamp_inventory(ambiguous, catalogue=catalogue)
    assert "dataset_id" not in ambiguous["items"][0]      # two unrelated fits: leave it alone


def test_manual_handoff_message_names_the_file_inside_the_share():
    text = obs_access.manual_handoff_message({
        "name": "CMFD prec 1980", "size": 390000000, "baidu_pwd": "ab12",
        "path_in_share": "daily/prec/prec_1980.nc"})
    assert "371.93 MB" in text and "ab12" in text and "daily/prec/prec_1980.nc" in text
    assert "not required" in obs_access.manual_handoff_message({"dataset_id": "x"})



def test_mac_token_lives_in_a_private_file_and_migrates_from_keychain(tmp_path, monkeypatch):
    # The conftest stubs get_secret for isolation; exercise the macOS path directly.
    from kiss_cli import secret_store
    monkeypatch.setattr(secret_store, "_file_path",
                        lambda service, account: tmp_path / "secrets" / f"{service}.{account}")
    reads = {"n": 0}

    def fake_mac_get(service, account):
        reads["n"] += 1
        return "legacy-token"

    monkeypatch.setattr(secret_store, "_mac_get", fake_mac_get)
    # first read: the Keychain is consulted once and the value is copied to the file
    assert secret_store._mac_get_migrating("svc", "acct") == "legacy-token"
    assert reads["n"] == 1
    assert secret_store._mac_get_migrating("svc", "acct") == "legacy-token"
    assert reads["n"] == 1                                    # never again
    token_file = tmp_path / "secrets" / "svc.acct"
    assert oct(token_file.stat().st_mode & 0o777) == "0o600"
    assert oct(token_file.parent.stat().st_mode & 0o777) == "0o700"
    secret_store._file_set("svc", "acct", "new-token")
    assert secret_store._mac_get_migrating("svc", "acct") == "new-token"
    secret_store._file_delete("svc", "acct")
    assert not token_file.exists()



def test_study_hint_requires_grid_check_before_selecting_regional_candidate():
    block = obs_access.study_hint_block(
        [{"id": "cmfd_huai", "name": "Huai forcing", "delivery": "manual"}], "Huai")
    assert "not by model grid" in block
    assert "bbox filtering does not clip a file" in block
    assert "ask the user to choose" in block


def test_search_distinguishes_coverage_from_download_granularity():
    records = [
        {"id": "a_partial", "bbox": [70, 15, 140, 55], "start_date": "1989", "end_date": "1989"},
        {"id": "b_full", "bbox": [70, 15, 140, 55], "start_date": "1980", "end_date": "2000", "delivery": "manual"},
        {"id": "c_unknown"},
    ]
    result = obs_access.local_search(records, bbox=[117.25, 32.75, 117.5, 33], start="1989", end="1990")
    assert [r["id"] for r in result["datasets"]] == ["b_full", "c_unknown", "a_partial"]
    full, unknown, partial = [r["match"] for r in result["datasets"]]
    assert full["status"] == "covered" and full["requires_local_extraction"]
    assert unknown["status"] == "unknown" and partial["status"] == "insufficient"
    assert "match" not in records[0]  # shared cached JSON must not be mutated


@pytest.mark.parametrize("kwargs", [{"bbox": "broken"}, {"bbox": "nan,0,1,1"},
                                  {"start": "1990-02-31"}, {"start": "1991", "end": "1990"}])
def test_search_rejects_invalid_filters_even_for_empty_catalogue(kwargs):
    with pytest.raises(ValueError):
        obs_access.local_search([], **kwargs)


def test_month_filter_uses_real_last_day():
    assert obs_access._iso("2000-02", end=True) == "2000-02-29"
    assert obs_access._iso("1999-02", end=True) == "1999-02-28"


def test_study_hint_lists_matching_records_and_prefers_subsets():
    records = [*_RECORDS, {"id": "china_gaugeflux_huaihe", "name": "Huai River gauge fluxes",
                           "dataset_kind": "gauge", "delivery": "served",
                           "spatial_coverage": "China — 淮河 (Huai River)"}]
    goal = "请用 VIC 模拟中国淮河蚌埠水文站（51080）1980–1990 年的日径流"
    terms = dict(obs_access.study_terms(goal))
    assert "51080" in terms and "淮河" in terms and "bengbu" in terms and "huai" in terms
    assert "1980" not in terms
    ids = [d["id"] for d in obs_access.study_matches(records, goal)]
    assert ids[0] == "bengbu_51080"                                   # station id is decisive
    assert "china_gaugeflux_huaihe" in ids                            # matched through 淮河
    assert ids.index("cmfd_huai_daily_025") < ids.index("cmfd_china_daily_010")   # subset first
    block = obs_access.study_hint_block(records, goal)
    assert "AVAILABLE FOR THIS STUDY" in block and "manual" in block and "not a dead end" in block
    assert obs_access.study_hint_block(records, "") == ""
@pytest.mark.parametrize('variables', ['prec,temp', ' TEMP,prec,prec ', ['prec', 'temp']])
def test_multiple_variables_share_list_semantics_and_partial_matches_are_not_proof(variables):
    record = {'id': 'forcing', 'variables': ['prec', {'name': 'temp', 'canonical': 'air_temperature'}]}
    result = obs_access.local_search([record], variable=variables)
    assert result['total'] == 1
    assert result['datasets'][0]['match']['checks']['variables'] == 'covered'
    assert obs_access.local_search([record], variable='air_temperature,prec')['total'] == 1
    partial = obs_access.local_search([record], variable='pre')
    assert partial['total'] == 1 and partial['datasets'][0]['match']['status'] == 'unknown'
    assert obs_access.local_search([record], variable='prec,wind')['total'] == 0
