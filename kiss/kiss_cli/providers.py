"""Driving an agent CLI as the chat backend.

KISS does not implement an agent loop. Five capable CLIs already exist, the
user has already authenticated one of them, and each ships its own tool set,
approval policy and session handling. The frontend spawns one in the KI's
working directory and streams its output.

The argv for each provider is drift-prone — flags get renamed upstream between
releases and a stale flag surfaces as an empty reply rather than an error.
Providers with a reliable local status command also declare an ``auth_probe``;
failures name the provider and the exact argv attempted.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .presentation import activity_marker


@dataclass(frozen=True)
class ProviderHealth:
    """Cheap local evidence about whether a CLI can be selected.

    ``authenticated=None`` means the CLI has no supported local status command;
    it remains selectable and its login is checked by the real first call, but
    the UI describes that honestly rather than claiming it is already verified.
    """

    installed: bool
    authenticated: bool | None
    detail: str
    compatible: bool | None = None

    @property
    def usable(self) -> bool:
        return (self.installed and self.authenticated is not False
                and self.compatible is not False)


@dataclass
class Provider:
    """One agent CLI and how to talk to it non-interactively."""

    name: str
    binary: str
    #: argv built around the prompt; {prompt} is substituted positionally
    argv: list[str]
    #: how the reply arrives: "stream-json" (JSONL) or "text"
    output: str = "stream-json"
    #: some CLIs put the reply on stdout and diagnostics on stderr
    stdout_only: bool = True
    label: str = ""
    notes: str = ""
    env: dict[str, str] = field(default_factory=dict)
    #: name of the policy mapper in kiss_cli.policy for this CLI
    policy_map: str = "coarse_args"
    #: model names this CLI accepts (canonical list mirrored from the
    #: HydroCraft backend, which probes the real CLIs), and the argv flag that
    #: selects one. Empty flag = CLI has no model selection.
    models: list[str] = field(default_factory=list)
    model_flag: str = "--model"
    default_model: str = ""
    #: how a user installs this CLI, shown when none is present. Naming the
    #: providers without saying how to get them leaves a dead end on the one
    #: screen where the user cannot do anything else.
    install: str = ""
    auth: str = ""
    #: Free, local-only authentication check. It must not call the model API.
    auth_probe: list[str] = field(default_factory=list)
    #: Old CLIs can be signed in but still reject the argv/model contract.
    min_version: tuple[int, ...] | None = None
    #: Feed the prompt on STDIN instead of substituting it into argv. The
    #: catalogue prompt is ~20KB and every OS caps a command line: Windows
    #: allows 32767 characters, and only 8191 when the CLI is reached through
    #: a batch shim. STDIN has no such ceiling. Only set this for a CLI that
    #: is known to read its prompt from STDIN -- the others reject a bare
    #: ``-p`` with a missing-argument error.
    stdin_prompt: bool = False
    #: Argv used instead of ``argv`` when continuing a prior conversation,
    #: with ``{resume}`` standing in for the id. A template rather than a flag
    #: because the CLIs disagree on shape: Claude and Kimi take an option
    #: (``--resume ID`` / ``-r ID``) while Codex takes a subcommand
    #: (``exec resume ID``). Empty means no verified headless resume, and every
    #: turn replays the transcript instead.
    resume_argv: list[str] = field(default_factory=list)
    #: For text-output CLIs, a regex whose first group is the session id, read
    #: from the diagnostics stream. Stream-json CLIs need no pattern — their
    #: id arrives as a JSON field.
    session_regex: str = ""

    def available(self) -> bool:
        return self.health().usable

    def installed(self) -> bool:
        return shutil.which(self.binary) is not None

    def path(self) -> str | None:
        return shutil.which(self.binary)

    def health(self, *, refresh: bool = False) -> ProviderHealth:
        return _health(self, refresh=refresh)

    def can_resume(self) -> bool:
        return bool(self.resume_argv)

    def build(self, prompt: str, *, extra_dirs: list[str] | None = None,
              model: str | None = None, resume: str | None = None) -> list[str]:
        template = self.resume_argv if (resume and self.resume_argv) else self.argv
        out: list[str] = []
        for tok in template:
            if tok == "{resume}":
                out.append(str(resume))
            elif tok != "{prompt}":
                out.append(tok)
            elif not self.stdin_prompt:
                out.append(prompt)
        if model and self.model_flag:
            out += [self.model_flag, model]
        for d in extra_dirs or []:
            out += ["--add-dir", d]
        head = _launcher(self.path() or self.binary)
        return head + out[1:] if out and out[0] == self.binary else out


#: A Windows batch shim points at the thing it really runs: either a native
#: ``.exe`` beside it, or a ``node`` runtime plus a ``.js`` entry point.
_SHIM_TARGET = re.compile(r'"%(?:_prog|dp0|~dp0)%\\?([^"%]+)"')


def _launcher(binary: str) -> list[str]:
    """Argv head that reaches ``binary`` without going through cmd.exe.

    ``npm install -g`` puts a ``.cmd`` batch shim on PATH, and CreateProcess
    runs a ``.cmd`` by handing it to the command processor -- whose command
    line is capped at 8191 characters, not the 32767 CreateProcess itself
    allows. The catalogue prompt is over twice that cap, so on Windows every
    turn died before the CLI was even reached: exit 1, stderr "The command
    line is too long", and an empty reply panel that named no cause.

    Following the shim to its target recovers the full 32767. It is a
    best-effort read: an unrecognised shim is returned untouched, which is no
    worse than today.
    """
    if os.name != "nt" or not binary.lower().endswith((".cmd", ".bat")):
        return [binary]
    try:
        text = Path(binary).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [binary]

    here = Path(binary).parent
    script: Path | None = None
    node: Path | None = None
    for raw in _SHIM_TARGET.findall(text):
        target = here / raw.lstrip("\\/")
        if not target.exists():
            continue
        suffix = target.suffix.lower()
        if suffix == ".exe":
            # A bundled node.exe is the runtime, not the program.
            if target.stem.lower() == "node":
                node = node or target
            else:
                return [str(target)]
        elif suffix in (".js", ".cjs", ".mjs"):
            script = script or target
    if script is not None:
        runtime = str(node) if node else shutil.which("node")
        if runtime:
            return [runtime, str(script)]
    return [binary]


#: Canonical invocations. These mirror the ones the HydroCraft deployment uses
#: in production against these same KI packages.
PROVIDERS: dict[str, Provider] = {
    "claude": Provider(
        name="claude", models=["sonnet", "opus", "haiku", "claude-opus-5", "claude-sonnet-5"], policy_map="claude_args", install="npm install -g @anthropic-ai/claude-code", auth="run `claude auth login` in Terminal", binary="claude", label="Claude Code",
        argv=["claude", "-p", "{prompt}", "--output-format", "stream-json", "--verbose"],
        auth_probe=["claude", "auth", "status", "--json"],
        output="stream-json", stdin_prompt=True,
        resume_argv=["claude", "--resume", "{resume}", "-p",
                     "--output-format", "stream-json", "--verbose"],
        notes="Reads CLAUDE.md from the working directory automatically.",
    ),
    "codex": Provider(
        name="codex", models=["gpt-5.5", "gpt-5.6-sol"], model_flag="-m", policy_map="codex_args", install="npm install -g @openai/codex", auth="run `codex login` in Terminal", binary="codex", label="OpenAI Codex",
        argv=["codex", "exec", "--skip-git-repo-check", "-"],
        resume_argv=["codex", "exec", "resume", "{resume}",
                     "--skip-git-repo-check", "-"],
        session_regex=r"session id:\s*([0-9a-fA-F-]{36})",
        auth_probe=["codex", "login", "status"],
        min_version=(0, 144, 0),
        output="text", stdout_only=True, stdin_prompt=True,
        notes=("Reads AGENTS.md. Since 0.144 the reply is on STDOUT and chrome on "
               "STDERR — parse stdout only. Never wrap in `timeout`. The `-` "
               "sentinel is codex's documented 'read the prompt from STDIN'; it "
               "also avoids openai/codex#20919, where a prompt on argv plus an "
               "inherited pipe with no writer hangs waiting for an EOF that "
               "never comes. --skip-git-repo-check is not optional here: a "
               "session project is an ordinary folder, and without it codex "
               "refuses to start at all."),
    ),
    "gemini": Provider(
        name="gemini", models=["gemini-3-pro", "gemini-3-flash", "gemini-2.5-pro", "gemini-2.5-flash"], default_model="gemini-3-flash",  install="npm install -g @google/gemini-cli", auth="run `gemini` once and sign in", binary="gemini", label="Gemini CLI",
        argv=["gemini", "-p", "{prompt}", "--output-format", "stream-json", "--yolo"],
        output="stream-json",
        notes="Reads ~/.gemini/GEMINI.md (global), not a project file.",
    ),
    "kimi": Provider(
        name="kimi", models=["kimi-for-coding", "kimi-for-coding-highspeed", "k3", "k3-256k"], default_model="kimi-for-coding", install="curl -fsSL https://code.kimi.com/kimi-code/install.sh | bash", auth="run `kimi login` in Terminal", binary="kimi", label="Kimi Code",
        argv=["kimi", "-p", "{prompt}", "--output-format", "stream-json"],
        auth_probe=["kimi", "provider", "list", "--json"],
        output="stream-json",
        resume_argv=["kimi", "-r", "{resume}", "-p", "{prompt}",
                     "--output-format", "stream-json"],
        notes=("Non-interactive -p uses Kimi's automatic permission policy; "
               "--yolo must not be combined with it."),
    ),
    "qwen": Provider(
        name="qwen", models=["qwen3-coder", "qwen3-coder-plus", "qwen-coder-plus"], default_model="qwen3-coder",  install="npm install -g @qwen-code/qwen-code", auth="run `qwen` once and sign in", binary="qwen", label="Qwen Code",
        argv=["qwen", "{prompt}", "--output-format", "stream-json",
              "--approval-mode", "yolo"],
        output="stream-json",
        notes="Reads QWEN.md.",
    ),
}


def available() -> list[Provider]:
    return [p for p in PROVIDERS.values() if p.available()]


def detected() -> list[Provider]:
    """Installed CLIs, including ones that still need sign-in."""
    return [p for p in PROVIDERS.values() if p.installed()]


def get(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise KeyError(f"unknown provider {name!r}; have {', '.join(PROVIDERS)}") from None


_HEALTH_TTL = 30.0
_HEALTH_CACHE: dict[str, tuple[float, ProviderHealth]] = {}
_HEALTH_LOCK = threading.Lock()


_CLAUDE_ENV_AUTH = (
    # Claude Code supports OAuth, direct API credentials, and enterprise cloud
    # providers.  ``auth status`` historically described only the first one on
    # some releases, so an otherwise working Bedrock/Vertex/API-key setup was
    # hidden from GeoForge's Local menu.
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


def _claude_auth_state(stdout: str) -> bool | None:
    """Interpret Claude's evolving local auth report conservatively.

    ``False`` is reserved for an explicit, recognised "no credentials" report.
    An unfamiliar future schema remains selectable and is verified by the real
    one-line probe instead of being incorrectly hidden from the UI.
    """
    try:
        doc = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None

    if any(os.environ.get(name) for name in _CLAUDE_ENV_AUTH):
        return True
    method = str(doc.get("authMethod") or "").strip().lower()
    provider = str(doc.get("apiProvider") or "").strip().lower()
    if method and method not in {"none", "null", "unknown"}:
        return True
    if provider in {"bedrock", "vertex", "vertexai", "foundry"}:
        return True
    if isinstance(doc.get("loggedIn"), bool):
        return doc["loggedIn"]
    return None


def _kimi_credential_dirs(binary: str) -> list[Path]:
    return [Path.home() / ".kimi-code" / "credentials",
            Path(binary).resolve().parent.parent / "credentials"]


def _kimi_auth_state(stdout: str, binary: str) -> bool | None:
    """Read sign-in out of ``kimi provider list --json``.

    Kimi has no ``auth status``, so GeoForge declared no probe at all and the
    Local menu reported "login checked on first use" for an account that was
    in fact signed in -- correct, but indistinguishable from a broken install.

    ``provider list`` exits 0 whether or not anyone has logged in, so the exit
    code proves nothing: what counts is whether a configured provider carries
    a usable credential. An OAuth binding only names a token file, so confirm
    the file is actually on disk before calling the CLI signed in.
    """
    try:
        doc = json.loads(stdout or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(doc, dict):
        return None
    entries = doc.get("providers")
    if not isinstance(entries, dict):
        return None
    if not entries:
        return False

    unknown = False
    for entry in entries.values():
        if not isinstance(entry, dict):
            continue
        if (entry.get("apiKey") or "").strip():
            return True
        oauth = entry.get("oauth")
        if not isinstance(oauth, dict):
            continue
        key = str(oauth.get("key") or "").strip()
        if not key:
            unknown = True
            continue
        name = key.rsplit("/", 1)[-1]
        if any((d / f"{name}.json").exists() for d in _kimi_credential_dirs(binary)):
            return True
        # A binding whose token is kept somewhere we cannot see (a keychain,
        # say) is not evidence of being signed out.
        if str(oauth.get("storage") or "file").lower() != "file":
            unknown = True
    return None if unknown else False


def _health(provider: Provider, *, refresh: bool = False) -> ProviderHealth:
    """Inspect installation and sign-in without contacting a model service."""
    now = time.monotonic()
    with _HEALTH_LOCK:
        cached = _HEALTH_CACHE.get(provider.name)
        if not refresh and cached and now - cached[0] < _HEALTH_TTL:
            return cached[1]

    binary = provider.path()
    if not binary:
        result = ProviderHealth(False, False, "not installed")
    elif not provider.auth_probe:
        result = ProviderHealth(True, None, "installed; login checked on first use")
    else:
        argv = [binary, *provider.auth_probe[1:]]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=8, stdin=subprocess.DEVNULL,
                **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
                   if os.name == "nt" else {}),
            )
            raw = (proc.stdout + proc.stderr).strip()
            if provider.name == "claude":
                signed_in = _claude_auth_state(proc.stdout)
            elif provider.name == "kimi":
                signed_in = _kimi_auth_state(proc.stdout, binary)
            elif provider.name == "codex":
                signed_in = proc.returncode == 0 and "logged in" in raw.lower()
            else:
                signed_in = proc.returncode == 0
            compatible = None
            version_note = ""
            if provider.min_version:
                ver = subprocess.run(
                    [binary, "--version"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=8,
                    stdin=subprocess.DEVNULL,
                    **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
                       if os.name == "nt" else {}),
                )
                match = re.search(r"\d+(?:\.\d+)+", ver.stdout + ver.stderr)
                if ver.returncode == 0 and match:
                    found = tuple(int(n) for n in match.group(0).split("."))
                    width = max(len(found), len(provider.min_version))
                    have = found + (0,) * (width - len(found))
                    need = provider.min_version + (0,) * (width - len(provider.min_version))
                    compatible = have >= need
                    if not compatible:
                        version_note = (f"; update required ({match.group(0)} < "
                                        f"{'.'.join(map(str, provider.min_version))})")
            if signed_in is True:
                detail = ("signed in using ChatGPT"
                          if provider.name == "codex" and "chatgpt" in raw.lower()
                          else "signed in")
            elif signed_in is False:
                detail = "installed; sign-in required"
            else:
                detail = "installed; sign-in status not recognised"
            result = ProviderHealth(True, signed_in, detail + version_note, compatible)
        except (OSError, subprocess.TimeoutExpired):
            result = ProviderHealth(True, None, "installed; sign-in check unavailable")

    with _HEALTH_LOCK:
        _HEALTH_CACHE[provider.name] = (now, result)
    return result


# --- streaming --------------------------------------------------------------

def _text_from_stream_json(line: str) -> str | None:
    """Pull displayable text out of one stream-json line.

    The CLIs do not agree on a schema, so this is deliberately tolerant: it
    looks for the shapes they actually emit and ignores anything else rather
    than failing the whole turn on an unrecognised event.
    """
    line = line.strip()
    if not line or not line.startswith("{"):
        return None
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Anthropic-style: {"type":"assistant","message":{"content":[{"type":"text",...}]}}
    msg = ev.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, list):
            chunks = [c.get("text", "") for c in content
                      if isinstance(c, dict) and c.get("type") == "text"]
            joined = "".join(chunks)
            if joined:
                return joined

    # Kimi stream-json: {"role":"assistant","content":"..."}.  Tool calls
    # use the same top-level role shape rather than Anthropic's message wrapper.
    if ev.get("role") == "assistant":
        content = ev.get("content")
        if isinstance(content, str) and content:
            return content
        if isinstance(content, list):
            chunks = [c.get("text", "") for c in content
                      if isinstance(c, dict) and isinstance(c.get("text"), str)]
            joined = "".join(chunks)
            if joined:
                return joined
        calls = ev.get("tool_calls")
        if isinstance(calls, list):
            names = []
            for call in calls:
                if not isinstance(call, dict):
                    continue
                fn = call.get("function")
                name = fn.get("name") if isinstance(fn, dict) else call.get("name")
                if name:
                    names.append(str(name))
            if names:
                return "".join(activity_marker(name) for name in names)

    # Flat shapes: {"type":"content_block_delta","delta":{"text":...}} / {"text":...}
    delta = ev.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("text"), str):
        return delta["text"]
    if isinstance(ev.get("text"), str):
        return ev["text"]

    # Tool activity is worth surfacing so the user sees work happening.
    if ev.get("type") in ("tool_use", "tool_call") and ev.get("name"):
        return activity_marker(ev["name"])
    return None


def _session_id_from_stream_json(line: str) -> str | None:
    """The id this CLI would need to resume the conversation later.

    Claude announces it in the opening ``system`` event; Kimi emits a
    ``session.resume_hint`` meta event carrying the same field. Both put it at
    the top level under ``session_id``, so one lookup covers both and an
    unknown CLI simply never yields one.
    """
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return None
    sid = ev.get("session_id") if isinstance(ev, dict) else None
    return sid if isinstance(sid, str) and sid else None


def run(provider: Provider, prompt: str, cwd: Path,
        *, extra_dirs: list[str] | None = None,
        cfg=None, ki_root: Path | None = None, pol=None,
        model: str | None = None,
        timeout: int | None = None,
        resume: str | None = None,
        session_out: dict | None = None) -> Iterator[str]:
    """Spawn the CLI and yield displayable text as it arrives.

    When ``cfg`` is given the agent is started **inside the relocation
    namespace**, together with everything it goes on to spawn. This is not
    optional polish: without it the agent resolves the KI\'s authoring paths
    against the bare host, finds them missing, and works around the KI instead
    of using it — while any model the installer set up sees the relocated
    paths. One process tree, one view.

    Never raises for a non-zero exit: the exit status and any stderr tail are
    yielded as text so the user sees what went wrong instead of a blank panel.
    """
    health = provider.health()
    if not health.installed:
        yield f"[{provider.label} is not installed — `{provider.binary}` not on PATH]"
        return
    if health.authenticated is False:
        yield f"[{provider.label} is installed but not signed in — {provider.auth}]"
        return
    if health.compatible is False:
        yield f"[{provider.label} needs an update — {health.detail}; {provider.install}]"
        return

    argv = provider.build(prompt, extra_dirs=extra_dirs, model=model,
                          resume=resume)
    env = {**os.environ, **provider.env}

    # Least privilege, mapped onto whatever this CLI can actually enforce.
    # When it cannot enforce anything, say so — silence here would imply a
    # guarantee that was never obtained.
    if pol is not None:
        from . import policy as _pol
        mapper = getattr(_pol, provider.policy_map, _pol.coarse_args)
        extra_args, enforcement = mapper(pol)
        argv = argv + extra_args
        if enforcement is not _pol.Enforcement.EXACT:
            yield f"[{_pol.describe(enforcement, provider.label)}]\n\n"

    if cfg is not None and getattr(cfg, "relocation", "sandbox") == "sandbox":
        from .paths import have_sandbox, sandbox_command
        if have_sandbox():
            extra = [Path(d) for d in (extra_dirs or [])]
            if ki_root is not None:
                extra.append(Path(ki_root))
            argv = sandbox_command(cfg, argv, cwd=cwd, extra_binds=extra)
        # No bwrap: nothing to say. The KI in use is a materialised copy with
        # real paths, so there is nothing for a namespace to fix; warning about
        # a missing Linux tool on a Mac was pure noise.

    import tempfile

    # A windowed build owns no console, so Windows hands each console child a
    # brand new one: a black window flashing over the app for every turn, which
    # reads as a crash. CREATE_NO_WINDOW suppresses it and keeps the CLI in the
    # non-interactive mode we asked for. Verified against all three CLIs.
    spawn: dict = {}
    if os.name == "nt":
        spawn["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

    # stderr goes to a spool file, never a PIPE: an unread PIPE fills at ~64KB
    # and a chatty CLI (codex logs its chrome there) then blocks forever.
    err_spool = tempfile.TemporaryFile(mode="w+", errors="replace")
    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), env=env,
            # DEVNULL, never inherited: a windowed parent has no valid stdin,
            # and a CLI that decides to read it would wait for an EOF that
            # cannot arrive (openai/codex#20919 is exactly this).
            stdin=subprocess.PIPE if provider.stdin_prompt else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=err_spool if provider.stdout_only else subprocess.STDOUT,
            # encoding is explicit: text=True alone decodes with the locale
            # codepage, which on a Chinese Windows install is cp936. Every
            # agent CLI emits UTF-8, so a non-ASCII reply came back as
            # replacement characters — invisible on an English machine, and
            # total corruption of any Chinese answer.
            text=True, encoding="utf-8", errors="replace", bufsize=1, **spawn,
        )
    except OSError as e:
        yield f"[failed to start {provider.label}: {e}]"
        return

    # Written from a thread, not inline: a prompt larger than the pipe buffer
    # blocks the writer until the child drains it, and the child cannot be
    # drained by a reader that has not started yet. Closing the pipe is the
    # EOF the CLI waits for, so it happens on every path out.
    if provider.stdin_prompt and proc.stdin is not None:
        def _feed(pipe, text: str) -> None:
            try:
                pipe.write(text)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass

        threading.Thread(target=_feed, args=(proc.stdin, prompt),
                         daemon=True, name="kiss-prompt-stdin").start()

    produced = False
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if provider.output == "stream-json":
                if session_out is not None and not session_out.get("session_id"):
                    sid = _session_id_from_stream_json(line)
                    if sid:
                        session_out["session_id"] = sid
                text = _text_from_stream_json(line)
                if text:
                    produced = True
                    if session_out is not None:
                        # Flagged the instant real output exists, not at exit:
                        # a caller deciding whether a failed resume is safe to
                        # retry must know before it forwards anything onward.
                        session_out["produced"] = True
                    yield text
            else:
                produced = True
                if session_out is not None:
                    session_out["produced"] = True
                yield line
    finally:
        proc.stdout and proc.stdout.close()  # type: ignore[func-returns-value]
        rc = proc.wait(timeout=timeout)
        if (session_out is not None and not session_out.get("session_id")
                and provider.session_regex and provider.stdout_only):
            # A text-mode CLI prints its session id with the rest of its chrome
            # on stderr, which is spooled rather than parsed. Only the header is
            # searched -- the id is announced before any work starts.
            try:
                err_spool.seek(0)
                found = re.search(provider.session_regex, err_spool.read(8192))
                if found:
                    session_out["session_id"] = found.group(1)
            except (OSError, ValueError):
                pass
        if session_out is not None:
            # The caller needs both to tell "this resume id is stale, replay
            # instead" from "the model answered and then something failed" —
            # only the first is safe to retry, because nothing reached the user.
            session_out["returncode"] = rc
            session_out["produced"] = produced
        if rc != 0:
            tail = ""
            if provider.stdout_only:
                err_spool.seek(0)
                tail = "".join(err_spool.readlines()[-15:]).strip()
            yield f"\n\n[{provider.label} exited {rc}]"
            if tail:
                yield f"\n```\n{tail[-1500:]}\n```"
        err_spool.close()
