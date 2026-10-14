"""DSSAT retains ordinary portable-role behavior through the shared fresh wrapper.

The preflight fixture is copied from published snapshot e3ed93f067f2f2693294d0ff5d1f98ad.
These are static projection tests; they do not run DSSAT or certify its installation.
"""
import ast
import hashlib
from pathlib import Path

import pytest

from kiss_cli import ki_adaptations, paths, port, project_verification
from kiss_cli.catalog import KI


FIXTURE = Path(__file__).parent / "fixtures/dssat_preflight_published.py"
MANIFEST = """package:
  name: DSSAT
  language: fortran
  implementation:
    id: dssat-csm-485
    version: 4.8.5 Build 41
  binary:
    path: KISSPATH_HOME/DSSAT/build/bin/dscsm048
    type: null
"""


def files(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in Path(root).rglob("*") if path.is_file()}


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_real_dssat_preflight_uses_selected_python_without_wofost_normalization(tmp_path, newline):
    source = tmp_path / "library/models/DSSAT"
    source.mkdir(parents=True)
    original = FIXTURE.read_bytes()
    preflight = original.decode("utf-8").replace("\r\n", "\n").replace("\n", newline).encode("utf-8")
    (source / "preflight_check.py").write_bytes(preflight)
    (source / "knowledge_infrastructure.yaml").write_bytes(MANIFEST.encode("utf-8"))
    (source / "SKILL.md").write_text("# DSSAT\nUse the published preflight and native DSSAT tools.\n", encoding="utf-8")
    reference_case = source / "test_cases/reference/input.txt"
    reference_case.parent.mkdir(parents=True)
    reference_case.write_bytes(b"reference input, preserve KISSPATH_HOME verbatim\n")
    before = files(source)

    project = tmp_path / "project spaces \u4e2d\u6587"
    cfg = paths.KissConfig.default(project)
    cfg.python = str(tmp_path / "retained software/Python312/Scripts/python.exe")
    cfg.relocation = "none"
    cfg.roles["home"] = tmp_path / "retained software/home"
    cfg.roles["ki_root"] = project / "models"
    target = project / "models/DSSAT/ki"
    candidate = tmp_path / "sibling-staging/DSSAT"
    ordinary = tmp_path / "ordinary-copy"
    baseline = port.materialise(source, ordinary, cfg)
    assert not baseline.unresolved and not baseline.corrupted

    report, path_report = ki_adaptations.project_runtime(
        source, candidate, cfg, model="DSSAT", target_root=target
    )
    assert not report.unresolved and not report.corrupted
    assert path_report is None, "DSSAT must not receive a WOFOST-specific normalization proof"
    assert files(candidate) == files(ordinary)
    assert files(source) == before
    assert (candidate / "test_cases/reference/input.txt").read_bytes() == reference_case.read_bytes()
    assert not target.exists(), "staging may not create or replace the logical live KI"

    tree = ast.parse((candidate / "preflight_check.py").read_text(encoding="utf-8"))
    values = {node.targets[0].id: node.value for node in tree.body
              if isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)}
    expected = {
        "HYDROCRAFT_PYTHON": cfg.python,
        "DSSAT_BINARY": str(cfg.roles["home"] / "DSSAT/build/bin/dscsm048"),
        "DSSAT_DATA": str(cfg.roles["home"] / "DSSAT/Data"),
    }
    for name, wanted in expected.items():
        node = values[name]
        assert isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path"
        assert ast.literal_eval(node.args[0]) == wanted.replace("\\", "/")
    assert project_verification.status(project, KI("DSSAT", candidate))["can_run"] is False


def test_dssat_fixture_is_the_published_source():
    # Git may translate fixture newlines; the case above separately exercises
    # both physical encodings through the real materializer.
    assert hashlib.sha256(FIXTURE.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == "48f412f39b45f952b495b00833f1a3e7acb2428dbb7953e39fcea7889796c1b6"
