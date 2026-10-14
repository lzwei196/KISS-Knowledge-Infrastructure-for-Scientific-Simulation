"""Intake reads exact approved portable bytes without creating runtime authority.

KDT signatures use the synthetic gate fixture from test_ki_adaptations. No model,
provider or installer runs; GUI transport seams capture the actual arguments.
"""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import api, flowrun, gui, ki_adaptations as adapt, ki_guard, ki_intake
from kiss_cli import paths, projectrun, providers, sessions, settings
from kiss_cli.catalog import KI
from .test_ki_adaptations import case, accepted, prepared


class Catalogue(list):
    def __init__(self, source):
        super().__init__([KI("Demo", source)])
        self.models_dir = source.parent

    def get(self, name):
        return next(ki for ki in self if ki.name == name)


@pytest.fixture
def repaired(case):
    ticket, portable, runtime = prepared(case)
    for root in (portable, runtime):
        (root / "diagnostics").mkdir()
        (root / "diagnostics" / "reader.md").write_text("Reader remedy: corrected portable columns.\n")
    ticket = adapt.prepare_registration(case.live, case.cfg, portable, accepted(portable),
                                        runtime, accepted(runtime))
    ki_guard.activate(case.live, runtime, ticket["runtime_report"], quiescent=True)
    adapt.register(ticket, case.live, case.cfg)
    (case.cfg.root / "kiss.toml").write_text(case.cfg.dumps(), encoding="utf-8")
    case.catalog = Catalogue(case.source)
    return case


def read_map(case):
    return ki_intake.build(case.catalog, workdir_for=lambda _: case.cfg.root,
                           manifest_for=lambda _: case.manifest, library_root=case.library)


def files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(root).rglob("*") if p.is_file()}


def test_effective_map_keeps_identity_provenance_and_all_bytes_unchanged(repaired):
    before = files(repaired.base)
    view = read_map(repaired)
    item = view.entry("dEmO")
    file, root = view.resolve("DEMO", "reader.py")
    assert "return 2" in file.read_text()
    assert "return 1" in (repaired.source / "reader.py").read_text()
    assert item["model"] == "Demo" and item["origin"] == "approved_portable_repair"
    assert item["can_run"] is False and item["portable_report"]["ok"]
    assert root.name != "Demo"
    assert view.read_roots(repaired.catalog.models_dir) == [repaired.catalog.models_dir, root]
    assert "inspection only" in sessions.catalogue_block(repaired.catalog, read_map=view)
    assert files(repaired.base) == before


@pytest.mark.parametrize("name,path", [("Demo", "Demo/SKILL.md"), (None, "Demo/Demo/SKILL.md"),
    (None, "Unknown/SKILL.md"), (None, "Demo/../SKILL.md"), ("Demo", "/etc/passwd"),
    ("Demo", "C:\\secret"), ("Demo", "..\\secret"), ("Unknown", "SKILL.md")])
def test_map_rejects_ambiguous_or_escaping_paths(repaired, name, path):
    with pytest.raises(ValueError):
        read_map(repaired).resolve(name, path)


def test_missing_installation_is_explicit_upstream_inspection(repaired):
    (repaired.cfg.root / "kiss.toml").unlink()
    view = read_map(repaired).entry("Demo")
    assert view["root"] == str(repaired.source)
    assert "no saved installation" in view["notice"] and not view["can_run"]


def test_legacy_toml_repair_is_only_in_memory(repaired):
    file = repaired.cfg.root / "kiss.toml"
    file.write_text('[kiss]\nroot = ' + paths._toml_str(repaired.cfg.root) + '\n[paths]\ndata = "C:\\Users\\sample"\n')
    before = file.read_bytes()
    cfg = ki_intake.saved_config(repaired.cfg.root)
    assert str(cfg.roles["data"]) == "C:\\Users\\sample"
    assert file.read_bytes() == before


def test_api_reads_lists_and_diagnostics_use_same_effective_map(repaired):
    project = repaired.base / "intake"
    project.mkdir()
    pre = flowrun.pre(project, "run Demo rainfall-runoff simulation for 2001-2002", [], repaired.catalog, None, None)
    assert pre.gated
    turn = flowrun.auto_turn(project, "api", "deepseek", database_access_mode="off")
    cfg = paths.KissConfig.default(project)
    library = KI("library", repaired.catalog.models_dir)
    context = {"project_root": project, "intake_ki_read_map": read_map(repaired)}

    def call(name, args):
        return api.execute_tool(name, args, library, cfg, project_mode=True,
                                setup_context=context, flow=turn.session)

    assert "return 2" in call("read_ki_file", {"path": "dEmO/reader.py"})
    assert "return 2" in call("read_ki_file", {"ki": "DEMO", "path": "reader.py"})
    assert "diagnostics/reader.md" in call("list_ki_files", {"ki": "Demo"})
    assert "Demo/SKILL.md" == call("list_ki_files", {})
    assert "corrected portable columns" in call("search_diagnostics", {"keyword": "remedy"})
    assert "corrected portable columns" in call("search_diagnostics", {"ki": "Demo", "keyword": "remedy"})
    with pytest.raises(api.ToolError):
        call("read_ki_file", {"path": "Demo/../Demo/reader.py"})
    with pytest.raises(api.ToolError):
        call("run_ki_tool", {"tool": "reader.py", "argv": []})
    assert turn.session.ki_roots == {} and turn.session.ctx.selected_kis == []
    assert not (project / "models").exists()


@pytest.mark.parametrize("want", ["api:deepseek", "cli:claude", "cli:codex", "cli:kimi"])
def test_gui_intake_api_cli_share_source_without_materialising_remembered_choice(repaired, monkeypatch, want):
    project = repaired.base / "new-project"
    project.mkdir()
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(repaired.base / "flow-index.json"))
    monkeypatch.setattr(settings, "database_access_mode", lambda: "off")
    pre = flowrun.pre(project, "run Demo rainfall-runoff simulation for 2001-2002", [], repaired.catalog, None, None)
    assert pre.gated
    # A previous intake can remember a choice without authorising setup or execution.
    projectrun.report(project, {"selected_kis": ["Demo"], "summary": "Choice only"})
    handler = object.__new__(gui.Handler)
    handler.catalog, handler.workroot, handler.library_root = repaired.catalog, repaired.base, repaired.library
    handler._workdir = lambda _: repaired.cfg.root
    handler._manifest = lambda _: repaired.manifest
    handler._status_for = lambda _: {"label": "Verified", "can_run": True}
    handler._session_workspaces = lambda *_: pytest.fail("intake materialised a runtime KI")
    capture = {}
    def api_run(_provider, _ki, _cfg, system, task, **kwargs):
        capture.update(system=system, **kwargs)
        yield "Fixture transport only"
    def cli_turn(_provider, **kwargs):
        capture.update(system=kwargs["replay_prompt"], **kwargs)
    monkeypatch.setattr(api, "run", api_run)
    handler._cli_turn = cli_turn
    fake = SimpleNamespace(name=want.partition(":")[2])
    monkeypatch.setattr(providers, "available", lambda: [fake])
    monkeypatch.setattr(providers, "get", lambda _: fake)
    monkeypatch.setattr(flowrun, "wrapper_commands", lambda: {"request_user_action": "geoforge-request"})
    messages = []
    handler._chat_auto(want, "Simulate with Demo using its shipped example", messages.append, project, flow_pre=pre)
    assert capture, messages
    effective = Path(read_map(repaired).entry("Demo")["root"])
    assert str(effective / "SKILL.md") in capture["system"]
    assert "KDT-approved compatible portable repair" in capture["system"]
    assert "<models_root>/<name>/SKILL.md" not in capture["system"]
    assert not (project / "models").exists() and not (project / "kiss.toml").exists()
    if want.startswith("api"):
        assert capture["setup_context"]["intake_ki_read_map"].entry("Demo")["root"] == str(effective)
        assert capture["flow"].ctx.selected_kis == [] and capture["flow"].ki_roots == {}
    else:
        assert str(effective) in capture["extra_dirs"]
        assert str(adapt._home()) not in capture["extra_dirs"]
        assert str(effective.parent) not in capture["extra_dirs"]
        assert capture["managed_roots"] == []
        if want == "cli:claude":
            grants = " ".join(capture["flow_policy"].argv_delta)
            assert f"/sources/{effective.name}/**)" in grants.replace("\\", "/")
            assert "Write(" not in grants and "Edit(" not in grants and "run-tool" not in grants


@pytest.mark.parametrize("change", ["source", "recipe", "helpers", "binding"])
def test_incompatible_repair_has_explicit_reconciliation_notice(repaired, change):
    if change == "source":
        from kiss_cli import ki_copy
        alternate = repaired.base / "new-snapshot"
        ki_copy.copytree(repaired.library, alternate)
        repaired.library = alternate
        repaired.source = alternate / "models" / "Demo"
        repaired.catalog = Catalogue(repaired.source)
        (repaired.source / "new-file").write_text("New upstream version")
    elif change == "recipe":
        repaired.manifest.notes = "Changed installation recipe"
    elif change == "helpers":
        (repaired.library / "ki_tools_common" / "helper.py").write_text("VALUE = 3\n")
    else:
        from kiss_cli import helper_identity
        (repaired.helpers / helper_identity.MARKER).unlink()
    view = read_map(repaired).entry("Demo")
    assert view["origin"] == "upstream" and not view["can_run"]
    assert "reconcil" in view["notice"] or "requires normal project verification" in view["notice"]


@pytest.mark.parametrize("target", ["registry", "portable", "report"])
def test_corrupt_retained_repair_fails_visibly_without_upstream_fallback(repaired, target, monkeypatch):
    view = read_map(repaired).entry("Demo")
    if target == "registry":
        next((adapt._home() / "registry").glob("*.json")).write_text("{}")
    elif target == "portable":
        (Path(view["root"]) / "reader.py").write_text("Corrupted retained source")
    else:
        from kiss_cli import kdtstudio
        monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "f" * 64)
    with pytest.raises(ValueError):
        read_map(repaired)


def test_uninstalled_catalogue_inspection_creates_no_config_or_keys(case):
    case.catalog = Catalogue(case.source)
    view = read_map(case).entry("Demo")
    assert view["origin"] == "upstream" and not view["can_run"]
    assert not (case.cfg.root / "kiss.toml").exists()
    assert "grants no verified readiness" in view["notice"]


@pytest.mark.parametrize("change", ["helpers", "config", "registry"])
def test_captured_view_cannot_keep_old_repair_after_compatibility_changes(repaired, change):
    view = read_map(repaired)
    if change == "helpers":
        (repaired.library / "ki_tools_common" / "helper.py").write_text("VALUE = 3\n")
    elif change == "config":
        (repaired.cfg.root / "kiss.toml").unlink()
    else:
        next((adapt._home() / "registry").glob("*.json")).write_text("{}")
    with pytest.raises(ValueError):
        view.resolve("Demo", "reader.py")


def legacy_marker(case):
    from kiss_cli import helper_identity
    binding = {"source_commit": "fixture", "source_tree": "fixture", "roles": {}}
    value = {**binding, "binding_sha256": hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest(),
             "files": helper_identity.package_files(case.helpers)}
    (case.helpers / helper_identity.MARKER).write_text(json.dumps(value), encoding="utf-8")


def test_checked_legacy_helpers_allow_portable_inspection_but_not_runtime_reuse(repaired):
    from .test_ki_adaptations import fresh
    legacy_marker(repaired)
    view = read_map(repaired).entry("Demo")
    assert view["origin"] == "approved_portable_repair" and not view["can_run"]
    assert view["helper_context"] == "selected_source" and view["saved_helper_source"] is None
    assert "legacy or older" in view["notice"] and "runtime helper preparation" in view["notice"]
    # Existing materialisation still requires an actual prepared helper source.
    live, cfg = fresh(repaired, "legacy-runtime-check")
    assert "return 1" in (live / "reader.py").read_text()
    assert adapt.projection(live, cfg)["adaptation_id"] is None


def test_corrupt_legacy_marker_cannot_expose_repair(repaired):
    legacy_marker(repaired)
    (repaired.helpers / "helper.py").write_text("Corrupt installed helper")
    with pytest.raises(ValueError, match="changed locally"):
        read_map(repaired)


def test_changed_host_helper_source_requires_new_exact_approved_context(repaired):
    legacy_marker(repaired)
    (repaired.library / "ki_tools_common" / "helper.py").write_text("VALUE = 77\n")
    view = read_map(repaired).entry("Demo")
    assert view["origin"] == "upstream" and not view["can_run"]
    assert "previous repair was retained" in view["notice"]
