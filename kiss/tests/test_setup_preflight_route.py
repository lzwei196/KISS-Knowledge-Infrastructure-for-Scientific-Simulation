"""Known direct preflight launches must use the host's isolated runner."""
import sys

import pytest

from kiss_cli import api, ki_guard, paths
from kiss_cli.catalog import KI


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_KI_GUARD_HOME", str(tmp_path / "guard"))
    monkeypatch.setattr(ki_guard, "_legacy_installation_roots", lambda: [])
    root = tmp_path / "work"
    ki_root = root / "ki"
    ki_root.mkdir(parents=True)
    (ki_root / "preflight_check.py").write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('unexpected-output.txt').write_text('ran')\n",
        encoding="utf-8",
    )
    (root / "probe.py").write_text("print('workspace probe')\n", encoding="utf-8")
    ki_guard.enroll(ki_root)
    cfg = paths.KissConfig.default(root)
    cfg.python = sys.executable
    return root, KI("M", ki_root), cfg


@pytest.mark.parametrize("spelling", ["relative", "absolute", "normalized", "module"])
def test_direct_preflight_rejected_before_launch(workspace, spelling):
    root, ki, cfg = workspace
    script = {
        "relative": "ki/preflight_check.py",
        "absolute": str(ki.root / "preflight_check.py"),
        "normalized": "ki/../ki/preflight_check.py",
    }
    args = ({"argv": [cfg.python, "-m", "preflight_check"], "cwd": "ki"}
            if spelling == "module" else
            {"argv": [cfg.python, script[spelling]]})
    with pytest.raises(api.ToolError, match="run_preflight"):
        api.execute_tool("run_setup_command", args, ki, cfg, setup_mode=True)
    assert not (ki.root / "unexpected-output.txt").exists()
    ki_guard.require_intact(ki.root)


def test_commands_cannot_use_protected_ki_as_output_directory(workspace):
    root, ki, cfg = workspace
    with pytest.raises(api.ToolError, match="protected KI"):
        api.execute_tool("run_setup_command", {
            "argv": [cfg.python, str(root / "probe.py")], "cwd": "ki",
        }, ki, cfg, setup_mode=True)


def test_workspace_probe_still_runs(workspace):
    root, ki, cfg = workspace
    result = api.execute_tool("run_setup_command", {
        "argv": [cfg.python, str(root / "probe.py")],
    }, ki, cfg, setup_mode=True)
    assert "exit_code=0" in result
    assert "workspace probe" in result
    ki_guard.require_intact(ki.root)


def test_preflight_source_remains_readable(workspace):
    _, ki, cfg = workspace
    result = api.execute_tool("read_ki_file", {
        "path": "preflight_check.py",
    }, ki, cfg, setup_mode=True)
    assert "unexpected-output.txt" in result


def test_locked_workspace_file_is_a_recoverable_tool_error(workspace, monkeypatch):
    root, ki, cfg = workspace
    locked = root / "locked.lease"
    locked.write_text("owner", encoding="utf-8")
    original = type(locked).read_text

    def read(path, *args, **kwargs):
        if path == locked:
            raise PermissionError(13, "Permission denied", str(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(type(locked), "read_text", read)
    with pytest.raises(api.ToolError, match="Cannot read locked.lease"):
        api.execute_tool("read_work_file", {"path": "locked.lease"},
                         ki, cfg, setup_mode=True)
    # A failed optional inspection must not prevent the agent's next read.
    assert "workspace probe" in api.execute_tool(
        "read_work_file", {"path": "probe.py"}, ki, cfg, setup_mode=True)
