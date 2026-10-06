"""Agent-owned software setup and human handoffs.

The server deployment succeeds because a coding agent owns the complete loop:
read the KI, run the model's checks, repair the environment, and try again.
Desktop setup uses the same contract.  This module contains the small amount of
state the UI needs around that agent:

* a prepared, writable KI workspace;
* one structured request when the agent genuinely needs a person; and
* an inbox for a licence- or login-gated file the user supplies.

It deliberately does not decide how to install scientific software.  That is
the agent's job, using the KI and its KDT-produced diagnostics.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import sys
import time
import uuid
from pathlib import Path

from . import install, install_locations, paths, port

REQUEST_FILE = "setup-request.json"
PARTIAL_SUFFIXES = (".part", ".partial", ".crdownload", ".download", ".tmp", ".aria2", ".bc!")
USER_FILES_DIR = "user-files"
LOG_FILE = "setup-agent.log"
REQUEST_KINDS = {"download", "licence", "login", "permission", "choice", "other"}


def _request_options(value) -> list[dict]:
    """Normalise short choices written by either an API or a CLI agent."""
    if not isinstance(value, list):
        return []
    out = []
    for index, item in enumerate(value):
        if isinstance(item, str):
            raw = {"label": item}
        elif isinstance(item, dict):
            raw = item
        else:
            continue
        label = " ".join(str(raw.get("label") or "").split())[:240]
        if not label:
            continue
        option_id = re.sub(r"[^A-Za-z0-9_.-]", "-", str(
            raw.get("id") or f"option-{index + 1}"))[:80].strip("-.")
        out.append({
            "id": option_id or f"option-{index + 1}",
            "label": label,
            "description": str(raw.get("description") or "").strip()[:2000],
            "response": str(raw.get("response") or label).strip()[:2000],
        })
    return out


def choice_response(pending: dict, action: dict | None) -> dict | None:
    """Resolve an explicit answer, never a clarification or an approval card.

    A custom answer is a planning value, not a permission or download grant.
    The caller still owns the existing permission-option side effects.
    """
    if (not action or pending.get("status") != "waiting"
            or str(action.get("request_id")) != str(pending.get("id"))):
        return None
    option_id = str(action.get("option_id") or "")
    if option_id == "__custom_answer__":
        note = str(action.get("note") or "").strip()
        if (pending.get("kind") != "choice" or pending.get("allow_note") is False
                or pending.get("plan_review") or not note
                or str(pending.get("id", "")).startswith(("flow:", "flow-"))):
            return None
        return {"id": option_id, "label": "Custom answer", "response": note}
    return next((item for item in pending.get("options") or []
                 if isinstance(item, dict) and str(item.get("id")) == option_id), None)


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def request(root: Path, *, archive_obsolete: bool = True) -> dict | None:
    """Return the current structured human request, if one exists.

    Read-only status projections disable legacy permission-request archival.
    Existing callers retain the migration behavior.
    """
    raw = _read_json(Path(root) / REQUEST_FILE)
    if not raw:
        return None
    # CLI agents write this file directly, so treat every field as untrusted
    # display data just like an imported KI. In particular, never let an agent
    # turn the official-page link into a javascript: URL.
    kind = str(raw.get("kind") or "other").lower()
    expected = str(raw.get("expected_path") or "").strip()[:1000]
    if kind == "permission" and expected:
        # v0.6.34 could persist a popup for Kimi's automatic shared-skill
        # discovery.  That folder is now part of Kimi's read-only runtime
        # surface, so archive the stale request instead of showing it forever.
        from .kimi_security import is_runtime_read_path
        if is_runtime_read_path(expected):
            if archive_obsolete:
                clear_request(root)
            return None
    url = str(raw.get("url") or "").strip()[:2000]
    return {
        **raw,
        "id": re.sub(r"[^A-Za-z0-9_.-]", "", str(
            raw.get("id") or raw.get("created_at") or "request"))[:100] or "request",
        "status": raw.get("status") if raw.get("status") in ("waiting", "ready") else "waiting",
        "kind": kind if kind in REQUEST_KINDS else "other",
        "title": " ".join(str(raw.get("title") or "Help needed").split())[:160],
        "message": str(raw.get("message") or "").strip()[:8000],
        "url": url if url.startswith(("https://", "http://")) else None,
        "expected_path": expected or None,
        "command": str(raw.get("command") or "").strip()[:2000] or None,
        "resume_hint": str(raw.get("resume_hint") or "").strip()[:4000] or None,
        "user_note": str(raw.get("user_note") or "").strip()[:4000] or None,
        "options": _request_options(raw.get("options")),
        "allow_note": bool(raw.get("allow_note", True)),
    }


def request_user(root: Path, payload: dict) -> dict:
    """Record the one action an agent cannot honestly perform itself."""
    kind = str(payload.get("kind") or "other").lower()
    if kind not in REQUEST_KINDS:
        kind = "other"
    title = " ".join(str(payload.get("title") or "Help needed").split())[:160]
    message = str(payload.get("message") or "").strip()[:8000]
    url = str(payload.get("url") or "").strip()[:2000]
    if url and not url.startswith(("https://", "http://")):
        url = ""
    expected = str(payload.get("expected_path") or "").strip()[:1000]
    command = str(payload.get("command") or "").strip()[:2000]
    resume = str(payload.get("resume_hint") or "").strip()[:4000]
    doc = {
        "id": uuid.uuid4().hex[:12],
        "status": "waiting",
        "kind": kind,
        "title": title,
        "message": message,
        "url": url or None,
        "expected_path": expected or None,
        "command": command or None,
        "resume_hint": resume or None,
        "options": _request_options(payload.get("options")),
        "allow_note": bool(payload.get("allow_note", True)),
        "created_at": time.time(),
    }
    path = Path(root) / REQUEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def request_for_kimi_permission(root: Path, path: str) -> dict | None:
    """Turn one macOS sandbox denial into a specific user decision.

    The denied path comes from Kimi's process stderr, not from the model's
    prose.  Approval remains explicit and project-local; this function never
    widens the policy by itself.
    """
    candidate = Path(str(path)).expanduser()
    if not candidate.is_absolute():
        return None
    try:
        candidate = candidate.resolve(strict=False)
    except OSError:
        candidate = candidate.absolute()
    from .kimi_security import is_runtime_read_path
    if is_runtime_read_path(candidate):
        # Startup-owned paths are already available read-only in the macOS
        # profile.  Never turn them into a project decision.
        return None
    current = request(root)
    if current and current.get("status") == "waiting":
        return current
    home = Path.home().resolve()
    # Asking for the whole home directory is equivalent to Full computer
    # access and must use the clearly labelled global setting instead.
    if candidate == home or candidate in home.parents:
        return None
    return request_user(root, {
        "kind": "permission",
        "title": "Kimi needs access to one folder",
        "message": (
            f"Kimi tried to read {candidate}. GeoForge blocked it because it is "
            "outside this project. Choose whether this project may read that "
            "specific path; no other personal folders will be opened."
        ),
        "expected_path": str(candidate),
        "allow_note": False,
        "options": [
            {
                "id": "allow-kimi-read-once",
                "label": "Allow once",
                "description": "Read this path for the next Kimi turn only, then close it again.",
                "response": f"Allow Kimi to read {candidate} once.",
            },
            {
                "id": "allow-kimi-read-project",
                "label": "Always for this project",
                "description": "Remember read-only access in this project's policy.",
                "response": f"Allow Kimi to read {candidate} in this project.",
            },
        ],
        "resume_hint": "Retry the interrupted turn after applying the selected project permission.",
    })


def request_for_provider_connection(root: Path, provider: str,
                                    service: str) -> dict:
    """Surface a provider network failure as a real setup handoff.

    A failed OAuth/DNS call cannot be repaired by the model-install agent.  If
    it remains only in the black setup transcript, users reasonably conclude
    that the scientific installation froze.  Keep it separate from KI status
    and tell the user exactly which outside service could not be reached.
    """
    current = request(root)
    if current and current.get("status") == "waiting":
        return current
    label = "Kimi Code" if str(provider).lower() == "kimi" else str(provider)
    host = str(service or "the provider service").strip()[:240]
    return request_user(root, {
        "kind": "login",
        "title": f"{label} cannot connect",
        "message": (
            f"{label} could not reach {host}. The model installation has not "
            "failed; its setup agent stopped because the AI connection is "
            "offline. Check DNS, VPN, or your network. If this provider needs "
            "a proxy on this Mac, open AI Settings, enable the proxy for "
            f"{label}, save, then continue the repair."
        ),
        "allow_note": False,
        "resume_hint": (
            f"Retry {label} after its connection to {host} is available, or "
            "select another AI provider on the setup page."
        ),
    })


def data_path_present(path: Path) -> bool:
    """A nonempty payload exists, not just a directory or download temporary file.

    This is a handoff check, not proof of dataset completeness or scientific
    validity. The KI still has to inspect the delivered data before running.
    Do not follow symlinks or scan hidden cache directories.
    """
    partial = PARTIAL_SUFFIXES

    def present(candidate: Path) -> bool:
        try:
            if candidate.is_symlink() or candidate.name.startswith("."):
                return False
            if candidate.name.lower().endswith(partial):
                return False
            if candidate.is_file():
                return candidate.stat().st_size > 0
            if candidate.is_dir():
                return any(present(child) for child in candidate.iterdir())
        except OSError:
            return False
        return False

    return present(Path(path))


def download_placed(request: dict | None) -> bool:
    """True only when every requested destination contains a candidate payload."""
    rows = (request or {}).get("rows") or []
    paths = [str(r.get("expected_path") or "").strip() for r in rows if isinstance(r, dict)]
    if not paths:
        paths = [str((request or {}).get("expected_path") or "").strip()]
    if not all(paths):
        return False  # no destination means delivery cannot be verified
    return all(data_path_present(Path(p).expanduser()) for p in paths)


def resume(root: Path, note: str = "") -> dict | None:
    """Mark the user's part complete so the next agent turn can continue."""
    path = Path(root) / REQUEST_FILE
    doc = request(root)
    if not doc:
        return None
    doc["status"] = "ready"
    doc["user_note"] = str(note).strip()[:4000]
    doc["resolved_at"] = time.time()
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


def clear_request(root: Path) -> None:
    """Archive a fulfilled request without losing the audit trail."""
    path = Path(root) / REQUEST_FILE
    if not path.exists():
        return
    archive = path.with_name(f"setup-request-{int(time.time())}.json")
    try:
        path.replace(archive)
    except OSError:
        pass


#: What each package manager calls the build tools a model source needs. Same
#: tools everywhere, different names — Homebrew's one `gcc` formula carries the
#: Fortran compiler that Debian splits into `gfortran`, and the NetCDF Fortran
#: bindings are a separate package almost everywhere.
#:
#: Every platform gets a real command. macOS used to be the only one that did;
#: Linux and Windows were told to "use your system package manager" and left to
#: work out that `nc-config` comes from `libnetcdf-dev`.
_PACKAGES: dict[str, dict[str, str]] = {
    "brew": {
        "git": "git", "cmake": "cmake", "make": "make", "gmake": "make",
        "gcc": "gcc", "g++": "gcc", "gfortran": "gcc",
        "mpicc": "mpich", "mpicxx": "mpich", "mpif90": "mpich",
        "nc-config": "netcdf", "nf-config": "netcdf-fortran",
        "pkg-config": "pkg-config",
    },
    "apt": {
        "git": "git", "cmake": "cmake", "make": "make", "gmake": "make",
        "gcc": "gcc", "g++": "g++", "gfortran": "gfortran",
        "mpicc": "libmpich-dev", "mpicxx": "libmpich-dev", "mpif90": "libmpich-dev",
        "nc-config": "libnetcdf-dev", "nf-config": "libnetcdff-dev",
        "pkg-config": "pkg-config",
    },
    "dnf": {
        "git": "git", "cmake": "cmake", "make": "make", "gmake": "make",
        "gcc": "gcc", "g++": "gcc-c++", "gfortran": "gcc-gfortran",
        "mpicc": "mpich-devel", "mpicxx": "mpich-devel", "mpif90": "mpich-devel",
        "nc-config": "netcdf-devel", "nf-config": "netcdf-fortran-devel",
        "pkg-config": "pkgconf-pkg-config",
    },
    "pacman": {
        "git": "git", "cmake": "cmake", "make": "make", "gmake": "make",
        "gcc": "gcc", "g++": "gcc", "gfortran": "gcc-fortran",
        "mpicc": "mpich", "mpicxx": "mpich", "mpif90": "mpich",
        "nc-config": "netcdf", "nf-config": "netcdf-fortran",
        "pkg-config": "pkgconf",
    },
    # Windows has no system package manager that carries a Fortran toolchain or
    # NetCDF; MSYS2 is how these arrive in practice, and its packages are
    # prefixed per target environment.
    "msys2": {
        "git": "git", "cmake": "mingw-w64-x86_64-cmake",
        "make": "make", "gmake": "make",
        "gcc": "mingw-w64-x86_64-gcc", "g++": "mingw-w64-x86_64-gcc",
        "gfortran": "mingw-w64-x86_64-gcc-fortran",
        "mpicc": "mingw-w64-x86_64-msmpi", "mpicxx": "mingw-w64-x86_64-msmpi",
        "mpif90": "mingw-w64-x86_64-msmpi",
        "nc-config": "mingw-w64-x86_64-netcdf",
        "nf-config": "mingw-w64-x86_64-netcdf-fortran",
        "pkg-config": "mingw-w64-x86_64-pkgconf",
    },
}

#: How to invoke each manager. Kept next to the tables so a new manager is one
#: entry in each, not a new branch in the message-building code.
_INSTALLERS: dict[str, str] = {
    "brew": "brew install",
    "apt": "sudo apt install",
    "dnf": "sudo dnf install",
    "pacman": "sudo pacman -S",
    "msys2": "pacman -S",
}


def _package_manager() -> str | None:
    """The manager to advise on this machine, or None if we cannot tell.

    Detected by what is actually on PATH rather than by distro name: a user on
    a derivative still has the tool their base ships.
    """
    if sys.platform == "darwin":
        return "brew" if shutil.which("brew") else None
    if sys.platform == "win32":
        # MSYS2's pacman is only ours to call if it is genuinely on PATH; the
        # instructions are worth printing either way, so callers fall back to
        # the generic message when this returns None.
        return "msys2" if shutil.which("pacman") else None
    for manager in ("apt", "dnf", "pacman"):
        if shutil.which(manager):
            return manager
    return None


def _shell_name() -> str:
    """What the user calls the place they type commands."""
    return "PowerShell" if sys.platform == "win32" else "Terminal"


def _install_command(missing: list[str]) -> str:
    """One copy-pasteable install line for the tools this machine lacks."""
    manager = _package_manager()
    if not manager:
        return ""
    table = _PACKAGES[manager]
    packages = list(dict.fromkeys(table[x] for x in missing if x in table))
    if not packages:
        return ""
    return f"{_INSTALLERS[manager]} " + " ".join(packages)


def request_for_system_dependencies(root: Path, software: dict) -> dict | None:
    """Turn a failed machine-level dependency check into a visible handoff.

    An AI agent may inspect Homebrew, but GeoForge intentionally does not let an
    API-driven agent change the user's whole Mac. If the deterministic install
    check already knows which commands are missing, do not depend on the model
    remembering to translate that failure into ``setup-request.json``.
    """
    current = request(root)
    if current and current.get("status") == "waiting":
        return current
    steps = software.get("steps") or []
    failed = next((s for s in steps if isinstance(s, dict)
                   and s.get("name") == "system-deps"
                   and not s.get("ok") and not s.get("recovered")
                   and not s.get("skipped")), None)
    if not failed:
        return None
    detail = str(failed.get("detail") or "")
    match = re.search(r"not on PATH:\s*(.+?)(?:\s+[—-]\s+|$)", detail)
    missing = [item.strip() for item in match.group(1).split(",")] if match else []
    missing = [item for item in missing if item]

    command = _install_command(missing)
    names = ", ".join(missing) if missing else "required build libraries"
    message = (
        f"The model build needs {names}. These are shared system tools, so the "
        "setup agent will not install them across your system without you. "
        + (f"Run the command below in {_shell_name()}, then return here and continue."
           if command else "Install them with your system package manager, then return here and continue.")
    )
    return request_user(root, {
        "kind": "permission",
        "title": "Install the required build libraries",
        "message": message,
        "command": command,
        "resume_hint": "Re-check the system tools, build the official source, and run preflight again.",
    })


def safe_upload_name(name: str) -> str:
    """A browser filename, reduced to one harmless local path component."""
    clean = re.sub(r"[^A-Za-z0-9._+-]", "_", Path(name).name)[:180]
    if clean in ("", ".", ".."):
        raise ValueError("invalid upload filename")
    return clean


def save_upload(root: Path, name: str, blob: bytes) -> Path:
    inbox = Path(root) / USER_FILES_DIR
    inbox.mkdir(parents=True, exist_ok=True)
    target = inbox / safe_upload_name(name)
    target.write_bytes(blob)
    return target


def uploads(root: Path) -> list[dict]:
    inbox = Path(root) / USER_FILES_DIR
    if not inbox.is_dir():
        return []
    return [
        {"name": p.name, "path": str(p), "size": p.stat().st_size,
         "modified_at": p.stat().st_mtime}
        for p in sorted(inbox.iterdir()) if p.is_file()
    ]


def runtime_command(models_dir: Path, model: str, root: Path) -> str:
    """The built-in recipe command an agent may use as evidence or a fast path."""
    if getattr(sys, "frozen", False):
        argv = [sys.executable]
        env = []
    else:
        package_parent = Path(__file__).resolve().parent.parent
        argv = [sys.executable, "-m", "kiss_cli"]
        env = [f"PYTHONPATH={package_parent}"]
    argv += ["--models", str(models_dir), "init", model, "-w", str(root)]
    return " ".join([*(shlex.quote(x) for x in env), *(shlex.quote(x) for x in argv)])


def prepare_common(cfg, repo_root: Path) -> Path:
    """Materialise helpers; versioned snapshots never overwrite an older copy."""
    source = Path(repo_root) / "ki_tools_common"
    if not source.is_dir():
        raise ValueError(
            f"GeoForge's bundled ki_tools_common is missing (expected {source})")
    from . import ki_updates
    snapshot = ki_updates._read_json(Path(repo_root) / ki_updates.SNAPSHOT_MANIFEST)
    if snapshot:
        import hashlib
        import tempfile
        binding = {
            "source_commit": snapshot.get("source_commit"),
            "source_tree": (snapshot.get("trees") or {}).get("shared_tools"),
            "roles": {key: str(value) for key, value in sorted(cfg.roles.items())
                      if key != "ki_tools_common"},
        }
        identity = hashlib.sha256(json.dumps(binding, sort_keys=True).encode()).hexdigest()
        target = Path(cfg.root) / "ktc" / identity[:12]
        cfg.roles["ki_tools_common"] = target
        marker = ".geoforge-common.json"
        def source_files(root):
            return {name: digest for name, digest in ki_updates._file_digests(root).items()
                    if name != marker and not any(part == "__pycache__" or part.endswith(".egg-info")
                                                for part in Path(name).parts)
                    and not name.endswith((".pyc", ".pyo"))}
        if target.exists():
            saved = ki_updates._read_json(target / marker)
            actual = source_files(target)
            if saved.get("binding_sha256") != identity or saved.get("files") != actual:
                raise ValueError(f"Pinned shared helpers changed locally; preserved without overwriting: {target}")
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".incoming-", dir=target.parent) as temporary:
            staged = Path(temporary) / "package"
            report = port.materialise(source, staged, cfg)
            if report.unresolved or report.corrupted:
                raise ValueError("cannot prepare snapshot ki_tools_common: unresolved or corrupted paths")
            ki_updates._atomic_json(staged / marker, {
                **binding, "binding_sha256": identity,
                "files": source_files(staged)})
            # Only a new directory is installed. Existing revisions and local
            # edits remain intact, including copies used by running projects.
            if target.exists():
                raise ValueError(f"Shared helper destination appeared during preparation: {target}")
            staged.rename(target)
        return target
    target = Path(cfg.roles.get("ki_tools_common") or (cfg.root / "ki_tools_common"))
    report = port.materialise(source, target, cfg)
    if report.unresolved or report.corrupted:
        detail = "; ".join(filter(None, [
            f"unresolved placeholders: {', '.join(sorted(report.unresolved))}"
            if report.unresolved else "",
            f"corrupted paths: {'; '.join(report.corrupted[:3])}"
            if report.corrupted else "",
        ]))
        raise ValueError(f"cannot prepare bundled ki_tools_common: {detail}")
    return target


def prepare(ki, man, root: Path, repo_root: Path, models_dir: Path):
    """Create the writable workspace and provider instruction files.

    This is bootstrap only.  It does not acquire or verify the simulator; the
    agent owns those decisions and retries.
    """
    from . import handoff

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cfg_file = root / paths.CONFIG_NAME
    cfg = paths.KissConfig.load(root) if cfg_file.exists() else paths.KissConfig.default(root)
    cfg.python = install.runtime_python(cfg.python)
    cfg_file.write_text(cfg.dumps(), encoding="utf-8")

    prepare_common(cfg, repo_root)
    cfg_file.write_text(cfg.dumps(), encoding="utf-8")
    live = root / "ki"
    report = port.materialise(ki.root, live, cfg)
    if report.unresolved or report.corrupted:
        detail = "; ".join(filter(None, [
            f"unresolved placeholders: {', '.join(sorted(report.unresolved))}"
            if report.unresolved else "",
            f"corrupted paths: {'; '.join(report.corrupted[:3])}"
            if report.corrupted else "",
        ]))
        raise ValueError(f"cannot prepare the KI workspace: {detail}")

    # This is application infrastructure, not a model-specific dependency the
    # agent or user should have to locate. Keep an offline, materialised copy
    # beside every shared model workspace before any preflight or chat starts.
    # Helpers were bound before KI paths were materialised above.

    live_ki = type(ki)(name=ki.name, root=live)
    # A small number of older KDT KIs declare their tools below the original
    # server layout (for example
    # ``KISSPATH_KI_ROOT/Delft3D/knowledge_infrastructure/tools``).  The
    # desktop deliberately materialises a portable KI at ``<workspace>/ki``.
    # Create the same compatibility links used by the deterministic installer
    # before the first preflight, even when the setup is agent-owned and no
    # model binary has been acquired yet.  Otherwise a user-selected install
    # folder is recorded correctly but the agent is handed a false "tools not
    # found" failure.
    install.place_where_the_ki_expects(live_ki, None, cfg, None)
    install_locations.record(ki.name, root, cfg, ki_root=live)
    handoff.write_setup(
        live_ki, man, cfg, root,
        built_in_command=runtime_command(models_dir, ki.name, root),
    )
    return live_ki, cfg


CLI_SESSION_FILE = ".geoforge-setup-session.json"


def cli_session(root: Path, provider: str) -> str | None:
    """The CLI's own session id from the last setup run of this provider, if any."""
    path = Path(root) / CLI_SESSION_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = doc.get(provider) if isinstance(doc, dict) else None
    sid = (entry or {}).get("id") if isinstance(entry, dict) else None
    return str(sid) if sid else None


def remember_cli_session(root: Path, provider: str, session_id: str) -> None:
    path = Path(root) / CLI_SESSION_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            doc = {}
    except (OSError, ValueError):
        doc = {}
    doc[provider] = {"id": str(session_id), "saved_at": time.time()}
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")


def resume_message(resumed: dict, root: Path) -> str:
    """What the continuing agent needs after the user's action: no restart, no re-diagnosis."""
    return (
        "The user has completed the request you made.\n"
        f"User note: {resumed.get('user_note') or '(none)'}\n"
        f"Files supplied: {json.dumps(uploads(root), ensure_ascii=False)}\n"
        f"Your resume hint: {resumed.get('resume_hint') or '(none)'}\n"
        "Continue exactly where you stopped. Do not re-read the KI, re-run the diagnosis or "
        "repeat installation steps that already succeeded; verify only the step that was "
        "blocked, then finish the setup and run the KI preflight."
    )


def agent_task(ki, cfg, root: Path, *, resumed: dict | None = None,
               initial_failure: str = "",
               installation_mode: str = "new",
               existing_paths: list[str] | None = None,
               installation_only: bool = False,
               manifest_hint: str = "") -> str:
    """Short task layered over the provider's auto-loaded setup instructions."""
    notes = getattr(ki, "installation_notes", None)
    experience = (
        f"\nRead `{notes}` for this KI's recorded installation experience on "
        "the current operating system. Recheck the reported paths and errors "
        "on this machine; an old failed attempt is not proof that a portable "
        "installation is impossible.\n" if notes else ""
    )
    prior = ""
    if resumed:
        prior = (
            "\nThe user has completed the earlier request.\n"
            f"User note: {resumed.get('user_note') or '(none)'}\n"
            f"Files supplied: {json.dumps(uploads(root), ensure_ascii=False)}\n"
            f"Resume hint: {resumed.get('resume_hint') or '(inspect the workspace)'}\n"
        )
    known_failure = ""
    if initial_failure.strip():
        known_failure = (
            "\nGeoForge already ran the deterministic preflight. Start from this "
            "failure instead of spending turns rediscovering it:\n"
            f"{initial_failure.strip()[:12000]}\n"
        )
    existing_paths = [str(path) for path in (existing_paths or [])]
    if installation_mode == "existing":
        existing = f"""
The user chose **Use software already installed**. Do not download, clone,
compile, upgrade, overwrite, or delete that external installation. Candidate
locations are:

{json.dumps(existing_paths, ensure_ascii=False, indent=2)}

Inspect the candidates and identify the real {ki.name} executable and support
tree. Create links or local configuration only inside `{root}` so the
materialised KI resolves to the existing software, then run the KI's real
preflight. If one candidate is used, write its canonical path to
`{Path(root) / install_locations.RECORD_FILE}` as `resolved_existing_path`;
preserve the other record fields. If none is valid, create one structured
request asking the user for the installation or executable path. Do not fall
back to a new installation unless the user explicitly switches modes.
"""
    else:
        existing = """
The user chose **Install or build a new copy**. Keep all model software inside
the configured model installation workspace unless a structured user request
is required.
"""
    if installation_only:
        manifest_guidance = (
            "\n\n[MANIFEST-SPECIFIC INSTALLATION ROUTE]\n"
            + manifest_hint.strip()
            if manifest_hint.strip() else ""
        )
        from . import runnable
        import_contract = runnable.declared_imports(ki)
        executable_contract = runnable.declared(ki)
        variant = (getattr(ki, "meta", {}) or {}).get("impl_id")
        from .python_script import VARIANTS
        variant_info = VARIANTS.get(ki.name)
        variant_guidance = ""
        if variant_info and variant == variant_info[0]:
            variant_guidance = (
                f"This KI explicitly declares {variant}, an existing bundled Python implementation. "
                f"Install that declared implementation using the original {variant_info[1]}; "
                "do not replace it with another implementation or an official upstream product. "
                "Its fixed installation probe is --help (exit 0), not --version. "
                "Read its current-platform manifest for all required dependencies. This result establishes "
                "only the declared variant, never official upstream installation or equivalence.\n"
            )
        contract = ("The independent installation check will also verify these KI Python imports: "
                    + json.dumps(import_contract) + ".\n"
                    "Install their real dependencies in a workspace environment even when the model "
                    "itself is a native executable. GeoForge supplies ki_tools_common from the bundled "
                    "workspace library; do not replace it with an unrelated PyPI project.\n"
                    "Declared executable locations for this materialised KI: "
                    + json.dumps(executable_contract) + ".\n"
                    "If upstream builds elsewhere, reconcile its real product with the install "
                    "configuration so the independent check can locate it; do not report completion "
                    "solely because a binary exists at another path.\n")
        return f"""Install {ki.name} on this machine now.
{experience}

{contract}
{variant_guidance}
This is an **installation-only stress test**, not a scientific verification
run. Install the declared implementation and its runtime dependencies
inside the selected workspace. You may use a cheap startup probe such as
`--version` or `--help` to prove that the executable loads, links, and responds.

Do NOT run the KI preflight, examples, reference cases, simulations,
calibration, data preparation, or result-generation tools. Do NOT download
forcing, observation, parameter, initial-condition, boundary-condition, or
reference-output datasets. Missing project/scientific data is not an
installation failure in this test.

Keep diagnosing build and runtime problems until the official executable or
declared Python package responds. Do not substitute a toy implementation,
launcher, or mock executable. Never fabricate a compatibility distribution,
standard-library shadow module, import hook, hand-written package metadata, or
wheel merely to make an import succeed; patch the pinned official source at its
real portability boundary and build/install that source instead. Do not inspect
or copy artifacts from another
GeoForge project or installation workspace: they are not provenance for this
test. Never create placeholder model/data files merely to satisfy a preflight
existence check. Do not create or overwrite GeoForge's `status.json` or
`installation-test.json`; GeoForge writes those records only after its own
independent runnable check.

Converge on evidence instead of repeatedly reconsidering the same hypothetical
blocker. Once the manifest gives an authorized portable/build route, execute it
and use the actual command result to choose the next action. Do not spend more
steps restating an untested concern, browsing for alternatives, or preparing a
human request while an authorized route remains untried. A previous successful
stage recorded in the manifest is evidence that the route is viable on this OS.

An absent compiler, interpreter, package manager, or other dependency is not
by itself a reason to ask the user. Before requesting human action, try an
official, pinned workspace-local distribution or portable archive using the
available `curl`/`wget`, archive, package-manager, and build tools. Keep it
inside this model workspace and invoke it by its absolute workspace path; it
does not need to be installed system-wide or added to the global PATH. Prefer
an upstream checksum and record the exact version/source. On Windows, a needed
CPython minor version can be staged without administrator access from the
official Python NuGet package, extracted inside the workspace, and invoked via
its `tools/python.exe`. Do not bypass an upstream `Requires-Python` or other
runtime compatibility bound merely to make an import probe green. Do not ask
the user merely because a command is missing from PATH. Likewise, the absence
of a prebuilt Python wheel does not prove a Windows source build is impossible:
when the upstream build uses CMake/Meson and C/Fortran, actually try a pinned
workspace-local GCC/gfortran toolchain and preserve its runtime DLLs before
claiming that MSVC or a system-wide compiler is mandatory. A standalone WinLibs
UCRT archive is one valid Windows route: it includes GCC, gfortran, GNU make,
and the associated runtime DLLs and can be extracted entirely in the workspace.
Its native build driver is normally `mingw32-make.exe`; GeoForge permits that
workspace-local executable just like `make`. Prefer it over starting a broad
MSYS2 shell or package manager, and patch only the workspace copy of an upstream
makefile when POSIX-only path or shell syntax needs a Windows portability fix.
Such build-system portability edits are allowed; do not change model algorithms
or scientific defaults. An `env.PATH` prefix applies only to the current tool
call, so provide it again on every generator, configure, compile, and link call
that relies on staged tools.
Use `replace_work_text` for a small exact source or build-file portability edit;
it does not require a shell, line-numbered patch hunk, or generated edit script.
An official Windows GUI installer is not automatically a human blocker. Before
asking the user to run it, try a pinned workspace-local archive extractor such
as the official portable 7-Zip `7zr.exe`/`7z.exe` or `innoextract`, extract only
inside this setup workspace, and verify the exact declared asset. Do not bypass
or auto-accept an installer licence or substitute a different model version.
When an official dependency is distributed through conda-forge only, stage the
official standalone micromamba executable in this workspace and use explicit
workspace-local `--root-prefix` and `--prefix` arguments for every create or
install call. GeoForge permits that bounded package-manager route but not
`micromamba run`; verify with the environment's interpreter/executable directly.
The `micro.mamba.pm/api/micromamba/win-64/latest` endpoint returns a tar.bz2
archive, not a directly runnable file: extract `Library/bin/micromamba.exe` and
confirm it has a Windows PE `MZ` header before executing it.
On deeply nested Windows workspaces, put CMake build and install prefixes in
short top-level directories such as `b/` and `p/` before diagnosing a path-length
failure. Use the shortest possible names directly below the model workspace for
package-manager roots and environments too; do not create redundant nesting
such as `b/env/name` or `b/root/pkgs` before claiming MAX_PATH requires a system
change. For micromamba on Windows, also set `CONDA_PKGS_DIRS` to a short flat
workspace-top-level directory such as `pc`; this avoids its longer default
URL-shaped cache tree and often works even when LongPathsEnabled is zero. The
normal compiler binutils (`ar`, `ranlib`, `dlltool`, `gendef`, `nm`,
`objdump`, `strip`) are permitted when staged inside the workspace.
For source generators, use a pinned portable release such as winflexbison on
Windows; flex/bison code generation is part of compilation and is permitted in
installation-only mode. Do not ask for approval merely to run those staged
build helpers with the upstream grammar/source arguments.
For models that require netCDF-C but have no usable Windows SDK, build the
official netCDF-C source workspace-locally with unnecessary HDF5/DAP/tests
disabled when the classic API is sufficient. A build being large or likely to
take the rest of this turn is not a permission question: start it and continue
until the actual time limit or a concrete build error is reached.
Do not merely speculate that MinGW and an MSVC-built CPython are incompatible;
configure the real upstream build with the staged compilers and capture the
actual compiler or linker result. Base any handoff on a concrete
compiler/linker failure, not on a generic package-build message.

Only when the dependency has no usable workspace-local distribution, or a
licence, login, protected download, system privilege, or scientifically
meaningful choice truly requires a person, create one structured setup request
and stop. If you create or select a Python environment, record its real
interpreter in `{Path(root) / 'kiss.toml'}` under `kiss.python`; do not leave
GeoForge pointing at the system Python after the package was installed into a
workspace venv.

Preserve the absolute environment launcher path, even when it is a symlink.
Do NOT replace a venv launcher with its realpath or symlink target: launching the
base interpreter loses the venv and its packages. Verify that sys.prefix points
to the intended workspace environment before claiming installation success.
{existing}
{known_failure}
{prior}
{manifest_guidance}"""

    return f"""Finish setting up {ki.name} on this machine now.
{experience}

You own the complete KDT loop: inspect, act, run preflight, diagnose, repair,
and retry. Read SKILL.md first and use the KI's validated tools and diagnostics.
Do not stop after merely explaining commands or after the first failed build.
The only successful outcome is a passing preflight.

Use only this workspace, the bundled KI, declared existing-install candidates,
and authoritative upstream sources. Do not inspect or copy artifacts from
other GeoForge projects or installation workspaces. Never fabricate or add a
placeholder scientific/model file merely to make a preflight check pass; if
the check contradicts an authoritative model deck, report that KI validation
defect with evidence instead.

If a licence, login, protected download, system privilege, or user choice makes
progress impossible, create one structured setup request exactly as described
in the project instructions, then stop. Do not pretend that blocked work passed.
{known_failure}
{existing}
{prior}"""


def setup_state(root: Path, software: dict) -> dict:
    log_path = Path(root) / LOG_FILE
    try:
        log_tail = log_path.read_text(encoding="utf-8", errors="replace")[-120_000:]
    except OSError:
        log_tail = ""
    current_request = request(root)
    attention = None
    primary = software.get("primary_error") or {}
    if (not software.get("can_run") and not current_request
            and (primary or log_tail.strip())):
        stopped = "load failed" in log_tail[-4000:].lower()
        attention = {
            "kind": "retry",
            "title": "Agent connection stopped" if stopped else "Setup is not finished",
            "message": (
                "The agent stopped before verification passed. Continue the repair; "
                "GeoForge will show a specific request here if an external action is needed."
            ),
            "action_label": "Continue repair",
        }
    return {
        "software": software,
        "request": current_request,
        "attention": attention,
        "uploads": uploads(root),
        "workdir": str(root),
        "agent_ready": (Path(root) / "CLAUDE.md").is_file(),
        "log_tail": log_tail,
    }
