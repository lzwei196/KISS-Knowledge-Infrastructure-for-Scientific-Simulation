"""Retained files do not become a new download by fuzzy inventory-id matching."""
import copy

from kiss_cli import obs_access, obs_subset


def test_explicit_local_reuse_preserves_native_dataset_provenance_without_download(tmp_path, monkeypatch):
    raw = tmp_path / "inputs/soilTemp10cm_2022.csv"
    raw.parent.mkdir()
    raw.write_text("retained fixture bytes")
    item = {"id": "agrometeo_quebec_archive", "chosen_source": "existing_local",
            "acceptable_sources": ["existing_local"], "status": "ready",
            "local_paths": [str(raw)], "rationale": "Acquired earlier from agrometeo_quebec; inspect its retained receipt."}
    inventory = {"items": [item]}
    before = copy.deepcopy(inventory)
    monkeypatch.setattr(obs_subset, "prefer_clip", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no new delivery")))
    errors = obs_access.stamp_inventory(inventory, project=tmp_path, catalogue={"datasets": [
        {"id": "agrometeo_quebec", "delivery": "manual", "size": 123}]})
    assert errors == []
    assert inventory == before
    assert raw.read_text() == "retained fixture bytes"


def test_explicit_dataset_id_is_not_hidden_by_local_source_label(tmp_path):
    inventory = {"items": [{"id": "observations", "chosen_source": "existing_local",
                             "dataset_id": "unresolved_id", "status": "ready"}]}
    errors = obs_access.stamp_inventory(inventory, project=tmp_path,
                                       catalogue={"datasets": [{"id": "other", "delivery": "manual"}]})
    assert len(errors) == 1 and "not in the GeoForge Database" in errors[0]


def test_implicit_catalogue_selection_still_matches_dataset_names():
    inventory = {"items": [{"id": "agrometeo_quebec_archive", "status": "missing"}]}
    assert obs_access.stamp_inventory(inventory, catalogue={"datasets": [
        {"id": "agrometeo_quebec", "delivery": "manual", "size": 123}]}) == []
    assert inventory["items"][0]["dataset_id"] == "agrometeo_quebec"
    assert inventory["items"][0]["delivery"] == "manual"
