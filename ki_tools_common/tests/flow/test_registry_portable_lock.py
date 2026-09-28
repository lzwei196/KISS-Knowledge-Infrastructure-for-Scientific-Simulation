"""Real inter-process registry locking, including Windows byte-range locks."""
import json
import os
from pathlib import Path
import subprocess
import sys

from ki_tools_common.flow import receipts


def test_concurrent_registry_writers_preserve_each_others_updates(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    registry = tmp_path / "registry"
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(registry))
    script = (
        "from pathlib import Path; import sys,time\n"
        "from ki_tools_common.flow.receipts import _update_registry\n"
        "def update(doc):\n"
        " time.sleep(.02)\n"
        " doc['count'] = doc.get('count', 0) + 1\n"
        " return doc\n"
        "for i in range(5): _update_registry(Path(sys.argv[1]), update)\n"
    )
    env = dict(os.environ)
    package_root = str(Path(receipts.__file__).resolve().parents[2])
    env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
    children = [subprocess.Popen([sys.executable, "-c", script, str(project)],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for _ in range(4)]
    try:
        for child in children:
            stdout, stderr = child.communicate(timeout=30)
            assert child.returncode == 0, (stdout, stderr)
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
    document = json.loads(receipts.registry_entry(project).read_text(encoding="utf-8"))
    assert document["count"] == 20
    assert document["ws"] == str(project.resolve())
