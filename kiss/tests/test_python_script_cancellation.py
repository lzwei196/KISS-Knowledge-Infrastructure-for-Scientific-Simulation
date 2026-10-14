"""The Python-script probe delegated by runnable shares the setup stop scope."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from kiss_cli import execution, install, python_script, runnable


@pytest.mark.parametrize("cancel_at", [1, 2])
def test_delegated_runtime_and_help_probes_obey_stop(tmp_path, monkeypatch, cancel_at):
    script = tmp_path / "ki/tools/read_observations.py"
    script.parent.mkdir(parents=True)
    script.write_text("print('usage: read_observations.py')\n", encoding="utf-8")
    ki = SimpleNamespace(name="HYDAT_Observations", root=script.parent.parent,
                         meta={"impl_id": "geoforge-hydat-daily-reader"})
    contract = {"implementation_id": ki.meta["impl_id"], "path": "tools/read_observations.py",
                "sha256": hashlib.sha256(script.read_bytes()).hexdigest()}
    turn = execution.begin_turn(tmp_path)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["project"] == tmp_path and kwargs["turn_id"] == turn
        if len(calls) == cancel_at:
            return execution.ProcessRun("stopped", None, detail="fixture Stop")
        return execution.ProcessRun("succeeded", 0,
                                     stdout=json.dumps([str(tmp_path / "venv"), "/base"]))

    monkeypatch.setattr(execution, "run_process", run)
    with runnable.cancellation_context(tmp_path, turn_id=turn):
        with pytest.raises(install.InstallStopped, match="fixture Stop"):
            python_script.check(runnable.Verdict(ki.name), ki, contract,
                                SimpleNamespace(root=tmp_path), "python")
    assert len(calls) == cancel_at
