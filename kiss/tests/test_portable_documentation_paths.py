"""Machine-path guard regression for canonical generated KI documentation.

The registration test uses the existing explicitly synthetic KDT receipt
fixture. This does not execute a model or certify scientific validation.
"""
from pathlib import Path
import sys

import pytest

from kiss_cli import ki_adaptations as adapt, ki_copy, paths, port
from .test_ki_adaptations import accepted, case


ROW = "| `tools/run_reference_case.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_reference_case.py --help` |\n"


@pytest.fixture
def trees(tmp_path):
    base, candidate = tmp_path / "base", tmp_path / "candidate"
    base.mkdir()
    candidate.mkdir()
    cfg = paths.KissConfig.default(tmp_path / "runtime")
    cfg.python = sys.executable
    return base, candidate, cfg


def check(trees, text, *, name="SKILL.md", previous=""):
    base, candidate, cfg = trees
    (base / name).write_text(previous, encoding="utf-8")
    (candidate / name).write_text(text, encoding="utf-8")
    adapt._portable_changes(base, candidate, cfg)


def test_exact_rejected_generated_row_is_portable(trees):
    # The live rejection was exactly this newly added tool-index row.
    assert adapt._ABSOLUTE.findall(ROW) == ["/tools/run_reference_case.py"]
    check(trees, ROW, previous="# DSSAT\n")


@pytest.mark.parametrize("reference", [
    "{KI}/run_and_score.py",
    "`{KI}/tools/s6_execution/run_reference_case.py`",
    '"{KI}/tools/read_case.py"',
    "{KI}/test_cases/site-1.0/input.dat\n",
    "| {KI}/tools/check_case.py |",
])
def test_canonical_documentation_reference_is_allowed(trees, reference):
    check(trees, reference)


@pytest.mark.parametrize("text", [
    "{KI}/../../../../home/private/input.dat",
    "{KI}/tools/../private/input.dat",
    "{KI}/tools/./input.dat",
    "{KI}//home/private/input.dat",
    "{KI}/tools//input.dat",
    "{KI}/C:/Users/private/input.dat",
    "{KI}/tools/input.dat:stream",
    r"{KI}/tools\private\input.dat",
    "{UNKNOWN}/tools/input.dat",
    "{ki}/tools/input.dat",
    "{{KI}/tools/input.dat",
    "{KI}/tools/a.py /home/private/input.dat",
    "{KI}/tools/a.py\n/mnt/shared/input.dat",
    "{KI}/tools/a.py C:/Users/private/input.dat",
    r"{KI}/tools/a.py C:\Users\private\input.dat",
    r"{KI}/tools/a.py \\server\share\input.dat",
    "{KI}/tools/a.py|/home/private/input.dat",
    "{KI}/tools/a.py`/home/private/input.dat",
    "/home/private/{KI}/tools/a.py",
    "C:/Users/private/{KI}/tools/a.py",
])
def test_documentation_reference_cannot_hide_machine_path_or_escape(trees, text):
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        check(trees, text)


@pytest.mark.parametrize("name,text", [
    ("script.py", "path = '{KI}/tools/run_reference_case.py'\n"),
    ("settings.yaml", "path: '{KI}/tools/run_reference_case.py'\n"),
])
def test_documentation_not_recognized_as_runtime_binding(trees, name, text):
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        check(trees, text, name=name)


def test_original_bound_runtime_comparison_is_not_masked(trees):
    base, candidate, cfg = trees
    # This is canonical-looking documentation but contains a current bound role.
    cfg.roles["outputs"] = Path("tools/local-output")
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        check(trees, "{KI}/tools/local-output/result.csv")


@pytest.mark.parametrize("text", [
    "KISSPATH_DATA/new-input.nc",
    "https://example.org/data/input.nc",
    "tools/read_case.py",
    "<div>Portable instructions</div>",
])
def test_existing_relative_tokens_urls_markup_still_allowed(trees, text):
    check(trees, text)


def test_unchanged_upstream_absolute_provenance_remains_allowed(trees):
    upstream = "Original provenance: /home/server/model/input.dat\n"
    check(trees, upstream + ROW, previous=upstream)


def test_new_absolute_path_is_rejected_next_to_old_upstream_provenance(trees):
    upstream = "Original provenance: /home/server/model/input.dat\n"
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        check(trees, upstream + ROW + "New: /home/other/private/input.dat\n", previous=upstream)


def test_generated_row_passes_real_registration_pipeline_with_required_seals(case):
    origin = adapt.projection(case.live, case.cfg)
    portable = case.base / "documentation-candidate"
    ki_copy.copytree(Path(origin["portable_root"]), portable)
    skill = portable / "SKILL.md"
    skill.write_text(skill.read_text() + ROW)
    runtime = case.base / "documentation-runtime"
    port.materialise(portable, runtime, case.cfg)
    with pytest.raises((adapt.AdaptationError, ValueError)):
        adapt.prepare_registration(case.live, case.cfg, portable, {}, runtime, {})
    ticket = adapt.prepare_registration(case.live, case.cfg, portable, accepted(portable),
                                        runtime, accepted(runtime))
    assert ticket["kind"] == "prepared_registration"
    # Preparation does not adopt into the live KI or issue native readiness.
    assert "run_reference_case.py" not in (case.live / "SKILL.md").read_text()

