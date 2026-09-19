"""Is this model actually runnable? — code, not opinion.

``preflight_check.py`` answers "is the file there": ``check_file(...,
executable=True)`` tests existence and the x bit and nothing else. A binary
built for another architecture, or missing libnetcdf / libgfortran / an MPI
runtime, passes that check and fails the moment anyone tries to use it. A
Python model whose numpy is absent passes it too.

This module closes that gap with four escalating tests, all mechanical:

  1. present   — the executable exists where the KI says it does
  2. shaped    — it is the right kind of executable for this machine
                 (ELF vs Mach-O vs PE vs script, and the right architecture)
  3. linked    — everything it needs resolves: shared libraries for a compiled
                 binary, imports for a script. Same question, two runtimes.
  4. responds  — it actually executes

Only (4) proves usability; (2) and (3) explain nearly every failure of it.
The agent does not judge any of this — it reads the verdict and acts.
"""

from __future__ import annotations

import ast
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

#: Flags that make a model print something and exit rather than start solving.
#: Tried in order; a model that ignores all of them still counts as running if
#: it exits on its own.
PROBE_FLAGS = ("--version", "-v", "--help", "-h", "")

#: Interpreters for models shipped as source. A scientific model written in
#: Python is no less installed than one written in Fortran; it just fails
#: differently, so it has to be probed differently.
INTERPRETERS = {
    # The frozen app's sys.executable is the GeoForge launcher, not Python.
    # ``check`` replaces this with the selected model/runtime interpreter.
    ".py": ["python3"],
    ".R": ["Rscript"], ".r": ["Rscript"],
    ".jl": ["julia"],
    ".sh": ["bash"], ".bash": ["bash"],
    ".m": ["octave", "--no-gui", "--eval"],
    ".pl": ["perl"],
}

_MARK = "@@KISS-MISSING@@"

_IMPORT_RE = re.compile(r"^\s*(?:import\s+([\w.]+)|from\s+([\w.]+)\s+import)", re.M)

#: A process can start, print one of these, and exit — having proved only that
#: the *launcher* works. APSIM's binary loads and links cleanly, then reports
#: "You must install .NET"; the model cannot run. Treating that as success is
#: the exact false green this module exists to prevent.
MISSING_RUNTIME = (
    ("must install .net", "the .NET runtime is not installed"),
    ("dotnet: not found", "the .NET runtime is not installed"),
    ("no java runtime", "no Java runtime is installed"),
    ("unable to locate a java runtime", "no Java runtime is installed"),
    ("jvmlib", "no Java runtime is installed"),
    ("error while loading shared libraries", "a shared library is missing"),
    ("image not found", "a shared library is missing"),
    ("modulenotfounderror", "a Python module is missing"),
    ("importerror", "a Python import failed"),
    ("command not found", "a required command is not on PATH"),
    ("no such file or directory", "an interpreter or helper is missing"),
)


def _runtime_gap(out: str) -> str:
    """Name the missing runtime a probe just reported, if it reported one."""
    low = out.lower()
    # Official HYPE 5.35.0 treats the first unknown argument as the simulation
    # directory (data.f90:11113), then appends info.txt (data.f90:11431).
    # Its --version probe therefore reaches a missing case configuration after
    # printing the real model banner. Do not exempt arbitrary missing .txt files.
    if re.search(r"(?m)^\s*hype version 5\.35\.0\s*$", low):
        low = re.sub(
            r"(?m)^fortran runtime error: cannot open file '--versioninfo\.txt': no such file or directory\s*$",
            "", low)
    # A Fortran namelist is project input, not an interpreter or shared library.
    # Strip only this precise runtime diagnostic; retain every other error line.
    low = re.sub(
        r"(?m)^fortran runtime error: cannot open file '[^'\n]*\.(?:nam|nml)': no such file or directory\s*$",
        "", low)
    for needle, why in MISSING_RUNTIME:
        if needle in low:
            return why
    return ""

#: Languages whose models are compiled: these must have a binary to be usable,
#: whatever their preflight remembered to declare. Judging a Fortran model on
#: imports alone would pass it while its executable is missing entirely.
COMPILED = {"fortran", "c", "c++", "cpp", "csharp", "julia", "matlab",
            "c++/c/python", "c/c++"}

#: Modules that ship with CPython — absent from site-packages by design, so
#: never report them missing.
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__"}


@dataclass
class Verdict:
    """What we found out, in the order we found it out."""

    model: str
    binary: str = ""
    present: bool = False
    shaped: bool = False
    linked: bool = False
    responds: bool = False
    kind: str = ""
    missing: list[str] = field(default_factory=list)
    imports_ok: bool = True
    needs_binary: bool = True
    detail: str = ""
    python: str = ""
    probe_command: list[str] = field(default_factory=list)
    probe_output: str = ""
    probe_returncode: int | None = None
    probe_timed_out: bool = False
    probe_runtime_assets: list[dict] = field(default_factory=list)
    probe_created_paths: list[str] = field(default_factory=list)
    implementation_id: str = ""
    installation_scope: str = ""
    official_upstream_verified: bool | None = None

    @property
    def usable(self) -> bool:
        """Everything the KI declares must work — its binary and its imports.

        A model with a Fortran core that also needs numpy is usable only when
        both are in place, so neither half can be waived.
        """
        if not self.imports_ok:
            return False
        if not self.needs_binary:
            return True                 # a Python-package KI: imports are the model
        return self.present and self.shaped and self.linked and self.responds

    #: The one word the app paints green or red.
    @property
    def state(self) -> str:
        return "ready" if self.usable else "blocked"

    def summary(self) -> str:
        if self.kind == "unknown":
            return f"cannot verify — {self.detail}"
        if not self.imports_ok:
            return f"missing Python modules: {', '.join(self.missing[:6])}"
        if self.usable and not self.needs_binary:
            return "runnable (python package) — all declared imports resolve"
        if self.usable:
            return f"runnable ({self.kind}) — {self.detail}"
        if not self.present:
            return f"not found — {self.detail}"
        if not self.shaped:
            return f"wrong kind of executable — {self.detail}"
        if not self.linked:
            if self.detail:
                return self.detail
            what = "shared libraries" if self.kind in ("elf", "macho", "pe") else "imports"
            return f"missing {what}: {', '.join(self.missing[:6])}"
        return f"does not execute — {self.detail}"

    def as_dict(self) -> dict:
        return {"model": self.model, "binary": self.binary, "state": self.state,
                "present": self.present, "shaped": self.shaped,
                "linked": self.linked, "responds": self.responds,
                "kind": self.kind, "missing": self.missing,
                "detail": self.detail, "python": self.python,
                "summary": self.summary(), "probe_command": self.probe_command,
                "probe_output": self.probe_output, "probe_returncode": self.probe_returncode,
                "probe_timed_out": self.probe_timed_out,
                "probe_created_paths": self.probe_created_paths,
                "implementation_id": self.implementation_id,
                "installation_scope": self.installation_scope,
                "official_upstream_verified": self.official_upstream_verified}


# ---------------------------------------------------------------- locating

def _static_path(node: ast.AST, names: dict[str, str]) -> str | None:
    """Evaluate the small path-expression subset used by generated preflights."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _static_path(node.left, names), _static_path(node.right, names)
        return str(Path(left) / right) if left is not None and right is not None else None
    if isinstance(node, ast.Attribute):
        value = _static_path(node.value, names)
        if value is not None and node.attr == "parent":
            return str(Path(value).parent)
    if not isinstance(node, ast.Call):
        return None

    args = [_static_path(arg, names) for arg in node.args]
    if isinstance(node.func, ast.Name) and node.func.id in {"Path", "str"}:
        return args[0] if args and args[0] is not None else None
    if isinstance(node.func, ast.Attribute):
        chain = []
        target: ast.AST = node.func
        while isinstance(target, ast.Attribute):
            chain.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            chain.append(target.id)
        dotted = ".".join(reversed(chain))
        if dotted == "os.path.join" and args and all(a is not None for a in args):
            return os.path.join(*args)
        if dotted == "os.path.dirname" and args and args[0] is not None:
            return os.path.dirname(args[0])
        if dotted == "os.path.abspath" and args and args[0] is not None:
            return os.path.abspath(args[0])
        if node.func.attr == "resolve":
            base = _static_path(node.func.value, names)
            return str(Path(base).resolve()) if base is not None else None
    return None


def declared(ki) -> list[str]:
    """Executable paths the KI's preflight names, tokens and all.

    Generated preflights also check data, documentation, and Python
    environments.  Treating the first literal ``check_file`` as the model
    binary made CRHM's elevation NetCDF look executable.  Read only calls whose
    own ``executable`` argument is true, while resolving their simple Path or
    ``os.path`` assignments without executing the preflight.
    """
    pre = getattr(ki, "preflight", None)
    if not pre or not Path(pre).is_file():
        return []
    text = Path(pre).read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    names = {"__file__": str(Path(pre))}
    path_index, executable_index = 0, None
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) and stmt.name == "check_file":
            params = [arg.arg for arg in stmt.args.args]
            if "path" in params:
                path_index = params.index("path")
            if "executable" in params:
                executable_index = params.index("executable")
            break

    # Resolve module-level constants in source order.  A few generated KIs use
    # Path division; older ones use os.path.dirname/join.
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            value = _static_path(stmt.value, names)
            if value is not None:
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = value

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = (node.func.id if isinstance(node.func, ast.Name)
                     else node.func.attr if isinstance(node.func, ast.Attribute)
                     else "")
        if func_name != "check_file":
            continue
        explicit = next((kw.value for kw in node.keywords
                         if kw.arg == "executable"), None)
        if explicit is None and executable_index is not None and len(node.args) > executable_index:
            explicit = node.args[executable_index]
        if not (isinstance(explicit, ast.Constant) and explicit.value is True):
            continue
        if len(node.args) <= path_index:
            continue
        value = _static_path(node.args[path_index], names)
        if value and value not in out:
            out.append(value)
    return out


def declared_dirs(ki) -> list[str]:
    """Directories the KI's preflight requires, from its own ``check_dir`` calls."""
    pre = getattr(ki, "preflight", None)
    if not pre or not Path(pre).is_file():
        return []
    text = Path(pre).read_text(encoding="utf-8", errors="replace")
    return [m.group(1) for m in
            re.finditer(r"""check_dir\(\s*['"]([^'"]+)['"]""", text)]


def declared_imports(ki) -> list[str]:
    """Read literal import contracts, including simple loops, without running preflight."""
    pre = getattr(ki, "preflight", None)
    if not pre or not Path(pre).is_file():
        return []
    try:
        tree = ast.parse(Path(pre).read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    argument_index = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "check_import":
            params = [arg.arg for arg in node.args.args if arg.arg not in {"self", "cls"}]
            if "module" in params:
                argument_index = params.index("module")
            break
    seen, out = set(), []
    # Some KIs declare their mandatory runtime imports as a module-level list
    # and check them through subprocess helpers rather than check_import calls.
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "IMPORT_MODULES"
                for target in statement.targets):
            try:
                modules = ast.literal_eval(statement.value)
            except (ValueError, TypeError, SyntaxError):
                continue
            if isinstance(modules, (list, tuple)):
                for mod in modules:
                    if isinstance(mod, str) and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", mod) and mod not in seen:
                        seen.add(mod)
                        out.append(mod)

    def literal(node, env):
        if isinstance(node, ast.Name):
            return env.get(node.id)
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError, SyntaxError):
            return None

    def bind(target, value, env):
        if isinstance(target, ast.Name):
            env[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(value, (tuple, list)):
            if len(target.elts) == len(value):
                for child, item in zip(target.elts, value):
                    bind(child, item, env)

    def scan(node, env):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local = dict(env)
            for arg in node.args.args:
                local.pop(arg.arg, None)
            for statement in node.body:
                scan(statement, local)
            return
        if isinstance(node, ast.Assign):
            value = literal(node.value, env)
            for target in node.targets:
                bind(target, value, env)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bind(node.target, literal(node.value, env), env)
        elif isinstance(node, ast.For):
            values = literal(node.iter, env)
            if isinstance(values, (list, tuple)):
                for value in values:
                    local = dict(env)
                    bind(node.target, value, local)
                    for statement in node.body:
                        scan(statement, local)
                for statement in node.orelse:
                    scan(statement, dict(env))
                return
        elif isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == "check_import") or (isinstance(node.func, ast.Attribute) and node.func.attr == "check_import")):
            critical = next((kw.value for kw in node.keywords if kw.arg == "critical"), None)
            if critical is not None and literal(critical, env) is False:
                return
            argument = next((kw.value for kw in node.keywords if kw.arg == "module"), None)
            if argument is None and len(node.args) > argument_index:
                argument = node.args[argument_index]
            mod = literal(argument, env)
            if isinstance(mod, str) and re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", mod) and mod not in seen:
                seen.add(mod)
                out.append(mod)
        for child in ast.iter_child_nodes(node):
            scan(child, env)

    scan(tree, {})
    # A module that lives inside the KI package itself (EPIC's tools/_common.py)
    # is shipped with the KI, not installed into the environment; the import
    # probe runs from the KI root and would report it missing for the wrong
    # reason. Drop names that resolve to a file or package inside the KI.
    root = Path(getattr(ki, "root", "") or "")
    if root.is_dir():
        def _local(mod: str) -> bool:
            head = mod.split(".")[0]
            for base in (root, root / "tools", root / "scripts", root / "workflow"):
                if (base / f"{head}.py").is_file() or (base / head / "__init__.py").is_file():
                    return True
            return False
        out = [m for m in out if not _local(m)]
    return out


def missing_imports(mods: list[str], python: str, cwd: Path | None = None,
                    env: dict[str, str] | None = None) -> list[str]:
    """Import the declared modules; discovery alone does not prove they load."""
    if not mods:
        return []
    probe = ("import importlib\n"
             "for m in %r:\n"
             "    try:\n"
             "        importlib.import_module(m)\n"
             "    except Exception:\n"
             "        print('%s' + m)\n"
             "print('__GEOFORGE_IMPORT_PROBE_DONE__')\n" % (mods, _MARK))
    env = dict(os.environ if env is None else env)
    env.setdefault("MPLBACKEND", "Agg")
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    try:
        r = subprocess.run([python, "-c", probe], capture_output=True, text=True,
                           timeout=180, cwd=str(cwd) if cwd else None, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return list(mods)
    if r.returncode or "__GEOFORGE_IMPORT_PROBE_DONE__" not in r.stdout.splitlines():
        return list(mods)
    return [ln.split(_MARK, 1)[1].strip() for ln in r.stdout.splitlines()
            if ln.startswith(_MARK)]


def _package_module(man) -> str:
    """The import name promised by a pip manifest, when it promises one."""
    acquire = getattr(man, "acquire", None) if man is not None else None
    if not acquire or getattr(acquire, "strategy", "") != "pip":
        return ""
    raw = getattr(acquire, "produces", None) or getattr(acquire, "package", None) or ""
    # A distribution may be pinned or use extras; imports use underscores.
    raw = re.split(r"[<>=!~\[; ]", str(raw), maxsplit=1)[0].strip()
    return raw.replace("-", "_") if re.fullmatch(r"[A-Za-z0-9_.-]+", raw) else ""


def _python_candidates(cfg, configured: str) -> list[str]:
    """Likely interpreters an install agent may have created in this workspace.

    Agent providers do not share one venv convention.  Accept the small set of
    conventional, project-contained layouts instead of requiring every model
    to rewrite ``kiss.toml`` perfectly before GeoForge can see a successful
    install.  The selected path is returned in the verdict and persisted by
    the setup handler.
    """
    candidates: list[Path | str] = []
    roles = getattr(cfg, "roles", {}) if cfg is not None else {}
    root = Path(getattr(cfg, "root", Path.cwd())) if cfg is not None else Path.cwd()
    binaries = Path(roles.get("binaries", root / "binaries"))
    python_env = Path(roles.get("python_env", root / "venv"))
    for base in (python_env, root / "venv", root / ".venv",
                 binaries / "venv", binaries / ".venv"):
        candidates.extend((base / "bin" / "python", base / "Scripts" / "python.exe"))
    if binaries.is_dir():
        candidates.extend(binaries.glob("*/venv/bin/python"))
        candidates.extend(binaries.glob("*/.venv/bin/python"))
        candidates.extend(binaries.glob("*/venv/Scripts/python.exe"))
        candidates.extend(binaries.glob("*/.venv/Scripts/python.exe"))
    candidates.append(configured)
    out: list[str] = []
    for candidate in candidates:
        value = str(candidate)
        resolved = shutil.which(value) or (value if Path(value).is_file() else "")
        if resolved and resolved not in out:
            out.append(resolved)
    return out


def select_python(cfg, configured: str, modules: list[str], cwd: Path | None = None) -> str:
    """Choose the project-contained interpreter that imports the model."""
    from .paths import with_ki_tools_common
    env = with_ki_tools_common(cfg) if cfg is not None else None
    for candidate in _python_candidates(cfg, configured):
        if not modules or not missing_imports(modules, candidate, cwd, env=env):
            return candidate
    return configured


def find_binary(ki, man=None, cfg=None, harvested: dict | None = None) -> Path | None:
    """Locate the model executable from what the KI and manifest declare."""
    cands: list[Path] = []
    if man is not None and getattr(man, "acquire", None) and getattr(man.acquire, "produces", None) and cfg is not None:
        cands.append(cfg.roles["binaries"] / (man.install_dir or ki.name) / man.acquire.produces)
        # An explicit native product is authoritative even before it exists.
        # Falling back to upstream setup tooling can falsely certify a failed build.
        if str(getattr(man, "binary_type", "")).strip().lower() in {"mach-o", "macho", "elf", "pe"}:
            if cands[0].is_file():
                return cands[0]
            # The recipe names the product; an agent that cloned one level
            # deeper (src/epanet2.2/...) or copied the product to binaries/
            # still built THAT file. Accept the same-named real executable
            # under the binaries root — never a script or an interpreter —
            # so a layout difference is not reported as a failed build.
            want = Path(man.acquire.produces).name
            skip = {".git", "venv", ".venv", "ki_tools_common", "ki", "runs", "node_modules"}
            hits = []
            for root in (cfg.roles.get("binaries"), getattr(cfg, "root", None)):
                if not root or not Path(root).is_dir():
                    continue
                try:
                    hits += [f for f in Path(root).rglob(want)
                             if f.is_file() and os.access(f, os.X_OK)
                             and not (skip & set(f.relative_to(root).parts[:-1]))
                             and f.suffix not in (".sh", ".py", ".pl", ".txt", ".cmake", ".o")]
                except OSError:
                    continue
                if hits:
                    break
            if hits:
                return max(hits, key=lambda f: f.stat().st_mtime)
            return cands[0]
    rel = (harvested or {}).get(ki.name)
    if rel and cfg is not None:
        cands.append(cfg.roles["binaries"] / ki.name / rel)
    # Last resort: whatever the KI's own preflight names as its binary.
    for p in declared(ki):
        if p.startswith("KISSPATH_"):
            if cfg is None:
                continue                # unresolvable without an install
            try:
                from .port import unsubstitute
                p = unsubstitute(p, cfg)[0]
            except Exception:
                continue
        cands.append(Path(p))
    # Interpreter startup does not establish a model installation in any language.
    cands = [c for c in cands if not re.fullmatch(
        r"(?:python(?:\d+(?:\.\d+)*)?|rscript|r|julia(?:-?\d+(?:\.\d+)*)?|java|node|nodejs|octave(?:-cli)?)(?:\.exe)?", c.name.lower())]
    for c in cands:
        if c.is_file():
            return c
    return cands[0] if cands else None


# ---------------------------------------------------------------- shape

def _file_kind(p: Path) -> str:
    """What sort of executable this is. Magic bytes first, suffix second.

    Suffix is not a fallback for style: plenty of working models are Python
    files with no shebang, and calling those "unknown" would paint a working
    install red.
    """
    try:
        head = p.open("rb").read(4)
    except OSError:
        return "unreadable"
    if head[:4] == b"\x7fELF":
        return "elf"
    if head[:2] == b"MZ":
        return "pe"                     # Windows binary — needs wine here
    if head[:4] in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xce\xfa\xed\xfe"):
        return "macho"
    if head[:2] == b"#!":
        return "script"
    if p.suffix in INTERPRETERS:
        return "script"
    return "other"


def _interpreter(p: Path, python: str | None = None) -> list[str] | None:
    """How to launch a script: its shebang if it has one, else its suffix."""
    try:
        first = p.open("rb").read(256).split(b"\n", 1)[0].decode("utf-8", "replace")
    except OSError:
        first = ""
    if first.startswith("#!"):
        parts = first[2:].strip().split()
        if parts:
            if parts[0].endswith("env") and len(parts) > 1:
                parts = parts[1:]
            exe = shutil.which(parts[0]) or (parts[0] if Path(parts[0]).exists() else None)
            if python and re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", Path(parts[0]).name):
                # pip console scripts often have no .py suffix. Keep the
                # selected workspace environment even with a stale shebang.
                selected = shutil.which(python) or (python if Path(python).is_file() else None)
                return [selected] + parts[1:] if selected else None
            if exe and not (python and "python" in Path(exe).name):
                return [exe] + parts[1:]
    argv = INTERPRETERS.get(p.suffix)
    if argv is None:
        return None
    argv = list(argv)
    if p.suffix == ".py" and python:
        argv[0] = python                # the KI's own venv, not ours
    resolved = shutil.which(argv[0]) or (argv[0] if Path(argv[0]).is_file() else None)
    return [resolved] + argv[1:] if resolved else None


def _ki_script(p: Path, ki) -> bool:
    """Recognize a KI helper, including a copy relocated as an install product.

    A compiled model's orchestration script can print argparse help without
    ever loading its engine. That is not evidence that the engine was built.
    Installed upstream entry points outside the KI remain eligible for probing.
    """
    root = getattr(ki, "root", None)
    if root is None:
        return False
    root = Path(root).resolve()
    if p.resolve().is_relative_to(root):
        return True
    try:
        content = p.read_bytes()
        for helper in (root / "tools").rglob("*"):
            if (helper.is_file() and helper.stat().st_size == len(content)
                    and helper.read_bytes() == content):
                return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------- linkage

def _sidecar_lib_env(p: Path, env: dict[str, str] | None = None) -> dict[str, str]:
    """LD_LIBRARY_PATH with the binary's own directory (and its lib/ siblings).

    Several upstreams ship their .so files next to the executable and document
    `export LD_LIBRARY_PATH=$dirbin` (DualSPHysics, DSSAT's dependencies).
    Checking such a binary with a bare loader path reports libraries as
    missing that are sitting beside it.
    """
    base = dict(env if env is not None else os.environ)
    if platform.system() != "Linux":
        return base
    d = p.resolve().parent
    extra = [str(d), str(d.parent / "lib"), str(d / "lib")]
    have = base.get("LD_LIBRARY_PATH", "")
    base["LD_LIBRARY_PATH"] = os.pathsep.join([x for x in extra if Path(x).is_dir()] + ([have] if have else []))
    return base


def _missing_libs(p: Path) -> list[str]:
    """Shared libraries the loader cannot resolve. Linux only; [] elsewhere."""
    if platform.system() != "Linux" or not shutil.which("ldd"):
        return []
    try:
        r = subprocess.run(["ldd", str(p)], capture_output=True, text=True, timeout=30,
                           env=_sidecar_lib_env(p))
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln.split("=>")[0].strip() for ln in r.stdout.splitlines() if "not found" in ln]


def _missing_imports(p: Path, python: str, env: dict[str, str] | None = None) -> list[str]:
    """Top-level imports a script needs that this interpreter cannot find.

    The script's own directory goes on the path first: models routinely import
    sibling modules, and reporting those missing would be an artefact of where
    we ran from rather than anything about the install.
    """
    try:
        src = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    mods = sorted({(m.group(1) or m.group(2)).split(".")[0]
                   for m in _IMPORT_RE.finditer(src)} - _STDLIB)
    if not mods:
        return []
    return missing_imports(mods, python, p.parent, env=env)


# ---------------------------------------------------------------- execution

def _ran(rc: int) -> bool:
    """Only a normal process exit can establish a successful startup probe.

    A signal may be a loader/security rejection or resource kill before main.
    Models may choose positive nonzero exits when project inputs are absent.
    """
    return rc is not None and rc >= 0


def _check_r_package(v, contract, man, cfg, timeout, env):
    from . import rpackage
    v.kind = "R package (native Fortran)"
    v.needs_binary = True
    try:
        c = rpackage.validate(contract)
        root = Path(cfg.root).resolve()
        prefix = (root if c.get("library_root", "model") == "workspace" else
                  rpackage.scoped(Path(cfg.roles["binaries"]) / man.install_dir, root, root))
        library = rpackage.scoped(prefix / c["library"], root, root)
        binary = rpackage.scoped(library / c["name"] / c["dll"], root, root)
        v.binary = str(binary)
        v.present = binary.is_file()
        if not v.present:
            v.detail = f"missing installed R package library: {binary}"
            return v
        native = {"Darwin": "macho", "Linux": "elf", "Windows": "pe"}.get(platform.system())
        v.shaped = _file_kind(binary) == native
        if not v.shaped:
            v.detail = "R package DLL is not native to this platform"
            return v
        runtime = shutil.which("Rscript")
        if not runtime:
            v.detail = "Rscript runtime is unavailable"
            return v
        v.probe_command = [runtime, *rpackage.probe_args(library, c)]
        clean_env = {k: val for k, val in (env or os.environ).items()
                     if not any(secret in k.upper() for secret in
                                ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
        with tempfile.TemporaryDirectory(prefix="kiss-r-package-probe-") as empty:
            result = subprocess.run(v.probe_command, cwd=empty, env=clean_env,
                                    stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=min(timeout, 25))
        v.probe_output = (result.stdout + result.stderr)[-12000:]
        v.probe_returncode = result.returncode
        v.linked = v.responds = result.returncode == 0 and rpackage.MARK in result.stdout.splitlines()
        v.detail = (f"{c['name']} {c['version']} loads its workspace DLL and registered Fortran routine"
                    if v.responds else "R package native-load/version/symbol verification failed")
    except subprocess.TimeoutExpired:
        v.probe_timed_out = True
        v.detail = "R package import timed out"
    except (ValueError, KeyError, TypeError, AttributeError, OSError) as e:
        v.detail = f"invalid/unavailable R package installation: {e}"
    return v


def _check_julia_package(v, contract, cfg, timeout, env):
    from . import jpackage
    v.kind = "Julia package"
    v.needs_binary = True
    try:
        c = jpackage.validate(contract)
        root = Path(cfg.root).resolve()
        project, depot, runtime = [jpackage.scoped(root / c[k],root,root)
                                    for k in ("project","depot","runtime")]
        v.present = (project / "Project.toml").is_file() and runtime.is_file() and depot.is_dir()
        if not v.present:
            v.detail = "Julia project, workspace depot or runtime missing"
            return v
        v.probe_command = [str(runtime), *jpackage.args(project,depot,c)]
        clean_env = {k: val for k, val in (env or os.environ).items()
                     if not any(secret in k.upper() for secret in
                                ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL"))}
        clean_env.update(jpackage.startup_env(depot))
        with tempfile.TemporaryDirectory(prefix="kiss-julia-package-probe-") as empty:
            result = subprocess.run(v.probe_command,cwd=empty,env=clean_env,
                                    stdin=subprocess.DEVNULL,capture_output=True,
                                    text=True,timeout=jpackage.IMPORT_TIMEOUT_SECONDS)
        v.probe_output = (result.stdout+result.stderr)[-12000:]
        v.probe_returncode = result.returncode
        lines=result.stdout.splitlines()
        if result.returncode == 0 and jpackage.MARK in lines:
            index=lines.index(jpackage.MARK)
            module=jpackage.scoped(lines[index+1],root,root)
            if depot not in module.parents or not module.is_file():
                raise ValueError("Julia module file outside workspace depot or absent")
            v.binary=str(module)
            v.shaped=v.linked=v.responds=True
        v.detail=(f"{c['name']} {c['version']} loads from workspace with verified UUID and bindings"
                  if v.responds else "Julia package load/version/UUID verification failed")
    except subprocess.TimeoutExpired:
        v.probe_timed_out=True
        v.detail="Julia package import timed out"
    except (ValueError,KeyError,TypeError,AttributeError,OSError,IndexError) as e:
        v.detail=f"invalid/unavailable Julia package installation: {e}"
    return v


def _check_octave_package(v,contract,cfg,timeout,env):
    from . import octpackage
    v.kind="Octave toolbox (47 MARRMoT classes)"
    v.needs_binary=True
    try:
        c=octpackage.validate(contract); root=Path(cfg.root).resolve()
        runtime,source,packages=[octpackage.scoped(root/c[k],root,root)
                                for k in ("runtime","source","package_registry_root")]
        base=source/"MARRMoT/Models/Model files/MARRMoT_model.m"
        v.binary=str(base)
        v.present=runtime.is_file() and base.is_file() and (packages/"package-list").is_file()
        if not v.present:
            v.detail="Octave runtime, pinned model source or package registry missing"
            return v
        native={"Darwin":"macho","Linux":"elf","Windows":"pe"}.get(platform.system())
        if _file_kind(runtime)!=native:
            v.detail="Octave runtime is not a native executable for this platform"
            return v
        octpackage.verify_source(source,c,root)
        clean_env={k:val for k,val in (env or os.environ).items()
                   if not any(x in k.upper() for x in ("API_KEY","TOKEN","SECRET","PASSWORD","CREDENTIAL"))}
        clean_env.pop("OCTAVE_PATH",None)
        clean_env.update(OCTAVE_HOME=str(runtime.parent.parent),
                         OCTAVE_EXEC_HOME=str(runtime.parent.parent),
                         OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1")
        with tempfile.TemporaryDirectory(prefix="kiss-octave-probe-",dir=root) as empty:
            script=Path(empty)/"load_toolbox.m"; script.write_text(octpackage.PROBE)
            v.probe_command=[str(runtime),*octpackage.probe_args(script,source,packages,c)]
            result=subprocess.run(v.probe_command,cwd=empty,env=clean_env,stdin=subprocess.DEVNULL,
                                  capture_output=True,text=True,timeout=min(timeout,25))
        v.probe_output=result.stdout[-16000:]+result.stderr[-2000:]
        v.probe_returncode=result.returncode
        lines=result.stdout.splitlines()
        if result.returncode==0 and octpackage.MARK in lines:
            records=[line.split(" ",2) for line in lines if line.startswith("CLASS_OK ")]
            if len(records)!=47 or len({x[1] for x in records})!=47:
                raise ValueError("incomplete/duplicate Octave class receipt")
            for _,name,path in records:
                if name not in c["classes"]:
                    raise ValueError("unexpected Octave model class")
                actual=octpackage.scoped(path,root,root)
                expected=(source/"MARRMoT/Models/Model files"/(name+".m")).resolve()
                if actual!=expected:
                    raise ValueError("Octave class loaded from wrong source")
            natives=[line[len("NATIVE_OK "):] for line in lines if line.startswith("NATIVE_OK ")]
            if len(natives)!=1:
                raise ValueError("missing native optim module receipt")
            module=octpackage.scoped(natives[0],root,root)
            if packages not in module.parents or _file_kind(module)!=native:
                raise ValueError("optim module is not native or outside workspace package directory")
            v.shaped=v.linked=v.responds=True
        v.detail=("47 pinned MARRMoT model classes and native optim module load from workspace; no model execution"
                  if v.responds else "Octave toolbox/native optim package load verification failed")
    except subprocess.TimeoutExpired:
        v.probe_timed_out=True; v.detail="Octave toolbox load timed out"
    except (ValueError,KeyError,TypeError,AttributeError,OSError,UnicodeError,IndexError) as e:
        v.detail=f"invalid/unavailable Octave toolbox installation: {e}"
    return v


def check(ki, man=None, cfg=None, harvested: dict | None = None,
          timeout: int = 25, python: str | None = None) -> Verdict:
    """Run the four tests and return a verdict the agent can act on."""
    v = Verdict(model=getattr(ki, "name", str(ki)))
    py = python or (getattr(cfg, "python", None) if cfg else None)
    if not py or getattr(sys, "frozen", False):
        from .install import runtime_python
        py = runtime_python(py)

    # Imports first: they are cheap, they are what 56 of the 127 KIs are made
    # of, and a missing module explains a binary failure more often than the
    # other way round.
    mods = declared_imports(ki)
    if getattr(man, "python_script", None) is not None:
        # These six bundled contracts list importable distribution names.
        # Their preflight extraction is incomplete (HEC_HMS yields no imports).
        for dep in man.python_deps:
            if not isinstance(dep, str) or not re.fullmatch(r"[A-Za-z_]\w*", dep):
                v.imports_ok = False
                v.detail = "Invalid dependency module in bundled Python contract"
                return v
            if dep not in mods:
                mods.append(dep)
    package_module = _package_module(man)
    if package_module and package_module not in mods:
        mods.append(package_module)
    py = select_python(cfg, py, mods, getattr(ki, "root", None))
    v.python = py
    from .paths import with_ki_tools_common
    probe_env = with_ki_tools_common(cfg) if cfg is not None else None
    if mods:
        v.missing = missing_imports(mods, py, getattr(ki, "root", None), env=probe_env)
        v.imports_ok = not v.missing

    script_contract = getattr(man, "python_script", None)
    if script_contract is not None:
        from . import python_script
        return python_script.check(v, ki, script_contract, cfg, py, probe_env, timeout)

    o_contract = getattr(man, "octave_package", None)
    if o_contract is not None:
        return _check_octave_package(v,o_contract,cfg,timeout,probe_env)

    j_contract = getattr(man, "julia_package", None)
    if j_contract is not None:
        return _check_julia_package(v, j_contract, cfg, timeout, probe_env)

    r_contract = getattr(man, "r_package", None)
    if r_contract is not None:
        return _check_r_package(v, r_contract, man, cfg, timeout, probe_env)

    lang = str((getattr(ki, "meta", None) or {}).get("language") or "").lower()
    b = find_binary(ki, man, cfg, harvested)
    # A pip-delivered Python model is the imported package. ``produces`` in
    # older manifests often names that module, not a filesystem executable;
    # turning it into <binaries>/<model>/<module> caused a false red after a
    # completely successful install (COSIPY is the real case).
    python_package = bool(package_module) and (
        lang == "python" or (
            not lang and str(getattr(man, "binary_type", "")).lower() == "python"))
    v.needs_binary = (not python_package and
                      (b is not None or bool(declared(ki)) or lang in COMPILED))

    if not v.needs_binary and not mods:
        # SUMMA's preflight declares no file and no import. Passing it because
        # nothing failed would be a vacuous green: the check that examines
        # nothing always succeeds. Absence of a test is not evidence of health.
        v.kind = "unknown"
        v.imports_ok = False
        v.detail = ("the KI declares nothing to run — no executable and no "
                    "imports to check, so its state cannot be established")
        v.missing = []
        return v

    if not v.needs_binary:
        # Nothing executable is claimed; the imports were the whole contract.
        v.kind = "python package"
        v.detail = (f"{len(mods)} declared imports resolve" if v.imports_ok
                    else f"missing: {', '.join(v.missing[:4])}")
        return v

    if b is None and lang in COMPILED and not declared(ki):
        v.kind = "unknown"
        v.imports_ok = False
        v.detail = (f"a {lang} model must have a binary, but the KI declares "
                    f"none — nothing to verify")
        return v
    if not v.imports_ok:
        v.kind = v.kind or "python package"
        v.detail = f"missing: {', '.join(v.missing[:4])}"
        return v
    if b is None:
        # "Declares nothing" and "declares something we cannot resolve here"
        # are different problems with different fixes; saying the first when
        # the second is true sends the user looking for a defect in the KI.
        d = declared(ki)
        v.detail = (f"declared at {d[0]} — no install on this machine "
                    f"(run: kiss init {v.model})") if d else "the KI declares no executable"
        return v
    v.binary = str(b)
    if not b.is_file():
        # Several Python KIs point check_file at a package directory rather
        # than an executable — WOFOST names .../pcse, which is not a file
        # anywhere and imports perfectly from site-packages. The declaration is
        # about the package, so answer the question the package can answer.
        if lang == "python" and not missing_imports([b.name], py):
            v.present = v.shaped = v.linked = v.responds = True
            v.kind = "python package"
            v.detail = f"{b.name} imports (installed as a package, not a file)"
            return v
        v.detail = f"nothing at {b}"
        return v
    v.present = True
    v.kind = _file_kind(b)

    if v.kind == "script" and str(getattr(man, "binary_type", "")).strip().lower() in {"mach-o", "macho", "elf", "pe"}:
        v.detail = "The manifest requires a native executable; a setup script cannot prove that product is installed."
        return v

    if v.kind == "script" and lang in COMPILED and _ki_script(b, ki):
        v.detail = (f"a {lang} model requires its installed engine; {b} is a KI "
                    "helper script, whose help output does not verify the engine. "
                    "Declare the actual upstream executable or verify an explicitly "
                    "supported installed package entry point.")
        return v

    argv0: list[str]
    native = {"Linux": "elf", "Darwin": "macho", "Windows": "pe"}.get(platform.system(), "elf")
    if v.kind == "script":
        interp = _interpreter(b, py)
        if interp is None:
            v.detail = f"no interpreter for {b.suffix or 'this script'} on this machine"
            return v
        v.shaped, argv0 = True, interp + [str(b)]
    elif v.kind == "pe" and platform.system() != "Windows":
        if not shutil.which("wine"):
            v.detail = "Windows binary and wine is not installed"
            return v
        v.shaped, argv0 = True, ["wine", str(b)]
    elif v.kind in ("elf", "macho", "pe"):
        if v.kind != native:
            v.detail = f"{v.kind} binary on {platform.system()} — built for another platform"
            return v
        if not os.access(b, os.X_OK):
            v.detail = f"not executable — chmod +x {b}"
            return v
        v.shaped, argv0 = True, [str(b)]
    else:
        v.detail = f"not an executable ({v.kind})"
        return v

    # For a compiled binary ldd is authoritative: if the loader cannot resolve a
    # library, the program will not start, full stop. For a script it is only a
    # hint — models routinely extend sys.path at import time (AquaCrop pulls
    # compute_eto_penman_monteith from tools/s3_weather_prep/), so a static scan
    # reports absences that do not exist at run time. There, running it is the
    # ground truth and the scan is kept back to explain a failure.
    scan: list[str] = []
    if v.kind in ("elf", "macho"):
        v.missing = _missing_libs(b)
        v.linked = not v.missing
        if not v.linked:
            return v
    else:
        v.linked = True
        if b.suffix == ".py":
            scan = _missing_imports(b, py, env=probe_env)

    rc = None
    strict_version = {"PISM": ("-version", r"(?m)^PISM \(2\.3\.0(?:-|\))"),
                      "BIOME_BGC": ("-V", r"(?m)^BiomeBGC version 4\.2 \("),
                      "PHREEQC": ("--version", r"\bPHREEQC-3\.8\.6\b")}.get(v.model)
    for flag in ((strict_version[0],) if strict_version else PROBE_FLAGS):
        argv = argv0 + ([flag] if flag else [])
        v.probe_command = argv
        try:
            # Several models ignore help/version flags and read a default namelist.
            # Do not let an installation probe pick up a bundled scientific case.
            with tempfile.TemporaryDirectory(prefix="geoforge-startup-") as probe_dir:
                from .native_probe import stage_runtime_assets
                contract = getattr(man, "native_probe", None)
                if contract is not None and v.kind not in ("elf", "macho", "pe"):
                    raise ValueError("runtime assets require an actual native executable")
                v.probe_runtime_assets = stage_runtime_assets(
                    contract, getattr(cfg, "root", Path(probe_dir)), Path(probe_dir), v.model)
                # PHREEQC's version-only branch must not create model output.
                # Inspect before TemporaryDirectory cleanup, including on timeout.
                before_paths = ({p.relative_to(probe_dir).as_posix()
                                 for p in Path(probe_dir).rglob("*")}
                                if v.model == "PHREEQC" else set())
                try:
                    if argv and argv[0] == "wine":
                        # A Windows console program under WINE can block for
                        # ever when its stdout is a pipe (Intel Fortran's
                        # CONOUT$ handling — EPIC 1102). Give it real files
                        # and read them back; the verdict is unchanged.
                        with open(Path(probe_dir) / ".probe.out", "w+", encoding="utf-8",
                                  errors="replace") as fo, \
                             open(Path(probe_dir) / ".probe.err", "w+", encoding="utf-8",
                                  errors="replace") as fe:
                            r = subprocess.run(argv, stdout=fo, stderr=fe, timeout=timeout,
                                               cwd=probe_dir, stdin=subprocess.DEVNULL,
                                               env=_sidecar_lib_env(b, probe_env))
                            fo.seek(0); fe.seek(0)
                            r = subprocess.CompletedProcess(argv, r.returncode,
                                                            fo.read(), fe.read())
                        for f in (".probe.out", ".probe.err"):
                            (Path(probe_dir) / f).unlink(missing_ok=True)
                    else:
                        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                           errors="replace", cwd=probe_dir, stdin=subprocess.DEVNULL,
                                           env=_sidecar_lib_env(b, probe_env))
                finally:
                    if v.model == "PHREEQC":
                        v.probe_created_paths = sorted(
                            {p.relative_to(probe_dir).as_posix()
                             for p in Path(probe_dir).rglob("*")} - before_paths)
        except subprocess.TimeoutExpired as exc:
            v.probe_timed_out = True
            chunks = [part.decode("utf-8", errors="replace") if isinstance(part, bytes) else (part or "")
                      for part in (exc.stdout, exc.stderr)]
            v.probe_output = "\n".join(chunks)[-8000:]
            # An input-prompt loop (or an unintended calculation) can keep a
            # process alive indefinitely. Neither establishes startup readiness.
            v.responds = False
            v.detail = f"Startup probe timed out after {timeout}s ({flag or 'no arguments'})"
            return v
        except (OSError, ValueError) as e:
            v.linked = False
            v.detail = f"could not execute: {e}"
            return v
        rc, out = r.returncode, (r.stdout + r.stderr).strip()
        v.probe_returncode = rc
        v.probe_output = out[-8000:]
        if strict_version:
            if v.model == "PHREEQC" and v.probe_created_paths:
                v.responds = False
                v.detail = "PHREEQC version probe created unexpected files or directories"
                return v
            v.responds = rc == 0 and bool(re.search(strict_version[1], out))
            v.detail = (v.model + " native version verified" if v.responds
                        else "Native version probe failed or reported a different model/version")
            return v
        from .native_probe import telemac_case_boundary
        if telemac_case_boundary(v.model, out, rc, v.probe_runtime_assets):
            v.responds = True
            v.detail = "TELEMAC2D 9.1 loads its verified dictionary and reaches missing scientific steering T2DCAS"
            return v
        from .native_probe import ctsm_case_boundary
        if v.kind in ("elf", "macho") and cfg is not None and ctsm_case_boundary(v.model, b, cfg.root, out, rc):
            v.responds = True
            v.detail = f"Native {v.model} loads its libraries and reaches drv_in case namelist in the SHA-verified CMEPS driver"
            return v
        gap = _runtime_gap(out) if rc != 0 else ""
        if gap:
            v.linked = False
            v.missing = scan or [gap]
            v.detail = f"{gap} — {out.splitlines()[0].strip()[:120]}" if out else gap
            return v
        if _ran(rc):
            v.responds = True
            if rc < 0:
                v.detail = f"ran and crashed on probe (signal {-rc}) — loads and executes"
            else:
                v.detail = (out.splitlines() or [f"exit {rc}, no output"])[0].strip()[:160]
            return v
    v.detail = f"exit {rc}"
    return v


def check_all(kis, **kw) -> list[Verdict]:
    return [check(ki, **kw) for ki in kis]


# ---------------------------------------------------------------- caching

def cache_path(workroot: Path, ki_name: str) -> Path:
    return Path(workroot) / ki_name.lower() / "runnable.json"


def load(workroot: Path, ki_name: str, max_age: float = 86400.0) -> dict | None:
    """A recent verdict, or None. Probing 127 models takes minutes; a page
    load must not do it. Verdicts go stale when the machine changes, so they
    expire rather than persisting as a claim about a machine that has moved on.
    """
    import json
    import time
    p = cache_path(workroot, ki_name)
    try:
        if time.time() - p.stat().st_mtime > max_age:
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(workroot: Path, v: Verdict) -> None:
    import json
    import time
    p = cache_path(workroot, v.model)
    p.parent.mkdir(parents=True, exist_ok=True)
    d = v.as_dict()
    d["checked_at"] = time.time()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(p)
