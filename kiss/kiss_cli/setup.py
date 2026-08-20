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
from pathlib import Path

from . import install, paths, port

REQUEST_FILE = "setup-request.json"
USER_FILES_DIR = "user-files"
LOG_FILE = "setup-agent.log"
REQUEST_KINDS = {"download", "licence", "login", "permission", "choice", "other"}


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def request(root: Path) -> dict | None:
    """Return the current structured human request, if one exists."""
    raw = _read_json(Path(root) / REQUEST_FILE)
    if not raw:
        return None
    # CLI agents write this file directly, so treat every field as untrusted
    # display data just like an imported KI. In particular, never let an agent
    # turn the official-page link into a javascript: URL.
    kind = str(raw.get("kind") or "other").lower()
    url = str(raw.get("url") or "").strip()[:2000]
    return {
        **raw,
        "status": raw.get("status") if raw.get("status") in ("waiting", "ready") else "waiting",
        "kind": kind if kind in REQUEST_KINDS else "other",
        "title": " ".join(str(raw.get("title") or "Help needed").split())[:160],
        "message": str(raw.get("message") or "").strip()[:8000],
        "url": url if url.startswith(("https://", "http://")) else None,
        "expected_path": str(raw.get("expected_path") or "").strip()[:1000] or None,
        "command": str(raw.get("command") or "").strip()[:2000] or None,
        "resume_hint": str(raw.get("resume_hint") or "").strip()[:4000] or None,
        "user_note": str(raw.get("user_note") or "").strip()[:4000] or None,
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
        "status": "waiting",
        "kind": kind,
        "title": title,
        "message": message,
        "url": url or None,
        "expected_path": expected or None,
        "command": command or None,
        "resume_hint": resume or None,
        "created_at": time.time(),
    }
    path = Path(root) / REQUEST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return doc


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

    brew_packages = {
        "git": "git", "cmake": "cmake", "make": "make", "gmake": "make",
        "gcc": "gcc", "g++": "gcc", "gfortran": "gcc",
        "mpicc": "mpich", "mpicxx": "mpich", "mpif90": "mpich",
        "nc-config": "netcdf", "nf-config": "netcdf-fortran",
        "pkg-config": "pkg-config",
    }
    packages = list(dict.fromkeys(brew_packages[x] for x in missing if x in brew_packages))
    command = ("brew install " + " ".join(packages)
               if sys.platform == "darwin" and shutil.which("brew") and packages else "")
    names = ", ".join(missing) if missing else "required build libraries"
    message = (
        f"The model build needs {names}. These are shared Mac tools, so the "
        "setup agent will not install them across your system without you. "
        + ("Run the command below in Terminal, then return here and continue."
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

    live_ki = type(ki)(name=ki.name, root=live)
    handoff.write_setup(
        live_ki, man, cfg, root,
        built_in_command=runtime_command(models_dir, ki.name, root),
    )
    return live_ki, cfg


def agent_task(ki, cfg, root: Path, *, resumed: dict | None = None) -> str:
    """Short task layered over the provider's auto-loaded setup instructions."""
    prior = ""
    if resumed:
        prior = (
            "\nThe user has completed the earlier request.\n"
            f"User note: {resumed.get('user_note') or '(none)'}\n"
            f"Files supplied: {json.dumps(uploads(root), ensure_ascii=False)}\n"
            f"Resume hint: {resumed.get('resume_hint') or '(inspect the workspace)'}\n"
        )
    return f"""Finish setting up {ki.name} on this machine now.

You own the complete KDT loop: inspect, act, run preflight, diagnose, repair,
and retry. Read SKILL.md first and use the KI's validated tools and diagnostics.
Do not stop after merely explaining commands or after the first failed build.
The only successful outcome is a passing preflight.

If a licence, login, protected download, system privilege, or user choice makes
progress impossible, create one structured setup request exactly as described
in the project instructions, then stop. Do not pretend that blocked work passed.
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
