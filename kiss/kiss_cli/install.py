"""Acquisition: get the model executable onto this machine.

Design rule: **never claim success we did not observe.** Every step returns what
actually happened. When a step cannot be automated, the installer says so and
records enough context for an agent to finish the job — it does not silently
substitute an approximation. That rule is inherited from the KI SKILL.md
mandatory execution policy, and it is the whole point of the project.
"""

from __future__ import annotations

import os
import contextlib
import contextvars
import copy
import hashlib
import json
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import tls
from .manifest import Manifest


_IMPORT_PATH_MARKER = "__GEOFORGE_IMPORT_PATH__="
_CANCELLATION = contextvars.ContextVar("installation_cancellation", default=None)


class InstallStopped(RuntimeError):
    """The owning chat stopped this installation; no subsequent step may run."""

    output: str = ""


@contextlib.contextmanager
def cancellation_context(project=None, *, stop=None, turn_id=None):
    if project is not None and turn_id is None:
        from . import execution
        inherited = execution.turn_environment(project)
        if execution.stop_requested(project, env=inherited):
            raise InstallStopped("Stopped by the user; installation was interrupted.")
        turn_id = inherited.get(execution.TURN_ID_ENV)
    token = _CANCELLATION.set((project, stop, turn_id))
    try:
        check_cancelled()
        yield
    finally:
        _CANCELLATION.reset(token)


def check_cancelled():
    context = _CANCELLATION.get()
    if context is not None:
        from . import execution
        project, stop, turn_id = context
        if ((stop is not None and stop()) or
                (project is not None and execution.stop_requested(project, turn_id=turn_id))):
            raise InstallStopped("Stopped by the user; installation was interrupted.")


def _marked_import_path(output: str) -> Path | None:
    """Extract our package path without treating import chatter as a filename.

    Some scientific packages print warnings, banners, or plugin diagnostics to
    stdout while they are imported.  The old probe passed that entire combined
    stream to ``Path``, which could turn a successful installation into
    ``ENAMETOOLONG``.  A marker also remains reliable if an ``atexit`` handler
    prints after our probe line.
    """
    if _IMPORT_PATH_MARKER not in output:
        return None
    value = output.rpartition(_IMPORT_PATH_MARKER)[2].splitlines()[0].strip()
    return Path(value) if value else None


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
    #: Host observations, never an agent's assertion of scientific success.
    evidence: dict = field(default_factory=dict)

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
         env: dict | None = None, *, full_output: bool = False,
         encoding: str | None = None) -> tuple[int, str]:
    """Return rc and combined output; preflight can retain the complete capture.

    Other installation callers keep their established 8,000-character tail.
    Cancellation still raises, carrying collected output for host evidence.
    """
    check_cancelled()
    from .paths import model_python_environment
    # These are model/install children, not the desktop's own CLI workers.
    # Explicit overrides include the selected KI helper path for preflight;
    # the host launcher's ambient Python paths must never reach pip/probes.
    child_env = {**model_python_environment(), **(env or {})}
    context = _CANCELLATION.get()
    if context is not None:
        from . import execution
        project, stop, turn_id = context
        # Windows: the exact command line Popen(shell=True) builds. A list would
        # go through list2cmdline, whose \" escapes cmd.exe does not understand,
        # splitting quoted manifest arguments such as CC="gcc -fcommon".
        argv = (f'{os.environ.get("COMSPEC", "cmd.exe")} /c "{cmd}"' if os.name == "nt"
                else ["/bin/sh", "-c", cmd]) if isinstance(cmd, str) else cmd
        result = execution.run_process(
            argv, cwd=cwd or Path.cwd(), env=child_env,
            timeout=timeout, project=project, stop=stop, turn_id=turn_id,
            **({"encoding": encoding} if encoding else {}))
        output = result.stdout + result.stderr + ("\n" + result.detail if result.detail else "")
        output = output if full_output else output[-8000:]
        try:
            if result.status in {"stopped", "interrupted"}:
                raise InstallStopped(result.detail or "Stopped by the user")
            check_cancelled()
        except InstallStopped as exc:
            exc.output = output
            raise
        rc = result.returncode if result.returncode is not None else (
            124 if result.status == "timed_out" else 127)
        return rc, output
    shell = isinstance(cmd, str)
    try:
        p = subprocess.run(
            cmd, cwd=cwd, shell=shell, timeout=timeout,
            capture_output=True, text=True, errors="replace",
            env=child_env, **({"encoding": encoding} if encoding else {}),
        )
        output = p.stdout + p.stderr
        return p.returncode, output if full_output else output[-8000:]
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


def needs_shared_tools(ki, man: Manifest) -> bool:
    """Only admitted first-party stdlib readers can skip scientific shared tools.

    Invalid, changed and unknown declarations keep the established install path;
    normal acquisition and runnable checks still reject invalid source contracts.
    """
    from . import python_script
    if (getattr(ki, "name", "") not in python_script.DATA_READERS or
            man.model != ki.name or man.acquire is None or
            man.acquire.strategy != "bundled" or man.python_deps):
        return True
    try:
        python_script.resolve(ki, man.python_script)
    except (ValueError, TypeError, OSError):
        return True
    return False


def install_python_deps(deps: list[str], python: str,
                        env: dict | None = None) -> Step:
    if not deps:
        return Step("python-deps", True, "none required")
    cmd = [python, "-m", "pip", "install", "--quiet", *deps]
    rc, out = _run(cmd, env=env)
    return Step("python-deps", rc == 0,
                f"{len(deps)} packages" if rc == 0 else out.strip()[-400:],
                commands=[" ".join(cmd)])


def acquire(man: Manifest, prefix: Path, python: str,
            env: dict | None = None, ki=None) -> tuple[Step, Path | None]:
    """Obtain the executable per the manifest's strategy."""
    a = man.acquire
    if a is None:
        return Step("acquire", False, "no acquire block in manifest"), None
    if getattr(man, "python_script", None) is not None:
        from . import python_script
        try:
            if a.strategy != "bundled" or ki is None:
                raise ValueError("Declared Python script requires bundled acquisition and KI context")
            path = python_script.resolve(ki, man.python_script)
            return Step("acquire[bundled]", True, "Source-bound declared Python implementation"), path
        except (ValueError, TypeError, OSError) as exc:
            return Step("acquire[bundled]", False, str(exc)), None
    prefix.mkdir(parents=True, exist_ok=True)
    fn = {
        "pip": _acq_pip, "download": _acq_download, "build": _acq_build,
        "wine": _acq_wine, "bundled": _acq_bundled, "manual": _acq_manual,
    }[a.strategy]
    return fn(man, prefix, python, env)


def _acq_pip(man, prefix, python, env=None):
    pkg = man.acquire.package or man.model.lower()
    cmd = [python, "-m", "pip", "install", "--quiet", pkg]
    rc, out = _run(cmd, env=env)
    if rc != 0:
        return Step("acquire[pip]", False, out.strip()[-400:], commands=[" ".join(cmd)]), None
    mod = (man.acquire.produces or pkg).replace("-", "_")
    probe = (
        "import importlib; "
        f"m=importlib.import_module({mod!r}); "
        "p=getattr(m,'__file__',None) or "
        "next(iter(getattr(m,'__path__',())), ''); "
        f"print('\\n{_IMPORT_PATH_MARKER}'+str(p))"
    )
    rc2, out2 = _run([python, "-c", probe], env=env)
    if rc2 != 0:
        return Step("acquire[pip]", False,
                    f"installed {pkg} but `import {mod}` fails: {out2.strip()[-200:]}",
                    commands=[" ".join(cmd)]), None
    location = _marked_import_path(out2)
    if location is None:
        return Step("acquire[pip]", False,
                    f"installed {pkg} and imported {mod}, but its location could not be read",
                    commands=[" ".join(cmd)]), None
    return Step("acquire[pip]", True, f"{pkg} importable as {mod}",
                commands=[" ".join(cmd)]), location


def _acq_download(man, prefix, python, env=None, *, partial_path=None):
    if _CANCELLATION.get() is not None:
        return _managed_download(man, prefix, python, env)
    a = man.acquire
    if not a.url:
        return Step("acquire[download]", False, "manifest has no url"), None
    dest = prefix / Path(a.url).name
    partial = partial_path or dest.with_name(dest.name + "." + uuid.uuid4().hex + ".part")
    try:
        check_cancelled()
        if not dest.exists():
            req = urllib.request.Request(a.url, headers={"User-Agent": "geoforge-desktop"})
            proxy = ((env or {}).get("HTTPS_PROXY") or
                     (env or {}).get("https_proxy") or
                     (env or {}).get("HTTP_PROXY") or
                     (env or {}).get("http_proxy") or "")
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler(
                    {"http": proxy, "https": proxy} if proxy else {}),
                urllib.request.HTTPSHandler(context=tls.context()),
            )
            # The supervising worker can end a blocked read without shortening
            # the supported server timeout. Publish only a complete transfer.
            with opener.open(req, timeout=1800) as src, \
                    partial.open("wb") as out:
                while True:
                    check_cancelled()
                    chunk = src.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
            check_cancelled()
            partial.replace(dest)
    except InstallStopped:
        raise
    except Exception as e:
        check_cancelled()
        return Step("acquire[download]", False, f"{a.url}: {e}"), None
    finally:
        partial.unlink(missing_ok=True)

    if a.sha256:
        import hashlib
        digest = hashlib.sha256()
        with dest.open("rb") as downloaded:
            while chunk := downloaded.read(1024 * 1024):
                check_cancelled()
                digest.update(chunk)
        got = digest.hexdigest()
        if got != a.sha256:
            return Step("acquire[download]", False,
                        f"checksum mismatch: expected {a.sha256[:16]}… got {got[:16]}…"), None

    is_archive = False
    if dest.suffix == ".zip":
        is_archive = True
        with zipfile.ZipFile(dest) as z:
            for member in z.infolist():
                check_cancelled()
                z.extract(member, prefix)
    elif ".tar" in dest.suffixes or dest.suffix in (".tgz", ".gz", ".bz2", ".xz"):
        is_archive = True
        with tarfile.open(dest) as t:
            for member in t:
                check_cancelled()
                t.extract(member, prefix)

    binary = prefix / a.produces if a.produces else None
    # Release assets commonly include their version in the download filename
    # while the KI expects a stable executable name (swap4.2.0-mingw.exe ->
    # swap.exe). For a direct file, ``produces`` is that canonical destination;
    # materialise it instead of falsely reporting that the download omitted it.
    if (binary and not binary.exists() and not is_archive and dest.is_file()):
        binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dest, binary)
    if binary and not binary.exists():
        return Step("acquire[download]", False,
                    f"archive extracted but expected binary missing: {a.produces}"), None
    if binary:
        binary.chmod(binary.stat().st_mode | 0o111)
    return Step("acquire[download]", True, f"from {a.url}"), binary


def download_worker_command(request_path: Path) -> list[str]:
    prefix = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "kiss_cli"]
    return [*prefix, "_install-download-worker", str(request_path)]


@contextlib.contextmanager
def scratch_directory(prefix: str, dir):
    """A temporary directory whose cleanup never replaces the real outcome.

    On Windows a just-terminated process, an AV scanner, or a surviving
    descendant whose cwd is inside it keeps it from being deleted. Even
    TemporaryDirectory(ignore_cleanup_errors=True) then recurses until
    RecursionError on the Python 3.11 the Windows build ships (gh-79325), so
    remove it best effort there. POSIX keeps TemporaryDirectory unchanged.
    """
    import tempfile
    if os.name != "nt":
        with tempfile.TemporaryDirectory(prefix=prefix, dir=dir) as path:
            yield path
        return
    path = tempfile.mkdtemp(prefix=prefix, dir=dir)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _managed_download(man, prefix, python, env):
    """Keep blocking HTTP, checksum and extraction outside the Desktop thread."""
    from . import execution
    check_cancelled()
    project, stop, turn_id = _CANCELLATION.get()
    with scratch_directory(".download-", prefix) as temporary:
        worker_dir = Path(temporary)
        request_path = worker_dir / "request.json"
        request_path.write_text(json.dumps({"project": str(project) if project is not None else None,
                                           "acquire": asdict(man.acquire),
                                           "prefix": str(prefix), "python": python}), encoding="utf-8")
        child_env = {**os.environ, **(env or {})}
        if project is not None:
            child_env = execution.turn_environment(project, turn_id=turn_id, env=child_env)
        if not getattr(sys, "frozen", False):
            child_env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1]) + os.pathsep + child_env.get("PYTHONPATH", "")
        result = execution.run_process(download_worker_command(request_path),
            cwd=prefix, env=child_env, timeout=None, project=project, stop=stop, turn_id=turn_id)
        if result.status in {"stopped", "interrupted"}:
            raise InstallStopped(result.detail or "Stopped by the user")
        check_cancelled()
        try:
            if result.status != "succeeded":
                raise ValueError(result.detail or result.stderr[-2000:] or "download worker failed")
            payload = json.loads((worker_dir / "result.json").read_text(encoding="utf-8"))
            step = Step(**payload["step"])
            return step, Path(payload["binary"]) if payload.get("binary") else None
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return Step("acquire[download]", False, f"download worker did not complete: {exc}"), None


def run_download_worker(request_path: Path) -> int:
    from .manifest import Acquire
    from . import execution
    request = json.loads(request_path.read_text(encoding="utf-8"))
    project = request.get("project") or os.environ.get(execution.TURN_PROJECT_ENV)
    if project and execution.stop_requested(Path(project)):
        return 130
    man = Manifest(model="download", acquire=Acquire.from_dict(request["acquire"]))
    step, binary = _acq_download(man, Path(request["prefix"]), request["python"],
                                 env=os.environ, partial_path=request_path.parent / "archive.part")
    (request_path.parent / "result.json").write_text(json.dumps({
        "step": asdict(step), "binary": str(binary) if binary else None}), encoding="utf-8")
    return 0


def _build_checkout(src: Path, acquire, commands: list[str], env=None) -> tuple[str, dict]:
    """Inspect a build checkout without refreshing, repairing or discarding it.

    HEAD's tree, rather than the index, defines which source files must exist:
    a failed checkout and sparse/skip-worktree flags must not hide missing files.
    Local portability patches and generated files remain the user's work. This
    verifies the superproject checkout, not submodule contents or remote freshness.
    """
    evidence: dict = {}

    def git(*args, required=True):
        cmd = ["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
               "-C", str(src), *args]
        rc, out = _run(cmd, timeout=120, env=env, full_output=True, encoding="utf-8")
        commands.append(" ".join(cmd))
        if len(out) > 8 * 1024 * 1024:
            raise ValueError("Git checkout inspection exceeds the 8 MiB output limit")
        if rc:
            if not required:
                return None
            raise ValueError(f"Git {args[0]} check failed: {out.strip()[-500:]}")
        return out

    def repo_identity(value):
        value = value.strip().rstrip("/\\")
        parsed = urllib.parse.urlsplit(value)
        # GitHub documents both HTTPS spellings for the same repository. Do
        # not generalize this alias to arbitrary servers, local paths or SSH.
        if (parsed.scheme.lower() in {"http", "https"}
                and parsed.netloc.lower() == "github.com"
                and not parsed.query and not parsed.fragment
                and len(parsed.path.strip("/").split("/")) == 2):
            path = parsed.path.removesuffix(".git")
            return f"{parsed.scheme.lower()}://github.com{path}"
        # Preserve URL/SSH identities; normalize ordinary local repository paths.
        if "://" in value or (":" in value and not re.match(r"^[A-Za-z]:[/\\]", value)):
            return value
        return os.path.normcase(str(Path(value).resolve()))

    try:
        top = git("rev-parse", "--show-toplevel").strip()
        if Path(top).resolve() != src.resolve():
            raise ValueError("Git worktree root is not the configured source directory")
        origin = git("remote", "get-url", "origin").strip()
        if repo_identity(origin) != repo_identity(acquire.repo):
            raise ValueError("checkout origin does not match the manifest repository")
        head = git("rev-parse", "--verify", "HEAD^{commit}", required=False)
        head = head.strip() if head is not None else ""
        if not re.fullmatch(r"[0-9a-f]{40,64}", head):
            raise ValueError("checkout has no readable HEAD commit")
        ref = (acquire.ref or "").strip()
        evidence.update(repo=acquire.repo, requested_ref=ref or None, resolved_commit=head,
                        ref_scope="local fetched state; no remote freshness check")
        if ref and ref != "HEAD":
            if re.fullmatch(r"[0-9a-fA-F]{7,40}", ref):
                candidates = [ref]
            elif ref.startswith("refs/tags/") or ref.startswith("refs/remotes/origin/"):
                candidates = [ref]
            elif ref.startswith("refs/heads/"):
                candidates = ["refs/remotes/origin/" + ref[len("refs/heads/"):]]
            else:
                candidates = ["refs/tags/" + ref, "refs/remotes/origin/" + ref]
            targets = {}
            for candidate in candidates:
                value = git("rev-parse", "--verify", "--end-of-options",
                            candidate + "^{commit}", required=False)
                if value is not None:
                    targets[candidate] = value.strip()
            if not targets:
                raise ValueError(f"requested ref {ref!r} is unavailable in this checkout; "
                                 "obtain that revision deliberately before retrying")
            if len(set(targets.values())) != 1:
                raise ValueError(f"requested ref {ref!r} is ambiguous between a tag and branch")
            expected = next(iter(targets.values()))
            evidence["requested_commit"] = expected
            if head != expected:
                raise ValueError(f"checkout HEAD {head[:12]} does not match requested "
                                 f"ref {ref!r} ({expected[:12]})")
        else:
            evidence["ref_scope"] = "existing HEAD observed; manifest does not pin a commit"

        tree = git("ls-tree", "-r", "-z", "HEAD")
        records = [row for row in tree.split("\0") if row]
        if len(records) > 100000:
            raise ValueError("checkout exceeds the 100,000 tracked-entry inspection limit")
        missing, gitlinks = [], []
        tracked = 0
        for row in records:
            header, rel = row.split("\t", 1)
            mode, kind, _oid = header.split(" ")
            parts = rel.split("/")
            if any(part in {"", ".", ".."} for part in parts) or Path(rel).is_absolute():
                raise ValueError("Git returned an invalid tracked path")
            if os.name == "nt":
                reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
                reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT")
                                for number in "123456789¹²³")
                if any(part.endswith((".", " "))
                       or part.split(".", 1)[0].rstrip(" ").upper() in reserved
                       or any(ord(char) < 32 or char in '<>:"\\|?*' for char in part)
                       for part in parts):
                    evidence["unrepresentable_tracked"] = [rel]
                    raise ValueError(f"checkout is incomplete: tracked path {rel!r} cannot be "
                                     "represented as an ordinary Windows source file; do not "
                                     "disable NTFS protections or silently exclude this source")
            if kind == "commit" and mode == "160000":
                gitlinks.append(rel)
                continue
            if kind != "blob" or mode not in {"100644", "100755", "120000"}:
                raise ValueError(f"unsupported tracked source entry {rel!r}")
            path = src.joinpath(*parts)
            tracked += 1
            # Git for Windows may materialise a tracked symlink as a text file.
            present = path.is_file() or (mode == "120000" and path.is_symlink())
            if not present:
                missing.append(rel)
        evidence.update(tracked_files=tracked, submodule_paths=gitlinks,
                        submodules_verified=False, missing_tracked=missing[:20])
        if missing:
            raise ValueError(f"checkout is incomplete: {len(missing)} tracked source file(s) "
                             f"missing or not files: {', '.join(repr(p) for p in missing[:8])}. "
                             "This may be an interrupted/unsupported checkout or sparse selection")

        if git("ls-files", "--unmerged", "-z"):
            raise ValueError("checkout index contains unresolved merge conflicts")
        status = git("status", "--porcelain=v1", "-z", "--untracked-files=no",
                     "--ignore-submodules=all")
        changes = []
        entries = iter(status.split("\0"))
        for row in entries:
            if not row:
                continue
            code, path = row[:2], row[3:]
            changes.append({"status": code, "path": path})
            if "R" in code or "C" in code:
                next(entries, None)  # the second NUL-delimited rename/copy path
            if code[0] == "D" or "U" in code or code in {"AA", "DD"}:
                evidence["tracked_changes"] = changes
                raise ValueError(f"checkout has a staged deletion or unresolved conflict: {path!r}")
        flags = git("ls-files", "-v", "-z")
        hidden = [row[2:] for row in flags.split("\0")
                  if row and (row[0].islower() or row[0] == "S")]
        evidence.update(tracked_changes=changes, index_visibility_limited=hidden,
                        local_changes_preserved=True, untracked_files="preserved; not inspected")
        return "", evidence
    except (ValueError, OSError) as exc:
        return (f"Source checkout cannot be reused: {exc}. No files were reset or removed. "
                "Inspect and repair the checkout while preserving local work, or choose a fresh "
                "installation directory; then retry."), evidence


def _acq_build(man, prefix, python, env=None):
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
                rc, out = _run(c, env=env)
                cmds.append(" ".join(c))
                if rc != 0:
                    break
            if rc == 0:
                rc, out = _run(
                    ["git", "-C", str(src), "checkout", "-q", "FETCH_HEAD"],
                    env=env)
                cmds.append(f"git -C {src} checkout FETCH_HEAD")
            if rc != 0:
                # Some servers refuse to serve an arbitrary SHA to a shallow
                # fetch. Falling back to a full clone costs time, not accuracy.
                rc, out = _run(
                    ["git", "-C", str(src), "fetch", "origin"],
                    timeout=1800, env=env)
                cmds.append(f"git -C {src} fetch origin")
                if rc == 0:
                    rc, out = _run(
                        ["git", "-C", str(src), "checkout", "-q", sha],
                        env=env)
                    cmds.append(f"git -C {src} checkout {sha}")
        else:
            clone = ["git", "clone", "--depth", "1"]
            if a.ref:
                clone += ["--branch", a.ref]
            clone += [a.repo, str(src)]
            rc, out = _run(clone, env=env)
            cmds.append(" ".join(clone))
        if rc != 0:
            return Step("acquire[build]", False, f"clone failed: {out.strip()[-400:]}",
                        commands=cmds), None

    problem, source = _build_checkout(src, a, cmds, env=env)
    if problem:
        return Step("acquire[build]", False, problem, commands=cmds,
                    evidence={"source_checkout": source}), None

    for c in a.commands:
        rc, out = _run(c, cwd=src, env=env)
        cmds.append(c)
        if rc != 0:
            return Step("acquire[build]", False,
                        f"`{c}` failed (rc={rc}):\n{out.strip()[-1500:]}", commands=cmds,
                        evidence={"source_checkout": source}), None

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
                        commands=cmds, evidence={"source_checkout": source}), None
    if binary:
        binary.chmod(binary.stat().st_mode | 0o111)
    detail = f"built from {a.repo}@{a.ref or 'HEAD'} (observed {source['resolved_commit'][:12]})"
    if source["tracked_changes"] or source["index_visibility_limited"]:
        detail += (f"; local source changes preserved ({len(source['tracked_changes'])} tracked "
                   f"changes, {len(source['index_visibility_limited'])} index visibility flags); "
                   "this is not a pristine-source build")
    if source["submodule_paths"]:
        detail += "; submodule contents were not verified by the source checkout check"
    return Step("acquire[build]", True, detail, commands=cmds,
                evidence={"source_checkout": source}), binary


def _acq_wine(man, prefix, python, env=None):
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


def _acq_bundled(man, prefix, python, env=None):
    p = Path(man.acquire.produces or "")
    return (Step("acquire[bundled]", p.exists(),
                 f"shipped in the KI: {p}" if p.exists() else f"expected bundled file missing: {p}"),
            p if p.exists() else None)


def _acq_manual(man, prefix, python, env=None):
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

    def require_destination(link: Path) -> None:
        """Aliases may expose a selected tree, never write through external/ KI parents."""
        check_cancelled()
        if cfg is None or not getattr(cfg, "root", None):
            raise ValueError(f"Cannot place an alias without a setup workspace: {link}")
        workspace = Path(cfg.root).resolve()
        lexical = Path(link).absolute()
        parent = lexical.parent.resolve()
        destination = parent / lexical.name
        # Compare the real parent, including Windows' short/long user-profile
        # spelling. Do not resolve the final entry through a dangling alias.
        if destination == workspace or not parent.is_relative_to(workspace):
            raise ValueError(f"KI alias destination is outside the setup workspace: {link}")
        protected = {workspace / "ki"}
        if getattr(ki, "root", None):
            protected.add(Path(ki.root).resolve())
        for boundary in protected:
            if destination.is_relative_to(boundary) or parent.is_relative_to(boundary):
                raise ValueError(f"KI alias destination would modify a protected KI: {link}")
        if os.path.lexists(link):
            raise ValueError(f"KI alias destination already exists or is a dangling link: {link}")

    def link_directory(link: Path, target: Path) -> None:
        """Create a directory alias without requiring Windows Developer Mode."""
        try:
            link.symlink_to(target, target_is_directory=True)
            return
        except OSError:
            if os.name != "nt":
                raise
        # Directory junctions are available to ordinary Windows users, unlike
        # symlinks on machines where Developer Mode is disabled. CPython's own
        # CreateJunction needs no cmd.exe: ``mklink`` through a list argv got
        # its quotes escaped as \" (cmd rejected every path), and a shell string
        # would still expand %VAR% inside a folder name.
        import _winapi
        existed = os.path.lexists(link)
        try:
            _winapi.CreateJunction(str(target), str(link))
        except OSError:
            # It makes the directory before turning it into a junction; never
            # leave a plain empty folder where the alias should be.
            if not existed:
                with contextlib.suppress(OSError):
                    link.rmdir()
            raise
        if not link.is_dir():
            raise OSError(f"junction {link} -> {target} was not created")

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

    declared_binaries = runnable.declared(ki)
    if binary and not declared_binaries:
        notes.append("No executable path could be bound statically from the KI preflight; "
                     "no additional executable aliases were created. Verify the declared layout with the agent.")

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
            for decl in declared_binaries:
                want = resolve(decl)
                if want is None or len(want.parts) < len(rel_binary.parts):
                    continue
                declared_tail = tuple(want.parts[-len(rel_binary.parts):])
                same_relative = declared_tail == rel_binary.parts
                if (not same_relative and os.name == "nt" and
                        rel_binary.suffix.lower() == ".exe"):
                    same_relative = declared_tail == rel_binary.with_suffix("").parts
                if not same_relative:
                    continue
                declared_root = want
                for _ in rel_binary.parts:
                    declared_root = declared_root.parent
                if declared_root == prefix or declared_root.exists():
                    continue
                require_destination(declared_root)
                try:
                    declared_root.parent.mkdir(parents=True, exist_ok=True)
                    link_directory(declared_root, prefix)
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
        require_destination(want)
        try:
            want.parent.mkdir(parents=True, exist_ok=True)
            link_directory(want, have)
            notes.append(f"linked {want} -> {have}")
        except OSError as e:
            notes.append(f"could not place {want.name}/ at {want}: {e}")

    if not binary or not binary.is_file():
        return notes
    for decl in declared_binaries:
        want = resolve(decl)
        if want is None or want.exists():
            continue
        if want.name != binary.name:
            continue                    # a different artefact, not this binary
        require_destination(want)
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


def place_agent_install(man: Manifest, binary: Path | None,
                        cfg) -> tuple[Path | None, list[str]]:
    """Put an agent-discovered runtime at the manifest's canonical path.

    Setup agents correctly obtain official releases but do not always preserve
    ``binaries/<install_dir>/<produces>``. A broad executable search can then
    paint the install green while the KI's run tools still fail with ENOENT.
    Preserve the complete distribution tree (or adjacent Windows DLLs for a
    single-file ``produces`` value) before the final runnable verdict.
    """
    check_cancelled()
    if (binary is None or not Path(binary).is_file() or man.acquire is None or
            not man.acquire.produces):
        return binary, []
    import stat
    from pathlib import PureWindowsPath

    binary = Path(binary).absolute()
    relative = Path(man.acquire.produces)
    install_dir = Path(man.install_dir or man.model)
    for value in (relative, install_dir):
        if (not value.parts or value.is_absolute() or value.drive
                or PureWindowsPath(str(value)).drive or PureWindowsPath(str(value)).root
                or ".." in value.parts):
            raise ValueError("Install directory and product must be bounded relative paths")
    prefix = Path(cfg.roles["binaries"]).absolute() / install_dir
    if (os.name == "nt" and
            binary.name.lower() == relative.name.lower() + ".exe"):
        # Manifests inherited from POSIX commonly omit the native suffix.
        # Normalise before comparing/copying so the complete source tree and
        # its adjacent DLLs still land at the path find_binary() probes.
        relative = relative.with_name(relative.name + ".exe")
    expected = prefix / relative
    if binary.name.lower() != expected.name.lower():
        return binary, []

    notes: list[str] = []
    parts = relative.parts
    suffix = binary.parts[-len(parts):] if len(binary.parts) >= len(parts) else ()
    suffix_matches = tuple(os.path.normcase(p) for p in suffix) == tuple(
        os.path.normcase(p) for p in parts)

    if len(parts) > 1 and suffix_matches:
        # The *whole* declared suffix identifies the distribution root. With
        # build/bin/model.exe, retaining only build/ loses sibling Data/.
        source = binary
        for _ in parts:
            source = source.parent
        source = source.resolve()
        if (man.acquire.strategy == "download"
                and source == Path(cfg.roles["binaries"]).resolve()):
            # Download agents may extract an archive's named top-level folder
            # directly under binaries/. The first component is already part
            # of the declared product, so place only that package folder at
            # the same relative location; never copy the binaries container
            # (including other models and the destination) into itself.
            package = source / parts[0]
            info = package.lstat()
            if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) &
                    getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
                raise ValueError("Downloaded package staging directory must be a real directory")
            source = package.resolve()
            prefix = prefix / parts[0]
        destination = prefix.resolve()
        if source == destination:
            return expected, []
        home = Path.home().resolve()
        if source == Path(source.anchor) or source == home or source in home.parents:
            raise ValueError("Cannot place a distribution from a disk or home directory")
        if source in destination.parents or destination in source.parents:
            raise ValueError("Source and destination distribution roots overlap")
        if not prefix.parent.resolve().is_relative_to(Path(cfg.roles["binaries"]).resolve()):
            raise ValueError("Install distribution parent escapes the configured binaries root")

        def linked(info):
            return (stat.S_ISLNK(info.st_mode) or
                    getattr(info, "st_file_attributes", 0) &
                    getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))

        def same_bytes(left, right):
            check_cancelled()
            if left.stat().st_size != right.stat().st_size:
                return False
            with left.open("rb") as a, right.open("rb") as b:
                while True:
                    check_cancelled()
                    chunk = a.read(1 << 20)
                    if chunk != b.read(1 << 20):
                        return False
                    if not chunk:
                        return True

        # Inspect every conflict before creating anything. Existing partial
        # installs may be completed, but different files and unrelated aliases
        # require an explicit repair decision; never merge with overwrite.
        plans = []
        pending = [(source, prefix)]
        while pending:
            check_cancelled()
            src, dst = pending.pop()
            src_info = src.lstat()
            try:
                dst_info = dst.lstat()
            except FileNotFoundError:
                dst_info = None
            if dst_info is not None:
                try:
                    if os.path.samefile(src, dst):
                        continue
                except OSError:
                    pass
                if linked(dst_info):
                    raise ValueError(f"Install distribution conflict at {dst}: unrelated alias")
            if stat.S_ISLNK(src_info.st_mode):
                if dst_info is not None:
                    raise ValueError(f"Install distribution conflict at {dst}: source is an alias")
                target = src.resolve(strict=True)
                plans.append(("link", target, dst))
            elif linked(src_info):
                raise ValueError(f"Unsupported distribution reparse point: {src}")
            elif stat.S_ISDIR(src_info.st_mode):
                if dst_info is not None and not stat.S_ISDIR(dst_info.st_mode):
                    raise ValueError(f"Install distribution conflict at {dst}: expected directory")
                if dst_info is None:
                    plans.append(("directory", src, dst))
                for child in src.iterdir():
                    check_cancelled()
                    pending.append((child, dst / child.name))
            elif stat.S_ISREG(src_info.st_mode):
                if dst_info is None:
                    plans.append(("file", src, dst))
                elif not stat.S_ISREG(dst_info.st_mode) or not same_bytes(src, dst):
                    raise ValueError(f"Install distribution conflict at {dst}: different file")
            else:
                raise ValueError(f"Unsupported distribution file type: {src}")

        if not plans:
            return expected, []
        check_cancelled()
        prefix.parent.mkdir(parents=True, exist_ok=True)
        if not os.path.lexists(prefix):
            try:
                prefix.symlink_to(source, target_is_directory=True)
                return expected, [f"linked complete distribution {prefix} -> {source}"]
            except OSError:
                # Developer Mode may be disabled. Exclusive creation below
                # also prevents a concurrently-created target being replaced.
                pass
        for kind, src, dst in sorted(plans, key=lambda row: len(row[2].parts)):
            check_cancelled()
            if kind == "directory":
                dst.mkdir()
            elif kind == "link":
                dst.symlink_to(src, target_is_directory=src.is_dir())
            else:
                created = None
                try:
                    with src.open("rb") as source_file, dst.open("xb") as target_file:
                        created = os.fstat(target_file.fileno())
                        while True:
                            check_cancelled()
                            chunk = source_file.read(1 << 20)
                            if not chunk:
                                break
                            target_file.write(chunk)
                except BaseException:
                    # Only discard this newly-created partial file. A stopped
                    # copy can then resume without conflicting with itself.
                    if created is not None:
                        try:
                            if os.path.samestat(created, dst.lstat()):
                                dst.unlink()
                        except OSError:
                            pass
                    raise
                shutil.copystat(src, dst)
        notes.append(f"completed distribution {source} -> {prefix}; existing files preserved")
    else:
        if expected.is_file():
            return expected, []
        expected.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, expected)
        copied = [binary.name]
        if os.name == "nt":
            for sibling in binary.parent.glob("*.dll"):
                shutil.copy2(sibling, expected.parent / sibling.name)
                copied.append(sibling.name)
        notes.append(
            f"copied agent runtime to {expected} ({', '.join(copied)})")

    return (expected if expected.is_file() else binary), notes


PREFLIGHT_POLICY = "ki-preflight-scratch-v2-full-output"


def _preflight_directory(path: Path, *, create: bool = False) -> None:
    """Never follow a child-owned link while recording host evidence."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            raise
        path.mkdir()
        info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError("Preflight evidence directory is a link or reparse point")


def _preflight_inputs(root: Path) -> dict:
    """Record canonical bytes and alias bindings, without expanding aliases."""
    from . import ki_tree
    inventory = ki_tree.scan(root)
    result, total = {}, 0
    for entry in inventory.entries:
        check_cancelled()
        row = {"kind": entry.kind}
        if entry.kind == "file":
            digest = hashlib.sha256()
            with (root / entry.relative).open("rb") as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    total += len(chunk)
                    if total > ki_tree.MAX_BYTES:
                        raise ValueError("Preflight copy exceeds the KI byte limit")
                    digest.update(chunk)
                    check_cancelled()
            row["sha256"] = digest.hexdigest()
        elif entry.kind == "link":
            row["target"] = entry.target
        result[entry.relative] = row
    return result


def run_preflight(ki, python: str, cfg=None, *, project=None, stop=None, turn_id=None) -> Step:
    """Execute exact KI bytes in retained scratch; never mutate/adopt active KI.

    This contains cwd/__file__ startup products, not arbitrary absolute writes
    or other same-user programs. No runtime paths or preflight report subjects
    are rewritten. Parent-relative assumptions can fail visibly in the copy.
    """
    from . import ki_guard
    context = (contextlib.nullcontext() if _CANCELLATION.get() is not None else
               cancellation_context(project or getattr(cfg, "root", None), stop=stop, turn_id=turn_id))
    try:
        # Keep ownership and cancellation live through final evidence writes.
        with context, ki_guard.worker(ki.root):
            return _run_preflight_copy(ki, python, cfg, project=project)
    except InstallStopped as exc:
        return Step("preflight", False, str(exc), evidence={
            "policy": PREFLIGHT_POLICY, "state": "cancelled", "ok": False,
            "source_root": str(ki.root), "launch_attempted": False})


def _preflight_record(attempt: Path, evidence: dict, ancestors: list[Path]) -> None:
    for directory in ancestors:
        _preflight_directory(directory)
    temporary = attempt / ("record-" + uuid.uuid4().hex[:8] + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
    if evidence["ok"]:
        check_cancelled()
    os.replace(temporary, attempt / "execution.json")
    if evidence["ok"]:
        check_cancelled()


def _run_preflight_copy(ki, python: str, cfg, *, project) -> Step:
    from . import ki_copy, ki_guard, ki_tree, ki_verification, software_verification
    source = Path(ki.root).absolute()
    required = (source / "SKILL.md").is_file()
    evidence = {"policy": PREFLIGHT_POLICY, "source_root": str(source),
                "python": str(python), "state": "failed", "source_intact": False,
                "returncode": None, "created_paths": [], "changed_inputs": [],
                "launch_attempted": False, "scope": "preflight_execution_only",
                "readiness_receipt": False}
    argv, out, problems, attempt, ancestors = [], "", [], None, []
    rc, before, inputs = None, None, None
    try:
        ki_guard.require_intact(source, required=required)
        if not ki.preflight:
            raise ValueError("this KI ships no preflight_check.py")
        preflight = Path(ki.preflight).absolute()
        relative = preflight.relative_to(source)
        if not preflight.resolve().is_relative_to(source.resolve()):
            raise ValueError("Preflight script is outside the exact KI")
        before = ki_verification.content_digest(source)
        if not before:
            raise ValueError("Cannot fingerprint the exact preflight KI")
        launch_cfg = copy.deepcopy(cfg)
        runtime = software_verification.runtime_identity(cfg) if cfg is not None else None
        evidence.update(source_digest=before, runtime_identity=runtime)
        base = Path(project or getattr(cfg, "root", None) or source.parent).resolve()
        if base == source.resolve() or base.is_relative_to(source.resolve()):
            raise ValueError("Preflight evidence must remain outside the protected KI")
        evidence["workspace_root"] = str(base)
        attempt_id = uuid.uuid4().hex[:12]
        storage_parts = (".geoforge", "preflight")
        # Python's host I/O can use extended paths, but a native model's
        # cwd/__file__ handling often cannot. Keep an explicitly reported
        # short host-temp copy when a nested Windows project would cross
        # that boundary. This does not relocate the selected runtime/data.
        longest = max((len(entry.relative) for entry in ki_tree.scan(source).entries), default=0)
        normal_copy = base.joinpath(*storage_parts, attempt_id, "ki")
        if os.name == "nt" and len(str(normal_copy)) + 1 + longest >= 240:
            base = Path(tempfile.gettempdir()).resolve()
            storage_parts = ("geoforge-preflight",)
            if base == source.resolve() or base.is_relative_to(source.resolve()):
                raise ValueError("Short preflight storage is inside the protected KI")
            evidence["storage_scope"] = "host_temp_long_path"
        else:
            evidence["storage_scope"] = "workspace"
        _preflight_directory(base)
        ancestors.append(base)
        parent = base
        for part in storage_parts:
            parent = parent / part
            _preflight_directory(parent, create=True)
            ancestors.append(parent)
        attempt = parent / attempt_id
        attempt.mkdir()
        ancestors.append(attempt)
        scratch = attempt / "ki"
        evidence.update(execution_root=str(scratch), record_path=str(attempt / "execution.json"))
        check_cancelled()
        ki_copy.copytree(source, scratch)
        copied = ki_verification.content_digest(scratch)
        if copied != before or ki_verification.content_digest(source) != before:
            raise ValueError("KI changed while preparing its execution copy")
        evidence["execution_digest"] = copied
        inputs = _preflight_inputs(scratch)
        if ki_verification.content_digest(scratch) != before:
            raise ValueError("Execution copy changed before launch")
        argv = [str(python), str(scratch / relative)]
        if launch_cfg is not None and launch_cfg.relocation == "sandbox":
            from .paths import have_sandbox, sandbox_command
            if have_sandbox():
                argv = sandbox_command(launch_cfg, argv, cwd=scratch)
        env = {"PYTHONDONTWRITEBYTECODE": "1"}
        if launch_cfg is not None:
            from .paths import with_ki_tools_common, with_python_runtime
            env = with_python_runtime(python, with_ki_tools_common(launch_cfg, env))
        evidence["launch_attempted"] = True
        rc, out = _run(argv, cwd=scratch, timeout=600, env=env, full_output=True)
        check_cancelled()
        after = _preflight_inputs(scratch)
        changed = [name for name, row in inputs.items() if after.get(name) != row]
        evidence["changed_inputs"] = changed[:200]
        evidence["created_paths"] = sorted(after.keys() - inputs.keys())[:200]
        evidence["created_path_count"] = len(after.keys() - inputs.keys())
        if changed:
            raise ValueError("Preflight changed copied KI input(s): " + ", ".join(changed[:10]))
        if cfg is not None and software_verification.runtime_identity(cfg) != runtime:
            raise ValueError("Preflight runtime binding changed during execution")
        ki_guard.require_intact(source, required=required)
        if ki_verification.content_digest(source) != before:
            raise ValueError("Original KI changed during preflight execution")
        evidence["source_intact"] = True
        check_cancelled()
        evidence["state"] = "completed" if rc == 0 else "failed"
    except InstallStopped as exc:
        out = exc.output or out
        evidence["state"] = "cancelled"
        problems.append(str(exc))
    except (OSError, ValueError, RuntimeError) as exc:
        problems.append(str(exc))
    finally:
        # Preserve the original integrity failure even after cancellation or
        # a child crash; this is never a recovery or automatic re-enrollment.
        if before is not None:
            try:
                ki_guard.require_intact(source, required=required)
                if ki_verification.content_digest(source) != before:
                    raise ValueError("Original KI changed during preflight execution")
                evidence["source_intact"] = True
            except (OSError, ValueError, RuntimeError) as exc:
                evidence["source_intact"] = False
                evidence["state"] = "failed" if evidence["state"] != "cancelled" else "cancelled"
                problems.append(str(exc))
        evidence["returncode"] = rc
        evidence["command"] = argv
        evidence["ok"] = evidence["state"] == "completed" and not problems
        if attempt is not None:
            try:
                for directory in ancestors:
                    _preflight_directory(directory)
                output = attempt / ("output-" + uuid.uuid4().hex[:8] + ".txt")
                with output.open("x", encoding="utf-8", newline="") as stream:
                    stream.write(out)
                evidence["output_path"] = str(output)
                evidence["output_chars"] = len(out)
                # The supervisor may report a timeout or interrupted stream;
                # this states only that the host retains everything captured.
                evidence["output_truncated"] = False
                try:
                    _preflight_record(attempt, evidence, ancestors)
                except InstallStopped as exc:
                    evidence.update(ok=False, state="cancelled")
                    problems.append(str(exc))
                    _preflight_record(attempt, evidence, ancestors)
            except (OSError, ValueError, RuntimeError) as exc:
                evidence.update(ok=False, state="failed")
                problems.append("Cannot retain preflight evidence: " + str(exc))
    location = ("Preflight execution copy: " + evidence["execution_root"]
                if "execution_root" in evidence else "Preflight was not executed")
    tail = "\n".join(out[-8000:].strip().splitlines()[-25:])
    output_location = ("Full captured output: " + evidence["output_path"]
                       if "output_path" in evidence else "")
    detail = "\n".join(filter(None, [location, output_location, *problems, tail]))
    return Step("preflight", evidence.get("ok", False), detail,
                commands=[" ".join(argv)] if argv else [], evidence=evidence)


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
        discovered = shutil.which(configured)
        resolved = discovered or configured
        try:
            candidate = Path(resolved).resolve()
            current = Path(sys.executable).resolve()
            app_launcher = (".app/Contents/MacOS/" in candidate.as_posix()
                            and candidate.name.lower() in {"geoforge desktop", "kiss"})
            is_launcher = (getattr(sys, "frozen", False)
                           and (candidate == current or app_launcher))
        except OSError:
            is_launcher = False
        if not is_launcher and (discovered or Path(configured).is_file()):
            # Persist and grant the executable GeoForge actually found.  A
            # macOS GUI does not inherit the user's interactive-shell PATH,
            # and Claude's permission matcher distinguishes ``python3`` from
            # ``/Library/.../python3``.  Returning the absolute discovery
            # makes both execution and the generated CLI allowlist stable.
            # Keep an explicitly configured symlink spelling (for example
            # python3 rather than python3.13); ``which`` is already absolute.
            return discovered if discovered else configured
    return find_base_python() or "python3"


_MODEL_ENV_PROBE = r"""
import importlib.util, json, os, pathlib, site, sys, sysconfig
target = pathlib.Path(sys.argv[1])
expected_python = pathlib.Path(sys.argv[2])
normal = lambda value: os.path.normcase(os.path.abspath(value))
if (normal(sys.prefix) != normal(target) or normal(sys.prefix) == normal(sys.base_prefix)
        or normal(sys.executable) != normal(expected_python) or site.ENABLE_USER_SITE):
    raise RuntimeError('Model interpreter is not the expected isolated virtual environment')
config = {}
for line in (target / 'pyvenv.cfg').read_text().splitlines():
    if '=' in line:
        key, value = line.split('=', 1)
        config[key.strip().lower()] = value.strip().lower()
if config.get('include-system-site-packages') != 'false':
    raise RuntimeError('Model virtual environment must not inherit system site packages')
for name in ('purelib', 'platlib', 'scripts', 'data'):
    if not pathlib.Path(sysconfig.get_path(name)).resolve().is_relative_to(target.resolve()):
        raise RuntimeError('Model installation path escapes its virtual environment: ' + name)
for entry in sys.path:
    path = pathlib.Path(entry)
    if (any(part in {'site-packages', 'dist-packages'} for part in path.parts)
            and not path.resolve().is_relative_to(target.resolve())):
        raise RuntimeError('Model interpreter imports packages outside its virtual environment')
spec = importlib.util.find_spec('pip')
if spec is not None and (not spec.origin or not pathlib.Path(spec.origin).resolve().is_relative_to(target.resolve())):
    raise RuntimeError('Model pip resolves outside its virtual environment')
print('__GEOFORGE_MODEL_ENV__=' + json.dumps({'pip_available': spec is not None}))
"""


def _model_env_probe(interpreter: Path, target: Path) -> tuple[bool, bool, str]:
    rc, out = _run([str(interpreter), "-I", "-c", _MODEL_ENV_PROBE, str(target), str(interpreter)])
    marker = "__GEOFORGE_MODEL_ENV__="
    if rc == 0 and marker in out:
        try:
            row = json.loads(out.rpartition(marker)[2].splitlines()[0])
            if isinstance(row, dict) and type(row.get("pip_available")) is bool:
                return True, row["pip_available"], ""
        except (ValueError, IndexError):
            pass
    return False, False, out.strip()[-600:] or "Interpreter isolation probe returned no valid result"


def ensure_python_env(cfg, base_python: str | None = None) -> Step:
    """Guarantee an interpreter that survives relocation.

    The venv is created at cfg.roles['python_env'] so the KI's hardcoded
    interpreter path resolves to the same environment its dependencies were
    installed into. See find_base_python for why the frozen app must not use
    sys.executable as the base.
    """
    target = Path(cfg.roles["python_env"]).absolute()
    # ``venv`` follows the platform's native layout.  POSIX puts the
    # interpreter in ``bin/python`` while Windows uses
    # ``Scripts/python.exe``.  Looking only in ``bin`` made every successful
    # Windows venv creation look like a failure and skipped model acquisition.
    interpreter = (target / "Scripts" / "python.exe"
                   if os.name == "nt" else target / "bin" / "python")
    # Keep existing/partial environments intact. A redirect or a broken old
    # launcher is an explicit repair decision, never grounds for a blind delete.
    try:
        for path in (target, *target.parents):
            if path.exists() and (path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
                return Step("python-env", False, f"Python environment path is linked: {path}")
    except OSError as error:
        return Step("python-env", False, str(error))
    existing = interpreter.exists()
    if existing:
        valid, pip_ready, detail = _model_env_probe(interpreter, target)
        if not valid:
            return Step("python-env", False, f"Existing Python environment requires repair; files preserved: {detail}")
        if pip_ready:
            cfg.python = str(interpreter)
            return Step("python-env", True, f"using isolated interpreter {interpreter}")

    base = base_python or find_base_python()
    if not existing and base is None:
        return Step(
            "python-env", False,
            "No Python 3 found on this machine, and the app cannot conjure one "
            "from inside itself. One-time fix, then press Install again:\n"
            "    macOS:  brew install python  (or: xcode-select --install)\n"
            "    Linux:  sudo apt install python3-venv python3-pip")

    commands = []
    if not existing:
        target.parent.mkdir(parents=True, exist_ok=True)
        cmd = [base, "-m", "venv", "--without-pip", str(target)]
        commands.append(" ".join(cmd))
        rc, out = _run(cmd, timeout=300)
        if rc != 0 or not interpreter.exists():
            return Step("python-env", False,
                        f"could not create a venv with {base}: {out.strip()[-300:]}", commands=commands)
        valid, pip_ready, detail = _model_env_probe(interpreter, target)
        if not valid:
            return Step("python-env", False, f"Created Python environment failed isolation checks: {detail}", commands=commands)
    else:
        pip_ready = False
    if not pip_ready:
        # Prefer bundled offline pip. Debian/Ubuntu may omit ensurepip; the
        # existing base pip can seed this exact isolated target via --python.
        cmd = [str(interpreter), "-I", "-m", "ensurepip", "--upgrade", "--default-pip"]
        commands.append(" ".join(cmd))
        rc, out = _run(cmd, timeout=300)
        valid, pip_ready, detail = _model_env_probe(interpreter, target)
        if not valid:
            return Step("python-env", False, f"Python environment isolation changed during pip bootstrap: {detail}", commands=commands)
        if not pip_ready:
            if base is None:
                return Step("python-env", False, "Isolated Python exists but pip is missing; a base Python with pip 22.3+ is required", commands=commands)
            cmd = [base, "-I", "-m", "pip", "--isolated", "--python", str(interpreter), "install",
                   "--require-virtualenv", "--prefix", str(target), "--disable-pip-version-check", "--no-input", "--no-deps", "pip"]
            commands.append(" ".join(cmd))
            rc, out = _run(cmd, timeout=600, env={"PIP_CONFIG_FILE": os.devnull, "PYTHONSAFEPATH": "1"})
            valid, pip_ready, detail = _model_env_probe(interpreter, target)
            if rc != 0 or not valid or not pip_ready:
                return Step("python-env", False, "Could not seed pip into the isolated model environment; "
                            "base Python needs pip 22.3+ with --python support. " + (detail or out.strip()[-600:]), commands=commands)
    cfg.python = str(interpreter)
    return Step("python-env", True, f"{'repaired pip in' if existing else 'created'} isolated interpreter {interpreter}", commands=commands)


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

    from .setup import prepare_common
    try:
        live = prepare_common(cfg, repo_root)
    except (ValueError, OSError) as error:
        return Step("ki-tools-common", False, str(error))
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
