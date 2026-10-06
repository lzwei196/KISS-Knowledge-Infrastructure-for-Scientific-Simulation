"""Real stdlib worker probes for declared case data; no scientific model runs."""
import hashlib
import json
from pathlib import Path

import pytest

from kiss_cli import project_data_tools
from .test_project_data_tools import case, approve, run


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))


def setup(tmp_path, source, *, directory=False):
    c = case(tmp_path, source)
    root = c[1] / "models/M/ki/test_cases/example"
    raw = root / "inputs/nested/deck.prj"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"original deck\r\n1 2 3\r\n")
    meta = root / "expected.json"
    meta.write_text('{"expected": 3}', encoding="utf-8")
    declared = [raw.parent.parent if directory else raw, meta]
    c[4]["items"][0]["local_paths"] = [str(p) for p in declared]
    c[3]["steps"][0]["project_data_tool"]["arguments"] = []
    return c, root, raw, meta


def request(c):
    return project_data_tools.worker_request(c[1], Path(c[5]["tool"]), c[3]["steps"][0], c[4], [])


STAGE = '''import json,pathlib
root=pathlib.Path('models/M/ki/test_cases/example')
raw=root/'inputs/nested/deck.prj'
meta=json.loads((root/'expected.json').read_text())
out=pathlib.Path('outputs/cases/deck.prj');out.parent.mkdir(parents=True,exist_ok=True)
out.write_bytes(raw.read_bytes())
report=pathlib.Path('artifacts/stage.json');report.parent.mkdir(parents=True,exist_ok=True)
report.write_text(json.dumps({'copied':True,'expected':meta['expected']}))
'''


def test_explicit_case_files_stage_exact_bytes_with_granted_input_identity(tmp_path):
    c, root, raw, meta = setup(tmp_path, STAGE)
    before = {p: p.read_bytes() for p in (raw, meta)}
    grants = request(c)
    assert set(grants["read_roots"]) == {str(raw), str(meta)}
    assert grants["list_roots"] == [] and str(root) not in grants["read_roots"]
    approve(c)
    result = run(c)
    assert result.startswith("exit_code=0"), result
    assert all(p.read_bytes() == content for p, content in before.items())
    assert (c[1] / "outputs/cases/deck.prj").read_bytes() == before[raw]
    summary = json.loads(result.splitlines()[1].split("[RECEIPT] ", 1)[1])
    assert summary["validation"] == "passed", result
    receipt = json.loads(Path(summary["receipt"]).read_text(encoding="utf-8"))
    copied = next(check for check in receipt["validation"]["checks"] if check.get("scope") == "unchanged_input_copy")
    assert copied["sha256"] == hashlib.sha256(before[raw]).hexdigest()
    assert copied["bytes"] == len(before[raw])
    assert copied["source"] == raw.relative_to(c[1]).as_posix()
    assert receipt["model_executed"] is False
    assert {entry["path"] for entry in receipt["inputs"]} >= {p.relative_to(c[1]).as_posix() for p in before}


def test_declared_case_input_directory_grants_listing_and_exact_data_files(tmp_path):
    source = '''import json,pathlib
root=pathlib.Path('models/M/ki/test_cases/example/inputs')
files={p.relative_to(root).as_posix():p.read_text() for p in root.rglob('*') if p.is_file()}
out=pathlib.Path('outputs/listing.json');out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(files))
'''
    c, root, raw, meta = setup(tmp_path, source, directory=True)
    grants = request(c)
    assert grants["list_roots"] == [str(root / "inputs")]
    assert set(grants["read_roots"]) == {str(raw), str(meta)}
    approve(c)
    assert run(c).startswith("exit_code=0")
    assert list(json.loads((c[1] / "outputs/listing.json").read_text())) == ["nested/deck.prj"]


@pytest.mark.parametrize("relative", [
    "models/OTHER/ki/test_cases/example/inputs/raw.csv", "models/M/ki/tools/helper.py",
    "models/M/ki/test_cases/example/run_reference.py", "models/M/ki/test_cases/example/inputs/helper.py",
    "models/M/ki/test_cases", "models/M/ki/test_cases/example", "models/M/ki",
])
def test_case_grants_reject_sibling_ki_code_and_broad_directories(tmp_path, relative):
    c, root, _raw, _meta = setup(tmp_path, STAGE)
    target = c[1] / relative
    if target.suffix:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture", encoding="utf-8")
    c[4]["items"][0]["local_paths"] = [str(target)]
    with pytest.raises(ValueError):
        request(c)


def test_declared_directory_with_code_is_rejected(tmp_path):
    c, root, _raw, _meta = setup(tmp_path, STAGE, directory=True)
    (root / "inputs/runner.py").write_text("raise RuntimeError('must never execute')")
    with pytest.raises(ValueError, match="executable code"):
        request(c)


@pytest.mark.parametrize("operation", [
    "raw.write_text('changed')", "list(raw.parent.iterdir())",
    "(raw.parent/'undeclared.csv').read_text()",
    "exec(compile(raw.read_text(), str(raw), 'exec'))",
])
def test_worker_keeps_raw_immutable_and_requires_explicit_listing_reads_and_no_code(tmp_path, operation):
    source = "from pathlib import Path\nraw=Path('models/M/ki/test_cases/example/inputs/nested/deck.prj')\n" + operation
    c, _root, raw, _meta = setup(tmp_path, source)
    if operation.startswith("exec"):
        raw.write_text("raise RuntimeError('KI code executed')", encoding="utf-8")
    (raw.parent / "undeclared.csv").write_text("secret fixture", encoding="utf-8")
    before = raw.read_bytes()
    approve(c)
    result = run(c)
    assert result.startswith("exit_code=1") and "PermissionError" in result, result
    assert raw.read_bytes() == before


@pytest.mark.parametrize("link_kind", ["file", "directory", "hardlink"])
def test_reference_case_aliases_cannot_escape_the_selected_tree(tmp_path, link_kind):
    c, root, raw, _meta = setup(tmp_path, STAGE, directory=link_kind == "directory")
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "raw.csv"
    target.write_text("outside", encoding="utf-8")
    link = root / "inputs/alias"
    try:
        if link_kind == "hardlink":
            link.hardlink_to(target)
        else:
            link.symlink_to(outside if link_kind == "directory" else target,
                            target_is_directory=link_kind == "directory")
    except OSError:
        pytest.skip("host cannot create this filesystem alias")
    if link_kind != "directory":
        c[4]["items"][0]["local_paths"] = [str(link)]
    with pytest.raises(ValueError):
        request(c)


@pytest.mark.parametrize("mode", ["changed", "ungranted", "external", "new_png"])
def test_unsupported_outputs_need_exact_copy_of_an_explicitly_granted_input(tmp_path, mode):
    c, _root, raw, _meta = setup(tmp_path, STAGE)
    out = c[1] / ("outputs/new.png" if mode == "new_png" else "outputs/copy.prj")
    out.parent.mkdir()
    out.write_bytes(raw.read_bytes() if mode != "changed" else raw.read_bytes() + b"changed")
    grants = [str(raw)] if mode == "changed" else []
    if mode == "external":
        external = tmp_path / "outside.prj"
        external.write_bytes(raw.read_bytes())
        grants = [str(external)]
    result = project_data_tools.validate_outputs(c[1], [out], 0, input_files=grants)
    assert result["status"] == "failed"
    assert not any(check.get("scope") == "unchanged_input_copy" for check in result["checks"])
