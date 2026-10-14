"""Fixture-signed metadata tests; these do not grant model/KDT acceptance."""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import ki_guidance_composition as composition
from kiss_cli import ki_platform_overlay as overlay
from kiss_cli import published_acceptance, raw_windows_guidance as raw


def write(root, path, value):
    output = root / path
    output.parent.mkdir(parents=True, exist_ok=True)
    body = (yaml.safe_dump(value, sort_keys=False).encode() if isinstance(value, dict)
            else value.encode() if isinstance(value, str) else value)
    output.write_bytes(body)
    return output


def generic(**extra):
    return {"kiss_manifest_version": 1, "model": "Demo", "verified": "unverified",
            "binary_type": "ELF", "install_dir": "demo", "python_deps": ["numpy"],
            "acquire": {"strategy": "build", "repo": "linux-v1", "produces": "bin/demo"}, **extra}


def windows(**extra):
    return generic(**{"binary_type": "PE32", "verified": "observed", "system_deps": ["mingw"],
        "acquire": {"strategy": "manual", "produces": "bin/demo.exe"}, **extra})


def signed_component(root, files, *, commit="b" * 40, tree="c" * 40):
    inputs = {}
    for path, value in files.items():
        body = write(root, path, value).read_bytes()
        inputs[path] = {"path": path, "sha256": hashlib.sha256(body).hexdigest(),
                       "bytes": len(body), "blob_sha1": raw._git_hash("blob", body)}
    evidence = {"scope": raw.SCOPE, "policy": raw.POLICY, "root": str(root.resolve()),
        "source_url": raw.SOURCE_URL, "source_commit": commit, "source_tree": tree,
        "selection": None, "implementation": raw._implementation(), "models": ["Demo"],
        "membership": {"Demo": {"path": "models/Demo/SKILL.md", "blob_sha1": "d" * 40}},
        "inputs": inputs, "content_sha256": raw._hash(inputs), "whole_ki_trusted": False,
        "authoring_verification": False, "native_regression": "not_run"}
    evidence["component_id"] = raw._component_id(evidence)
    evidence = published_acceptance._sign(root, evidence)
    write(root, raw.MANIFEST, json.dumps(evidence))
    raw.require_current(root, evidence)
    return {"root": root, "evidence": evidence}


def run(component, incoming, **options):
    return composition.compose(component, incoming, source_commit="a" * 40,
        archive_sha256="e" * 64, source_content_sha256="f" * 64,
        architecture="amd64", **options)


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_VERIFICATION_HOME", str(tmp_path / "receipts"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    files = {"models/Demo/kiss.windows.yaml": windows(),
             "kiss/manifests/Demo.yaml": windows(),
             "models/Demo/docs/install.windows.md": "Official Windows instructions\r\n"}
    component = signed_component(tmp_path / "raw", files)
    incoming = tmp_path / "incoming"
    write(incoming, "models/Demo/SKILL.md", "Current main scientific KI")
    write(incoming, "models/Demo/kiss.yaml", generic(python_deps=["numpy>=2"]))
    return SimpleNamespace(root=tmp_path, component=component, incoming=incoming, files=files)


def test_raw_membership_without_skill_composes_and_records_both_sources(case):
    assert not (case.component["root"] / "models/Demo/SKILL.md").exists()
    result = run(case.component, case.incoming)
    merged = yaml.safe_load((case.incoming / "models/Demo/kiss.windows.yaml").read_text())
    assert merged["acquire"]["produces"] == "bin/demo.exe"
    assert merged["python_deps"] == ["numpy>=2"] and merged["verified"] == "unverified"
    assert {row["mode"] for row in result["files"]} == {"retained_windows_notes", "platform_contract_overlay"}
    context = result["composition"]
    assert context["main"] == {"source_commit": "a" * 40,
        "archive_sha256": "e" * 64, "source_content_sha256": "f" * 64}
    assert context["windows"]["source_commit"] == "b" * 40
    assert context["windows"]["component_id"] == case.component["evidence"]["component_id"]
    assert context["policy_sha256"] == composition.policy_digest()
    assert context["whole_ki_trusted"] is False and context["authoring_verification"] is False
    assert context["native_regression"] == "not_run"
    for row in result["files"]:
        output = row["output"]
        assert hashlib.sha256((case.incoming / output["path"]).read_bytes()).hexdigest() == output["sha256"]
    raw.require_current(**case.component)


def test_same_raw_bytes_in_different_cache_paths_have_same_composition_identity(case):
    second = signed_component(case.root / "raw-copy", case.files)
    other = case.root / "other-incoming"
    write(other, "models/Demo/SKILL.md", "Current main scientific KI")
    write(other, "models/Demo/kiss.yaml", generic(python_deps=["numpy>=2"]))
    first_result, second_result = run(case.component, case.incoming), run(second, other)
    assert first_result["overlay_id"] == second_result["overlay_id"]
    assert first_result["composition"]["windows"]["evidence_sha256"] != second_result["composition"]["windows"]["evidence_sha256"]


def test_windows_only_update_changes_identity_even_when_no_files_are_added(case):
    identities = []
    for i, commit in enumerate(("b" * 40, "9" * 40)):
        component = signed_component(case.root / f"raw-{i}", case.files, commit=commit)
        incoming = case.root / f"new-{i}"
        write(incoming, "models/Demo/SKILL.md", "Current main")
        write(incoming, "models/Demo/kiss.windows.yaml", windows())
        write(incoming, "models/Demo/docs/install.windows.md", "Main has newer notes")
        result = run(component, incoming)
        assert result["files"] == []
        identities.append(result["overlay_id"])
    assert identities[0] != identities[1]


def test_fresh_raw_composes_across_successive_generic_updates(case):
    first = run(case.component, case.incoming)
    second = case.root / "second"
    write(second, "models/Demo/SKILL.md", "Next main")
    write(second, "models/Demo/kiss.yaml", generic(python_deps=["numpy>=3"],
        acquire={"strategy": "build", "repo": "linux-v2", "produces": "bin/demo"}))
    result = run(case.component, second)
    assert first["files"][-1]["mode"] == result["files"][-1]["mode"] == "platform_contract_overlay"
    merged = yaml.safe_load((second / "models/Demo/kiss.windows.yaml").read_text())
    assert merged["acquire"]["produces"] == "bin/demo.exe" and merged["python_deps"] == ["numpy>=3"]
    assert yaml.safe_load((case.incoming / "models/Demo/kiss.windows.yaml").read_text())["python_deps"] == ["numpy>=2"]


def test_independent_raw_generic_is_the_three_way_ancestor(case):
    component = signed_component(case.root / "independent-raw", {
        "models/Demo/kiss.yaml": generic(), "models/Demo/kiss.windows.yaml": windows()})
    result = run(component, case.incoming)
    assert result["files"][0]["mode"] == "three_way_rebase"
    assert result["files"][0]["base_generic"]["path"] == "models/Demo/kiss.yaml"


@pytest.mark.parametrize("field,value", [("source_commit", "main"), ("source_commit", "A" * 40),
    ("archive_sha256", "b" * 63), ("source_content_sha256", None)])
def test_exact_main_identities_required_before_mutation(case, field, value):
    options = dict(source_commit="a" * 40, archive_sha256="e" * 64, source_content_sha256="f" * 64)
    options[field] = value
    with pytest.raises(composition.CompositionError, match="exact"):
        composition.compose(case.component, case.incoming, **options)
    assert not (case.incoming / "models/Demo/kiss.windows.yaml").exists()


@pytest.mark.parametrize("tamper", ["input", "proof", "extra", "old-composed-root"])
def test_unauthenticated_or_changed_raw_component_never_falls_back(case, tamper):
    component = case.component
    if tamper == "input":
        write(component["root"], "models/Demo/kiss.windows.yaml", windows(system_deps=["other"]))
    elif tamper == "proof":
        component["evidence"]["source_commit"] = "9" * 40
    elif tamper == "extra":
        write(component["root"], "models/Demo/tool.py", "print('extra')")
    else:
        component = dict(component, root=case.incoming)
    with pytest.raises(raw.RawGuidanceError):
        run(component, case.incoming)
    assert not (case.incoming / "models/Demo/kiss.windows.yaml").exists()


@pytest.mark.parametrize("changed", ["source", "output", "generic", "undeclared", "missing-record", "record-path"])
def test_composer_changed_bytes_or_declarations_are_rejected(case, monkeypatch, changed):
    original = overlay.apply_windows_overlay
    def corrupted(*args, **kwargs):
        result = original(*args, **kwargs)
        if changed == "source":
            write(case.component["root"], "models/Demo/docs/install.windows.md", "changed mid-composition")
        elif changed == "output":
            write(case.incoming, "models/Demo/kiss.windows.yaml", windows(python_deps=["wrong"]))
        elif changed == "generic":
            write(case.incoming, "models/Demo/kiss.yaml", generic(python_deps=["wrong"]))
        elif changed == "undeclared":
            write(case.incoming, "models/Demo/kiss.windows.x86_64.yaml", windows())
        elif changed == "missing-record":
            result["files"].pop()
        else:
            result["files"][0]["source"]["path"] = "../escape"
        return result
    monkeypatch.setattr(overlay, "apply_windows_overlay", corrupted)
    with pytest.raises((composition.CompositionError, raw.RawGuidanceError)):
        run(case.component, case.incoming)


def test_existing_upstream_windows_guidance_cannot_be_changed(case, monkeypatch):
    write(case.incoming, "models/Demo/kiss.windows.yaml", windows(python_deps=["main-owned"]))
    original = overlay.apply_windows_overlay
    def corrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        write(case.incoming, "models/Demo/kiss.windows.yaml", windows())
        return result
    monkeypatch.setattr(overlay, "apply_windows_overlay", corrupt)
    with pytest.raises(composition.CompositionError, match="pre-existing"):
        run(case.component, case.incoming)


def test_source_authenticated_again_after_composition(case, monkeypatch):
    original = raw.require_current
    calls = []
    def require(root, evidence):
        calls.append(str(root))
        if len(calls) == 2:
            raise raw.RawGuidanceError("Changed signed component")
        return original(root, evidence)
    monkeypatch.setattr(raw, "require_current", require)
    with pytest.raises(raw.RawGuidanceError, match="Changed signed"):
        run(case.component, case.incoming)
    assert len(calls) == 2


def test_outputs_rechecked_after_last_raw_authentication(case, monkeypatch):
    original = raw.require_current
    calls = 0
    def require(root, evidence):
        nonlocal calls
        calls += 1
        result = original(root, evidence)
        if calls == 2:
            write(case.incoming, "models/Demo/kiss.windows.yaml", "changed after first validation")
        return result
    monkeypatch.setattr(raw, "require_current", require)
    with pytest.raises(composition.CompositionError, match="output bytes"):
        run(case.component, case.incoming)


def test_composition_policy_drift_is_rejected(case, monkeypatch):
    values = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(composition, "policy_digest", lambda: next(values))
    with pytest.raises(composition.CompositionError, match="implementation"):
        run(case.component, case.incoming)


def test_composer_cannot_report_a_different_input_identity(case, monkeypatch):
    original = overlay.apply_windows_overlay
    def corrupt(*args, **kwargs):
        result = original(*args, **kwargs)
        result["source_identity"] = "9" * 64
        return result
    monkeypatch.setattr(overlay, "apply_windows_overlay", corrupt)
    with pytest.raises(composition.CompositionError, match="inconsistent source"):
        run(case.component, case.incoming)


def test_policy_identity_includes_each_implementation(monkeypatch):
    original = composition.published_kdt._module_identity
    baseline = composition.policy_digest()
    for target in (composition, overlay, raw):
        monkeypatch.setattr(composition.published_kdt, "_module_identity",
            lambda module, target=target: "f" * 64 if module is target else original(module))
        assert composition.policy_digest() != baseline
    monkeypatch.setattr(composition.published_kdt, "_module_identity", original)


@pytest.mark.parametrize("architecture", ["../unsafe", "C:\\tmp"])
def test_unsafe_architecture_is_rejected(case, architecture):
    with pytest.raises(composition.CompositionError, match="architecture"):
        composition.compose(case.component, case.incoming, source_commit="a" * 40,
            archive_sha256="e" * 64, source_content_sha256="f" * 64, architecture=architecture)


def test_non_windows_composition_is_not_silently_accepted(case):
    with pytest.raises(composition.CompositionError, match="Windows platform"):
        run(case.component, case.incoming, platform="linux")


def test_composition_provenance_is_covered_by_existing_publication_signature(case):
    result = run(case.component, case.incoming)
    signed = published_acceptance._sign(case.incoming, {"scope": "fixture-origin", "overlay": result})
    assert published_acceptance._authentic(case.incoming, signed)
    altered = copy.deepcopy(signed)
    altered["overlay"]["composition"]["windows"]["source_commit"] = "9" * 40
    assert not published_acceptance._authentic(case.incoming, altered)
