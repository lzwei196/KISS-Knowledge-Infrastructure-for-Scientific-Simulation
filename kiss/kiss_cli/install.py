"""Acquisition: get the model executable onto this machine.

Design rule: **never claim success we did not observe.** Every step returns what
actually happened. When a step cannot be automated, the installer says so and
records enough context for an agent to finish the job — it does not silently
substitute an approximation. That rule is inherited from the KI SKILL.md
mandatory execution policy, and it is the whole point of the project.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .manifest import Manifest


@dataclass
class Step:
    name: str
    ok: bool
    detail: str = ""
    #: commands actually executed, for reproducibility and for the agent handoff
    commands: list[str] = field(default_factory=list)

    @property
    def mark(self) -> str:
        return "ok" if self.ok else "FAILED"


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


def _run(cmd: list[str] | str, cwd: Path | None = None, timeout: int = 1800) -> tuple[int, str]:
    """Run a command, returning (rc, combined output). Never raises on failure."""
    shell = isinstance(cmd, str)
    try:
        p = subprocess.run(
            cmd, cwd=cwd, shell=shell, timeout=timeout,
            capture_output=True, text=True, errors="replace",
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
            urllib.request.urlretrieve(a.url, dest)
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
        return Step("acquire[build]", False,
                    f"build reported success but {a.produces} is absent", commands=cmds), None
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


def ensure_python_env(cfg, base_python: str | None = None) -> Step:
    """Guarantee an interpreter that survives relocation.

    The ``python_env`` role is itself a relocated path: the KIs expect an
    interpreter at ``<server_root>/python_env`` and ``kiss`` binds the user's
    ``python_env`` directory there. So the interpreter kiss *runs with* must
    live inside that role, not outside it — otherwise the role bind replaces
    the directory the interpreter came from and the sandbox reports an opaque
    ``execvp ...: No such file or directory``.

    Creating the venv at ``cfg.roles['python_env']`` makes the two agree: the
    KI's hardcoded ``.../python_env/bin/python`` resolves to exactly the
    interpreter that was used to install its dependencies.
    """
    import venv as _venv

    target = Path(cfg.roles["python_env"])
    interpreter = target / "bin" / "python"
    if interpreter.exists():
        cfg.python = str(interpreter)
        return Step("python-env", True, f"using {interpreter}")

    try:
        target.mkdir(parents=True, exist_ok=True)
        _venv.EnvBuilder(with_pip=True, symlinks=True).create(target)
    except Exception as e:
        return Step("python-env", False, f"could not create venv at {target}: {e}")

    if not interpreter.exists():
        return Step("python-env", False, f"venv created but no interpreter at {interpreter}")
    cfg.python = str(interpreter)
    return Step("python-env", True, f"created {interpreter}")


def install_ki_tools_common(cfg, repo_root: Path) -> Step:
    """Install the shared helper library the KIs import.

    126 of the 127 packages do ``from ki_tools_common.<mod> import ...``. Without
    it every one of their tools raises ImportError the moment it is called — and
    crucially *after* preflight has already reported success, because preflight
    checks the model binary rather than the KI's own Python helpers. A green
    preflight followed by an ImportError is exactly the kind of late, confusing
    failure this installer exists to prevent, so it is installed up front.
    """
    src = Path(repo_root) / "ki_tools_common"
    if not src.is_dir():
        return Step("ki-tools-common", False,
                    f"not shipped in this checkout (expected {src})")

    rc, out = _run([cfg.python, "-c", "import ki_tools_common"])
    if rc == 0:
        return Step("ki-tools-common", True, "already importable")

    # Install with the [all] extra. xarray is declared *optional* in this
    # library's pyproject, but its __init__ imports climate_scenarios, which
    # imports xarray at module level — so a plain install produces a package
    # that cannot be imported at all. Measured, not guessed.
    cmd = [cfg.python, "-m", "pip", "install", "--quiet", "-e", f"{src}[all]"]
    rc, out = _run(cmd)
    if rc != 0:
        return Step("ki-tools-common", False, out.strip()[-400:], commands=[" ".join(cmd)])

    rc2, out2 = _run([cfg.python, "-c",
                      "import ki_tools_common, ki_tools_common.units; print('ok')"])
    if rc2 != 0:
        return Step("ki-tools-common", False,
                    f"pip install succeeded but import fails: {out2.strip()[-200:]}",
                    commands=[" ".join(cmd)])
    return Step("ki-tools-common", True, f"installed editable from {src}",
                commands=[" ".join(cmd)])
