"""Frozen preflight keeps the exact runtime-data policy used by source receipts."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import shutil
from types import ModuleType, SimpleNamespace

import pytest

from kiss_cli import runtime_data


SOURCE = Path(__file__).resolve().parents[1]


def _data_entry(spec: Path):
    tree = ast.parse(spec.read_text(encoding="utf-8"), filename=str(spec))
    assignments = {target.id: node.value for node in tree.body if isinstance(node, ast.Assign)
                   for target in node.targets if isinstance(target, ast.Name)}
    analysis = assignments["a"]
    datas = next(k.value for k in analysis.keywords if k.arg == "datas")
    if isinstance(datas, ast.Name):
        datas = assignments[datas.id]
    entries = [entry for entry in datas.elts if isinstance(entry, ast.Tuple) and any(
        isinstance(node, ast.Constant) and node.value == "runtime_data.py" for node in ast.walk(entry))]
    assert len(entries) == 1, "Frozen Analysis.datas must include runtime_data.py exactly once"
    value = eval(compile(ast.Expression(entries[0]), str(spec), "eval"),
                 {"__builtins__": {}, "str": str, "SOURCE": SOURCE})
    return Path(value[0]), value[1]


@pytest.mark.parametrize("spec_name", ["GeoForgeDesktopWindows.spec", "GeoForgeDesktop.spec", "KISS.spec"])
def test_frozen_runtime_data_checks_match_source_policy_and_keep_conflicts_blocked(spec_name, tmp_path):
    source, destination = _data_entry(SOURCE / spec_name)
    target = tmp_path / "frozen" / destination / "runtime_data.py"
    payload = b"reference table\nA 1 2\n"
    data = tmp_path / "runtime" / "Model/Data/TABLE.CDE"
    data.parent.mkdir(parents=True)
    data.write_bytes(payload)
    manifest = SimpleNamespace(runtime_data={
        "version": 1, "source": {"repo": "https://example.invalid/model.git", "commit": "a" * 40},
        "target": {"role": "home", "path": "Model/Data"},
        "files": [{"source": "Data/TABLE.CDE", "path": "TABLE.CDE",
                   "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}]})
    cfg = SimpleNamespace(roles={"home": tmp_path / "runtime"})
    expected = runtime_data.inspect(manifest, cfg)
    assert expected["ok"]

    # PYZ modules execute with a __file__ spelling even when no source was copied.
    module = ModuleType("frozen_runtime_data")
    module.__file__ = str(target)
    exec(compile(source.read_bytes(), str(target), "exec"), module.__dict__)
    with pytest.raises(FileNotFoundError):
        module.inspect(manifest, cfg)

    target.parent.mkdir(parents=True)
    shutil.copyfile(source, target)
    assert module.inspect(manifest, cfg) == expected
    assert expected["policy_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()

    data.write_bytes(b"changed scientific support table")
    failed = module.inspect(manifest, cfg)
    assert failed["ok"] is False and failed["files"][0]["state"] == "conflict"
    assert failed["policy_sha256"] == expected["policy_sha256"]
    assert data.read_bytes() == b"changed scientific support table"
    target.write_bytes(target.read_bytes() + b"\n# changed policy source\n")
    assert module.inspect(manifest, cfg)["policy_sha256"] != expected["policy_sha256"]
