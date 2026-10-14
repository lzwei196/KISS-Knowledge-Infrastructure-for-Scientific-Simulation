"""Final setup verification must use one valid, saved runtime binding."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import (api, catalog, gui, install, install_locations, ki_guard,
                      ki_updates, ki_verification, paths, providers, setup,
                      software_verification)


@pytest.fixture
def case(tmp_path):
    library = tmp_path / "snapshot"
    source = library / "models/Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    # This harmless fixture can prove the selected launcher through a real child
    # process. Its only artifact stays outside the protected KI tree.
    (source / "preflight_check.py").write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "marker = Path(__file__).resolve().parent.parent / 'preflight-runtime.json'\n"
        "marker.write_text(json.dumps({'python': sys.executable}), encoding='utf-8')\n"
        "print('Runtime fixture completed')\n", encoding="utf-8")
    (source / "kiss.yaml").write_text(yaml.safe_dump({
        "kiss_manifest_version": 1, "model": "Demo", "verified": "unverified"}))
    (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
        "content_sha256": "a" * 64, "trees": {"shared_tools": "b" * 40}}))
    shared = library / "ki_tools_common" / "ki_tools_common"
    shared.mkdir(parents=True)
    (shared / "__init__.py").write_text("# fixture helpers\n", encoding="utf-8")
    workroot = tmp_path / "work"
    root = workroot / "demo"
    root.mkdir(parents=True)
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    cfg.relocation = "none"
    setup.prepare_common(cfg, library)
    (root / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    ki = catalog.KI("Demo", source)
    ki_guard.enroll(source)
    setup.materialise_active(source, root / "ki", cfg)
    live = catalog.KI("Demo", root / "ki")
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler.workroot = workroot
    handler.catalog = SimpleNamespace(models_dir=library / "models")
    handler._ki = lambda _name: ki
    return SimpleNamespace(handler=handler, ki=ki, live=live, cfg=cfg,
                           root=root, workroot=workroot, library=library)


def save_config(case, **changes):
    updated = deepcopy(case.cfg)
    for key, value in changes.items():
        setattr(updated, key, value)
    (case.root / "kiss.toml").write_text(updated.dumps(), encoding="utf-8")
    return updated


def install_spies(monkeypatch, *, preflight_ok=True, requirements_ok=True):
    seen = SimpleNamespace(preflight=[], requirements=[])

    def preflight(ki, python, cfg, **kwargs):
        seen.preflight.append((ki, python, cfg, kwargs))
        return install.Step("preflight", preflight_ok, "independent fixture preflight")

    def requirements(manifest, cfg, **kwargs):
        seen.requirements.append(cfg)
        return install.Step("manifest-requirements", requirements_ok, "fixture requirements")

    monkeypatch.setattr(install, "run_preflight", preflight)
    monkeypatch.setattr(software_verification, "requirements", requirements)
    return seen


def finish(case, **kwargs):
    return case.handler._record_agent_preflight(
        case.ki, case.live, case.cfg, case.root, lambda _piece: None, **kwargs)


def saved_status(case):
    return json.loads((case.root / "status.json").read_text(encoding="utf-8"))


def assert_cleared(case):
    state = saved_status(case)
    assert not state["ok"]
    assert state["verified_at"] is None
    assert state["verification_identity"] is None
    assert state["ki_content_digest"] is None
    assert state["primary_error"]["detail"]
    record = json.loads((case.root / install_locations.RECORD_FILE).read_text())
    assert record["workspace"] == str(case.root)
    assert not record["verified"] and record["verified_at"] is None


def seed_success(case):
    (case.root / "status.json").write_text(json.dumps({
        "ok": True, "verified_at": 123, "verification_identity": {"old": True},
        "ki_content_digest": "old-digest", "steps": []}))
    install_locations.record(case.ki.name, case.root, case.cfg,
                             ki_root=case.live.root, verified=True)


def assert_binding_recorded(case, seen, expected):
    assert len(seen.requirements) == 1
    checked = seen.preflight[-1][2]
    assert seen.preflight[-1][1] == expected.python
    assert checked.python == expected.python and checked.roles == expected.roles
    assert checked.root == expected.root and checked.relocation == expected.relocation
    assert seen.requirements[0] is checked, "requirements must use the verified runtime object"
    record = json.loads((case.root / install_locations.RECORD_FILE).read_text())
    assert record["python"] == expected.python
    assert record["binaries"] == str(expected.roles["binaries"])
    assert record["workspace"] == str(case.root) and record["verified"]
    state = saved_status(case)
    assert state["ok"] and state["verification_identity"]
    assert state["ki_content_digest"] == ki_verification.content_digest(case.live.root)


def test_replacement_runtime_cannot_reuse_an_old_projected_ki(case, monkeypatch):
    replacement = case.root / "runtime2" / "python.exe"
    replacement.parent.mkdir()
    replacement.write_bytes(b"fixture interpreter; never executed")
    roles = {**case.cfg.roles, "python_env": replacement.parent,
             "binaries": case.root / "engine2"}
    expected = save_config(case, python=str(replacement), roles=roles)
    seen = install_spies(monkeypatch)
    assert not finish(case)
    assert seen.preflight == [] and seen.requirements == []
    assert_cleared(case)
    assert saved_status(case)["primary_error"]["name"] == "runtime-projection"
    assert paths.KissConfig.load(case.root).python == expected.python


@pytest.mark.parametrize("change", ["python", "roles", "relocation"])
def test_early_check_is_rejected_when_saved_projection_binding_changes(case, monkeypatch, change):
    if change == "python":
        updated = save_config(case, python="selected-python")
    elif change == "roles":
        updated = save_config(case, roles={**case.cfg.roles, "ki_tools_common": case.root / "new-tools"})
    else:
        updated = save_config(case, relocation="port")
    seen = install_spies(monkeypatch)
    assert not finish(case, check=install.Step("preflight", True, "early result"))
    assert seen.preflight == [] and seen.requirements == []
    assert_cleared(case)
    assert saved_status(case)["primary_error"]["name"] == "runtime-projection"


def test_unchanged_saved_binding_reuses_early_check(case, monkeypatch):
    seen = install_spies(monkeypatch)
    assert finish(case, check=install.Step("preflight", True, "early result"))
    assert seen.preflight == []
    assert len(seen.requirements) == 1
    assert seen.requirements[0].python == case.cfg.python
    assert saved_status(case)["steps"][-1]["detail"] == "early result"


@pytest.mark.parametrize("invalid", ["missing", "malformed", "wrong_root", "missing_python",
    "nonstring_python", "empty_python", "paths_list", "role_integer", "missing_root",
    "nonstring_relocation", "kiss_list"])
def test_invalid_saved_config_clears_prior_success_without_execution(case, monkeypatch, invalid):
    seed_success(case)
    path = case.root / "kiss.toml"
    text = path.read_text(encoding="utf-8")
    if invalid == "missing":
        path.unlink()
        # A valid ancestor configuration must not be substituted for the missing local file.
        (case.workroot / "kiss.toml").write_text(paths.KissConfig.default(case.workroot).dumps())
    elif invalid == "malformed":
        path.write_text("[kiss\nnot valid TOML", encoding="utf-8")
    elif invalid == "wrong_root":
        save_config(case, root=case.root.parent / "redirected")
    elif invalid == "missing_root":
        path.write_text("\n".join(line for line in text.splitlines()
                                  if not line.startswith("root =")), encoding="utf-8")
    elif invalid == "nonstring_relocation":
        path.write_text("\n".join("relocation = 123" if line.startswith("relocation =")
                                  else line for line in text.splitlines()), encoding="utf-8")
    elif invalid == "kiss_list":
        path.write_text("kiss = []\n[paths]\n", encoding="utf-8")
    elif invalid in {"missing_python", "nonstring_python", "empty_python"}:
        lines = text.splitlines()
        value = {"missing_python": None, "nonstring_python": "python = 123",
                 "empty_python": "python = ''"}[invalid]
        lines = [line for line in lines if not line.startswith("python =")]
        if value is not None:
            lines.insert(lines.index("[kiss]") + 1, value)
        path.write_text("\n".join(lines), encoding="utf-8")
    elif invalid == "paths_list":
        path.write_text("paths = []\n" + text.split("[paths]")[0], encoding="utf-8")
    else:
        prefix, _ = text.split("[paths]")
        path.write_text(prefix + "[paths]\npython_env = 42\n", encoding="utf-8")
    seen = install_spies(monkeypatch)
    assert not finish(case, check=install.Step("preflight", True, "old pass"))
    assert seen.preflight == [] and seen.requirements == []
    assert_cleared(case)
    assert not (case.root.parent / "redirected").exists()


def test_explicit_workspace_cannot_be_redirected_by_stale_config_object(case, monkeypatch):
    seed_success(case)
    original = case.root
    other = case.root.parent / "other"
    other.mkdir()
    (other / "kiss.toml").write_text(paths.KissConfig.default(other).dumps())
    case.cfg.root = other
    seen = install_spies(monkeypatch)
    result = finish(case, check=install.Step("preflight", True, "untrusted old pass"))
    # Rejecting this inconsistent handoff is safer than following the stale object's root.
    assert not result
    assert seen.preflight == [] and seen.requirements == []
    assert_cleared(case)
    assert case.root == original
    assert not (other / "status.json").exists()
    assert not (other / install_locations.RECORD_FILE).exists()


def test_existing_external_interpreter_is_a_valid_saved_selection(case, monkeypatch):
    case.cfg.python = "old-interpreter"
    expected = save_config(case, python=sys.executable)
    seen = install_spies(monkeypatch)
    assert finish(case)
    assert_binding_recorded(case, seen, expected)


def test_saved_launcher_runs_actual_preflight_without_changing_ki(case):
    before = ki_verification.content_digest(case.live.root)
    # The TOML already names the real interpreter; only the stale in-memory
    # binding is unusable. No preflight, process runner or requirements mocks.
    case.cfg.python = str(case.root / "missing-old-runtime" / "python.exe")
    marker = case.root / "preflight-runtime.json"
    assert not marker.exists()
    assert finish(case)
    assert not marker.exists(), "the preflight must not write into the original workspace"
    state = saved_status(case)
    check = next(step for step in state["steps"] if step["name"] == "preflight")
    marker = Path(check["evidence"]["execution_root"]).parent / "preflight-runtime.json"
    evidence = json.loads(marker.read_text(encoding="utf-8"))
    assert Path(evidence["python"]).resolve() == Path(sys.executable).resolve()
    assert ki_verification.content_digest(case.live.root) == before
    ki_guard.require_intact(case.live.root)
    assert state["ok"] and state["ki_content_digest"] == before
    record = json.loads((case.root / install_locations.RECORD_FILE).read_text())
    assert record["python"] == sys.executable and record["verified"]


def test_failed_fresh_check_cannot_reuse_old_runtime_pass(case, monkeypatch):
    seed_success(case)
    save_config(case, python="new-but-failing-python")
    seen = install_spies(monkeypatch, preflight_ok=False)
    assert not finish(case, check=install.Step("preflight", True, "old environment passed"))
    assert seen.preflight == [] and seen.requirements == []
    assert_cleared(case)


@pytest.mark.parametrize("failure", ["native", "requirements", "ki_drift", "cancelled"])
def test_reloading_does_not_weaken_other_final_verification_gates(case, monkeypatch, failure):
    seed_success(case)
    seen = install_spies(monkeypatch, preflight_ok=failure != "native",
                         requirements_ok=failure != "requirements")
    if failure == "ki_drift":
        (case.live.root / "SKILL.md").write_text("unverified change", encoding="utf-8")
    assert not finish(case, stop=(lambda: failure == "cancelled"))
    assert_cleared(case)


@pytest.mark.parametrize("kind", ["api", "cli"])
def test_provider_saved_runtime_cannot_certify_the_previously_projected_ki(case, monkeypatch, kind):
    handler = case.handler
    (case.root / "CLAUDE.md").write_text("Fixture setup contract", encoding="utf-8")
    output = []
    handler._open_stream = lambda: None
    handler._end_stream = lambda: None
    handler._chunk = lambda piece: output.append(piece) or True
    handler._validate_binding = lambda _req: None
    handler._helper_repo_root = lambda: case.library
    monkeypatch.setattr(setup, "prepare", lambda *args: (case.live, case.cfg))
    monkeypatch.setattr(gui.prompt, "compose", lambda *args, **kwargs: "Fixture prompt")
    monkeypatch.setattr(setup, "agent_task", lambda *args, **kwargs: "Fixture task")
    monkeypatch.setattr(gui, "_with_heartbeats", lambda stream, **kwargs: stream)
    seen = install_spies(monkeypatch)
    original_preflight = install.run_preflight

    def preflight(*args, **kwargs):
        result = original_preflight(*args, **kwargs)
        return install.Step("preflight", False, "needs replacement runtime") if len(seen.preflight) == 1 else result

    monkeypatch.setattr(install, "run_preflight", preflight)
    updated = deepcopy(case.cfg)
    updated.python = "provider-selected-python"
    updated.roles["python_env"] = case.root / "provider-env"

    def provider(*args, **kwargs):
        (case.root / "kiss.toml").write_text(updated.dumps(), encoding="utf-8")
        yield "Provider saved the replacement environment.\n"

    if kind == "api":
        monkeypatch.setattr(api, "run", provider)
        want = "api:deepseek"
    else:
        fake = providers.Provider(name="fixture", binary="fixture", argv=["fixture"],
                                  output="text", label="Fixture CLI")
        monkeypatch.setitem(providers.PROVIDERS, "fixture", fake)
        monkeypatch.setattr(providers, "run", provider)
        want = "cli:fixture"
    handler._stream_agent_setup({"model": "Demo", "provider": want})
    assert len(seen.preflight) == 1, "the final host gate must refuse the stale projection before launch"
    assert seen.requirements == []
    assert_cleared(case)
    assert saved_status(case)["primary_error"]["name"] == "runtime-projection"
    assert any("GeoForge final check: FAIL" in piece for piece in output)
