"""flow.states — the project state machine and what each state allows.

Plan v3 map A1. States and the allow/deny table come from the desktop issue
(ANALYSIS/01_DESKTOP_ISSUE.md, "统一状态机"); the agent-writable `status` vs
flow-owned `state` split follows kiss_cli/projectrun.py STATUSES (L29); the
enum style follows kiss_cli/policy.py Posture/Enforcement (L37-58).

Rules that matter:
  * Only the flow moves `state`. An agent's progress report may change
    `status` and `summary`, never `state`.
  * `transition()` refuses a move when the evidence for it is missing.
    APPROVED needs a valid approval; COMPLETED needs verified receipts and a
    passed validation. There is no "trust me" path.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path


class FlowError(Exception):
    """A state move or an action that the flow does not allow. Loud, never downgraded."""


class State(str, Enum):
    NEW = "NEW"
    RESOLVING_KIS = "RESOLVING_KIS"
    PLANNING = "PLANNING"
    PLAN_REVIEW = "PLAN_REVIEW"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    APPROVED = "APPROVED"
    ACQUIRING = "ACQUIRING"          # host fetches the approved data; no agent turn
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    # side states
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    REPLAN_REQUIRED = "REPLAN_REQUIRED"
    # software setup sub-flow (reviewers: setup is not a scientific run)
    SETUP_REQUIRED = "SETUP_REQUIRED"
    SETUP_RUNNING = "SETUP_RUNNING"
    SETUP_VERIFIED = "SETUP_VERIFIED"


class Capability(str, Enum):
    READ_KI = "read_ki"
    READ_PROJECT = "read_project"
    WRITE_PLAN_FILES = "write_plan_files"     # runs/plan.json + runs/data-inventory.json only
    WRITE_PROJECT = "write_project"           # inputs/, runs/ (except protected), outputs/, artifacts/
    DOWNLOAD = "download"
    COMPILE = "compile"
    RUN_MODEL = "run_model"
    PLOT = "plot"
    EDIT_SHARED_TOOLS = "edit_shared_tools"   # never granted by any state
    RUN_SETUP = "run_setup"


class Enforcement(str, Enum):
    """How faithfully a provider applied the state's tool policy (kiss_cli/policy.py L48-58)."""
    EXACT = "exact"
    APPROXIMATE = "approximate"
    NONE = "none"


# The per-state allow table (issue "状态权限"). Anything not listed is denied.
_R = {Capability.READ_KI, Capability.READ_PROJECT}
ALLOWED: dict[State, frozenset[Capability]] = {
    State.NEW: frozenset(_R),
    State.RESOLVING_KIS: frozenset(_R),
    State.PLANNING: frozenset(_R | {Capability.WRITE_PLAN_FILES}),
    State.PLAN_REVIEW: frozenset(_R),
    State.WAITING_FOR_USER: frozenset(_R),
    State.APPROVED: frozenset(_R),
    State.ACQUIRING: frozenset(_R),
    State.EXECUTING: frozenset(_R | {Capability.WRITE_PROJECT, Capability.DOWNLOAD,
                                     Capability.COMPILE, Capability.RUN_MODEL, Capability.PLOT}),
    State.VERIFYING: frozenset(_R | {Capability.PLOT}),
    State.COMPLETED: frozenset(_R | {Capability.PLOT}),
    State.BLOCKED: frozenset(_R),
    State.FAILED: frozenset(_R),
    State.FAILED_VALIDATION: frozenset(_R | {Capability.PLOT}),
    State.REPLAN_REQUIRED: frozenset(_R | {Capability.WRITE_PLAN_FILES}),
    State.SETUP_REQUIRED: frozenset(_R),
    State.SETUP_RUNNING: frozenset(_R | {Capability.RUN_SETUP, Capability.COMPILE}),
    State.SETUP_VERIFIED: frozenset(_R),
}

# Which of the eight desktop display labels (kiss_cli/projectrun.py STAGES L25-28) a
# flow state maps to. Display only; the UI panel keeps its wording.
DISPLAY_STAGE: dict[State, str] = {
    # RESOLVING_KIS is the protected task-intake turn: the agent is still understanding the
    # whole request while proposing KI(s). "choosing_ki" made it look like a name picker.
    State.NEW: "understanding", State.RESOLVING_KIS: "understanding",
    State.PLANNING: "preparing", State.PLAN_REVIEW: "preparing",
    State.WAITING_FOR_USER: "preparing", State.APPROVED: "validating",
    State.ACQUIRING: "researching",
    State.EXECUTING: "running", State.VERIFYING: "validating", State.COMPLETED: "results",
    State.BLOCKED: "preparing", State.FAILED: "running", State.FAILED_VALIDATION: "validating",
    State.REPLAN_REQUIRED: "preparing",
    State.SETUP_REQUIRED: "software", State.SETUP_RUNNING: "software", State.SETUP_VERIFIED: "software",
}

# Legal moves and the evidence key each one needs (None = no evidence needed).
_MOVES: dict[tuple[State, str], tuple[State, str | None]] = {
    (State.NEW, "task_received"): (State.RESOLVING_KIS, None),
    (State.RESOLVING_KIS, "kis_resolved"): (State.PLANNING, "selected_kis"),
    (State.RESOLVING_KIS, "ambiguous"): (State.WAITING_FOR_USER, None),
    (State.PLANNING, "plan_written"): (State.PLAN_REVIEW, "plan_valid"),
    (State.PLANNING, "plan_missing"): (State.BLOCKED, None),
    (State.PLAN_REVIEW, "needs_user"): (State.WAITING_FOR_USER, None),
    (State.PLAN_REVIEW, "approved"): (State.APPROVED, "approval"),
    (State.PLAN_REVIEW, "modify"): (State.PLANNING, None),
    (State.PLAN_REVIEW, "drift"): (State.REPLAN_REQUIRED, None),
    (State.APPROVED, "drift"): (State.REPLAN_REQUIRED, None),
    (State.WAITING_FOR_USER, "answered"): (State.PLANNING, None),
    (State.WAITING_FOR_USER, "modify"): (State.PLANNING, None),      # "Modify the plan" on the card
    (State.WAITING_FOR_USER, "kis_resolved"): (State.PLANNING, "selected_kis"),
    (State.WAITING_FOR_USER, "approved"): (State.APPROVED, "approval"),
    (State.APPROVED, "execution_started"): (State.EXECUTING, "setup_verified"),
    (State.APPROVED, "setup_needed"): (State.SETUP_REQUIRED, None),
    # data acquisition sub-flow (FLOW-TARGET-2026-09-17 step 3): host only, returns to
    # APPROVED like SETUP_VERIFIED does, so the setup gate and rerun paths stay untouched
    (State.APPROVED, "acquire"): (State.ACQUIRING, "approval"),
    (State.ACQUIRING, "acquired"): (State.APPROVED, "data_receipted"),
    (State.ACQUIRING, "acquisition_failed"): (State.BLOCKED, None),
    (State.BLOCKED, "retry_acquire"): (State.ACQUIRING, "approval"),
    (State.EXECUTING, "run_finished"): (State.VERIFYING, None),
    (State.EXECUTING, "drift"): (State.REPLAN_REQUIRED, None),
    (State.EXECUTING, "replan"): (State.REPLAN_REQUIRED, None),
    (State.EXECUTING, "error"): (State.FAILED, None),
    (State.VERIFYING, "validated"): (State.COMPLETED, "evidence"),
    (State.VERIFYING, "validation_failed"): (State.FAILED_VALIDATION, None),
    # a rerun goes back through APPROVED so the setup gate and the current-approval check
    # apply again (codex review #7): FAILED* -> APPROVED (approval OK) -> EXECUTING (setup)
    (State.FAILED_VALIDATION, "rerun"): (State.APPROVED, "approval"),
    (State.FAILED, "rerun"): (State.APPROVED, "approval"),
    (State.FAILED_VALIDATION, "replan"): (State.REPLAN_REQUIRED, None),
    (State.FAILED, "replan"): (State.REPLAN_REQUIRED, None),
    (State.REPLAN_REQUIRED, "plan_written"): (State.PLAN_REVIEW, "plan_valid"),
    (State.BLOCKED, "unblocked"): (State.PLANNING, None),
    # waiting for manual (Baidu) files, the user asks for a different plan instead
    (State.ACQUIRING, "modify"): (State.PLANNING, None),
    (State.SETUP_REQUIRED, "setup_started"): (State.SETUP_RUNNING, None),
    (State.SETUP_RUNNING, "setup_verified"): (State.SETUP_VERIFIED, "preflight_ok"),
    (State.SETUP_RUNNING, "setup_failed"): (State.SETUP_REQUIRED, None),
    (State.SETUP_VERIFIED, "resume"): (State.APPROVED, None),
}


def allowed(state: State, cap: Capability) -> bool:
    return cap in ALLOWED.get(State(state), frozenset())


def transition(state: State, event: str, evidence: dict | None = None) -> State:
    """Return the next state, or raise FlowError. Evidence is checked, not assumed."""
    state = State(state)
    key = (state, event)
    if key not in _MOVES:
        raise FlowError(f"no move '{event}' from {state.value}")
    nxt, need = _MOVES[key]
    ev = evidence or {}
    if need is None:
        return nxt
    if need == "approval":
        if ev.get("approval") != "OK":
            raise FlowError(f"{state.value} -> {nxt.value} needs a valid approval "
                            f"(got {ev.get('approval')!r})")
    elif need == "evidence":
        if not (ev.get("receipts_verified") is True and ev.get("validation") == "passed"):
            raise FlowError(f"{state.value} -> COMPLETED needs verified receipts and a passed "
                            f"validation (got receipts_verified={ev.get('receipts_verified')!r}, "
                            f"validation={ev.get('validation')!r})")
    elif need == "plan_valid":
        if ev.get("plan_valid") is not True:
            raise FlowError(f"{state.value} -> PLAN_REVIEW needs a validated plan")
    elif need == "selected_kis":
        if not ev.get("selected_kis"):
            raise FlowError("cannot enter PLANNING without at least one resolved KI")
    elif need == "data_receipted":
        if ev.get("data_receipted") is not True:
            raise FlowError("cannot leave ACQUIRING until every approved input has a receipt")
    elif need == "setup_verified":
        if ev.get("setup_verified") is not True:
            raise FlowError("cannot execute: the KI software is not verified (setup sub-flow)")
    elif need == "preflight_ok":
        if ev.get("preflight_ok") is not True:
            raise FlowError("setup is verified only by the KI's own preflight passing")
    return nxt


@dataclass
class FlowContext:
    """Loaded ONCE per turn (kimi: no per-call disk reloads) and passed to the tool proxy."""
    project: Path
    state: State = State.NEW
    selected_kis: list[str] = field(default_factory=list)
    plan_sha256: str | None = None
    data_inventory_sha256: str | None = None
    approval_sha256: str | None = None
    provider: str = ""
    enforcement: Enforcement = Enforcement.NONE
    updated_at: float = 0.0

    # --- persistence (runs/flow-state.json; separate from the desktop's project-run.json
    #     so an agent-written project-agent-status.json can never touch it) ---------------
    @staticmethod
    def _path(project: Path) -> Path:
        return Path(project) / "runs" / "flow-state.json"

    @classmethod
    def load(cls, project: Path) -> "FlowContext":
        p = cls._path(project)
        ctx = cls(project=Path(project))
        if not p.exists():
            # Once the server registry has named a current state, deleting the workspace
            # copy is corruption, not a way to reset a managed flow to NEW.
            from . import receipts as _receipts
            if _receipts.current_value(Path(project), "state") is not None:
                raise FlowError(f"current flow state file missing: {p}; resolve by hand")
            return ctx                      # first run: NEW
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            # corrupt state is LOUD, never silently NEW (codex review #8)
            raise FlowError(f"flow state file unreadable: {p} ({e}); resolve by hand") from e
        # flow-state controls the RUN_MODEL capability, so structural validity is not
        # enough.  It is signed with the same app-owned per-project key as approvals and
        # receipts; an agent-written state value must never grant itself EXECUTING.
        from . import receipts as _receipts
        if not _receipts.verify(Path(project), raw):
            raise FlowError(f"flow state file signature invalid: {p}; resolve by hand")
        if not _receipts.current_matches(Path(project), "state", raw):
            raise FlowError(f"flow state file is stale, not the server-current state: {p}; "
                            "resolve by hand")
        if not isinstance(raw, dict) or raw.get("state") not in State.__members__:
            raise FlowError(f"flow state file invalid: {p} (state={raw.get('state') if isinstance(raw, dict) else raw!r})")
        if not isinstance(raw.get("state_nonce"), str) or not raw["state_nonce"]:
            raise FlowError(f"flow state file invalid: {p} (missing state nonce)")
        ctx.state = State(raw["state"])
        ctx.selected_kis = [str(k) for k in (raw.get("selected_kis") or [])][:20]
        ctx.plan_sha256 = raw.get("plan_sha256")
        ctx.data_inventory_sha256 = raw.get("data_inventory_sha256")
        ctx.approval_sha256 = raw.get("approval_sha256")
        ctx.provider = str(raw.get("provider") or "")
        try:
            ctx.enforcement = Enforcement(raw.get("enforcement", "none"))
        except ValueError:
            raise FlowError(f"flow state file invalid: unknown enforcement {raw.get('enforcement')!r}")
        ctx.updated_at = float(raw.get("updated_at") or 0.0)
        return ctx

    def save(self) -> Path:
        p = self._path(self.project)
        p.parent.mkdir(parents=True, exist_ok=True)
        d = asdict(self)
        d["project"] = str(self.project)
        d["state"] = self.state.value
        d["enforcement"] = self.enforcement.value
        d["display_stage"] = DISPLAY_STAGE[self.state]
        self.updated_at = time.time()
        d["updated_at"] = self.updated_at
        # A nonce guarantees that two saves in the same clock tick cannot produce the
        # same signed document and accidentally make an older state replay-current.
        d["state_nonce"] = secrets.token_hex(16)
        from . import receipts as _receipts
        d = _receipts.sign(Path(self.project), d)
        # kimi R2 #3: the temp file lives under the protected .geoforge/ tree, never beside the
        # final file where a sibling name could be agent-writable
        tmpdir = Path(self.project) / ".geoforge" / "tmp"
        tmpdir.mkdir(parents=True, exist_ok=True)
        tmp = tmpdir / f"flow-state.{os.getpid()}.json"
        tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
        _receipts.publish_current(Path(self.project), "state", d)
        return p

    def move(self, event: str, evidence: dict | None = None) -> State:
        self.state = transition(self.state, event, evidence)
        self.save()
        return self.state

    def allows(self, cap: Capability) -> bool:
        return allowed(self.state, cap)

    def require(self, cap: Capability, what: str = "") -> None:
        if not self.allows(cap):
            raise FlowError(f"{what or cap.value} is not allowed in state {self.state.value}; "
                            f"finish planning and get approval first")
