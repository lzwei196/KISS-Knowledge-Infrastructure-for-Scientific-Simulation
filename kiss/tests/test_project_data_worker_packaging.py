"""Every desktop layout must retain the externally launched worker as source."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SOURCE = Path(__file__).resolve().parents[1]
SPECS = ("GeoForgeDesktopWindows.spec", "GeoForgeDesktop.spec", "KISS.spec")


def _worker_data_entry(spec: Path) -> tuple[Path, str]:
    """Inspect Analysis.datas without importing PyInstaller or collecting libraries."""
    tree = ast.parse(spec.read_text(encoding="utf-8"), filename=str(spec))
    assignments = {
        target.id: node.value
        for node in tree.body if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    analysis = assignments["a"]
    assert isinstance(analysis, ast.Call) and analysis.func.id == "Analysis"
    datas = next(k.value for k in analysis.keywords if k.arg == "datas")
    if isinstance(datas, ast.Name):
        datas = assignments[datas.id]
    assert isinstance(datas, ast.List)
    entries = [
        entry for entry in datas.elts
        if isinstance(entry, ast.Tuple) and any(
            isinstance(node, ast.Constant) and node.value == "_project_data_worker.py"
            for node in ast.walk(entry)
        )
    ]
    assert len(entries) == 1, "Analysis.datas must include the standalone worker once"
    entry = eval(compile(ast.Expression(entries[0]), str(spec), "eval"),
                 {"__builtins__": {}, "str": str, "SOURCE": SOURCE})
    return Path(entry[0]), entry[1]


@pytest.mark.parametrize("spec_name", SPECS)
def test_frozen_layout_contains_resolved_standalone_worker(spec_name, tmp_path):
    source, destination = _worker_data_entry(SOURCE / spec_name)
    bundle_root = tmp_path / "bundle"
    staged_worker = bundle_root / destination / source.name
    staged_worker.parent.mkdir(parents=True)
    shutil.copyfile(source, staged_worker)

    # Evaluate the actual runtime lookup against a frozen package __file__.
    tree = ast.parse((SOURCE / "kiss_cli" / "execution.py").read_text(encoding="utf-8"))
    lookup = next(
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "worker" for t in node.targets
        ) and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "with_name"
    )
    resolved = eval(compile(ast.Expression(lookup), "execution.py", "eval"),
                    {"__builtins__": {}, "Path": Path,
                     "__file__": str(bundle_root / "kiss_cli" / "execution.pyc")})
    assert resolved == staged_worker
    assert resolved.read_bytes() == source.read_bytes()

    # An external Python can execute that packaged source without the app's imports.
    project = tmp_path / "project"
    input_file = project / "inputs" / "sample.txt"
    input_file.parent.mkdir(parents=True)
    input_file.write_text("raw observation\n", encoding="utf-8")
    output_file = project / "outputs" / "reader-result.json"
    output_file.parent.mkdir()
    reader = project / "reader.py"
    reader.write_text(
        "import json, sys\nfrom pathlib import Path\n"
        "value = Path(sys.argv[1]).read_text(encoding='utf-8')\n"
        "Path(sys.argv[2]).write_text(json.dumps({'value': value}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    request = {"source": str(reader),
               "source_sha256": hashlib.sha256(reader.read_bytes()).hexdigest(),
               "arguments": [str(input_file), str(output_file)],
               "read_roots": [str(input_file)],
               "write_roots": [str(output_file.parent)], "project": str(project)}
    result = subprocess.run([sys.executable, "-I", "-S", str(resolved), str(reader), json.dumps(request)],
                            cwd=project, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(output_file.read_text(encoding="utf-8")) == {"value": "raw observation\n"}
    assert input_file.read_text(encoding="utf-8") == "raw observation\n"
