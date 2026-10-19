"""Desktop-only portable-role projection with synthetic, never-executed KIs.

These are path/provenance integration tests, not native model or E2E tests.
The real host copy, guard and signature code runs; no KDT pass is fabricated.
"""
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import ki_adaptations as adapt, ki_copy, ki_guard, paths, project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest, document
from .test_ki_adaptations import prepare_helpers


CONTRACT = {"version": 1, "mode": "role_tokens"}


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in Path(root).rglob("*") if p.is_file()}


def package(root, model, *, manifest="declared", revision=1):
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f"# {model}: synthetic portable-path fixture\n", encoding="utf-8")
    # Deliberately unlike the old model-specific AST whitelist. If accidentally
    # launched, either script fails rather than simulating a model result.
    (root / "preflight_check.py").write_text(
        "from pathlib import Path\n"
        "CURRENT = Path('KISSPATH_CURRENT_KI')\n"
        "PYTHON = 'KISSPATH_PYTHON'\n"
        f"REVISION = {revision}\n"
        "raise AssertionError('synthetic preflight must never execute')\n", encoding="utf-8")
    (root / "run.py").write_text(
        "raise AssertionError('synthetic model must never execute')\n", encoding="utf-8")
    (root / "knowledge_infrastructure.yaml").write_text(yaml.safe_dump({"package": {
        "name": model, "language": "python", "binary": {
            "path": "KISSPATH_CURRENT_KI/run.py", "type": "Python"}}}), encoding="utf-8")
    if manifest != "absent":
        data = {"kiss_manifest_version": 1, "model": model}
        if manifest == "declared":
            data["runtime_paths"] = CONTRACT
        (root / "kiss.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    cases = root / "test_cases/example"
    (cases / "inputs").mkdir(parents=True)
    (cases / "manifest.json").write_bytes(b'{"entry":"KISSPATH_CURRENT_KI/run.py"}\r\n')
    (cases / "expected.json").write_bytes(b'{"historical_path":"KISSPATH_DATA/site"}\n')
    (cases / "inputs/raw.txt").write_bytes(b"literal KISSPATH_CURRENT_KI\r\nscientific input\n")
    ki_guard.enroll(root)
    return root


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "authority"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    library = tmp_path / "library"
    helper_source = library / "ki_tools_common"
    helper_source.mkdir(parents=True)
    (helper_source / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    helpers = tmp_path / "prepared-helpers"
    prepare_helpers(library, helpers)
    return SimpleNamespace(base=tmp_path, library=library, helpers=helpers)


def config(fixture, model, name="project 中文", *, installation=False):
    cfg = paths.KissConfig.default(fixture.base / name)
    cfg.python = str(cfg.root / "runtime/python.exe")  # A binding only; never created or launched.
    cfg.relocation = "none"
    cfg.roles["ki_root"] = cfg.root / "models"
    cfg.roles["ki_tools_common"] = fixture.helpers
    target = cfg.root / "ki" if installation else cfg.root / "models" / model / "ki"
    return cfg, target


@pytest.mark.parametrize("model", ["WOFOST", "DSSAT", "SHAW", "VIC"])
@pytest.mark.parametrize("installation", [False, True])
def test_explicit_contract_projects_arbitrary_model_shape_without_execution(fixture, model, installation):
    source = package(fixture.library / "models" / model, model)
    cfg, logical = config(fixture, model, installation=installation)
    candidate = fixture.base / "physical staging" / model
    before = files(source)

    report, proof = adapt.project_runtime(source, candidate, cfg, model=model, target_root=logical)

    assert not report.unresolved and not report.corrupted
    assert proof is None, "Generic projection must not fabricate the legacy WOFOST runtime proof"
    projected = (candidate / "preflight_check.py").read_text(encoding="utf-8")
    assert logical.as_posix() in projected and cfg.python.replace("\\", "/") in projected
    assert candidate.as_posix() not in projected and source.as_posix() not in projected
    assert yaml.safe_load((candidate / "knowledge_infrastructure.yaml").read_text(encoding="utf-8"))[
        "package"]["binary"]["path"] == logical.as_posix() + "/run.py"
    assert files(source) == before
    for name, content in before.items():
        if name.startswith("test_cases/") or name == "run.py":
            assert (candidate / name).read_bytes() == content
    assert not logical.exists()
    assert not Path(cfg.python).exists()
    assert not ki_guard.is_managed(candidate), "Raw projection must not enroll or verify its candidate"
    assert project_verification.status(cfg.root, KI(model, logical))["can_run"] is False


@pytest.mark.parametrize("format", ["object", "document"])
def test_shipped_effective_manifest_can_opt_in_when_source_has_no_manifest(fixture, format):
    source = package(fixture.library / "models/WOFOST", "WOFOST", manifest="absent")
    cfg, target = config(fixture, "WOFOST")
    supplied = Manifest("WOFOST", runtime_paths=CONTRACT)
    if format == "document":
        supplied = document(supplied)

    assert adapt.runtime_path_contract(source, "WOFOST", manifest=supplied) == CONTRACT
    report, proof = adapt.project_runtime(source, target, cfg, model="WOFOST",
                                          target_root=target, manifest=supplied)
    assert not report.unresolved and not report.corrupted and proof is None
    assert target.as_posix() in (target / "preflight_check.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("source_manifest", ["absent", "legacy"])
def test_no_opt_in_keeps_unknown_wofost_on_strict_legacy_route(fixture, source_manifest):
    source = package(fixture.library / "models/WOFOST", "WOFOST", manifest=source_manifest)
    cfg, target = config(fixture, "WOFOST")
    before = files(source)

    with pytest.raises((ValueError, RuntimeError), match="Unsupported|Unrecognized|WOFOST"):
        adapt.project_runtime(source, target, cfg, model="WOFOST", target_root=target)

    assert not target.exists()
    assert files(source) == before


@pytest.mark.parametrize("source_declared,supplied", [
    (True, Manifest("WOFOST")),
    (False, Manifest("WOFOST", runtime_paths=CONTRACT)),
    (True, Manifest("VIC", runtime_paths=CONTRACT)),
])
def test_source_and_effective_contract_mismatch_rejected_before_writes(fixture, source_declared, supplied):
    source = package(fixture.library / "models/WOFOST", "WOFOST",
                     manifest="declared" if source_declared else "legacy")
    cfg, target = config(fixture, "WOFOST")
    before = files(source)

    with pytest.raises((ValueError, RuntimeError)):
        adapt.project_runtime(source, target, cfg, model="WOFOST", target_root=target, manifest=supplied)

    assert not target.exists()
    assert files(source) == before


@pytest.mark.parametrize("declaration", [
    {"version": True, "mode": "role_tokens"},
    {"version": 1, "mode": "guess"},
    {"version": 1, "mode": "role_tokens", "bypass_verification": True},
])
def test_canonical_manifest_argument_cannot_bypass_contract_validation(fixture, declaration):
    source = package(fixture.library / "models/WOFOST", "WOFOST", manifest="absent")
    cfg, target = config(fixture, "WOFOST")
    supplied = {"model": "WOFOST", "runtime_paths": declaration}

    with pytest.raises(ValueError, match="runtime_paths"):
        adapt.project_runtime(source, target, cfg, model="WOFOST", target_root=target, manifest=supplied)

    assert not target.exists()


@pytest.mark.parametrize("destination", ["other-model", "elsewhere"])
def test_explicit_contract_cannot_bind_another_logical_target(fixture, destination):
    source = package(fixture.library / "models/WOFOST", "WOFOST")
    cfg, _ = config(fixture, "WOFOST")
    wrong = cfg.root / "models/VIC/ki" if destination == "other-model" else fixture.base / "outside"
    staging = fixture.base / "staging"

    with pytest.raises((ValueError, RuntimeError)):
        adapt.project_runtime(source, staging, cfg, model="WOFOST", target_root=wrong)

    assert not staging.exists() and not wrong.exists()


def materialized(fixture):
    source = package(fixture.library / "models/WOFOST", "WOFOST")
    cfg, live = config(fixture, "WOFOST")
    man = Manifest("WOFOST", runtime_paths=CONTRACT)
    report = adapt.materialise(source, live, cfg, model="WOFOST", library_root=fixture.library, manifest=man)
    assert not report.unresolved and not report.corrupted
    record = adapt.projection(live, cfg)
    assert record["context"]["runtime_paths"] == CONTRACT
    assert record["effective_manifest"]["runtime_paths"] == CONTRACT
    assert record["path_projection"] is None
    assert record["portable_report"] is None and record["adaptation_id"] is None
    assert record["context"]["path_normalizer"]
    assert project_verification.status(cfg.root, KI("WOFOST", live))["can_run"] is False
    return source, cfg, live, record


def test_source_update_with_same_declaration_projects_into_new_project(fixture):
    source, cfg, live, record = materialized(fixture)
    previous = files(live)
    updated_library = fixture.base / "updated-library"
    ki_copy.copytree(fixture.library / "ki_tools_common", updated_library / "ki_tools_common")
    updated_source = package(updated_library / "models/WOFOST", "WOFOST", revision=2)
    next_cfg, next_live = config(fixture, "WOFOST", "new project")

    report = adapt.materialise(updated_source, next_live, next_cfg, model="WOFOST",
        library_root=updated_library, manifest=Manifest("WOFOST", runtime_paths=CONTRACT))
    current = adapt.projection(next_live, next_cfg)

    assert not report.unresolved and not report.corrupted
    assert "REVISION = 2" in (next_live / "preflight_check.py").read_text(encoding="utf-8")
    assert current["upstream_digest"] != record["upstream_digest"]
    assert current["context"]["path_normalizer"] == record["context"]["path_normalizer"]
    assert files(live) == previous and adapt.projection(live, cfg)["upstream_digest"] == record["upstream_digest"]


@pytest.mark.parametrize("changed", ["retained-source", "helpers", "config", "declaration"])
def test_stored_projection_detects_context_drift(fixture, changed):
    _, cfg, live, record = materialized(fixture)
    if changed == "retained-source":
        (Path(record["portable_root"]) / "run.py").write_text("changed retained source\n", encoding="utf-8")
    elif changed == "helpers":
        (fixture.helpers / "helper.py").write_text("VALUE = 2\n", encoding="utf-8")
    elif changed == "config":
        cfg.python = str(cfg.root / "another-runtime/python.exe")
    else:
        # Retain a valid host signature while testing inconsistent declaration
        # fields; this is not a simulated provider ability to sign authority.
        altered = copy.deepcopy(record)
        altered["effective_manifest"]["runtime_paths"] = None
        adapt._write(adapt._location(live), altered)

    with pytest.raises((ValueError, RuntimeError)):
        adapt.projection(live, cfg)


@pytest.mark.parametrize("policy", ["projection", "normalizer"])
def test_changed_projection_policy_invalidates_current_generic_proof(fixture, monkeypatch, policy):
    _, cfg, live, _ = materialized(fixture)
    if policy == "projection":
        monkeypatch.setattr(adapt, "PROJECTION_POLICY", "changed-projection-policy")
    else:
        monkeypatch.setattr(adapt, "_portable_path_identity", lambda: "changed-normalizer-policy")

    with pytest.raises((ValueError, RuntimeError)):
        adapt.projection(live, cfg)
