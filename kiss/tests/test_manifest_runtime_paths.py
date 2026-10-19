"""A portable path opt-in is explicit and preserves legacy recipe identities."""
import json

import pytest
import yaml

from kiss_cli.manifest import Manifest, document, validate_runtime_paths


DECLARATION = {"version": 1, "mode": "role_tokens"}
INVALID = [
    True, False, 1, "role_tokens", [], [DECLARATION], {},
    {"version": 1}, {"mode": "role_tokens"},
    {**DECLARATION, "allow_execution": True},
    {"version": True, "mode": "role_tokens"},
    {"version": False, "mode": "role_tokens"},
    {"version": 1.0, "mode": "role_tokens"},
    {"version": "1", "mode": "role_tokens"},
    {"version": None, "mode": "role_tokens"},
    {"version": 0, "mode": "role_tokens"},
    {"version": 2, "mode": "role_tokens"},
    {"version": 1, "mode": "auto"},
    {"version": 1, "mode": "ROLE_TOKENS"},
    {"version": 1, "mode": None},
    {"version": 1, "mode": True},
    {"version": 1, "mode": ["role_tokens"]},
]


def _load(tmp_path, **extra):
    path = tmp_path / "kiss.yaml"
    path.write_text(yaml.safe_dump({"kiss_manifest_version": 1, "model": "Fixture", **extra}),
                    encoding="utf-8")
    return Manifest.load(path)


def test_absent_and_null_preserve_exact_legacy_canonical_bytes(tmp_path):
    # This is the pre-opt-in default document, including its existing key order.
    legacy = {"model": "Fixture", "binary_type": "", "r_package": None,
        "native_probe": None, "julia_package": None, "octave_package": None,
        "python_script": None, "verified": "unverified", "install_dir": "",
        "depends_on": [], "acquire": None, "python_deps": [], "system_deps": [],
        "data": [], "reference_case": None, "startup_marker": "", "notes": "", "agent_hint": ""}
    expected = json.dumps(legacy, separators=(",", ":")).encode()
    for man in (Manifest("Fixture"), Manifest("Fixture", runtime_paths=None),
                _load(tmp_path), _load(tmp_path, runtime_paths=None)):
        assert man.runtime_paths is None
        assert json.dumps(document(man), separators=(",", ":")).encode() == expected


def test_declared_projection_roundtrips_without_granting_readiness(tmp_path):
    direct = Manifest("Fixture", runtime_paths=DECLARATION)
    loaded = _load(tmp_path, runtime_paths=DECLARATION)
    assert document(direct) == document(loaded)
    assert document(loaded)["runtime_paths"] == DECLARATION
    assert loaded.verified == "unverified" and not loaded.trustworthy
    assert loaded.acquire is None and loaded.reference_case is None


def test_contract_is_copied_at_construction_and_canonicalization():
    supplied = dict(DECLARATION)
    man = Manifest("Fixture", runtime_paths=supplied)
    supplied["mode"] = "unsupported"
    assert man.runtime_paths == DECLARATION
    saved = document(man)
    saved["runtime_paths"]["mode"] = "unsupported"
    assert man.runtime_paths == DECLARATION
    assert validate_runtime_paths(None) is None


@pytest.mark.parametrize("declaration", INVALID)
def test_load_rejects_unsupported_projection_contract(tmp_path, declaration):
    with pytest.raises(ValueError, match="runtime_paths"):
        _load(tmp_path, runtime_paths=declaration)


@pytest.mark.parametrize("declaration", INVALID)
def test_direct_constructor_rejects_unsupported_projection_contract(declaration):
    with pytest.raises(ValueError, match="runtime_paths"):
        Manifest("Fixture", runtime_paths=declaration)


@pytest.mark.parametrize("declaration", INVALID)
def test_document_rejects_a_contract_changed_after_construction(declaration):
    man = Manifest("Fixture", runtime_paths=DECLARATION)
    man.runtime_paths = declaration
    with pytest.raises(ValueError, match="runtime_paths"):
        document(man)


def test_document_rechecks_in_place_mutation():
    man = Manifest("Fixture", runtime_paths=DECLARATION)
    man.runtime_paths["version"] = True
    with pytest.raises(ValueError, match="runtime_paths.version"):
        document(man)
