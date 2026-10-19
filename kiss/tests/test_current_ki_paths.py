"""The current-package token is a host binding, not a configurable path role."""

import ast
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from kiss_cli import port


def config(tmp_path):
    return SimpleNamespace(
        python=str(tmp_path / "runtime" / "python.exe"),
        roles={"ki_root": tmp_path / "catalogue", "data": tmp_path / "data"},
    )


def test_current_package_is_host_bound_and_distinct_from_catalogue(tmp_path):
    cfg = config(tmp_path)
    target = tmp_path / "项目 with spaces" / "models" / "Demo" / "ki"
    cfg.roles.update({
        "current_ki": tmp_path / "wrong role",
        "__current_ki__": tmp_path / "wrong private role",
        port.CURRENT_KI_TOKEN: tmp_path / "wrong token role",
    })
    source = "KISSPATH_CURRENT_KI/run.py\nKISSPATH_KI_ROOT/Other/ki"

    rendered, count, unresolved = port.unsubstitute(source, cfg, ki_target=target)

    assert rendered == f"{target.as_posix()}/run.py\n{cfg.roles['ki_root'].as_posix()}/Other/ki"
    assert count == 2
    assert unresolved == set()
    assert port.CURRENT_KI_TOKEN not in port.TOKENS.values()
    assert "current_ki" not in port.render_config_template()


def test_missing_host_target_stays_unresolved_despite_user_roles(tmp_path):
    cfg = config(tmp_path)
    cfg.roles.update({
        "current_ki": tmp_path / "forged",
        "__current_ki__": tmp_path / "forged",
        port.CURRENT_KI_TOKEN: tmp_path / "forged",
    })
    source = "KISSPATH_CURRENT_KI/a.py KISSPATH_CURRENT_KI/b.py"

    assert port.unsubstitute(source, cfg) == (source, 0, {port.CURRENT_KI_TOKEN})


@pytest.mark.parametrize("text", [
    "KISSPATH_CURRENT_KI_EXTRA/run.py",
    "KISSPATH_CURRENT_KI2/run.py",
    "KISSPATH_CURRENT_KIlower/run.py",
    "prefixKISSPATH_CURRENT_KI/run.py",
    "_KISSPATH_CURRENT_KI/run.py",
])
def test_current_package_token_does_not_rewrite_identifier_fragments(tmp_path, text):
    assert port.unsubstitute(text, config(tmp_path), ki_target=tmp_path / "live") == (text, 0, set())


def test_repeated_complete_tokens_replace_once_each(tmp_path):
    target = tmp_path / "final"
    source = '"KISSPATH_CURRENT_KI/a" "KISSPATH_CURRENT_KI/b" KISSPATH_CURRENT_KI'

    rendered, count, unresolved = port.unsubstitute(source, config(tmp_path), ki_target=target)

    assert rendered == f'"{target.as_posix()}/a" "{target.as_posix()}/b" {target.as_posix()}'
    assert count == 3 and not unresolved


@pytest.mark.parametrize("bad", ["", "relative/ki", "../ki", 7, False])
def test_invalid_target_rejected_even_without_current_token(tmp_path, bad):
    with pytest.raises(ValueError, match="Current KI target"):
        port.unsubstitute("unchanged", config(tmp_path), ki_target=bad)


@pytest.mark.parametrize("token", ["KISSPATH_CURRENT_KI", "KISSPATH_DATA", "KISSPATH_UNKNOWN"])
def test_unresolved_tokens_in_target_are_rejected(tmp_path, token):
    with pytest.raises(ValueError, match="no path tokens"):
        port.unsubstitute("KISSPATH_CURRENT_KI/run.py", config(tmp_path), ki_target=tmp_path / token)


def test_materialisation_uses_logical_target_and_keeps_reference_case_bytes(tmp_path):
    source = tmp_path / "portable"
    source.mkdir()
    cfg = config(tmp_path)
    logical = tmp_path / "中文 final install" / "models" / "Demo" / "ki"
    staging = tmp_path / "projection scratch"
    scripts = {
        "preflight_check.py": b'ENTRY = "KISSPATH_CURRENT_KI/run.py"\nPYTHON = "KISSPATH_PYTHON"\n',
        "knowledge_infrastructure.yaml": b'package:\n  binary:\n    path: KISSPATH_CURRENT_KI/run.py\n',
        "settings.json": b'{"entry": "KISSPATH_CURRENT_KI/run.py"}\n',
        "run.py": b"# Kept byte-for-byte when no token changes.\nvalue = 1\n",
        "test_cases/example/README.md": b"KISSPATH_CURRENT_KI is recorded provenance.\r\n",
        "test_cases/example/manifest.json": b'{"entry": "KISSPATH_CURRENT_KI/run.py"}\r\n',
        "test_cases/example/expected.json": b'{"origin": "KISSPATH_CURRENT_KI"}\n',
        "test_cases/example/inputs/data.txt": b"KISSPATH_CURRENT_KI\r\nraw data\n",
    }
    for relative, content in scripts.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = {relative: hashlib.sha256(content).hexdigest() for relative, content in scripts.items()}

    report = port.materialise(source, staging, cfg, ki_target=logical)

    assert not report.unresolved and not report.corrupted
    assert report.tokens_replaced == 4
    assert not logical.exists()
    projected = (staging / "preflight_check.py").read_text(encoding="utf-8")
    ast.parse(projected)
    assert logical.as_posix() + "/run.py" in projected
    assert staging.as_posix() not in projected
    assert source.as_posix() not in projected
    assert json.loads((staging / "settings.json").read_text(encoding="utf-8"))["entry"] == logical.as_posix() + "/run.py"
    for relative, digest in before.items():
        assert hashlib.sha256((source / relative).read_bytes()).hexdigest() == digest
        if relative.startswith("test_cases/") or relative == "run.py":
            assert hashlib.sha256((staging / relative).read_bytes()).hexdigest() == digest


def test_materialisation_missing_binding_reports_token_without_inventing_target(tmp_path):
    source = tmp_path / "portable"
    source.mkdir()
    original = b'ENTRY = "KISSPATH_CURRENT_KI/run.py"\r\n'
    (source / "preflight_check.py").write_bytes(original)
    destination = tmp_path / "projection"

    report = port.materialise(source, destination, config(tmp_path))

    assert report.unresolved == {port.CURRENT_KI_TOKEN}
    assert report.tokens_replaced == 0
    assert (destination / "preflight_check.py").read_bytes() == original


def test_invalid_target_rejected_before_materialisation_writes(tmp_path):
    source = tmp_path / "portable"
    source.mkdir()
    (source / "SKILL.md").write_text("Example", encoding="utf-8")
    destination = tmp_path / "projection"

    with pytest.raises(ValueError, match="Current KI target"):
        port.materialise(source, destination, config(tmp_path), ki_target="relative")

    assert not destination.exists()


@pytest.mark.skipif(os.name != "nt", reason="native Windows path rendering")
def test_windows_backslashes_are_rendered_safely_in_source(tmp_path):
    target = r"C:\GeoForge 中文\project with spaces\models\Demo\ki"

    rendered, count, unresolved = port.unsubstitute(
        '{"entry": "KISSPATH_CURRENT_KI/run.py"}', config(tmp_path), ki_target=target,
    )

    assert json.loads(rendered)["entry"] == "C:/GeoForge 中文/project with spaces/models/Demo/ki/run.py"
    assert count == 1 and not unresolved


def test_ordinary_roles_and_python_keep_the_existing_default_api(tmp_path):
    cfg = config(tmp_path)
    rendered, count, unresolved = port.unsubstitute("KISSPATH_DATA/input KISSPATH_PYTHON", cfg)
    assert rendered == f"{cfg.roles['data'].as_posix()}/input {port._portable(cfg.python)}"
    assert count == 2 and not unresolved
