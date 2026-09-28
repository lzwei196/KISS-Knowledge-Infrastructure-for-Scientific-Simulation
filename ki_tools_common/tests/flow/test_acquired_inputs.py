"""Acquired-input evidence: local integrity is not suitability or freshness.

These small byte fixtures exercise the public receipt-inspection interface;
they are not scientific data validation or network download tests.
"""
from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from ki_tools_common.flow import receipts


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "host-keys"))
    root = tmp_path / "project"
    root.mkdir()
    return root


def _item():
    return {
        "id": "forcing", "dataset_id": "weather", "chosen_source": "source-a",
        "requirements": {
            "bbox": [110, 30, 111, 31], "start": "2000-01-01",
            "end": "2000-01-02", "variables": ["prec"],
        },
    }


def _record(project, *, item=None, raw_suffix=".zip", legacy=False, no_files=False):
    item = _item() if item is None else item
    raw = project / "transport" / f"weather{raw_suffix}"
    output = project / "inputs" / "weather.dat"
    raw.parent.mkdir(exist_ok=True)
    output.parent.mkdir(exist_ok=True)
    raw.write_bytes(b"original transport bytes")
    output.write_bytes(b"original extracted bytes")
    path = receipts.record_download(
        project, item_id=item["id"], source="GeoForge Database catalogue",
        request_url="https://example.test/weather", http_status=200,
        raw_files=[] if no_files else [raw],
        processed_files=[] if no_files else [output],
        transform_tool="verified_zip_extract", approval_sha256="old-approval",
        plan_step_id="download", inventory_item=None if legacy else item,
    )
    return path, raw, output


def _inspect(project, item=None, *, approval="new-approval"):
    return receipts.inspect_downloads(
        project, {"items": [_item() if item is None else item]},
        approval_sha256=approval,
    )


def _replace_signed(project, path, **fields):
    doc = json.loads(path.read_text())
    doc.update(fields)
    path.write_text(json.dumps(receipts.sign(project, doc)))


def _snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes()
            for p in root.rglob("*") if p.is_file()}


def test_exact_request_reuses_intact_input_across_approvals(project):
    path, _raw, _output = _record(project)
    result = receipts.find_download(project, _item(), approval_sha256="new-approval")
    assert result is not None and result.path == path
    assert result.request_match == "exact" and result.files == "intact"
    assert result.reusable and result.bound
    assert result.source_freshness == "unknown"
    assert result.scientific_validation == "not_assessed"
    assert receipts.find_download(project, _item(), source="another source") is None


def test_only_rename_matches_historical_fingerprint(project):
    path, _raw, _output = _record(project)
    renamed = {**_item(), "id": "weather_for_run"}
    assert receipts.find_download(project, renamed) is None
    result = receipts.find_download(project, renamed, recover=True)
    assert result is not None and result.path == path
    assert result.request_match == "renamed" and result.files == "intact"
    assert result.recoverable and not result.reusable
    assert not result.bound                     # host must explicitly issue the new binding
    assert result.receipt["item_id"] == "forcing"


@pytest.mark.parametrize("change", ["bbox", "period", "variables", "source"])
def test_rename_does_not_hide_changed_request(project, change):
    _record(project)
    changed = {**deepcopy(_item()), "id": "weather_for_run"}
    if change == "bbox":
        changed["requirements"]["bbox"] = [110, 30, 110.5, 30.5]  # narrower is not proof
    elif change == "period":
        changed["requirements"]["end"] = "2000-01-01"
    elif change == "variables":
        changed["requirements"]["variables"] = ["temp"]
    else:
        changed["chosen_source"] = "source-b"
    result, = _inspect(project, changed)
    assert result.request_match == "mismatch"
    assert not result.reusable and not result.recoverable and not result.bound
    assert receipts.find_download(project, changed, recover=True) is None


def test_missing_zip_can_be_explicitly_recovered_from_intact_extraction(project):
    path, raw, output = _record(project)
    raw.unlink()
    assert output.is_file()
    assert receipts.find_download(project, _item()) is None
    result = receipts.find_download(project, _item(), recover=True)
    assert result is not None and result.path == path
    assert result.files == "extracted_only" and result.recoverable
    assert not result.reusable and not result.bound


def test_changed_present_zip_cannot_be_recovered_as_missing(project):
    _path, raw, _output = _record(project)
    raw.write_bytes(b"changed transport bytes")
    result, = _inspect(project)
    assert result.files == "changed"
    assert not result.recoverable and not result.reusable and not result.bound
    assert receipts.find_download(project, _item(), recover=True) is None


def test_missing_nonarchive_is_not_transport_recovery(project):
    _path, raw, _output = _record(project, raw_suffix=".dat")
    raw.unlink()
    result, = _inspect(project)
    assert not result.recoverable and not result.reusable and not result.bound
    assert receipts.find_download(project, _item(), recover=True) is None


def test_existing_directory_is_not_a_missing_transport_zip(project):
    _path, raw, _output = _record(project)
    raw.unlink()
    raw.mkdir()
    result, = _inspect(project)
    assert result.files in {"unsafe", "changed"}
    assert not result.reusable and not result.recoverable and not result.bound
    assert receipts.find_download(project, _item(), recover=True) is None


def test_recovery_refuses_files_changed_after_inspection(project, monkeypatch):
    # This host integration is the inspection-to-issuance seam: a second hash
    # must not silently turn changed bytes into evidence for the old request.
    from kiss_cli import acquire

    path, raw, output = _record(project)
    original_receipt = path.read_bytes()
    raw.unlink()
    original_find = receipts.find_download

    def mutate_after_inspection(*args, **kwargs):
        found = original_find(*args, **kwargs)
        assert found is not None and found.files == "extracted_only"
        output.write_bytes(b"changed after the inspection")
        return found

    monkeypatch.setattr(receipts, "find_download", mutate_after_inspection)
    with pytest.raises(receipts.ReceiptError):
        acquire._rebind_existing(project, SimpleNamespace(receipts=receipts), _item(), "new-approval")
    assert path.read_bytes() == original_receipt


def test_same_item_recovery_preserves_verifiable_original_receipt(project):
    from kiss_cli import acquire

    path, raw, _output = _record(project)
    original = json.loads(path.read_text())
    raw.unlink()
    result = acquire._rebind_existing(
        project, SimpleNamespace(receipts=receipts), _item(), "new-approval",
    )
    assert result is not None and result["status"] == "done"
    recovered = json.loads(path.read_text())
    previous = recovered["recovery"]["previous_receipt"]
    assert previous == original and receipts.verify(project, previous)
    assert recovered["recovery"]["original_raw_files"] == original["raw_files"]
    assert recovered["raw_files"] == original["processed_files"]
    assert recovered["recovery"]["receipt_signature"] == original["signature"]["value"]


def test_changed_extracted_file_invalidates_intact_raw_archive(project):
    _path, _raw, output = _record(project)
    output.write_bytes(b"changed extraction")
    result, = _inspect(project)
    assert result.files == "changed"
    assert not result.reusable and not result.recoverable and not result.bound


def test_symlink_escape_is_not_intact_even_when_hash_matches(project):
    _path, raw, _output = _record(project)
    outside = project.parent / "outside.zip"
    outside.write_bytes(raw.read_bytes())
    raw.unlink()
    raw.symlink_to(outside)
    result, = _inspect(project)
    assert result.files == "unsafe"
    assert not result.reusable and not result.recoverable and not result.bound


def test_missing_zip_cannot_promote_extraction_outside_project(project):
    _path, raw, output = _record(project)
    outside = project.parent / "outside.dat"
    outside.write_bytes(output.read_bytes())
    output.unlink()
    output.symlink_to(outside)
    raw.unlink()
    result, = _inspect(project)
    assert result.files == "unsafe"
    assert receipts.find_download(project, _item(), recover=True) is None


def test_signed_parent_traversal_is_rejected(project):
    path, _raw, _output = _record(project)
    outside = project.parent / "outside.dat"
    outside.write_bytes(b"outside")
    _replace_signed(project, path, raw_files=[{
        "path": "../outside.dat", "sha256": receipts.sha256_file(outside), "bytes": 7,
    }])
    result, = _inspect(project)
    assert result.files == "unsafe"
    assert not result.reusable and not result.recoverable and not result.bound


@pytest.mark.parametrize("no_files", [False, True])
def test_current_approval_legacy_evidence_is_not_reusable_provenance(project, no_files):
    _record(project, legacy=True, no_files=no_files)
    result, = _inspect(project, approval="old-approval")
    assert result.request_match == "unknown"
    assert result.bound and not result.reusable and not result.recoverable
    assert receipts.find_download(project, _item(), approval_sha256="old-approval", recover=True) is None
    # Preserve the existing web/older Desktop final-evidence contract.
    ev = receipts.evidence(
        project, {"steps": []}, {"signature": {"value": "old-approval"}},
        inventory={"items": [_item()]},
    )
    assert ev["downloads_bound"] == 1
    later, = _inspect(project, approval="new-approval")
    assert not later.bound and not later.reusable and not later.recoverable


def test_current_approval_legacy_files_are_still_hash_checked(project):
    _path, raw, _output = _record(project, legacy=True)
    raw.write_bytes(b"changed")
    result, = _inspect(project, approval="old-approval")
    assert result.files == "changed" and not result.bound
    ev = receipts.evidence(
        project, {"steps": []}, {"signature": {"value": "old-approval"}},
        inventory={"items": [_item()]},
    )
    assert ev["downloads_bound"] == 0


@pytest.mark.parametrize("raw_files", ["not-a-list", ["not-an-entry"]])
def test_malformed_file_entries_fail_closed(project, raw_files):
    path, _raw, _output = _record(project)
    _replace_signed(project, path, raw_files=raw_files)
    result, = _inspect(project)
    assert result.files == "malformed"
    assert result.reason and not result.bound and not result.reusable and not result.recoverable


@pytest.mark.parametrize("contents", ["not json", "[]", "null"])
def test_invalid_receipt_document_is_rejected_without_crashing(project, contents):
    path, _raw, _output = _record(project)
    path.write_text(contents)
    result, = _inspect(project)
    assert result.reason and not result.bound and not result.reusable and not result.recoverable
    ev = receipts.evidence(project, {"steps": []}, {"signature": {"value": "old-approval"}})
    assert ev["downloads_bound"] == 0 and ev["rejected_receipts"]


def test_valid_signature_does_not_make_wrong_kind_a_download(project):
    path, _raw, _output = _record(project)
    _replace_signed(project, path, kind="run")
    result, = _inspect(project, approval="old-approval")
    assert result.reason and not result.bound and not result.reusable and not result.recoverable
    ev = receipts.evidence(
        project, {"steps": []}, {"signature": {"value": "old-approval"}},
        inventory={"items": [_item()]},
    )
    assert ev["downloads_bound"] == 0 and ev["rejected_receipts"]


def test_unverified_receipt_is_never_reusable(project):
    path, _raw, _output = _record(project)
    doc = json.loads(path.read_text())
    doc["request_url"] = "https://example.test/changed"
    path.write_text(json.dumps(doc))
    result, = _inspect(project)
    assert result.reason and not result.bound and not result.reusable and not result.recoverable


def test_inspection_never_creates_keys_or_rewrites_evidence(project):
    assert receipts.inspect_downloads(project, {"items": [_item()]}) == []
    assert not list(project.iterdir())
    assert not (project.parent / "host-keys").exists()
    _path, raw, _output = _record(project)
    raw.unlink()                              # even recoverable evidence is read-only
    before = _snapshot(project.parent)
    assert receipts.find_download(project, _item(), recover=True) is not None
    receipts.inspect_downloads(project, {"items": [_item()]}, approval_sha256="new-approval")
    assert _snapshot(project.parent) == before
