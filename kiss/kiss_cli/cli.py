"""``kiss`` — the command line entry point.

    kiss list                 what is available
    kiss info VIC             what one KI needs
    kiss doctor [VIC]         what would stop this working elsewhere
    kiss init VIC             set it up here, hand the rest to an agent
    kiss run VIC -- ./x.py    run something with the KI's paths resolved
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from . import doctor, gui, handoff, install, install_locations, paths, port, recipe
from .catalog import Catalog
from .manifest import Manifest

C = {
    "BLOCK": "\033[31m", "WARN": "\033[33m", "INFO": "\033[36m",
    "ok": "\033[32m", "dim": "\033[2m", "b": "\033[1m", "0": "\033[0m",
}


def _c(key: str, s: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return s
    return f"{C.get(key, '')}{s}{C['0']}"


def _catalog(args) -> Catalog:
    return Catalog(args.models) if args.models else Catalog.discover()


def _manifest_for(ki, repo_root: Path) -> Manifest:
    if ki.manifest:
        return Manifest.load(ki.manifest)
    shipped = repo_root / "kiss" / "manifests" / f"{ki.name}.yaml"
    if shipped.exists():
        return Manifest.load(shipped)
    return Manifest.stub_for(ki)


# --- commands ---------------------------------------------------------------

def cmd_list(args) -> int:
    cat = _catalog(args)
    kis = cat.search(args.filter) if args.filter else list(cat)
    if args.json:
        print(json.dumps([{"name": k.name, **k.meta} for k in kis], indent=2))
        return 0
    print(f"{_c('b','MODEL'):<32} {'LANGUAGE':<12} {'VERSION':<12} SOURCE")
    for ki in sorted(kis, key=lambda k: k.name.lower()):
        m = ki.meta
        src = (m.get("repo_url") or "—").replace("https://", "")[:44]
        print(f"{ki.name:<24} {str(m.get('language') or '—'):<12} "
              f"{str(m.get('version') or '—'):<12} {_c('dim', src)}")
    print(f"\n{len(kis)} of {len(cat)} packages")
    return 0


def cmd_info(args) -> int:
    ki = _catalog(args).get(args.model)
    repo_root = ki.root.parent.parent
    man = _manifest_for(ki, repo_root)
    m = ki.meta
    print(_c("b", f"\n{ki.name}"))
    print(f"  {m.get('reference') or '(no reference recorded)'}\n")
    for k in ("language", "version", "license", "repo_url", "spatial", "temporal"):
        if m.get(k):
            print(f"  {k:<12} {m[k]}")
    print(f"\n  {_c('b','ships')}")
    for label, p in (("SKILL.md", ki.skill), ("dag.yaml", ki.dag),
                     ("preflight", ki.preflight), ("triplets", ki.triplets),
                     ("manifest", ki.manifest)):
        print(f"    {'yes' if p else _c('WARN','no ')}  {label}")
    if ki.forcing_vars:
        print(f"\n  {_c('b','forcing')}  {', '.join(ki.forcing_vars)}")
    ver_colour = "ok" if man.verified == "observed" else "WARN"
    print(f"\n  {_c('b','install')}   strategy={man.acquire.strategy if man.acquire else '—'}"
          f"  verified={_c(ver_colour, man.verified)}")
    if man.notes:
        print(f"    {_c('dim', man.notes)}")
    port = ki.portability
    print(f"\n  {_c('b','portability')}  "
          + (_c("ok", "clean") if port.clean else
             _c("BLOCK", f"{port.total} authoring paths across {len(port.files)} files")))
    if port.roles_needed:
        print(f"    needs paths for: {', '.join(port.roles_needed)}")
    print()
    return 0


def cmd_doctor(args) -> int:
    cat = _catalog(args)
    if args.model:
        kis = [cat.get(args.model)]
        findings = doctor.check_ki(kis[0])
        rep = doctor.Report(findings=findings, checked=1)
    else:
        rep = doctor.run(cat)

    if args.json:
        print(json.dumps([f.__dict__ for f in rep.findings], indent=2))
        return 1 if rep.by_severity(doctor.BLOCK) else 0

    if args.model:
        for f in rep.findings:
            print(f"  {_c(f.severity, f.severity):<14} {f.check:<24} {f.detail}")
        if not rep.findings:
            print(_c("ok", "  clean — nothing would stop this working elsewhere"))
    else:
        print(f"\n{_c('b', f'{rep.checked} KI packages checked')}\n")
        print(f"  {'SEV':<6} {'CHECK':<26} PACKAGES")
        for check, fs in sorted(rep.by_check().items(), key=lambda kv: (-len(kv[1]), kv[0])):
            sev = fs[0].severity
            print(f"  {_c(sev, sev):<15} {check:<26} {len(fs):>4}")
        blocked = rep.blocked_kis()
        print(f"\n  {_c('BLOCK', str(len(blocked)))} packages have at least one BLOCK finding.")
        if args.verbose:
            print()
            for f in sorted(rep.findings, key=lambda f: (f.severity, f.ki)):
                print(f"  {_c(f.severity, f.severity):<14} {f.ki:<22} {f.check:<22} {f.detail[:90]}")
    return 1 if rep.by_severity(doctor.BLOCK) else 0


def cmd_init(args) -> int:
    cat = _catalog(args)
    ki = cat.get(args.model)
    repo_root = ki.root.parent.parent

    # Default to ~/kiss/<model>, the same layout the app and `kiss verify` use.
    # Installing to ./kiss-<model> while verify looked in ~/kiss meant the two
    # commands could not see each other's work: `kiss init MODFLOW6` followed
    # by `kiss verify MODFLOW6` reported the model missing.
    default_workroot = Path.home() / "kiss"
    if args.workdir:
        root = install_locations.select(default_workroot, ki.name, args.workdir)
    else:
        root = install_locations.resolve(default_workroot, ki.name)
    root.mkdir(parents=True, exist_ok=True)
    cfg_file = root / paths.CONFIG_NAME
    if cfg_file.exists():
        cfg = paths.KissConfig.load(root)
        print(_c("dim", f"using existing {cfg_file}"))
    else:
        cfg = paths.KissConfig.default(root)
        cfg.python = args.python or install.runtime_python(sys.executable)
        cfg.relocation = args.relocation
        cfg_file.write_text(cfg.dumps(), encoding="utf-8")
        print(f"  wrote {cfg_file}")

    man = _manifest_for(ki, repo_root)
    print(_c("b", f"\ninitialising {ki.name}") +
          _c("dim", f"  (strategy: {man.acquire.strategy if man.acquire else 'none'})\n"))

    result = install.InstallResult(model=ki.name)

    # Materialise the KI: a working copy with this machine's real paths written
    # in place of the KISSPATH_* placeholders. Everything downstream — preflight,
    # the model's own tools, its config files — then sees true paths.
    live = root / "ki"
    mrep = port.materialise(ki.root, live, cfg)
    # A file that stopped parsing once the real path was written in is a failure,
    # not a footnote — writing broken JSON/YAML silently is the whole class of
    # bug this installer exists to avoid.
    ok = not mrep.unresolved and not mrep.corrupted
    result.add(install.Step(
        "materialise", ok,
        f"{mrep.tokens_replaced} placeholders resolved into {live}" if ok else
        f"unresolved placeholders: {', '.join(sorted(mrep.unresolved))} "
        f"— add these roles to {paths.CONFIG_NAME}"))
    print(f"  [1/8] materialise KI .. {_c('ok' if ok else 'BLOCK', 'ok' if ok else 'FAILED')}"
          + _c("dim", f"  ({mrep.tokens_replaced} paths written)"))
    if mrep.unresolved:
        print(_c("dim", "        unresolved: " + ", ".join(sorted(mrep.unresolved))))
    for c in mrep.corrupted[:5]:
        print(_c("dim", f"        corrupted by your path values: {c}"))
    if mrep.undeliverable_files:
        print(_c("dim", f"        note: {mrep.undeliverable_files} files reference the "
                        "author's private tooling; those instructions cannot be followed"))
    # From here on the KI in use is the materialised copy, not the package.
    ki = type(ki)(name=ki.name, root=live)

    s = result.add(install.ensure_python_env(cfg))
    if s.ok and not args.python:
        cfg_file.write_text(cfg.dumps(), encoding="utf-8")
    print(f"  [2/8] python env ...... {_c('ok' if s.ok else 'BLOCK', s.mark)}")

    s = result.add(install.install_ki_tools_common(cfg, repo_root))
    print(f"  [3/8] ki_tools_common . {_c('ok' if s.ok else 'BLOCK', s.mark)}")
    if not s.ok:
        print(_c("dim", "        " + s.detail.strip().splitlines()[0][:100]))

    s = result.add(install.check_system_deps(man.system_deps))
    print(f"  [4/8] system deps ..... {_c('ok' if s.ok else 'BLOCK', s.mark)}")

    s = result.add(install.install_python_deps(man.python_deps, cfg.python))
    print(f"  [5/8] python deps ..... {_c('ok' if s.ok else 'BLOCK', s.mark)}")

    prefix = cfg.roles["binaries"] / (man.install_dir or ki.name)
    blocker = next((step for step in result.steps if not step.ok), None)
    if blocker:
        strategy = man.acquire.strategy if man.acquire else "none"
        s, binary = install.Step(
            f"acquire[{strategy}]", False,
            f"not run because {blocker.name} failed: {blocker.detail}", skipped=True,
        ), None
    else:
        s, binary = install.acquire(man, prefix, cfg.python, ki=ki)
    result.add(s)
    result.binary = binary
    for note in install.place_where_the_ki_expects(ki, binary, cfg, prefix):
        print(_c("dim", f"        {note}"))
    print(f"  [6/8] acquire ......... {_c('ok' if s.ok else 'WARN' if s.skipped else 'BLOCK', s.mark)}")
    if not s.ok:
        print(_c("dim", "        " + s.detail.strip().splitlines()[0][:100]))

    if man.depends_on:
        print(_c("dim", f"        couples with: {', '.join(man.depends_on)}"))

    s = result.add(install.check_data(man, cfg))
    print(f"  [7/8] data ............ {_c('ok' if s.ok else 'WARN', s.mark)}")

    blocker = next((step for step in result.steps if not step.ok), None)
    if blocker:
        s = result.add(install.Step(
            "preflight", False,
            f"not run because {blocker.name} did not complete: {blocker.detail}",
            skipped=True,
        ))
    else:
        s = result.add(install.run_preflight(ki, cfg.python, cfg))
    print(f"  [8/8] preflight ....... "
          f"{_c('ok' if s.ok else 'WARN' if s.skipped else 'BLOCK', s.mark)}")

    written = handoff.write(ki, result, man, cfg, root)
    install_locations.record(
        ki.name, root, cfg, ki_root=ki.root, verified=result.ok)
    print(f"    agent handoff ... {_c('ok', 'ok')} ({len(written)} files)")

    print()
    if result.ok:
        print(_c("ok", f"  {ki.name} is ready.") + f"  Working directory: {root}")
    else:
        n = len(result.failures)
        print(_c("WARN", f"  {ki.name} is not finished — {n} step(s) need attention."))
        print(f"  Open {root} in your coding agent and say:")
        print(_c("b", f'      "finish the {ki.name} setup"'))
        print(_c("dim", "  It will read CLAUDE.md, which lists exactly what failed,"))
        print(_c("dim", f"  alongside the KI's own diagnostics for this model."))
    return 0 if result.ok else 2


def cmd_app(args) -> int:
    from . import app as _app
    return _app.run_app(args.models, workroot=args.workroot)


def cmd_gui(args) -> int:
    return gui.serve(args.models, port=args.port, open_browser=not args.no_browser,
                     workroot=args.workroot, host=args.host,
                     auto_update=args.desktop_server)


def cmd_recipe(args) -> int:
    import json as _json

    cat = _catalog(args)
    ki = cat.get(args.model)
    repo_root = ki.root.parent.parent
    harvested = {}
    hp = repo_root / "kiss" / "manifests" / "_harvested_produces.json"
    if hp.exists():
        harvested = _json.loads(hp.read_text(encoding="utf-8"))
    res = recipe.gather(ki, harvested)
    if args.json:
        print(_json.dumps({
            "model": res.model, "repo": res.repo, "ref": res.ref,
            "produces": res.produces, "strength": res.strength(),
            "evidence": [{"kind": e.kind, "path": e.path} for e in res.evidence],
            "notes": res.notes,
        }, indent=2))
        return 0
    print(recipe.brief(res, ki))
    return 0


def cmd_run(args) -> int:
    cat = _catalog(args)
    ki = cat.get(args.model)
    cfg = paths.KissConfig.load(Path(args.workdir) if args.workdir else None)
    if not args.argv:
        print("nothing to run — pass a command after --", file=sys.stderr)
        return 2
    argv = list(args.argv)
    if cfg.relocation == "sandbox":
        if not paths.have_sandbox():
            print("bubblewrap (bwrap) is not installed — cannot relocate paths.\n"
                  "Install it, or set relocation = \"symlink\" in kiss.toml.", file=sys.stderr)
            return 3
        argv = paths.sandbox_command(cfg, argv, cwd=ki.root)
    os.execvp(argv[0], argv)


def _flow_project(explicit: str | None) -> Path:
    """The chat project a receipt wrapper acts on: --project, $KISS_PROJECT, or the nearest
    ancestor of the cwd that carries runs/flow-state.json (the agent runs inside the project)."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("KISS_PROJECT")
    if env:
        return Path(env).expanduser().resolve()
    here = Path.cwd().resolve()
    for cand in (here, *here.parents):
        if (cand / "runs" / "flow-state.json").is_file():
            return cand
    raise FileNotFoundError("no flow-managed project here: pass --project or run inside the project")


def _flow_ki_root(project: Path, name: str, args) -> Path:
    live = project / "models" / name / "ki"
    if live.is_dir():
        return live
    return Path(_catalog(args).get(name).root)


#: Errors main() already reports as ``kiss: <message>`` with exit status 2.
_REPORTED_ERRORS = (KeyError, FileNotFoundError, NotADirectoryError, ValueError)


def _worker_entry(handler):
    """Answer a crash with a traceback on stderr and exit status 1.

    These commands run as children of the Desktop, which waits with no timeout.
    In the windowed frozen Windows exe an uncaught exception becomes
    PyInstaller's modal traceback dialog nobody sees, so the child never exits.
    """
    @functools.wraps(handler)
    def run(args) -> int:
        try:
            return handler(args)
        except _REPORTED_ERRORS:
            raise
        except Exception:
            if sys.stderr is not None:
                import traceback
                traceback.print_exc(file=sys.stderr)
            return 1
    return run


@_worker_entry
def cmd_run_tool(args) -> int:
    """Run one KI tool for an APPROVED plan step and write the signed receipt (plan v3 B7).
    This is the only way a CLI agent's run can count; anything run outside it has no receipt."""
    from . import flowgate, project_paths
    from .execution import execute_ki_tool
    project = _flow_project(args.project)
    ki_root = _flow_ki_root(project, args.ki, args)
    try:
        fallback = None
        if not (project / "models" / args.ki / paths.CONFIG_NAME).exists() and not Path(ki_root).is_relative_to(project / "models"):
            fallback = paths.KissConfig.load(project)
        cfg = project_paths.execution_config(
            project, args.ki, ki_root, fallback=fallback)
    except (OSError, ValueError) as e:
        print(f"run-tool refused: {e}", file=sys.stderr)
        return 3
    fs = flowgate.FlowSession.open(project, {args.ki: ki_root}, python=str(cfg.python))
    if fs.state.value != "EXECUTING":
        print(f"run-tool refused: project is in {fs.state.value}, not EXECUTING", file=sys.stderr)
        return 3
    if fs.approval_status() != "OK":
        print("run-tool refused: no valid approval (plan changed or never approved)", file=sys.stderr)
        return 3
    tool = (ki_root / args.tool).resolve() if not Path(args.tool).is_absolute() else Path(args.tool).resolve()
    from ki_tools_common.flow.tools import is_ki_tool
    if not is_ki_tool(ki_root, tool):
        print(f"run-tool refused: {args.tool} is not a tool under {ki_root / 'tools'}", file=sys.stderr)
        return 3
    argv = list(args.argv)
    if argv and argv[0] == "--":
        argv = argv[1:]
    import signal
    import threading
    from .execution import LIVE_PROCESSES
    if threading.current_thread() is threading.main_thread():
        # Stop SIGTERMs the agent CLI's process tree, which a direct run-tool is in.
        # While the tool runs, end like Ctrl-C: its tree is killed and the attempt receipted.
        # Before launch the stop marker refuses it; after exit the finished run keeps its receipt.
        def interrupt(*_):
            if LIVE_PROCESSES:
                raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)
    try:
        result = execute_ki_tool(
            flow=fs, cfg=cfg, project=project, ki=args.ki, ki_root=ki_root,
            tool=tool, arguments=argv, cwd=project, plan_step_id=args.step,
            python_tool=tool.suffix == ".py", timeout=None)
    except flowgate.FlowDenied as e:
        print(f"run-tool refused: {e}", file=sys.stderr)
        return 3
    print(result.output)
    if result.detail:
        print(result.detail, file=sys.stderr)
    if result.receipt_error:
        print(f"[receipt NOT written: {result.receipt_error}]", file=sys.stderr)
        return 3
    if result.receipt:
        print("[RECEIPT] " + json.dumps(result.receipt, ensure_ascii=False))
    if result.exit_code is not None:
        return result.exit_code
    return {"timed_out": 124, "interrupted": 130, "stopped": 130}.get(result.status, 1)


def cmd_fetch(args) -> int:
    """Download one public file for an APPROVED plan and write the signed download receipt."""
    from . import flowgate
    project = _flow_project(args.project)
    fs = flowgate.FlowSession.open(project, {})
    if fs.state.value != "EXECUTING":
        print(f"fetch refused: project is in {fs.state.value}, not EXECUTING", file=sys.stderr)
        return 3
    try:
        info = fs.fetch(args.url, args.item, filename=args.filename, plan_step_id=args.step)
    except flowgate.FlowDenied as e:
        print(f"fetch refused: {e}", file=sys.stderr)
        return 3
    except OSError as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        return 1
    print("[RECEIPT] " + json.dumps(info, ensure_ascii=False))
    return 0


def cmd_ask_question(args) -> int:
    """Publish one planning choice through the same host validator as the bridge."""
    from . import flowrun
    try:
        if len(args.question.encode("utf-8")) > 60 * 1024:
            raise ValueError("question JSON is too large")
        payload = json.loads(args.question)
        result = flowrun.request_planning_question(_flow_project(None), payload)
    except (OSError, ValueError, TypeError) as error:
        print(f"ask-question refused: {error}", file=sys.stderr)
        return 3
    print(json.dumps({"id": result["id"], "status": result["status"],
                      "message": "Question shown. Stop and wait for the user's answer."},
                     ensure_ascii=False))
    return 0


def cmd_obs_search(args) -> int:
    """Search GeoForge Database without exposing its token."""
    from . import obs_access
    try:
        result = obs_access.search_catalogue(
            q=(getattr(args, "query_option", "") or args.query or ""),
            offset=args.offset, limit=args.limit,
            bbox=getattr(args, "bbox", None), start=getattr(args, "start", None),
            end=getattr(args, "end", None), variable=getattr(args, "variable", "") or "",
            category=getattr(args, "category", "") or "",
            describe_dataset_id=getattr(args, "describe_dataset_id", "") or "",
            resolve_dataset_id=getattr(args, "resolve_dataset_id", "") or "",
            time_step=getattr(args, "time_step", "") or "",
            delivery=getattr(args, "delivery", "") or "")
    except obs_access.ObsAccessError as error:
        print(f"GeoForge Database search failed: {error}", file=sys.stderr)
        return 3 if error.code in {
            "missing_token", "invalid_token", "expired_token", "revoked_token"} else 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_calibration_status(args) -> int:
    """Prove that the fixed engine and required optimizers are in this runtime."""
    from . import calibration

    status = calibration.framework_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0 if status.get("ready") else 1


def cmd_harness_status(args) -> int:
    """Prove the bundled harness and its enforced flow modules are complete."""
    from . import flowgate, harness_runtime

    cat = _catalog(args)
    if args.model:
        ki = cat.get(args.model)
    else:
        ki = next((candidate for candidate in cat if candidate.skill), None)
        if ki is None:
            print(json.dumps({"ready": False, "error": "no KI with SKILL.md"},
                             indent=2))
            return 1
    status = harness_runtime.status(ki.root)
    try:
        flow = flowgate.load()
        status["flow_ready"] = True
        status["flow_source"] = str(getattr(flow, "__file__", ""))
        # The modules flowgate.load() imports; keep the two lists identical.
        status["flow_modules"] = [
            "states", "resolve", "plan", "approval", "contracts",
            "receipts", "policy", "tools", "build_data", "declared",
            "decisions", "ki_inputs",
        ]
    except flowgate.FlowUnavailable as error:
        status["flow_ready"] = False
        status["flow_error"] = str(error)
        status["ready"] = False
    status["model"] = ki.name
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0 if status.get("ready") else 1


def cmd_calibrate(args) -> int:
    """Run the same approved, receipted native operation used by the Desktop API."""
    from . import api, flowgate, project_paths
    from .catalog import KI
    import signal
    import threading
    from .execution import LIVE_PROCESSES
    if threading.current_thread() is threading.main_thread():
        # A provider's Stop signals this wrapper and the engine tree. Keep the
        # wrapper alive long enough to persist the interrupted calibration report.
        def interrupt(*_):
            if LIVE_PROCESSES:
                raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, interrupt)

    try:
        obs_shapes = json.loads(args.obs_shapes_json)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--obs-shapes-json is not valid JSON: {exc}") from None
    if not getattr(args, "plan_step_id", None):
        raise ValueError("--plan-step-id is required: calibrations execute an approved plan step")
    project = Path(args.project).expanduser().resolve()
    expected_root = project_paths._model_home(project, args.model) / "ki"
    ki_root = Path(args.ki_path).expanduser().resolve()
    if ki_root != expected_root:
        raise ValueError("--ki-path must be this project's materialized KI workspace")
    cfg = project_paths.execution_config(project, args.model, expected_root)
    fs = flowgate.FlowSession.open(project, {args.model: ki_root}, python=cfg.python)
    if args.expected_case_id is not None:
        step = next((step for step in (fs.plan or {}).get("steps", [])
                     if step.get("id") == args.plan_step_id), {})
        if args.expected_case_id != (step.get("calibration") or {}).get("expected_case_id"):
            raise ValueError("--expected-case-id differs from the approved calibration case")
    summary = json.loads(api.execute_tool(
        "run_calibration", {"plan_step_id": args.plan_step_id, "obs_shape_by_var": obs_shapes,
                            "algorithm": args.algorithm, "budget": args.budget, "seed": args.seed,
                            "determining_metric": args.determining_metric},
        KI(args.model, ki_root), cfg, project_mode=True, flow=fs))
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    if summary.get("status") in {"stopped", "interrupted"}:
        return 130
    return 0 if (summary.get("receipt") or {}).get("validation") == "passed" else 2


@_worker_entry
def cmd_calibration_worker(args) -> int:
    from . import calibration
    return calibration.run_worker(args.request_path)


@_worker_entry
def cmd_install_download_worker(args) -> int:
    return install.run_download_worker(args.request_path)


# --- wiring -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kiss", description="Knowledge Infrastructure installer")
    p.add_argument("--models", type=Path, help="path to the models/ directory")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("list", help="list available KI packages")
    q.add_argument("filter", nargs="?", help="substring to match")
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_list)

    q = sub.add_parser("info", help="show what one KI needs")
    q.add_argument("model")
    q.set_defaults(fn=cmd_info)

    q = sub.add_parser("doctor", help="report what would stop a KI working elsewhere")
    q.add_argument("model", nargs="?")
    q.add_argument("--json", action="store_true")
    q.add_argument("-v", "--verbose", action="store_true")
    q.set_defaults(fn=cmd_doctor)

    q = sub.add_parser("init", help="set a KI up on this machine")
    q.add_argument("model")
    q.add_argument("-w", "--workdir", help="where to install (default ~/kiss/<model>)")
    q.add_argument("--python", help="interpreter to install into")
    q.add_argument("--relocation", default="sandbox", choices=("sandbox", "port", "symlink"))
    q.set_defaults(fn=cmd_init)

    q = sub.add_parser("app", help="open KISS in its own native window (default when launched bare)")
    q.add_argument("-w", "--workroot", type=Path)
    q.set_defaults(fn=cmd_app)

    q = sub.add_parser("gui", help="browse and install through a local web UI")
    q.add_argument("-p", "--port", type=int, default=8765)
    q.add_argument("--host", default="127.0.0.1",
                   help="bind address; 0.0.0.0 to reach the GUI from another "
                        "machine (no auth — only on a network you trust)")
    q.add_argument("--no-browser", action="store_true")
    q.add_argument("--desktop-server", action="store_true", help=argparse.SUPPRESS)
    q.add_argument("-w", "--workroot", type=Path, help="where installs live (default ~/kiss)")
    q.set_defaults(fn=cmd_gui)

    q = sub.add_parser("recipe", help="gather build evidence for a model and print the agent brief")
    q.add_argument("model")
    q.add_argument("--json", action="store_true", help="emit the raw research as json")
    q.set_defaults(fn=cmd_recipe)

    q = sub.add_parser("papers", help="the literature behind a model, and how to get it")
    q.add_argument("model", nargs="?", help="one model, or a summary of all")
    q.add_argument("--quantity", help="only papers covering this quantity")
    q.add_argument("--role", help="only papers with this role")
    q.add_argument("--check", action="store_true", help="validate the shipped files")
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_papers)

    q = sub.add_parser("verify", help="prove a model actually runs on this machine")
    q.add_argument("model", nargs="?", help="one model, or all of them if omitted")
    q.add_argument("-w", "--workdir", help="where the install lives")
    q.add_argument("--python", help="interpreter to probe scripts with")
    q.add_argument("--timeout", type=int, default=25)
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_verify)

    q = sub.add_parser("run", help="run a command with the KI's paths resolved")
    q.add_argument("model")
    q.add_argument("-w", "--workdir")
    q.add_argument("argv", nargs=argparse.REMAINDER)
    q.set_defaults(fn=cmd_run)

    q = sub.add_parser("run-tool", help="run one KI tool for an approved plan step and write its receipt")
    q.add_argument("ki", help="the selected KI the tool belongs to")
    q.add_argument("tool", help="tool path relative to the KI root (tools/...)")
    q.add_argument("--step", required=True, help="the approved plan step id (runs/plan.json steps[].id)")
    q.add_argument("--project", help="the chat project (default: $KISS_PROJECT or the cwd's project)")
    q.add_argument("argv", nargs=argparse.REMAINDER, help="arguments for the tool (after --)")
    q.set_defaults(fn=cmd_run_tool)

    q = sub.add_parser("ask-question", help="show one planning question; never approve, download or run")
    q.add_argument("question", help="one JSON object with kind=choice, title, message and options")
    q.set_defaults(fn=cmd_ask_question)

    q = sub.add_parser("fetch", help="download one public file for an approved plan and write its receipt")
    q.add_argument("url")
    q.add_argument("--item", required=True, help="the data-inventory item id")
    q.add_argument("--filename")
    q.add_argument("--step")
    q.add_argument("--project")
    q.set_defaults(fn=cmd_fetch)

    q = sub.add_parser(
        "obs-search", help="search the authenticated GeoForge Database catalogue")
    q.add_argument("query", nargs="?", default="")
    q.add_argument("--query", dest="query_option", default="",
                   help="search words (alias for the positional query)")
    q.add_argument("--bbox", help="min_lon,min_lat,max_lon,max_lat")
    q.add_argument("--start", help="YYYY-MM-DD")
    q.add_argument("--end", help="YYYY-MM-DD")
    q.add_argument("--variable", default="")
    q.add_argument("--describe", dest="describe_dataset_id", default="", help="Read a dataset's actual source schema; no download")
    q.add_argument("--resolve", dest="resolve_dataset_id", default="")
    q.add_argument("--time-step", default="", choices=["", "daily", "3hr"])
    q.add_argument("--category", default="")
    q.add_argument("--delivery", default="", choices=["", "served", "manual"])
    q.add_argument("--offset", type=int, default=0)
    q.add_argument("--limit", type=int, default=25)
    q.set_defaults(fn=cmd_obs_search)

    q = sub.add_parser(
        "calibration-status",
        help="check the bundled calibration framework and optimizer dependencies")
    q.set_defaults(fn=cmd_calibration_status)

    q = sub.add_parser(
        "harness-status",
        help="prove the bundled KI harness imports and injects its contract")
    q.add_argument("model", nargs="?", help="KI used for contract generation")
    q.set_defaults(fn=cmd_harness_status)

    q = sub.add_parser(
        "calibrate",
        help="run one KI calibration using GeoForge's bundled optimizer runtime")
    q.add_argument("--model", required=True, help="KI name")
    q.add_argument("--ki-path", required=True, type=Path,
                   help="materialised KI root containing dag.yaml and calibration.yaml")
    q.add_argument("--project", required=True, type=Path,
                   help="chat project that owns calibration inputs and results")
    q.add_argument("--plan-step-id", required=True,
                   help="approved typed calibration step; execution writes a signed receipt")
    q.add_argument("--obs-shapes-json", required=True,
                   help='JSON mapping, e.g. {"Q":"point_time_series"}')
    q.add_argument("--algorithm", choices=sorted((
        "dds", "sceua", "dream", "nsga2", "nsga3", "moead")))
    q.add_argument("--budget", type=int)
    q.add_argument("--seed", type=int, default=0)
    q.add_argument("--expected-case-id")
    q.add_argument("--determining-metric")
    q.set_defaults(fn=cmd_calibrate)
    q = sub.add_parser("_calibration-worker", help=argparse.SUPPRESS)
    q.add_argument("request_path", type=Path)
    q.set_defaults(fn=cmd_calibration_worker)
    q = sub.add_parser("_install-download-worker", help=argparse.SUPPRESS)
    q.add_argument("request_path", type=Path)
    q.set_defaults(fn=cmd_install_download_worker)
    return p


def cmd_verify(args) -> int:
    """Execute the model and report whether it runs. Not bookkeeping — evidence.

    ``preflight_check.py`` stops at "the file is there". This goes on to ask
    whether the machine can actually execute it: right architecture, libraries
    and imports resolvable, language runtime present. A model whose binary is
    in place but whose .NET or libnetcdf is missing reports the specific gap,
    which is the thing a user or an agent can act on.
    """
    import json as _json

    from . import runnable

    cat = _catalog(args)
    kis = [cat.get(args.model)] if args.model else list(cat)
    repo_root = kis[0].root.parent.parent
    harvested = {}
    hp = repo_root / "kiss" / "manifests" / "_harvested_produces.json"
    if hp.exists():
        try:
            harvested = _json.loads(hp.read_text(encoding="utf-8"))
        except ValueError:
            pass

    workroot = Path(args.workdir).expanduser().resolve() if args.workdir else Path.home() / "kiss"
    results = []
    for ki in kis:
        root = install_locations.resolve(workroot, ki.name)
        cfg = None
        if (root / paths.CONFIG_NAME).exists():
            try:
                cfg = paths.KissConfig.load(root)
            except Exception:
                cfg = None
        py = args.python or (cfg.python if cfg else None)
        v = runnable.check(ki, _manifest_for(ki, repo_root), cfg, harvested,
                           timeout=args.timeout, python=py)
        runnable.save(workroot, v)
        results.append(v)
        if not args.json:
            tick = _c("ok", "  runs  ") if v.usable else _c("BLOCK", "  BLOCKED")
            print(f"{tick} {ki.name:<22}{v.summary()[:90]}")

    if args.json:
        print(_json.dumps([v.as_dict() for v in results], indent=2))
    else:
        ok = sum(v.usable for v in results)
        print(f"\n{ok}/{len(results)} run on this machine")
        for v in results:
            if not v.usable and v.missing:
                print(_c("dim", f"  {v.model}: {', '.join(v.missing[:4])}"))
    return 0 if all(v.usable for v in results) else 1


def cmd_papers(args) -> int:
    """Show the model's literature. Metadata only — the PDFs are not ours to ship."""
    import json as _json

    from . import papers as _papers

    cat = _catalog(args)

    if args.check or not args.model:
        reports = [_papers.check(ki) for ki in cat]
        if args.json:
            print(_json.dumps([r.__dict__ for r in reports], indent=2))
            return 0
        bad = [r for r in reports if not r.ok]
        for r in bad:
            print(_c("WARN", "  gap  ") + r.line())
        have = [r for r in reports if r.ok]
        tot = sum(r.count for r in have)
        opn = sum(r.open_access for r in have)
        print(f"\n{len(have)}/{len(reports)} KIs ship literature — {tot} papers, "
              f"{opn} downloadable by anyone, {tot - opn} need your own access")
        return 0 if not bad else 1

    ki = cat.get(args.model)
    lib = _papers.load(ki)
    if lib is None:
        print(f"{ki.name} ships no literature index (docs/{_papers.FILENAME})")
        return 1
    sel = lib.papers
    if args.quantity:
        sel = lib.for_quantity(args.quantity)
    if args.role:
        sel = [p for p in sel if p.role.lower() == args.role.lower()]
    if args.json:
        print(_json.dumps({**lib.as_dict(), "papers": [p.as_dict() for p in sel]},
                          indent=2, ensure_ascii=False))
        return 0

    print(f"{ki.name} — {len(sel)} papers" +
          (f" covering {args.quantity}" if args.quantity else ""))
    for p in sel:
        tag = _c("ok", "open") if p.open_access else _c("dim", "need access")
        print(f"  [{tag}] {p.title[:78]}")
        print(_c("dim", f"          {p.url}  {p.role}"))
    gated = [p for p in sel if not p.open_access]
    if gated:
        print(f"\n{len(gated)} of these are subscription articles. We ship the "
              f"reference, not the PDF.\nDownload the ones you need through your "
              f"library and put them beside the KI —\nan agent reading the full "
              f"text sets a model up far better than one reading a title.")
    return 0


def _rescue_run_options(args) -> None:
    """Recover options that ``argparse.REMAINDER`` swallowed.

    ``kiss run MODEL -w DIR -- cmd`` is the ordering people actually type, but
    REMAINDER captures everything after MODEL, ``-w`` included. Pull the known
    options back out rather than making the user learn option ordering.
    """
    rest = list(args.argv)
    while rest and rest[0] != "--":
        tok = rest[0]
        if tok in ("-w", "--workdir") and len(rest) > 1:
            args.workdir = rest[1]
            del rest[:2]
            continue
        if tok.startswith(("-w=", "--workdir=")):
            args.workdir = tok.split("=", 1)[1]
            del rest[:1]
            continue
        break
    args.argv = rest


def main(argv: list[str] | None = None) -> int:
    import sys as _sys

    if getattr(_sys, "frozen", False) and os.name == "nt":
        # The frozen exe ignores PYTHONIOENCODING, so its pipes use the locale
        # code page (cp936) strictly. Tool output decoded with U+FFFD must not
        # raise UnicodeEncodeError once its receipt is already written. The
        # encoding stays what run_process decodes with; the windowed app has
        # no streams at all (None). stderr is normally backslashreplace, which
        # cannot raise and keeps diagnostics exact, so only a strict one changes.
        for stream in (_sys.stdout, _sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None and (
                    stream is _sys.stdout or getattr(stream, "errors", "") == "strict"):
                reconfigure(errors="replace")

    # Before anything looks for agent CLIs or API keys: a double-clicked app
    # gets launchd's bare PATH, not the user's shell PATH.
    from . import shellenv
    shellenv.adopt()

    if argv is None:
        argv = _sys.argv[1:]
    # A bare launch means "open the app". The first real macOS test was someone
    # double-clicking the binary and getting `error: the following arguments
    # are required: cmd` — correct for a CLI, wrong for a desktop app.
    if not argv:
        argv = ["app"]
    args = build_parser().parse_args(argv)
    if args.cmd == "run":
        _rescue_run_options(args)
        if args.argv and args.argv[0] == "--":
            args.argv = args.argv[1:]
    handler = args.fn
    if (getattr(_sys, "frozen", False) and os.name == "nt"
            and args.cmd not in {"app", "gui"}):
        # Every other command of the windowed exe runs as a child the Desktop
        # or an agent waits on; a crash must exit, not raise a modal dialog.
        handler = _worker_entry(handler)
    try:
        return handler(args)
    except _REPORTED_ERRORS as e:
        print(f"kiss: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
