"""Acquisition: get the model executable onto this machine.

Design rule: **never claim success we did not observe.** Every step returns what
actually happened. When a step cannot be automated, the installer says so and
records enough context for an agent to finish the job — it does not silently
substitute an approximation. That rule is inherited from the KI SKILL.md
mandatory execution policy, and it is the whole point of the project.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from . import tls
from .manifest import Manifest


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""
    #: commands actually executed, for reproducibility and for the agent handoff
    commands: list[str] = field(default_factory=list)
    #: A prerequisite failed, so this step was deliberately not attempted.
    #: This is not success, but presenting it as an independent failure hides
    #: the real cause (for example: clone failed -> preflight missing binary).
    skipped: bool = False

    @property
    def mark(self) -> str:
        return "ok" if self.ok else "SKIPPED" if self.skipped else "FAILED"


@dataclass
class InstallResult:
    model: str
    steps: list[Step] = field(default_factory=list)
    binary: Path | None = None

    def add(self, step: Step) -> Step:
        self.steps.append(step)
        return step

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    @property
    def failures(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]


def _run(cmd: list[str] | str, cwd: Path | None = None, timeout: int = 1800,
         env: dict | None = None) -> tuple[int, str]:
    """Run a command, returning (rc, combined output). Never raises on failure."""
    shell = isinstance(cmd, str)
    try:
        p = subprocess.run(
            cmd, cwd=cwd, shell=shell, timeout=timeout,
            capture_output=True, text=True, errors="replace",
            env={**os.environ, **env} if env else None,
        )
        return p.returncode, (p.stdout + p.stderr)[-8000:]
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except FileNotFoundError as e:
        return 127, str(e)


def check_system_deps(deps: list[str]) -> Step:
    missing = [d for d in deps if shutil.which(d) is None]
    if missing:
        return Step("system-deps", False,
                    f"not on PATH: {', '.join(missing)} — install them with your package manager")
    return Step("system-deps", True, f"{len(deps)} present" if deps else "none required")


def install_python_deps(deps: list[str], python: str) -> Step:
    if not deps:
        return Step("python-deps", True, "none required")
    cmd = [python, "-m", "pip", "install", "--quiet", *deps]
    rc, out = _run(cmd)
    return Step("python-deps", rc == 0,
                f"{len(deps)} packages" if rc == 0 else out.strip()[-400:],
                commands=[" ".join(cmd)])


def acquire(man: Manifest, prefix: Path, python: str) -> tuple[Step, Path | None]:
    """Obtain the executable per the manifest's strategy."""
    a = man.acquire
    if a is None:
        return Step("acquire", False, "no acquire block in manifest"), None
    prefix.mkdir(parents=True, exist_ok=True)
    fn = {
        "pip": _acq_pip, "download": _acq_download, "build": _acq_build,
        "wine": _acq_wine, "bundled": _acq_bundled, "manual": _acq_manual,
    }[a.strategy]
    return fn(man, prefix, python)


def _acq_pip(man, prefix, python):
    pkg = man.acquire.package or man.model.lower()
    cmd = [python, "-m", "pip", "install", "--quiet", pkg]
    rc, out = _run(cmd)
    if rc != 0:
        return Step("acquire[pip]", False, out.strip()[-400:], commands=[" ".join(cmd)]), None
    mod = (man.acquire.produces or pkg).replace("-", "_")
    rc2, out2 = _run([python, "-c", f"import {mod}; print({mod}.__file__)"])
    if rc2 != 0:
        return Step("acquire[pip]", False,
                    f"installed {pkg} but `import {mod}` fails: {out2.strip()[-200:]}",
                    commands=[" ".join(cmd)]), None
    return Step("acquire[pip]", True, f"{pkg} importable as {mod}",
                commands=[" ".join(cmd)]), Path(out2.strip())


def _acq_download(man, prefix, python):
    a = man.acquire
    if not a.url:
        return Step("acquire[download]", False, "manifest has no url"), None
    dest = prefix / Path(a.url).name
    try:
        if not dest.exists():
            req = urllib.request.Request(a.url, headers={"User-Agent": "geoforge-desktop"})
            with urllib.request.urlopen(req, timeout=1800, context=tls.context()) as src, \
                    dest.open("wb") as out:
                shutil.copyfileobj(src, out)
    except Exception as e:
        return Step("acquire[download]", False, f"{a.url}: {e}"), None

    if a.sha256:
        import hashlib
        got = hashlib.sha256(dest.read_bytes()).hexdigest()
        if got != a.sha256:
            return Step("acquire[download]", False,
                        f"checksum mismatch: expected {a.sha256[:16]}… got {got[:16]}…"), None

    if dest.suffix == ".zip":
        with zipfile.ZipFile(dest) as z:
            z.extractall(prefix)
    elif ".tar" in dest.suffixes or dest.suffix in (".tgz", ".gz", ".bz2", ".xz"):
        with tarfile.open(dest) as t:
            t.extractall(prefix)

    binary = prefix / a.produces if a.produces else None
    if binary and not binary.exists():
        return Step("acquire[download]", False,
                    f"archive extracted but expected binary missing: {a.produces}"), None
    if binary:
        binary.chmod(binary.stat().st_mode | 0o111)
    return Step("acquire[download]", True, f"from {a.url}"), binary


def _acq_build(man, prefix, python):
    a = man.acquire
    if not a.repo:
        return Step("acquire[build]", False, "manifest has no repo"), None
    # Clone into the prefix itself, not a nested src/. The KI's hardcoded paths
    # were written against a checkout sitting directly at the install dir
    # (".../model/VIC-5.1.0/vic/drivers/..."), so an extra level here produces a
    # working binary that the KI's own preflight cannot find.
    src = prefix
    cmds: list[str] = []
    if not (src / ".git").exists():
        # `--branch` takes a branch or tag, never a commit. We ask agents to pin
        # the ref because an unpinned build is not reproducible, and a pinned
        # ref is usually a SHA — so the one answer we asked for was the one
        # answer clone could not take. TOPMODEL failed here on a real commit.
        is_sha = bool(a.ref) and re.fullmatch(r"[0-9a-f]{7,40}", a.ref.strip()) is not None
        if is_sha:
            sha = a.ref.strip()
            src.mkdir(parents=True, exist_ok=True)
            steps = [["git", "init", "-q", str(src)],
                     ["git", "-C", str(src), "remote", "add", "origin", a.repo],
                     ["git", "-C", str(src), "fetch", "--depth", "1", "origin", sha]]
            rc, out = 0, ""
            for c in steps:
                rc, out = _run(c)
                cmds.append(" ".join(c))
                if rc != 0:
                    break
            if rc == 0:
                rc, out = _run(["git", "-C", str(src), "checkout", "-q", "FETCH_HEAD"])
                cmds.append(f"git -C {src} checkout FETCH_HEAD")
            if rc != 0:
                # Some servers refuse to serve an arbitrary SHA to a shallow
                # fetch. Falling back to a full clone costs time, not accuracy.
                rc, out = _run(["git", "-C", str(src), "fetch", "origin"], timeout=1800)
                cmds.append(f"git -C {src} fetch origin")
                if rc == 0:
                    rc, out = _run(["git", "-C", str(src), "checkout", "-q", sha])
                    cmds.append(f"git -C {src} checkout {sha}")
        else:
            clone = ["git", "clone", "--depth", "1"]
            if a.ref:
                clone += ["--branch", a.ref]
            clone += [a.repo, str(src)]
            rc, out = _run(clone)
            cmds.append(" ".join(clone))
        if rc != 0:
            return Step("acquire[build]", False, f"clone failed: {out.strip()[-400:]}",
                        commands=cmds), None

    for c in a.commands:
        rc, out = _run(c, cwd=src)
        cmds.append(c)
        if rc != 0:
            return Step("acquire[build]", False,
                        f"`{c}` failed (rc={rc}):\n{out.strip()[-1500:]}", commands=cmds), None

    binary = src / a.produces if a.produces else None
    if binary and not binary.exists():
        # The build succeeded and the binary exists — just not at the path the
        # manifest predicted. Build evidence describes upstream's own layout
        # (KDT checks out into source/repo/), while we clone into the prefix
        # itself, so a correct manifest can still name source/repo/run_bmi for
        # a file that landed at run_bmi. We know where we cloned, so find what
        # was actually built instead of failing a working build over a prefix.
        want = Path(a.produces).name
        hits = [f for f in src.rglob(want)
                if f.is_file() and os.access(f, os.X_OK) and ".git" not in f.parts]
        if len(hits) == 1:
            binary = hits[0]
            cmds.append(f"# produces corrected: {a.produces} -> "
                        f"{binary.relative_to(src)}")

        else:
            found = f"; {len(hits)} candidates named {want}" if hits else ""
            return Step("acquire[build]", False,
                        f"build reported success but {a.produces} is absent{found}",
                        commands=cmds), None
    if binary:
        binary.chmod(binary.stat().st_mode | 0o111)
    return Step("acquire[build]", True, f"built from {a.repo}@{a.ref or 'HEAD'}",
                commands=cmds), binary


def _acq_wine(man, prefix, python):
    if shutil.which("wine") is None:
        return Step("acquire[wine]", False,
                    "wine is not installed — required to run this model's Windows binary"), None
    a = man.acquire
    exe = Path(a.exe) if a.exe else None
    if exe and not exe.is_absolute():
        exe = prefix / exe
    if exe and not exe.exists():
        return Step("acquire[wine]", False, f"Windows executable not found: {exe}"), None
    return Step("acquire[wine]", True, f"wine present; exe at {exe}"), exe


def _acq_bundled(man, prefix, python):
    p = Path(man.acquire.produces or "")
    return (Step("acquire[bundled]", p.exists(),
                 f"shipped in the KI: {p}" if p.exists() else f"expected bundled file missing: {p}"),
            p if p.exists() else None)


def _acq_manual(man, prefix, python):
    return Step("acquire[manual]", False,
                man.agent_hint or "this model must be obtained by hand — see SKILL.md"), None


def place_where_the_ki_expects(ki, binary: Path | None, cfg,
                               install_prefix: Path | None = None) -> list[str]:
    """Make the KI's declared binary path true.

    preflight_check.py hardcodes where the binary lives, and that declaration
    is the contract every consumer reads — including our own verifier. It was
    written against the dissection toolkit's layout, so TOPMODEL's preflight
    looks for source/repo/run_bmi while our build produces run_bmi at the
    checkout root. Both are legitimate; they just disagree.

    Rather than rewrite 127 KIs or fail a working build, link the binary into
    the place the KI names. One real file, every declared path true.
    """
    from . import runnable

    notes: list[str] = []

    def resolve(decl: str) -> Path | None:
        if decl.startswith("KISSPATH_"):
            if cfg is None:
                return None
            try:
                from .port import unsubstitute
                decl = unsubstitute(decl, cfg)[0]
            except Exception:
                return None
        p = Path(decl)
        return p if p.is_absolute() else None

    # Some source-built models expect the whole checkout under KISSPATH_HOME
    # while manifests correctly install software under the binaries role.
    # When the declared executable and built executable have the same suffix,
    # link the expected checkout root to the real install prefix. Linking only
    # the executable made DSSAT find dscsm048 but miss its adjacent Data tree.
    if binary and install_prefix:
        prefix = Path(install_prefix)
        try:
            rel_binary = Path(binary).relative_to(prefix)
        except ValueError:
            rel_binary = None
        if rel_binary and rel_binary.parts:
            for decl in runnable.declared(ki):
                want = resolve(decl)
                if want is None or len(want.parts) < len(rel_binary.parts):
                    continue
                if tuple(want.parts[-len(rel_binary.parts):]) != rel_binary.parts:
                    continue
                declared_root = want
                for _ in rel_binary.parts:
                    declared_root = declared_root.parent
                if declared_root == prefix or declared_root.exists():
                    continue
                try:
                    declared_root.parent.mkdir(parents=True, exist_ok=True)
                    declared_root.symlink_to(prefix, target_is_directory=True)
                    notes.append(f"linked install tree {declared_root} -> {prefix}")
                except OSError as e:
                    notes.append(f"could not link install tree at {declared_root}: {e}")
                break

    # The KI ships tools/ and declares it at KISSPATH_KI_ROOT/<name>/
    # knowledge_infrastructure/tools, while materialisation puts the package at
    # ki/. Ten of the KIs disagree about that middle segment among themselves,
    # so rather than encode a layout, link what the package actually contains
    # to wherever it says the directory lives.
    ki_root = Path(getattr(ki, "root", "")) if getattr(ki, "root", None) else None
    for decl in runnable.declared_dirs(ki):
        want = resolve(decl)
        if want is None or want.exists() or ki_root is None:
            continue
        have = ki_root / want.name
        if not have.is_dir():
            continue
        try:
            want.parent.mkdir(parents=True, exist_ok=True)
            want.symlink_to(have, target_is_directory=True)
            notes.append(f"linked {want} -> {have}")
        except OSError as e:
            notes.append(f"could not place {want.name}/ at {want}: {e}")

    if not binary or not binary.is_file():
        return notes
    for decl in runnable.declared(ki):
        want = resolve(decl)
        if want is None or want.exists():
            continue
        if want.name != binary.name:
            continue                    # a different artefact, not this binary
        try:
            want.parent.mkdir(parents=True, exist_ok=True)
            want.symlink_to(binary)
            notes.append(f"linked {want} -> {binary}")
        except OSError:
            try:
                shutil.copy2(binary, want)
                notes.append(f"copied {binary} -> {want}")
            except OSError as e:
                notes.append(f"could not place binary at {want}: {e}")
    return notes


def run_preflight(ki, python: str, cfg=None) -> Step:
    """Run the KI's own preflight_check.py, inside the sandbox when configured."""
    if not ki.preflight:
        return Step("preflight", False, "this KI ships no preflight_check.py")
    argv = [python, str(ki.preflight)]
    if cfg is not None and cfg.relocation == "sandbox":
        from .paths import have_sandbox, sandbox_command
        if have_sandbox():
            argv = sandbox_command(cfg, argv, cwd=ki.root)
    rc, out = _run(argv, cwd=ki.root, timeout=600)
    tail = "\n".join(out.strip().splitlines()[-25:])
    return Step("preflight", rc == 0, tail, commands=[" ".join(argv)])


def check_data(man: Manifest, cfg) -> Step:
    """Report which required datasets are present. Never downloads silently."""
    if not man.data:
        return Step("data", True, "manifest declares no external data")
    missing = []
    for need in man.data:
        base = cfg.roles.get(need.role)
        if base is None:
            missing.append(f"{need.name} (no '{need.role}' path configured)")
            continue
        probe = base / need.probe if need.probe else base
        if not probe.exists() and not need.optional:
            missing.append(f"{need.name} — expected at {probe}")
    if missing:
        return Step("data", False, "not present:\n  - " + "\n  - ".join(missing))
    return Step("data", True, f"{len(man.data)} dataset(s) present")


def find_base_python() -> str | None:
    """A real Python interpreter to build venvs from.

    Inside a PyInstaller app sys.executable is the app binary itself — asking
    the venv module to build an environment from that symlinks venv/bin/python
    at the KISS executable, and every later `pip install` detonates into a wall
    of errors. That is exactly what the first Mac install attempt produced.
    A frozen app must therefore find a real interpreter on the system.
    """
    import shutil
    import sys

    if os.environ.get("KISS_PYTHON"):
        return os.environ["KISS_PYTHON"]
    if not getattr(sys, "frozen", False):
        return sys.executable
    for name in ("python3.12", "python3.11", "python3.13", "python3.10", "python3"):
        found = shutil.which(name)
        if found:
            rc, out = _run([found, "-c", "import venv, pip; print('ok')"])
            if rc == 0 and "ok" in out:
                return found
    return None


def runtime_python(configured: str | None = None) -> str:
    """Return a real interpreter for preflight and other child scripts.

    In source mode ``sys.executable`` is correct. In a frozen app it is the
    GeoForge bootloader, which accepts KISS subcommands rather than Python
    files. Old ``kiss.toml`` files may already contain that launcher path, so
    repair both new defaults and persisted values at the point of use.
    """
    import shutil
    import sys

    if configured:
        resolved = shutil.which(configured) or configured
        try:
            candidate = Path(resolved).resolve()
            current = Path(sys.executable).resolve()
            app_launcher = (".app/Contents/MacOS/" in candidate.as_posix()
                            and candidate.name.lower() in {"geoforge desktop", "kiss"})
            is_launcher = (getattr(sys, "frozen", False)
                           and (candidate == current or app_launcher))
        except OSError:
            is_launcher = False
        if not is_launcher and (shutil.which(configured) or Path(configured).is_file()):
            return configured
    return find_base_python() or "python3"


def ensure_python_env(cfg, base_python: str | None = None) -> Step:
    """Guarantee an interpreter that survives relocation.

    The venv is created at cfg.roles['python_env'] so the KI's hardcoded
    interpreter path resolves to the same environment its dependencies were
    installed into. See find_base_python for why the frozen app must not use
    sys.executable as the base.
    """
    import subprocess as _sp

    target = Path(cfg.roles["python_env"])
    interpreter = target / "bin" / "python"
    if interpreter.exists():
        rc, _ = _run([str(interpreter), "-c", "import sys; print(sys.version)"])
        if rc == 0:
            cfg.python = str(interpreter)
            return Step("python-env", True, f"using {interpreter}")
        # A venv built from a frozen binary in an earlier version: unusable.
        import shutil as _sh
        _sh.rmtree(target, ignore_errors=True)

    base = base_python or find_base_python()
    if base is None:
        return Step(
            "python-env", False,
            "No Python 3 found on this machine, and the app cannot conjure one "
            "from inside itself. One-time fix, then press Install again:\n"
            "    macOS:  brew install python  (or: xcode-select --install)\n"
            "    Linux:  sudo apt install python3-venv python3-pip")

    target.parent.mkdir(parents=True, exist_ok=True)
    rc, out = _run([base, "-m", "venv", str(target)], timeout=300)
    if rc != 0 or not interpreter.exists():
        return Step("python-env", False,
                    f"could not create a venv with {base}: {out.strip()[-300:]}")
    cfg.python = str(interpreter)
    return Step("python-env", True, f"created {interpreter} (from {base})")


def install_ki_tools_common(cfg, repo_root: Path) -> Step:
    """Install the shared helper library the KIs import.

    (Restored: an earlier edit that rewrote ensure_python_env sliced off the
    tail of this module and deleted this function, so every install crashed at
    step 3 with AttributeError — found by walking the app as a user, not by
    reading the diff. 126 of the 127 packages import this library.)

    The library is materialised into the workdir first: the repo copy carries
    KISSPATH_* placeholders, and installing it verbatim leaves defaults like
    load_forcing's CMFD_DIR pointing at a token. The install then verifies the
    import resolves to the copy we just installed, not a stale global one.
    """
    src = Path(repo_root) / "ki_tools_common"
    if not src.is_dir():
        return Step("ki-tools-common", False,
                    f"not shipped in this checkout (expected {src})")

    from . import port as _port

    live = Path(cfg.roles.get("ki_tools_common") or (cfg.root / "ki_tools_common"))
    mrep = _port.materialise(src, live, cfg)
    if mrep.unresolved:
        return Step("ki-tools-common", False,
                    f"unresolved roles in ki_tools_common: "
                    f"{', '.join(sorted(mrep.unresolved))}")
    src = live

    cmds: list[str] = []
    for spec in (f"{src}[all]", str(src)):
        cmd = [cfg.python, "-m", "pip", "install", "--quiet", "-e", spec]
        cmds.append(" ".join(cmd))
        rc, out = _run(cmd, timeout=900)
        if rc == 0:
            break
    else:
        return Step("ki-tools-common", False, out.strip()[-400:], commands=cmds)

    # Identify the copy by __path__, not __file__. An editable install is
    # reached through a finder that yields a package whose __file__ is None
    # while the package works perfectly; reading __file__ reported "resolves to
    # None" on a healthy install and told the user MODFLOW6 was unfinished when
    # it was already running.
    # Ask from a neutral directory. Python puts the working directory first on
    # sys.path for -c, and this repo has a bare ki_tools_common/ at its root, so
    # probing from the checkout found that directory instead of the installed
    # copy and failed a correct install. PYTHONSAFEPATH is the 3.11+ belt to
    # that braces, and is ignored harmlessly by older interpreters.
    import tempfile
    rc2, out2 = _run([cfg.python, "-c",
                      "import ki_tools_common as k, ki_tools_common.units\n"
                      "print('|'.join(list(getattr(k, '__path__', None) or [])"
                      " or [k.__file__ or '']))"],
                     cwd=Path(tempfile.gettempdir()),
                     env={"PYTHONSAFEPATH": "1"})
    if rc2 != 0:
        return Step("ki-tools-common", False,
                    f"pip install succeeded but import fails: {out2.strip()[-200:]}",
                    commands=cmds)
    where = [w for w in out2.strip().splitlines()[-1].split("|") if w]
    target = str(live.resolve())
    if not any(target in str(Path(w).resolve()) for w in where):
        return Step("ki-tools-common", False,
                    f"import resolves to {', '.join(where) or 'nowhere'}, not the copy "
                    f"installed at {live} — remove the other ki_tools_common "
                    f"from this interpreter")
    extras = "with extras" if len(cmds) == 1 else "bare (extras unavailable)"
    return Step("ki-tools-common", True, f"installed editable from {src}, {extras}",
                commands=cmds)
