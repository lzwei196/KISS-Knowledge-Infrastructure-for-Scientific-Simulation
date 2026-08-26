"""File-system containment for Kimi Code on macOS.

Kimi has useful permission rules of its own, but an approved ``Bash`` command
is still an ordinary child process.  GeoForge therefore puts the complete
Kimi process tree inside the macOS Seatbelt sandbox when the user selects the
default project-scoped mode.  The sandbox is deliberately outside Kimi: a
shell command cannot bypass it.

This is a file-system boundary, not a network boundary.  Kimi must still reach
its model API.  Its own login/session directory also stays available so an
already authenticated CLI keeps working.

Kimi watches its reported OS home for global instruction changes.  Scoped
mode therefore gives it an empty, private temporary HOME while keeping the
real Kimi state reachable through KIMI_CODE_HOME.  This avoids granting a
watcher over the user's actual home directory.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

SCOPED = "scoped"
FULL = "full"
MODES = {SCOPED, FULL}


def _literal(path: str | Path) -> str:
    """Return one escaped Seatbelt string literal."""
    value = str(path).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{value}"'


def _resolved(path: str | Path) -> Path | None:
    value = str(path).strip()
    if not value:
        return None
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        return None
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate.absolute()


def _roots(paths) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for raw in paths:
        path = _resolved(raw)
        if path is None:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _policy_paths(pol, kinds: set[str]) -> list[str]:
    if pol is None:
        return []
    return [g.path for g in pol.all_grants()
            if g.kind in kinds and Path(g.path).is_absolute()]


def runtime_read_roots(home: Path | None = None) -> list[Path]:
    """Return Kimi-owned or Kimi-discovered user roots needed at startup.

    Kimi automatically discovers the cross-agent ``~/.agents/skills`` folder
    before it processes a prompt.  Treating that deterministic startup read as
    project data creates an approval loop: every fresh Kimi process fails at
    the same ``realpath`` call and asks the user again.  These roots are opened
    read-only; they do not widen project writes or expose the rest of home.
    """
    base = (home or Path.home()).expanduser().resolve()
    configured = str(os.environ.get("KIMI_CODE_HOME") or "").strip()
    state = Path(configured).expanduser() if configured else base / ".kimi-code"
    if not state.is_absolute():
        state = base / state
    return _roots([state, base / ".agents" / "skills"])


def is_runtime_read_path(path: str | Path) -> bool:
    """Whether a denied read belongs to Kimi's fixed startup surface."""
    candidate = _resolved(path)
    if candidate is None:
        return False
    for root in runtime_read_roots():
        if candidate == root or root in candidate.parents:
            return True
    return False


def explicit_skill_dirs(cwd: Path) -> list[Path]:
    """Pin Kimi skill discovery to roots already inside the safe profile.

    Without ``--skills-dir``, Kimi watches the entire OS home directory while
    discovering ``~/.agents/skills``.  Seatbelt cannot grant that watcher
    without also exposing the names of every home entry.  Explicit roots skip
    both automatic user/project discovery and that broad watcher.
    """
    roots = runtime_read_roots()
    candidates = [
        roots[0] / "skills",
        *roots[1:],
        Path(cwd) / ".kimi-code" / "skills",
        Path(cwd) / ".agents" / "skills",
    ]
    return [root for root in _roots(candidates) if root.is_dir()]


def scoped_environment(env: dict[str, str]) -> tuple[dict[str, str], Path]:
    """Give Kimi a private HOME without disconnecting its login/session state."""
    isolated_home = Path(tempfile.mkdtemp(prefix="geoforge-kimi-home-"))
    try:
        isolated_home.chmod(0o700)
        updated = dict(env)
        updated["HOME"] = str(isolated_home)
        updated["KIMI_CODE_HOME"] = str(runtime_read_roots()[0])
        return updated, isolated_home
    except Exception:
        shutil.rmtree(isolated_home, ignore_errors=True)
        raise


def profile(*, cwd: Path, extra_dirs: list[str] | None = None,
            cfg=None, ki_root: Path | None = None, pol=None) -> str:
    """Build a Seatbelt profile for one Kimi invocation.

    Reads are allowed from the project, selected KI/model roots and Kimi's own
    state.  Other files below the user's home directory are hidden.  Writes
    are limited to the project/model roots, Kimi state and temporary files.
    System libraries and executables outside the home directory remain
    readable so the CLI and scientific software can start normally.
    """
    home = Path.home().resolve()
    runtime_roots = runtime_read_roots(home)
    kimi_state = runtime_roots[0]

    common = [cwd, *(extra_dirs or []), *_policy_paths(pol, {"read", "exec"})]
    writable = [cwd, *_policy_paths(pol, {"write"})]
    if cfg is not None:
        common.append(getattr(cfg, "root", ""))
        writable.append(getattr(cfg, "root", ""))
    if ki_root is not None:
        common.append(ki_root)

    # The installed Kimi binary commonly lives below ~/.local.  Add only its
    # resolved launcher directory, not all of ~/.local.
    launcher = shutil.which("kimi")
    if launcher:
        common.append(Path(launcher).resolve().parent)
    read_roots = _roots([*common, *runtime_roots])
    write_roots = _roots([*writable, kimi_state, Path(tempfile.gettempdir())])

    lines = [
        "(version 1)",
        "(debug deny)",
        # Hide the home directory first, then reopen only approved roots.  The
        # order matters for nested paths on macOS Seatbelt.
        f"(deny file-read* (subpath {_literal(home)}))",
    ]
    # Node's realpath/watcher setup stats path ancestors before it opens an
    # approved child.  Metadata on ancestors reveals no file content, but
    # without it Kimi emits EPERM at (for example) ~/.agents/skills even when
    # that child itself is readable.
    for ancestor in reversed(home.parents):
        if str(ancestor) != "/":
            lines.append(
                f"(allow file-read-metadata (literal {_literal(ancestor)}))")
    lines.append(f"(allow file-read-metadata (literal {_literal(home)}))")
    metadata_parents: set[Path] = set()
    for root in read_roots:
        try:
            root.relative_to(home)
        except ValueError:
            continue
        parent = root.parent
        while parent != home and home in parent.parents:
            metadata_parents.add(parent)
            parent = parent.parent
    for parent in sorted(metadata_parents, key=lambda item: (len(item.parts), str(item))):
        lines.append(
            f"(allow file-read-metadata (literal {_literal(parent)}))")
    for root in read_roots:
        lines.append(f"(allow file-read* (subpath {_literal(root)}))")

    # Console-less children still need these device files.  Temporary output
    # is needed by Python, compilers and the CLIs themselves.
    for device in ("/dev/null", "/dev/zero", "/dev/random", "/dev/urandom"):
        lines.append(f"(allow file-write* (literal {_literal(device)}))")
    lines.append('(allow file-write* (regex #"^/dev/fd/[0-9]+$"))')
    for root in write_roots:
        lines.append(f"(allow file-write* (subpath {_literal(root)}))")
    lines.extend([
        '(allow file-write* (regex #"^/private/var/folders/[^/]+/[^/]+/[CT]/"))',
        "(deny file-write*)",
        # Network, process execution, system libraries and other non-file
        # operations retain their normal macOS permissions.
        "(allow default)",
        "",
    ])
    return "\n".join(lines)


def wrap(argv: list[str], **kwargs) -> tuple[list[str], Path]:
    """Wrap argv in the macOS sandbox and return its temporary profile.

    The caller owns the returned file and must call :func:`cleanup` after the
    process exits.  Fail closed when the requested boundary is unavailable.
    """
    if sys.platform != "darwin":
        raise RuntimeError("project-scoped Kimi is currently available on macOS only")
    executable = Path("/usr/bin/sandbox-exec")
    if not executable.is_file():
        raise RuntimeError("macOS sandbox-exec is not available")
    fd, raw = tempfile.mkstemp(prefix="geoforge-kimi-", suffix=".sb")
    target = Path(raw)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(profile(**kwargs))
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        target.unlink(missing_ok=True)
        raise
    return [str(executable), "-f", str(target), *argv], target


def cleanup(path: Path | None) -> None:
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def cleanup_home(path: Path | None) -> None:
    """Remove only the private HOME created by :func:`scoped_environment`."""
    if path is not None:
        shutil.rmtree(path, ignore_errors=True)
