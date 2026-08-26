"""Composing the opening prompt that makes an agent use a KI *properly*.

The KI-usage contract itself is **not written here**. It comes from
``ki_tools_common.harness.contract()`` — the neutral, spec-backed harness
(KI_HARNESS_SPEC §2-§4) that every driver shares: the self-improve loop,
GeoForge chat, ata-kdt, and this app. One contract, one place to fix it.

That matters more than it sounds. An earlier version of this module
*paraphrased* the mandatory execution policy from memory. The harness instead
extracts the real block out of the KI's own SKILL.md, so the agent reads the
words the KI actually ships rather than someone's summary of them — and when a
KI tightens its policy, every driver picks it up without being edited.

What this module still owns is the part that is specific to *this* app and
absent from the shared contract:

* where things live on this machine after ``kiss init`` relocated them
* the silent-failure traps — wrong units that do not raise, they just return
  plausible wrong numbers
* the headless long-job rule, because our CLI driver is one-shot
* output formatting, because the reply is rendered in a chat panel

If the harness cannot be imported the prompt is still built, minus the shared
contract, and says so rather than pretending it had it.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Unit and configuration traps that fail *silently* — the model accepts the
#: input, runs to completion, and returns numbers that are wrong. These cannot
#: wait to be looked up, so they are stated up front.
#:
#: Keyed by KI directory name. Only models with a known silent-failure mode
#: appear; the absence of an entry is not a claim of safety, and the prompt
#: says so.
SILENT_TRAPS: dict[str, list[str]] = {
    "GLM": ["Rain must be m/day, NOT mm/day (divide by 1000)."],
    "ParFlow": [
        "K must be m/hr, NOT m/day (divide by 24).",
        "alpha must be 1/m, NOT 1/cm (multiply by 100).",
    ],
    "WRF_Hydro": ["RAINRATE must be mm/s, NOT mm/3hr (divide by 10800)."],
    "SFINCS": ["Rainfall must be mm/hr, NOT mm/3hr (divide by 3)."],
    "MODFLOW6": ["FloPy precision must be 'double' to read .hds output files."],
    "VIC": [
        "Forcing column order is TEMP, PREC, PRESSURE, SWDOWN, LWDOWN, VP, WIND.",
        "VIC has no routing. Gauge discharge ALWAYS requires a routing step "
        "afterwards (VIC-Lohmann or CaMa-Flood) — never compare raw VIC runoff "
        "to a gauge.",
    ],
    "DSSAT": [
        "Keep the working-directory path short. DSSATPRO truncates at roughly "
        "64 characters and the failure surfaces as an unrelated 'IPVAR Line 0' "
        "error.",
    ],
}

#: Traps that belong to a forcing source rather than a model.
FORCING_TRAPS = [
    "NASA POWER: PRECTOTCORR is a mm/day rate — divide by 24 for mm/hr. "
    "SW/LW are MJ/m²/hr — multiply by 277.78 for W/m².",
    "CMFD: prec is kg m-2 s-1 — multiply by 10800 for mm/3hr.",
]

_HEADLESS_LONG_JOB_TEMPLATE = """[LONG JOBS — POLL INSIDE THIS TURN; THIS SESSION HAS NO 'LATER']
You are running HEADLESS. The moment your turn ends this process EXITS — there
is no next turn, and a background-task completion notification can NEVER reach
you. Ending your turn while a job you launched is still running KILLS the run.

  1. LAUNCH long work DETACHED so a crash cannot take it with you:
       {detach} <cmd> > <log> 2>&1 < /dev/null & echo $!    # keep the PID
  2. THEN WAIT IN THE FOREGROUND, in this SAME turn, with a bounded loop:
       until ! kill -0 <PID> 2>/dev/null; do sleep 30; done; tail -20 <log>
     A bare `sleep 60 && tail ...` is BLOCKED by the CLI; an until-loop is not.
  3. If that call times out you GET CONTROL BACK — repeat the loop, do not stop.
"""

#: ``setsid`` is not present on Windows — not in Git Bash either, which is the
#: shell the agent CLIs use there. Emitting it made step 1 of every long run
#: die with "setsid: command not found", and this app exists to run long jobs.
#: ``nohup`` plus ``&`` already survives the parent on Windows.
HEADLESS_LONG_JOB_RULE = _HEADLESS_LONG_JOB_TEMPLATE.format(
    detach="nohup" if os.name == "nt" else "setsid nohup")


def _load_harness_standalone():
    """Load ``ki_harness`` from its file, bypassing its package's ``__init__``.

    ``ki_tools_common/__init__.py`` eagerly imports seventeen submodules —
    netcdf_utils, load_forcing, soil_utils, climate_scenarios — so
    ``from ki_tools_common.harness import contract`` drags in numpy, netCDF4
    and h5py. The desktop build ships none of them, and should not: the harness
    is text generation and imports nothing but the standard library. Frozen,
    that mismatch made every agent prompt fall back to the weaker pointer list
    with the ten obligations missing, announced only in a line nobody reads.

    ki_harness.py already inserts its own directory on sys.path for sibling
    imports, so loading it by path is how it was built to be used.
    """
    import importlib.util
    import sys

    rel = Path("ki_tools_common") / "ki_tools_common" / "harness" / "ki_harness.py"
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    roots.append(Path(__file__).resolve().parents[2])   # a source checkout
    for root in roots:
        f = root / rel
        if not f.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("_kiss_ki_harness", f)
            mod = importlib.util.module_from_spec(spec)
            sys.modules.setdefault("_kiss_ki_harness", mod)
            spec.loader.exec_module(mod)
            if hasattr(mod, "contract"):
                return mod
        except Exception:
            continue
    return None


def _harness_contract(ki, *, execute: bool, python: str | None) -> tuple[str, str | None]:
    """The shared KI-usage contract, or ('', reason) if it is unavailable."""
    import os

    try:
        from ki_tools_common.harness import contract as _contract
        from ki_tools_common.harness import ki_harness as _kh
    except Exception:
        _kh = _load_harness_standalone()
        if _kh is None:
            return "", ("the KI usage contract could not be loaded — "
                        "ki_tools_common/ki_tools_common/harness/ki_harness.py "
                        "is not beside this build")
        _contract = _kh.contract

    # The harness renders every tool command with a project interpreter, and it
    # resolves that ONCE at import time:
    #
    #     PROJECT_PY = os.environ.get("HC_PROJECT_PYTHON", "<authoring machine>")
    #
    # so setting the environment variable here is a no-op — the module is
    # already imported. Left unset it emits the authoring machine's python, and
    # an agent dutifully copies a path that does not exist on this one. Rebind
    # the module attribute for the duration of the call instead.
    prev = getattr(_kh, "PROJECT_PY", None)
    if python:
        _kh.PROJECT_PY = str(python)
    try:
        return _contract(ki.root, execute=execute), None
    except Exception as e:
        # A KI with no SKILL.md raises on an execute contract by design.
        return "", f"{type(e).__name__}: {e}"
    finally:
        if python and prev is not None:
            _kh.PROJECT_PY = prev


def _rel(p: Path | None, root: Path) -> str:
    if p is None:
        return "(not shipped)"
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def compose(ki, cfg=None, *, task: str = "", headless: bool = True,
            execute: bool = True) -> str:
    """Build the opening prompt for an agent about to operate ``ki``."""
    meta = ki.meta or {}
    root = ki.root
    parts: list[str] = []

    parts.append(f"You are GeoForge, an Earth-system modelling agent. You are "
                 f"operating **{ki.name}** through its Knowledge Infrastructure "
                 f"(KI) package.\n")

    # --- 1. identity -------------------------------------------------------
    ident = [
        f"  Model        {meta.get('model_id', ki.name)}",
        f"  Reference    {meta.get('reference') or 'see docs/REFERENCES.md'}",
        f"  Language     {meta.get('language') or '—'}",
        f"  Version      {meta.get('version') or '—'}",
        f"  Resolution   {meta.get('spatial') or '—'}, {meta.get('temporal') or '—'}",
    ]
    parts.append("[MODEL]\n" + "\n".join(ident) + "\n")

    # --- 2. where the knowledge is (pointer, not paste) --------------------
    kifiles = [
        f"  KI root      {root}",
        f"  SKILL.md     {_rel(ki.skill, root)}   <- READ THIS FIRST, ALWAYS",
        f"  dag.yaml     {_rel(ki.dag, root)}   <- machine-readable I/O contract",
        f"  diagnostics  {_rel(ki.triplets, root)}   <- error / cause / remedy",
        f"  preflight    {_rel(ki.preflight, root)}",
        f"  formats      {_rel(ki.format_spec, root)}",
    ]
    parts.append("[KNOWLEDGE INFRASTRUCTURE]\n" + "\n".join(kifiles) + "\n")

    # --- the shared KI-usage contract (not ours; see module docstring) -----
    harness_text, why = _harness_contract(
        ki, execute=execute, python=(cfg.python if cfg is not None else None))
    if harness_text:
        parts.append(harness_text.rstrip() + "\n")
    else:
        parts.append(
            "[KI USAGE CONTRACT UNAVAILABLE]\n"
            f"  {why}\n"
            "  Falling back to the pointers above. READ SKILL.md before running\n"
            "  anything, use the KI's own tools rather than writing your own, and\n"
            "  search diagnostics/ before debugging from first principles.\n")

    # --- 3. silent-failure traps ------------------------------------------
    traps = SILENT_TRAPS.get(ki.name, [])
    trap_lines = [f"  - {t}" for t in traps + FORCING_TRAPS]
    parts.append(
        "[SILENT-FAILURE TRAPS]\n"
        "These do not raise an error. They produce plausible, wrong numbers.\n"
        + "\n".join(trap_lines) + "\n"
        + ("" if traps else
           f"  (No {ki.name}-specific trap is catalogued here. That is NOT a\n"
           f"   guarantee of safety — SKILL.md is the authority, read it.)\n")
    )

    # --- 4. inputs ---------------------------------------------------------
    if ki.forcing_vars:
        parts.append("[REQUIRED FORCING]\n  " + ", ".join(ki.forcing_vars) + "\n")

    # --- 5. relocation -----------------------------------------------------
    if cfg is not None:
        parts.append(
            "[PATHS]\n"
            "This KI was authored on another machine and contains that machine's\n"
            "absolute paths. They are relocated for you via "
            f"'{cfg.relocation}'. Do NOT hand-edit paths inside the KI to local\n"
            "ones. If a path does not resolve, run `kiss doctor "
            f"{ki.name}` and fix\nthe mapping in kiss.toml.\n"
            f"  binaries   {cfg.roles.get('binaries')}\n"
            f"  data       {cfg.roles.get('data')}\n"
            f"  outputs    {cfg.roles.get('outputs')}\n"
        )

    if headless:
        parts.append(HEADLESS_LONG_JOB_RULE)

    parts.append(
        "[OUTPUT]\n"
        "Your output is rendered in a chat panel. Use markdown: **bold** for step\n"
        "titles, `code` for paths and commands, a blank line between steps, and\n"
        "'---' between major stages. Do not run steps together in one paragraph.\n"
        "State plainly what you actually ran and what it actually returned.\n"
    )

    if task:
        parts.append(f"[TASK]\n{task.strip()}\n")

    return "\n".join(parts)


def compose_multi(kis, cfg=None, *, task: str = "", headless: bool = True) -> str:
    """One task, several models: each toggled KI contributes its own contract.

    The single-model prompt stays the default; this exists for the compare/
    ensemble workflow, where the agent must treat every selected model as a
    first-class participant rather than picking a favourite and narrating the
    rest. Contracts are the same per-KI harness text as the single case, so a
    model behaves identically whether toggled alone or with others.
    """
    if len(kis) == 1:
        return compose(kis[0], cfg, task=task, headless=headless)

    names = ", ".join(k.name for k in kis)
    parts = [
        f"You are GeoForge, an Earth-system modelling agent, operating "
        f"{len(kis)} models through their Knowledge Infrastructure packages: {names}.",
        "",
        "[MULTI-MODEL RULES]",
        "- Run EVERY selected model on the task; do not silently drop one.",
        "- Keep each model inside its own KI contract below; never mix tools "
        "across packages.",
        "- Finish with a comparison table of the results, and say plainly if a "
        "model could not run and why.",
        "",
    ]
    for ki in kis:
        parts.append(f"===== {ki.name} " + "=" * max(4, 60 - len(ki.name)))
        contract, why = _harness_contract(
            ki, execute=True, python=(cfg.python if cfg is not None else None))
        parts.append(contract if contract else
                     f"[contract unavailable: {why}] Read {ki.root}/SKILL.md first.")
        parts.append("")
    if headless:
        parts.append(HEADLESS_LONG_JOB_RULE)
    if task:
        parts.append(f"[TASK]\n{task.strip()}")
    return "\n".join(parts)
