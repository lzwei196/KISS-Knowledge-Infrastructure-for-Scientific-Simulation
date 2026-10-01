"""CRHM's official example must be staged by its actual execution tool."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[2] / "models/CRHM/tools/s5_execution/run_crhm.py"
    spec = importlib.util.spec_from_file_location("crhm_run_staging", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def example(tmp_path):
    source = tmp_path / "upstream"
    source.mkdir()
    obs = source / "Badlake73_76.obs"
    obs.write_bytes(b"authentic station forcing\r\nt 1 (\xbaC)\r\n1973 1 1 1 0 -10\r\n")
    prj = source / "badlake.prj"
    content = (b"Description \xba\r\nDimensions:\r\n######\r\nnhru 3\r\n"
               b"######\r\nObservations:\r\n######\r\n"
               b"C:\\Users\\author\\crhmcode\\obs\\Badlake73_76.obs\r\n"
               b"######\r\nDates:\r\n######\r\n1973 1 1\r\n1974 1 1\r\n"
               b"######\r\nParameters:\r\nShared hru_area <1E-06 to 1E+09>\r\n"
               b"3.58 6.13 1.68\r\n######\r\nDisplay_Variable:\r\npbsm SWE 1 2 3\r\n")
    prj.write_bytes(content)
    return SimpleNamespace(source=source, obs=obs, prj=prj, content=content, run=tmp_path / "outputs/badlake")


def test_staging_changes_only_observation_path_bytes(runner, example):
    e = example
    staged = runner.stage_inputs(e.prj, e.run, e.source)
    staged_obs = e.run / "obs" / e.obs.name
    old_line = b"C:\\Users\\author\\crhmcode\\obs\\Badlake73_76.obs"
    assert staged.read_bytes() == e.content.replace(old_line, str(staged_obs).encode())
    assert staged_obs.read_bytes() == e.obs.read_bytes()
    assert e.prj.read_bytes() == e.content
    assert runner.read_prj_obs_paths(staged) == [str(staged_obs)]


def test_relative_observation_path_resolves_from_original_project(runner, example):
    e = example
    e.prj.write_bytes(e.content.replace(b"C:\\Users\\author\\crhmcode\\obs\\Badlake73_76.obs",
                                      b"Badlake73_76.obs"))
    runner.stage_inputs(e.prj, e.run)
    assert (e.run / "obs" / e.obs.name).read_bytes() == e.obs.read_bytes()


def test_missing_genuine_observation_does_not_write_partial_stage(runner, example):
    e = example
    e.prj.write_bytes(e.content.replace(b"Badlake73_76.obs\r\n######\r\nDates:",
                                      b"Badlake73_76.obs\r\nmissing.obs\r\n######\r\nDates:"))
    with pytest.raises(ValueError, match="Observation file not found"):
        runner.stage_inputs(e.prj, e.run, e.source)
    assert not e.run.exists()


def test_staging_refuses_to_modify_original_project(runner, example):
    with pytest.raises(ValueError, match="original project"):
        runner.stage_inputs(example.prj, example.source, example.source)
    assert example.prj.read_bytes() == example.content


@pytest.mark.parametrize("linked_destination", ["project", "observation"])
def test_staging_rejects_hardlinks_before_modifying_original_inputs(runner, example, linked_destination):
    e = example
    (e.run / "obs").mkdir(parents=True)
    if linked_destination == "project":
        original, destination = e.prj, e.run / e.prj.name
    else:
        # This could link a different upstream input from an earlier run. A
        # samefile check against the newly selected source is insufficient.
        original, destination = e.source / "other.obs", e.run / "obs" / e.obs.name
        original.write_bytes(b"original observation to preserve\r\n")
    original_bytes = original.read_bytes()
    os.link(original, destination)
    with pytest.raises(ValueError, match="hard link"):
        runner.stage_inputs(e.prj, e.run, e.source)
    assert original.read_bytes() == original_bytes
    assert e.prj.read_bytes() == e.content


def test_run_uses_staged_paths_and_contains_model_logs(runner, example, monkeypatch):
    e = example
    output = e.run / "output.txt"
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        assert Path(command[-1]) == e.run / "badlake.prj"
        assert command[command.index("-o") + 1] == str(output)
        assert "--obs_file_directory" not in command
        assert Path(kwargs["cwd"]) == e.run
        (Path(kwargs["cwd"]) / "crhmRun.log").write_text("model log")
        output.write_text("date\tSWE(1)\n()\t(mm)\n1973-01-01T01:00\t1.25\n")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", run)
    runner.process("crhm.exe", e.prj, output, e.source, 100, "ISO", e.run)
    runner.validate_outputs(output)
    assert len(calls) == 1
    assert (e.run / "crhmRun.log").is_file()
    assert e.prj.read_bytes() == e.content


def test_staging_refuses_output_outside_run_directory(runner, example, monkeypatch):
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **k: pytest.fail("must not launch"))
    with pytest.raises(ValueError):
        runner.process("crhm.exe", example.prj, example.source / "output.txt",
                       example.source, 100, "ISO", example.run)
    assert not example.run.exists()


@pytest.mark.parametrize("ambient_tz", [None, "CST-8", "PST8PDT"])
def test_model_civil_time_is_independent_of_host_timezone(runner, example, monkeypatch, ambient_tz):
    if ambient_tz is None:
        monkeypatch.delenv("TZ", raising=False)
    else:
        monkeypatch.setenv("TZ", ambient_tz)
    monkeypatch.setenv("CRHM_TEST_PRESERVE", "unchanged")
    before = dict(os.environ)

    def run(command, **kwargs):
        assert kwargs["env"] is not os.environ
        assert kwargs["env"] == {**before, "TZ": "UTC0"}
        assert dict(os.environ) == before
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(runner.subprocess, "run", run)
    runner.process("crhm.exe", example.prj, example.run / "raw.txt",
                   example.source, 100, "ISO", example.run)
    assert dict(os.environ) == before


def test_success_exit_cannot_reuse_untouched_old_output(runner, example, monkeypatch):
    e = example
    e.run.mkdir(parents=True)
    output = e.run / "output.txt"
    output.write_text("date\tSWE(1)\n()\t(mm)\n1973-01-01T01:00\t1.25\n")
    monkeypatch.setattr(runner.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    with pytest.raises(SystemExit) as exc:
        runner.process("crhm.exe", e.prj, output, e.source, 100, "ISO", e.run)
    assert exc.value.code == 3


@pytest.mark.parametrize("content", ["", "date\tSWE(1)\n()\t(mm)\n",
                                     "date\tSWE(1)\n()\t(mm)\n1973-01-01T01:00\tnan\n"])
def test_empty_or_header_only_output_never_passes(runner, tmp_path, content):
    output = tmp_path / "output.txt"
    output.write_text(content)
    with pytest.raises(SystemExit) as exc:
        runner.validate_outputs(output)
    assert exc.value.code == 3
