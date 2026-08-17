"""Composing the opening prompt that makes an agent use a KI *properly*.

A KI is useless if the agent never reads it. The failure is silent: the agent
writes its own script, gets units wrong, and reports success over garbage. This
module encodes the prompt discipline that prevents that.

The rules here are generalised from the HydroCraft deployment, which drives the
same KI packages through Claude / Codex / Gemini / Kimi / Qwen CLIs. Four of
them are load-bearing and none is obvious:

1. **Point at the KI, do not paste it.** SKILL.md files run to hundreds of
   lines; injecting 127 of them is impossible and injecting one wastes the
   budget the agent needs for work. Mandate reading it instead.
2. **Inline only the silent-failure traps.** A wrong unit does not raise — it
   produces plausible numbers that are wrong. Those specific traps go in the
   prompt because by the time the agent would look them up, it has already
   written the conversion.
3. **Triplets before improvisation.** Every KI ships an error/cause/remedy
   catalogue. An agent that debugs from first principles rewrites tools that
   already work.
4. **Headless turns end the process.** A one-shot `claude -p` exits when the
   turn ends, so an agent that backgrounds a long job and stops kills its own
   run — the completion notification arrives to a dead process.
"""

from __future__ import annotations

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

HEADLESS_LONG_JOB_RULE = """[LONG JOBS — POLL INSIDE THIS TURN; THIS SESSION HAS NO 'LATER']
You are running HEADLESS. The moment your turn ends this process EXITS — there
is no next turn, and a background-task completion notification can NEVER reach
you. Ending your turn while a job you launched is still running KILLS the run.

  1. LAUNCH long work DETACHED so a crash cannot take it with you:
       setsid nohup <cmd> > <log> 2>&1 < /dev/null & echo $!    # keep the PID
  2. THEN WAIT IN THE FOREGROUND, in this SAME turn, with a bounded loop:
       until ! kill -0 <PID> 2>/dev/null; do sleep 30; done; tail -20 <log>
     A bare `sleep 60 && tail ...` is BLOCKED by the CLI; an until-loop is not.
  3. If that call times out you GET CONTROL BACK — repeat the loop, do not stop.
"""

EXECUTION_POLICY = """[MANDATORY EXECUTION POLICY]
You MUST run the actual model binary or package. If it fails to build, import
or execute:
  1. Search the KI's diagnostics for the error before doing anything else.
  2. Read the model's own docs/ for expected formats and units.
  3. Report the failure with full output.

You MUST NOT substitute a simplified formula, a regression fit, or a hand-coded
approximation for the real model. That produces scientifically invalid results
and defeats the purpose of this package. If you cannot run the model, say so —
a reported failure is worth more than a fabricated number.
"""


def _rel(p: Path | None, root: Path) -> str:
    if p is None:
        return "(not shipped)"
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


def compose(ki, cfg=None, *, task: str = "", headless: bool = True) -> str:
    """Build the opening prompt for an agent about to operate ``ki``."""
    meta = ki.meta or {}
    root = ki.root
    parts: list[str] = []

    parts.append(f"You are operating **{ki.name}** through its Knowledge "
                 f"Infrastructure (KI) package.\n")

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

    parts.append(
        "[HOW TO USE IT — NOT OPTIONAL]\n"
        f"1. READ {_rel(ki.skill, root)} BEFORE running anything. It carries the unit\n"
        "   conventions, input formats and known traps for this model. The model\n"
        "   will NOT warn you when units are wrong — the run completes and the\n"
        "   results are silently incorrect.\n"
        "2. USE THE KI'S OWN TOOLS. Validated operators live under this package\n"
        "   (tools/, s1_*/, s2_*/ ...). NEVER write a custom script when one\n"
        "   already exists — it has been checked against real cases and yours\n"
        "   has not.\n"
        f"3. WHEN SOMETHING BREAKS, search {_rel(ki.triplets, root)} FIRST:\n"
        "     grep -i '<error keyword>' " + _rel(ki.triplets, root) + "\n"
        "   Only debug from first principles if the catalogue has no match.\n"
        "4. VERIFY with preflight before trusting any output:\n"
        f"     python {_rel(ki.preflight, root)}\n"
    )

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

    parts.append(EXECUTION_POLICY)
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
