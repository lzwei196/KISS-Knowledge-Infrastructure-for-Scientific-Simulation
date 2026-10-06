"""All supported Desktop bundles must retain the real PNG decoder."""
import ast
from pathlib import Path
import tomllib

import pytest

SOURCE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["KISS.spec", "GeoForgeDesktop.spec", "GeoForgeDesktopWindows.spec"])
def test_desktop_spec_includes_png_decoder_and_does_not_exclude_pil(name):
    tree = ast.parse((SOURCE / name).read_text(encoding="utf-8"))
    hidden = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "harness_hidden" for t in node.targets))
    assert {"PIL.Image", "PIL.PngImagePlugin"} <= set(hidden)
    analysis = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == "Analysis")
    excluded = ast.literal_eval(next(kw.value for kw in analysis.keywords if kw.arg == "excludes"))
    assert not any(name == "PIL" or name.startswith("PIL.") for name in excluded)
    imports = next(kw.value for kw in analysis.keywords if kw.arg == "hiddenimports")
    assert any(isinstance(node, ast.Name) and node.id == "harness_hidden" for node in ast.walk(imports))


def test_source_and_shared_flow_installation_declare_decoder_dependency():
    desktop = tomllib.loads((SOURCE / "pyproject.toml").read_text(encoding="utf-8"))
    shared = tomllib.loads((SOURCE.parent / "ki_tools_common/pyproject.toml").read_text(encoding="utf-8"))
    assert any(value.lower().startswith("pillow") for value in desktop["project"]["dependencies"])
    assert any(value.lower().startswith("pillow") for value in shared["project"]["optional-dependencies"]["flow"])
