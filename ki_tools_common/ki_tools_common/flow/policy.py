"""flow.policy — what each provider may do in each state, and how honestly that is enforced.

Plan v3 map A7. Adopts:
  * the plan-only tool set          cli_process_manager.py `_PLAN_ONLY_BASE_TOOLS` L237 and
                                    `_plan_only_allowed_tools` L241-259 (scoped Bash for the
                                    mode's own read-only tool)
  * "allowedTools both restricts and pre-approves; drop --dangerously-skip-permissions"
                                    cli_process_manager.py L1444-1453
  * shared trees read-only mid-run  .claude/hooks/guard_shared_tool_edits.py L11-17
  * honest labels                   kiss_cli/policy.py Enforcement L48-58, describe() L315-323
  * providers offered               user decision 4 (2026-08-30): claude, codex, kimi, api;
                                    gemini/qwen not offered for scientific projects

Codex review #1 (2026-08-30): protected paths are now STATE-AWARE (plan files writable in
PLANNING only; flow-state/approval/receipts/KI tools never), Claude's EXECUTING argv is
rebuilt from an explicit allow-list (parent grants such as `Write(<project>/**)` or
`Write(<project>/runs/**)` never survive), and every non-wrapper `Bash(...)` is stripped.
Overlap is decided on resolved PATHS, not substrings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .states import State, Capability, Enforcement, allowed

SUPPORTED_PROVIDERS = ("claude", "codex", "kimi", "api")
NOT_OFFERED = ("gemini", "qwen")

# chat's plan-only set (CPM L237) — Claude Code tool names
PLAN_ONLY_BASE_TOOLS = ("WebSearch", "WebFetch", "TodoWrite")

PLAN_FILES = ("runs/plan.json", "runs/data-inventory.json")
ALWAYS_PROTECTED = ("runs/flow-state.json", "runs/approval.json", ".geoforge")
# subtrees an agent may write in EXECUTING (kiss_cli/api.py write_project_file L611-629,
# minus the protected files); everything else under the project is read-only
EXEC_WRITABLE = ("inputs", "outputs", "artifacts", "references", "calibration/cases",
                 "calibration/kis", "runs/logs", "runs/notes")

# desktop API-provider tool names (kiss_cli/api.py tool_schemas L115-489) allowed per state
# GeoForge Database tools: one job each (FLOW-TARGET-2026-09-17 step 1). The old
# multi-mode search_observation_data stays until the data proposal folds into the plan.
DATABASE_API_TOOLS = frozenset({"search_catalogue", "describe_dataset", "estimate_clip"})
_BASE_API = frozenset({"read_ki_file", "list_ki_files", "list_skills", "read_skill",
                       "search_diagnostics", "list_project_files", "read_project_file",
                       "report_project_progress", "request_user_action"}) | DATABASE_API_TOOLS
API_TOOLS_BY_STATE: dict[State, frozenset[str]] = {s: _BASE_API for s in State}
API_TOOLS_BY_STATE[State.PLANNING] = _BASE_API | {"write_plan"}
API_TOOLS_BY_STATE[State.REPLAN_REQUIRED] = _BASE_API | {"write_plan"}
# Data comes in during ACQUIRING (host-driven); EXECUTING keeps fetch_data for public URLs.
API_TOOLS_BY_STATE[State.EXECUTING] = _BASE_API | {"run_preflight", "write_project_file", "run_ki_tool", "run_calibration",
                                                   "fetch_data",
                                                   "create_project_plot", "publish_project_view",
                                                   "request_replan"}
for _s in (State.VERIFYING, State.COMPLETED, State.FAILED_VALIDATION):
    API_TOOLS_BY_STATE[_s] = _BASE_API | {"create_project_plot", "publish_project_view"}
API_TOOLS_BY_STATE[State.SETUP_RUNNING] = _BASE_API | {"run_preflight", "run_builtin_setup", "list_work_files",
                                                       "read_work_file", "write_work_file",
                                                       "run_setup_command", "publish_setup_output"}

# tool name -> capability it needs (checked again inside execute_tool, plan v3 B4)
API_TOOL_CAPABILITY: dict[str, Capability] = {
    "write_plan": Capability.WRITE_PLAN_FILES,
    "write_project_file": Capability.WRITE_PROJECT,
    "run_ki_tool": Capability.RUN_MODEL,
    "run_calibration": Capability.RUN_MODEL,
    "fetch_data": Capability.DOWNLOAD,
    "create_project_plot": Capability.PLOT,
    "publish_project_view": Capability.PLOT,
    "run_builtin_setup": Capability.RUN_SETUP,
    "run_setup_command": Capability.RUN_SETUP,
    "write_work_file": Capability.RUN_SETUP,
}


def api_tools_for(state: State) -> frozenset[str]:
    return API_TOOLS_BY_STATE.get(State(state), _BASE_API)


def api_tool_allowed(state: State, tool_name: str) -> bool:
    if tool_name not in api_tools_for(state):
        return False
    cap = API_TOOL_CAPABILITY.get(tool_name)
    return True if cap is None else allowed(state, cap)


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------

def _res(p: Path | str) -> Path:
    return Path(p).expanduser().resolve(strict=False)


def _under(p: Path, root: Path) -> bool:
    p, root = _res(p), _res(root)
    if p == root:
        return True
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def protected_paths(project: Path, ki_roots: list[Path], state: State | None = None) -> list[Path]:
    """Paths an agent may never write in `state` (all states when state is None):
    flow-state, approval, receipts, every KI's tools/ — and the two plan files outside
    PLANNING / REPLAN_REQUIRED."""
    project = Path(project)
    out = [project / rel for rel in ALWAYS_PROTECTED]
    for r in ki_roots:
        out.append(Path(r) / "tools")
    if state is None or State(state) not in (State.PLANNING, State.REPLAN_REQUIRED):
        out += [project / rel for rel in PLAN_FILES]
    return out


def is_protected(path: Path, project: Path, ki_roots: list[Path], state: State | None = None) -> bool:
    return any(_under(path, prot) for prot in protected_paths(project, ki_roots, state))


def write_allowed(path: Path, project: Path, ki_roots: list[Path], state: State) -> bool:
    """The single write rule the API tool proxy and the argv builder both use."""
    state = State(state)
    if is_protected(path, project, ki_roots, state):
        return False
    project = Path(project)
    if state in (State.PLANNING, State.REPLAN_REQUIRED):
        return any(_res(path) == _res(project / rel) for rel in PLAN_FILES)
    if state == State.EXECUTING:
        return any(_under(path, project / rel) for rel in EXEC_WRITABLE)
    if state == State.SETUP_RUNNING:
        return _under(path, project)   # the setup workspace; setup has its own grants
    return False


# ---------------------------------------------------------------------------
# provider policies
# ---------------------------------------------------------------------------

@dataclass
class ProviderPolicy:
    provider: str
    state: State
    argv_delta: list[str]          # appended to / replacing the driver's provider args
    drop_flags: tuple[str, ...]    # flags the driver must NOT pass (e.g. --dangerously-skip-permissions)
    enforcement: Enforcement
    planning_worktree: bool        # codex/kimi PLANNING: run in a throwaway copy, harvest plan files
    note: str


_CLAUDE_DROP = ("--dangerously-skip-permissions", "--permission-mode", "--tools", "--allowedTools")
_TOOL_RE = re.compile(r"^(?P<name>[A-Za-z]+)\((?P<arg>.*)\)$")


def _assert_key_dir_unreadable(tools: list[str]) -> None:
    """The receipt-signing key dir must not fall under any granted read path (kimi R2 #1)."""
    from .receipts import keys_dir
    kd = keys_dir()
    for t in tools:
        m = _TOOL_RE.match(t)
        if not m or m.group("name") not in ("Read", "Glob", "Grep"):
            continue
        target = Path(m.group("arg").replace("/**", ""))
        if _under(kd, target):
            raise ValueError(f"the receipt key dir {kd} is readable through grant {t!r}; move "
                             f"GEOFORGE_FLOW_KEYS outside every granted tree")


def _read_grants(paths: list[Path]) -> list[str]:
    out = []
    for p in paths:
        p = claude_path(p).rstrip("/")
        out += [f"Read({p}/**)", f"Glob({p}/**)", f"Grep({p}/**)"]
    return out


def claude_path(path: Path | str) -> str:
    """Claude uses // for filesystem-absolute rules, / for project-relative ones.

    https://code.claude.com/docs/en/permissions#read-and-edit
    Windows drive letters are normalized by Claude to /c/... before matching.
    """
    p = str(path).replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", p):
        return "//" + p[0].lower() + p[2:]
    return "/" + p if p.startswith("/") and not p.startswith("//") else p


def _claude_planning_tools(project: Path, ki_roots: dict[str, Path], python: str,
                           wrappers: dict | None = None) -> list[str]:
    tools = list(PLAN_ONLY_BASE_TOOLS)
    # Read code and previous reports: even --help/preflight may have side effects.
    tools += _read_grants(list(ki_roots.values()) + [Path(project)])
    for rel in PLAN_FILES:
        p = claude_path(Path(project) / rel)
        tools += [f"Write({p})", f"Edit({p})"]
    if wrappers and wrappers.get("obs_search"):
        tools.append(f"Bash({wrappers['obs_search']}:*)")
    return tools


def _claude_executing_tools(project: Path, ki_roots: dict[str, Path],
                            base_allowed_tools: list[str] | None, wrappers: dict | None) -> list[str]:
    """Rebuild the EXECUTING allow-list from scratch (codex #1): reads from the base grants
    are kept; writes are ONLY the EXEC_WRITABLE subtrees; Bash is ONLY the wrappers (and the
    base's non-path command grants such as `Bash(git:*)` are dropped too — the wrappers are
    the execution surface)."""
    project = Path(project)
    # kimi R2 #1: NEVER a bare Read/Glob/Grep — that reads the whole filesystem, including the
    # receipt-signing key. Reads are path-scoped: the project, the selected KIs, and the base
    # policy's own path-scoped read grants (binaries, data roles, interpreter env).
    kept: list[str] = ["TodoWrite"]
    kept += _read_grants([project] + list(ki_roots.values()))
    for t in base_allowed_tools or []:
        m = _TOOL_RE.match(t.strip())
        if not m:
            continue
        name, arg = m.group("name"), m.group("arg")
        if name in ("Read", "Glob", "Grep") and arg.strip():
            kept.append(t.strip())
        # Write/Edit/Bash/NotebookEdit/Agent from the base are NOT carried over
    _assert_key_dir_unreadable(kept)
    for rel in EXEC_WRITABLE:
        p = claude_path(project / rel)
        kept += [f"Write({p}/**)", f"Edit({p}/**)"]
    for cmd in (wrappers or {}).values():
        kept.append(f"Bash({cmd}:*)")
    # belt and braces: nothing kept may touch a protected path
    prot = protected_paths(project, list(ki_roots.values()), State.EXECUTING)
    out = []
    for t in kept:
        m = _TOOL_RE.match(t)
        if m and m.group("name") in ("Write", "Edit"):
            target = Path(m.group("arg").replace("/**", ""))
            if any(_under(target, p) or _under(p, target) for p in prot):
                continue
        out.append(t)
    return list(dict.fromkeys(out))


def for_state(state: State, provider: str, project: Path, ki_roots: dict[str, Path],
              python: str = "python3", base_allowed_tools: list[str] | None = None,
              wrappers: dict | None = None) -> ProviderPolicy:
    """Per-state provider policy. `base_allowed_tools` = the desktop's Policy.derive →
    claude_args output (only its Read/Glob/Grep grants are reused); `wrappers` =
    {"run_tool": cmd, "fetch": cmd} — the ONLY Bash allowed in EXECUTING."""
    state = State(state)
    provider = (provider or "").lower()
    if provider in NOT_OFFERED:
        return ProviderPolicy(provider, state, [], (), Enforcement.NONE, False,
                              f"{provider} offers no tool policy; not offered for scientific "
                              f"projects (user decision 2026-08-30)")
    if provider not in SUPPORTED_PROVIDERS:
        return ProviderPolicy(provider, state, [], (), Enforcement.NONE, False,
                              f"unknown provider {provider!r}")

    # Only PLANNING / REPLAN_REQUIRED may write the two plan files. NEW / RESOLVING_KIS /
    # PLAN_REVIEW / WAITING_FOR_USER are read-only turns (codex desktop review #2: the
    # auto-mode "choose a model" turn must not get a worktree or any write).
    planning = state in (State.PLANNING, State.REPLAN_REQUIRED)
    if provider == "api":
        return ProviderPolicy(provider, state, [], (), Enforcement.EXACT, False,
                              "tool proxy filters the schema list by state and re-checks each call")

    if provider == "claude":
        if planning:
            tools = _claude_planning_tools(project, ki_roots, python, wrappers)
            _assert_key_dir_unreadable(tools)
            return ProviderPolicy(provider, state, ["--allowedTools", ",".join(tools),
                                  "--permission-mode", "dontAsk", "--tools",
                                  "Read,Glob,Grep,Write,Edit,Bash,WebSearch,WebFetch,TodoWrite"], _CLAUDE_DROP,
                                  Enforcement.EXACT, False,
                                  "read-only tool wall + the two plan files (CPM L237-259 pattern)")
        if state == State.EXECUTING:
            if not wrappers:
                raise ValueError("EXECUTING on claude needs the receipt wrappers (run_tool, fetch)")
            tools = _claude_executing_tools(project, ki_roots, base_allowed_tools, wrappers)
            return ProviderPolicy(provider, state, ["--allowedTools", ",".join(tools)], _CLAUDE_DROP,
                                  Enforcement.EXACT, False,
                                  "reads from the base grants; writes only under the project's "
                                  "output subtrees; Bash only through the receipt wrappers")
        tools = _read_grants([Path(project)] + list(ki_roots.values()))
        # RESOLVING_KIS is read-only, but a catalogue search is also read-only
        # and may be needed to choose the right KI or ask the right question.
        # ``auto_turn`` passes only obs_search here; it never passes the run,
        # fetch, or download wrappers before planning is approved.
        if state is State.RESOLVING_KIS and wrappers and wrappers.get("obs_search"):
            tools.append(f"Bash({wrappers['obs_search']}:*)")
        return ProviderPolicy(provider, state, ["--allowedTools", ",".join(tools)], _CLAUDE_DROP,
                              Enforcement.EXACT, False, "read-only")

    # codex / kimi: no per-command allowlist (kiss_cli/policy.py codex_args L288-300)
    drop = ("--dangerously-bypass-approvals-and-sandbox", "--yolo", "--sandbox")
    if planning:
        return ProviderPolicy(provider, state, ["--sandbox", "workspace-write"] if provider == "codex" else [],
                              drop, Enforcement.APPROXIMATE, True,
                              "no read-only mode: planning runs in a throwaway worktree; only "
                              "runs/plan.json and runs/data-inventory.json are harvested back")
    if state == State.EXECUTING:
        return ProviderPolicy(provider, state, ["--sandbox", "workspace-write"] if provider == "codex" else [],
                              drop, Enforcement.APPROXIMATE, False,
                              "workspace-write only; a run outside the receipt wrappers has no "
                              "receipt and cannot make the project done")
    return ProviderPolicy(provider, state, ["--sandbox", "read-only"] if provider == "codex" else [],
                          drop, Enforcement.APPROXIMATE, False, "read-only sandbox where the CLI has one")


def describe(pp: ProviderPolicy) -> str:
    """One honest sentence for the PLAN_REVIEW card (kiss_cli/policy.py describe L315-323)."""
    if pp.enforcement is Enforcement.EXACT:
        return f"{pp.provider}: the {pp.state.value} tool policy is applied as written."
    if pp.enforcement is Enforcement.APPROXIMATE:
        return (f"{pp.provider}: {pp.state.value} is contained, not walled — {pp.note}. "
                f"Receipts and the evidence gate still apply.")
    return f"{pp.provider}: no tool policy can be enforced ({pp.note})."
