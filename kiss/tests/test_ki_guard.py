"""Host KI integrity lifecycle: no real providers, installers or model runs."""
from pathlib import Path
import json
import shutil
from types import SimpleNamespace

import pytest

from kiss_cli import api, execution, flowgate, install, ki_guard, ki_verification, paths, providers, setup
from kiss_cli.catalog import KI, Catalog


@pytest.fixture
def active(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guard"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    # This fixture has no shipped/default library; only the explicitly
    # enrolled KI below supplies legacy host provenance.
    monkeypatch.setattr(ki_guard, "_legacy_installation_roots", lambda: [])
    root = tmp_path / "work" / "ki"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text("original instructions", encoding="utf-8")
    (root / "preflight_check.py").write_text("print('checked')\n", encoding="utf-8")
    ki_guard.enroll(root)
    return root


def test_enrollment_never_reblesses_changes(active):
    (active / "SKILL.md").write_text("changed")
    with pytest.raises(ki_guard.KIIntegrityError, match="changed"):
        ki_guard.enroll(active)


def test_recovery_preserves_draft_and_exact_baseline(active):
    (active / "SKILL.md").write_text("changed")
    (active / "added.txt").write_bytes(b"new bytes")
    with pytest.raises(ki_guard.KIIntegrityError, match="stop active workers"):
        ki_guard.recover_drift(active)
    draft = ki_guard.recover_drift(active, quiescent=True)
    assert (draft / "SKILL.md").read_text() == "changed"
    assert (draft / "added.txt").read_bytes() == b"new bytes"
    assert (active / "SKILL.md").read_text() == "original instructions"
    assert not (active / "added.txt").exists()
    ki_guard.require_intact(active)


def test_restore_refuses_corrupt_backup(active):
    doc = ki_guard.require_intact(active)
    backup = ki_guard._entry(active) / doc["digest"][:12]
    (backup / "SKILL.md").write_text("bad backup")
    (active / "SKILL.md").write_text("draft bytes")
    with pytest.raises(ki_guard.KIIntegrityError, match="backup"):
        ki_guard.recover_drift(active, quiescent=True)
    assert (active / "SKILL.md").read_text() == "draft bytes"


def test_existing_bytecode_is_preserved_in_baseline(active):
    other = active.parent / "other"
    other.mkdir()
    (other / "__pycache__").mkdir()
    (other / "__pycache__/x.pyc").write_bytes(b"cached bytes")
    ki_guard.enroll(other)
    ki_guard.require_intact(other)


def test_backup_handles_long_windows_paths(active, monkeypatch):
    # Original KI files are ordinary-length; host backup location may exceed
    # MAX_PATH, reproducing the regression without shortening pytest paths.
    long_home = active.parent / ("host-" + "x" * 95)
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(long_home))
    ki_guard.enroll(active)
    ki_guard.require_intact(active)


@pytest.mark.parametrize("tool,args", [
    ("write_work_file", {"path": "ki/SKILL.md", "content": "new"}),
    ("replace_work_text", {"path": "ki/SKILL.md", "old": "original", "new": "new"}),
])
def test_api_rejects_active_writes(active, tool, args):
    cfg = paths.KissConfig.default(active.parent)
    with pytest.raises(api.ToolError, match="Active KI files"):
        api.execute_tool(tool, args, KI("M", active), cfg, setup_mode=True)
    ki_guard.require_intact(active)


def test_api_allows_unrelated_installation_file(active):
    cfg = paths.KissConfig.default(active.parent)
    api.execute_tool("write_work_file", {"path": "build/config.txt", "content": "build"},
                     KI("M", active), cfg, setup_mode=True)
    assert (active.parent / "build/config.txt").read_text() == "build"


def test_api_indirect_mutation_is_draft_not_success(active, monkeypatch):
    def command(*args, **kwargs):
        (active / "SKILL.md").write_text("indirect change")
        return "exit_code=0"
    monkeypatch.setattr(api, "_execute_tool", command)
    with pytest.raises(api.ToolError, match="changed bytes retained"):
        api.execute_tool("run_setup_command", {}, KI("M", active),
                         paths.KissConfig.default(active.parent), setup_mode=True)
    with pytest.raises(ki_guard.KIIntegrityError, match="changed"):
        ki_guard.require_intact(active)
    assert list(active.parent.glob("ki-draft-*/SKILL.md"))[0].read_text() == "indirect change"
    ki_guard.recover_drift(active, quiescent=True)
    ki_guard.require_intact(active)


@pytest.mark.parametrize("provider", ["claude", "codex", "gemini", "kimi", "qwen"])
def test_every_cli_provider_rejects_changed_active_bytes(active, monkeypatch, provider):
    def fake_run(*args, **kwargs):
        assert kwargs["extra_env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        (active / "SKILL.md").write_text(provider)
        kwargs["session_out"]["returncode"] = 0
        yield "claimed success"
    monkeypatch.setattr(providers, "_run", fake_run)
    state = {}
    with pytest.raises(ki_guard.KIIntegrityError, match="retained"):
        list(providers.run(SimpleNamespace(name=provider), "task", active.parent,
                           ki_root=active, session_out=state))
    assert state["returncode"] == 1
    with pytest.raises(ki_guard.KIIntegrityError, match="changed"):
        ki_guard.require_intact(active)
    assert (active / "SKILL.md").read_text() == provider


def test_cli_host_callback_does_not_wait_for_provider_exit(active, monkeypatch):
    import threading
    callback_done = threading.Event()
    failures = []
    def fake_run(*args, **kwargs):
        def callback():
            try:
                ki_guard.require_intact(active)
                with ki_guard.worker(active):
                    ki_guard.require_intact(active)
            except BaseException as exc:
                failures.append(exc)
            finally:
                callback_done.set()
        callback_thread = threading.Thread(target=callback, daemon=True)
        callback_thread.start()
        assert callback_done.wait(2), "host callback deadlocked behind provider lifetime lock"
        callback_thread.join(1)
        yield "host callback completed"
    monkeypatch.setattr(providers, "_run", fake_run)
    assert list(providers.run(SimpleNamespace(name="fixture"), "task", active.parent,
                              ki_root=active)) == ["host callback completed"]
    assert not failures


@pytest.mark.parametrize("route", ["api", "cli"])
def test_secondary_ki_edits_are_blocked_and_preserved(active, monkeypatch, route):
    secondary = active.parent / "secondary"
    secondary.mkdir()
    (secondary / "SKILL.md").write_text("secondary baseline")
    ki_guard.enroll(secondary)
    def change():
        (secondary / "SKILL.md").write_text("changed secondary")
    if route == "api":
        def fake_tool(*args, **kwargs):
            change()
            return "claimed success"
        monkeypatch.setattr(api, "_execute_tool", fake_tool)
        flow = SimpleNamespace(ctx=SimpleNamespace(selected_kis=["M", "N"]),
            ki_root_for=lambda name, _default: (name, active if name == "M" else secondary))
        with pytest.raises(api.ToolError, match="changed bytes retained"):
            api.execute_tool("run_ki_tool", {}, KI("M", active),
                paths.KissConfig.default(active.parent), project_mode=True, flow=flow)
    else:
        def fake_cli(*args, **kwargs):
            change()
            yield "claimed success"
        monkeypatch.setattr(providers, "_run", fake_cli)
        with pytest.raises(ki_guard.KIIntegrityError, match="changed bytes retained"):
            list(providers.run(SimpleNamespace(name="fixture"), "task", active.parent,
                               ki_root=active, managed_roots=[active, secondary]))
    ki_guard.require_intact(active)
    with pytest.raises(ki_guard.KIIntegrityError, match="changed"):
        ki_guard.require_intact(secondary)
    assert any((p / "SKILL.md").read_text() == "changed secondary"
               for p in active.parent.glob("ki-draft-*"))


def test_recovery_refused_while_host_worker_active(active):
    with ki_guard.worker(active):
        (active / "SKILL.md").write_text("changed")
        with pytest.raises(ki_guard.KIIntegrityError, match="host worker"):
            ki_guard.recover_drift(active, quiescent=True)
        draft = ki_guard.preserve_drift(active)
        assert (draft / "SKILL.md").read_text() == "changed"
        assert (active / "SKILL.md").read_text() == "changed"
    ki_guard.recover_drift(active, quiescent=True)


def test_unknown_ki_cannot_enroll_itself_at_api_dispatch(active):
    fresh = active.parent / "unregistered"
    fresh.mkdir()
    (fresh / "SKILL.md").write_text("unverified")
    inspected = api.execute_tool("read_ki_file", {"path": "SKILL.md"}, KI("M", fresh),
                                 paths.KissConfig.default(active.parent))
    assert "unverified" in inspected
    with pytest.raises(api.ToolError, match="no host baseline"):
        api.execute_tool("run_preflight", {}, KI("M", fresh),
                         paths.KissConfig.default(active.parent))
    assert not ki_guard.is_managed(fresh)


def test_blocked_ki_remains_readable_but_cannot_execute(active):
    (active / "SKILL.md").write_text("draft diagnosis")
    ki, cfg = KI("M", active), paths.KissConfig.default(active.parent)
    assert "draft diagnosis" in api.execute_tool("read_ki_file", {"path": "SKILL.md"}, ki, cfg)
    assert "SKILL.md" in api.execute_tool("list_ki_files", {}, ki, cfg)
    with pytest.raises(api.ToolError, match="Active KI changed"):
        api.execute_tool("run_preflight", {}, ki, cfg)
    with pytest.raises(api.ToolError, match="Active KI files"):
        api.execute_tool("write_work_file", {"path": "ki/SKILL.md", "content": "accept"},
                         ki, cfg, setup_mode=True)


def test_execution_lease_spans_preparation_and_receipt_boundary(active, monkeypatch):
    observed = []
    def host_boundary(**kwargs):
        for stage in ("approval", "native", "receipt"):
            with pytest.raises(ki_guard.KIIntegrityError, match="host worker"):
                ki_guard._no_workers(active)
            observed.append(stage)
        return "fixture result"
    monkeypatch.setattr(execution, "_execute_ki_tool", host_boundary)
    result = execution.execute_ki_tool(flow=None, cfg=None, project=active.parent,
        ki="M", ki_root=active, tool=active / "preflight_check.py", arguments=[],
        cwd=active.parent, plan_step_id=None, python_tool=True)
    assert result == "fixture result" and observed == ["approval", "native", "receipt"]
    ki_guard._no_workers(active)


def test_cli_verify_returns_blocked_json_for_changed_ki(active, monkeypatch, capsys):
    import json
    from kiss_cli import cli, runnable
    class Catalogue:
        models_dir = active.parent
        def __iter__(self):
            return iter([KI("M", active)])
        def get(self, _name):
            return KI("M", active)
    monkeypatch.setattr(cli, "_catalog", lambda _args: Catalogue())
    monkeypatch.setattr(cli.install_locations, "resolve", lambda *_args: active.parent)
    monkeypatch.setattr(cli, "_manifest_for", lambda *_args: None)
    monkeypatch.setattr(runnable, "check", lambda *_args, **_kwargs:
                        runnable.Verdict("M", needs_binary=False))
    args = SimpleNamespace(model="M", workdir=str(active.parent), python=None,
                           timeout=1, json=True)
    assert cli.cmd_verify(args) == 0
    capsys.readouterr()
    (active / "SKILL.md").write_text("unreviewed edit")
    def never_run(*args, **kwargs):
        pytest.fail("Changed KI must not reach runtime verification")
    monkeypatch.setattr(runnable, "check", never_run)
    assert cli.cmd_verify(args) == 1
    doc = json.loads(capsys.readouterr().out)[0]
    assert doc["state"] == "blocked" and "KI integrity gate" in doc["detail"]
    assert (active / "SKILL.md").read_text() == "unreviewed edit"


def test_preflight_drift_fails_even_on_zero_exit(active, monkeypatch):
    def fake_run(*args, **kwargs):
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        (active / "SKILL.md").write_text("probe edited KI")
        return 0, "all checks passed"
    monkeypatch.setattr(install, "_run", fake_run)
    result = install.run_preflight(KI("M", active), "python")
    assert not result.ok and "Active KI changed" in result.detail


def test_setup_does_not_refresh_enrolled_ki(active):
    source = active.parent / "new-source"
    source.mkdir()
    (source / "SKILL.md").write_text("new upstream instructions")
    with pytest.raises(ki_guard.KIIntegrityError, match="different working copy"):
        setup.materialise_active(source, active, paths.KissConfig.default(active.parent))
    ki_guard.require_intact(active)
    assert list(active.parent.glob("ki-draft-*/SKILL.md"))[0].read_text() == "new upstream instructions"


def test_existing_host_metadata_and_cache_do_not_force_setup_upgrade(active):
    source = active.parent / "portable"
    source.mkdir()
    for name in ("SKILL.md", "preflight_check.py"):
        (source / name).write_bytes((active / name).read_bytes())
    other = active.parent / "legacy"
    other.mkdir()
    for name in ("SKILL.md", "preflight_check.py"):
        (other / name).write_bytes((source / name).read_bytes())
    (other / "__pycache__").mkdir()
    (other / "__pycache__/preflight.cpython-311.pyc").write_bytes(b"old cache")
    (other / ".geoforge-install.json").write_text('{"old": true}')
    result = setup.materialise_active(source, other, paths.KissConfig.default(active.parent))
    assert not result.corrupted and (other / ".geoforge-install.json").is_file()
    ki_guard.require_intact(other)


def test_native_dispatch_refuses_drift_without_launch(active, monkeypatch):
    (active / "SKILL.md").write_text("changed")
    def forbidden(*args, **kwargs):
        pytest.fail("native process must not be called")
    monkeypatch.setattr(execution, "run_process", forbidden)
    with pytest.raises(flowgate.FlowDenied, match="Active KI changed"):
        execution.execute_ki_tool(flow=None, cfg=paths.KissConfig.default(active.parent),
            project=active.parent, ki="M", ki_root=active, tool=active / "preflight_check.py",
            arguments=[], cwd=active.parent, plan_step_id=None, python_tool=True)


def test_catalogue_migration_is_once_and_later_new_names_need_kdt(active):
    class Catalogue:
        models_dir = active.parent
        def __iter__(self):
            return iter([KI(path.name, path) for path in sorted(self.models_dir.iterdir())
                         if path.is_dir() and (path / "SKILL.md").is_file()])
    catalog = Catalogue()
    first = ki_guard.enroll_catalogue(catalog)
    assert first["legacy_migration"] and not first["errors"]
    added = active.parent / "unreviewed"
    added.mkdir()
    (added / "SKILL.md").write_text("new package")
    second = ki_guard.enroll_catalogue(catalog)
    assert not second["legacy_migration"]
    assert "unreviewed" in second["errors"] and not ki_guard.is_managed(added)
    (active / "SKILL.md").write_text("changed existing package")
    third = ki_guard.enroll_catalogue(catalog)
    assert "ki" in third["errors"]


def test_new_models_directory_cannot_restart_legacy_migration(active):
    first = ki_guard.enroll_catalogue(Catalog(active.parent))
    assert not first["errors"]
    new_models = active.parent.parent / "new-models"
    edited = new_models / "ki"
    shutil.copytree(active, edited)
    (edited / "SKILL.md").write_text("edited unverified KI", encoding="utf-8")
    result = ki_guard.enroll_catalogue(Catalog(new_models))
    assert not result["legacy_migration"]
    assert "ki" in result["errors"] and "cannot restart migration" in result["errors"]["ki"]
    assert not ki_guard.is_managed(edited)


def test_first_arbitrary_models_directory_does_not_gain_bootstrap_trust(active):
    new_models = active.parent.parent / "first-arbitrary-models"
    edited = new_models / "edited"
    shutil.copytree(active, edited)
    (edited / "SKILL.md").write_text("new unverified instructions", encoding="utf-8")
    result = ki_guard.enroll_catalogue(Catalog(new_models))
    assert "edited" in result["errors"] and not ki_guard.is_managed(edited)


def test_readonly_exact_legacy_copy_uses_recorded_provenance(active):
    ki_guard.enroll_catalogue(Catalog(active.parent))
    new_models = active.parent.parent / "relocated-models"
    copied = new_models / "ki"
    shutil.copytree(active, copied)
    for path in copied.iterdir():
        if path.is_file():
            path.chmod(0o444)
    before = ki_verification.content_digest(copied)
    result = ki_guard.enroll_catalogue(Catalog(new_models))
    assert not result["errors"] and result["enrolled"] == ["ki"]
    assert ki_guard.require_intact(copied)["origin"] == "existing_host_baseline"
    assert ki_verification.content_digest(copied) == before
    assert ki_verification.current_report(copied) is None, "legacy identity must not become a claimed KDT pass"


def test_fresh_installed_library_bootstraps_only_once(active, monkeypatch):
    installed = active.parent.parent / "installed-models"
    shipped = installed / "shipped"
    shutil.copytree(active, shipped)
    (shipped / "SKILL.md").write_text("shipped initial revision", encoding="utf-8")
    monkeypatch.setattr(ki_guard, "_legacy_installation_roots", lambda: [installed])
    first = ki_guard.enroll_catalogue(Catalog(installed))
    assert first["legacy_migration"] and not first["errors"]
    added = installed / "added-later"
    shutil.copytree(shipped, added)
    (added / "SKILL.md").write_text("unverified later package", encoding="utf-8")
    second = ki_guard.enroll_catalogue(Catalog(installed))
    assert "added-later" in second["errors"] and not ki_guard.is_managed(added)


def test_prior_signed_catalogue_migrates_recorded_hash_not_current_bytes(active, monkeypatch):
    installed = active.parent.parent / "older-installation"
    old = installed / "old"
    shutil.copytree(active, old)
    original_digest = ki_verification.content_digest(old)
    receipts = flowgate.load().receipts
    prior = receipts.sign(installed, {
        "schema_version": 1, "root": str(installed.absolute()),
        "origin": "host_catalogue_baseline",
        "models": {"old": {"root": str(old.absolute()), "digest": original_digest}},
    })
    record = ki_guard._home() / "catalogues" / "prior.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps(prior), encoding="utf-8")
    (old / "SKILL.md").write_text("edited after original migration", encoding="utf-8")
    monkeypatch.setattr(ki_guard, "_legacy_installation_roots", lambda: [installed])
    result = ki_guard.enroll_catalogue(Catalog(installed))
    assert "old" in result["errors"] and not ki_guard.is_managed(old)
    inventory, created = ki_guard._legacy_inventory()
    assert not created
    digests = {item["digest"] for item in inventory["models"]}
    assert original_digest in digests and ki_verification.content_digest(old) not in digests


def test_adoption_requires_valid_report_and_current_candidate(active, monkeypatch):
    draft = active.parent / "candidate"
    draft.mkdir()
    (draft / "SKILL.md").write_text("candidate")
    # Signed fixture report exercises the real exact-byte acceptance seam;
    # the KDT subprocess itself has separate verification-layer tests.
    from kiss_cli import kdtstudio, doctor
    monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "fixture-engine")
    report = ki_verification._seal(draft, {
        "gate_policy": ki_verification.GATE_POLICY, "ok": True,
        "kind": "process_model", "desktop_requested": True,
        "engine_policy": kdtstudio.REVIEWED_COMMIT,
        "doctor_policy": doctor.VALIDATION_POLICY_VERSION,
        "engine_source_digest": "fixture-engine", "engine_override": False,
        "candidate_digest": ki_verification.content_digest(draft)})
    with pytest.raises(ki_guard.KIIntegrityError, match="Stop active workers"):
        ki_guard.activate(active, draft, report)
    (draft / "SKILL.md").write_text("post-verification edit")
    with pytest.raises(ki_verification.VerificationError, match="changed"):
        ki_guard.activate(active, draft, report, quiescent=True)
    ki_guard.require_intact(active)
    (draft / "SKILL.md").write_text("candidate")
    ki_guard.activate(active, draft, report, quiescent=True)
    assert (active / "SKILL.md").read_text() == "candidate"
    assert list(active.parent.glob("ki-previous-*/SKILL.md"))[0].read_text() == "original instructions"
    ki_guard.require_intact(active)
