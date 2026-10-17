"""Both reviewed source variants retain their own checks and proof identity.

No interpreter, preflight or model is executed. Actual catalogue/GUI coverage
is separate; these cases vary exactly the known published dependency name.
"""
import ast
from copy import deepcopy
from pathlib import Path

import pytest

from kiss_cli import ki_adaptations, ki_fresh_paths as fresh, ki_path_contracts as paths
from .test_fresh_path_projection import case
from .test_ki_path_contracts import apply, prepare


ORIGINAL = b"tools/s3_weather_prep/build_pcse_weather_from_source.py"
BUNDLED = b"tools/s3_weather_prep/convert_vic_to_pcse_weather.py"
VARIANTS = [(ORIGINAL, paths.OLD_AST_SHA256), (BUNDLED, paths.BUNDLED_AST_SHA256)]


def select_variant(root, weather_tool):
    path = root / paths.PREFLIGHT
    raw = path.read_bytes()
    assert raw.count(ORIGINAL) == 1
    path.write_bytes(raw.replace(ORIGINAL, weather_tool))


@pytest.mark.parametrize("weather_tool,digest", VARIANTS)
@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_retained_projection_preserves_each_variants_exact_checks(tmp_path, weather_tool, digest, portable, newline):
    base, candidate, cfg, target = prepare(tmp_path, portable=portable, newline=newline)
    select_variant(base, weather_tool)
    originals = {p.name: p.read_bytes() for p in base.iterdir()}
    changes = apply(base, candidate, cfg, target)
    report = paths.validate_behavior(base, candidate, cfg, target_root=target)
    assert report["recognized_ast_sha256"] == digest
    assert report["source_root"] == str(base)
    paths.require_runtime_current(report)
    assert weather_tool in changes[paths.PREFLIGHT]
    before = ast.parse(paths._inputs(base, cfg)[paths.PREFLIGHT])
    after = ast.parse(changes[paths.PREFLIGHT])
    old_values = paths._assignments(before)
    for name, node in paths._assignments(after).items():
        if name in paths._CHANGED_NAMES:
            node.value = deepcopy(old_values[name].value)
    assert paths._ast_value(after) == paths._ast_value(before)
    assert originals == {p.name: p.read_bytes() for p in base.iterdir()}
    assert all(report[key] is False for key in
               ("model_execution", "native_execution", "scientific_validation", "preflight_passed"))
    report["recognized_ast_sha256"] = next(value for _, value in VARIANTS if value != digest)
    with pytest.raises(ValueError, match="recognized source"):
        paths.require_runtime_current(report)


@pytest.mark.parametrize("weather_tool,digest", VARIANTS)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_fresh_proof_reproduces_the_actual_variant_and_refuses_label_swap(tmp_path, weather_tool, digest, newline):
    source, cfg, target = case(tmp_path, newline=newline)
    select_variant(source, weather_tool)
    original = fresh.tree_files(source)
    dest = tmp_path / "stage"
    _, proof = ki_adaptations.project_runtime(source, dest, cfg, model="WOFOST", target_root=target)
    assert proof["recognized_ast_sha256"] == digest
    assert weather_tool in (dest / paths.PREFLIGHT).read_bytes()
    assert fresh.tree_files(source) == original
    assert not target.exists()
    fresh.require_fresh_current(proof)
    proof["recognized_ast_sha256"] = next(value for _, value in VARIANTS if value != digest)
    with pytest.raises(ValueError, match="reproduces exactly"):
        fresh.require_fresh_current(proof)


@pytest.mark.parametrize("weather_tool,_digest", VARIANTS)
@pytest.mark.parametrize("change", ["unknown_tool", "critical", "python", "exit", "import"])
def test_neither_variant_allows_other_preflight_changes(tmp_path, weather_tool, _digest, change):
    base, candidate, cfg, target = prepare(tmp_path)
    select_variant(base, weather_tool)
    replacements = {
        "unknown_tool": (weather_tool, b"tools/s3_weather_prep/unknown_weather.py"),
        "critical": (b"critical=True", b"critical=False"),
        "python": (b'"(3, 12)"', b'"(3, 13)"'),
        "exit": (b"sys.exit(1 if critical_failed else 0)", b"sys.exit(0)"),
        "import": (b"import subprocess", b"import subprocess\nimport unreviewed"),
    }
    path = base / paths.PREFLIGHT
    old, new = replacements[change]
    assert old in path.read_bytes()
    path.write_bytes(path.read_bytes().replace(old, new, 1))
    assert paths.expected_changes(base, "WOFOST", cfg, target_root=target) == {}
    with pytest.raises(ValueError, match="Unrecognized WOFOST preflight"):
        paths.validate_behavior(base, candidate, cfg, target_root=target)


@pytest.mark.parametrize("weather_tool,_digest", VARIANTS)
@pytest.mark.parametrize("damage", ["missing", "changed", "missing_root", "relative_root", "decisions", "bad_identity"])
def test_retained_currentness_requires_the_actual_captured_source(tmp_path, weather_tool, _digest, damage):
    base, candidate, cfg, target = prepare(tmp_path)
    select_variant(base, weather_tool)
    apply(base, candidate, cfg, target)
    report = paths.validate_behavior(base, candidate, cfg, target_root=target)
    if damage == "missing":
        (base / paths.PREFLIGHT).unlink()
    elif damage == "changed":
        with (base / paths.PREFLIGHT).open("ab") as stream:
            stream.write(b"\n# source content changed\n")
    elif damage == "missing_root":
        del report["source_root"]
    elif damage == "relative_root":
        report["source_root"] = "relative/source"
    elif damage == "decisions":
        report["unchanged_decisions_sha256"] = "0" * 64
    else:
        report["recognized_ast_sha256"] = []
    with pytest.raises(ValueError):
        paths.require_runtime_current(report)
