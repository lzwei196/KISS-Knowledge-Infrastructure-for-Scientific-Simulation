"""Windows guidance composition preserves provenance and rejects ambiguity."""
import hashlib
from pathlib import Path

import pytest
import yaml

from kiss_cli import ki_platform_overlay as overlay


def write(root, relative, value):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (yaml.safe_dump(value, sort_keys=False).encode() if isinstance(value, dict)
            else value.encode() if isinstance(value, str) else value)
    path.write_bytes(body)
    return path


def generic(**fields):
    return {"kiss_manifest_version": 1, "model": "Demo", "verified": "unverified",
            "binary_type": "ELF", "install_dir": "demo",
            "acquire": {"strategy": "download", "url": "https://example.org/linux.tar",
                        "produces": "bin/demo"}, "python_deps": ["numpy"], **fields}


def windows(**fields):
    return generic(binary_type="PE32", acquire={"strategy": "download",
        "url": "https://example.org/windows.zip", "produces": "bin/demo.exe"},
        verified="observed", system_deps=["Windows compiler"], **fields)


@pytest.fixture
def libraries(tmp_path):
    before, incoming = tmp_path / "before", tmp_path / "incoming"
    for root in (before, incoming):
        write(root, "models/Demo/SKILL.md", "Demo scientific KI")
    return before, incoming


def compose(before, incoming, **options):
    return overlay.apply_windows_overlay(before, incoming, architecture="amd64",
        upstream_commit="a" * 40, source_identity="windows-release-pinned", **options)


def test_restores_only_missing_guidance_and_preserves_source_bytes(libraries):
    before, incoming = libraries
    recipe = write(before, "models/Demo/kiss.windows.yaml", windows())
    notes = write(before, "models/Demo/docs/install.windows.md", b"Windows\r\n")
    original = recipe.read_bytes()
    result = compose(before, incoming)
    assert recipe.read_bytes() == original
    assert (incoming / "models/Demo/kiss.windows.yaml").read_bytes() == original
    assert (incoming / "models/Demo/docs/install.windows.md").read_bytes() == notes.read_bytes()
    assert {f["mode"] for f in result["files"]} == {"retained_windows_notes", "retained_windows_recipe"}
    assert result["setup_reverification_required"]
    for record in result["files"]:
        assert hashlib.sha256((incoming / record["output"]["path"]).read_bytes()).hexdigest() == record["output"]["sha256"]


@pytest.mark.parametrize("new_name", ["kiss.windows.yaml", "kiss.windows.x86_64.yaml"])
def test_upstream_effective_windows_recipe_wins_over_old_specific_filename(libraries, new_name):
    before, incoming = libraries
    write(before, "models/Demo/kiss.windows.x86_64.yaml", windows())
    updated = write(incoming, "models/Demo/" + new_name, windows(python_deps=["new-dependency"]))
    expected = updated.read_bytes()
    result = compose(before, incoming)
    assert result["files"] == [] and not result["setup_reverification_required"]
    assert updated.read_bytes() == expected
    if new_name != "kiss.windows.x86_64.yaml":
        assert not (incoming / "models/Demo/kiss.windows.x86_64.yaml").exists()


def test_existing_upstream_notes_and_removed_kis_are_not_restored(libraries):
    before, incoming = libraries
    write(before, "models/Demo/docs/install.windows.md", "old")
    write(incoming, "models/Demo/docs/install.windows.md", "upstream")
    write(before, "models/Removed/SKILL.md", "old")
    write(before, "models/Removed/docs/install.windows.md", "removed")
    result = compose(before, incoming)
    assert result["files"] == []
    assert (incoming / "models/Demo/docs/install.windows.md").read_text() == "upstream"
    assert not (incoming / "models/Removed").exists()


def test_three_way_follows_upstream_neutral_dependency_change(libraries):
    before, incoming = libraries
    write(before, "models/Demo/kiss.yaml", generic())
    write(before, "models/Demo/kiss.windows.yaml", windows())
    upstream = write(incoming, "models/Demo/kiss.yaml", generic(python_deps=["numpy>=2", "pandas"]))
    original = upstream.read_bytes()
    result = compose(before, incoming)
    merged = yaml.safe_load((incoming / "models/Demo/kiss.windows.yaml").read_text())
    assert merged["python_deps"] == ["numpy>=2", "pandas"]
    assert merged["acquire"] == windows()["acquire"]
    assert merged["verified"] == "unverified"
    assert result["files"][0]["mode"] == "three_way_rebase"
    assert upstream.read_bytes() == original


def test_three_way_rejects_concurrent_atomic_acquire_changes_before_any_write(libraries):
    before, incoming = libraries
    write(before, "models/Demo/kiss.yaml", generic())
    write(before, "models/Demo/kiss.windows.yaml", windows())
    write(before, "models/Demo/docs/install.windows.md", "would be copied later")
    write(incoming, "models/Demo/kiss.yaml", generic(acquire={"strategy": "build", "repo": "new-repo"}))
    with pytest.raises(overlay.OverlayConflict, match="acquire"):
        compose(before, incoming)
    assert not (incoming / "models/Demo/docs/install.windows.md").exists()
    assert not (incoming / "models/Demo/kiss.windows.yaml").exists()


def test_no_base_platform_contract_follows_new_requirements_and_preserves_windows_runtime(libraries):
    before, incoming = libraries
    old = write(before, "models/Demo/kiss.windows.yaml", windows())
    upstream = write(incoming, "kiss/manifests/Demo.yaml", generic(
        python_deps=["numpy>=2", "pandas"], depends_on=["Routing"],
        data=[{"role": "forcing", "name": "new required forcing"}], future_metadata="new"))
    originals = old.read_bytes(), upstream.read_bytes()
    result = compose(before, incoming)
    merged = yaml.safe_load((incoming / "models/Demo/kiss.windows.yaml").read_text())
    assert merged["python_deps"] == ["numpy>=2", "pandas"]
    assert merged["depends_on"] == ["Routing"] and merged["data"][0]["name"] == "new required forcing"
    assert merged["binary_type"] == "PE32" and merged["acquire"]["produces"] == "bin/demo.exe"
    assert merged["system_deps"] == ["Windows compiler"]
    assert merged["future_metadata"] == "new" and merged["verified"] == "unverified"
    assert result["files"][0]["mode"] == "platform_contract_overlay"
    assert result["files"][0]["incoming_neutral_fields"] == ["data", "depends_on", "python_deps"]
    assert (old.read_bytes(), upstream.read_bytes()) == originals


def test_mirrored_windows_shared_manifest_is_not_a_generic_ancestor(libraries):
    before, incoming = libraries
    recipe = windows()
    write(before, "models/Demo/kiss.windows.yaml", recipe)
    write(before, "kiss/manifests/Demo.yaml", recipe)
    write(incoming, "kiss/manifests/Demo.yaml", generic(python_deps=["new-scientific-dependency"]))
    result = compose(before, incoming)
    merged = yaml.safe_load((incoming / "models/Demo/kiss.windows.yaml").read_text())
    assert merged["python_deps"] == ["new-scientific-dependency"]
    assert merged["acquire"] == recipe["acquire"]
    assert result["files"][0]["mode"] == "platform_contract_overlay"
    assert result["files"][0]["excluded_platform_duplicate"]["path"] == "kiss/manifests/Demo.yaml"


def test_real_bundled_crhm_mirror_keeps_exe_and_applies_new_scientific_dependencies(tmp_path):
    source = Path(__file__).parents[2] / "models/CRHM/kiss.windows.yaml"
    recipe = yaml.safe_load(source.read_text(encoding="utf-8"))
    before, incoming = tmp_path / "before", tmp_path / "incoming"
    for root in (before, incoming):write(root, "models/CRHM/SKILL.md", "CRHM")
    write(before, "models/CRHM/kiss.windows.yaml", source.read_bytes())
    write(before, "kiss/manifests/CRHM.yaml", recipe)
    upstream = dict(recipe, binary_type="ELF", python_deps=["numpy", "pandas", "scipy"])
    upstream["acquire"] = {"strategy": "build", "repo": "upstream-source", "produces": "bin/crhm"}
    write(incoming, "kiss/manifests/CRHM.yaml", upstream)
    result = compose(before, incoming)
    merged = yaml.safe_load((incoming / "models/CRHM/kiss.windows.yaml").read_text())
    assert merged["acquire"]["produces"] == "bin/crhm.exe"
    assert merged["python_deps"] == ["numpy", "pandas", "scipy"]
    assert result["files"][0]["mode"] == "platform_contract_overlay"


def test_unclassified_conflicts_fail_closed(libraries):
    before, incoming = libraries
    write(before, "models/Demo/kiss.windows.yaml", windows(future_execution_policy="old"))
    write(incoming, "models/Demo/kiss.yaml", generic(future_execution_policy="new"))
    with pytest.raises(overlay.OverlayConflict, match="future_execution_policy"):
        compose(before, incoming)


def test_provenance_digest_stable_and_changes_with_source_content(tmp_path):
    ids = []
    for index, note in enumerate(["same", "same", "changed"]):
        before, incoming = tmp_path / f"before{index}", tmp_path / f"incoming{index}"
        for root in (before, incoming):write(root, "models/Demo/SKILL.md", "Demo")
        write(before, "models/Demo/docs/install.windows.md", note)
        ids.append(compose(before, incoming)["overlay_id"])
    assert ids[0] == ids[1] and ids[1] != ids[2]


def test_symlink_source_escape_rejected(libraries, tmp_path):
    before, incoming = libraries
    outside = write(tmp_path, "external.txt", "outside")
    path = before / "models/Demo/docs/install.windows.md"
    path.parent.mkdir()
    try:path.symlink_to(outside)
    except OSError:pytest.skip("host cannot create symlinks")
    with pytest.raises(overlay.OverlayConflict, match="link"):
        compose(before, incoming)


def test_symlink_destination_escape_rejected(libraries, tmp_path):
    before, incoming = libraries
    write(before, "models/Demo/docs/install.windows.md", "Windows notes")
    outside = tmp_path / "outside"; outside.mkdir()
    try:(incoming / "models/Demo/docs").symlink_to(outside, target_is_directory=True)
    except OSError:pytest.skip("host cannot create symlinks")
    with pytest.raises(overlay.OverlayConflict, match="link"):
        compose(before, incoming)
    assert not list(outside.iterdir())


@pytest.mark.parametrize("architecture", ["../bad", "x86/64", "C:\\bad"])
def test_architecture_cannot_supply_a_path(libraries, architecture):
    with pytest.raises(overlay.OverlayConflict, match="architecture"):
        overlay.apply_windows_overlay(*libraries, architecture=architecture)


def test_no_non_windows_mutation(libraries):
    before, incoming = libraries
    write(before, "models/Demo/kiss.windows.yaml", windows())
    assert compose(before, incoming, platform="linux")["files"] == []
    assert not (incoming / "models/Demo/kiss.windows.yaml").exists()


def test_source_and_destination_must_be_disjoint(libraries):
    before, _ = libraries
    with pytest.raises(overlay.OverlayConflict, match="disjoint"):
        compose(before, before / "stage")
