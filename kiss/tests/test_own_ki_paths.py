"""A KI's own server paths bind to its final directory; the model's home stays put."""
import ast
import os
import re
from pathlib import Path

import pytest

from kiss_cli import ki_adaptations, paths, port

REPO = Path(__file__).resolve().parents[2]
LIBRARY = REPO / "models"


@pytest.fixture
def cfg(tmp_path):
    return paths.KissConfig.default(tmp_path / "project")


def home(cfg, name="Demo"):
    return Path(cfg.roles["ki_root"]) / name


def target(cfg, name="Demo"):
    return home(cfg, name) / "ki"


def own(*files, names=("Demo",)):
    return port.OwnPackage(frozenset(names), frozenset(files))


def bind(text, cfg, package=None, ki_target=None):
    return port.unsubstitute(text, cfg, ki_target=ki_target or target(cfg),
                             own_package=package or own("run_and_score.py", "tools/run.py"))[0]


def value(source, name):
    scope = {"os": os, "Path": Path}
    exec(source, scope)
    return Path(scope[name])


@pytest.mark.parametrize("written, rest", [
    ("KISSPATH_KI_ROOT/Demo/knowledge_infrastructure/tools/run.py", "tools/run.py"),
    ("KISSPATH_KI_ROOT/Demo/knowledge_infrastructure", ""),
    ("KISSPATH_KI_ROOT/Demo/ki/tools", "tools"),
    ("KISSPATH_KI_ROOT/Demo/run_and_score.py", "run_and_score.py"),
])
def test_the_ki_folder_and_shipped_files_bind_to_the_final_directory(cfg, written, rest):
    assert value(f'X = "{written}"\n', "X") != target(cfg)     # sanity: still a token
    assert value(bind(f'X = "{written}"\n', cfg), "X") == target(cfg) / rest


@pytest.mark.parametrize("written", [
    "KISSPATH_KI_ROOT/Demo/detached/verify_1/result.json",   # run state
    "KISSPATH_KI_ROOT/Demo/source/repo",                      # source checkout
    "KISSPATH_KI_ROOT/Demo/outputs",                          # a folder, even if the KI ships one
    "KISSPATH_KI_ROOT/Demo/tools",
    "KISSPATH_KI_ROOT/Demo",                                  # the model's home itself
])
def test_the_models_home_stays_outside_the_ki(cfg, written):
    package = own("run_and_score.py", "tools/run.py", "outputs/reference.json")
    rest = written[len("KISSPATH_KI_ROOT/Demo"):].lstrip("/")
    assert value(bind(f'X = "{written}"\n', cfg, package), "X") == home(cfg) / rest


def test_code_built_from_the_models_home(cfg):
    text = ('ROOT = "KISSPATH_KI_ROOT/Demo"\n'
            'KI = os.path.join(ROOT, "knowledge_infrastructure")\n'
            'TOOLS = f"{ROOT}/knowledge_infrastructure/tools"\n'
            'RUN = Path(ROOT) / "run_and_score.py"\n'
            'STATE = os.path.join(ROOT, "detached", "verify_2")\n'
            'SRC = f"{ROOT}/source/repo"\n')
    bound = bind(text, cfg)
    assert value(bound, "KI") == target(cfg)
    assert value(bound, "TOOLS") == target(cfg) / "tools"
    assert value(bound, "RUN") == target(cfg) / "run_and_score.py"
    assert value(bound, "STATE") == home(cfg) / "detached/verify_2"
    assert value(bound, "SRC") == home(cfg) / "source/repo"


def test_code_built_from_the_ki_root(cfg):
    text = ('MODELS = Path("KISSPATH_KI_ROOT")\n'
            'KI = MODELS / "Demo" / "knowledge_infrastructure" / "tools"\n'
            'OTHER = MODELS / "Other" / "knowledge_infrastructure"\n')
    bound = bind(text, cfg)
    assert value(bound, "KI") == target(cfg) / "tools"
    assert value(bound, "OTHER") == Path(cfg.roles["ki_root"]) / "Other/knowledge_infrastructure"


def test_server_root_paths_into_models_reach_the_ki(cfg):
    text = 'ROOT = Path("KISSPATH_ROOT")\nKI = ROOT / "models" / "Demo" / "knowledge_infrastructure"\n'
    bound = port.unsubstitute(text, cfg, ki_target=target(cfg), server_layout=True,
                              own_package=own())[0]
    assert value(bound, "KI") == target(cfg)


def test_documentation_and_other_kis(cfg):
    text = ("Run `KISSPATH_KI_ROOT/Demo/knowledge_infrastructure/tools/run.py`.\n"
            "See KISSPATH_KI_ROOT/Other/knowledge_infrastructure/README.md\n"
            "Not a prefix: KISSPATH_KI_ROOT/Demo_old/knowledge_infrastructure\n")
    bound = bind(text, cfg)
    models = port._portable(cfg.roles["ki_root"])
    assert f"`{port._portable(target(cfg))}/tools/run.py`" in bound
    assert f"{models}/Other/knowledge_infrastructure/README.md" in bound
    assert f"{models}/Demo_old/knowledge_infrastructure" in bound


def test_shared_workspace_target(tmp_path):
    workspace = paths.KissConfig.default(tmp_path / "kiss" / "Demo")
    bound = bind('X = "KISSPATH_KI_ROOT/Demo/knowledge_infrastructure/tools"\n', workspace,
                 ki_target=workspace.root / "ki")
    assert value(bound, "X") == workspace.root / "ki" / "tools"


def test_without_a_target_or_package_binding_is_unchanged(cfg):
    text = 'X = "KISSPATH_KI_ROOT/Demo/knowledge_infrastructure"\n'
    plain = home(cfg) / "knowledge_infrastructure"
    assert value(port.unsubstitute(text, cfg)[0], "X") == plain
    assert value(port.unsubstitute(text, cfg, own_package=own())[0], "X") == plain
    assert value(port.unsubstitute(text, cfg, ki_target=target(cfg))[0], "X") == plain


def _ki(root, name, package=None):
    (root / "tools").mkdir(parents=True)
    (root / "knowledge_infrastructure.yaml").write_text(
        f"package:\n  name: {package or name}\n  entry: KISSPATH_KI_ROOT/{name}/knowledge_infrastructure/tools/run.py\n",
        encoding="utf-8")
    (root / "tools" / "run.py").write_text("print('run')\n", encoding="utf-8")
    return root


@pytest.mark.parametrize("name, mapped", [("SHAW", False), ("WOFOST", False), ("HYPE", True)])
def test_materialise_binds_except_shaw_and_wofost(tmp_path, cfg, name, mapped):
    live = target(cfg, name)
    port.materialise(_ki(tmp_path / "candidate", name), live, cfg, ki_target=live, model=name)
    entry = (live / "knowledge_infrastructure.yaml").read_text(encoding="utf-8").split("entry: ")[1].strip()
    assert Path(entry) == (live / "tools/run.py" if mapped else home(cfg, name) / "knowledge_infrastructure/tools/run.py")


def test_catalogue_and_package_names_both_match(tmp_path, cfg):
    source = _ki(tmp_path / "SWAT_Plus", "SWAT_Plus", package="SWAT+")
    (source / "tools" / "calib.py").write_text('BIN = "KISSPATH_KI_ROOT/SWAT+/knowledge_infrastructure/tools"\n',
                                               encoding="utf-8")
    live = target(cfg, "SWAT_Plus")
    port.materialise(source, live, cfg, ki_target=live, model="SWAT_Plus")
    entry = (live / "knowledge_infrastructure.yaml").read_text(encoding="utf-8").split("entry: ")[1].strip()
    assert Path(entry) == live / "tools/run.py"
    assert value((live / "tools" / "calib.py").read_text(encoding="utf-8"), "BIN") == live / "tools"


def test_projection_binds_the_final_directory_not_its_staging_copy(tmp_path, cfg):
    live = target(cfg, "HYPE")
    staging = tmp_path / "staging" / "ki"
    report, _ = ki_adaptations.project_runtime(_ki(tmp_path / "HYPE", "HYPE"), staging, cfg,
                                               model="HYPE", target_root=live)
    assert not report.unresolved and not report.corrupted
    entry = (staging / "knowledge_infrastructure.yaml").read_text(encoding="utf-8").split("entry: ")[1].strip()
    assert Path(entry) == live / "tools/run.py"


@pytest.mark.skipif(not LIBRARY.is_dir(), reason="KI library not in this checkout")
def test_no_library_ki_keeps_a_literal_path_to_its_server_ki_folder():
    left = []
    for ki in sorted(p for p in LIBRARY.iterdir() if (p / "SKILL.md").is_file()):
        names = {ki.name, port.package_name(ki)}
        if not all(map(port.server_layout_applies, names)):
            continue
        files = frozenset(p.relative_to(ki).as_posix() for p in ki.rglob("*") if p.is_file())
        package = port.OwnPackage(frozenset(names), files)
        spelled = re.compile(r"KISSPATH_KI_ROOT/(?:%s)/(?:knowledge_infrastructure|ki)(?![\w.-])"
                             % "|".join(map(re.escape, names)))
        for path in ki.rglob("*"):
            rel = path.relative_to(ki)
            if (not path.is_file() or rel.parts[0] == "test_cases"
                    or path.suffix.lower() not in port.TEXT_SUFFIXES):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rewritten, _ = port._migrate_own_package(text, package)
            if path.suffix == ".py":
                try:
                    ast.parse(text)
                except SyntaxError:
                    pass
                else:
                    ast.parse(rewritten)                 # never corrupts a parsable file
            left += [f"{ki.name}/{rel.as_posix()}" for _ in spelled.finditer(rewritten)]
    assert left == []
