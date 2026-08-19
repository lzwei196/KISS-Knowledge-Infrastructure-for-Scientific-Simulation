"""The API driver: talk to a model directly instead of spawning an agent CLI.

The CLI driver reuses an agent the user has already installed and signed in, so
it needs no key and inherits that agent's tools. This driver is the other half:
an API key, and KISS owns the loop.

Two things follow from owning the loop, and they are the reason to have it:

* **The tools are typed.** The model asks for ``run_preflight`` or
  ``read_ki_file(path)``; it cannot express an arbitrary shell command. The
  permission question changes from "is this command safe" — undecidable from a
  string — to "is this argument in range", which is checkable.
* **It can stop and ask mid-turn.** A one-shot ``claude -p`` exits when the turn
  ends, so a CLI agent can only ask between turns. Here the loop is ours, so a
  request for approval can suspend it and resume on an answer.

No SDK dependency: both wire formats are a single POST of JSON, and taking a
dependency on two vendor SDKs to send one request each would be a poor trade for
a tool meant to install cleanly anywhere.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

TIMEOUT = 300


@dataclass
class ApiProvider:
    """One API endpoint and how to authenticate to it."""

    name: str
    label: str
    #: "anthropic" (native messages API) or "openai" (chat/completions shape)
    wire: str
    base_url: str
    env_key: str
    models: dict[str, str] = field(default_factory=dict)
    default_model: str = ""
    signup: str = ""

    def key(self) -> str | None:
        return os.environ.get(self.env_key) or None

    def available(self) -> bool:
        return bool(self.key())


#: Mirrors the provider table the HydroCraft backend already serves, so a key
#: that works there works here.
PROVIDERS: dict[str, ApiProvider] = {
    "anthropic": ApiProvider(
        name="anthropic", label="Claude (API)", wire="anthropic",
        base_url="https://api.anthropic.com/v1/messages",
        env_key="ANTHROPIC_API_KEY",
        models={"claude-sonnet-4-5": "claude-sonnet-4-5",
                "claude-opus-4-1": "claude-opus-4-1"},
        default_model="claude-sonnet-4-5",
        signup="https://console.anthropic.com/settings/keys",
    ),
    "deepseek": ApiProvider(
        name="deepseek", label="DeepSeek (API)", wire="openai",
        base_url="https://api.deepseek.com/chat/completions",
        env_key="DEEPSEEK_API_KEY",
        models={"deepseek-chat": "deepseek-chat",
                "deepseek-reasoner": "deepseek-reasoner"},
        default_model="deepseek-chat",
        signup="https://platform.deepseek.com/api_keys",
    ),
    "openai": ApiProvider(
        name="openai", label="OpenAI (API)", wire="openai",
        base_url="https://api.openai.com/v1/chat/completions",
        env_key="OPENAI_API_KEY",
        models={"gpt-4o": "gpt-4o", "gpt-4o-mini": "gpt-4o-mini"},
        default_model="gpt-4o",
        signup="https://platform.openai.com/api-keys",
    ),
    "openrouter": ApiProvider(
        name="openrouter", label="OpenRouter (API)", wire="openai",
        base_url="https://openrouter.ai/api/v1/chat/completions",
        env_key="OPENROUTER_API_KEY",
        models={"claude-sonnet-4-5": "anthropic/claude-sonnet-4.5",
                "deepseek-chat": "deepseek/deepseek-chat"},
        default_model="deepseek-chat",
        signup="https://openrouter.ai/keys",
    ),
}


def available() -> list[ApiProvider]:
    return [p for p in PROVIDERS.values() if p.available()]


# --- the tools the model may call ------------------------------------------
#
# Deliberately typed and narrow. There is no `bash` here: a KI declares what a
# model needs, so the useful operations are enumerable, and enumerating them is
# what lets the permission layer check an argument instead of guessing at a
# command string.

def tool_schemas(ki) -> list[dict]:
    return [
        {
            "name": "read_ki_file",
            "description": (
                "Read a file from this model's Knowledge Infrastructure package "
                "(SKILL.md, dag.yaml, diagnostics/triplets, docs/, tools/). "
                "Always read SKILL.md before proposing how to run the model."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "path relative to the KI root, e.g. 'SKILL.md'"},
                },
                "required": ["path"],
            },
        },
        {
            "name": "list_ki_files",
            "description": "List the files in this KI package, optionally under a subdirectory.",
            "input_schema": {
                "type": "object",
                "properties": {"subdir": {"type": "string"}},
            },
        },
        {
            "name": "run_preflight",
            "description": (
                "Run this KI's preflight_check.py and return its output. This is "
                "the authoritative answer to whether the model is ready to run."
            ),
            "input_schema": {"type": "object", "properties": {}},
        },
        {
            "name": "list_skills",
            "description": (
                "List the agent skills installed on this machine (name + one-line "
                "description). Skills are reusable instruction packages — use one "
                "when a task matches its description (plotting, statistics, "
                "literature review, document formats, ...)."
            ),
            "input_schema": {"type": "object",
                             "properties": {"query": {"type": "string",
                                            "description": "optional substring filter"}}},
        },
        {
            "name": "read_skill",
            "description": (
                "Read one installed skill's SKILL.md instructions by name. Read it "
                "before applying the skill; follow it like a procedure."
            ),
            "input_schema": {"type": "object",
                             "properties": {"name": {"type": "string"}},
                             "required": ["name"]},
        },
        {
            "name": "search_diagnostics",
            "description": (
                "Search this KI's diagnostics/triplets for an error keyword. Use "
                "this before debugging from first principles — the failure is "
                "often already catalogued with a verified remedy."
            ),
            "input_schema": {
                "type": "object",
                "properties": {"keyword": {"type": "string"}},
                "required": ["keyword"],
            },
        },
    ]


class ToolError(Exception):
    pass


def execute_tool(name: str, args: dict, ki, cfg) -> str:
    """Run one tool. Every path argument is confined to the KI package."""
    root = Path(ki.root).resolve()

    def _inside(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ToolError(f"absolute paths are not accepted: {rel}")
        # Resolve then verify containment: a bare prefix check is defeated by
        # '..' and by symlinks, and this is the only place model-supplied paths
        # reach the filesystem.
        p = (root / rel).resolve()
        if p != root and root not in p.parents:
            raise ToolError(f"path escapes the KI package: {rel}")
        return p

    if name == "read_ki_file":
        p = _inside(args.get("path", ""))
        if not p.is_file():
            raise ToolError(f"no such file in this KI: {args.get('path')}")
        text = p.read_text(encoding="utf-8", errors="replace")
        return text[:60000]

    if name == "list_ki_files":
        base = _inside(args.get("subdir") or ".")
        names = sorted(str(f.relative_to(root)) for f in base.rglob("*") if f.is_file())
        return "\n".join(names[:400]) or "(empty)"

    if name == "run_preflight":
        from . import install as _install
        step = _install.run_preflight(ki, cfg.python, cfg)
        return f"{'PASS' if step.ok else 'FAIL'}\n{step.detail}"

    if name == "search_diagnostics":
        kw = (args.get("keyword") or "").lower()
        if not kw:
            raise ToolError("keyword required")
        hits: list[str] = []
        for f in root.rglob("*"):
            if not f.is_file() or "diagnostic" not in str(f.relative_to(root)):
                continue
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if kw in line.lower():
                    hits.append(f"{f.relative_to(root)}:{i}: {line.strip()[:200]}")
        return "\n".join(hits[:40]) or f"no diagnostics mention {kw!r}"

    if name in ("list_skills", "read_skill"):
        # The CLI drivers inherit the unified skill library natively; the API
        # loop is ours, so the same library is exposed through tools — one
        # library, every provider. Canonical home: ~/.agents/skills (the
        # cross-agent convention the CLIs and DeepSeek Harness all read).
        lib = Path.home() / ".agents" / "skills"
        if name == "list_skills":
            q = (args.get("query") or "").lower()
            out = []
            for d in sorted(lib.iterdir()) if lib.is_dir() else []:
                sk = d / "SKILL.md"
                if not sk.is_file():
                    continue
                desc = ""
                for line in sk.read_text(encoding="utf-8", errors="replace")[:2000].splitlines():
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip()[:140]
                        break
                if not q or q in d.name.lower() or q in desc.lower():
                    out.append(f"{d.name} — {desc}")
            return "\n".join(out[:200]) or "no skills installed"
        sk = lib / re.sub(r"[^A-Za-z0-9_-]", "", args.get("name", "")) / "SKILL.md"
        if not sk.is_file():
            raise ToolError(f"no skill named {args.get('name')!r}")
        return sk.read_text(encoding="utf-8", errors="replace")[:60000]

    raise ToolError(f"unknown tool {name}")


# --- wire formats -----------------------------------------------------------

def _post(url: str, headers: dict, payload: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:800]
        raise ToolError(f"HTTP {e.code} from {url}: {body}") from None
    except urllib.error.URLError as e:
        raise ToolError(f"cannot reach {url}: {e.reason}") from None


def _anthropic_turn(prov, model, system, messages, tools, key):
    data = _post(prov.base_url,
                 {"x-api-key": key, "anthropic-version": "2023-06-01"},
                 {"model": model, "max_tokens": 4096, "system": system,
                  "messages": messages, "tools": tools})
    text = "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text")
    calls = [(b["id"], b["name"], b.get("input") or {})
             for b in data.get("content", []) if b.get("type") == "tool_use"]
    return text, calls, data.get("content", [])


def _openai_turn(prov, model, system, messages, tools, key):
    oai_tools = [{"type": "function",
                  "function": {"name": t["name"], "description": t["description"],
                               "parameters": t["input_schema"]}} for t in tools]
    msgs = [{"role": "system", "content": system}, *messages]
    data = _post(prov.base_url, {"Authorization": f"Bearer {key}"},
                 {"model": model, "messages": msgs, "tools": oai_tools})
    choice = (data.get("choices") or [{}])[0].get("message", {})
    text = choice.get("content") or ""
    calls = []
    for c in (choice.get("tool_calls") or []):
        # A malformed tool call from the vendor must degrade into a visible
        # error, not an uncaught exception that drops the whole stream.
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                args = {}
            calls.append((c["id"], c["function"]["name"], args))
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            raise ToolError(f"vendor returned a malformed tool call: {e}") from None
    return text, calls, choice


def run(prov: ApiProvider, ki, cfg, system: str, task: str,
        *, model: str | None = None, max_steps: int = 12,
        history: list[dict] | None = None,
        approve: Callable[[str, dict], bool] | None = None) -> Iterator[str]:
    """Drive one task to completion, yielding text as it is produced.

    ``approve`` is the seam the CLI driver cannot offer: it is called before
    each tool runs and may refuse. Returning False denies that one call and
    tells the model why, rather than aborting the turn.
    """
    key = prov.key()
    if not key:
        yield f"[{prov.label}: set {prov.env_key} — get one at {prov.signup}]"
        return

    want = model or prov.default_model
    if prov.models and want not in prov.models and want not in prov.models.values():
        yield (f"[{prov.label} does not offer {want!r}; choose from "
               f"{list(prov.models)}]")
        return
    model_id = prov.models.get(want, want)
    tools = tool_schemas(ki)
    # Prior turns travel as REAL messages, not flattened into one user blob
    # with USER:/YOU: markers — the vendor's own multi-turn handling is the
    # thing that makes context work, and counterfeit markers cannot exist in a
    # role field.
    messages: list[dict] = []
    for m in history or []:
        role = "assistant" if m.get("role") == "assistant" else "user"
        body = str(m.get("text", ""))[:8000]
        if body:
            messages.append({"role": role, "content": body})
    messages.append({"role": "user", "content": task})

    for step in range(max_steps):
        try:
            if prov.wire == "anthropic":
                text, calls, raw = _anthropic_turn(prov, model_id, system, messages, tools, key)
            else:
                text, calls, raw = _openai_turn(prov, model_id, system, messages, tools, key)
        except ToolError as e:
            yield f"\n[{prov.label} failed: {e}]"
            return

        if text:
            yield text
        if not calls:
            return

        results = []
        for call_id, name, args in calls:
            yield f"\n`> {name}({', '.join(f'{k}={v!r}' for k, v in args.items())[:80]})`\n"
            if approve is not None and not approve(name, args):
                out = "DENIED by the user. Do not retry; explain what you needed it for."
            else:
                try:
                    out = execute_tool(name, args, ki, cfg)
                except ToolError as e:
                    out = f"ERROR: {e}"
            results.append((call_id, out))

        if prov.wire == "anthropic":
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": cid, "content": out}
                for cid, out in results]})
        else:
            messages.append(raw)
            for cid, out in results:
                messages.append({"role": "tool", "tool_call_id": cid, "content": out})

    yield f"\n[stopped after {max_steps} steps without finishing]"
