"""The frozen Windows build ships the exact Linux source the sidecar sends to WSL."""
from __future__ import annotations

import ast
from pathlib import Path
import shutil

import pytest

from kiss_cli import linux_sidecar, runtime_backend


SOURCE = Path(__file__).resolve().parents[1]
REPO = SOURCE.parent


def _portable_linux_datas():
    spec = SOURCE / "GeoForgeDesktopWindows.spec"
    tree = ast.parse(spec.read_text(encoding="utf-8"), filename=str(spec))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "portable_linux_datas")
    namespace = {"Path": Path}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(spec), "exec"), namespace)
    analysis = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "a" for t in node.targets))
    datas = next(k.value for k in analysis.keywords if k.arg == "datas")
    assert any(isinstance(item, ast.Starred) and isinstance(item.value, ast.Call)
               and getattr(item.value.func, "id", None) == "portable_linux_datas"
               for item in datas.elts), "Analysis.datas must include the portable Linux source"
    return namespace["portable_linux_datas"]


def _models(tmp_path):
    models = tmp_path / "library" / "models"
    (models / "Sample").mkdir(parents=True)
    (models / "Sample" / "SKILL.md").write_bytes(b"# Sample KI\n")
    return models


def test_source_root_is_the_checkout_when_not_frozen(monkeypatch):
    monkeypatch.delattr(runtime_backend.sys, "frozen", raising=False)
    root = runtime_backend.application_source_root()
    assert root == REPO
    assert (root / "kiss" / "kiss_cli" / "_wsl_worker.py").is_file()


def test_frozen_source_root_is_the_bundled_linux_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_backend.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_backend.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert runtime_backend.application_source_root() == tmp_path.resolve() / "linux-runtime"
    monkeypatch.delattr(runtime_backend.sys, "_MEIPASS")
    with pytest.raises(runtime_backend.RuntimeBackendError):
        runtime_backend.application_source_root()


def test_bundled_payload_matches_the_sidecar_source_inventory(tmp_path):
    rows = _portable_linux_datas()(REPO)
    bundle = tmp_path / "bundle"
    for source, destination in rows:
        assert not Path(source).name.endswith((".pyc", ".pyo", ".key", ".pem"))
        assert "__pycache__" not in Path(source).parts
        target = bundle / destination / Path(source).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    payload = bundle / "linux-runtime"
    for name in ("runtime_backend.py", "_wsl_worker.py", "linux_sidecar.py"):
        assert (payload / "kiss" / "kiss_cli" / name).is_file()

    models = _models(tmp_path)
    checkout = linux_sidecar.source_inventory(REPO, models)
    frozen = linux_sidecar.source_inventory(payload, models)
    # Same files, bytes and digests: a frozen build sends WSL what a source build sends.
    assert frozen[1] == checkout[1]
    assert frozen[0] == checkout[0]
