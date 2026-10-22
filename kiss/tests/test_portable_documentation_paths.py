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



# Seen in real WRF-Hydro and ParFlow repair drafts (2026-10-20): prose
# alternatives, role paths after a closed code span, relative links and
# Ubuntu-owned locations that a Linux install recipe has to name.
@pytest.mark.parametrize("text", [
    "Launch with `mpirun`/`mpiexec`.\n",
    "NetCDF is found by (`nc-config`/`nf-config`).\n",
    "`REFKDT`/`SLOPE`/`SMCMAX` come from GENPARM.TBL.\n",
    "Install into `KISSPATH_BINARIES`/wrf_hydro/Run/wrf_hydro.exe.\n",
    "reported by check_parflow_dir()/check_file() and run_parflow.py\n",
    "| build-essential | C/C++/Fortran toolchain |\n",
    'sha256sum "$INSTALL_RUN"/*.TBL\n',
    "See [the build record](../tools/s10_execution/wrfhydro_builds.json).\n",
    "PYTHONPATH=KISSPATH_PYTHON_ENV/lib/python3*/site-packages\n",
    "Ubuntu puts libHYPRE in /usr/lib/x86_64-linux-gnu, headers in /usr/include/hypre.\n",
    "The launcher is /usr/bin/mpiexec; check /etc/os-release.\n",
])
def test_prose_and_distribution_paths_are_portable(trees, text):
    check(trees, text)


@pytest.mark.parametrize("text, literal", [
    ("Built under /usr/local/hypre/lib.\n", "/usr/local/hypre/lib."),
    ("Run `/home/user/venv/bin/python` first.\n", "/home/user/venv/bin/python`"),
    ('PARFLOW_DIR="/opt/parflow"\n', "/opt/parflow"),
    ("Data: /mnt/disk1/Hydrocraft_server/x.nc\n", "/mnt/disk1/Hydrocraft_server/x.nc"),
    ("Copy C:/Users/me/x.dat here.\n", "C:/Users/me/x.dat"),
])
def test_machine_paths_are_still_rejected_and_named(trees, text, literal):
    with pytest.raises(adapt.AdaptationError, match="machine path") as error:
        check(trees, text)
    assert repr(literal) in str(error.value)
    assert "SKILL.md" in str(error.value)


def test_error_lists_at_most_five_paths(trees):
    text = "".join(f"/home/user{n}/x\n" for n in range(7))
    with pytest.raises(adapt.AdaptationError) as error:
        check(trees, text)
    assert "'/home/user0/x'" in str(error.value) and "and 2 more" in str(error.value)


@pytest.mark.parametrize("text", [
    "WRF-Hydro executable:  {KISSPATH_BINARIES}/wrf_hydro/source/trunk/NDHMS/Run/wrf_hydro_NoahMP.exe\n",
    "TBL parameter tables:  {KISSPATH_BINARIES}/wrf_hydro/source/trunk/NDHMS/Run/ — the five\n",
    "| exe | `{KISSPATH_BINARIES}/parflow/install/bin/parflow` |\n",
    "Tables: {KISSPATH_BINARIES}/model/Run/*.TBL\n",
])
def test_documented_path_roles_are_portable(trees, text):
    check(trees, text)


@pytest.mark.parametrize("name, text", [
    ("SKILL.md", "{KISSPATH_BINARIES}/../../home/user/x\n"),
    ("SKILL.md", "{KISSPATH_BINARIES}/model /home/user/x\n"),
    ("tool.py", "path = '{KISSPATH_BINARIES}/model/bin/x'\n"),
    ("settings.yaml", "path: '{KISSPATH_BINARIES}/model/bin/x'\n"),
])
def test_documented_role_rule_is_markdown_only_and_cannot_escape(trees, name, text):
    with pytest.raises(adapt.AdaptationError, match="machine path"):
        check(trees, text, name=name)


def test_arithmetic_is_not_a_path(trees):
    check(trees, "If RAINRATE > 0.1 everywhere, the /10800 division was missed; halve it /2.5\n")


def test_every_offending_file_is_named_at_once(trees):
    base, candidate, cfg = trees
    (candidate / "SKILL.md").write_text("Run /home/user/a\n", encoding="utf-8")
    (candidate / "notes.md").write_text("See /opt/model/b\n", encoding="utf-8")
    (candidate / "tool.py").write_text("PATH = '/mnt/disk1/c'\n", encoding="utf-8")
    with pytest.raises(adapt.AdaptationError, match="machine path") as error:
        adapt._portable_changes(base, candidate, cfg)
    message = str(error.value)
    for name, literal in (("SKILL.md", "/home/user/a"), ("notes.md", "/opt/model/b"), ("tool.py", "/mnt/disk1/c")):
        assert f"{name}: {literal!r}" in message
