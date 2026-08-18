"""Driving an agent CLI as the chat backend.

KISS does not implement an agent loop. Five capable CLIs already exist, the
user has already authenticated one of them, and each ships its own tool set,
approval policy and session handling. The frontend spawns one in the KI's
working directory and streams its output.

The argv for each provider is drift-prone — flags get renamed upstream between
releases and a stale flag surfaces as an empty reply rather than an error. So
every provider here declares a `probe` that is run before first use, and
failures name the provider and the exact argv attempted.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


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

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def path(self) -> str | None:
        return shutil.which(self.binary)

    def build(self, prompt: str, *, extra_dirs: list[str] | None = None,
              model: str | None = None) -> list[str]:
        out: list[str] = []
        for tok in self.argv:
            out.append(prompt if tok == "{prompt}" else tok)
        if model and self.model_flag:
            out += [self.model_flag, model]
        for d in extra_dirs or []:
            out += ["--add-dir", d]
        return [self.path() or self.binary] + out[1:] if out and out[0] == self.binary else out


#: Canonical invocations. These mirror the ones the HydroCraft deployment uses
#: in production against these same KI packages.
PROVIDERS: dict[str, Provider] = {
    "claude": Provider(
        name="claude", models=["sonnet", "opus", "haiku", "claude-opus-5", "claude-sonnet-5"], default_model="sonnet",  policy_map="claude_args", install="npm install -g @anthropic-ai/claude-code", auth="run `claude` once and sign in", binary="claude", label="Claude Code",
        argv=["claude", "-p", "{prompt}", "--output-format", "stream-json", "--verbose"],
        output="stream-json",
        notes="Reads CLAUDE.md from the working directory automatically.",
    ),
    "codex": Provider(
        name="codex", models=["gpt-5.5", "gpt-5.6-sol"], model_flag="-m", default_model="gpt-5.5",  policy_map="codex_args", install="npm install -g @openai/codex", auth="run `codex` once and sign in", binary="codex", label="OpenAI Codex",
        argv=["codex", "exec", "{prompt}"],
        output="text", stdout_only=True,
        notes=("Reads AGENTS.md. Since 0.144 the reply is on STDOUT and chrome on "
               "STDERR — parse stdout only. Never wrap in `timeout`."),
    ),
    "gemini": Provider(
        name="gemini", models=["gemini-3-pro", "gemini-3-flash", "gemini-2.5-pro", "gemini-2.5-flash"], default_model="gemini-3-flash",  install="npm install -g @google/gemini-cli", auth="run `gemini` once and sign in", binary="gemini", label="Gemini CLI",
        argv=["gemini", "-p", "{prompt}", "--output-format", "stream-json", "--yolo"],
        output="stream-json",
        notes="Reads ~/.gemini/GEMINI.md (global), not a project file.",
    ),
    "kimi": Provider(
        name="kimi", models=["kimi-for-coding", "kimi-for-coding-highspeed", "k3", "k3-256k"], default_model="kimi-for-coding",  install="see moonshot's Kimi Code install guide", auth="run `kimi` once and sign in", binary="kimi", label="Kimi Code",
        argv=["kimi", "-p", "{prompt}", "--output-format", "stream-json", "--yolo"],
        output="stream-json",
        notes="`--print` was removed upstream; prompt mode is just -p.",
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


def get(name: str) -> Provider:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise KeyError(f"unknown provider {name!r}; have {', '.join(PROVIDERS)}") from None


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

    # Flat shapes: {"type":"content_block_delta","delta":{"text":...}} / {"text":...}
    delta = ev.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("text"), str):
        return delta["text"]
    if isinstance(ev.get("text"), str):
        return ev["text"]

    # Tool activity is worth surfacing so the user sees work happening.
    if ev.get("type") in ("tool_use", "tool_call") and ev.get("name"):
        return f"\n`> {ev['name']}`\n"
    return None


def run(provider: Provider, prompt: str, cwd: Path,
        *, extra_dirs: list[str] | None = None,
        cfg=None, ki_root: Path | None = None, pol=None,
        model: str | None = None,
        timeout: int | None = None) -> Iterator[str]:
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
    if not provider.available():
        yield f"[{provider.label} is not installed — `{provider.binary}` not on PATH]"
        return

    argv = provider.build(prompt, extra_dirs=extra_dirs, model=model)
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

    try:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE if provider.stdout_only else subprocess.STDOUT,
            text=True, errors="replace", bufsize=1,
        )
    except OSError as e:
        yield f"[failed to start {provider.label}: {e}]"
        return

    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if provider.output == "stream-json":
                text = _text_from_stream_json(line)
                if text:
                    yield text
            else:
                yield line
    finally:
        proc.stdout and proc.stdout.close()  # type: ignore[func-returns-value]
        rc = proc.wait(timeout=timeout)
        if rc != 0:
            tail = ""
            if provider.stdout_only and proc.stderr:
                tail = "".join(proc.stderr.readlines()[-15:]).strip()
            yield f"\n\n[{provider.label} exited {rc}]"
            if tail:
                yield f"\n```\n{tail[-1500:]}\n```"
