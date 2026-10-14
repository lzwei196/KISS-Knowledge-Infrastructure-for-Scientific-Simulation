"""Source/frozen policy identity; no model, runtime or network execution."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

from kiss_cli import implementation_identity as identity
from kiss_cli import ki_fresh_paths, ki_path_contracts, port


def module(tmp_path, source, *, filename="policy.py"):
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("fixture_policy", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def frozen(source, path):
    result = ModuleType("fixture_policy")
    result.__file__ = str(path)
    code = compile(source, "different-build-root/policy.py", "exec", dont_inherit=True)
    result.__loader__ = SimpleNamespace(get_code=lambda name: code)
    return result


def test_source_and_sourceless_code_have_same_identity_despite_paths_and_lines(tmp_path):
    source = 'VALUE = frozenset({1, 2, 3})\ndef helper(default=3):\n    return default + VALUE.__len__()\n'
    first = module(tmp_path, source)
    other = frozen("\n\n" + source.replace("\n", "\r\n"), tmp_path / "absent.py")
    assert identity.module_digest(first) == identity.module_digest(other)


def test_source_edit_after_import_invalidates_identity_even_with_cached_loader(tmp_path):
    original = "VALUE = 1\ndef nested():\n    def helper(): return VALUE + 3\n    return helper\n"
    loaded = module(tmp_path, original)
    before = identity.module_digest(loaded)
    # A same-length edit could leave an importer's timestamp bytecode cache
    # apparently current. Read the real current source rather than that cache.
    Path(loaded.__file__).write_text(original.replace("+ 3", "+ 4"), encoding="utf-8")
    assert loaded.nested()() == 4
    assert identity.module_digest(loaded) != before


@pytest.mark.parametrize("source", [
    "VALUE = 2\ndef helper(default=3): return default + VALUE\n",
    "VALUE = 1\ndef helper(default=4): return default + VALUE\n",
    "VALUE = 1\ndef helper(default=3): return default - VALUE\n",
    "VALUE = 1\ndef helper(default=3):\n    try: return default + VALUE\n    except TypeError: return None\n",
    "from __future__ import annotations\nVALUE = 1\ndef helper(default=3): return default + VALUE\n",
])
def test_frozen_executable_changes_invalidate_identity(tmp_path, source):
    first = frozen("VALUE = 1\ndef helper(default=3): return default + VALUE\n", tmp_path / "absent.py")
    second = frozen(source, tmp_path / "other.py")
    assert identity.module_digest(first) != identity.module_digest(second)


@pytest.mark.parametrize("field,replacement", [("co_flags", 0x1000000), ("co_exceptiontable", b"changed")])
def test_execution_metadata_is_part_of_identity(tmp_path, field, replacement):
    first = frozen("VALUE = 1\n", tmp_path / "absent.py")
    baseline = identity.module_digest(first)
    original = first.__loader__.get_code(first.__name__)
    if not hasattr(original, field):
        pytest.skip(f"Interpreter has no {field}")
    first.__loader__.get_code = lambda name: original.replace(**{field: replacement})
    assert identity.module_digest(first) != baseline


def test_policy_algorithm_and_bytecode_abi_changes_invalidate_identity(tmp_path, monkeypatch):
    loaded = frozen("VALUE = 1\n", tmp_path / "absent.py")
    baseline = identity.module_digest(loaded)
    with monkeypatch.context() as changed:
        changed.setattr(identity, "POLICY", "next-identity-policy")
        assert identity.module_digest(loaded) != baseline
    with monkeypatch.context() as changed:
        changed.setattr(identity, "__file__", str(tmp_path / "identity.py"))
        (tmp_path / "identity.py").write_text("ALGORITHM = 2\n", encoding="utf-8")
        assert identity.module_digest(loaded) != baseline
    with monkeypatch.context() as changed:
        changed.setattr(sys, "implementation", SimpleNamespace(name="different", cache_tag="different-abi"))
        assert identity.module_digest(loaded) != baseline


@pytest.mark.parametrize("loader", [None, SimpleNamespace(get_code=lambda name: None),
                                    SimpleNamespace(get_code=lambda name: "not code")])
def test_missing_code_fails_closed(tmp_path, loader):
    loaded = frozen("VALUE = 1\n", tmp_path / "absent.py")
    loaded.__loader__ = loader
    with pytest.raises(identity.IdentityError, match="Cannot identify"):
        identity.module_digest(loaded)


@pytest.mark.parametrize("damage", ["syntax", "unreadable"])
def test_invalid_existing_source_never_falls_back_to_old_code(tmp_path, damage):
    loaded = frozen("VALUE = 1\n", tmp_path / "policy.py")
    path = Path(loaded.__file__)
    if damage == "syntax":
        path.write_text("this is invalid Python !", encoding="utf-8")
    else:
        path.mkdir()
    with pytest.raises(identity.IdentityError, match="Cannot (compile|read)"):
        identity.module_digest(loaded)


def test_complete_path_policies_work_without_source_files(tmp_path, monkeypatch):
    modules = (ki_fresh_paths, ki_path_contracts, port, identity)
    originals = {item: compile(Path(item.__file__).read_bytes(), item.__file__, "exec",
                               dont_inherit=True, optimize=0) for item in modules}
    before = ki_fresh_paths.source_digest(), ki_path_contracts.source_digest()
    for item, code in originals.items():
        monkeypatch.setattr(item, "__file__", str(tmp_path / (item.__name__ + ".py")))
        monkeypatch.setattr(item, "__loader__", SimpleNamespace(get_code=lambda name, code=code: code))
    assert (ki_fresh_paths.source_digest(), ki_path_contracts.source_digest()) == before
    # The fresh receipt must also cover its ordinary port implementation.
    altered = compile("POLICY_CHANGED = True", "elsewhere/port.py", "exec")
    monkeypatch.setattr(port, "__loader__", SimpleNamespace(get_code=lambda name: altered))
    assert ki_fresh_paths.source_digest() != before[0]
    assert ki_path_contracts.source_digest() == before[1]
