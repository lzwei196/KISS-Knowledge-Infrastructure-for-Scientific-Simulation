"""Real stdlib venv probes for explicitly declared first-party data readers."""
from pathlib import Path
import json
import shutil
from types import SimpleNamespace
import venv

import pytest

from kiss_cli import cli, install, ki_guard, paths, port, python_script, runnable
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest

SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    root = tmp_path_factory.mktemp("data-reader-runtime")
    environment = root/"python"
    venv.EnvBuilder(with_pip=False).create(environment)
    executable = environment/("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python")
    return root, executable


@pytest.fixture
def package(tmp_path, workspace):
    root, python = workspace
    def prepare(name):
        target = root/tmp_path.name/name
        shutil.copytree(SOURCE/"data_kis"/name, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        ki = KI(name, target)
        assert ki.meta["impl_id"] == python_script.DATA_READERS[name][0]
        assert ki.meta["package_role"] == "data_reader"
        cfg = SimpleNamespace(root=root, python=str(python), roles={}, ki_path=target)
        return ki, Manifest.load(target/"kiss.yaml"), cfg
    return prepare


@pytest.mark.parametrize("name", list(python_script.DATA_READERS))
def test_real_source_bound_help_and_stdlib_imports(package, name):
    ki, manifest, cfg = package(name)
    verdict = runnable.check(ki, manifest, cfg, timeout=10)
    assert verdict.usable, verdict.as_dict()
    assert verdict.installation_scope == "data-reader"
    assert verdict.kind == "data reader (Python)" and verdict.official_upstream_verified is None
    assert verdict.binary.endswith("read_observations.py") and not verdict.probe_created_paths
    assert "no model was executed" in verdict.detail
    assert "csv" in runnable.declared_imports(ki)
    if name == "HYDAT_Observations":
        assert "sqlite3" in runnable.declared_imports(ki)
    step, path = install.acquire(manifest, cfg.root/"unused-prefix", cfg.python, ki=ki)
    assert step.ok and path == ki.root/"tools/read_observations.py"
    assert install.needs_shared_tools(ki, manifest) is False


def test_changed_source_and_wrong_identity_fail(package):
    ki, manifest, cfg = package("HYDAT_Observations")
    tool = ki.root/"tools/read_observations.py"
    tool.write_bytes(tool.read_bytes()+b"\n# changed after manifest pin\n")
    assert install.needs_shared_tools(ki, manifest) is True
    assert not runnable.check(ki, manifest, cfg, timeout=10).usable
    with pytest.raises(ValueError, match="SHA256"):
        python_script.resolve(ki, manifest.python_script)
    ki.__dict__["meta"] = {"impl_id": "another-reader"}
    with pytest.raises(ValueError, match="metadata"):
        python_script.resolve(ki, manifest.python_script)


def test_unknown_reader_cannot_gain_arbitrary_script_admission(package):
    ki, manifest, _ = package("HYDAT_Observations")
    ki.name = "Unregistered_Data_Reader"
    assert install.needs_shared_tools(ki, manifest) is True
    with pytest.raises(ValueError, match="Unrecognized"):
        python_script.resolve(ki, manifest.python_script)


def test_only_valid_bundled_stdlib_reader_skips_shared_tools(package):
    ki, manifest, _ = package("HYDAT_Observations")
    manifest.python_deps = ["numpy"]
    assert install.needs_shared_tools(ki, manifest) is True
    manifest.python_deps = []
    manifest.acquire.strategy = "download"
    assert install.needs_shared_tools(ki, manifest) is True
    manifest.acquire.strategy = "bundled"
    manifest.python_script = None
    assert install.needs_shared_tools(ki, manifest) is True
    model = SimpleNamespace(name="VIC")
    assert install.needs_shared_tools(model, Manifest(model="VIC")) is True


@pytest.mark.parametrize("name", list(python_script.DATA_READERS))
def test_materialised_reader_retains_exact_source_and_can_complete_setup(tmp_path, workspace, name):
    root, executable = workspace
    cfg = paths.KissConfig.default(root)
    cfg.python = str(executable)
    source = SOURCE/"data_kis"/name
    manifest = Manifest.load(source/"kiss.yaml")
    live = root/tmp_path.name/"materialised"/name
    report = port.materialise(source, live, cfg)
    assert not report.unresolved and not report.corrupted and report.tokens_replaced == 0
    assert (source/"tools/read_observations.py").read_bytes() == (live/"tools/read_observations.py").read_bytes()
    ki = KI(name, live)
    ki_guard.enroll(live)
    assert install.needs_shared_tools(ki, manifest) is False
    step, runner = install.acquire(manifest, root/"unused-prefix", cfg.python, ki=ki)
    assert step.ok and runner == live/"tools/read_observations.py"
    step = install.run_preflight(ki, cfg.python, cfg)
    assert step.ok, step.detail
    verdict = runnable.check(ki, manifest, cfg, timeout=10)
    assert verdict.usable, verdict.as_dict()


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_materialisation_without_replacements_preserves_raw_newlines(tmp_path, newline):
    source = tmp_path/"source"
    source.mkdir()
    original = newline.join([b"# unchanged source", b"print('hello')", b""])
    (source/"reader.py").write_bytes(original)
    destination = tmp_path/"materialised"
    report = port.materialise(source, destination, paths.KissConfig.default(tmp_path))
    assert report.tokens_replaced == 0 and not report.corrupted
    assert (destination/"reader.py").read_bytes() == original


@pytest.mark.parametrize("name", list(python_script.DATA_READERS))
def test_cli_verify_checks_installed_copy_and_rejects_installed_source_drift(tmp_path, capsys, name):
    workroot = tmp_path/"installs"
    root = workroot/name.lower()
    cfg = paths.KissConfig.default(root)
    environment = root/"venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    cfg.python = str(environment/("Scripts/python.exe" if __import__("os").name == "nt" else "bin/python"))
    (root/paths.CONFIG_NAME).write_text(cfg.dumps(),encoding="utf-8")
    source = SOURCE/"data_kis"/name
    port.materialise(source,root/"ki",cfg)
    args = SimpleNamespace(models=SOURCE/"data_kis",model=name,workdir=str(workroot),
                           python=None,timeout=10,json=True)
    assert cli.cmd_verify(args) == 0
    verdict = json.loads(capsys.readouterr().out)[0]
    runner = root/"ki/tools/read_observations.py"
    assert Path(verdict["binary"]) == runner
    assert verdict["installation_scope"] == "data-reader"
    runner.write_bytes(runner.read_bytes()+b"\n# installed source drift\n")
    assert cli.cmd_verify(args) == 1
    failed = json.loads(capsys.readouterr().out)[0]
    assert "KI integrity gate" in failed["detail"] and "Active KI changed" in failed["detail"]
    assert failed["state"] == "blocked"
    assert failed["responds"] is False
