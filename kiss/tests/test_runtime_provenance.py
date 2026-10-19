"""Build labels are retained observations, never replacement readiness proof."""
from copy import deepcopy
from pathlib import Path

import pytest

from kiss_cli import runtime_context, runtime_provenance as rp


@pytest.fixture(autouse=True)
def fresh_observation():
    rp._startup.cache_clear()
    yield
    rp._startup.cache_clear()


def context(digest="a" * 64, scheme="python-application-tree-sha256-v1"):
    return {"schema_version": 1, "application": {"name": "GeoForge", "version": "0.6.60",
        "version_source": "source-project-metadata", "build": {"scheme": scheme, "sha256": digest}},
        "backend": {"kind": "native", "platform": "Windows", "machine": "AMD64"}}


def test_startup_build_is_frozen_and_returned_copies_cannot_relabel_it(monkeypatch):
    monkeypatch.setattr(runtime_context, "identity", lambda: {"kind": "native", "platform": "Windows", "machine": "AMD64"})
    monkeypatch.setattr(rp, "_source_build", lambda _: {"scheme": "python-application-tree-sha256-v1", "sha256": "a" * 64})
    old = rp.capture()
    monkeypatch.setattr(rp, "_source_build", lambda _: {"scheme": "python-application-tree-sha256-v1", "sha256": "b" * 64})
    old["application"]["build"]["sha256"] = "c" * 64
    assert rp.capture()["application"]["build"]["sha256"] == "a" * 64


def test_supervised_payload_does_not_claim_pure_app_or_copy_nonce(monkeypatch):
    monkeypatch.setattr(runtime_context, "identity", lambda: {
        "kind": "wsl", "platform": "Linux", "source_hash": "d" * 64,
        "distro": "Ubuntu", "user": "scientist", "workspace": "/home/scientist/work",
        "id": "runtime", "machine": "x86_64", "guest_path_identity": "f" * 64,
        "nonce": "PRIVATE", "settings": "PRIVATE", "guest_identity": "e" * 64})
    value = rp.capture()
    assert value["application"]["build"] == {"scheme": "supervised-portable-payload-sha256-v1", "sha256": "d" * 64}
    assert "PRIVATE" not in str(value) and "nonce" not in value["backend"]


@pytest.mark.parametrize("change", ["missing", "unknown_scheme", "bad_digest", "extra_secret", "version", "backend_control", "bool_schema", "incomplete_backend"])
def test_invalid_present_context_cannot_become_legacy_unknown(change):
    value = context()
    if change == "missing": del value["application"]
    elif change == "unknown_scheme": value["application"]["build"]["scheme"] = "guess"
    elif change == "bad_digest": value["application"]["build"]["sha256"] = "short"
    elif change == "extra_secret": value["backend"]["nonce"] = "PRIVATE"
    elif change == "version": value["application"]["version"] = "version\nINSTRUCTION"
    elif change == "bool_schema": value["schema_version"] = True
    elif change == "incomplete_backend": del value["backend"]["machine"]
    else: value["backend"]["workspace"] = "/tmp\nINSTRUCTION"
    with pytest.raises(ValueError): rp.validate(value)


def test_legacy_unknown_does_not_inherit_current_version_or_build():
    current = context()
    before = deepcopy(current)
    assert rp.compare(None, current)["build"] == "unknown"
    assert current == before


def test_comparison_is_scheme_aware_and_does_not_assert_execution():
    current = context()
    old = context("b" * 64)
    assert rp.compare(old, current) == {"build": "different", "backend": "same", "declared_version": "same",
        "reason": "observations_only_not_readiness_or_model_execution"}
    old["application"]["build"]["scheme"] = "frozen-executable-sha256-v1"
    assert rp.compare(old, current)["build"] == "unknown"


def test_source_metadata_is_exact_package_metadata_and_missing_stays_unknown(tmp_path):
    package = tmp_path / "kiss_cli"; package.mkdir()
    metadata = tmp_path / "pyproject.toml"
    assert rp._version(package) == (None, "unknown")
    metadata.write_text('[project]\nname="kiss-ki"\nversion="0.7.1"\n')
    assert rp._version(package) == ("0.7.1", "source-project-metadata")
    metadata.write_text('[project]\nname="unrelated"\nversion="99.0"\n')
    assert rp._version(package) == (None, "unknown")
    metadata.write_text('project = []\n')
    assert rp._version(package) == (None, "unknown")


def test_native_source_digest_changes_only_with_included_application_bytes(tmp_path, monkeypatch):
    import ki_tools_common
    package = tmp_path / "kiss_cli"; package.mkdir()
    common = tmp_path / "common"; common.mkdir()
    (package / "app.py").write_text("original")
    (common / "__init__.py").write_text("common")
    monkeypatch.setattr(ki_tools_common, "__file__", str(common / "__init__.py"))
    first = rp._source_build(package)
    tests = package / "tests"; tests.mkdir(); (tests / "secret.py").write_text("ignored")
    assert rp._source_build(package) == first
    (package / "app.py").write_text("changed!")
    assert rp._source_build(package) != first


def test_sidecar_transfers_declared_version_as_fingerprinted_source_metadata(tmp_path):
    from kiss_cli import linux_sidecar
    root = tmp_path / "source"
    for name, data in {
        "kiss/kiss_cli/cli.py": "# app", "kiss/manifests/M.yaml": "model: M",
        "ki_tools_common/ki_tools_common/__init__.py": "# shared",
        "models/M/SKILL.md": "# M",
        "kiss/pyproject.toml": '[project]\nname="kiss-ki"\nversion="0.6.60"\n',
    }.items():
        path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(data)
    first, rows, files = linux_sidecar.source_inventory(root, root / "models")
    assert files["kiss/pyproject.toml"] == root / "kiss/pyproject.toml"
    assert rows["kiss/pyproject.toml"]["sha256"]
    (root / "kiss/pyproject.toml").write_text('[project]\nname="kiss-ki"\nversion="0.6.61"\n')
    assert linux_sidecar.source_inventory(root, root / "models")[0] != first
