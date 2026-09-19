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
    for index, item in enumerate(value[:8]):
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
    expected = str(raw.get("expected_path") or "").strip()[:1000]
    if kind == "permission" and expected:
        # v0.6.34 could persist a popup for Kimi's automatic shared-skill
        # discovery.  That folder is now part of Kimi's read-only runtime
        # surface, so archive the stale request instead of showing it forever.
        from .kimi_security import is_runtime_read_path
        if is_runtime_read_path(expected):
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


def prepare_common(cfg, repo_root: Path) -> Path:
    """Materialise the bundled shared tool library into this setup workspace."""
    source = Path(repo_root) / "ki_tools_common"
    if not source.is_dir():
        raise ValueError(
            f"GeoForge's bundled ki_tools_common is missing (expected {source})")
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
    prepare_common(cfg, repo_root)

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
               installation_mode: str = "new",
               existing_paths: list[str] | None = None,
               installation_only: bool = False) -> str:
    """Short task layered over the provider's auto-loaded setup instructions."""
    notes = getattr(ki, "installation_notes", None)
    experience = (f"Read `{notes}` for this model's current-OS installation record. "
                  "Previous results are evidence, not a guarantee on this host.\n" if notes else "")
    prior = experience
    if resumed:
        prior = (
            "\nThe user has completed the earlier request.\n"
            f"User note: {resumed.get('user_note') or '(none)'}\n"
            f"Files supplied: {json.dumps(uploads(root), ensure_ascii=False)}\n"
            f"Resume hint: {resumed.get('resume_hint') or '(inspect the workspace)'}\n"
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
                "Read its Mac manifest for all required dependencies. This result establishes "
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

Keep diagnosing build and runtime problems until the declared executable,
source-bound Python runner, or Python package responds. Do not substitute a toy implementation,
launcher, or mock executable. If a licence, login, protected download, system
privilege, or missing shared toolchain requires a person, create one structured
setup request and stop. If you create or select a Python environment, record
the absolute environment launcher path (for example, `<workspace>/venv/bin/python`)
in `{Path(root) / 'kiss.toml'}` under `kiss.python`. Preserve this venv path even
when it is a symlink: do NOT use realpath, resolve(), or the symlink target.
Launching the resolved base interpreter loses the venv and its packages. Verify
`sys.prefix` identifies the intended workspace environment using an inspection
script, and keep GeoForge pointed at that environment launcher.
{existing}
{prior}"""

    return f"""Finish setting up {ki.name} on this machine now.

You own the complete KDT loop: inspect, act, run preflight, diagnose, repair,
and retry. Read SKILL.md first and use the KI's validated tools and diagnostics.
Do not stop after merely explaining commands or after the first failed build.
The only successful outcome is a passing preflight.

If a licence, login, protected download, system privilege, or user choice makes
progress impossible, create one structured setup request exactly as described
in the project instructions, then stop. Do not pretend that blocked work passed.
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
