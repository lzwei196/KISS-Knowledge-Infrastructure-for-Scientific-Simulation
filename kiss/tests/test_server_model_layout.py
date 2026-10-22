"""Paths built from the server root bind through LEGACY_PREFIXES, not below the project."""
import ast
import os
from pathlib import Path

import pytest

from kiss_cli import paths, port

REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "models"


@pytest.fixture
def cfg(tmp_path):
    cfg = paths.KissConfig.default(tmp_path / "project")
    cfg.roles["binaries"] = tmp_path / "bin"
    cfg.roles["python_env"] = tmp_path / "venv"
    cfg.python = str(tmp_path / "venv" / "bin" / "python")
    return cfg


def bind(text, cfg):
    return port.unsubstitute(text, cfg, server_layout=True)[0]


def value(source, name, **scope):
    scope.update(os=os, Path=Path)
    exec(source, scope)
    return Path(scope[name])


def test_plain_binding_is_unchanged_unless_requested(cfg):
    text = 'ROOT = Path("KISSPATH_ROOT")\nEXE = ROOT / "model" / "hype" / "hype"\n'
    assert value(port.unsubstitute(text, cfg)[0], "EXE") == cfg.roles["server_root"] / "model/hype/hype"
    assert value(bind(text, cfg), "EXE") == cfg.roles["binaries"] / "hype/hype"


def test_environment_join_binds_below_binaries(cfg):
    text = ("EXE = os.path.join(os.environ.get('HYDROCRAFT_ROOT', 'KISSPATH_ROOT'), "
            "'model/wrf_hydro/source/trunk/NDHMS/Run/wrf_hydro.exe')\n")
    bound = bind(text, cfg)
    assert "HYDROCRAFT_ROOT" not in bound
    assert value(bound, "EXE") == cfg.roles["binaries"] / "wrf_hydro/source/trunk/NDHMS/Run/wrf_hydro.exe"


def test_join_split_across_lines(cfg):
    text = ('RUN = os.path.join(\n    os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"),\n'
            '    "model/wrf_hydro/source/trunk/NDHMS/Run")\n')
    assert value(bind(text, cfg), "RUN") == cfg.roles["binaries"] / "wrf_hydro/source/trunk/NDHMS/Run"


def test_separate_segments_and_python_env(cfg):
    text = ('HYDROCRAFT_ROOT = "KISSPATH_ROOT"\n'
            'PY = os.path.join(HYDROCRAFT_ROOT, "python_env", "bin", "python")\n'
            'ROOT = Path(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"))\n'
            'LDNDC = ROOT / "model" / "ldndc" / "ldndc-1.37.linux64"\n')
    bound = bind(text, cfg)
    # KISSPATH_PYTHON_ENV/bin/python is GeoForge's legacy interpreter spelling: it
    # binds to the configured interpreter (Scripts/python.exe in a Windows venv).
    assert value(bound, "PY") == Path(cfg.python)
    assert value(bound, "LDNDC") == cfg.roles["binaries"] / "ldndc/ldndc-1.37.linux64"


def test_parenthesised_string_operand(cfg):
    text = ('ROOT = Path("KISSPATH_ROOT")\n'
            'OBS = ROOT / ("data/obs/GRDC/"\n              "2182250_Q_Day.Cmd.txt")\n'
            'JN = os.path.join(ROOT, ("python_env/" "lib"))\n')
    bound = bind(text, cfg)
    assert value(bound, "OBS") == Path(cfg.roles["obs"]) / "GRDC/2182250_Q_Day.Cmd.txt"
    assert value(bound, "JN") == cfg.roles["python_env"] / "lib"


@pytest.mark.parametrize("rel, role, rest", [
    ('"data" / "obs" / "q.csv"', "obs", "q.csv"),
    ('"data/soil/HWSD_RASTER/hwsd.bil"', "static", "HWSD_RASTER/hwsd.bil"),
    ('"data/dem/china_dem_90m.tif"', "static", "china_dem_90m.tif"),
    ('"data/forcing/CMFD"', "data", "forcing/CMFD"),
    ('"outputs" / "run1"', "outputs", "run1"),
])
def test_data_sub_folders_follow_the_table(cfg, rel, role, rest):
    bound = bind(f'ROOT = Path("KISSPATH_ROOT")\nX = ROOT / {rel}\n', cfg)
    assert value(bound, "X") == Path(cfg.roles[role]) / rest


def test_fstring_concatenation_path_and_joinpath(cfg):
    text = ('BASE = Path("KISSPATH_ROOT")\nbasin = "NX"\n'
            'OBS = f"{BASE}/data/obs/{basin}/q.txt"\n'
            'CAT = str(BASE) + "/data/obs/x.txt"\n'
            'CTOR = Path(BASE, "model", "hype")\n'
            'JP = BASE.joinpath("python_env", "lib")\n')
    bound = bind(text, cfg)
    assert value(bound, "OBS") == Path(cfg.roles["obs"]) / "NX/q.txt"
    assert value(bound, "CAT") == Path(cfg.roles["obs"]) / "x.txt"
    assert value(bound, "CTOR") == cfg.roles["binaries"] / "hype"
    assert value(bound, "JP") == cfg.roles["python_env"] / "lib"


def test_replacement_inside_an_fstring_keeps_python_311_quoting(cfg):
    text = ('ROOT = Path("KISSPATH_ROOT")\n'
            "MSG = f\"install into {ROOT / 'python_env' / 'lib'} now\"\n")
    bound = bind(text, cfg)
    ast.parse(bound, feature_version=(3, 11))
    assert f"install into {Path(cfg.roles['python_env']) / 'lib'} now" == _msg(bound)


def _msg(source):
    scope = {"Path": Path, "os": os}
    exec(source, scope)
    return scope["MSG"]


def test_folders_without_a_table_row_stay_where_they_were(cfg):
    text = 'ROOT = Path("KISSPATH_ROOT")\nS = ROOT / "scripts" / "s1"\n'
    assert value(bind(text, cfg), "S") == cfg.roles["server_root"] / "scripts/s1"


def test_a_name_with_another_assignment_is_not_the_root():
    text = ('ROOT = Path("KISSPATH_ROOT")\n'
            'def f():\n    global ROOT\n    ROOT = Path("/elsewhere")\n'
            'X = ROOT / "model" / "x"\n')
    assert port._migrate_server_layout(text) == (text, 0)


def test_documentation_and_config_text(cfg):
    bound = bind("obs: KISSPATH_ROOT/data/obs/gauges\nexe: `KISSPATH_ROOT/model/mhm/mhm`\n", cfg)
    assert f"obs: {port._portable(cfg.roles['obs'])}/gauges\n" in bound
    assert f"exe: `{port._portable(cfg.roles['binaries'])}/mhm/mhm`" in bound


def _ki(root, name):
    (root / "tools").mkdir(parents=True)
    (root / "knowledge_infrastructure.yaml").write_text(f"package:\n  name: {name}\n", encoding="utf-8")
    (root / "tools" / "run.py").write_text(
        'import os\nPY = os.path.join("KISSPATH_ROOT", "python_env", "bin", "python")\n', encoding="utf-8")
    return root


@pytest.mark.parametrize("name, mapped", [("SHAW", False), ("WOFOST", False), ("HYPE", True)])
def test_materialise_applies_the_rule_except_shaw_and_wofost(tmp_path, cfg, name, mapped):
    source = _ki(tmp_path / "candidate", name)   # drafts live in candidate/, not <name>/
    port.materialise(source, tmp_path / "out", cfg)
    bound = (tmp_path / "out" / "tools" / "run.py").read_text(encoding="utf-8")
    expected = Path(cfg.python) if mapped else cfg.roles["server_root"] / "python_env/bin/python"
    assert value(bound, "PY") == expected


def test_package_name_prefers_the_manifest(tmp_path):
    assert port.package_name(_ki(tmp_path / "ki", "VIC")) == "VIC"
    (tmp_path / "Plain").mkdir()
    assert port.package_name(tmp_path / "Plain") == "Plain"


@pytest.mark.skipif(not LIBRARY.is_dir(), reason="KI library not in this checkout")
def test_every_library_python_file_still_parses_and_no_table_path_is_left():
    left = []
    for path in LIBRARY.rglob("*.py"):
        name = path.relative_to(LIBRARY).parts[0]
        if not port.server_layout_applies(name) or "test_cases" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            ast.parse(text)
        except SyntaxError:
            continue
        rewritten, _ = port._migrate_server_layout(text)
        tree = ast.parse(rewritten)                       # never corrupts a parsable file
        roots = port._server_root_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and port._is_server_root(node.left, roots):
                run = port._strings([node.right])
                if run and port._server_relative(port._joined(run)):
                    left.append(f"{path.relative_to(LIBRARY)}:{node.lineno}")
    assert left == []
