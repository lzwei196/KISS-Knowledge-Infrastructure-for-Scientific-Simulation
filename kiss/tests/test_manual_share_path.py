"""Offline acquisition regression for the server's manual share-path field.

All records and paths are synthetic. No database credentials or real share links.
"""
import json

import pytest

from kiss_cli import acquire, flowrun, obs_access, obs_subset
from kiss_cli import setup as setup_flow
from .test_acquisition_mixed_delivery import _approve, _review


@pytest.mark.parametrize(("preferred", "expected"), [
    (None, "synthetic/archive/database.sqlite"),
    ("preferred/path.sqlite", "preferred/path.sqlite"),
    ("", "synthetic/archive/database.sqlite"),
])
def test_server_manual_share_path_reaches_card_and_survives_recovery(
        tmp_path, monkeypatch, preferred, expected):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    project, fs, ki, approval = _review(tmp_path, monkeypatch, "subset", True)
    calls = []

    class OfflineManualTransport:
        def download(self, dataset_id, project):
            calls.append(dataset_id)
            assert dataset_id == "manual-yearbook"
            # Shape observed from the manual-delivery API, with synthetic values.
            response = {"served": False, "size": 1234,
                        "baidu_url": "https://example.invalid/manual-fixture",
                        "baidu_remote_path": "synthetic/archive/database.sqlite",
                        "reason": "manual", "instructions": "Offline fixture"}
            if preferred is not None:
                response["path_in_share"] = preferred
            return response

    monkeypatch.setattr(obs_access, "Client", OfflineManualTransport)
    monkeypatch.setattr(obs_subset, "advance_approved",
                        lambda *args, **kwargs: {"status": "running", "receipt": None})
    monkeypatch.setattr(flowrun, "ACQ_POLL_SECONDS", 0)
    _approve(project, ki, approval)

    card = setup_flow.request(project)
    assert card["id"] == acquire.MANUAL_REQUEST_ID
    assert card["rows"][0]["path_in_share"] == expected
    assert f"inside the share, download only: {expected}" in card["message"]
    target = project / "inputs/observations/manual-yearbook"
    assert card["rows"][0]["expected_path"] == str(target.resolve())
    assert not target.exists(), "A manual instruction must not fabricate downloaded data"
    cached = json.loads((project / acquire.MANUAL_DETAILS_FILE).read_text(encoding="utf-8"))
    assert cached["items"]["manual"]["path_in_share"] == expected

    setup_flow.clear_request(project)
    assert flowrun.poll_acquisition(project, setup_ok=True, automatic_only=True) == "waiting"
    restored = setup_flow.request(project)
    assert restored["rows"] == card["rows"]
    assert expected in restored["message"]
    assert calls == ["manual-yearbook"], "Recovery must reuse the approved private instructions"
    state = acquire.status(project)
    assert state["items"]["manual"]["status"] == "waiting"
    assert expected not in json.dumps(state), "Share details must stay out of public acquisition status"
