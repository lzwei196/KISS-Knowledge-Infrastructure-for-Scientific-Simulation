"""flowgate — the desktop's thin adapter over ``ki_tools_common.flow``.

The flow package (states, plan, approval, receipts, policy, contracts) is
driver-neutral and lives in the bundled ``ki_tools_common``; this module is the
only place kiss_cli touches it. It owns:

* loading the bundled package the same way ``harness_runtime`` does (frozen
  build or source checkout, never a stray copy from another workspace);
* ``FlowSession`` — one object per chat turn holding the project's flow state,
  the selected KIs' roots, the current plan/inventory/approval, and the helpers
  the tool proxy calls (``check_tool``, ``write_allowed``, ``record_tool_run``,
  ``write_plan``, ``fetch``);
* the tool policy for the API providers (``api_tools_for``).

Nothing here decides science. It decides WHEN the agent may do what, and writes
the receipts that make a run real. Plan v3 file map: PART B (B4/B5), design
06_PLAN_harness_flow_v2.md §4-5.
"""
from __future__ import annotations

import importlib
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import harness_runtime


class FlowUnavailable(RuntimeError):
    """The bundled flow package cannot be loaded. Fail the turn, never weaken."""


def load():
    """Return the ``ki_tools_common.flow`` package from GeoForge's bundled source."""
    outer = harness_runtime.bundled_source_root()
    outer_text = str(outer)
    if outer_text in sys.path:
        sys.path.remove(outer_text)
    sys.path.insert(0, outer_text)
    importlib.invalidate_caches()
    try:
        pkg = importlib.import_module("ki_tools_common.flow")
        # Import every module used by the desktop at runtime.  In particular,
        # ``tools`` decides whether a script is a trusted KI tool and
        # ``build_data`` is shipped as the data refresh entry point.  A frozen
        # app missing either one must fail its startup/smoke check rather than
        # discovering the incomplete bundle halfway through a project.
        for sub in (
                "states", "resolve", "plan", "approval", "contracts",
                "receipts", "policy", "tools", "build_data", "declared", "decisions", "ki_inputs"):
            importlib.import_module(f"ki_tools_common.flow.{sub}")
    except Exception as error:
        raise FlowUnavailable(
            "ki_tools_common.flow could not be imported from GeoForge's bundled source "
            f"({type(error).__name__}: {error})") from error
    origin = getattr(pkg, "__file__", "")
    if not harness_runtime._inside(origin, outer):
        raise FlowUnavailable(f"ki_tools_common.flow resolved outside this GeoForge build: {origin}")
    return pkg


def _snapshot(project: Path, subs=("inputs", "outputs", "artifacts", "runs/logs")) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for sub in subs:
        base = Path(project) / sub
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.is_file():
                try:
                    st = p.stat()
                    out[str(p)] = (st.st_size, st.st_mtime_ns)
                except OSError:
                    continue
    return out


def _changed(before: dict, after: dict) -> list[Path]:
    return [Path(k) for k, v in after.items() if before.get(k) != v]


@dataclass
class FlowSession:
    """Everything the tool proxy needs for one turn. Load with :meth:`open`."""
    project: Path
    flow: object                      # the ki_tools_common.flow package
    ctx: object                       # flow.states.FlowContext
    ki_roots: dict[str, Path] = field(default_factory=dict)
    python: str = "python3"
    plan: dict | None = None
    inventory: dict | None = None
    approval_doc: dict | None = None
    database_access_mode: str = "direct"

    # ---------------------------------------------------------------- construction
    @classmethod
    def open(cls, project: Path, ki_roots: dict[str, Path], python: str | None = None,
             database_access_mode: str = "direct") -> "FlowSession":
        flow = load()
        ctx = flow.states.FlowContext.load(Path(project))
        if ki_roots and not ctx.selected_kis:
            ctx.selected_kis = list(ki_roots)
        s = cls(project=Path(project), flow=flow, ctx=ctx,
                ki_roots={k: Path(v) for k, v in ki_roots.items()}, python=python or "python3",
                database_access_mode=database_access_mode)
        s.reload_artifacts()
        return s

    def reload_artifacts(self) -> None:
        self.plan, self.inventory = self.flow.plan.read_artifacts(self.project)
        self.approval_doc = self.flow.approval.read(self.project)

    # ---------------------------------------------------------------- state
    @property
    def state(self):
        return self.ctx.state

    @property
    def approval_id(self) -> str:
        return self.flow.approval.approval_id(self.approval_doc or {})

    def approval_status(self) -> str:
        return self.flow.approval.check(self.project)

    def move(self, event: str, evidence: dict | None = None):
        return self.ctx.move(event, evidence)

    # ---------------------------------------------------------------- tool gating (api.py B4)
    def api_tools(self) -> frozenset[str]:
        tools = self.flow.policy.api_tools_for(self.state)
        if self.database_access_mode == "direct":
            return tools
        return frozenset(tools - set(self.flow.policy.DATABASE_API_TOOLS))

    def check_tool(self, name: str) -> None:
        """Raise ``FlowDenied`` when ``name`` is not allowed in the current state."""
        if name not in self.api_tools() or not self.flow.policy.api_tool_allowed(self.state, name):
            raise FlowDenied(
                f"'{name}' is not allowed while the project is in {self.state.value}. "
                + _hint(self.state))

    def write_allowed(self, path: Path) -> bool:
        return self.flow.policy.write_allowed(Path(path), self.project, list(self.ki_roots.values()),
                                              self.state)

    def ki_root_for(self, name: str | None, default_root: Path) -> tuple[str, Path]:
        """Multi-KI (map B4): a tool call may name one of the selected KIs."""
        if not name:
            for k, r in self.ki_roots.items():
                if Path(r).resolve() == Path(default_root).resolve():
                    return k, Path(r)
            return (self.ctx.selected_kis[0] if self.ctx.selected_kis else "KI"), Path(default_root)
        if name not in self.ki_roots:
            raise FlowDenied(f"KI {name!r} is not one of the selected KIs {list(self.ki_roots)}")
        return name, self.ki_roots[name]

    # ---------------------------------------------------------------- receipts (api.py B4)
    def check_step_tool(self, plan_step_id: str | None, ki: str, tool_path: Path | None) -> dict:
        """BEFORE anything runs (codex desktop R2 #4): the step must exist in the approved plan,
        belong to `ki`, and — when it names a tool — that tool must be the one about to run."""
        if self.approval_status() != "OK":
            raise FlowDenied("no valid approval — runs happen only in an approved plan")
        if not plan_step_id:
            raise FlowDenied("plan_step_id is required: name the approved plan step this run executes")
        step = next((s for s in (self.plan or {}).get("steps") or []
                     if isinstance(s, dict) and str(s.get("id")) == str(plan_step_id)), None)
        if step is None:
            raise FlowDenied(f"plan_step_id {plan_step_id!r} is not a step of the approved plan")
        if step.get("ki") != ki:
            raise FlowDenied(f"step {plan_step_id!r} belongs to KI {step.get('ki')!r}, not {ki!r}")
        want = step.get("tool")
        if tool_path is not None and not want:
            raise FlowDenied(
                f"step {plan_step_id!r} has no approved tool; revise and re-approve the plan")
        if want and tool_path is not None:
            try:
                same = Path(want).resolve() == Path(tool_path).resolve()
            except OSError:
                same = str(want) == str(tool_path)
            if not same:
                raise FlowDenied(f"step {plan_step_id!r} is approved for tool {want!r}, not "
                                 f"{str(tool_path)!r}")
        if step.get('kind') != 'download':
            for item in (self.inventory or {}).get('items') or []:
                if item.get('acquisition_id') and item.get('id') in (step.get('inputs') or []):
                    valid = self.flow.receipts.find_download(self.project, item)
                    if not valid:
                        raise FlowDenied(f"Input {item['id']!r} has no intact, bound acquisition. "
                                         "Complete its approved data download before running this step.")
        return step

    def check_calibration_step(self, plan_step_id: str | None, ki: str,
                               runner: Path, binding: dict) -> dict:
        """Bind the native calibration call to the adapter and settings reviewed by the user."""
        step = self.check_step_tool(plan_step_id, ki, runner)
        if step.get("kind") != "calibrate" or not isinstance(step.get("calibration"), dict):
            raise FlowDenied("run_calibration requires an approved typed calibration step")
        if errors := self.flow.plan.calibration_step_errors(step, self.project):
            raise FlowDenied("; ".join(errors))
        if self.flow.plan.sha256(binding) != self.flow.plan.sha256(step["calibration"]):
            raise FlowDenied("calibration adapter or invocation differs from the approved plan; "
                             "revise and re-approve before running")
        return step

    def request_replan(self, reason: str) -> str:
        """EXECUTING -> REPLAN_REQUIRED in the middle of a turn.

        The approval is revoked and ``write_plan`` becomes available at once, so
        the agent that discovered the problem can write the corrected plan in
        the same turn instead of stopping to ask for a state change."""
        S = self.flow.states.State
        if self.state is not S.EXECUTING:
            raise FlowDenied(f"request_replan is only meaningful while EXECUTING, not in {self.state.value}")
        self.move("replan")
        self.flow.approval.revoke(self.project, reason or "agent requested a plan change")
        self.reload_artifacts()
        from . import projectrun
        projectrun.set_stage(self.project, self.flow.states.DISPLAY_STAGE.get(self.state, "preparing"),
                             "The agent is revising the plan")
        return ("Plan change accepted: the project is now REPLAN_REQUIRED and the approval is revoked. "
                "Write the corrected plan now with write_plan (plan first, then data_inventory if "
                "large). Nothing runs until the user approves the revision.")

    def approved_step_environment(self, step: dict, ki_root: Path) -> dict[str, str]:
        """Return only the environment recorded in the signed plan step."""
        try:
            return self.flow.plan.step_environment(step, self.project, ki_root)
        except ValueError as error:
            raise FlowDenied(f"step {step.get('id')!r} has an unsafe environment: {error}") from None

    def step_kind(self, plan_step_id: str | None) -> str:
        for st in (self.plan or {}).get("steps") or []:
            if isinstance(st, dict) and str(st.get("id")) == str(plan_step_id):
                return str(st.get("kind") or "process")
        return "process"

    def record_tool_run(self, *, ki: str, ki_root: Path, command: list[str], cwd: Path,
                        started_at: float, finished_at: float, exit_code: int | None,
                        before: dict, plan_step_id: str | None, stdout_tail: str = "",
                        forcing_source: str | None = None,
                        expected_approval_sha256: str | None = None,
                        execution_status: str | None = None,
                        process_started: bool | None = None,
                        input_arguments: list[str] | None = None,
                        calibration_result: dict | None = None) -> dict:
        """Write the signed run receipt + validation for one tool/model run and return a
        small summary for the agent. Receipts are bound to the current approval; an
        unapproved run cannot get one (the tool proxy refuses earlier, but never trust it)."""
        r = self.flow.receipts
        if self.approval_status() != "OK":
            raise FlowDenied("no valid approval for this run — the receipt cannot be written")
        if expected_approval_sha256 is not None and (
                self.approval_id != expected_approval_sha256 or
                self.flow.approval.approval_id(self.flow.approval.read(self.project)) != expected_approval_sha256):
            raise FlowDenied("approval changed during execution — the receipt cannot be written for a different approval")
        if not plan_step_id:
            raise FlowDenied("run_ki_tool needs plan_step_id (the plan step this run executes)")
        if not any(str(s.get("id")) == str(plan_step_id) for s in (self.plan or {}).get("steps") or []):
            raise FlowDenied(f"plan_step_id {plan_step_id!r} is not a step of the approved plan")
        kind = self.step_kind(plan_step_id)
        subs = ("inputs", "outputs", "artifacts", "runs/logs")
        if kind == "calibrate":
            subs += ("calibration/runs",)
        after = _snapshot(self.project, subs=subs)
        outputs = _changed(before, after)
        step = next(s for s in self.plan["steps"] if str(s.get("id")) == str(plan_step_id))
        typed_calibration = kind == "calibrate" and isinstance(step.get("calibration"), dict)
        if typed_calibration:
            if not isinstance(calibration_result, dict):
                raise FlowDenied("typed calibration needs the native engine's result for its receipt")
            # The runtime copy is generated execution material, not numeric model
            # output. Hash it alongside every raw evaluation artifact so nothing
            # under calibration/ is hidden by a broad bookkeeping exemption.
            from . import calibration
            run_id = str(calibration_result.get("run_id") or "")
            runtime = self.project.resolve() / "calibration" / "runtime" / calibration._slug(ki) / run_id
            runtime_named = self.project / str(calibration_result.get("runtime_ki") or "")
            runtime_bound = bool(run_id and Path(run_id).name == run_id
                                 and runtime_named.resolve() == runtime and runtime.is_dir())
            if runtime_bound:
                for path in runtime.rglob("*"):
                    if path.is_file():
                        if not path.resolve().is_relative_to(runtime):
                            raise FlowDenied("calibration runtime contains a file outside its project directory")
                        if path not in outputs:
                            outputs.append(path)
        inputs = []
        # The caller knows which tokens are arguments (binary commands have no
        # interpreter prefix). Resolve relative paths against the child's cwd.
        for token in input_arguments if input_arguments is not None else command[2:]:
            if not isinstance(token, str):
                continue
            value = token.split("=", 1)[1] if token.startswith("-") and "=" in token else token
            path = Path(value)
            path = path if path.is_absolute() else cwd / path
            if path.is_file() and path not in outputs:
                inputs.append(path)
        logs_dir = self.project / "runs" / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log = logs_dir / f"{ki}_{time.strftime('%Y%m%dT%H%M%S', time.localtime(started_at))}_{secrets.token_hex(6)}.log"
        log.write_text(stdout_tail, encoding="utf-8", errors="replace")
        physical = kind in ("run", "route", "calibrate")
        if typed_calibration:
            validation = calibration.validate_receipt_result(calibration_result, step["calibration"])
            report_path = self.project / str(calibration_result.get("report_path") or "")
            fresh_report = (report_path.resolve().is_relative_to(self.project.resolve() / "calibration" / "runs")
                            and report_path in outputs and report_path.is_file())
            validation["checks"].append({"check": "fresh_calibration_report", "ok": fresh_report,
                                         "detail": str(report_path), "level": "fail"})
            try:
                persisted = json.loads(report_path.read_text(encoding="utf-8")) if fresh_report else {}
                report_matches = (persisted.get("report") == calibration_result.get("report")
                                  and persisted.get("approved_binding") == step["calibration"])
            except (OSError, ValueError, AttributeError):
                report_matches = False
            validation["checks"].extend([
                {"check": "calibration_report_matches_result", "ok": report_matches, "level": "fail"},
                {"check": "calibration_runtime_bound", "ok": runtime_bound, "level": "fail"}])
            if exit_code != 0 or not fresh_report or not report_matches or not runtime_bound:
                validation["status"] = "failed"
        else:
            validation = r.validate_outputs(
                ki_root, outputs,
                run_facts={"errored": exit_code != 0, "output_nonempty": any(
                    p.is_file() and p.stat().st_size > 0 for p in outputs)},
                physical=physical)
        if execution_status == "stopped":
            # The user's Stop is its own outcome: neither passed nor failed, the step is still to do.
            validation["status"] = "stopped"
        # Validation may take time; do not attach this attempt to a later approval.
        if expected_approval_sha256 is not None and (self.approval_status() != "OK" or
                self.flow.approval.approval_id(self.flow.approval.read(self.project)) != expected_approval_sha256):
            raise FlowDenied("approval changed during execution — the receipt cannot be written for a different approval")
        path = r.record_run(self.project, ki=ki, executable=command[0], command=command,
                            cwd=str(cwd), started_at=started_at, finished_at=finished_at,
                            exit_code=exit_code, inputs=inputs, outputs=outputs,
                            stdout_log=str(log), plan_step_id=plan_step_id,
                            approval_sha256=expected_approval_sha256 or self.approval_id,
                            forcing_source=forcing_source,
                            validation=validation, execution_status=execution_status,
                            process_started=process_started)
        return {"receipt": str(path), "run_id": json.loads(path.read_text(encoding="utf-8"))["run_id"],
                "outputs": [p.relative_to(self.project).as_posix()
                            if _under(p, self.project) else str(p)
                            for p in outputs][:50],
                "validation": validation["status"], "execution_status": execution_status,
                "failed_checks": [c["check"] for c in validation["checks"] if not c["ok"]][:12]}

    # ---------------------------------------------------------------- plan files (api.py write_plan)
    def prepare_calibration_steps(self, plan: dict) -> list[str]:
        """Resolve partial typed requests before review; never replace stale supplied hashes."""
        from . import calibration
        errors = []
        for step in plan.get("steps") or []:
            if not isinstance(step, dict) or "calibration" not in step:
                continue
            supplied = step.get("calibration")
            if (step.get("kind") != "calibrate" or not isinstance(supplied, dict)
                    or set(supplied) - self.flow.plan.CALIBRATION_FIELDS):
                errors.append(f"step {step.get('id')!r}: invalid typed calibration binding")
                continue
            try:
                binding, _snapshot = calibration.prepare_invocation(
                    self.project, str(step.get("ki") or ""), supplied)
                for key in ("contract_path", "contract_sha256", "runner_sha256", "expected_case_id"):
                    if key in supplied and supplied[key] != binding[key]:
                        raise ValueError(f"supplied calibration {key} does not match the project adapter")
                step["calibration"] = binding
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                errors.append(f"step {step.get('id')!r}: {error}")
        return errors

    def write_plan(self, plan: dict, inventory: dict) -> list[str]:
        """Validate and write the two plan files. Returns validation errors (empty = written)."""
        if isinstance(plan, dict) and (errors := self.prepare_calibration_steps(plan)):
            return errors
        errs = self.flow.plan.validate(plan, inventory, list(self.ki_roots), self.ki_roots,
                                      for_review=True, project=self.project)
        if errs:
            return errs
        from . import obs_subset
        for item in inventory.get('items') or []:
            if item.get('acquisition_id'):
                try:
                    obs_subset.stamp_item(self.project, item)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    errs.append(f"item {item.get('id')!r}: {error}")
        if errs:
            return errs
        self.flow.plan.write_artifacts(self.project, plan, inventory)
        self.reload_artifacts()
        self.plan_submission = (self.flow.plan.sha256(plan), self.flow.plan.sha256(inventory))
        return []

    # ---------------------------------------------------------------- downloads (api.py fetch_data)
    def fetch(self, url: str, item_id: str, filename: str | None = None,
              plan_step_id: str | None = None, max_bytes: int = 2_000_000_000,
              timeout: int = 600) -> dict:
        r = self.flow.receipts
        if self.approval_status() != "OK":
            raise FlowDenied("no valid approval — downloads happen only in an approved run")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("https", "http"):
            raise FlowDenied("fetch_data accepts http(s) URLs only")
        # Issue #6a: only a planned input Desktop does not bring in itself. A download under a
        # catalogue item replaced Desktop's signed receipt; one under an unplanned id was bound.
        from .acquire import ACQUIRABLE
        item = next((it for it in (self.inventory or {}).get("items") or []
                     if isinstance(it, dict) and str(it.get("id")) == item_id), None)
        if item is None:
            raise FlowDenied(f"{item_id!r} is not in the approved data inventory; "
                             "downloads are for planned inputs only")
        if item.get("delivery") in ACQUIRABLE:
            raise FlowDenied(f"GeoForge acquires {item_id!r} itself from the GeoForge Database "
                             "and keeps its receipt; do not download a replacement")
        if str(item.get("decision") or "").lower() in {"user", "provide", "you"}:
            raise FlowDenied(f"the user provides {item_id!r}; use their file, do not download one")
        safe_item = "".join(c if c.isalnum() or c in "-_." else "_" for c in item_id)[:80]
        dest_dir = self.project / "inputs" / "raw" / safe_item
        dest_dir.mkdir(parents=True, exist_ok=True)
        name = filename or (Path(parsed.path).name or "download.bin")
        name = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)[:160]
        dest = dest_dir / name
        if not _under(dest, dest_dir):
            raise FlowDenied("bad filename")
        requested_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        req = urllib.request.Request(url, headers={"User-Agent": "GeoForge-Desktop/flow"})
        status = None
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as fh:
            status = getattr(resp, "status", None)
            total = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    fh.close(); dest.unlink(missing_ok=True)
                    raise FlowDenied(f"download exceeds {max_bytes} bytes")
                fh.write(chunk)
        path = r.record_download(self.project, item_id=item_id, source=parsed.netloc,
                                 request_url=url, http_status=status, raw_files=[dest],
                                 approval_sha256=self.approval_id, requested_at=requested_at,
                                 plan_step_id=plan_step_id,
                                 inventory_item=next((it for it in (self.inventory or {}).get("items", [])
                                                      if str(it.get("id")) == item_id), None))
        # mark the inventory item as ready (the app does this, not the agent)
        if self.inventory:
            for it in self.inventory.get("items") or []:
                if isinstance(it, dict) and str(it.get("id")) == item_id:
                    it["status"] = "ready"
                    it.setdefault("local_paths", []).append(dest.relative_to(self.project).as_posix())
        return {"receipt": str(path), "path": dest.relative_to(self.project).as_posix(),
                "bytes": dest.stat().st_size, "http_status": status}

    def evidence(self, enforcement: str = "exact") -> dict:
        return self.flow.receipts.evidence(self.project, self.plan, self.approval_doc,
                                           enforcement=enforcement, inventory=self.inventory)


class FlowDenied(Exception):
    """A tool call the flow does not allow in this state. Shown to the agent as ERROR."""


def _under(p: Path, root: Path) -> bool:
    try:
        Path(p).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def _hint(state) -> str:
    v = getattr(state, "value", str(state))
    if v in ("NEW", "RESOLVING_KIS", "PLANNING", "REPLAN_REQUIRED"):
        return ("Finish the plan first: write runs/plan.json and runs/data-inventory.json "
                "with write_plan, then the user approves.")
    if v in ("PLAN_REVIEW", "WAITING_FOR_USER", "APPROVED"):
        return "The plan is waiting for the user's approval; nothing runs before that."
    if v in ("SETUP_REQUIRED", "SETUP_RUNNING"):
        return "The KI software is not verified yet; finish setup first."
    if v in ("COMPLETED", "VERIFYING", "FAILED_VALIDATION", "FAILED"):
        return "This run is closed; a rerun needs a fresh approval."
    return ""
