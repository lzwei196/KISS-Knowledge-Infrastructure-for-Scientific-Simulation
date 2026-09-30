"""Project/model path ownership through the same interface used by Desktop."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kiss_cli import paths, port, project_paths


def shared(tmp_path, name):
    cfg = paths.KissConfig.default(tmp_path / "installed" / name)
    cfg.python = str(cfg.roles["python_env"] / "bin" / "python")
    return cfg


def save(cfg, folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")


def test_two_models_do_not_inherit_first_outputs_or_last_runtime(tmp_path):
    project = tmp_path / "scenario"
    a = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    save(a, project / "models" / "A")
    save(a, project)  # old Desktop wrote the last model config here
    b = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    save(b, project / "models" / "B")
    assert a.roles["outputs"] == project / "outputs" / "A"
    assert b.roles["outputs"] == project / "outputs" / "B"
    assert a.python != b.python
    assert project_paths.load_model_config(project, "A").python == a.python
    assert project_paths.load_model_config(project, "B").python == b.python
    package = tmp_path / "package"
    package.mkdir()
    (package / "SKILL.md").write_text("output=KISSPATH_OUTPUTS/result.nc\n")
    live = project / "models" / "B" / "ki"
    port.materialise(package, live, b)
    text = (live / "SKILL.md").read_text(encoding="utf-8")
    assert (project / "outputs" / "B" / "result.nc").as_posix() in text
    assert str(project / "outputs" / "A") not in text


def test_per_model_scenario_override_wins_and_install_binding_refreshes(tmp_path):
    project = tmp_path / "scenario"
    old = project_paths.model_config(project, "A", shared(tmp_path, "old"))
    old.roles["static"] = project / "outputs" / "A" / "runnable-deck"
    old.roles["forcing"] = project / "inputs" / "prepared-A"
    save(old, project / "models" / "A")
    fresh = shared(tmp_path, "new")
    actual = project_paths.model_config(project, "A", fresh)
    assert actual.roles["static"] == old.roles["static"]
    assert actual.roles["forcing"] == old.roles["forcing"]
    for role in ("binaries", "python_env", "ki_tools_common", "home"):
        assert actual.roles[role] == fresh.roles[role]
    assert actual.python == fresh.python
    assert actual.relocation == "none"


def test_saved_model_config_beats_global_overrides(tmp_path):
    project = tmp_path / "scenario"
    own = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    own.roles["static"] = project / "inputs" / "own"
    save(own, project / "models" / "A")
    legacy = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    legacy.roles["static"] = project / "inputs" / "other"
    save(legacy, project)
    assert project_paths.model_config(project, "A", shared(tmp_path, "A")).roles["static"] == own.roles["static"]


def test_legacy_single_model_global_deck_is_migrated_only_to_owner(tmp_path):
    project = tmp_path / "scenario"
    legacy = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    legacy.roles["static"] = project / "outputs" / "A" / "deck"
    save(legacy, project)
    assert project_paths.model_config(project, "A", shared(tmp_path, "A")).roles["static"] == legacy.roles["static"]
    b = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    assert b.roles["static"] == project / "inputs" / "static"
    assert b.roles["outputs"] == project / "outputs" / "B"


def test_legacy_single_model_custom_output_is_preserved(tmp_path):
    project = tmp_path / "scenario"
    legacy = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    legacy.roles["outputs"] = project / "custom-case"
    legacy.roles["outputs_disk1"] = project / "custom-case"
    (project / "models" / "A").mkdir(parents=True)
    save(legacy, project)
    assert project_paths.model_config(project, "A", shared(tmp_path, "A")).roles["outputs"] == project / "custom-case"
    assert project_paths.model_config(project, "B", shared(tmp_path, "B")).roles["outputs"] == project / "outputs" / "B"


def test_ambiguous_legacy_custom_output_is_not_assigned_to_a_model(tmp_path):
    project = tmp_path / "scenario"
    legacy = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    legacy.roles["outputs"] = project / "custom-case"
    legacy.roles["outputs_disk1"] = project / "custom-case"
    for name in ("A", "B"):
        (project / "models" / name).mkdir(parents=True)
    save(legacy, project)
    assert project_paths.model_config(project, "B", shared(tmp_path, "B")).roles["outputs"] == project / "outputs" / "B"


def test_resets_foreign_output_ownership_without_ambiguous_input_refs(tmp_path):
    project = tmp_path / "scenario"
    (project / "models" / "A").mkdir(parents=True)
    old = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    old.roles["outputs"] = project / "outputs" / "A"
    save(old, project / "models" / "B")
    actual = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    assert actual.roles["outputs"] == project / "outputs" / "B"
    assert actual.roles["static"] == project / "inputs" / "static"


def test_preserves_explicit_input_coupling_when_output_ownership_is_intact(tmp_path):
    project = tmp_path / "scenario"
    (project / "models" / "A").mkdir(parents=True)
    saved = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    saved.roles["forcing"] = project / "outputs" / "A" / "runoff"
    save(saved, project / "models" / "B")
    actual = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    assert actual.roles["outputs"] == project / "outputs" / "B"
    assert actual.roles["forcing"] == project / "outputs" / "A" / "runoff"


@pytest.mark.parametrize("output_role", ["outputs", "outputs_disk1"])
@pytest.mark.parametrize("input_role", ["data", "forcing", "obs", "static", "data_ki", "forcing_rechunked"])
def test_ambiguous_legacy_output_and_input_contamination_requires_review(tmp_path, output_role, input_role):
    project = tmp_path / "scenario"
    (project / "models" / "A").mkdir(parents=True)
    saved = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    saved.roles[output_role] = project / "outputs" / "A"
    saved.roles[input_role] = project / "outputs" / "A" / "runoff"
    folder = project / "models" / "B"
    save(saved, folder)
    before = (folder / paths.CONFIG_NAME).read_bytes()
    with pytest.raises(ValueError, match=r"review.*models/B/kiss.toml"):
        project_paths.model_config(project, "B", shared(tmp_path, "B"))
    with pytest.raises(ValueError, match=r"review.*models/B/kiss.toml"):
        project_paths.load_model_config(project, "B")
    assert (folder / paths.CONFIG_NAME).read_bytes() == before


def test_custom_legacy_config_from_another_install_is_not_misattributed(tmp_path):
    project = tmp_path / "scenario"
    legacy = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    legacy.roles["outputs"] = project / "old-case"
    legacy.roles["outputs_disk1"] = project / "old-case"
    save(legacy, project)
    (project / "models" / "B").mkdir(parents=True)
    b = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    assert b.roles["outputs"] == project / "outputs" / "B"


def test_already_mixed_legacy_output_and_runtime_is_not_migration_authority(tmp_path):
    project = tmp_path / "scenario"
    broken = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    broken.roles["outputs"] = project / "outputs" / "A"
    broken.roles["outputs_disk1"] = project / "outputs" / "A"
    broken.roles["static"] = project / "inputs" / "B-case"
    save(broken, project)
    for name in ("A", "B"):
        (project / "models" / name).mkdir(parents=True)
    actual = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    assert actual.roles["static"] == project / "inputs" / "static"


def test_model_config_directory_cannot_be_a_symlink_outside_project(tmp_path):
    project = tmp_path / "scenario"
    (project / "models").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "models" / "A").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="outside"):
        project_paths.model_config(project, "A", shared(tmp_path, "A"))


def test_model_config_directory_cannot_alias_another_model(tmp_path):
    project = tmp_path / "scenario"
    save(project_paths.model_config(project, "A", shared(tmp_path, "A")), project / "models" / "A")
    (project / "models" / "B").symlink_to(project / "models" / "A", target_is_directory=True)
    with pytest.raises(ValueError, match="aliased"):
        project_paths.load_model_config(project, "B")


def test_default_output_directory_cannot_alias_another_model(tmp_path):
    project = tmp_path / "scenario"
    (project / "outputs" / "A").mkdir(parents=True)
    (project / "outputs" / "B").symlink_to(project / "outputs" / "A", target_is_directory=True)
    with pytest.raises(ValueError, match="aliased"):
        project_paths.model_config(project, "B", shared(tmp_path, "B"))


def test_execution_load_rejects_unsafe_saved_roles_instead_of_defaulting(tmp_path):
    project = tmp_path / "scenario"
    cfg = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    cfg.roles["outputs"] = tmp_path / "outside"
    save(cfg, project / "models" / "A")
    with pytest.raises(ValueError, match="outputs"):
        project_paths.load_model_config(project, "A")


def test_materialized_config_survives_restart_with_neutral_global(tmp_path):
    project = tmp_path / "scenario"
    for name in ("A", "B"):
        own = project_paths.model_config(project, name, shared(tmp_path, name))
        own.roles["static"] = project / "inputs" / name / "deck"
        save(own, project / "models" / name)
    save(project_paths.project_config(project, python=sys.executable), project)
    for name in ("A", "B"):
        loaded = project_paths.load_model_config(project, name)
        refreshed = project_paths.model_config(project, name, shared(tmp_path, name))
        assert loaded.dumps() == refreshed.dumps()
        assert loaded.roles["outputs"] == project / "outputs" / name
        assert loaded.roles["static"] == project / "inputs" / name / "deck"


@pytest.mark.parametrize("role", ["data", "forcing", "obs", "static", "outputs", "outputs_disk1", "data_ki", "forcing_rechunked"])
def test_outside_project_scenario_override_is_ignored(tmp_path, role):
    project = tmp_path / "scenario"
    old = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    expected = old.roles[role]
    old.roles[role] = tmp_path / "outside"
    save(old, project / "models" / "A")
    assert project_paths.model_config(project, "A", shared(tmp_path, "A")).roles[role] == expected


def test_symlink_escape_is_not_a_project_owned_override(tmp_path):
    project = tmp_path / "scenario"
    project.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (project / "escape").symlink_to(outside, target_is_directory=True)
    old = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    old.roles["static"] = project / "escape" / "new-deck"
    save(old, project / "models" / "A")
    assert project_paths.model_config(project, "A", shared(tmp_path, "A")).roles["static"] == project / "inputs" / "static"


def test_relative_saved_roles_resolve_against_project_not_process_cwd(tmp_path):
    project = tmp_path / "scenario"
    old = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    old.roles["static"] = Path("inputs/prepared/A")
    save(old, project / "models" / "A")
    assert project_paths.model_config(project, "A", shared(tmp_path, "A")).roles["static"] == project / "inputs" / "prepared" / "A"


def test_relocated_model_roles_rebase_only_old_project_paths(tmp_path):
    old_project = tmp_path / "before"
    new_project = tmp_path / "after"
    old = project_paths.model_config(old_project, "A", shared(tmp_path, "A"))
    old.roles["static"] = old_project / "outputs" / "A" / "deck"
    save(old, new_project / "models" / "A")
    actual = project_paths.model_config(new_project, "A", shared(tmp_path, "new-install"))
    assert actual.root == new_project
    assert actual.roles["static"] == new_project / "outputs" / "A" / "deck"
    assert actual.roles["outputs"] == new_project / "outputs" / "A"


def test_model_resolution_never_walks_up_to_unrelated_parent_config(tmp_path):
    legacy = shared(tmp_path, "unrelated")
    project = tmp_path / "scenario"
    legacy.roles["static"] = project / "wrong"
    save(legacy, tmp_path)
    cfg = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    assert cfg.roles["static"] == project / "inputs" / "static"
    with pytest.raises(FileNotFoundError):
        project_paths.load_model_config(project, "A")


def test_neutral_project_config_has_no_model_runtime_or_output_owner(tmp_path):
    project = tmp_path / "scenario"
    legacy = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    save(legacy, project)
    neutral = project_paths.project_config(project, python=sys.executable)
    assert neutral.python == sys.executable
    assert neutral.roles["outputs"] == project / "outputs"
    assert neutral.roles["binaries"] == project / "binaries"
    assert neutral.roles["home"] == project


def test_neutral_project_common_input_override_reaches_each_model(tmp_path):
    project = tmp_path / "scenario"
    neutral = project_paths.project_config(project, python=sys.executable)
    neutral.roles["forcing"] = project / "inputs" / "shared-weather"
    save(neutral, project)
    for name in ("A", "B"):
        cfg = project_paths.model_config(project, name, shared(tmp_path, name))
        assert cfg.roles["forcing"] == neutral.roles["forcing"]
        assert cfg.roles["outputs"] == project / "outputs" / name


def test_resolution_does_not_create_project_dirs_or_mutate_shared_config(tmp_path):
    project = tmp_path / "not-created"
    install = shared(tmp_path, "A")
    before = install.dumps()
    project_paths.model_config(project, "A", install)
    project_paths.project_config(project, python=sys.executable)
    assert install.dumps() == before
    assert not project.exists()


@pytest.mark.parametrize("name", ["", ".", "..", "../A", "A/B", "A\\B", "/A"])
def test_model_name_must_be_one_directory_component(tmp_path, name):
    with pytest.raises(ValueError):
        project_paths.model_config(tmp_path / "scenario", name, shared(tmp_path, "A"))


def test_corrupt_owned_config_is_reported_not_silently_discarded(tmp_path):
    folder = tmp_path / "scenario" / "models" / "A"
    folder.mkdir(parents=True)
    (folder / paths.CONFIG_NAME).write_text("not valid = [toml")
    with pytest.raises(ValueError):
        project_paths.model_config(tmp_path / "scenario", "A", shared(tmp_path, "A"))


def test_execution_prefers_exact_model_config_over_explicit_other_runtime(tmp_path):
    project = tmp_path / "scenario"
    own = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    save(own, project / "models" / "B")
    other = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    actual = project_paths.execution_config(project, "B", project / "models" / "B" / "ki", fallback=other)
    assert actual.python == own.python
    assert actual.roles["binaries"] == own.roles["binaries"]
    assert actual.root == project


def test_execution_rejects_missing_materialized_model_config_even_with_fallback(tmp_path):
    project = tmp_path / "scenario"
    fallback = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    save(fallback, project)  # no model-specific B config
    with pytest.raises(FileNotFoundError):
        project_paths.execution_config(project, "B", project / "models" / "B" / "ki", fallback=fallback)


def test_external_legacy_execution_requires_explicit_fallback_not_global(tmp_path):
    project = tmp_path / "scenario"
    fallback = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    save(fallback, project)
    with pytest.raises(FileNotFoundError):
        project_paths.execution_config(project, "A", tmp_path / "external-ki")
    actual = project_paths.execution_config(project, "A", tmp_path / "external-ki", fallback=fallback)
    assert actual.python == fallback.python
    assert actual.root == project
    assert actual is not fallback
    actual.roles["outputs"] = project / "new"
    assert fallback.roles["outputs"] == project / "outputs" / "A"


def test_execution_rejects_materialized_root_of_another_model(tmp_path):
    project = tmp_path / "scenario"
    own = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    save(own, project / "models" / "A")
    with pytest.raises(ValueError, match="KI root"):
        project_paths.execution_config(project, "A", project / "models" / "B" / "ki", fallback=own)


def test_execution_rejects_inner_ki_symlink_to_another_model(tmp_path):
    project = tmp_path / "scenario"
    own = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    save(own, project / "models" / "A")
    other = project / "models" / "B" / "ki"
    other.mkdir(parents=True)
    live = project / "models" / "A" / "ki"
    live.symlink_to(other, target_is_directory=True)
    with pytest.raises(ValueError, match="KI root"):
        project_paths.execution_config(project, "A", live, fallback=own)


def test_execution_rejects_materialized_root_symlink_to_external_shared_ki(tmp_path):
    project = tmp_path / "scenario"
    own = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    save(own, project / "models" / "A")
    external = tmp_path / "external-ki"
    external.mkdir()
    live = project / "models" / "A" / "ki"
    live.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="KI root"):
        project_paths.execution_config(project, "A", live, fallback=own)


def test_execution_does_not_hide_corrupt_model_config_behind_fallback(tmp_path):
    project = tmp_path / "scenario"
    own = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    save(own, project / "models" / "A")
    (project / "models" / "A" / paths.CONFIG_NAME).write_text("broken = [toml")
    with pytest.raises(ValueError):
        project_paths.execution_config(project, "A", tmp_path / "external-ki", fallback=own)


def test_execution_child_discovery_can_use_model_home_without_changing_project_root(tmp_path, monkeypatch):
    project = tmp_path / "scenario"
    own = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    save(own, project / "models" / "B")
    save(project_paths.project_config(project, python=sys.executable), project)
    monkeypatch.setenv("KISS_ROOT", str(project / "models" / "B"))
    monkeypatch.setattr(paths, "_ACTIVE", None)
    actual = paths.active()
    assert actual.root == project
    assert actual.python == own.python


def test_root_retirement_requires_selected_legacy_owner_with_captured_bindings(tmp_path):
    project = tmp_path / "scenario"
    legacy = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    legacy.roles["static"] = project / "outputs" / "B" / "deck"
    save(legacy, project)
    a = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    save(a, project / "models" / "A")
    assert not project_paths.can_write_project_config(project, ["A"])
    assert not project_paths.can_write_project_config(project, ["B"])  # not captured yet
    b = project_paths.model_config(project, "B", shared(tmp_path, "B"))
    save(b, project / "models" / "B")
    assert not project_paths.can_write_project_config(project, ["A"])  # B not selected this time
    assert project_paths.can_write_project_config(project, ["A", "B"])


def test_root_retirement_refuses_lost_or_ambiguous_legacy_bindings(tmp_path):
    project = tmp_path / "scenario"
    legacy = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    legacy.roles["static"] = project / "inputs" / "legacy-deck"
    save(legacy, project)
    captured = project_paths.model_config(project, "A", shared(tmp_path, "A"))
    captured.roles["static"] = project / "inputs" / "static"
    save(captured, project / "models" / "A")
    assert not project_paths.can_write_project_config(project, ["A"])
    # Even equal scenario roles cannot prove ownership when the legacy output
    # owner and runtime belong to different KIs.
    captured.roles["static"] = legacy.roles["static"]
    captured.python = shared(tmp_path, "B").python
    save(captured, project / "models" / "A")
    assert not project_paths.can_write_project_config(project, ["A"])


def test_root_retirement_allows_no_root_or_already_neutral_root(tmp_path):
    project = tmp_path / "scenario"
    assert project_paths.can_write_project_config(project, ["A"])
    save(project_paths.project_config(project, python=sys.executable), project)
    assert project_paths.can_write_project_config(project, ["A"])


def test_root_retirement_preserves_unparseable_root(tmp_path):
    project = tmp_path / "scenario"
    project.mkdir()
    path = project / paths.CONFIG_NAME
    path.write_text("broken = [toml")
    before = path.read_bytes()
    assert not project_paths.can_write_project_config(project, ["A"])
    assert path.read_bytes() == before


@pytest.mark.parametrize("role,target", [
    ("survey", "inputs/user-survey"),
    ("python_env", "custom-python"),
    ("static", "models/B/case"),
    ("forcing", "../external-weather"),
])
def test_neutral_root_is_retained_if_rewrite_would_discard_a_binding(tmp_path, role, target):
    project = tmp_path / "scenario"
    saved = project_paths.project_config(project, python=sys.executable)
    saved.roles[role] = (project / target).resolve()
    save(saved, project)
    before = (project / paths.CONFIG_NAME).read_bytes()
    assert not project_paths.can_write_project_config(project, ["A"])
    assert (project / paths.CONFIG_NAME).read_bytes() == before


def test_neutral_root_safe_input_override_survives_rewrite(tmp_path):
    project = tmp_path / "scenario"
    saved = project_paths.project_config(project, python=sys.executable)
    saved.roles["forcing"] = project / "inputs" / "user-weather"
    save(saved, project)
    assert project_paths.can_write_project_config(project, ["A"])
    actual = project_paths.project_config(project, python=sys.executable)
    assert actual.roles == saved.roles


def test_external_ki_child_normalizes_exact_config_without_a_local_ki_directory(tmp_path):
    import json
    import os
    import subprocess

    old = (tmp_path / "old-project").resolve()
    project = (tmp_path / "moved-project").resolve()
    model_home = project / "models" / "A"
    external = tmp_path / "external-ki"
    external.mkdir()
    saved = paths.KissConfig.default(old)
    saved.python = sys.executable
    saved.roles["forcing"] = Path("inputs/user-weather")
    saved.roles["outputs"] = old / "outputs" / "A"
    save(saved, model_home)
    host = project_paths.execution_config(project, "A", external)
    assert not (model_home / "ki").exists()
    source = str(Path(paths.__file__).resolve().parents[1])
    code = (
        f"import sys;sys.path.insert(0, {source!r});"
        "import json;from kiss_cli.paths import active,P;"
        "print(json.dumps({'root':str(active().root),'forcing':str(P('forcing')),'outputs':str(P('outputs'))}))"
    )
    child = subprocess.run([sys.executable, "-c", code], cwd=project,
                           env=dict(os.environ, KISS_ROOT=str(model_home)),
                           capture_output=True, text=True, check=True, timeout=10)
    assert json.loads(child.stdout) == {
        "root": str(host.root), "forcing": str(host.roles["forcing"]),
        "outputs": str(host.roles["outputs"]),
    }
