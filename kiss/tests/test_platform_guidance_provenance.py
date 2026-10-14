"""Exact official guidance inputs do not imply trust in a whole source KI."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import ki_guard, ki_updates, published_acceptance
from kiss_cli import platform_guidance_provenance as proof


def git_object(root, kind, body):
    raw = kind.encode() + b" " + str(len(body)).encode() + b"\0" + body
    oid = hashlib.sha1(raw).hexdigest()
    path = root / ".git/objects" / oid[:2] / oid[2:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(zlib.compress(raw))
    return oid


def git_tree(root, files):
    nested = {}
    for name, value in files.items():
        current = nested
        parts = name.split("/")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value

    def encode(tree):
        entries = []
        for name, value in sorted(tree.items()):
            if isinstance(value, dict):
                mode, oid = b"40000", encode(value)
            else:
                mode, body = value if isinstance(value, tuple) else (b"100644", value)
                oid = git_object(root, "blob", body)
            entries.append(mode + b" " + name.encode() + b"\0" + bytes.fromhex(oid))
        return git_object(root, "tree", b"".join(entries))
    return encode(nested)


def overlay_for(root, paths):
    def record(name):
        body = (root / name).read_bytes()
        return {"path": name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    return {"files": [{"source": record(name)} for name in paths]}


@pytest.fixture
def case(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("Git is needed for the real object-hash fixture")
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(tmp_path / "receipts"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    files = {"models/Demo/docs/install.windows.md": b"# Installation\nUse the official executable.\n",
             "models/Demo/kiss.windows.yaml": b"model: Demo\nverified: unverified\n",
             "kiss/manifests/Demo.yaml": b"model: Demo\nbinary_type: ELF\n"}
    tree = git_tree(root, files)
    for name, body in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    calls = []
    response = {"sha": "a" * 40, "commit": {"tree": {"sha": tree}}}

    def request(url):
        calls.append(url)
        return response
    return SimpleNamespace(root=root, files=files, tree=tree, response=response,
                           calls=calls, request=request, overlay=overlay_for(root, files))


def test_real_git_objects_authenticate_selected_inputs_without_ki_baseline(case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Guidance authentication must not enroll/trust a whole KI")
    monkeypatch.setattr(ki_guard, "enroll", forbidden)
    monkeypatch.setattr(ki_guard, "require_intact", forbidden)
    result = proof.authenticate(case.root, case.overlay, request_json=case.request)
    assert case.calls == [proof.SOURCE_URL]
    assert result["scope"] == proof.SCOPE
    assert result["whole_ki_trusted"] is False and result["authoring_verification"] is False
    assert all(row["transform"] == "exact_bytes" for row in result["files"])
    assert proof.require_current(case.root, case.overlay, result) == result
    (case.root / "models/Demo/unrelated-tool.py").write_text("unreviewed content", encoding="utf-8")
    assert proof.require_current(case.root, case.overlay, result) == result


def test_updater_authenticates_missing_baseline_guidance_without_enrolling_ki(case, monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guards"))
    manager = ki_updates.UpdateManager(case.root, lambda _root: pytest.fail("No activation during provenance"))
    monkeypatch.setattr(manager, "_request_json", case.request)
    manager._check_overlay_source(case.overlay)
    source = case.overlay["host_source"]
    assert source["scope"] == proof.SCOPE
    proof.require_current(case.root, case.overlay, source["evidence"])
    assert not ki_guard.is_managed(case.root / "models/Demo")


def test_updater_does_not_use_official_guidance_to_bypass_changed_registered_ki(case, monkeypatch, tmp_path):
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    manager = ki_updates.UpdateManager(case.root, lambda _root: None)
    monkeypatch.setattr(ki_guard, "is_managed", lambda _root: True)

    def changed(_root):
        raise ki_guard.KIIntegrityError("registered KI changed")

    monkeypatch.setattr(ki_guard, "require_intact", changed)
    monkeypatch.setattr(manager, "_request_json", lambda _url: pytest.fail("Must retain registered KI guard"))
    with pytest.raises(ki_guard.KIIntegrityError, match="registered KI changed"):
        manager._check_overlay_source(case.overlay)
    assert "host_source" not in case.overlay


def test_crlf_only_checkout_conversion_retains_both_byte_hashes(case):
    for name, body in case.files.items():
        (case.root / name).write_bytes(body.replace(b"\n", b"\r\n"))
    overlay = overlay_for(case.root, case.files)
    result = proof.authenticate(case.root, overlay, request_json=case.request)
    assert all(row["transform"] == "crlf_lf_only" for row in result["files"])
    assert all(row["official_sha256"] != row["input_sha256"] for row in result["files"])
    assert all(len(row["blob_sha1"]) == 40 for row in result["files"])


def test_signed_cache_avoids_another_connection_and_rechecks_current_bytes(case):
    result = proof.authenticate(case.root, case.overlay, request_json=case.request)
    again = proof.authenticate(case.root, case.overlay,
                               request_json=lambda url: pytest.fail("Cache should not connect"))
    assert again == result
    path = next(iter(case.files))
    (case.root / path).write_bytes(b"different command\n")
    with pytest.raises(proof.GuidanceProvenanceError, match="changed"):
        proof.authenticate(case.root, case.overlay, request_json=case.request)
    assert len(case.calls) == 1


def test_changed_selected_bytes_cannot_be_rebaselined_as_official(case):
    path = next(iter(case.files))
    (case.root / path).write_bytes(b"changed installation command\n")
    overlay = overlay_for(case.root, case.files)
    with pytest.raises(proof.GuidanceProvenanceError, match="differs from official"):
        proof.authenticate(case.root, overlay, request_json=case.request)


def test_tampered_cache_is_not_silently_replaced(case):
    proof.authenticate(case.root, case.overlay, request_json=case.request)
    path = next((published_acceptance._authority(case.root) / "guidance-provenance").glob("*.json"))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["source_commit"] = "b" * 40
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(proof.GuidanceProvenanceError, match="Cached"):
        proof.authenticate(case.root, case.overlay, request_json=case.request)
    assert len(case.calls) == 1


@pytest.mark.parametrize("kind", ["tree", "blob"])
def test_hash_verification_rejects_corrupt_local_git_object_bytes(case, kind):
    if kind == "tree":
        oid = case.tree
    else:
        body = next(iter(case.files.values()))
        oid = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    path = case.root / ".git/objects" / oid[:2] / oid[2:]
    raw = zlib.decompress(path.read_bytes())
    path.write_bytes(zlib.compress(raw[:-1] + bytes([raw[-1] ^ 1])))
    with pytest.raises(proof.GuidanceProvenanceError, match="object"):
        proof.authenticate(case.root, case.overlay, request_json=case.request)


@pytest.mark.parametrize("mode", [b"120000", b"160000"])
def test_official_leaf_link_or_submodule_does_not_authorize_guidance(case, mode):
    source = next(iter(case.files))
    tree = git_tree(case.root, {source: (mode, case.files[source])})
    case.response["commit"]["tree"]["sha"] = tree
    with pytest.raises(proof.GuidanceProvenanceError, match="absent|regular file"):
        proof.authenticate(case.root, overlay_for(case.root, [source]), request_json=case.request)


@pytest.mark.parametrize("path", ["models/Demo/tools/run.py", "../escape", "/absolute.yaml",
                                    "models/Demo/kiss.linux.yaml", "models\\Demo\\kiss.yaml",
                                    "models/Demo/../Other/kiss.yaml"])
def test_only_selected_windows_guidance_paths_are_allowed(case, path):
    case.overlay["files"][0]["source"]["path"] = path
    with pytest.raises(proof.GuidanceProvenanceError, match="allowed metadata paths"):
        proof.authenticate(case.root, case.overlay, request_json=case.request)
    assert case.calls == []


@pytest.mark.parametrize("response", [{}, {"sha": "main", "commit": {"tree": {"sha": "a" * 40}}},
                                       {"sha": "a" * 40, "commit": {"tree": {"sha": "missing"}}}])
def test_invalid_official_commit_response_fails_closed(case, response):
    with pytest.raises(proof.GuidanceProvenanceError):
        proof.authenticate(case.root, case.overlay, request_json=lambda url: response)


def test_network_failure_does_not_create_source_proof(case):
    def failed(url):
        raise OSError("No connection")
    with pytest.raises(proof.GuidanceProvenanceError, match="Cannot authenticate"):
        proof.authenticate(case.root, case.overlay, request_json=failed)
    assert not (published_acceptance._authority(case.root) / "guidance-provenance").exists()


def test_implementation_change_during_check_cannot_be_signed(case, monkeypatch):
    identity = {"value": "a" * 64}
    monkeypatch.setattr(proof, "_implementation", lambda: identity["value"])
    def request(url):
        identity["value"] = "b" * 64
        return case.response
    monkeypatch.setattr(published_acceptance, "_sign", lambda *a: pytest.fail("Must not sign changed verifier"))
    with pytest.raises(proof.GuidanceProvenanceError, match="changed during"):
        proof.authenticate(case.root, case.overlay, request_json=request)


def test_changed_input_during_authentication_cannot_be_signed(case, monkeypatch):
    def request(url):
        (case.root / next(iter(case.files))).write_bytes(b"mid-check edit\n")
        return case.response
    monkeypatch.setattr(published_acceptance, "_sign", lambda *a: pytest.fail("Must not sign changed inputs"))
    with pytest.raises(proof.GuidanceProvenanceError, match="changed"):
        proof.authenticate(case.root, case.overlay, request_json=request)


def test_input_and_object_limits_fail_closed(case, monkeypatch):
    monkeypatch.setattr(proof, "MAX_INPUTS", 1)
    with pytest.raises(proof.GuidanceProvenanceError, match="Too many"):
        proof.authenticate(case.root, case.overlay, request_json=case.request)
    monkeypatch.setattr(proof, "MAX_INPUTS", 512)
    monkeypatch.setattr(proof, "MAX_OBJECT_BYTES", 1)
    with pytest.raises(proof.GuidanceProvenanceError, match="byte limit"):
        proof.authenticate(case.root, case.overlay, request_json=case.request)


def test_aggregate_git_object_bytes_are_bounded(case, monkeypatch):
    monkeypatch.setattr(proof, "MAX_OBJECT_TOTAL_BYTES", 1)
    with pytest.raises(proof.GuidanceProvenanceError, match="total byte limit"):
        proof.authenticate(case.root, case.overlay, request_json=case.request)


@pytest.mark.parametrize("message", [
    "Git is required to authenticate development-checkout guidance",
    "Official guidance Git object is unavailable locally",
    "Cannot read the official guidance Git objects",
])
def test_git_provenance_failure_keeps_original_error(tmp_path, monkeypatch, message):
    failure = proof.GuidanceProvenanceError(message)
    def unavailable(*_args):
        raise failure
    monkeypatch.setattr(proof, "_git", unavailable)
    with pytest.raises(proof.GuidanceProvenanceError) as caught:
        proof._Objects(tmp_path).read("tree", "a" * 40)
    assert caught.value is failure


@pytest.mark.parametrize("raw_size", [b"", b"not-a-size", b"12 trailing-data"])
def test_successful_but_malformed_git_size_response_is_reported(tmp_path, monkeypatch, raw_size):
    monkeypatch.setattr(proof, "_git", lambda *_args: raw_size)
    with pytest.raises(proof.GuidanceProvenanceError, match="Invalid Git object size"):
        proof._Objects(tmp_path).read("tree", "a" * 40)


def test_snapshot_directory_without_git_reports_missing_object_store(case, tmp_path):
    snapshot = tmp_path / "unpacked-snapshot"
    snapshot.mkdir()
    with pytest.raises(proof.GuidanceProvenanceError, match="object is unavailable locally"):
        proof._Objects(snapshot).read("tree", case.tree)


def snapshot_from(case, tmp_path):
    root = tmp_path / "unpacked-snapshot"
    for name, body in case.files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    return root


def test_separate_git_store_authenticates_snapshot_bytes_and_keeps_source_identity(case, tmp_path, monkeypatch):
    snapshot = snapshot_from(case, tmp_path)
    overlay = overlay_for(snapshot, case.files)
    def forbidden(*_args, **_kwargs):
        pytest.fail("An object store must not grant a whole-KI baseline")
    monkeypatch.setattr(ki_guard, "enroll", forbidden)
    monkeypatch.setattr(ki_guard, "require_intact", forbidden)
    # The object's working checkout is not the selected input or authority.
    for name in case.files:
        (case.root / name).write_text("untrusted working-copy edits")
    result = proof.authenticate(snapshot, overlay, request_json=case.request, object_root=case.root)
    assert result["root"] == str(snapshot.resolve())
    assert result["inputs"] == proof._inputs(snapshot, overlay)[0]
    assert result["whole_ki_trusted"] is False
    assert proof.require_current(snapshot, overlay, result) == result
    with pytest.raises(proof.GuidanceProvenanceError):
        proof.require_current(case.root, case.overlay, result)
    # A valid signed cache remains usable without the original byte store.
    assert proof.authenticate(snapshot, overlay,
        request_json=lambda _: pytest.fail("Cached proof must not request a new anchor"),
        object_root=tmp_path / "unavailable-store") == result
    assert case.calls == [proof.SOURCE_URL]


def test_separate_git_store_cannot_authorize_changed_selected_metadata(case, tmp_path):
    snapshot = snapshot_from(case, tmp_path)
    (snapshot / next(iter(case.files))).write_bytes(b"not the official guidance\n")
    with pytest.raises(proof.GuidanceProvenanceError, match="differs from official"):
        proof.authenticate(snapshot, overlay_for(snapshot, case.files),
            request_json=case.request, object_root=case.root)


def test_separate_git_store_still_checks_actual_object_identity(case, tmp_path):
    snapshot = snapshot_from(case, tmp_path)
    path = case.root / ".git/objects" / case.tree[:2] / case.tree[2:]
    raw = zlib.decompress(path.read_bytes())
    path.write_bytes(zlib.compress(raw[:-1] + bytes([raw[-1] ^ 1])))
    with pytest.raises(proof.GuidanceProvenanceError, match="object bytes do not match"):
        proof.authenticate(snapshot, overlay_for(snapshot, case.files),
            request_json=case.request, object_root=case.root)


def test_unavailable_object_store_fails_before_network_or_proof(case, tmp_path):
    snapshot = snapshot_from(case, tmp_path)
    with pytest.raises(proof.GuidanceProvenanceError, match="no local Git object store.*complete GeoForge"):
        proof.authenticate(snapshot, overlay_for(snapshot, case.files),
            request_json=lambda _: pytest.fail("Unavailable store needs no network request"))
    assert not (published_acceptance._authority(snapshot) / "guidance-provenance").exists()


def test_updater_uses_app_checkout_objects_for_unpacked_snapshot(case, tmp_path, monkeypatch):
    snapshot = snapshot_from(case, tmp_path)
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guards"))
    monkeypatch.setattr(ki_updates, "__file__", str(case.root / "kiss/kiss_cli/ki_updates.py"))
    manager = ki_updates.UpdateManager(snapshot, lambda _: pytest.fail("Provenance does not activate"))
    monkeypatch.setattr(manager, "_request_json", case.request)
    overlay = overlay_for(snapshot, case.files)
    manager._check_overlay_source(overlay)
    evidence = overlay["host_source"]["evidence"]
    assert evidence["root"] == str(snapshot.resolve())
    assert proof.require_current(snapshot, overlay, evidence) == evidence
    assert not ki_guard.is_managed(snapshot / "models/Demo")


def test_updater_without_app_git_store_preserves_snapshot_and_reports_limitation(case, tmp_path, monkeypatch):
    snapshot = snapshot_from(case, tmp_path)
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guards"))
    monkeypatch.setattr(ki_updates, "__file__", str(tmp_path / "packaged-app/kiss/kiss_cli/ki_updates.py"))
    manager = ki_updates.UpdateManager(snapshot, lambda _: pytest.fail("No unproven activation"))
    monkeypatch.setattr(manager, "_request_json", lambda _: pytest.fail("No available object store"))
    overlay = overlay_for(snapshot, case.files)
    before = proof._inputs(snapshot, overlay)[0]
    with pytest.raises(proof.GuidanceProvenanceError, match="no local Git object store"):
        manager._check_overlay_source(overlay)
    assert "host_source" not in overlay
    assert proof._inputs(snapshot, overlay)[0] == before
    assert not ki_guard.is_managed(snapshot / "models/Demo")
