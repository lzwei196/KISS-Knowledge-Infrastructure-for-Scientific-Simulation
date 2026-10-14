"""A successful software check certifies its saved runtime, not every later one."""
from copy import deepcopy
import json
import sys
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import (catalog, gui, install, ki_guard, ki_updates, paths,
                      setup, software_verification)


@pytest.fixture(params=["bundled", "snapshot"])
def case(tmp_path, request, monkeypatch):
    library = tmp_path / request.param
    source = library / "models" / "Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    (source / "preflight_check.py").write_text("print('fixture')\n", encoding="utf-8")
    (source / "kiss.yaml").write_text(yaml.safe_dump({
        "kiss_manifest_version": 1, "model": "Demo", "verified": "unverified"}), encoding="utf-8")
    if request.param == "snapshot":
        (library / ki_updates.SNAPSHOT_MANIFEST).write_text(json.dumps({
            "content_sha256": "a" * 64, "trees": {"shared_tools": "b" * 40}}), encoding="utf-8")
        shared = library / "ki_tools_common" / "ki_tools_common"
        shared.mkdir(parents=True)
        (shared / "__init__.py").write_text("# fixture helpers\n", encoding="utf-8")
    workroot = tmp_path / "work"
    root = workroot / "demo"
    root.mkdir(parents=True)
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    cfg.relocation = "none"
    if request.param == "snapshot":
        setup.prepare_common(cfg, library)
    (root / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
    ki = catalog.KI("Demo", source)
    ki_guard.enroll(source)
    setup.materialise_active(source, root / "ki", cfg)
    handler = object.__new__(gui.Handler)
    handler.repo_root = handler.library_root = library
    handler.workroot = workroot
    monkeypatch.setattr(install, "run_preflight", lambda *args, **kwargs:
                        install.Step("preflight", True, "fresh fixture check"))
    monkeypatch.setattr(software_verification, "requirements", lambda *args, **kwargs:
                        install.Step("manifest-requirements", True, "fixture requirements"))
    return SimpleNamespace(handler=handler, ki=ki, live=catalog.KI("Demo", root / "ki"),
                           cfg=cfg, root=root, workroot=workroot, library=library,
                           config=root / paths.CONFIG_NAME, status=root / "status.json")


def finish(case):
    return case.handler._record_agent_preflight(
        case.ki, case.live, case.cfg, case.root, lambda _piece: None)


def fake_builtin_prerequisites(monkeypatch):
    """Keep the real install/status lifecycle, replacing external setup work."""
    for name in ("ensure_python_env", "check_system_deps", "install_python_deps"):
        monkeypatch.setattr(install, name, lambda *args, **kwargs:
                            install.Step("prerequisite", True, "fixture ready"))
    monkeypatch.setattr(install, "needs_shared_tools", lambda *args: False)
    monkeypatch.setattr(install, "acquire", lambda *args, **kwargs:
                        (install.Step("acquire", True, "fixture existing software"), None))


def assert_current_verification_revoked(case):
    saved = json.loads(case.status.read_text(encoding="utf-8"))
    assert not saved["ok"]
    assert saved["verified_at"] is None
    assert saved.get("runtime_identity") is None
    assert not case.handler._status_for(case.ki)["can_run"]
    return saved


def save_changed(case, change):
    cfg = deepcopy(case.cfg)
    if change == "python":
        cfg.python = str(case.root / "other-runtime" / "python.exe")
    elif change == "relocation":
        cfg.relocation = "port"
    else:
        cfg.roles[change] = case.root / ("replacement-" + change)
    case.config.write_text(cfg.dumps(), encoding="utf-8")
    return cfg


def assert_stale_without_rewriting_history(case):
    before_status = case.status.read_bytes()
    before_config = case.config.read_bytes() if case.config.exists() else None
    state = case.handler._status_for(case.ki)
    assert not state["can_run"], "an earlier pass cannot verify a changed or unknown runtime"
    assert state["requires_reverification"]
    assert state["verified_at"] is None
    assert state["primary_error"], "the GUI must explain why verification is stale"
    assert case.status.read_bytes() == before_status, "status reads preserve the original successful evidence"
    if before_config is None:
        assert not case.config.exists()
    else:
        assert case.config.read_bytes() == before_config, "readiness checks must not repair or rewrite configuration"
    return state


def test_final_verification_records_the_runtime_that_was_checked(case):
    assert finish(case)
    saved = json.loads(case.status.read_text(encoding="utf-8"))
    assert isinstance(saved.get("runtime_identity"), str) and saved["runtime_identity"]
    assert saved["runtime_identity"] == software_verification.runtime_identity(case.cfg)
    assert case.handler._status_for(case.ki)["can_run"]


@pytest.mark.parametrize("previous_installation_only", [None, True])
def test_full_agent_verification_clears_stale_install_only_failure(case, previous_installation_only):
    prior = {"ok": False, "installation_ready": False}
    if previous_installation_only is not None:
        prior["installation_only"] = previous_installation_only
    case.status.write_text(json.dumps(prior), encoding="utf-8")

    assert finish(case)

    saved = json.loads(case.status.read_text(encoding="utf-8"))
    assert saved["ok"] and saved["verified_at"] is not None
    assert saved["installation_only"] is False
    assert saved["installation_ready"] is None
    assert saved["runtime_identity"] == software_verification.runtime_identity(case.cfg)
    assert case.handler._status_for(case.ki)["can_run"]


@pytest.mark.parametrize("change", ["python", "binaries", "home", "ki_tools_common", "relocation"])
def test_relevant_runtime_changes_require_reverification(case, change):
    assert finish(case)
    assert case.handler._status_for(case.ki)["can_run"]
    save_changed(case, change)
    assert_stale_without_rewriting_history(case)


@pytest.mark.parametrize("invalid", ["deleted", "malformed", "wrong_root", "missing_python", "legacy_backslashes"])
def test_missing_or_invalid_exact_saved_config_cannot_reuse_a_pass(case, invalid):
    assert finish(case)
    text = case.config.read_text(encoding="utf-8")
    if invalid == "deleted":
        case.config.unlink()
        # Nearest-parent discovery is appropriate elsewhere, not for proving
        # which exact workspace configuration the old check used.
        (case.workroot / paths.CONFIG_NAME).write_text(case.cfg.dumps(), encoding="utf-8")
    elif invalid == "malformed":
        case.config.write_text("[kiss\ninvalid TOML", encoding="utf-8")
    elif invalid == "wrong_root":
        changed = deepcopy(case.cfg)
        changed.root = case.root.parent / "redirected"
        case.config.write_text(changed.dumps(), encoding="utf-8")
    elif invalid == "missing_python":
        case.config.write_text("\n".join(line for line in text.splitlines()
                                         if not line.startswith("python =")), encoding="utf-8")
    else:
        case.config.write_text("\n".join(
            r'python = "C:\Users\Legacy\python.exe"' if line.startswith("python =") else line
            for line in text.splitlines()), encoding="utf-8")
    assert_stale_without_rewriting_history(case)
    assert not (case.root.parent / "redirected").exists()


def test_historical_pass_without_runtime_identity_requires_one_recheck(case):
    assert finish(case)
    saved = json.loads(case.status.read_text(encoding="utf-8"))
    saved.pop("runtime_identity", None)
    case.status.write_text(json.dumps(saved), encoding="utf-8")
    state = assert_stale_without_rewriting_history(case)
    assert state["checked_at"] == saved["checked_at"]


@pytest.mark.parametrize("change", ["none", "comments", "role_order", "root_spelling"])
def test_nonsemantic_config_changes_preserve_current_readiness(case, change):
    assert finish(case)
    if change == "comments":
        case.config.write_text("# Local note; no runtime change.\n" +
                               case.config.read_text(encoding="utf-8") + "\n# End\n", encoding="utf-8")
    elif change == "role_order":
        reordered = deepcopy(case.cfg)
        reordered.roles = dict(reversed(list(reordered.roles.items())))
        case.config.write_text(reordered.dumps(), encoding="utf-8")
    elif change == "root_spelling":
        equivalent = deepcopy(case.cfg)
        equivalent.root = case.root / ".." / case.root.name
        case.config.write_text(equivalent.dumps(), encoding="utf-8")
    before_status = case.status.read_bytes()
    before_config = case.config.read_bytes()
    assert case.handler._status_for(case.ki)["can_run"]
    assert case.status.read_bytes() == before_status
    assert case.config.read_bytes() == before_config


def test_reverification_cannot_relabel_an_old_projection_with_new_runtime(case):
    assert finish(case)
    first = json.loads(case.status.read_text(encoding="utf-8"))
    changed = save_changed(case, "python")
    assert_stale_without_rewriting_history(case)
    assert not finish(case)
    second = json.loads(case.status.read_text(encoding="utf-8"))
    assert second["runtime_identity"] is None
    assert second["primary_error"]["name"] == "runtime-projection"
    assert not case.handler._status_for(case.ki)["can_run"]


def test_config_change_during_preflight_cannot_certify_the_new_binding(case, monkeypatch):
    def preflight(*args, **kwargs):
        save_changed(case, "python")
        return install.Step("preflight", True, "old interpreter completed its check")

    monkeypatch.setattr(install, "run_preflight", preflight)
    assert not finish(case)
    # The host must never associate a passing old process with configuration
    # saved concurrently, including returning success to the project handoff.
    saved = json.loads(case.status.read_text(encoding="utf-8"))
    assert not saved["ok"] and saved["runtime_identity"] is None
    assert saved["primary_error"]["name"] == "runtime-config"
    state = case.handler._status_for(case.ki)
    assert not state["can_run"]


def test_builtin_install_records_runtime_and_later_change_invalidates_it(case, monkeypatch):
    for name in ("ensure_python_env", "check_system_deps", "install_python_deps"):
        monkeypatch.setattr(install, name, lambda *args, **kwargs:
                            install.Step("prerequisite", True, "fixture ready"))
    monkeypatch.setattr(install, "needs_shared_tools", lambda *args: False)
    monkeypatch.setattr(install, "acquire", lambda *args, **kwargs:
                        (install.Step("acquire", True, "fixture existing software"), None))
    gui.run_install(case.ki, case.handler._manifest(case.ki), case.root,
                    lambda _piece: None, case.library)
    saved = json.loads(case.status.read_text(encoding="utf-8"))
    assert saved["ok"] and saved.get("runtime_identity")
    assert case.handler._status_for(case.ki)["can_run"]
    save_changed(case, "binaries")
    assert_stale_without_rewriting_history(case)


def test_starting_reverification_cannot_leave_old_readiness_after_early_failure(case, monkeypatch):
    assert finish(case)
    assert case.handler._status_for(case.ki)["can_run"]

    def fail_before_install(*args, **kwargs):
        raise ValueError("fixture interrupted before runtime preparation")

    monkeypatch.setattr(setup, "prepare_python", fail_before_install)
    with pytest.raises(ValueError, match="fixture interrupted"):
        gui.run_install(case.ki, case.handler._manifest(case.ki), case.root,
                        lambda _piece: None, case.library)
    state = case.handler._status_for(case.ki)
    assert not state["can_run"]
    saved = json.loads(case.status.read_text(encoding="utf-8"))
    assert not saved["ok"] and saved["verified_at"] is None
    assert saved.get("runtime_identity") is None


@pytest.mark.parametrize("operation", ["agent", "builtin"])
def test_cancelled_reverification_clears_current_runtime_certificate(case, monkeypatch, operation):
    assert finish(case)
    if operation == "agent":
        assert not case.handler._record_agent_preflight(
            case.ki, case.live, case.cfg, case.root, lambda _piece: None,
            stop=lambda: True)
    else:
        def cancelled(*args, **kwargs):
            raise install.InstallStopped("fixture stopped by the user")

        monkeypatch.setattr(install, "runtime_python", cancelled)
        gui.run_install(case.ki, case.handler._manifest(case.ki), case.root,
                        lambda _piece: None, case.library)
    saved = json.loads(case.status.read_text(encoding="utf-8"))
    assert not saved["ok"] and saved["verified_at"] is None
    assert saved.get("runtime_identity") is None
    assert not case.handler._status_for(case.ki)["can_run"]


def test_runtime_identity_preserves_distinct_venv_launcher_paths(tmp_path):
    target = tmp_path / "base-python.exe"
    target.write_bytes(b"fixture launcher; never executed")
    launcher = tmp_path / "venv" / "python.exe"
    launcher.parent.mkdir()
    try:
        launcher.symlink_to(target)
    except OSError as error:
        pytest.skip(f"creating a launcher symlink is unavailable: {error}")
    cfg = paths.KissConfig.default(tmp_path)
    cfg.python = str(target)
    base_identity = software_verification.runtime_identity(cfg)
    cfg.python = str(launcher)
    assert launcher.resolve() == target.resolve()
    assert software_verification.runtime_identity(cfg) != base_identity, (
        "dereferencing the launcher loses which virtual environment was selected")


def test_identity_lookup_failure_revokes_previous_builtin_verification(case, monkeypatch):
    assert finish(case)
    assert case.handler._status_for(case.ki)["can_run"]

    def identity_failure(*args, **kwargs):
        raise ValueError("fixture identity metadata unavailable")

    # Restore normal identity lookup before querying status. The old verdict
    # must have been revoked, rather than hidden by this temporary exception.
    with monkeypatch.context() as patch:
        patch.setattr(software_verification, "identity", identity_failure)
        with pytest.raises(ValueError, match="fixture identity metadata unavailable"):
            gui.run_install(case.ki, case.handler._manifest(case.ki), case.root,
                            lambda _piece: None, case.library)
    assert_current_verification_revoked(case)


def test_builtin_rejects_config_redirect_even_when_destination_has_matching_config(case, monkeypatch):
    assert finish(case)
    redirected = case.root.parent / "redirected"
    redirected.mkdir()
    wrong = deepcopy(case.cfg)
    wrong.root = redirected
    body = wrong.dumps()
    case.config.write_text(body, encoding="utf-8")
    destination_config = redirected / paths.CONFIG_NAME
    destination_config.write_text(body, encoding="utf-8")
    fake_builtin_prerequisites(monkeypatch)

    gui.run_install(case.ki, case.handler._manifest(case.ki), case.root,
                    lambda _piece: None, case.library)

    saved = assert_current_verification_revoked(case)
    assert saved["primary_error"]["name"] == "runtime-config"
    assert "root" in saved["primary_error"]["detail"].lower()
    assert destination_config.read_text(encoding="utf-8") == body
    assert not (redirected / "status.json").exists()


def test_unexpected_final_preflight_exception_revokes_previous_success(case, monkeypatch):
    assert finish(case)
    assert case.handler._status_for(case.ki)["can_run"]

    def unexpected_failure(*args, **kwargs):
        raise RuntimeError("fixture preflight transport failed")

    monkeypatch.setattr(install, "run_preflight", unexpected_failure)
    with pytest.raises(RuntimeError, match="fixture preflight transport failed"):
        finish(case)
    assert_current_verification_revoked(case)


def test_builtin_config_change_during_preflight_cannot_certify_new_binding(case, monkeypatch):
    assert finish(case)
    fake_builtin_prerequisites(monkeypatch)

    def changing_preflight(*args, **kwargs):
        save_changed(case, "python")
        return install.Step("preflight", True, "previous interpreter passed")

    monkeypatch.setattr(install, "run_preflight", changing_preflight)
    gui.run_install(case.ki, case.handler._manifest(case.ki), case.root,
                    lambda _piece: None, case.library)
    saved = assert_current_verification_revoked(case)
    assert saved["primary_error"]["name"] == "runtime-config"


def test_installation_only_success_does_not_publish_a_runtime_verification(case, monkeypatch):
    assert finish(case)
    fake_builtin_prerequisites(monkeypatch)
    monkeypatch.setattr(gui.runnable, "check", lambda *args, **kwargs:
                        SimpleNamespace(usable=True, summary=lambda: "fixture startup passed"))

    def forbidden_preflight(*args, **kwargs):
        raise AssertionError("installation-only must not execute full KI preflight")

    monkeypatch.setattr(install, "run_preflight", forbidden_preflight)
    gui.run_install(case.ki, case.handler._manifest(case.ki), case.root,
                    lambda _piece: None, case.library, installation_only=True)
    saved = json.loads(case.status.read_text(encoding="utf-8"))
    assert saved["ok"] and saved["installation_only"] and saved["installation_ready"]
    assert saved["runtime_identity"] is None
    assert saved["verified_at"] is None
    assert not case.handler._status_for(case.ki)["can_run"]
