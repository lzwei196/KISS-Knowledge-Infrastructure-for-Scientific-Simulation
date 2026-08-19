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

import os
import platform
import re
import shutil
import subprocess
import sys
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
    ".py": [sys.executable or "python3"],
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
                "detail": self.detail, "summary": self.summary()}


# ---------------------------------------------------------------- locating

def declared(ki) -> list[str]:
    """Executable paths the KI's own preflight names, tokens and all."""
    pre = getattr(ki, "preflight", None)
    if not pre or not Path(pre).is_file():
        return []
    text = Path(pre).read_text(encoding="utf-8", errors="replace")
    return [m.group(1) for m in
            re.finditer(r"""check_file\(\s*['"]([^'"]+)['"]""", text)]


def declared_dirs(ki) -> list[str]:
    """Directories the KI's preflight requires, from its own ``check_dir`` calls."""
    pre = getattr(ki, "preflight", None)
    if not pre or not Path(pre).is_file():
        return []
    text = Path(pre).read_text(encoding="utf-8", errors="replace")
    return [m.group(1) for m in
            re.finditer(r"""check_dir\(\s*['"]([^'"]+)['"]""", text)]


def declared_imports(ki) -> list[str]:
    """Modules the KI's preflight requires, from its own ``check_import`` calls.

    125 of the 127 KIs declare imports and 56 declare no executable at all: for
    a model shipped as a Python package, importing it *is* running it. Judging
    those on a binary they never claimed to have would paint every one of them
    red while they work perfectly.
    """
    pre = getattr(ki, "preflight", None)
    if not pre or not Path(pre).is_file():
        return []
    text = Path(pre).read_text(encoding="utf-8", errors="replace")
    seen, out = set(), []
    for m in re.finditer(r"""check_import\(\s*['"]([\w.]+)['"]""", text):
        mod = m.group(1)
        if mod not in seen:
            seen.add(mod)
            out.append(mod)
    return out


def missing_imports(mods: list[str], python: str, cwd: Path | None = None) -> list[str]:
    """Which of these modules this interpreter cannot find. One probe, not N."""
    if not mods:
        return []
    # find_spec imports parent packages, and packages print things: pysteps
    # announces its config file on stdout. Unmarked output would be read back
    # as the name of a missing module, so every answer carries a marker and
    # anything else on the stream is somebody else's noise.
    probe = ("import importlib.util as u\n"
             "for m in %r:\n"
             "    try:\n"
             "        ok = u.find_spec(m) is not None\n"
             "    except Exception:\n"
             "        ok = False\n"
             "    if not ok:\n"
             "        print('%s' + m)" % (mods, _MARK))
    try:
        r = subprocess.run([python, "-c", probe], capture_output=True, text=True,
                           timeout=180, cwd=str(cwd) if cwd else None)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln.split(_MARK, 1)[1].strip() for ln in r.stdout.splitlines()
            if _MARK in ln]


def find_binary(ki, man=None, cfg=None, harvested: dict | None = None) -> Path | None:
    """Locate the model executable from what the KI and manifest declare."""
    cands: list[Path] = []
    if man is not None and getattr(man, "acquire", None) and getattr(man.acquire, "produces", None) and cfg is not None:
        cands.append(cfg.roles["binaries"] / (man.install_dir or ki.name) / man.acquire.produces)
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


# ---------------------------------------------------------------- linkage

def _missing_libs(p: Path) -> list[str]:
    """Shared libraries the loader cannot resolve. Linux only; [] elsewhere."""
    if platform.system() != "Linux" or not shutil.which("ldd"):
        return []
    try:
        r = subprocess.run(["ldd", str(p)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln.split("=>")[0].strip() for ln in r.stdout.splitlines() if "not found" in ln]


def _missing_imports(p: Path, python: str) -> list[str]:
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
    probe = ("import sys,importlib.util as u;sys.path.insert(0,%r);"
             "print('\\n'.join(m for m in %r if u.find_spec(m) is None))"
             % (str(p.parent), mods))
    try:
        r = subprocess.run([python, "-c", probe], capture_output=True,
                           text=True, timeout=90, cwd=str(p.parent))
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]


# ---------------------------------------------------------------- execution

def _ran(rc: int) -> bool:
    """Did the process actually execute?

    A non-negative code means the program ran and chose it — including codes
    above 127, which several models use (APSIM exits 131, CAM-chem 233).
    Python reports a signal death as a *negative* code; that still proves the
    binary loaded and executed instructions, which is the question here.
    """
    return rc is not None


def check(ki, man=None, cfg=None, harvested: dict | None = None,
          timeout: int = 25, python: str | None = None) -> Verdict:
    """Run the four tests and return a verdict the agent can act on."""
    v = Verdict(model=getattr(ki, "name", str(ki)))
    py = python or (getattr(cfg, "python", None) if cfg else None) or sys.executable or "python3"

    # Imports first: they are cheap, they are what 56 of the 127 KIs are made
    # of, and a missing module explains a binary failure more often than the
    # other way round.
    mods = declared_imports(ki)
    if mods:
        v.missing = missing_imports(mods, py, getattr(ki, "root", None))
        v.imports_ok = not v.missing

    lang = str((getattr(ki, "meta", None) or {}).get("language") or "").lower()
    b = find_binary(ki, man, cfg, harvested)
    v.needs_binary = b is not None or bool(declared(ki)) or lang in COMPILED

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
            scan = _missing_imports(b, py)

    rc = None
    for flag in PROBE_FLAGS:
        argv = argv0 + ([flag] if flag else [])
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                               errors="replace", cwd=str(b.parent), stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            # A model that starts solving instead of printing help is running.
            v.responds = True
            v.detail = f"ran — still working after {timeout}s ({flag or 'no arguments'})"
            return v
        except OSError as e:
            v.detail = f"could not execute: {e}"
            return v
        rc, out = r.returncode, (r.stdout + r.stderr).strip()
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
