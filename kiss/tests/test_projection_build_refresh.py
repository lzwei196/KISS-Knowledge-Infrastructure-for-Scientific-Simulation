"""Host build changes expire readiness without destroying static KI lineage.

Real signed records and exact tree copies; the WSL location is a local fixture,
not a guest execution or a model run.
"""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from kiss_cli import ki_adaptations as adapt, ki_guard, paths, runtime_backend, runtime_context
from kiss_cli import setup, software_verification as verification
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    guest = tmp_path / "guest"
    backend = {"kind": "wsl", "platform": "Linux", "machine": "x86_64",
        "id": "f" * 32, "distro": "Ubuntu", "user": "fixture", "workspace": str(guest),
        "source_hash": "a" * 64, "guest_identity": "c" * 64}
    monkeypatch.setattr(runtime_context, "binding", lambda: dict(backend))
    # Production validation uses WSLBinding's native Linux namespace. This
    # Windows fixture retains all bound fields but locates its app cache locally.
    monkeypatch.setattr(runtime_backend, "WSLBinding", lambda distro, user, workspace, identifier:
                        SimpleNamespace(workspace=workspace))
    (guest / "app" / backend["source_hash"]).mkdir(parents=True)
    library = tmp_path / "library"
    source = library / "models" / "Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Portable Demo\n")
    (source / "tool.py").write_text("output = 'KISSPATH_OUTPUTS/result.csv'\n")
    (source / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: Demo\nnotes: 'KISSPATH_ROOT fixture'\n")
    helpers = library / "ki_tools_common"
    helpers.mkdir()
    (helpers / "common.py").write_text("root = 'KISSPATH_ROOT'\n")
    root = guest / "work" / "Demo"
    root.mkdir(parents=True)
    cfg = paths.KissConfig.default(root)
    cfg.python, cfg.relocation = sys.executable, "none"
    setup.prepare_common(cfg, library)
    (root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    man = Manifest.load(source / "kiss.yaml")
    live = root / "ki"
    ki_guard.enroll(source)
    adapt.materialise(source, live, cfg, model="Demo", library_root=library, manifest=man)
    return SimpleNamespace(root=root, source=source, library=library, man=man, cfg=cfg,
        live=live, backend=backend, guest=guest)


def refresh(c):
    return adapt.refresh_projection(c.live, c.cfg, source=c.source, model="Demo",
                                    library_root=c.library, manifest=c.man)


def legacy(c):
    original = adapt._read(adapt._location(c.live))
    original.pop("projection_binding")
    return adapt._write(adapt._location(c.live), original)


def test_new_static_lineage_survives_app_build_but_readiness_expires(case):
    origin = adapt.projection(case.live, case.cfg)
    old = verification.runtime_identity(case.cfg)
    case.backend["source_hash"] = "b" * 64
    assert verification.runtime_identity(case.cfg) != old
    assert adapt.projection(case.live, case.cfg) == origin
    assert refresh(case) is False
    assert not list(adapt._home().glob("projection-refreshes/*"))


def test_legacy_source_only_refresh_reproduces_exact_bytes_and_preserves_history(case):
    old = legacy(case)
    original_tree = {p: p.read_bytes() for p in case.root.rglob("*") if p.is_file()}
    baseline = ki_guard.require_intact(case.live)
    case.backend["source_hash"] = "b" * 64
    with pytest.raises(adapt.AdaptationError, match="revalidate"):
        adapt.projection(case.live, case.cfg)
    assert adapt._read(adapt._location(case.live)) == old  # ordinary read cannot migrate
    assert refresh(case)
    updated = adapt.projection(case.live, case.cfg)
    assert updated["projected_digest"] == old["projected_digest"]
    assert updated["runtime_identity"] == verification.runtime_identity(case.cfg)
    assert updated["projection_binding"] == verification.projection_binding(case.cfg)
    assert updated["projection_refresh"]["model_readiness"] is False
    assert original_tree == {p: p.read_bytes() for p in case.root.rglob("*") if p.is_file()}
    assert ki_guard.require_intact(case.live) == baseline
    audits = list(adapt._home().glob("projection-refreshes/*.json"))
    assert len(audits) == 1 and adapt._read(audits[0])["previous"] == old
    assert refresh(case) is False
    assert not (case.root / "status.json").exists()


@pytest.mark.parametrize("change", ["python", "unused_role", "relocation", "guest", "user", "distro"])
def test_legacy_refresh_never_masks_other_binding_changes(case, change):
    old = legacy(case)
    case.backend["source_hash"] = "b" * 64
    if change == "python": case.cfg.python += "-other"
    elif change == "unused_role": case.cfg.roles["unused_fixture_role"] = case.root / "other"
    elif change == "relocation": case.cfg.relocation = "port"
    elif change == "guest": case.backend["guest_identity"] = "d" * 64
    else: case.backend[change] += "-other"
    (case.root / paths.CONFIG_NAME).write_text(case.cfg.dumps(), encoding="utf-8")
    with pytest.raises(adapt.AdaptationError, match="source-only"):
        refresh(case)
    assert adapt._read(adapt._location(case.live)) == old


@pytest.mark.parametrize("change", ["live", "portable", "helpers", "signature", "source", "recipe", "missing_build"])
def test_legacy_refresh_rejects_tamper_and_changed_source_context(case, change):
    old = legacy(case)
    case.backend["source_hash"] = "b" * 64
    if change == "live": (case.live / "tool.py").write_text("tamper\n")
    elif change == "portable": (Path(old["portable_root"]) / "tool.py").write_text("tamper\n")
    elif change == "helpers": (case.cfg.roles["ki_tools_common"] / "common.py").write_text("tamper\n")
    elif change == "source": (case.source / "tool.py").write_text("different upstream\n")
    elif change == "recipe": case.man.notes = "different recipe"
    elif change == "missing_build": (case.guest / "app" / ("a" * 64)).rmdir()
    else:
        path = adapt._location(case.live)
        doc = json.loads(path.read_text()); doc["context"]["model"] = "Other"
        path.write_text(json.dumps(doc))
    before = adapt._location(case.live).read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        refresh(case)
    assert adapt._location(case.live).read_bytes() == before
    assert not list(adapt._home().glob("projection-refreshes/*"))


def test_new_static_binding_still_rejects_unused_role_change(case):
    case.cfg.roles["unused_fixture_role"] = case.root / "new-role"
    with pytest.raises(adapt.AdaptationError, match="runtime binding changed"):
        adapt.projection(case.live, case.cfg)


def test_changed_projection_implementation_cannot_renew_different_bytes(case, monkeypatch):
    old = legacy(case)
    case.backend["source_hash"] = "b" * 64
    original = adapt.project_runtime
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        (Path(args[1]) / "tool.py").write_text("different projection\n")
        return result
    monkeypatch.setattr(adapt, "project_runtime", changed)
    with pytest.raises(adapt.AdaptationError, match="differs from the intact"):
        refresh(case)
    assert adapt._read(adapt._location(case.live)) == old


def test_declared_policy_refresh_requires_exact_current_projection(case, monkeypatch):
    # This is a fresh setup fixture for the explicit portable path route.
    source = case.library / "models" / "Declared"
    source.mkdir()
    (source / "SKILL.md").write_text("# Declared\n")
    (source / "tool.py").write_text("root = 'KISSPATH_CURRENT_KI'\n")
    (source / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: Declared\nruntime_paths:\n  version: 1\n  mode: role_tokens\n")
    man = Manifest.load(source / "kiss.yaml")
    cfg = copy.deepcopy(case.cfg)
    cfg.root = case.root.parent / "Declared"
    cfg.root.mkdir()
    (cfg.root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    live = cfg.root / "ki"
    ki_guard.enroll(source)
    adapt.materialise(source, live, cfg, model="Declared", library_root=case.library, manifest=man)
    before = adapt.projection(live, cfg)
    monkeypatch.setattr(adapt, "_portable_path_identity", lambda: "renewed-path-policy")
    with pytest.raises(adapt.AdaptationError, match="policy changed"):
        adapt.projection(live, cfg)
    assert adapt.refresh_projection(live, cfg, source=source, model="Declared",
                                    library_root=case.library, manifest=man)
    after = adapt.projection(live, cfg)
    assert after["projected_digest"] == before["projected_digest"]
    assert after["context"]["path_normalizer"] == "renewed-path-policy"


@pytest.mark.parametrize("damage", [None, "scope", "inventory"])
def test_legacy_fresh_policy_refresh_rechecks_whole_static_proof(tmp_path, monkeypatch, damage):
    from kiss_cli import ki_fresh_paths as fresh
    from .test_fresh_path_projection import case as fresh_case
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    source, cfg, _target = fresh_case(tmp_path)
    live = cfg.root / "ki"
    (cfg.root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    ki_guard.enroll(source)
    adapt.materialise(source, live, cfg, model="WOFOST")
    old = adapt.projection(live, cfg)
    if damage:
        if damage == "scope": old["path_projection"]["scope"] = "runtime_pass"
        else: old["path_projection"]["ordinary_files"]["notes.txt"]["sha256"] = "0" * 64
        adapt._write(adapt._location(live), old)
    before = adapt._location(live).read_bytes()
    monkeypatch.setattr(fresh, "source_digest", lambda: "0" * 64)
    with pytest.raises(ValueError):
        adapt.projection(live, cfg)
    if damage:
        with pytest.raises(ValueError):
            adapt.refresh_projection(live, cfg, source=source, model="WOFOST", library_root=None)
        assert adapt._location(live).read_bytes() == before
    else:
        assert adapt.refresh_projection(live, cfg, source=source, model="WOFOST", library_root=None)
        updated = adapt.projection(live, cfg)
        assert updated["projected_digest"] == old["projected_digest"]
        assert updated["path_projection"]["policy_sha256"] == "0" * 64
        assert updated["projection_refresh"]["model_readiness"] is False


@pytest.mark.parametrize("pending", [False, True])
def test_legacy_project_refresh_uses_exact_saved_model_binding_and_original_library(case, pending):
    from kiss_cli import project_paths, project_verification, ki_data_lineage
    project = case.guest / "projects" / "existing"
    project.mkdir(parents=True)
    cfg = project_paths.model_config(project, "Demo", case.cfg)
    home = project / "models" / "Demo"
    cfg.roles["ki_tools_common"] = home / "ki_tools_common"
    setup.prepare_common(cfg, case.library)
    home.mkdir(parents=True, exist_ok=True)
    saved = home / paths.CONFIG_NAME
    saved.write_text(cfg.dumps(), encoding="utf-8")
    live = home / "ki"
    adapt.materialise(case.source, live, cfg, model="Demo", library_root=case.library, manifest=case.man)
    original = adapt._read(adapt._location(live)); original.pop("projection_binding")
    adapt._write(adapt._location(live), original)
    files = {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    case.backend["source_hash"] = "b" * 64
    with pytest.raises(adapt.AdaptationError, match="revalidate"):
        ki_data_lineage.require_projection(project, "Demo", live, cfg)
    # Caller uses the same strict loader as project preflight; no root fallback.
    current = project_verification._config(project, home, "Demo")
    runtime_manifest = Manifest.load(live / "kiss.yaml")
    assert runtime_manifest.notes != case.man.notes
    if pending:
        from kiss_cli import project_setup_repair
        project_setup_repair._write(live, {
            "policy": project_setup_repair.POLICY, "implementation": project_setup_repair._policy(),
            "status": "pending", "binding": {"model": "Demo", "source_root": str(case.source),
                "setup_root": str(case.root), "library_root": str(case.library),
                "effective_manifest": original["effective_manifest"]}})
        before = adapt._location(live).read_bytes()
        with pytest.raises(ValueError, match="incomplete"):
            adapt.refresh_project_projection(live, current, model="Demo", manifest=runtime_manifest)
        assert adapt._location(live).read_bytes() == before
        assert files == {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
        return
    assert adapt.refresh_project_projection(live, current, model="Demo", manifest=runtime_manifest)
    updated = ki_data_lineage.require_projection(project, "Demo", live, current)
    assert updated["projected_digest"] == original["projected_digest"]
    assert updated["library_root"] == str(case.library)
    assert files == {p: p.read_bytes() for p in project.rglob("*") if p.is_file()}
    assert not (project / ".geoforge" / "project-verification").exists()
