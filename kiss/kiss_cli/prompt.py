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

If one KI is incomplete, the prompt can still explain that KI-specific gap.
If the shared harness itself cannot be imported, prompt construction fails
loudly: silently weakening every agent is not an acceptable release fallback.
"""

from __future__ import annotations

import os
import shutil
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

def _long_job_detach() -> str:
    # Windows: an MSYS2/Cygwin setsid.exe on the Desktop's PATH is not the
    # agent's Git Bash (foreign msys runtime), and cannot detach a Windows
    # process tree anyway; plain nohup is the verified rule there.
    return "nohup" if os.name == "nt" or not shutil.which("setsid") else "setsid nohup"


#: ``setsid`` is not present on Windows (not in Git Bash either) or macOS.
#: Emitting it made step 1 of every long run die with "setsid: command not
#: found", and this app exists to run long jobs. ``nohup`` plus ``&`` already
#: survives the parent; Stop reaches receipted runs through their own marker.
HEADLESS_LONG_JOB_RULE = _HEADLESS_LONG_JOB_TEMPLATE.format(detach=_long_job_detach())


def _harness_contract(ki, *, execute: bool, python: str | None) -> tuple[str, str | None]:
    """The shared KI-usage contract, or ('', reason) if it is unavailable."""
    from . import harness_runtime

    try:
        text, receipt = harness_runtime.verified_contract(
            ki.root, execute=execute, python=python)
        return text + "\n" + harness_runtime.receipt_line(receipt), None
    except harness_runtime.KiContractUnavailable as e:
        # The shared harness itself loaded and passed, but this individual KI
        # is incomplete (for example it has no SKILL.md). HarnessUnavailable
        # is deliberately not caught: a broken bundled runtime must stop the
        # turn rather than silently weakening every provider.
        return "", f"{type(e).__name__}: {e}"


def _rel(p: Path | None, root: Path) -> str:
    if p is None:
        return "(not shipped)"
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def _reference_case_guidance(root: Path) -> str:
    """Point to shipped cases without choosing one or granting execution."""
    root = Path(root).resolve()
    case_root = root / "test_cases"
    if not case_root.is_dir() or not case_root.resolve().is_relative_to(root):
        return ""
    cases = []
    for case in sorted(case_root.iterdir()):
        if not case.is_dir() or not case.resolve().is_relative_to(root):
            continue
        docs = [case / name for name in ("README.md", "manifest.json", "expected.json")]
        docs = [path for path in docs if path.is_file() and path.resolve().is_relative_to(root)]
        if docs:
            cases.append("  " + ", ".join(path.relative_to(root).as_posix() for path in docs))
    if not cases:
        return ""
    return (
        "[SHIPPED REFERENCE CASES]\n" + "\n".join(cases) + "\n"
        "If the user requests a shipped case replay, read these files and the linked runner. "
        "The case supplies its own run settings and inputs; inspect them before asking for "
        "new study choices or data. Retain the input bytes and expected checks. Plan the replay "
        "through the normal approval/tool interface; this list grants no execution permission. "
        "Do not substitute an example for a requested new-site study.\n"
    )


def compose(ki, cfg=None, *, task: str = "", headless: bool = True,
            execute: bool = True, strict: bool = False) -> str:
    """Build the opening prompt for an agent about to operate ``ki``.

    ``strict`` (flow-managed chats): an execute-mode contract that cannot be built raises
    instead of falling back to pointers."""
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
    reference_cases = _reference_case_guidance(root)
    if reference_cases:
        parts.append(reference_cases)

    # --- the shared KI-usage contract (not ours; see module docstring) -----
    harness_text, why = _harness_contract(
        ki, execute=execute, python=(cfg.python if cfg is not None else None))
    if harness_text:
        parts.append(harness_text.rstrip() + "\n")
    elif execute and strict:
        # plan v3 B2: under the flow, a KI with no protocol is never given the run
        # wording — the turn is refused instead of silently weakened
        from .harness_runtime import KiContractUnavailable
        raise KiContractUnavailable(f"{ki.name}: {why}")
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

    if headless and execute:
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


def compose_multi(kis, cfg=None, *, task: str = "", headless: bool = True,
                  execute: bool = True, strict: bool = False) -> str:
    """One task, several KIs: each selected package contributes its own contract.

    The single-model prompt stays the default; this exists for the compare/
    ensemble workflow, where the agent must treat every selected model as a
    first-class participant rather than picking a favourite and narrating the
    rest. Contracts are the same per-KI harness text as the single case, so a
    model behaves identically whether toggled alone or with others.
    Explicit data-reader workflows contribute preparation roles, not additional
    model runs or model-comparison obligations.

    ``execute`` selects the contract wording (plan v3 B2): False = the planning
    turn's inspect contract (read, plan, never run); True = the run contract.
    """
    if len(kis) == 1:
        return compose(kis[0], cfg, task=task, headless=headless, execute=execute, strict=strict)

    names = ", ".join(k.name for k in kis)
    parts = [
        f"You are GeoForge, an Earth-system modelling agent, operating "
        f"{len(kis)} models through their Knowledge Infrastructure packages: {names}.",
        "",
        "[MULTI-MODEL RULES]",
        ("- Run EVERY selected model on the task; do not silently drop one." if execute else
         "- Plan for EVERY selected model; do not silently drop one. Do not run any model in this turn."),
        "- Keep each model inside its own KI contract below; never mix tools "
        "across packages.",
        ("- Finish with a comparison table of the results, and say plainly if a model could not run and why."
         if execute else "- Explain the planned roles, inputs and missing requirements of each model; "
         "do not present planned outputs as simulation results."),
        "",
    ]
    readers = [ki for ki in kis if (getattr(ki, "meta", {}) or {}).get("package_kind") == "task_workflow"
               and (getattr(ki, "meta", {}) or {}).get("package_role") == "data_reader"]
    if readers:
        reader_names = {ki.name for ki in readers}
        models = [ki.name for ki in kis if ki.name not in reader_names]
        parts = [
            f"You are GeoForge, using {len(kis)} Knowledge Infrastructure packages: {names}.",
            "", "[MODEL AND DATA-READER ROLES]",
            f"- Scientific models: {', '.join(models) or 'none'}. Data readers: {', '.join(ki.name for ki in readers)}.",
            ("- Execute each KI's role in the approved current phase; do not silently drop a selected role."
             if execute else "- Plan each selected KI's role; no reader or model execution in this planning turn."),
            "- Data readers extract and check acquired observations in check/prepare steps. Their completion "
            "is data preparation, not model execution or scientific validation.",
            "- Keep each tool attributed to its own KI. Selecting a reader with a model does not create "
            "a model-coupling requirement or a model-versus-reader comparison.",
            "- Use only acquired data and explicit project bindings; resolve missing source, station, period "
            "and output paths before executing a reader. Never invent missing weather or site inputs.",
            ("- Report reader preparation and model outcomes separately, including any remaining work."
             if execute else "- Explain planned model and reader inputs, roles and missing requirements; "
             "planned outputs are not results."), "",
        ]
    for ki in kis:
        parts.append(f"===== {ki.name} " + "=" * max(4, 60 - len(ki.name)))
        contract, why = _harness_contract(
            ki, execute=execute, python=(cfg.python if cfg is not None else None))
        if not contract and execute and strict:
            from .harness_runtime import KiContractUnavailable
            raise KiContractUnavailable(f"{ki.name}: {why}")
        parts.append(contract if contract else
                     f"[contract unavailable: {why}] Read {ki.root}/SKILL.md first.")
        reference_cases = _reference_case_guidance(ki.root)
        if reference_cases:
            parts.append(reference_cases)
        parts.append("")
    if headless and execute:
        parts.append(HEADLESS_LONG_JOB_RULE)
    if task:
        parts.append(f"[TASK]\n{task.strip()}")
    return "\n".join(parts)
