"""Static portable-path lifecycle coverage, never a model or scientific pass.

Adaptation tests use the existing explicitly synthetic KDT reports to exercise
real host signatures, adoption and reuse. GUI tests use real helper preparation
and projection, without executing the synthetic preflight or model scripts.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import gui, implementation_identity, kdtstudio, ki_adaptations as adapt
from kiss_cli import ki_copy, ki_guard, ki_updates, ki_verification as gate
from kiss_cli import manifest as manifest_module, port, project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest
from .test_gui_project_helpers import case as gui_case, assert_setup_untouched
from .test_ki_adaptations import accepted
from .test_portable_path_route import CONTRACT, config, files, fixture as route_fixture, package


@pytest.fixture
def lifecycle(route_fixture, monkeypatch, request):
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    # Synthetic verifier identity only. No real KDT scientific review is claimed.
    monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "e" * 64)
    model = getattr(request, "param", "WOFOST")
    source = package(route_fixture.library / "models" / model, model)
    cfg, live = config(route_fixture, model, "initial project 中文")
    manifest = Manifest(model, runtime_paths=CONTRACT)
    adapt.materialise(source, live, cfg, model=model,
                      library_root=route_fixture.library, manifest=manifest)
    return SimpleNamespace(fixture=route_fixture, model=model, source=source,
                           cfg=cfg, live=live, manifest=manifest)


def draft(c):
    origin = adapt.projection(c.live, c.cfg)
    portable = c.fixture.base / "portable repair"
    ki_copy.copytree(Path(origin["portable_root"]), portable)
    preflight = portable / "preflight_check.py"
    text = preflight.read_text(encoding="utf-8")
    assert "REVISION = 1" in text
    preflight.write_text(text.replace("REVISION = 1", "REVISION = 2"), encoding="utf-8")
    runtime = c.fixture.base / "physical candidate"
    result, legacy_proof = adapt.project_runtime(
        portable, runtime, c.cfg, model=c.model, target_root=c.live, manifest=c.manifest,
    )
    assert not result.unresolved and not result.corrupted and legacy_proof is None
    return portable, runtime, accepted(portable), accepted(runtime)


def ticket(c, portable, runtime, portable_report, runtime_report):
    return adapt.prepare_registration(c.live, c.cfg, portable, portable_report,
                                      runtime, runtime_report)


@pytest.mark.parametrize("lifecycle", ["WOFOST", "Demo"], indirect=True)
def test_declared_repair_adopts_and_reuses_with_new_logical_target(lifecycle):
    c = lifecycle
    source_before, live_before = files(c.source), files(c.live)
    portable, runtime, portable_report, runtime_report = draft(c)
    prepared = ticket(c, portable, runtime, portable_report, runtime_report)

    assert files(c.live) == live_before, "Preparing a repair must not adopt it"
    assert not list((adapt._home() / "registry").glob("*.json"))
    ki_guard.activate(c.live, runtime, runtime_report, quiescent=True)
    registered = adapt.register(prepared, c.live, c.cfg)
    next_cfg, next_live = config(c.fixture, c.model, "second project with spaces")
    result = adapt.materialise(c.source, next_live, next_cfg, model=c.model,
        library_root=c.fixture.library, manifest=c.manifest)
    reused = adapt.projection(next_live, next_cfg)

    assert not result.unresolved and not result.corrupted
    assert reused["adaptation_id"] == registered["adaptation_id"]
    assert reused["projected_digest"] != registered["projected_digest"]
    assert reused["context"]["runtime_paths"] == CONTRACT
    assert reused["effective_manifest"]["runtime_paths"] == CONTRACT
    assert registered["logical_target"] == str(c.live)
    assert reused["logical_target"] == str(next_live)
    assert registered["path_projection"] is None and reused["path_projection"] is None
    for root, target, excluded in ((c.live, c.live, next_live), (next_live, next_live, c.live)):
        text = (root / "preflight_check.py").read_text(encoding="utf-8")
        assert "REVISION = 2" in text and target.as_posix() in text
        assert excluded.as_posix() not in text and runtime.as_posix() not in text
    retained = Path(reused["portable_root"])
    assert "KISSPATH_CURRENT_KI" in (retained / "preflight_check.py").read_text(encoding="utf-8")
    assert files(c.source) == source_before
    for name, content in source_before.items():
        if name.startswith("test_cases/"):
            for root in (c.live, next_live, retained):
                assert (root / name).read_bytes() == content
    for cfg, root in ((c.cfg, c.live), (next_cfg, next_live)):
        assert project_verification.status(cfg.root, KI(c.model, root))["can_run"] is False


@pytest.mark.parametrize("damage", [
    "missing-portable-kdt", "missing-runtime-kdt", "changed-portable", "changed-runtime",
])
def test_missing_or_stale_kdt_cannot_prepare_declared_repair(lifecycle, damage):
    c = lifecycle
    before = files(c.live)
    portable, runtime, portable_report, runtime_report = draft(c)
    if damage == "missing-portable-kdt":
        portable_report = None
    elif damage == "missing-runtime-kdt":
        runtime_report = None
    else:
        changed = portable if damage == "changed-portable" else runtime
        (changed / "run.py").write_text("raise AssertionError('changed after review')\n", encoding="utf-8")

    with pytest.raises(gate.VerificationError, match="missing or unauthenticated|changed after verification"):
        ticket(c, portable, runtime, portable_report, runtime_report)

    assert files(c.live) == before
    ki_guard.require_intact(c.live)
    assert not list((adapt._home() / "registry").glob("*.json"))


def test_declared_repair_cannot_register_before_exact_adoption(lifecycle):
    c = lifecycle
    prepared = ticket(c, *draft(c))
    before = files(c.live)

    with pytest.raises(adapt.AdaptationError, match="not been adopted"):
        adapt.register(prepared, c.live, c.cfg)

    assert files(c.live) == before
    assert not list((adapt._home() / "registry").glob("*.json"))


def test_reference_case_mutation_after_preparation_cannot_be_adopted(lifecycle):
    c = lifecycle
    portable, runtime, portable_report, runtime_report = draft(c)
    ticket(c, portable, runtime, portable_report, runtime_report)
    before = files(c.live)
    (runtime / "test_cases/example/inputs/raw.txt").write_bytes(b"changed scientific input\n")

    with pytest.raises((ValueError, RuntimeError), match="changed after verification"):
        ki_guard.activate(c.live, runtime, runtime_report, quiescent=True)

    assert files(c.live) == before
    ki_guard.require_intact(c.live)
    assert not list((adapt._home() / "registry").glob("*.json"))


@pytest.mark.parametrize("model", ["DSSAT", "VIC"])
def test_bundled_nonwofost_gui_fallback_contract_gets_complete_signed_projection(gui_case, monkeypatch, model):
    c = gui_case
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(c.base / "adaptations"))
    # Keep the fixture's isolated signing authority: it already enrolled the
    # existing install whose bytes and baseline must remain untouched.
    # Explicitly exercise the bundled library branch, not the snapshot branch.
    (c.library / ki_updates.SNAPSHOT_MANIFEST).unlink()
    source = package(c.library / "models" / model, model, manifest="absent")
    source_before = files(source)
    selected = KI(model, source)
    assert selected.manifest is None
    fallback = Manifest(model, runtime_paths=CONTRACT)
    c.handler._manifest = lambda ki: fallback

    def forbidden_copy(*_args, **_kwargs):
        raise AssertionError("A declared KI must not merge stale installed assets")

    monkeypatch.setattr(gui, "_copy_missing_assets", forbidden_copy)
    project = c.base / f"bundled {model} 中文"
    working, cfg = c.handler._session_workspace(project, selected)
    record = adapt.projection(working.root, cfg)

    assert record is not None and record["reusable"] is True
    assert record["context"]["runtime_paths"] == CONTRACT
    assert record["effective_manifest"]["runtime_paths"] == CONTRACT
    assert record["logical_target"] == str(project / "models" / model / "ki")
    assert record["portable_report"] is None and record["path_projection"] is None
    assert record["context"]["helper_source_digest"]
    assert working.root.as_posix() in (working.root / "preflight_check.py").read_text(encoding="utf-8")
    assert not (working.root / "binding.py").exists(), "Old installed-only assets must remain absent"
    assert files(source) == source_before
    for name, content in source_before.items():
        if name.startswith("test_cases/"):
            assert (working.root / name).read_bytes() == content
    reopened, reopened_cfg = c.handler._session_workspace(project, selected)
    assert reopened.root == working.root
    assert adapt.projection(reopened.root, reopened_cfg) == record
    assert not project_verification.status(project, working)["can_run"]
    assert_setup_untouched(c)


def freeze_path_modules(tmp_path, monkeypatch):
    modules = (adapt, port, manifest_module, implementation_identity)
    originals = {module: compile(Path(module.__file__).read_bytes(), module.__file__, "exec",
                                 dont_inherit=True, optimize=0) for module in modules}
    for module, code in originals.items():
        monkeypatch.setattr(module, "__file__", str(tmp_path / "source-free" / (module.__name__ + ".py")))
        monkeypatch.setattr(module, "__loader__", SimpleNamespace(get_code=lambda name, code=code: code))


def test_declared_projection_reopens_under_equivalent_source_free_loader(lifecycle, monkeypatch):
    c = lifecycle
    original = adapt.projection(c.live, c.cfg)
    identity = adapt._portable_path_identity()
    freeze_path_modules(c.fixture.base, monkeypatch)

    assert adapt._portable_path_identity() == identity
    assert adapt.projection(c.live, c.cfg) == original

    changed = compile("CHANGED_PORT_POLICY = True\n", "frozen/port.py", "exec")
    monkeypatch.setattr(port, "__loader__", SimpleNamespace(get_code=lambda name: changed))
    assert adapt._portable_path_identity() != identity
    with pytest.raises(adapt.AdaptationError, match="runtime path policy changed"):
        adapt.projection(c.live, c.cfg)


@pytest.mark.parametrize("loader", [None, SimpleNamespace(get_code=lambda name: None)])
def test_source_free_unidentifiable_policy_refuses_existing_projection(lifecycle, monkeypatch, loader):
    c = lifecycle
    freeze_path_modules(c.fixture.base, monkeypatch)
    monkeypatch.setattr(port, "__loader__", loader)

    with pytest.raises(implementation_identity.IdentityError, match="Cannot identify"):
        adapt.projection(c.live, c.cfg)
