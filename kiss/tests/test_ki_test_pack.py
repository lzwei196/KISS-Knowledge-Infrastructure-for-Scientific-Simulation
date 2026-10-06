"""A complete byte manifest must not pass when input delivery is incomplete."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "verify_ki_test_pack", Path(__file__).resolve().parents[2] / "tools/verify_ki_test_pack.py")
verifier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(verifier)


def pack(root):
    (root / "inputs").mkdir()
    (root / "inputs/weather.dat").write_bytes(b"real fixture bytes\n")
    row = {"path": "inputs/weather.dat", "bytes": 19,
           "sha256": hashlib.sha256(b"real fixture bytes\n").hexdigest()}
    # Compute actual bytes rather than let a fixture typo hide a verifier failure.
    row["bytes"] = (root / row["path"]).stat().st_size
    manifest = {"schema_version": 1, "members": [row],
                "excluded_self_references": ["member-manifest.json", "SHA256SUMS.txt"]}
    save(root, manifest)
    return manifest


def save(root, manifest):
    (root / "member-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_intact_pack_only_proves_bytes(tmp_path):
    pack(tmp_path)
    result = verifier.verify(tmp_path)
    assert result["status"] == "PASS" and result["checked_members"] == 1
    assert result["scientific_validity"] == "NOT_CHECKED" and result["native_run"] == "NOT_RUN"


@pytest.mark.parametrize("change", ["missing", "truncated", "same_size_changed", "extra"])
def test_incomplete_or_changed_delivery_fails(tmp_path, change):
    pack(tmp_path)
    path = tmp_path / "inputs/weather.dat"
    if change == "missing":
        path.unlink()
    elif change == "truncated":
        path.write_bytes(b"partial")
    elif change == "same_size_changed":
        path.write_bytes(b"x" * path.stat().st_size)
    else:
        (tmp_path / "unlisted.dat").write_bytes(b"extra")
    assert verifier.verify(tmp_path)["status"] == "FAIL"


@pytest.mark.parametrize("bad", ["../outside", "D:/outside", "inputs\\weather.dat", "inputs/./weather.dat", "inputs/weather.dat."])
def test_nonportable_manifest_paths_fail(tmp_path, bad):
    manifest = pack(tmp_path)
    manifest["members"][0]["path"] = bad
    save(tmp_path, manifest)
    assert verifier.verify(tmp_path)["status"] == "FAIL"


def test_case_collisions_and_arbitrary_exclusions_fail(tmp_path):
    manifest = pack(tmp_path)
    manifest["members"].append({**manifest["members"][0], "path": "INPUTS/WEATHER.DAT"})
    save(tmp_path, manifest)
    assert verifier.verify(tmp_path)["status"] == "FAIL"
    manifest["members"].pop()
    manifest["excluded_self_references"].append("forcing.nc")
    save(tmp_path, manifest)
    assert verifier.verify(tmp_path)["status"] == "FAIL"


@pytest.mark.parametrize("schema", [False, 2, "1"])
def test_unknown_or_malformed_schema_fails(tmp_path, schema):
    manifest = pack(tmp_path)
    manifest["schema_version"] = schema
    save(tmp_path, manifest)
    assert verifier.verify(tmp_path)["status"] == "FAIL"
