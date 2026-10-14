"""Raw guidance is proven once, never reverse-engineered from composed files."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from kiss_cli import ki_guard
from kiss_cli import raw_windows_guidance as raw


def official_source(files, commit="a" * 40):
    """Harmless Git/HTTPS fixture usable by updater and composition tests."""
    files = {path: body.encode() if isinstance(body, str) else body for path, body in files.items()}
    nested, objects, rows = {}, {}, []
    for path, body in files.items():
        current = nested
        for part in path.split("/")[:-1]:
            current = current.setdefault(part, {})
        current[path.split("/")[-1]] = body

    def object_bytes(kind, body):
        oid = raw._git_hash(kind, body)
        objects[(kind, oid)] = body
        return oid

    def encode(tree, prefix=""):
        entries = []
        for name, value in sorted(tree.items(), key=lambda row: row[0].encode() + (b"/" if isinstance(row[1], dict) else b"")):
            path = prefix + name
            if isinstance(value, dict):
                mode, kind, oid = "040000", "tree", encode(value, path + "/")
            else:
                mode, kind, body = "100644", "blob", value
                if isinstance(value, tuple):
                    mode, body = value
                oid = object_bytes(kind, body)
            rows.append({"path": path, "mode": mode, "type": kind, "sha": oid})
            entries.append(mode.lstrip("0").encode() + b" " + name.encode() + b"\0" + bytes.fromhex(oid))
        return object_bytes("tree", b"".join(entries))

    tree = encode(nested)
    calls = []
    response = {"sha": commit, "commit": {"tree": {"sha": tree}}}
    tree_response = {"sha": tree, "truncated": False, "tree": rows}

    def request_json(url):
        calls.append(url)
        if url == raw.SOURCE_URL:
            return copy.deepcopy(response)
        assert url == f"{raw.API_ROOT}/git/trees/{tree}?recursive=1"
        return copy.deepcopy(tree_response)

    def request_bytes(url, *, max_bytes):
        calls.append(url)
        prefix = f"{raw.RAW_ROOT}/{commit}/"
        assert url.startswith(prefix)
        path = unquote(url[len(prefix):])
        body = files[path]
        assert isinstance(body, bytes) and len(body) <= max_bytes
        return body

    def write_git(root):
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        for (kind, oid), body in objects.items():
            target = root / ".git/objects" / oid[:2] / oid[2:]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zlib.compress(kind.encode() + b" " + str(len(body)).encode() + b"\0" + body))

    return SimpleNamespace(files=files, tree=tree, commit=commit, objects=objects, response=response,
        tree_response=tree_response, calls=calls, request_json=request_json,
        request_bytes=request_bytes, write_git=write_git)


def prepare_fixture(files, *, commit="a" * 40, model_names=None):
    """Return a real signed component using only the fake official transport.

    The caller sets GEOFORGE_KI_UPDATE_HOME, GEOFORGE_KI_VERIFICATION_HOME and
    GEOFORGE_FLOW_KEYS once, so multiple fixture versions retain the same key.
    """
    source = official_source(files, commit)
    return raw.prepare(model_names, request_json=source.request_json, request_bytes=source.request_bytes)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_UPDATE_HOME", str(tmp_path / "updates"))
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(tmp_path / "receipts"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    files = {
        "models/APEX/SKILL.md": b"Official model membership only.\n",
        "models/APEX/docs/install.windows.md": b"# Windows\nUse official runtime.\n",
        "models/APEX/kiss.windows.yaml": b"kiss_manifest_version: 1\nmodel: APEX\nbinary_type: PE32\n",
        "kiss/manifests/APEX.yaml": b"kiss_manifest_version: 1\nmodel: APEX\nbinary_type: ELF\n",
        "models/APEX/tools/run.py": b"raise RuntimeError('must not be imported or copied')\n",
        "unrelated/file.txt": b"Irrelevant repository content\n",
    }
    return official_source(files)


def prepare(case, **kwargs):
    return raw.prepare(request_json=case.request_json, request_bytes=case.request_bytes, **kwargs)


def test_packaged_without_git_authenticates_only_original_metadata(case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Metadata must not enroll or execute a model")
    monkeypatch.setattr(ki_guard, "enroll", forbidden)
    monkeypatch.setattr(ki_guard, "require_intact", forbidden)
    result = prepare(case)
    root, evidence = result["root"], result["evidence"]
    assert raw.require_current(root, evidence) == evidence
    assert evidence["models"] == ["APEX"]
    assert evidence["source_commit"] == case.commit and evidence["source_tree"] == case.tree
    assert evidence["whole_ki_trusted"] is False and evidence["authoring_verification"] is False
    assert evidence["native_regression"] == "not_run"
    assert set(evidence["inputs"]) == {"models/APEX/docs/install.windows.md", "models/APEX/kiss.windows.yaml", "kiss/manifests/APEX.yaml"}
    assert not (root / "models/APEX/SKILL.md").exists()
    assert not (root / "models/APEX/tools").exists()
    for path in evidence["inputs"]:
        assert (root / path).read_bytes() == case.files[path]
    assert len([url for url in case.calls if url.startswith(raw.API_ROOT)]) == 2


def test_local_git_is_only_optional_untrusted_byte_cache(case, tmp_path):
    if not shutil.which("git"):
        pytest.skip("Local object-store test needs Git")
    checkout = tmp_path / "checkout"
    case.write_git(checkout)
    (checkout / "models/APEX").mkdir(parents=True)
    (checkout / "models/APEX/kiss.windows.yaml").write_bytes(b"untrusted working-copy edit")
    result = prepare(case, object_root=checkout)
    assert case.calls == [raw.SOURCE_URL]
    assert (result["root"] / "models/APEX/kiss.windows.yaml").read_bytes() == case.files["models/APEX/kiss.windows.yaml"]


def test_cache_rechecks_files_but_only_refreshes_official_commit(case):
    first = prepare(case)
    case.calls.clear()
    assert prepare(case) == first
    assert case.calls == [raw.SOURCE_URL]
    (first["root"] / "models/APEX/kiss.windows.yaml").write_bytes(b"edited")
    with pytest.raises(raw.RawGuidanceError, match="Cached raw Windows guidance is invalid"):
        prepare(case)
    assert (first["root"] / "models/APEX/kiss.windows.yaml").read_bytes() == b"edited"


@pytest.mark.parametrize("mutation", ["extra", "receipt", "missing"])
def test_tampered_component_is_not_replaced(case, mutation):
    result = prepare(case)
    root, evidence = result["root"], result["evidence"]
    if mutation == "extra":
        (root / "models/APEX/SKILL.md").write_bytes(b"forged KI")
    elif mutation == "receipt":
        document = dict(evidence, source_commit="b" * 40)
        (root / raw.MANIFEST).write_text(json.dumps(document), encoding="utf-8")
    else:
        (root / "models/APEX/kiss.windows.yaml").unlink()
    with pytest.raises(raw.RawGuidanceError):
        raw.require_current(root, evidence)
    with pytest.raises(raw.RawGuidanceError, match="not replaced"):
        prepare(case)


@pytest.mark.parametrize("mutation", ["truncated", "blob_oid", "omitted", "parent", "duplicate", "tree_oid"])
def test_recursive_tree_must_reconstruct_exact_official_root(case, mutation):
    rows = case.tree_response["tree"]
    if mutation == "truncated":
        case.tree_response["truncated"] = True
    elif mutation == "blob_oid":
        next(row for row in rows if row["path"].endswith("kiss.windows.yaml"))["sha"] = "b" * 40
    elif mutation == "omitted":
        rows.pop(0)
    elif mutation == "parent":
        rows[:] = [row for row in rows if row["path"] != "models/APEX"]
    elif mutation == "duplicate":
        rows.append(dict(rows[0]))
    else:
        case.tree_response["sha"] = "b" * 40
    with pytest.raises(raw.RawGuidanceError):
        prepare(case)


def test_wrong_raw_body_cannot_be_authenticated(case):
    case.files["models/APEX/kiss.windows.yaml"] = b"Bytes from a composed snapshot"
    with pytest.raises(raw.RawGuidanceError, match="do not match their identity"):
        prepare(case)


def test_missing_git_objects_fall_back_to_verified_https(case, tmp_path):
    result = prepare(case, object_root=tmp_path / "not-a-checkout")
    assert raw.require_current(result["root"], result["evidence"])
    assert len(case.calls) == 5


@pytest.mark.parametrize("path", ["models/APEX/SKILL.md", "models/APEX/docs/install.windows.md", "models/APEX/kiss.windows.yaml"])
def test_symlink_metadata_or_membership_is_rejected(case, path):
    files = dict(case.files, **{path: ("120000", b"somewhere-else")})
    unsafe = official_source(files)
    with pytest.raises(raw.RawGuidanceError, match="regular"):
        prepare(unsafe)


def test_new_windows_commit_changes_identity_even_with_same_metadata(case):
    first = prepare(case)
    second = prepare(official_source(case.files, commit="b" * 40))
    assert first["root"] != second["root"]
    assert first["evidence"]["component_id"] != second["evidence"]["component_id"]
    assert first["evidence"]["content_sha256"] == second["evidence"]["content_sha256"]
    assert raw.require_current(first["root"], first["evidence"])


def test_requested_model_membership_and_all_models_inventory(case):
    files = dict(case.files, **{"models/Other/SKILL.md": b"Other model", "models/Other/docs/install.windows.md": b"Other notes"})
    source = official_source(files)
    all_models = prepare(source)
    assert all_models["evidence"]["models"] == ["APEX", "Other"]
    one_model = prepare(source, model_names=["APEX"])
    assert one_model["evidence"]["models"] == ["APEX"]
    with pytest.raises(raw.RawGuidanceError, match="missing models"):
        prepare(source, model_names=["Missing"])


def test_metadata_download_bounded(case, monkeypatch):
    monkeypatch.setattr(raw, "MAX_TOTAL_BYTES", 10)
    with pytest.raises(raw.RawGuidanceError, match="byte limits"):
        prepare(case)


def test_no_byte_transport_is_actionable_when_git_unavailable(case):
    with pytest.raises(raw.RawGuidanceError, match="HTTPS download route"):
        raw.prepare(request_json=case.request_json)


def test_arbitrary_official_commit_identity_is_rejected(case):
    case.response["sha"] = "branch-name"
    with pytest.raises(raw.RawGuidanceError, match="exact commit/tree"):
        prepare(case)


def test_old_implementation_receipt_cannot_be_reused(case, monkeypatch):
    result = prepare(case)
    monkeypatch.setattr(raw, "_implementation", lambda: "f" * 64)
    with pytest.raises(raw.RawGuidanceError, match="current authentic"):
        raw.require_current(result["root"], result["evidence"])


def test_empty_windows_guidance_still_has_proven_model_component(case):
    source = official_source({"models/APEX/SKILL.md": b"Official model without Windows files"})
    result = prepare(source)
    assert result["evidence"]["models"] == ["APEX"] and result["evidence"]["inputs"] == {}
    assert raw.require_current(result["root"], result["evidence"])


def test_extra_empty_directory_rejected_without_descent(case):
    result = prepare(case)
    (result["root"] / "unexpected/deep").mkdir(parents=True)
    with pytest.raises(raw.RawGuidanceError, match="unexpected directory"):
        raw.require_current(result["root"], result["evidence"])


def test_oversized_saved_proof_rejected_before_parsing(case, monkeypatch):
    result = prepare(case)
    monkeypatch.setattr(raw, "MAX_PROOF_BYTES", 8)
    with pytest.raises(raw.RawGuidanceError, match="not replaced"):
        prepare(case)


def test_corrupt_local_bytes_fail_without_network_substitution(case, tmp_path, monkeypatch):
    def corrupt(self, kind, oid):
        if kind == "blob":
            raise raw.provenance.GuidanceProvenanceError("Local Git object bytes do not match their official identity")
        return case.objects[(kind, oid)]
    monkeypatch.setattr(raw.provenance._Objects, "read", corrupt)
    monkeypatch.setattr(raw.provenance, "has_git_object_store", lambda root: True)
    with pytest.raises(raw.RawGuidanceError, match="do not match their official identity"):
        prepare(case, object_root=tmp_path)
    assert case.calls == [raw.SOURCE_URL]


@pytest.mark.parametrize("name", ["../APEX", "APEX/child", "APEX\\child", "CON", "aux.txt", "APEX."])
def test_unsafe_requested_model_names_rejected_before_network(case, name):
    with pytest.raises(raw.RawGuidanceError, match="Invalid requested"):
        prepare(case, model_names=[name])
    assert case.calls == []


def test_casefold_model_collision_rejected(case):
    source = official_source({"models/Model/SKILL.md": b"one", "models/model/SKILL.md": b"two"})
    with pytest.raises(raw.RawGuidanceError, match="collide"):
        prepare(source)


def test_selected_symlink_directory_rejected(case):
    source = official_source({"models/APEX/SKILL.md": b"membership", "models/APEX/docs": ("120000", b"elsewhere")})
    with pytest.raises(raw.RawGuidanceError, match="not a directory"):
        prepare(source)


def test_non_utf8_metadata_rejected(case):
    source = official_source(dict(case.files, **{"models/APEX/docs/install.windows.md": b"\xff"}))
    with pytest.raises(raw.RawGuidanceError, match="UTF-8"):
        prepare(source)


def test_file_bound_is_passed_to_transport_and_rechecked(case, monkeypatch):
    calls = []
    def oversized(url, *, max_bytes):
        calls.append(max_bytes)
        return b"x" * (max_bytes + 1)
    with pytest.raises(raw.RawGuidanceError):
        raw.prepare(request_json=case.request_json, request_bytes=oversized)
    assert calls == [raw.MAX_FILE_BYTES]


@pytest.mark.skipif(os.name != "nt", reason="Actual Windows junction regression")
@pytest.mark.parametrize("location", ["root", "input_parent", "unexpected"])
def test_windows_junction_rejected_on_python311(case, tmp_path, location):
    result = prepare(case)
    root = result["root"]
    outside = tmp_path / "outside"
    if location == "root":
        root.rename(outside)
        link = root
    elif location == "input_parent":
        link = root / "models/APEX/docs"
        link.rename(outside)
    else:
        outside.mkdir()
        link = root / "unexpected"
    subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Python 3.11 lacks Path.is_junction; st_file_attributes must catch it.
        assert raw.ki_tree._reparse(link.lstat())
        with pytest.raises(raw.RawGuidanceError):
            raw.require_current(root, result["evidence"])
        with pytest.raises(raw.RawGuidanceError, match="not replaced"):
            prepare(case)
        assert outside.is_dir()
    finally:
        link.rmdir()
