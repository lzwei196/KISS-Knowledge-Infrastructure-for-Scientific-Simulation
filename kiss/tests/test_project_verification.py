"""Exact project receipts cannot borrow a shared installation's successful check."""
from dataclasses import replace
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import sys
import threading

import pytest

from kiss_cli import install, ki_guard, ki_verification, paths, project_paths
from kiss_cli import project_verification as pv
from kiss_cli import software_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "host-keys"))
    project = (tmp_path / "project").resolve()
    ki = KI("Demo", project / "models" / "Demo" / "ki")
    ki.root.mkdir(parents=True)
    (ki.root / "SKILL.md").write_text("# Harmless verification fixture\n", encoding="utf-8")
    (ki.root / "preflight_check.py").write_text("print('fixture preflight passed')\n", encoding="utf-8")
    shared = paths.KissConfig.default(tmp_path / "shared-install")
    shared.python = sys.executable
    cfg = project_paths.model_config(project, ki.name, shared)
    config = ki.root.parent / "kiss.toml"
    config.write_text(cfg.dumps(), encoding="utf-8")
    ki_guard.enroll(ki.root)
    return project, ki, Manifest(model=ki.name), cfg, config


def _passing(monkeypatch):
    monkeypatch.setattr(install, "run_preflight", lambda *_a, **_kw: install.Step("preflight", True, "fixture"))


def _forbid_checks(monkeypatch):
    def forbidden(*_a, **_kw):
        pytest.fail("A read-only gate executed scientific/preflight/requirement checks")
    monkeypatch.setattr(install, "run_preflight", forbidden)
    monkeypatch.setattr(software_verification, "requirements", forbidden)


def test_missing_receipt_blocks_canonical_dispatch_without_checks(case, monkeypatch):
    project, ki, man, _cfg, config = case
    before = config.read_bytes()
    _forbid_checks(monkeypatch)
    result = pv.status(project, ki, man)
    assert result["state"] == "unverified" and not result["can_run"]
    with pytest.raises(ValueError, match="verification required"):
        pv.require_current(project, ki.name, ki.root)
    assert config.read_bytes() == before
    assert not (project / ".geoforge").exists()


def test_real_preflight_signs_exact_project_without_touching_shared_status(case, monkeypatch):
    project, ki, man, cfg, _config = case
    before = ki_verification.content_digest(ki.root)
    shared_status = cfg.roles["home"] / "status.json"
    shared_status.parent.mkdir(parents=True)
    shared_status.write_text('{"preflight_ok": true}', encoding="utf-8")
    result = pv.verify(project, ki, man)
    assert result["ok"], result
    assert [check["name"] for check in result["receipt"]["checks"]] == ["preflight", "manifest-requirements"]
    assert "fixture preflight passed" in result["receipt"]["checks"][0]["detail"]
    assert pv._receipts().verify(project, result["receipt"])
    assert ki_verification.content_digest(ki.root) == before
    assert shared_status.read_text(encoding="utf-8") == '{"preflight_ok": true}'
    _forbid_checks(monkeypatch)
    assert pv.status(project, ki)["can_run"]
    pv.require_current(project, ki.name, ki.root, cfg=cfg)


@pytest.mark.parametrize("reason", ["pending project derivation", "stale setup runtime"])
def test_derived_authority_loss_blocks_cached_dispatch_and_fresh_preflight(case, monkeypatch, reason):
    from kiss_cli import ki_data_lineage
    project, ki, man, cfg, config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    before = config.read_bytes()

    def reject(current_project, model, live, saved):
        assert current_project == project
        assert live == ki.root and saved.root == project and model == ki.name
        raise ValueError(reason)

    monkeypatch.setattr(ki_data_lineage, "require_setup_projection", reject)
    _forbid_checks(monkeypatch)
    result = pv.status(project, ki)
    assert not result["can_run"] and reason in result["detail"]
    with pytest.raises(ValueError, match=reason):
        pv.require_current(project, ki.name, ki.root, cfg=cfg)
    result = pv.verify(project, ki, man)
    assert not result["ok"] and reason in result["detail"]
    assert config.read_bytes() == before


def test_receipt_remembers_required_derivation_after_optional_record_disappears(case, monkeypatch):
    from kiss_cli import ki_data_lineage
    project, ki, man, cfg, _config = case
    _passing(monkeypatch)
    monkeypatch.setattr(ki_data_lineage, "require_setup_projection",
                        lambda *args: {"project_derivation": {"setup_adoption_digest": "bound-setup"}})
    result = pv.verify(project, ki, man)
    assert result["ok"] and result["receipt"]["setup_derivation"]
    monkeypatch.setattr(ki_data_lineage, "require_setup_projection", lambda *args: None)
    _forbid_checks(monkeypatch)
    assert not pv.status(project, ki)["can_run"]
    with pytest.raises(ValueError, match="verification required"):
        pv.require_current(project, ki.name, ki.root, cfg=cfg)


def test_existing_ordinary_maintenance_lineage_keeps_its_project_verification_route(case, monkeypatch):
    from kiss_cli import ki_data_lineage
    project, ki, man, cfg, _config = case
    _passing(monkeypatch)
    monkeypatch.setattr(ki_data_lineage, "require_setup_projection",
                        lambda *args: {"kind": "maintenance_data_lineage", "adoptions": ["existing"]})
    result = pv.verify(project, ki, man)
    assert result["ok"] and result["receipt"]["setup_derivation"] is None
    pv.require_current(project, ki.name, ki.root, cfg=cfg)


def test_shared_source_pass_does_not_certify_failing_project(case, tmp_path, monkeypatch):
    project, ki, man, cfg, _config = case
    source = KI(ki.name, tmp_path / "upstream" / ki.name)
    shutil.copytree(ki.root, source.root)
    ki_guard.enroll(source.root)
    assert install.run_preflight(source, cfg.python, cfg).ok
    (ki.root / "preflight_check.py").write_text("raise SystemExit('project-specific requirement missing')\n", encoding="utf-8")
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "project-fixture-guard"))
    ki_guard.enroll(ki.root)  # fixture materialization, not adoption by the verifier
    def forbidden(*_a, **_kw):
        pytest.fail("Requirements must not run after a failed preflight")
    monkeypatch.setattr(software_verification, "requirements", forbidden)
    result = pv.verify(project, ki, man, source_ki=source)
    assert result["state"] == "failed" and not result["can_run"]
    assert "project-specific requirement missing" in result["detail"]
    assert pv.status(project, ki)["state"] == "failed"


@pytest.mark.parametrize("change", ["python", "role", "relocation", "root", "missing", "malformed", "invalid_role"])
def test_changed_saved_config_revokes_status_without_rewriting(case, monkeypatch, tmp_path, change):
    project, ki, man, cfg, config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    receipt_path = pv._receipt_path(project, ki.name)
    receipt_before = receipt_path.read_bytes()
    if change == "python":
        cfg.python = str(tmp_path / "different-python.exe")
    elif change == "role":
        cfg.roles["binaries"] = tmp_path / "new-install"
    elif change == "relocation":
        cfg.relocation = "port"
    elif change == "root":
        cfg.root = tmp_path / "different-project"
    if change in ("python", "role", "relocation", "root"):
        config.write_text(cfg.dumps(), encoding="utf-8")
    elif change == "missing":
        config.unlink()
        # An ancestor's valid config must not be an implicit fallback.
        (project / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    elif change == "malformed":
        config.write_text("[kiss invalid TOML", encoding="utf-8")
    else:
        config.write_text(cfg.dumps().replace("[paths]", "[paths]\ninvalid = 42"), encoding="utf-8")
    before = config.read_bytes() if config.exists() else None
    _forbid_checks(monkeypatch)
    result = pv.status(project, ki, man)
    assert result["state"] == "stale" and not result["can_run"]
    assert receipt_path.read_bytes() == receipt_before
    assert (config.read_bytes() if config.exists() else None) == before


def test_legacy_toml_compatibility_is_in_memory_and_comment_changes_are_harmless(case, monkeypatch):
    project, ki, man, _cfg, config = case
    _passing(monkeypatch)
    original = config.read_text(encoding="utf-8")
    # On Windows these raw basic strings require the existing compatibility repair.
    legacy = original.replace("'", '"')
    config.write_text(legacy, encoding="utf-8")
    assert pv.verify(project, ki, man)["ok"]
    config.write_text(legacy + "\n# A human explanation\n", encoding="utf-8")
    before = config.read_bytes()
    _forbid_checks(monkeypatch)
    assert pv.status(project, ki, man)["can_run"]
    assert config.read_bytes() == before


def test_ki_changes_require_integrity_and_new_receipt(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    receipt = pv._receipt_path(project, ki.name).read_bytes()
    (ki.root / "SKILL.md").write_text("# Changed scientific instructions", encoding="utf-8")
    _forbid_checks(monkeypatch)
    assert not pv.status(project, ki, man)["can_run"]
    result = pv.verify(project, ki, man)
    assert result["state"] == "failed"
    # Model an already accepted new tree in a fresh, isolated guard fixture.
    # Its bytes still must not recycle a pass for the previous project snapshot.
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(project.parent / "replacement-fixture-guard"))
    ki_guard.enroll(ki.root)
    pv._receipt_path(project, ki.name).write_bytes(receipt)
    assert not pv.status(project, ki, man)["can_run"]


def test_unenrolled_project_is_not_adopted_by_verification(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(project.parent / "empty-guard"))
    _forbid_checks(monkeypatch)
    result = pv.verify(project, ki, man)
    assert not result["ok"]
    with pytest.raises(ki_guard.KIIntegrityError):
        ki_guard.require_intact(ki.root)


@pytest.mark.parametrize("where", ["saved", "in_memory"])
def test_config_changed_inside_check_cannot_pass(case, monkeypatch, where):
    project, ki, man, cfg, config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    def changing(_ki, _python, checked, **_kw):
        if where == "saved":
            cfg.roles["binaries"] = project.parent / "different-runtime"
            config.write_text(cfg.dumps(), encoding="utf-8")
        else:
            checked.python = "different-runtime"
        return install.Step("preflight", True)
    monkeypatch.setattr(install, "run_preflight", changing)
    result = pv.verify(project, ki, man)
    assert result["state"] == "failed" and "changed during" in result["detail"]
    assert not pv.status(project, ki, man)["can_run"]


@pytest.mark.parametrize("when", ["before", "during"])
def test_cancellation_revokes_previous_pass(case, monkeypatch, when):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    stopped = when == "before"
    def preflight(*_a, **_kw):
        nonlocal stopped
        stopped = True
        return install.Step("preflight", False, "interrupted by fixture")
    monkeypatch.setattr(install, "run_preflight", preflight)
    def forbidden(*_a, **_kw):
        pytest.fail("requirements ran after cancellation")
    monkeypatch.setattr(software_verification, "requirements", forbidden)
    result = pv.verify(project, ki, man, stop=lambda: stopped)
    assert result["state"] == "cancelled" and not result["ok"]
    assert pv.status(project, ki, man)["state"] == "cancelled"


def test_manifest_dependency_is_required_and_manifest_change_invalidates(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    coupled = replace(man, depends_on=["Routing"])
    assert not pv.verify(project, ki, coupled)["ok"]
    called = []
    assert pv.verify(project, ki, coupled, dependency_check=lambda name: called.append(name) or True)["ok"]
    assert called == ["Routing"]
    assert pv.status(project, ki, coupled)["can_run"]
    assert not pv.status(project, ki, man)["can_run"]
    # No on-disk recipe: dispatch validates the signed pinned effective manifest.
    pv.require_current(project, ki.name, ki.root)


def test_actual_platform_manifest_cannot_be_overridden_by_weaker_argument(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    (ki.root / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: Demo\ndepends_on: [Routing]\n", encoding="utf-8")
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(project.parent / "manifest-fixture-guard"))
    ki_guard.enroll(ki.root)
    _forbid_checks(monkeypatch)
    result = pv.verify(project, ki, man)
    assert not result["ok"] and "actual KI manifest" in result["detail"]


def test_unsigned_and_tampered_receipts_fail_closed(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    result = pv.verify(project, ki, man)
    path = pv._receipt_path(project, ki.name)
    for mutation in ("unsigned", "tampered"):
        doc = dict(result["receipt"])
        if mutation == "unsigned":
            doc.pop("signature")
        else:
            doc["detail"] = "forged"
        path.write_text(json.dumps(doc), encoding="utf-8")
        assert not pv.status(project, ki, man)["can_run"]


def test_copied_receipt_cannot_authorize_another_project(case, monkeypatch, tmp_path):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    copied = tmp_path / "copied-project"
    shutil.copytree(project, copied)
    assert not pv.status(copied, KI(ki.name, copied / "models" / ki.name / "ki"), man)["can_run"]


@pytest.mark.parametrize("relevant_change", ["ki", "helpers", "recipe"])
def test_pinned_origin_not_invalidated_by_unrelated_library_refresh(case, monkeypatch, tmp_path, relevant_change):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    library = tmp_path / "library"
    source = KI(ki.name, library / "models" / ki.name)
    shutil.copytree(ki.root, source.root)
    helpers = library / "ki_tools_common/ki_tools_common"
    helpers.mkdir(parents=True)
    helper_file = helpers / "__init__.py"
    helper_file.write_text("# fixture helpers\n", encoding="utf-8")
    marker = library / ".geoforge-library.json"
    marker.write_text(json.dumps({"content_sha256": "before", "trees": {"shared_tools": "helpers"}}), encoding="utf-8")
    result = pv.verify(project, ki, man, source_ki=source, library_root=library)
    assert result["ok"] and result["receipt"]["origin"]["snapshot_identity"]
    assert pv.status(project, ki, man, source_ki=source, library_root=library)["can_run"]
    marker.write_text(json.dumps({"content_sha256": "unrelated-model-update", "trees": {"shared_tools": "helpers"}}), encoding="utf-8")
    _forbid_checks(monkeypatch)
    assert pv.status(project, ki)["can_run"]
    assert pv.status(project, ki, man, source_ki=source, library_root=library)["can_run"]
    compared = man
    if relevant_change == "ki":
        (source.root / "SKILL.md").write_text("# Changed upstream KI\n", encoding="utf-8")
    elif relevant_change == "helpers":
        helper_file.write_text("# Changed helper behavior\n", encoding="utf-8")
    else:
        compared = replace(man, python_deps=["new-package>=2"])
    assert pv.status(project, ki)["can_run"]
    assert not pv.status(project, ki, compared, source_ki=source, library_root=library)["can_run"]


def test_exception_and_invalid_saved_config_revoke_old_pass(case, monkeypatch):
    project, ki, man, _cfg, config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    config.write_text("[invalid", encoding="utf-8")
    _forbid_checks(monkeypatch)
    assert pv.verify(project, ki, man)["state"] == "failed"
    assert pv.status(project, ki, man)["state"] == "failed"


def test_dispatch_compares_actual_launch_config_and_preserves_legacy(case, monkeypatch, tmp_path):
    project, ki, man, cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    _forbid_checks(monkeypatch)
    pv.require_current(project, ki.name, ki.root, cfg=cfg)
    cfg.python = "other-python"
    with pytest.raises(ValueError, match="launch configuration"):
        pv.require_current(project, ki.name, ki.root, cfg=cfg)
    pv.require_current(project, ki.name, tmp_path / "legacy-ki", cfg=cfg)
    with pytest.raises(ValueError, match="verification required"):
        pv.require_current(project, ki.name, project / "models" / "Other" / "ki")


def test_new_attempt_is_pending_before_any_identity_probe(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    def fail_identity(*_a, **_kw):
        doc = pv._read(pv._receipt_path(project, ki.name))
        assert doc["state"] == "pending" and doc["ok"] is False
        raise RuntimeError("identity probe failed")
    monkeypatch.setattr(pv, "_identity", fail_identity)
    result = pv.verify(project, ki, man)
    assert result["state"] == "failed" and "identity probe failed" in result["detail"]


def test_superseded_attempt_does_not_overwrite_newer_receipt(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    def preflight(*_a, **_kw):
        doc = pv._read(pv._receipt_path(project, ki.name))
        doc.pop("signature")
        doc["attempt_id"] = "newer-attempt"
        pv._write(project, ki.name, doc)
        return install.Step("preflight", True)
    monkeypatch.setattr(install, "run_preflight", preflight)
    assert pv.verify(project, ki, man)["state"] == "failed"
    assert pv.status(project, ki, man)["state"] == "pending"


def test_project_configuration_cannot_borrow_other_models_private_outputs(case, monkeypatch):
    project, ki, man, cfg, config = case
    (project / "models" / "Other").mkdir()
    cfg.roles["outputs"] = project / "outputs" / "Other"
    config.write_text(cfg.dumps(), encoding="utf-8")
    _forbid_checks(monkeypatch)
    assert not pv.verify(project, ki, man)["can_run"]


def test_preflight_exception_revokes_existing_pass(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    def failing(*_a, **_kw):
        raise RuntimeError("fixture launch exception")
    monkeypatch.setattr(install, "run_preflight", failing)
    result = pv.verify(project, ki, man)
    assert result["state"] == "failed" and "fixture launch exception" in result["detail"]
    assert not pv.status(project, ki, man)["can_run"]


def test_current_actual_manifest_is_used_at_read_only_dispatch(case, monkeypatch):
    project, ki, _man, _cfg, _config = case
    (ki.root / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: Demo\n", encoding="utf-8")
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(project.parent / "actual-manifest-guard"))
    ki_guard.enroll(ki.root)
    _passing(monkeypatch)
    assert pv.verify(project, ki, Manifest.load(ki.manifest))["ok"]
    _forbid_checks(monkeypatch)
    pv.require_current(project, ki.name, ki.root)


def test_alias_to_materialized_ki_cannot_take_legacy_route(case, monkeypatch, tmp_path):
    project, ki, man, _cfg, _config = case
    alias = tmp_path / "outside-alias"
    try:
        alias.symlink_to(ki.root, target_is_directory=True)
    except OSError:
        pytest.skip("Creating directory symlinks is unavailable on this host")
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    _forbid_checks(monkeypatch)
    with pytest.raises(ValueError, match="verification required"):
        pv.require_current(project, ki.name, alias)


def test_nested_session_directory_supports_long_receipt_paths(case, tmp_path):
    original, ki, man, shared, _config = case
    base = tmp_path / "sessions" / "investigate-existing-project"
    project = (base / ("nested-" + "x" * max(8, 218 - len(str(base)) - 8))).resolve()
    shutil.copytree(original, project)
    live = KI(ki.name, project / "models" / ki.name / "ki")
    cfg = project_paths.model_config(project, ki.name, shared)
    ki_guard._io(live.root.parent / "kiss.toml").write_text(cfg.dumps(), encoding="utf-8")
    ki_guard.enroll(live.root)
    # The current receipt itself exceeds MAX_PATH, not only the previous longer
    # temporary filename. This exercises the host's extended-path I/O spelling.
    assert len(str(pv._receipt_path(project, ki.name))) > 260
    result = pv.verify(project, live, man)
    assert result["ok"], result
    assert pv.status(project, live, man)["can_run"]
    assert ki_guard._io(pv._receipt_path(project, ki.name)).is_file()


def test_stop_after_last_identity_check_does_not_publish_pass(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    assert pv.verify(project, ki, man)["ok"]
    original = pv._identity
    calls, stopped = 0, False
    def stop_after_identity(*args, **kwargs):
        nonlocal calls, stopped
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            stopped = True
        return result
    monkeypatch.setattr(pv, "_identity", stop_after_identity)
    result = pv.verify(project, ki, man, stop=lambda: stopped)
    assert result["state"] == "cancelled" and not result["can_run"]
    assert pv.status(project, ki, man)["state"] == "cancelled"


@pytest.mark.parametrize("when", ["sign", "replace"])
def test_stop_during_receipt_publication_revokes_pass_under_operation(case, monkeypatch, when):
    project, ki, man, _cfg, _config = case
    # Use the real harmless preflight: the fixture only changes the instant
    # at which the user's cancellation becomes visible during receipt I/O.
    assert pv.verify(project, ki, man)["ok"]
    stopped = False
    published = []
    signer = pv._receipts()
    original_sign, original_replace = signer.sign, pv.os.replace
    target = ki_guard._io(pv._receipt_path(project, ki.name))

    def sign(authority, doc):
        nonlocal stopped
        result = original_sign(authority, doc)
        if when == "sign" and doc.get("state") == "verified":
            stopped = True
        return result

    def replace(source, destination):
        nonlocal stopped
        is_receipt = Path(destination) == target
        state = json.loads(Path(source).read_text(encoding="utf-8"))["state"] if is_receipt else None
        result = original_replace(source, destination)
        if is_receipt:
            published.append(state)
            if when == "replace" and state == "verified":
                stopped = True
        return result

    monkeypatch.setattr(signer, "sign", sign)
    monkeypatch.setattr(pv.os, "replace", replace)
    result = pv.verify(project, ki, man, stop=lambda: stopped)
    assert result["state"] == "cancelled" and not result["can_run"]
    assert pv.status(project, ki, man)["state"] == "cancelled"
    assert published[-1] == "cancelled"
    if when == "sign":
        assert "verified" not in published


def test_status_cannot_return_a_pass_being_revoked_during_publication(case, monkeypatch):
    project, ki, man, _cfg, _config = case
    _passing(monkeypatch)
    target = ki_guard._io(pv._receipt_path(project, ki.name))
    original_operation, original_replace = ki_guard.operation, pv.os.replace
    reader_at_lock = threading.Event()
    reader_results, readers = [], []
    stopped = False

    @contextmanager
    def operation(root):
        if threading.current_thread().name == "receipt-status-reader":
            reader_at_lock.set()
        with original_operation(root):
            yield

    def replace(source, destination):
        nonlocal stopped
        is_receipt = Path(destination) == target
        state = json.loads(Path(source).read_text(encoding="utf-8"))["state"] if is_receipt else None
        result = original_replace(source, destination)
        if state == "verified":
            reader = threading.Thread(target=lambda: reader_results.append(pv.status(project, ki, man)),
                                      name="receipt-status-reader", daemon=True)
            readers.append(reader)
            reader.start()
            assert reader_at_lock.wait(3), "status reader never reached the host operation lock"
            stopped = True
        return result

    monkeypatch.setattr(ki_guard, "operation", operation)
    monkeypatch.setattr(pv.os, "replace", replace)
    result = pv.verify(project, ki, man, stop=lambda: stopped)
    for reader in readers:
        reader.join(timeout=3)
        assert not reader.is_alive()
    assert result["state"] == "cancelled"
    assert len(reader_results) == 1 and reader_results[0]["state"] == "cancelled"
