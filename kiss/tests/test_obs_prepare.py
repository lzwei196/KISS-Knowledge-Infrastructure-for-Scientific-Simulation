"""Offline contract controls; no fixture claims authenticated server acceptance."""
from __future__ import annotations

import json
from urllib.error import HTTPError
import io

import pytest

from kiss_cli import obs_access, obs_prepare as prep
from .test_obs_access import Opener, json_response


BODY = {"model": "shaw", "source": "cmfd", "mode": "daily", "lat": 47.43,
        "lon": 126.97, "start": "2003-10-01", "end": "2004-05-31"}
ESTIMATE = {"contract_version": "ki_prepare/1", "preparable": True,
            "model": "shaw", "source": "cmfd", "mode": "daily", "ki_version": "synthetic-v1",
            "source_cadence": "3-hourly", "tool_hash": "a" * 64,
            "transforms": [{"operation": "daily aggregation", "input_units": {"temp": "K"},
                            "output_units": {"temp": "C"}}],
            "outputs": [{"name": "synthetic.wea", "role": "weather", "format": "SHAW daily",
                         "columns": "JD JYR TMAX TMIN TDEW WIND PRECIP SOLAR"}], "blockers": []}


def client(*responses):
    return obs_access.Client(opener=Opener(*responses), token_getter=lambda: "host-owned-test-token")


def test_estimate_posts_explicit_request_only_and_never_creates_a_job():
    c = client(json_response(ESTIMATE))
    result = prep.estimate(BODY, client=c)
    assert result["status"] == "estimate_available" and result["plan_available"]
    assert result["server_estimate"]["source_cadence"] == "3-hourly"
    assert all(result[key] is False for key in ("acquisition_approved", "input_ready", "model_ready"))
    assert "acquisition_id" not in result and "authorization" not in result
    assert len(c._provided_opener.requests) == 1
    request = c._provided_opener.requests[0][0]
    assert request.method == "POST" and request.full_url.endswith("/prepare/estimate")
    assert json.loads(request.data) == BODY
    assert request.get_header("Authorization") == "Bearer host-owned-test-token"
    assert "host-owned-test-token" not in json.dumps(result)


@pytest.mark.parametrize("change", [
    {"source": None}, {"mode": None}, {"model": "unknown"}, {"start": None}, {"end": "2003-02-30"},
    {"start": "2004-06-01"}, {"start": "2003-10-01T00:00:00"}, {"lat": True},
    {"lat": float("nan")}, {"lon": float("inf")}, {"lon": 181}, {"lat": -91},
    {"lat": "47.43"}, {"utc_offset": 1.5}, {"utc_offset": True}, {"utc_offset": 15},
    {"ki_version": {"hash": "x"}}, {"ki_step": "../private"}, {"bbox": [1, 2, 3, 4]},
    {"token": "not-allowed"}, {"dataset_id": "raw-only"}, {"mode": "hourly; command"},
])
def test_invalid_or_implicit_requests_do_not_touch_transport(change):
    c = client()
    with pytest.raises(ValueError):
        prep.estimate({**BODY, **change}, client=c)
    assert not c._provided_opener.requests


def test_site_and_vic_grid_requests_and_explicit_unsupported_combo_are_not_rewritten():
    assert prep.request_body({**BODY, "model": "crhm", "source": "nasa_power", "mode": "hourly"})["mode"] == "hourly"
    unsupported = {**BODY, "mode": "hourly"}
    c = client(json_response({**ESTIMATE, "mode": "hourly", "preparable": False,
                             "reason": "unsupported_combination", "delivery_fallback": "raw subset plus local conversion"}))
    result = prep.estimate(unsupported, client=c)
    assert result["status"] == "blocked" and not result["plan_available"]
    assert json.loads(c._provided_opener.requests[0][0].data)["source"] == "cmfd"
    assert len(c._provided_opener.requests) == 1
    grid = {k: v for k, v in BODY.items() if k not in {"lat", "lon"}}
    grid.update(model="vic", mode="3-hourly", bbox=[115.25, 32.75, 115.75, 33.25], grid_res=0.25)
    assert prep.request_body(grid) == grid
    for change in ({"bbox": [1, 2, 1, 3]}, {"bbox": [1, 2, 3]}, {"grid_res": 0},
                   {"grid_res": True}, {"lat": 47}, {"bbox": [1, 2, 3, float("nan")]},
                   {"bbox": [True, 2, 3, 4]}, {"bbox": [-181, 2, 3, 4]}):
        with pytest.raises(ValueError):
            prep.request_body({**grid, **change})


def test_server_blockers_win_over_preparable_true():
    result = prep.estimate(BODY, client=client(json_response({**ESTIMATE,
        "blockers": [{"code": "soil_grid_required", "message": "Build project soil and grid first"}]})))
    assert result["status"] == "blocked"
    assert not result["plan_available"]
    assert result["blockers"] == ["soil_grid_required: Build project soil and grid first"]


@pytest.mark.parametrize("change", [{"contract_version": "ki_prepare/2"},
                                   {"schema_version": "other/1"}])
def test_unknown_or_conflicting_contract_cannot_produce_supported_plan(change):
    result = prep.estimate(BODY, client=client(json_response({**ESTIMATE, **change})))
    assert result["status"] == "unsupported_contract" and not result["plan_available"]


def test_missing_contract_and_schema_version_alias():
    raw = {k: v for k, v in ESTIMATE.items() if k != "contract_version"}
    assert prep.estimate(BODY, client=client(json_response(raw)))["status"] == "unsupported_contract"
    assert prep.estimate(BODY, client=client(json_response({**raw, "schema_version": "ki_prepare/1"})))["status"] == "estimate_available"


@pytest.mark.parametrize("change", [
    {"model": "vic"}, {"source": "mswx"}, {"mode": "hourly"}, {"lat": 47.45},
    {"start": "2003-01-01"}, {"request": {"lon": 125.23}}, {"request": "private"},
    {"preparable": "true"}, {"blockers": "none"}, {"outputs": {}},
    {"transforms": [True]}, {"tool_hash": "not a hash"}, {"estimated_output_bytes": True},
])
def test_contradictory_identity_and_malformed_response_fail_closed(change):
    result = prep.estimate(BODY, client=client(json_response({**ESTIMATE, **change})))
    assert result["status"] == "estimate_failed" and not result["plan_available"]
    assert result["failure"]["code"] == "invalid_response"


def test_pinned_revision_echo_is_verified_and_unknown_defaults_not_invented():
    c = client(json_response(ESTIMATE))
    result = prep.estimate({**BODY, "ki_version": "different-v2"}, client=c)
    assert result["status"] == "estimate_failed"
    assert "ki_version" not in prep.request_body(BODY)
    assert prep.request_body({**BODY, "ki_version": None}) == BODY


def test_nested_private_fields_and_private_prose_are_not_saved_or_returned(tmp_path):
    raw = {**ESTIMATE, "token": "SECRET-TOP", "source_path": "/mnt/SECRET-TOP",
           "outputs": [{"role": "weather", "name": "safe.wea", "url": "https://secret.invalid/SECRET-NESTED",
                        "description": "Created from /mnt/private/SECRET-PROSE", "extra": {"token": "SECRET-NESTED"},
                        "units": {"precip": "mm", "password": "SECRET-UNITS"}}],
           "blockers": [{"code": "source_unavailable", "message": "Read C:\\private\\SECRET-PATH",
                         "source_path": "/mnt/SECRET-NESTED"}],
           "reason": "See https://private.invalid/SECRET-URL", "internal": {"token": "SECRET-INTERNAL"}}
    result = prep.record_estimate(tmp_path, BODY, client=client(json_response(raw)))
    public = json.dumps(result)
    assert "SECRET" not in public and "private.invalid" not in public
    path = tmp_path / ".geoforge" / "preparations" / (result["preparation_id"] + ".json")
    assert "SECRET" not in path.read_text(encoding="utf-8")
    assert result["server_estimate"]["outputs"][0]["units"] == {"precip": "mm"}
    restored = prep.list_estimates(tmp_path)
    assert len(restored) == 1 and restored[0]["status"] == "blocked"


def test_missing_token_and_http_failure_have_safe_nonready_results():
    c = obs_access.Client(opener=Opener(), token_getter=lambda: "")
    result = prep.estimate(BODY, client=c)
    assert result["failure"]["code"] == "missing_token" and not c._provided_opener.requests
    c = client(HTTPError("https://secret.invalid", 500, "SECRET", {}, io.BytesIO(b"SECRET")))
    result = prep.estimate(BODY, client=c)
    assert result["failure"] == {"stage": "estimate", "code": "server_unavailable", "http_status": 500}
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("change", [{"ki_version": "v2"}, {"source": "nasa_power"}, {"mode": "hourly"},
                                   {"lat": 47.44}, {"end": "2004-06-01"}, {"utc_offset": 8}])
def test_each_consuming_context_change_changes_request_fingerprint(change):
    baseline = prep.estimate(BODY, client=client(json_response(ESTIMATE)))
    result = prep.estimate({**BODY, **change}, client=client(json_response(ESTIMATE)))
    assert result["request_sha256"] != baseline["request_sha256"]


def test_persisted_records_are_not_trusted_approval_or_ready_state(tmp_path):
    result = prep.record_estimate(tmp_path, BODY, client=client(json_response(ESTIMATE)))
    path = tmp_path / ".geoforge" / "preparations" / (result["preparation_id"] + ".json")
    result.update(acquisition_approved=True, input_ready=True, model_ready=True, token="SECRET")
    path.write_text(json.dumps(result), encoding="utf-8")
    restored = prep.list_estimates(tmp_path)[0]
    assert all(restored[k] is False for k in ("acquisition_approved", "input_ready", "model_ready"))
    assert "SECRET" not in json.dumps(restored)
    result["request"]["lat"] = 0
    path.write_text(json.dumps(result), encoding="utf-8")
    assert prep.list_estimates(tmp_path) == []


def test_reading_empty_project_does_not_create_evidence_directory(tmp_path):
    assert prep.list_estimates(tmp_path) == []
    assert not (tmp_path / ".geoforge").exists()


@pytest.mark.parametrize("omit", ["source_cadence", "outputs"])
def test_preparable_boolean_alone_does_not_establish_an_available_plan(omit):
    raw = {key: value for key, value in ESTIMATE.items() if key != omit}
    result = prep.estimate(BODY, client=client(json_response(raw)))
    assert result["status"] == "blocked" and not result["plan_available"]
    assert "incomplete_preparation_plan" in result["blockers"]


@pytest.mark.parametrize("summary_change,expected_status", [
    ({"blockers": ["soil_grid_required"]}, "blocked"),
    ({"schema_version": "ki_prepare/2"}, "unsupported_contract"),
    ({"source_cadence": ""}, "blocked"),
])
def test_record_classification_is_recomputed_from_summary(tmp_path, summary_change, expected_status):
    result = prep.record_estimate(tmp_path, BODY, client=client(json_response(ESTIMATE)))
    result["server_estimate"].update(summary_change)
    result.update(status="estimate_available", blockers=[], plan_available=True)
    path = tmp_path / ".geoforge" / "preparations" / (result["preparation_id"] + ".json")
    path.write_text(json.dumps(result), encoding="utf-8")
    restored = prep.list_estimates(tmp_path)[0]
    assert restored["status"] == expected_status and not restored["plan_available"]
    assert restored["blockers"]


def test_failed_record_keeps_only_derived_message_and_safe_http_status(tmp_path):
    c = client(HTTPError("https://secret.invalid", 500, "SECRET", {}, io.BytesIO(b"SECRET")))
    result = prep.record_estimate(tmp_path, BODY, client=c)
    result["message"] = "SECRET"
    result["failure"]["private"] = "SECRET"
    path = tmp_path / ".geoforge" / "preparations" / (result["preparation_id"] + ".json")
    path.write_text(json.dumps(result), encoding="utf-8")
    restored = prep.list_estimates(tmp_path)[0]
    assert restored["failure"] == {"stage": "estimate", "code": "server_unavailable", "http_status": 500}
    assert restored["message"] == obs_access.ERROR_MESSAGES["server_unavailable"]
    assert "SECRET" not in json.dumps(restored)
