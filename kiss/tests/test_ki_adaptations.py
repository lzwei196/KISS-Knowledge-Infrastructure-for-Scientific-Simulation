"""Exact portable repair lifecycle; real copies/signatures, no model launches.

The KDT report fixture is explicitly synthetic. These tests exercise provenance
and acceptance boundaries, not KDT's scientific/package review implementation.
"""
from pathlib import Path
import json
import sys
from types import SimpleNamespace

import pytest

from kiss_cli import doctor, helper_identity, kdtstudio, ki_adaptations as adapt, ki_copy, ki_guard
from kiss_cli import ki_verification as gate, paths, port, project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_ADAPTATION_HOME", str(tmp_path / "adaptations"))
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.delenv("GEOFORGE_KDT_ENGINE", raising=False)
    monkeypatch.setattr(kdtstudio, "engine_source_digest", lambda: "e" * 64)
    library = tmp_path / "library"
    source = library / "models" / "Demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# Demo portable fixture\n")
    (source / "reader.py").write_text("output = 'KISSPATH_OUTPUTS/result.txt'\ndef read(): return 1\n")
    (source / "preflight_check.py").write_text("print('fixture; never launched')\n")
    (source / "kiss.yaml").write_text("kiss_manifest_version: 1\nmodel: Demo\n")
    helpers = library / "ki_tools_common"
    helpers.mkdir()
    (helpers / "helper.py").write_text("VALUE = 1\n")
    prepared_helpers = tmp_path / "prepared-helpers"
    prepare_helpers(library, prepared_helpers)
    ki_guard.enroll(source)
    c = SimpleNamespace(base=tmp_path, source=source, library=library,
                        manifest=Manifest(model="Demo"), helpers=prepared_helpers)
    c.live, c.cfg = fresh(c, "project-a")
    return c


def prepare_helpers(library, target):
    ki_copy.copytree(library / "ki_tools_common", target)
    binding = {"source_files": helper_identity.package_files(library / "ki_tools_common")}
    marker = {"schema_version": 2, "binding": binding,
              "binding_sha256": adapt._hash(binding), "files": helper_identity.package_files(target)}
    # The marker hash uses its module's canonical serialization contract.
    import hashlib
    marker["binding_sha256"] = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
    (target / helper_identity.MARKER).write_text(json.dumps(marker))


def accepted(root):
    return gate._seal(root, {"ok": True, "gate_policy": gate.GATE_POLICY,
        "kind": "process_model", "desktop_requested": True,
        "doctor_policy": doctor.VALIDATION_POLICY_VERSION,
        "engine_policy": kdtstudio.REVIEWED_COMMIT,
        "engine_source_digest": "e" * 64, "engine_override": False,
        "candidate_digest": gate.content_digest(root)})


def fresh(case, name, *, source=None, manifest=None, library=None):
    project = case.base / name
    cfg = paths.KissConfig.default(project)
    cfg.python, cfg.relocation = sys.executable, "none"
    cfg.roles["ki_root"] = project / "models"
    cfg.roles["ki_tools_common"] = case.helpers
    live = project / "models" / "Demo" / "ki"
    adapt.materialise(source or case.source, live, cfg, model="Demo",
                      library_root=library or case.library, manifest=manifest or case.manifest)
    return live, cfg


def prepared(case, *, extra=""):
    origin = adapt.projection(case.live, case.cfg)
    portable = case.base / "portable-candidate"
    ki_copy.copytree(Path(origin["portable_root"]), portable)
    source = portable / "reader.py"
    source.write_text(source.read_text().replace("return 1", "return 2") + extra)
    runtime = case.base / "runtime-candidate"
    port.materialise(portable, runtime, case.cfg)
    ticket = adapt.prepare_registration(case.live, case.cfg, portable, accepted(portable),
                                         runtime, accepted(runtime))
    return ticket, portable, runtime


def adopted(case):
    ticket, portable, runtime = prepared(case)
    ki_guard.activate(case.live, runtime, ticket["runtime_report"], quiescent=True)
    record = adapt.register(ticket, case.live, case.cfg)
    return ticket, portable, runtime, record


def test_portable_repair_rebinds_new_project_and_requires_verification(case):
    _, _, _, first = adopted(case)
    second, cfg = fresh(case, "project-b")
    record = adapt.projection(second, cfg)
    text = (second / "reader.py").read_text()
    assert "return 2" in text
    assert cfg.roles["outputs"].as_posix() in text
    assert case.cfg.roles["outputs"].as_posix() not in text
    assert record["adaptation_id"] == first["adaptation_id"]
    assert record["projected_digest"] != first["projected_digest"]
    assert "KISSPATH_OUTPUTS" in (Path(record["portable_root"]) / "reader.py").read_text()
    assert project_verification.status(cfg.root, KI("Demo", second))["can_run"] is False


def test_unrelated_library_commit_and_folder_do_not_invalidate_reuse(case):
    adopted(case)
    alternate = case.base / "unrelated-new-snapshot"
    ki_copy.copytree(case.library, alternate)
    (alternate / ".geoforge-library.json").write_text(json.dumps({"source_commit": "b" * 40}))
    second, cfg = fresh(case, "project-b", source=alternate / "models/Demo", library=alternate)
    assert "return 2" in (second / "reader.py").read_text()
    assert adapt.projection(second, cfg)["reconciliation_needed"] is False


@pytest.mark.parametrize("change", ["source", "recipe", "helpers", "projection"])
def test_changed_relevant_context_preserves_repair_without_replaying(case, change, monkeypatch):
    adopted(case)
    alternate = case.base / "new-snapshot"
    ki_copy.copytree(case.library, alternate)
    manifest = case.manifest
    if change == "source":
        (alternate / "models/Demo/new.txt").write_text("new upstream file")
    elif change == "recipe":
        manifest = Manifest(model="Demo", notes="new installation requirement")
    elif change == "helpers":
        (alternate / "ki_tools_common/helper.py").write_text("VALUE = 2\n")
        replacement = case.base / "prepared-helpers-new"
        prepare_helpers(alternate, replacement)
        case.helpers = replacement
    else:
        monkeypatch.setattr(adapt, "PROJECTION_POLICY", "changed-projection")
    second, cfg = fresh(case, "project-b", source=alternate / "models/Demo",
                        library=alternate, manifest=manifest)
    assert "return 1" in (second / "reader.py").read_text()
    record = adapt.projection(second, cfg)
    assert record["adaptation_id"] is None
    assert record["reconciliation_needed"] is True
    assert record["reconciliation"]["previous_adaptations"]
    assert "return 2" in (case.live / "reader.py").read_text()
    assert adapt.projection(case.live, case.cfg)["adaptation_id"]


def test_platform_change_never_reuses_repair(case, monkeypatch):
    adopted(case)
    monkeypatch.setattr(adapt, "installation_platform", lambda: "different-platform")
    second, cfg = fresh(case, "project-b")
    assert "return 1" in (second / "reader.py").read_text()
    assert adapt.projection(second, cfg)["adaptation_id"] is None


def test_registration_requires_prior_exact_runtime_adoption(case):
    ticket, _, _ = prepared(case)
    with pytest.raises(adapt.AdaptationError, match="not been adopted"):
        adapt.register(ticket, case.live, case.cfg)
    second, _ = fresh(case, "project-b")
    assert "return 1" in (second / "reader.py").read_text()


@pytest.mark.parametrize("target", ["registry", "projection", "prepared"])
def test_forged_record_cannot_authorize_reuse(case, target):
    if target == "prepared":
        ticket, _, runtime = prepared(case)
        ticket["runtime_digest"] = "0" * 64
        with pytest.raises(adapt.AdaptationError, match="invalid"):
            adapt.register(ticket, case.live, case.cfg)
        return
    adopted(case)
    path = (next((adapt._home() / "registry").glob("*.json")) if target == "registry"
            else adapt._location(case.live))
    value = json.loads(path.read_text())
    value["portable_digest"] = "0" * 64
    path.write_text(json.dumps(value))
    with pytest.raises(adapt.AdaptationError, match="invalid"):
        if target == "registry":
            fresh(case, "project-b")
        else:
            adapt.projection(case.live, case.cfg)


def test_modified_retained_portable_bytes_refuse_reuse(case):
    _, _, _, record = adopted(case)
    (Path(record["portable_root"]) / "reader.py").write_text("modified cache")
    with pytest.raises(adapt.AdaptationError, match="retained|Retained"):
        fresh(case, "project-b")


def test_stale_kdt_policy_refuses_reuse(case, monkeypatch):
    adopted(case)
    monkeypatch.setattr(gate, "GATE_POLICY", "new-gate-policy")
    with pytest.raises(gate.VerificationError, match="gate contract"):
        fresh(case, "project-b")


def test_runtime_candidate_must_be_exact_portable_projection(case):
    origin = adapt.projection(case.live, case.cfg)
    portable = Path(origin["portable_root"])
    runtime = case.base / "runtime-candidate"
    port.materialise(portable, runtime, case.cfg)
    (runtime / "reader.py").write_text("different = 1\n")
    with pytest.raises(adapt.AdaptationError, match="exact projection"):
        adapt.prepare_registration(case.live, case.cfg, portable, accepted(portable), runtime, accepted(runtime))


@pytest.mark.parametrize("literal", ["D:/private/model.exe", "/home/someone/model", "\\\\server\\share\\model.exe"])
def test_new_machine_paths_are_rejected_before_adoption(case, literal):
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        prepared(case, extra="executable = " + repr(literal) + "\n")
    assert "return 1" in (case.live / "reader.py").read_text()
    assert not list((adapt._home() / "registry").glob("*.json"))


def test_existing_upstream_absolute_provenance_is_not_rewritten(case):
    # Exercise the focused scanner directly: legacy literals may remain;
    # adding a new project binding is not made portable by old provenance.
    before = case.base / "before"
    after = case.base / "after"
    before.mkdir(); after.mkdir()
    text = "legacy = '/mnt/disk1/known/input'\nvalue = 1\n"
    (before / "run.py").write_text(text)
    (after / "run.py").write_text(text.replace("value = 1", "value = 2"))
    adapt._portable_changes(before, after, case.cfg)


def test_changed_runtime_bindings_invalidate_lineage(case):
    case.cfg.python = "changed-python"
    with pytest.raises(adapt.AdaptationError, match="runtime binding changed"):
        adapt.projection(case.live, case.cfg)


def test_legacy_absence_and_unmarked_helpers_remain_local_only(case):
    legacy = case.base / "legacy"
    assert adapt.projection(legacy, case.cfg) is None
    cfg = paths.KissConfig.default(case.base / "legacy-project")
    live = cfg.root / "ki"
    adapt.materialise(case.source, live, cfg)
    record = adapt.projection(live, cfg)
    assert record["reusable"] is False
    with pytest.raises(adapt.AdaptationError, match="proven portable"):
        adapt.prepare_registration(live, cfg, case.source, accepted(case.source), live, accepted(live))


def test_existing_active_destination_is_never_overwritten(case):
    before = gate.content_digest(case.live)
    with pytest.raises(adapt.AdaptationError, match="new empty destination"):
        adapt.materialise(case.source, case.live, case.cfg, library_root=case.library)
    assert gate.content_digest(case.live) == before


def test_wrong_prepared_helpers_are_not_called_reusable(case):
    alternate = case.base / "wrong-library"
    ki_copy.copytree(case.library, alternate)
    (alternate / "ki_tools_common/helper.py").write_text("VALUE = 99\n")
    with pytest.raises(adapt.AdaptationError, match="Prepared shared helpers differ"):
        fresh(case, "project-b", library=alternate)


def test_prepared_helper_drift_invalidates_lineage_and_registration(case):
    ticket, _, runtime = prepared(case)
    (case.helpers / "helper.py").write_text("modified after preparing repair")
    with pytest.raises(ValueError, match="shared helpers changed"):
        adapt.projection(case.live, case.cfg)
    # Adoption itself remains the separate existing boundary. Registration
    # must independently recheck the actual helper bytes afterward.
    ki_guard.activate(case.live, runtime, ticket["runtime_report"], quiescent=True)
    with pytest.raises(ValueError, match="shared helpers changed"):
        adapt.register(ticket, case.live, case.cfg)


@pytest.mark.parametrize("stage", ["projection", "registry"])
def test_failed_registration_does_not_publish_reuse(case, monkeypatch, stage):
    ticket, _, runtime = prepared(case)
    ki_guard.activate(case.live, runtime, ticket["runtime_report"], quiescent=True)
    original = adapt._write
    def fail(path, doc):
        if (stage == "projection" and "projections" in Path(path).parts
                or stage == "registry" and "registry" in Path(path).parts):
            raise OSError("injected publication failure")
        return original(path, doc)
    with monkeypatch.context() as patched:
        patched.setattr(adapt, "_write", fail)
        with pytest.raises(OSError, match="publication failure"):
            adapt.register(ticket, case.live, case.cfg)
    second, _ = fresh(case, "project-b")
    assert "return 1" in (second / "reader.py").read_text()
    assert "return 2" in (case.live / "reader.py").read_text()


@pytest.mark.parametrize("text", [
    "path = 'KISSPATH_DATA/new-input.nc'\n",
    "url = 'https://example.org/data/input.nc'\n",
    "fraction = 7 / 2\n",
    "fraction = 7 /2\n",
    "pattern = r'foo/[0-9]+'\n",
    "path = f'{output}/new-file.txt'\n",
])
def test_portable_paths_urls_and_ordinary_code_remain_allowed(case, text):
    ticket, _, _ = prepared(case, extra=text)
    assert ticket["kind"] == "prepared_registration"


@pytest.mark.parametrize("change", ["dependency", "platform", "remove"])
def test_reusable_repair_cannot_change_effective_install_requirements(case, change):
    origin = adapt.projection(case.live, case.cfg)
    portable = case.base / "recipe-candidate"
    ki_copy.copytree(Path(origin["portable_root"]), portable)
    manifest = portable / "kiss.yaml"
    if change == "dependency":
        manifest.write_text(manifest.read_text() + "python_deps: ['missing-package']\n")
    elif change == "platform":
        (portable / f"kiss.{adapt.installation_platform()}.yaml").write_text(
            "kiss_manifest_version: 1\nmodel: Demo\npython_deps: ['new-package']\n")
    else:
        manifest.unlink()
    runtime = case.base / "runtime-candidate"
    port.materialise(portable, runtime, case.cfg)
    with pytest.raises(adapt.AdaptationError, match="effective installation recipe"):
        adapt.prepare_registration(case.live, case.cfg, portable, accepted(portable), runtime, accepted(runtime))


def test_explicit_helper_argument_cannot_override_saved_runtime(case):
    with pytest.raises(adapt.AdaptationError, match="saved shared-helper binding"):
        adapt.materialise(case.source, case.base / "new-projection", case.cfg,
                          library_root=case.library, helper_root=case.library / "ki_tools_common")


def test_runtime_change_during_projection_cannot_receive_provenance(case, monkeypatch):
    target = case.base / "race-projection"
    original = port.materialise
    def change(*args, **kwargs):
        result = original(*args, **kwargs)
        case.cfg.python = "changed-after-projection"
        return result
    monkeypatch.setattr(port, "materialise", change)
    with pytest.raises(adapt.AdaptationError, match="context changed"):
        adapt.materialise(case.source, target, case.cfg, library_root=case.library)
    assert not ki_guard.is_managed(target)
    assert not adapt._location(target).exists()


def test_source_change_before_provenance_cannot_receive_enrollment(case, monkeypatch):
    target = case.base / "race-projection"
    original = adapt._remember
    def change(source):
        (source / "reader.py").write_text("changed_after_projection = True\n")
        return original(source)
    monkeypatch.setattr(adapt, "_remember", change)
    with pytest.raises(adapt.AdaptationError, match="Portable source changed"):
        adapt.materialise(case.source, target, case.cfg, library_root=case.library)
    assert not ki_guard.is_managed(target)
    assert not adapt._location(target).exists()


@pytest.mark.parametrize("name", ["case.nml", "case.inp", "case.txt", "test_cases/demo/case.nml", "test_cases/demo/case.prj"])
def test_scientific_input_files_cannot_capture_a_project_binding(case, name):
    origin = adapt.projection(case.live, case.cfg)
    portable = case.base / "input-candidate"
    ki_copy.copytree(Path(origin["portable_root"]), portable)
    config = portable / name
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("outputs = '" + case.cfg.roles["outputs"].as_posix() + "/result'\n")
    runtime = case.base / "runtime-candidate"
    port.materialise(portable, runtime, case.cfg)
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        adapt.prepare_registration(case.live, case.cfg, portable, accepted(portable), runtime, accepted(runtime))


@pytest.mark.parametrize("name,text", [("settings.xml", "<x>1</x>"),
    ("README.md", "<div>Portable instructions</div>"),
    ("settings.xml", "<x>KISSPATH_DATA/input.dat</x>")])
def test_closing_markup_is_not_an_absolute_path(case, name, text):
    base = case.base / "markup-base"
    candidate = case.base / "markup-candidate"
    base.mkdir()
    candidate.mkdir()
    (candidate / name).write_text(text)
    adapt._portable_changes(base, candidate, case.cfg)


def test_absolute_xml_values_remain_rejected(case):
    base = case.base / "xml-base"
    candidate = case.base / "xml-candidate"
    base.mkdir()
    candidate.mkdir()
    (candidate / "settings.xml").write_text("<path>/home/private/input.dat</path>")
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        adapt._portable_changes(base, candidate, case.cfg)


@pytest.mark.parametrize("encoding", ["latin-1", "utf-16", "utf-16-le", "utf-32"])
def test_non_utf8_input_paths_are_checked_without_reencoding(case, encoding):
    base = case.base / "encoded-base"
    candidate = case.base / "encoded-candidate"
    base.mkdir()
    candidate.mkdir()
    blob = "temperature_units = '°C'\ninput = 'D:/old-project/input.dat'\n".encode(encoding)
    target = candidate / "case.nml"
    target.write_bytes(blob)
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        adapt._portable_changes(base, candidate, case.cfg)
    assert target.read_bytes() == blob
