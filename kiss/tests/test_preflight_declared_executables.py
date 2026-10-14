"""Statically declared executable checks drive bounded, whole-tree aliases."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kiss_cli import gui, install, runnable
from kiss_cli.manifest import Acquire, Manifest
from kiss_cli.paths import KissConfig


CHECKERS = '''
def check_executable(path: Path, label: str, critical: bool, report_realpath: bool = False) -> Path:
    resolved = path.resolve(strict=False)
    subject = resolved if report_realpath else path
    ok = path.is_file() and os.access(path, os.X_OK)
    add_check("binary" if report_realpath else "data", subject, critical, ok)
    return resolved

def check_file(path: Path, label: str, critical: bool, executable: bool = False) -> Path:
    return path
'''


@pytest.fixture
def case(tmp_path):
    root = tmp_path / "workspace"
    ki_root = root / "ki"
    ki_root.mkdir(parents=True)
    preflight = ki_root / "preflight_check.py"
    cfg = KissConfig.default(root)
    cfg.relocation = "none"
    cfg.roles["home"] = root
    distribution = tmp_path / "official/Demo"
    binary = distribution / "build/bin/demo.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"MZ fixture only; never execute")
    # The real selected DSSAT distribution already contains both spellings.
    # This slice connects that tree; it does not modify external filenames.
    if os.name == "nt":
        binary.with_suffix("").write_bytes(binary.read_bytes())
    (distribution / "Data").mkdir()
    (distribution / "Data/MODEL.ERR").write_bytes(b"official support file")
    ki = SimpleNamespace(name="Demo", root=ki_root, preflight=preflight)
    man = Manifest(model="Demo", install_dir="Demo",
                   acquire=Acquire(strategy="build", produces="build/bin/demo.exe"))
    return SimpleNamespace(root=root, ki=ki, cfg=cfg, distribution=distribution,
                           binary=binary, man=man, preflight=preflight)


def source(case, body):
    executable = "demo" if os.name == "nt" else "demo.exe"
    text = ("from pathlib import Path\nimport os\n"
            f"MODEL_BINARY = Path('KISSPATH_HOME/Demo/build/bin/{executable}')\n"
            "MODEL_DATA = Path('KISSPATH_HOME/Demo/Data')\n"
            "RUNTIME_PYTHON = Path('KISSPATH_PYTHON_ENV/bin/python')\n"
            + CHECKERS + "\n" + body)
    case.preflight.write_text(text, encoding="utf-8")
    return text


def test_current_explicit_checker_pattern_keeps_data_out_of_binary_candidates(case):
    source(case, '''
def main():
    binary_realpath = check_executable(
        MODEL_BINARY, "Official model", critical=True, report_realpath=True)
    check_file(MODEL_DATA / "MODEL.ERR", "support data", critical=True)
    check_executable(RUNTIME_PYTHON, "Python interpreter", critical=True)
''')
    executable = "demo" if os.name == "nt" else "demo.exe"
    assert runnable.declared(case.ki) == [
        f"KISSPATH_HOME/Demo/build/bin/{executable}", "KISSPATH_PYTHON_ENV/bin/python"]


def test_current_checker_pattern_places_whole_expected_tree_without_ki_edits_or_execution(case):
    marker = case.root / "preflight-executed.txt"
    text = source(case, f'''
Path({str(marker)!r}).write_text("Must never execute discovery input")
def main():
    binary_realpath = check_executable(
        MODEL_BINARY, "Official model", critical=True, report_realpath=True)
    check_file(MODEL_DATA / "MODEL.ERR", "support data", critical=True)
''')
    source_bytes = case.binary.read_bytes()
    for _ in range(2):
        report = gui._place_selected_existing_install(
            case.ki, case.man, case.cfg, str(case.distribution))
        assert report["state"] == "placed" and not report["verified"]
        assert (case.root / "Demo/build/bin/demo.exe").read_bytes() == source_bytes
        declared_name = "demo" if os.name == "nt" else "demo.exe"
        assert (case.root / "Demo/build/bin" / declared_name).read_bytes() == source_bytes
        assert (case.root / "Demo/Data/MODEL.ERR").read_bytes() == b"official support file"
        assert not (case.root / "Demo/Data/Genotype/China").exists()
    assert case.preflight.read_text(encoding="utf-8") == text
    assert case.binary.read_bytes() == source_bytes
    assert not marker.exists()


def test_keyword_path_is_resolved_statically(case):
    source(case, "check_executable(path=MODEL_BINARY, label='model', critical=True)\n")
    assert len(runnable.declared(case.ki)) == 1


@pytest.mark.parametrize("body", [
    "MODEL_BINARY = get_runtime_path()\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "def main(MODEL_BINARY):\n    check_executable(MODEL_BINARY, 'model', critical=True)\n",
    "def main():\n    MODEL_BINARY = get_runtime_path()\n    check_executable(MODEL_BINARY, 'model', critical=True)\n",
    "external.check_executable(MODEL_BINARY, 'model', critical=True)\n",
    "check_executable(get_runtime_path(), 'model', critical=True)\n",
    "def main(check_executable):\n    check_executable(MODEL_BINARY, 'model', critical=True)\n",
    "check_executable = alternate_checker\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
])
def test_unknown_or_shadowed_checker_binding_is_not_guessed(case, body):
    source(case, body)
    assert runnable.declared(case.ki) == []


def test_imported_checker_is_not_assumed_to_have_the_local_contract(case):
    case.preflight.write_text(
        "from external import check_executable\n"
        "check_executable('/unknown/model', 'model', critical=True)\n")
    assert runnable.declared(case.ki) == []


def test_existing_expected_tree_conflict_is_detected_with_new_checker(case):
    source(case, "check_executable(MODEL_BINARY, 'model', critical=True)\n")
    unrelated = case.root / "Demo/Data/MODEL.ERR"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"unrelated protected content")
    with pytest.raises(ValueError, match="conflict"):
        gui._place_selected_existing_install(case.ki, case.man, case.cfg, str(case.distribution))
    assert unrelated.read_bytes() == b"unrelated protected content"
    assert not (case.root / "binaries/Demo").exists()


@pytest.mark.parametrize("checker", ["check_executable", "check_file"])
def test_same_basename_different_suffix_never_places_outside_workspace(case, checker, tmp_path):
    outside = tmp_path / "outside/other-layout/demo.exe"
    args = "critical=True" if checker == "check_executable" else "critical=True, executable=True"
    source(case, f"{checker}(Path({str(outside)!r}), 'model', {args})\n")
    with pytest.raises(ValueError, match="outside.*workspace"):
        install.place_where_the_ki_expects(case.ki, case.binary, case.cfg, case.distribution)
    assert not outside.parent.exists()


@pytest.mark.parametrize("target", ["outside", "protected_ki"])
def test_alias_parent_cannot_redirect_a_file_placement(case, target, tmp_path):
    destination = tmp_path / "outside" if target == "outside" else case.ki.root
    destination.mkdir(exist_ok=True)
    parent_alias = case.root / "redirect"
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(destination), str(parent_alias))
    else:
        parent_alias.symlink_to(destination, target_is_directory=True)
    try:
        source(case, f"check_executable(Path({str(parent_alias / 'other/demo.exe')!r}), 'model', critical=True)\n")
        with pytest.raises(ValueError, match="outside.*workspace|protected KI"):
            install.place_where_the_ki_expects(case.ki, case.binary, case.cfg, case.distribution)
        assert not (destination / "other").exists()
    finally:
        os.rmdir(parent_alias) if os.name == "nt" else parent_alias.unlink()


@pytest.mark.parametrize("body", [
    "check_executable(MODEL_BINARY, path=MODEL_DATA, label='model', critical=True)\n",
    "check_executable(*[MODEL_BINARY], label='model', critical=True)\n",
    "check_executable(MODEL_BINARY, **options)\n",
    "os = alternate_os\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "from somewhere import os\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "Path = alternate_path\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "if condition:\n    MODEL_BINARY = get_runtime_path()\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "from other import check_executable\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "from other import MODEL_BINARY\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "MODEL_BINARY, other = dynamic_pair\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "def check_executable(path, label, critical): pass\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "def Path(value): return value\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "class os: pass\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "def MODEL_BINARY(): pass\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
    "from other import *\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n",
])
def test_ambiguous_call_or_namespace_is_not_inferred(case, body):
    source(case, body)
    assert runnable.declared(case.ki) == []


def test_checker_name_without_explicit_executable_test_is_not_enough(case):
    case.preflight.write_text(
        "def check_executable(path, label, critical): return path\n"
        "check_executable('/not-declared/model', 'model', critical=True)\n")
    assert runnable.declared(case.ki) == []


def test_oversized_preflight_is_not_parsed_or_executed(case):
    source(case, "#" + "x" * 1_048_576 + "\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n")
    assert runnable.declared(case.ki) == []


@pytest.mark.parametrize("prefix", ["@wrapper\n", "async "])
def test_decorated_or_async_checker_is_not_an_executable_contract(case, prefix):
    source(case, CHECKERS.replace("def check_executable", prefix + "def check_executable") +
           "\ncheck_executable(MODEL_BINARY, 'model', critical=True)\n")
    assert runnable.declared(case.ki) == []


def test_unresolved_declaration_reports_no_additional_alias_instead_of_guessing(case):
    source(case, "check_executable(lookup_runtime(), 'model', critical=True)\n")
    notes = install.place_where_the_ki_expects(case.ki, case.binary, case.cfg, case.distribution)
    assert any("No executable path could be bound statically" in note for note in notes)
    assert not (case.root / "Demo").exists()
