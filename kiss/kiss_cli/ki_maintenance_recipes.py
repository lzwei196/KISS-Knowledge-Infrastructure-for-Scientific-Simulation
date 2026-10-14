"""Small, deterministic maintenance projections; never scientific authoring.

The caller owns baseline provenance, evidence checks, and KDT acceptance. These
recipes only compute exact bytes from that baseline. Unknown preflight layouts
are left unsupported, never guessed. No model code is launched by the fixture
validator: it runs the recognized preflight with an in-memory filesystem and
restricted imports in a separate interpreter.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import textwrap

import yaml

POLICY = "bounded-maintenance-recipes-v3-interface-routing"
MAX_TEXT_BYTES = 1024 * 1024

_COUNTER = '''def tool_files(ki: Path):
    """Every tool the KI carries, BOTH layouts, rejects/caches excluded. Used by generator AND gate."""
    out = set()
    roots = ([ki / "tools"] if (ki / "tools").is_dir() else []) + [d for d in ki.glob("s[0-9]*_*") if d.is_dir()]
    for r in roots:
        for q in r.rglob("*.py"):
            if q.name.startswith("__"): continue
            if any(x in str(q) for x in _TOOL_EXCLUDE): continue
            out.add(str(q.relative_to(ki)))
    return sorted(out)
'''

_CHECK_FILE = '''def check_file(path, label, executable=False):
    global PASS, FAIL
    if os.path.isfile(path):
        if executable and not os.access(path, os.X_OK):
            print(f"  WARN  {label}: exists but not executable: {path}")
            print(f"         Fix: chmod +x {path}")
            FAIL += 1
        else:
            print(f"  OK    {label}: {path}")
            PASS += 1
    else:
        print(f"  FAIL  {label}: NOT FOUND at {path}")
        FAIL += 1
'''


def _read(path: Path) -> str:
    if path.is_symlink():
        raise ValueError("Maintenance recipe inputs must be ordinary files")
    raw = path.read_bytes()
    if len(raw) > MAX_TEXT_BYTES:
        raise ValueError("Maintenance text exceeds its bounded size")
    return raw.decode("utf-8")


def _dump(node):
    return ast.dump(node, include_attributes=False)


def _tool_files(root: Path) -> list[str]:
    """Execute only the exact reviewed function, not its module import hooks."""
    from . import kdtstudio, ki_tree
    ki_tree.scan(root)
    tools = kdtstudio._projection_tools_root()
    if tools is None:
        raise ValueError("The reviewed shared tool counter is unavailable")
    tree = ast.parse(_read(tools / "ki_projection_common.py"))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "tool_files"]
    excludes = [n for n in tree.body if isinstance(n, ast.Assign)
                and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "_TOOL_EXCLUDE"]
    if (len(functions) != 1 or _dump(functions[0]) != _dump(ast.parse(_COUNTER).body[0])
            or len(excludes) != 1
            or ast.literal_eval(excludes[0].value) != ("__pycache__", "_rejected", ".kdt_")):
        raise ValueError("The shared tool counter changed; review this maintenance recipe")
    namespace = {"Path": Path, "_TOOL_EXCLUDE": ("__pycache__", "_rejected", ".kdt_")}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<reviewed tool counter>", "exec"), namespace)
    return [Path(value).as_posix() for value in namespace["tool_files"](root)]


def _mapping(node, label):
    if not isinstance(node, yaml.MappingNode):
        raise ValueError(f"{label} must be a YAML mapping")
    values = {}
    for key, value in node.value:
        if not isinstance(key, yaml.ScalarNode) or key.value in values:
            raise ValueError(f"{label} has a duplicate or nonscalar key")
        values[key.value] = value
    return values


def _inventory_changes(base: Path) -> dict[str, bytes]:
    path = base / "knowledge_infrastructure.yaml"
    if not path.is_file():
        return {}
    source = _read(path)
    document = yaml.compose(source, Loader=yaml.SafeLoader)
    top = _mapping(document, "manifest")
    if "tools" not in top or "summary" not in top:
        return {}
    tools = _mapping(top["tools"], "tools")
    summary = _mapping(top["summary"], "summary")
    if not {"count", "files"} <= set(tools) or "total_tools" not in summary:
        return {}
    # Aliases make node spans shared with other manifest claims. Do not mutate
    # them indirectly; a normal authoring revision must resolve that layout.
    visited = set()
    pending = [document]
    while pending:
        node = pending.pop()
        if id(node) in visited:
            raise ValueError("Inventory maintenance does not rewrite YAML aliases")
        visited.add(id(node))
        if isinstance(node, yaml.MappingNode):
            _mapping(node, "manifest")
            pending.extend(item for pair in node.value for item in pair)
        elif isinstance(node, yaml.SequenceNode):
            pending.extend(node.value)
    actual = _tool_files(base)
    changes = []
    for node in (tools["count"], summary["total_tools"]):
        if not isinstance(node, yaml.ScalarNode) or node.tag != "tag:yaml.org,2002:int":
            raise ValueError("Inventory counts must be integer scalars")
        if yaml.safe_load(node.value) != len(actual):
            changes.append((node.start_mark.index, node.end_mark.index, str(len(actual))))
    files = tools["files"]
    if not isinstance(files, yaml.SequenceNode) or any(
            not isinstance(n, yaml.ScalarNode) or n.tag != "tag:yaml.org,2002:str" for n in files.value):
        raise ValueError("tools.files must be a sequence of paths")
    old_files = [n.value for n in files.value]
    if old_files != actual:
        # One flow sequence is legal YAML in both flow and block contexts. It
        # changes only this value and retains every unrelated source byte.
        replacement = ("" if files.flow_style else "  ") + json.dumps(actual, ensure_ascii=False)
        end = files.end_mark.index
        trailing = source[files.start_mark.index:end]
        if trailing.endswith("\r\n"):
            replacement += "\r\n"
        elif trailing.endswith("\n"):
            replacement += "\n"
        changes.append((files.start_mark.index, end, replacement))
    updated = source
    for start, end, replacement in sorted(changes, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    # Parse again: span surgery must not absorb the next key or alter claims.
    after = yaml.safe_load(updated)
    expected = yaml.safe_load(source)
    expected["tools"]["count"] = len(actual)
    expected["tools"]["files"] = actual
    expected["summary"]["total_tools"] = len(actual)
    if after != expected:
        raise ValueError("Inventory projection changed unrelated manifest values")
    return {"knowledge_infrastructure.yaml": updated.encode("utf-8")} if updated != source else {}


_INDEX_BEGIN = "<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->"
_INDEX_END = "<!-- KI-TOOL-INDEX:END -->"
_INDEX_HEADER = """### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
"""
_INDEX_FOOTER = " public tools; `_`-prefixed helpers and packaging files excluded.*"
_MAP_BEGIN = "<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->"
_MAP_END = "<!-- KI-MAP:END -->"
_MAP_TOOLS_ROW = ("| to run the pipeline stages | `tools/` ({count} tools) | "
                  "the executable pipeline. Read each tool's argparse (`--help`) before composing a "
                  "command; SKILL.md's stage table says which tool serves which stage. |")


def _marked_span(source: str, label: str, begin: str, end: str):
    """Never repair malformed markers by eating surrounding authored prose."""
    starts, ends = source.count(f"<!-- {label}:BEGIN"), source.count(f"<!-- {label}:END")
    if not starts and not ends:
        return None
    if (starts != 1 or ends != 1 or source.count(begin) != 1 or source.count(end) != 1
            or source.index(begin) >= source.index(end)):
        raise ValueError(f"Maintenance refuses malformed {label} markers")
    start, stop = source.index(begin), source.index(end) + len(end)
    if ((start and source[start - 1] != "\n")
            or (stop < len(source) and source[stop] not in "\r\n")):
        raise ValueError(f"Maintenance refuses embedded {label} markers")
    return start, stop


def _skill_inventory_changes(base: Path) -> dict[str, bytes]:
    """Refresh only existing, recognized derived tool rows, never the KI map.

    The bundled map generator predates the public-tool index. Its tool-map row
    count and the reviewed KDT public-tool filter have different definitions:
    the former counts tools/**/*.py (except caches), while the latter filters
    the canonical cross-layout tool list. Keep that distinction explicit. No
    scientific/bibliography row is regenerated and no command is executed.
    """
    path = base / "SKILL.md"
    if not path.is_file():
        return {}
    source = _read(path)
    index_span = _marked_span(source, "KI-TOOL-INDEX", _INDEX_BEGIN, _INDEX_END)
    map_span = _marked_span(source, "KI-MAP", _MAP_BEGIN, _MAP_END)
    if index_span is None:
        return {}  # Missing documents/sections require full authoring.
    if map_span and not (map_span[1] <= index_span[0] or index_span[1] <= map_span[0]):
        raise ValueError("Maintenance refuses overlapping projected sections")
    start, stop = index_span
    block = source[start:stop]
    newline = "\r\n" if "\r\n" in block else "\n"
    normalized = block.replace("\r\n", "\n")
    if "\r" in normalized or (newline == "\r\n" and "\n" in block.replace("\r\n", "")):
        raise ValueError("Maintenance refuses mixed newlines in the tool index")
    prefix = _INDEX_BEGIN + "\n" + _INDEX_HEADER
    if not normalized.startswith(prefix):
        raise ValueError("The tool index is not a recognized generated section")
    rest = normalized[len(prefix):]
    match = re.fullmatch(r"(?P<rows>(?:[^\n]+\n)*)\n\*(?P<count>\d+)" +
                         re.escape(_INDEX_FOOTER) + "\n" + re.escape(_INDEX_END), rest)
    if not match:
        raise ValueError("The tool index is not a recognized generated section")
    interpreter = None
    seen = set()
    for row in match["rows"].splitlines():
        parsed = re.fullmatch(r"\| `(?P<path>[^`]+)` \| `(?P<python>[^`]+) \{KI\}/(?P=path) --help` \|", row)
        if not parsed or parsed["path"] in seen:
            raise ValueError("The tool index has an ambiguous path or invocation")
        seen.add(parsed["path"])
        value = parsed["python"]
        # Preserve a single existing interpreter, including materialized local
        # paths, rather than replacing it with a server or guessed interpreter.
        if (any(c in value for c in "\r\n\t`|$;&<>" )
                or not re.fullmatch(r'(?:KISSPATH_PYTHON_ENV/bin/python|python(?:3(?:\.\d+)?)?|(?:[A-Za-z]:/|/)[^"\r\n]+/python(?:3(?:\.\d+)?)?(?:\.exe)?)', value, re.I)
                or (interpreter is not None and value != interpreter)):
            raise ValueError("The tool index has no single recognized interpreter")
        interpreter = value
    actual = _tool_files(base)
    public = [p for p in actual if not p.rsplit("/", 1)[-1].startswith("_")
              and p.rsplit("/", 1)[-1] not in ("__init__.py", "setup.py", "conftest.py")]
    if public and interpreter is None:
        raise ValueError("The empty tool index provides no existing interpreter")
    for relative in [*seen, *public]:
        if (not re.fullmatch(r"[\w./-]+\.py", relative)
                or any(part in ("", ".", "..") for part in relative.split("/"))
                or relative.startswith("/")):
            raise ValueError("The tool index path cannot be safely projected")
    rows = [f"| `{relative}` | `{interpreter} {{KI}}/{relative} --help` |" for relative in public]
    replacement = prefix + "".join(row + "\n" for row in rows) + "\n*" + str(len(public)) + _INDEX_FOOTER + "\n" + _INDEX_END
    changes = [(start, stop, replacement.replace("\n", newline))]
    if map_span:
        map_start, map_stop = map_span
        map_block = source[map_start:map_stop]
        pattern = re.escape(_MAP_TOOLS_ROW).replace(r"\{count\}", r"(?P<count>\d+)")
        matches = list(re.finditer(r"(?m)^" + pattern + r"(?=\r?$)", map_block))
        if len(matches) > 1:
            raise ValueError("The KI map has duplicate tool-count rows")
        if matches:
            row = matches[0]
            # Match generate_skill_map.build_map without importing unreviewed
            # module code or rewriting its gathered-literature claims.
            count = sum(1 for p in (base / "tools").rglob("*.py") if "__pycache__" not in p.parts)
            a, b = row.span("count")
            changes.append((map_start + a, map_start + b, str(count)))
    updated = source
    for a, b, value in sorted(changes, reverse=True):
        updated = updated[:a] + value + updated[b:]
    return {"SKILL.md": updated.encode("utf-8")} if updated != source else {}


def _call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return parent + "." + node.attr if parent else ""
    return ""


def _preflight_layout(source: str):
    """Recognize a conservative conventional file-check preflight, or None."""
    if "PREFLIGHT_REPORT=" in source or "_geoforge_maintenance_" in source:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    if (len(functions) != sum(isinstance(n, ast.FunctionDef) for n in tree.body)
            or not {"main", "check_file"} <= functions.keys()
            or _dump(functions["check_file"]) != _dump(ast.parse(_CHECK_FILE).body[0])):
        return None
    guard = ast.parse('if __name__ == "__main__":\n    main()\n').body[0]
    if not tree.body or _dump(tree.body[-1]) != _dump(guard):
        return None
    assigned = {}
    imports = set()
    for node in tree.body[:-1]:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            continue
        if isinstance(node, ast.Import):
            if any(n.name not in {"os", "sys", "shutil", "subprocess"} or n.asname for n in node.names):
                return None
            imports.update(n.name for n in node.names)
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            key = node.targets[0].id
            if key not in {"PASS", "FAIL"} or key in assigned or not isinstance(node.value, ast.Constant) or type(node.value.value) is not int or node.value.value != 0:
                return None
            assigned[key] = 0
        elif isinstance(node, ast.FunctionDef):
            arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs,
                         *([node.args.vararg] if node.args.vararg else []),
                         *([node.args.kwarg] if node.args.kwarg else [])]
            if node.decorator_list or node.returns or any(a.annotation for a in arguments):
                return None
            if any(not isinstance(x, ast.Constant) for x in [*node.args.defaults,
                    *(x for x in node.args.kw_defaults if x is not None)]):
                return None
        else:
            return None
    if assigned != {"PASS": 0, "FAIL": 0} or not {"os", "sys"} <= imports:
        return None
    main = functions["main"]
    if main.args.posonlyargs or main.args.args or main.args.vararg or main.args.kwarg or main.args.kwonlyargs:
        return None
    checks = []
    for statement in main.body:
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) and _call_name(statement.value.func) == "check_file":
            call = statement.value
            if (len(call.args) != 2 or any(not isinstance(v, ast.Constant) or not isinstance(v.value, str) or not v.value for v in call.args)
                    or len(call.keywords) != 1 or call.keywords[0].arg != "executable"
                    or not isinstance(call.keywords[0].value, ast.Constant) or call.keywords[0].value.value is not True):
                return None
            checks.append((call.args[0].value, call.args[1].value))
    if not checks or len(checks) > 12 or len({p for p, _ in checks}) != len(checks):
        return None
    if sum(isinstance(n, ast.Call) and _call_name(n.func) == "check_file" for n in ast.walk(main)) != len(checks):
        return None
    # Reachable helpers may only inspect presence of optional data, format
    # output, and update counters. Scientific runners/searches are unsupported.
    allowed_calls = {"print", "len", "os.path.isfile", "os.path.isdir", "os.path.dirname",
                     "os.path.abspath", "os.path.join", "os.access", "os.listdir", "sys.exit"}
    reachable, pending = set(), ["main"]
    protected = {"print", "len", "os", "sys", "shutil", "subprocess", *functions}
    forbidden = (ast.Import, ast.ImportFrom, ast.With, ast.AsyncWith, ast.Try, ast.Raise,
                 ast.Lambda, ast.ClassDef, ast.AsyncFunctionDef, ast.While, ast.Delete,
                 ast.Yield, ast.YieldFrom, ast.Await, ast.NamedExpr)
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        reachable.add(name)
        function = functions[name]
        arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs,
                     *([function.args.vararg] if function.args.vararg else []),
                     *([function.args.kwarg] if function.args.kwarg else [])]
        if any(argument.arg in protected or argument.arg.startswith("__") for argument in arguments):
            return None
        for node in ast.walk(function):
            if isinstance(node, forbidden):
                return None
            if isinstance(node, ast.FunctionDef) and node is not function:
                return None
            if isinstance(node, ast.Name):
                if node.id.startswith("__") and node.id != "__file__":
                    return None
                if isinstance(node.ctx, ast.Store) and node.id in protected:
                    return None
            if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
                return None
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(not isinstance(target, ast.Name) for target in targets):
                    return None
            if isinstance(node, ast.Call):
                called = _call_name(node.func)
                if called in functions:
                    if called not in {"check_file", "report_project_data", "check_common_data"}:
                        return None
                    if name != "main":
                        return None
                    pending.append(called)
                elif called not in allowed_calls:
                    return None
    return tree.body[-1], checks


def _report_changes(base: Path, name: str) -> dict[str, bytes]:
    path = base / "preflight_check.py"
    if not path.is_file():
        return {}
    source = _read(path)
    layout = _preflight_layout(source)
    if layout is None:
        return {}
    guard, _checks = layout
    model = json.dumps(name, ensure_ascii=True)
    addition = textwrap.dedent('''\
        # GeoForge KDT maintenance: report the existing file-check decisions.
        import json as _geoforge_maintenance_json
        _geoforge_maintenance_checks = []
        _geoforge_maintenance_original_check_file = check_file
        _geoforge_maintenance_original_main = main

        def _geoforge_maintenance_check_file(path, label, executable=False):
            before_pass, before_fail = PASS, FAIL
            try:
                return _geoforge_maintenance_original_check_file(path, label, executable)
            finally:
                passed = PASS == before_pass + 1 and FAIL == before_fail
                _geoforge_maintenance_checks.append({
                    "kind": "binary", "subject": path, "label": label,
                    "critical": True, "status": "pass" if passed else "fail",
                    "fix": "" if passed else "Install the declared binary and ensure it is executable: " + path,
                })

        def _geoforge_maintenance_main():
            _geoforge_maintenance_checks.clear()
            try:
                return _geoforge_maintenance_original_main()
            finally:
                print("PREFLIGHT_REPORT=" + _geoforge_maintenance_json.dumps({
                    "model_id": __MODEL__, "checks": _geoforge_maintenance_checks,
                }, ensure_ascii=True))

        check_file = _geoforge_maintenance_check_file
        main = _geoforge_maintenance_main

        ''').replace("__MODEL__", model)
    newline = "\r\n" if "\r\n" in source else "\n"
    addition = addition.replace("\n", newline)
    lines = source.splitlines(keepends=True)
    offset = sum(len(line) for line in lines[:guard.lineno - 1])
    updated = source[:offset] + addition + source[offset:]
    ast.parse(updated)
    return {"preflight_check.py": updated.encode("utf-8")}


def recipe_changes(base: Path, name: str, *, runtime_config=None, target_root=None) -> dict[str, dict[str, bytes]]:
    """Return supported nonempty repairs; malformed supported input raises.

    Unsupported preflight layouts and absent inventory documents are no-ops.
    No missing document, tool, paper evidence or validation value is invented.
    """
    if not isinstance(name, str) or not name.strip() or len(name) > 200:
        raise ValueError("Maintenance requires a bounded model identity")
    base = Path(base)
    changes = {key: values for key, values in {
        "tool_inventory": {**_inventory_changes(base), **_skill_inventory_changes(base)},
        "preflight_reporting": _report_changes(base, name),
    }.items() if values}
    if len(changes) == 2:
        changes["package_contract"] = {path: raw for values in changes.values() for path, raw in values.items()}
    # This is a separate interface contract, not part of inventory/reporting.
    # Its changed tool triggers real, runtime-bound PCSE fixtures at the gate.
    from . import ki_maintenance_wofost
    routing = ki_maintenance_wofost.expected_changes(base, name)
    if routing:
        changes["wofost_parameter_routing"] = routing
    # This recipe requires a selected runtime and an explicit active target.
    # Keep it out of generic expected_changes: its manifest projection must
    # never overwrite a competing inventory recipe by dictionary order.
    if runtime_config is not None or target_root is not None:
        from . import ki_path_contracts
        runtime_paths = ki_path_contracts.expected_changes(base, name, runtime_config, target_root=target_root)
        if runtime_paths:
            changes[ki_path_contracts.RECIPE] = runtime_paths
    return changes


def expected_changes(base: Path, name: str) -> dict[str, bytes]:
    return {path: raw for changes in recipe_changes(base, name).values() for path, raw in changes.items()}


def apply_recipe(candidate: Path, *, source: Path, recipe: str, name: str,
                 runtime_config=None, target_root=None) -> dict:
    """Apply one reproducible projection in a caller-owned maintenance draft."""
    source, candidate = Path(source).resolve(), Path(candidate).resolve()
    if source == candidate or source in candidate.parents or candidate in source.parents:
        raise ValueError("Maintenance must use a separate draft, not its baseline")
    if recipe == "wofost_runtime_paths":
        from . import ki_path_contracts
        changes = ki_path_contracts.expected_changes(source, name, runtime_config, target_root=target_root)
    else:
        changes = recipe_changes(source, name).get(recipe)
    if not changes:
        raise ValueError("This baseline has no supported correction for the selected recipe")
    from . import ki_tree
    ki_tree.scan(candidate)
    for relative in changes:
        path = candidate / relative
        if path.is_symlink() or path.read_bytes() != (source / relative).read_bytes():
            raise ValueError("The draft changed before its deterministic projection")
    for relative, raw in changes.items():
        (candidate / relative).write_bytes(raw)
    return {"recipe": recipe, "changed_files": sorted(changes),
            "outputs": {path: hashlib.sha256(raw).hexdigest() for path, raw in changes.items()}}


_PROBE = r'''
import contextlib, io, json, os, sys, types
request = json.loads(sys.stdin.read())
source, paths = request["source"], request["paths"]
rows = []
scenarios = [("software_present_data_absent", None, None, False, None),
             ("software_present_data_present", None, None, True, None)]
scenarios += [("missing_" + str(i), path, None, False, None) for i, path in enumerate(paths)]
scenarios += [("not_executable_" + str(i), None, path, False, None) for i, path in enumerate(paths)]
scenarios += [("original_exception_preserved", None, None, False, paths[0])]
real_import = __import__
for label, missing, denied, data, inaccessible in scenarios:
    attempted = []
    def isfile(path):
        if path == inaccessible:
            raise OSError("fixture access failure")
        return path in paths and path != missing
    def access(path, mode):
        return path in paths and path != missing and path != denied
    fake_path = types.SimpleNamespace(isfile=isfile, isdir=lambda p: data,
        dirname=os.path.dirname, abspath=os.path.abspath, join=os.path.join)
    fake_os = types.SimpleNamespace(path=fake_path, access=access, X_OK=os.X_OK,
        listdir=lambda p: ["fixture"] if data else [], sep=os.sep)
    def exit_(code=0):
        raise SystemExit(code)
    def blocked(*args, **kwargs):
        attempted.append("forbidden process/network operation")
        raise RuntimeError(attempted[-1])
    forbidden = types.SimpleNamespace(run=blocked, Popen=blocked, call=blocked,
        check_call=blocked, check_output=blocked, which=blocked)
    def import_(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "os": return fake_os
        if name == "sys": return types.SimpleNamespace(exit=exit_)
        if name in ("subprocess", "shutil"): return forbidden
        if name == "json": return json
        raise RuntimeError("Fixture import rejected: " + name)
    # No open, eval, exec, globals, getattr, or unrestricted import authority is
    # exposed to the fixture. This is still a host test, not an OS sandbox.
    builtins_ = {"print": print, "len": len, "__import__": import_}
    namespace = {"__builtins__": builtins_, "__name__": "maintenance_probe", "__file__": "fixture/preflight_check.py"}
    output = io.StringIO()
    code, error = None, None
    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
        try:
            exec(compile(source, "<recognized preflight>", "exec"), namespace)
            namespace["main"]()
            code = 0
        except SystemExit as exc:
            code = exc.code
        except BaseException as exc:
            error = type(exc).__name__ + ": " + str(exc)
    reports = [line.split("=", 1)[1] for line in output.getvalue().splitlines() if line.startswith("PREFLIGHT_REPORT=")]
    try:
        report = json.loads(reports[0]) if len(reports) == 1 else None
    except ValueError:
        report = None
    expected_fail = missing or denied or inaccessible
    checks = report.get("checks") if isinstance(report, dict) else None
    expected_paths = paths[:1] if inaccessible else paths
    expected_error = "OSError: fixture access failure" if inaccessible else None
    expected_code = None if inaccessible else (1 if expected_fail else 0)
    ok = (error == expected_error and not attempted and code == expected_code
          and isinstance(checks, list) and len(checks) == len(expected_paths)
          and report.get("model_id") == request["name"])
    if ok:
        for check, path in zip(checks, expected_paths):
            failed = path == expected_fail
            ok = ok and (check.get("subject") == path and check.get("critical") is True
                         and check.get("status") == ("fail" if failed else "pass")
                         and (not failed or bool(check.get("fix"))))
    rows.append({"fixture": label, "ok": bool(ok), "returncode": code,
                 "report_count": len(reports), "error": error})
print(json.dumps({"ok": all(row["ok"] for row in rows), "status": "fixture_checked",
                  "fixtures": rows, "model_execution": "not_run", "filesystem": "in_memory"}))
'''


def validate_preflight_behavior(base: Path, candidate: Path) -> dict:
    """Prove the generated report reflects existing decisions, not readiness."""
    base, candidate = Path(base), Path(candidate)
    source = _read(base / "preflight_check.py")
    layout = _preflight_layout(source)
    if layout is None:
        raise ValueError("This preflight has no reviewed reporting recipe")
    # Infer no identity from model paths: the deterministic caller must supply
    # it in the generated assignment. Only parse the wrapper's constant here.
    updated = _read(candidate / "preflight_check.py")
    tree = ast.parse(updated)
    wrappers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_geoforge_maintenance_main"]
    names = [v.value for n in wrappers for node in ast.walk(n) if isinstance(node, ast.Dict)
             for key, v in zip(node.keys, node.values)
             if isinstance(key, ast.Constant) and key.value == "model_id" and isinstance(v, ast.Constant)]
    if len(names) != 1 or not isinstance(names[0], str):
        raise ValueError("Reporting candidate has no exact model identity")
    expected = _report_changes(base, names[0]).get("preflight_check.py")
    if expected != updated.encode("utf-8"):
        raise ValueError("Only the exact deterministic reporting projection may execute in fixtures")
    from . import ki_verification
    result = subprocess.run([ki_verification._preflight_interpreter(), "-I", "-B", "-c", _PROBE],
                            input=json.dumps({"source": updated, "paths": [p for p, _ in layout[1]], "name": names[0]}),
                            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False)
    if result.returncode != 0 or len(result.stdout) > 100_000:
        raise ValueError("The isolated preflight reporting fixtures could not finish")
    try:
        report = json.loads(result.stdout)
    except ValueError as error:
        raise ValueError("The reporting fixture returned invalid evidence") from error
    if not isinstance(report, dict) or report.get("ok") is not True:
        raise ValueError("The generated preflight failed its reporting fixtures")
    return report
