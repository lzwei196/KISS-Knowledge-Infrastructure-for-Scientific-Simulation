"""``kiss`` — the command line entry point.

    kiss list                 what is available
    kiss info VIC             what one KI needs
    kiss doctor [VIC]         what would stop this working elsewhere
    kiss init VIC             set it up here, hand the rest to an agent
    kiss run VIC -- ./x.py    run something with the KI's paths resolved
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import doctor, gui, handoff, install, paths, port, recipe
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
    root = Path(args.workdir or Path.home() / "kiss" / ki.name.lower()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    cfg_file = root / paths.CONFIG_NAME
    if cfg_file.exists():
        cfg = paths.KissConfig.load(root)
        print(_c("dim", f"using existing {cfg_file}"))
    else:
        cfg = paths.KissConfig.default(root)
        cfg.python = args.python or sys.executable
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
    s, binary = install.acquire(man, prefix, cfg.python)
    result.add(s)
    result.binary = binary
    for note in install.place_where_the_ki_expects(ki, binary, cfg):
        print(_c("dim", f"        {note}"))
    print(f"  [6/8] acquire ......... {_c('ok' if s.ok else 'BLOCK', s.mark)}")
    if not s.ok:
        print(_c("dim", "        " + s.detail.strip().splitlines()[0][:100]))

    if man.depends_on:
        print(_c("dim", f"        couples with: {', '.join(man.depends_on)}"))

    s = result.add(install.check_data(man, cfg))
    print(f"  [7/8] data ............ {_c('ok' if s.ok else 'WARN', s.mark)}")

    s = result.add(install.run_preflight(ki, cfg.python, cfg))
    print(f"  [8/8] preflight ....... {_c('ok' if s.ok else 'BLOCK', s.mark)}")

    written = handoff.write(ki, result, man, cfg, root)
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
                     workroot=args.workroot, host=args.host)


def cmd_recipe(args) -> int:
    import json as _json

    cat = _catalog(args)
    ki = cat.get(args.model)
    repo_root = ki.root.parent.parent
    harvested = {}
    hp = repo_root / "kiss" / "manifests" / "_harvested_produces.json"
    if hp.exists():
        harvested = _json.loads(hp.read_text())
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
            harvested = _json.loads(hp.read_text())
        except ValueError:
            pass

    workroot = Path(args.workdir).expanduser().resolve() if args.workdir else Path.home() / "kiss"
    results = []
    for ki in kis:
        root = workroot / ki.name.lower()
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
    try:
        return args.fn(args)
    except (KeyError, FileNotFoundError, NotADirectoryError, ValueError) as e:
        print(f"kiss: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
