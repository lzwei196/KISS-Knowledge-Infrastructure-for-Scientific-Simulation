"""Fresh setup refreshes only a byte-identical projection's runtime proof.

Real local Python identity probes and static WOFOST projection are exercised;
no WOFOST preflight, simulation, pip install, network or KDT bypass is used.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import venv

import pytest

from kiss_cli import (install, ki_adaptations, ki_fresh_paths, ki_guard,
                     ki_verification, paths, setup, setup_runtime as runtime)
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest
from .test_ki_path_contracts import FIXTURES, MANIFEST


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    library = tmp_path / "library"
    source = library / "models" / "WOFOST"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Published shape fixture; no scientific execution\n")
    (source / "preflight_check.py").write_bytes((FIXTURES / "wofost_preflight_published.py").read_bytes())
    (source / "run_and_score.py").write_bytes((FIXTURES / "wofost_entrypoint_published.py").read_bytes())
    (source / ki_fresh_paths.MANIFEST).write_text(MANIFEST, encoding="utf-8")
    common = library / "ki_tools_common"
    (common / "ki_tools_common").mkdir(parents=True)
    (common / "ki_tools_common/__init__.py").write_text("# fixture source\n")
    root = tmp_path / "workspace"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    environment = cfg.roles["python_env"]
    venv.EnvBuilder(with_pip=False).create(environment)
    cfg.python = str(environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    cfg.relocation = "none"
    ki, man = KI("WOFOST", source), Manifest(model="WOFOST")
    ki_guard.enroll(source)
    ticket = runtime.begin(root)
    assert ticket is not None
    setup.prepare_common(cfg, library)
    (root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    setup.materialise_active(source, root / "ki", cfg, manifest=man, library_root=library)
    live = KI("WOFOST", root / "ki")
    runtime.capture(ticket, ki, live, cfg, library_root=library, manifest=man)
    return SimpleNamespace(root=root, cfg=cfg, ki=ki, live=live, man=man,
                           library=library, ticket=ticket)


def refresh(c):
    return runtime.refresh(c.ticket, c.ki, c.live, c.cfg, library_root=c.library, manifest=c.man)


def replace_launcher(c):
    # PE/ELF loaders ignore an appended data overlay. This changes actual file
    # identity while retaining a real interpreter and unchanged venv prefix.
    executable = Path(c.cfg.python)
    content = executable.read_bytes()
    if executable.is_symlink():
        executable.unlink()
    executable.write_bytes(content + b"\nGeoForge fresh setup identity fixture\n")
    if os.name != "nt":
        executable.chmod(0o755)


def authority(c):
    return ki_adaptations._location(c.live.root).read_bytes()


def test_same_path_launcher_replacement_refreshes_proof_without_ki_or_readiness_changes(case):
    c = case
    baseline = ki_guard.require_intact(c.live.root)
    old = ki_adaptations.projection(c.live.root, c.cfg)
    old_config = (c.root / paths.CONFIG_NAME).read_bytes()
    old_helpers = runtime._helpers(c.cfg)
    replace_launcher(c)
    with pytest.raises(ValueError, match="runtime/helper identity changed"):
        ki_adaptations.projection(c.live.root, c.cfg)
    assert refresh(c) is True
    renewed = ki_adaptations.projection(c.live.root, c.cfg)
    assert renewed["projected_digest"] == old["projected_digest"]
    assert renewed["path_projection"]["runtime"]["selected_python"] != old["path_projection"]["runtime"]["selected_python"]
    assert ki_guard.require_intact(c.live.root) == baseline
    assert (c.root / paths.CONFIG_NAME).read_bytes() == old_config
    assert runtime._helpers(c.cfg) == old_helpers
    assert not (c.root / "status.json").exists()
    assert not (c.root / "installation-test.json").exists()
    assert renewed["runtime_refresh"]["preflight_passed"] is False
    assert all(renewed["path_projection"][key] is False for key in
               ("preflight_passed", "native_execution", "model_execution", "scientific_validation"))
    assert refresh(c) is False, "an unchanged runtime is not refreshed twice"
    runtime.close(c.ticket)
    # Reopen uses ordinary signed projection validation; no open ticket needed.
    assert ki_adaptations.projection(c.live.root, setup.load_runtime_config(c.root)) == renewed
    with pytest.raises(ValueError, match="closed"):
        refresh(c)


def test_unchanged_runtime_is_a_complete_noop(case):
    before = authority(case)
    assert refresh(case) is False
    assert authority(case) == before


@pytest.mark.parametrize("damage", ["source", "active", "helper", "helper_marker", "helper_source",
                                  "runtime_path", "data_path", "missing_runtime", "invalid_runtime",
                                  "projection", "ticket", "closed"])
def test_refuses_other_changes_and_preserves_projection_authority(case, damage):
    c = case
    replace_launcher(c)
    if damage in {"source", "active"}:
        tree = c.ki.root if damage == "source" else c.live.root
        (tree / "SKILL.md").write_text("unreviewed edit\n")
    elif damage == "helper":
        (c.cfg.roles["ki_tools_common"] / "ki_tools_common/__init__.py").write_text("changed\n")
    elif damage == "helper_marker":
        (c.cfg.roles["ki_tools_common"] / ".geoforge-common.json").write_text("{}")
    elif damage == "helper_source":
        (c.library / "ki_tools_common/ki_tools_common/__init__.py").write_text("changed\n")
    elif damage in {"runtime_path", "data_path"}:
        if damage == "runtime_path":
            c.cfg.python = str(c.root / "other-python.exe")
        else:
            c.cfg.roles["data"] = c.root / "other-data"
        (c.root / paths.CONFIG_NAME).write_text(c.cfg.dumps())
    elif damage == "missing_runtime":
        Path(c.cfg.python).unlink()
    elif damage == "invalid_runtime":
        Path(c.cfg.python).write_bytes(b"not an interpreter")
    elif damage == "projection":
        doc = json.loads(authority(c))
        doc["projected_digest"] = "0" * 64
        ki_adaptations._location(c.live.root).write_text(json.dumps(doc))
    elif damage == "ticket":
        runtime._location(c.ticket).write_text("{}")
    else:
        runtime.close(c.ticket)
    before = authority(c)
    with pytest.raises((ValueError, OSError)):
        refresh(c)
    assert authority(c) == before


def test_previous_installation_cannot_claim_freshness_by_editing_status(case):
    c = case
    (c.root / "status.json").write_text('{"ok":false,"verified":false}')
    assert runtime.begin(c.root) is None
    assert runtime.begin(c.root, allowed=False) is None
    # Even deleting the active directory cannot erase host enrollment.
    moved = c.root / "preserved-ki"
    c.live.root.rename(moved)
    assert runtime.begin(c.root) is None


def test_fresh_ticket_requires_saved_configuration_before_capture(tmp_path, monkeypatch):
    # No forged empty ticket can refresh another prepared installation.
    root = tmp_path / "new"
    root.mkdir()
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    ticket = runtime.begin(root)
    assert runtime._read(ticket)["state"] == "started"
    with pytest.raises(ValueError, match="closed or changed"):
        runtime._read(ticket, state="captured")
    runtime.close(ticket)


def test_mid_projection_runtime_change_cannot_publish_evidence(case, monkeypatch):
    c = case
    replace_launcher(c)
    original = ki_adaptations.project_runtime
    def race(*args, **kwargs):
        report = original(*args, **kwargs)
        Path(c.cfg.python).write_bytes(Path(c.cfg.python).read_bytes() + b"raced")
        return report
    monkeypatch.setattr(ki_adaptations, "project_runtime", race)
    before = authority(c)
    with pytest.raises(ValueError):
        refresh(c)
    assert authority(c) == before


def test_different_candidate_bytes_cannot_be_refreshed(case, monkeypatch):
    c = case
    replace_launcher(c)
    original = ki_adaptations.project_runtime
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        (Path(args[1]) / "SKILL.md").write_text("different bytes\n")
        return result
    monkeypatch.setattr(ki_adaptations, "project_runtime", changed)
    before = authority(c)
    with pytest.raises(ValueError, match="differs"):
        refresh(c)
    assert authority(c) == before


def test_generic_fresh_setup_does_not_gain_new_helper_or_local_python_requirement(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("# Generic fixture\n")
    root = tmp_path / "workspace"
    root.mkdir()
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable  # Deliberately external, with no prepared helpers.
    (root / paths.CONFIG_NAME).write_text(cfg.dumps())
    ticket = runtime.begin(root)
    ki_guard.enroll(source)
    ki_adaptations.materialise(source, root / "ki", cfg, model="Demo")
    ki, live, man = KI("Demo", source), KI("Demo", root / "ki"), Manifest(model="Demo")
    runtime.capture(ticket, ki, live, cfg, library_root=tmp_path, manifest=man)
    assert runtime._read(ticket)["state"] == "not_applicable"
    assert runtime.refresh(ticket, ki, live, cfg, library_root=tmp_path, manifest=man) is False
    runtime.close(ticket)
