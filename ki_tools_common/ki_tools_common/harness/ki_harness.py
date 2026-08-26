#!/usr/bin/env python3
"""ki_harness — ONE contract for how ANY agent uses a model KI (KI_HARNESS_SPEC §2-§4, App. C).

Driver-neutral: chat modes, the self-improve loop, and future drivers all call `contract()` and
inject the returned text. It carries KI USAGE only — no pass bands, no obs selection, no verdicts
(those stay driver-side; spec §0).

    from ki_harness import contract
    text = contract(ki_path, execute=True, target_var="Q")

Env flags (migration, spec App. B/C):
    KI_HARNESS_FULL=1  -> include the RUN-TIME ATTENTION digest (dag caveats, format spec,
                          top triplets, op rules, verified pointers). Default OFF until step 2+.
Failure behaviour (spec §4): SKILL.md missing on an EXECUTE contract -> KiHarnessError (an agent
cannot run a KI without its protocol). Everything else missing -> explicit MISSING line. Never
silently omit.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))  # CLI fallback for sibling imports

PROJECT_PY = os.environ.get("HC_PROJECT_PYTHON",
                            "KISSPATH_PYTHON_ENV/bin/python")
MARKER = "[KI HARNESS v1]"

# ── THE OBLIGATIONS REGISTRY (G3, 2026-08-20) ───────────────────────────────────────────────────
# The ten KI-usage obligations exist on TWO surfaces: this module's contract() (injected into the
# self-improve loop's agents) and the chat exec-prefix in
# hydrocraft-web/backend/services/cli_process_manager.py (baked text). They agreed in 2026-08 only
# because they were written the same week. This registry is the ONE canonical list; the parity
# test (knowledge-dissection-toolkit/test_harness_parity.py) renders/reads BOTH surfaces and fails
# the moment either drops an obligation. Each entry: accepted marker regexes per surface — the
# wording may differ (chat says it generically, the contract per-KI); the OBLIGATION may not.
OBLIGATIONS = {
    "policy_no_surrogates": {
        "contract": r"MANDATORY EXECUTION POLICY|substitut\w+ a toy|simplified approach",
        "chat":     r"NO SHORTCUTS|simplified approach|literature values as results",
    },
    "protocol_in_order": {
        "contract": r"READ and FOLLOW .*SKILL\.md.*IN ORDER",
        "chat":     r"read the SKILL\.md BEFORE running",
    },
    "tools_absolute_path": {
        "contract": r"ABSOLUTE PATH.*project\s+python|do NOT search, do NOT disk-glob",
        "chat":     r"Resolve the real path from the DB|harness\\.ki_path '<Model>'",
    },
    "know_the_outputs": {
        "contract": r"WHAT THIS MODEL PRODUCES",
        "chat":     r"machine-file digest.*read it in full|KI DIGEST . server-rendered.*READ BEFORE RUNNING",
    },
    "verify_units_from_files": {
        "contract": r"FILE'S OWN attributes|never from documentation",
        "chat":     r"FILE'S OWN metadata|files on disk are ground truth",
    },
    "preflight_first": {
        "contract": r"preflight_check\.py.*OBEY",
        "chat":     r"preflight",
    },
    "failure_ladder": {
        "contract": r"ON FAILURE.*triplets|symptom .?\u2192.? diagnosis|triplets\.yaml for the error",
        "chat":     r"grep -i '<error_keyword>'.*triplets",
    },
    "never_weaken": {
        "contract": r"NEVER weaken a tool or gate",
        "chat":     r"DO NOT EDIT KI TOOLS.*STOP and report",
    },
    "not_your_own_judge": {
        "contract": r"do not declare your own .*verdict|NOT YOUR OWN JUDGE",
        "chat":     r"NOT YOUR OWN JUDGE",
    },
    "evidence_series_csv": {
        "contract": r"simulated time series to CSV|reproducib",
        "chat":     r"BEFORE computing any metric.*paired simulated \+ observed series.*CSV",
    },
}

_MAX_TOOLS_LISTED = 24


class KiHarnessError(Exception):
    """A KI cannot be used the way the caller asked. Loud, never downgraded."""


def _policy_excerpt(skill_text: str, max_lines: int = 12) -> str | None:
    """The MANDATORY EXECUTION POLICY block from SKILL.md (the no-surrogate guardrail)."""
    m = re.search(r"MANDATORY EXECUTION POLICY.*?(?:\n\s*\n|\Z)", skill_text[:12000], re.S)
    if not m:
        return None
    lines = m.group(0).strip().splitlines()
    return "\n".join(lines[:max_lines])


def _tools(ki: Path) -> list[str]:
    d = ki / "tools"
    if not d.is_dir():
        return []
    out = [str(p) for p in sorted(d.rglob("*.py"))
           if "__pycache__" not in p.parts and ".bak" not in p.name]
    return out


def tool_command(ki_path, rel_tool: str) -> str:
    """`<project python> <absolute tool path>`. Rejects absolute-outside-KI, missing, non-tools."""
    ki = Path(ki_path)
    p = (ki / rel_tool) if not os.path.isabs(rel_tool) else Path(rel_tool)
    p = p.resolve()
    if ki.resolve() not in p.parents:
        raise KiHarnessError(f"tool {rel_tool!r} is outside the KI {ki}")
    if not p.is_file():
        raise KiHarnessError(f"tool does not exist: {p}")
    return f"{PROJECT_PY} {p}"


def manifest(ki_path) -> dict:
    """Machine view of the KI: artifact presence, absolute tool paths, outputs digest source.
    Used by graders, auditors and conformance tests — never guesses."""
    ki = Path(ki_path)
    arts = {
        "SKILL.md": (ki / "SKILL.md").is_file(),
        "dag.yaml": (ki / "dag.yaml").is_file(),
        "diagnostics/triplets.yaml": (ki / "diagnostics" / "triplets.yaml").is_file(),
        "docs/format_spec.yaml": (ki / "docs" / "format_spec.yaml").is_file(),
        "docs/validation_convention.yaml": (ki / "docs" / "validation_convention.yaml").is_file(),
        "preflight_check.py": (ki / "preflight_check.py").is_file(),
        "knowledge_infrastructure.yaml": (ki / "knowledge_infrastructure.yaml").is_file(),
    }
    # OUTPUTS (G3 parity fix, 2026-08-20): the spec promised outputs (name/unit/rank/obs_shapes)
    # in the manifest; the built module never implemented it, so contract() had nothing to render.
    outputs = []
    dagf = ki / "dag.yaml"
    if dagf.is_file():
        try:
            import yaml as _y
            _d = _y.safe_load(dagf.read_text(errors="ignore")) or {}
            for o in (_d.get("outputs") or []):
                if not isinstance(o, dict):
                    continue
                shp = []
                for c in ((o.get("observability") or {}).get("comparable_obs_shapes") or []):
                    if isinstance(c, dict) and c.get("obs_shape"):
                        shp.append(str(c["obs_shape"]))
                    elif isinstance(c, str):
                        shp.append(c)
                outputs.append({"name": o.get("var") or o.get("name"), "unit": o.get("unit"),
                                "rank": o.get("validation_rank"), "obs_shapes": shp})
            outputs.sort(key=lambda x: (int(x["rank"]) if str(x.get("rank") or "").isdigit() else 99))
        except Exception:
            outputs = []
    return {"ki_path": str(ki), "artifacts": arts, "tools": _tools(ki),
            "outputs": outputs,
            "missing": sorted(k for k, v in arts.items() if not v)}


def run_preflight(ki_path, timeout: int = 300) -> dict:
    """Execute preflight_check.py with the project python; parse its JSON report if it emits one.
    Raises KiHarnessError when the script is absent (readiness unknowable)."""
    ki = Path(ki_path)
    pf = ki / "preflight_check.py"
    if not pf.is_file():
        raise KiHarnessError(f"no preflight_check.py at {ki}")
    r = subprocess.run([PROJECT_PY, str(pf)], capture_output=True, text=True,
                       timeout=timeout, cwd=str(ki))
    out = (r.stdout or "") + (r.stderr or "")
    m = re.search(r"\{.*\}", out, re.S)
    report = None
    if m:
        try:
            report = json.loads(m.group(0))
        except Exception:
            report = None
    return {"returncode": r.returncode, "report": report, "raw_tail": out[-800:]}


def assert_injected(prompt_text: str) -> None:
    """Conformance hook: raise unless the harness marker is present."""
    if MARKER not in (prompt_text or ""):
        raise KiHarnessError(f"prompt does not carry {MARKER} — spawn site bypasses the harness")


def contract(ki_path, *, execute: bool = True, target_var: str | None = None,
             full: bool | None = None, attention_budget: int = 4500,
             mode: str | None = None) -> str:
    """The injectable KI-usage contract. See module docstring.

    THREE WORDINGS (G1 round 2, codex): an agent is a runner, a reader, or an editor — and the
    contract must say which, or it mis-instructs:
      mode="execute" (default; = execute=True)  runs the model: full run discipline.
      mode="inspect" (= execute=False)          reads to plan/diagnose: non-mutating probes
                                                 (--help, preflight, grep) are ALLOWED; never run
                                                 the model pipeline, never mutate files.
      mode="edit"                                edits KI files but must NOT run the model
                                                 (apply-only fix agents: the reviewer gate comes
                                                 between their edit and any rerun).
    full=None -> read env KI_HARNESS_FULL (default off) for the RUN-TIME ATTENTION digest.
    """
    if mode is None:
        mode = "execute" if execute else "inspect"
    if mode not in ("execute", "inspect", "edit"):
        raise KiHarnessError(f"unknown contract mode {mode!r}")
    execute = (mode == "execute")
    ki = Path(ki_path)
    if not ki.is_dir():
        raise KiHarnessError(f"KI dir does not exist: {ki}")
    if full is None:
        full = os.environ.get("KI_HARNESS_FULL", "0").strip() == "1"

    skill = ki / "SKILL.md"
    missing: list[str] = []
    lines: list[str] = [f"{MARKER} Walk this Knowledge Infrastructure. KI dir: {ki}"]

    # POLICY + PROTOCOL --------------------------------------------------------------------------
    if skill.is_file():
        txt = skill.read_text(errors="ignore")
        pol = _policy_excerpt(txt)
        if pol:
            lines.append(pol)
        else:
            missing.append("SKILL.md carries no MANDATORY EXECUTION POLICY block")
        lines.append(f"1. PROTOCOL — READ and FOLLOW {skill} IN ORDER; it defines what 'done' "
                     f"means. Do not improvise a pipeline that the protocol already defines.")
    else:
        if execute:
            raise KiHarnessError(f"SKILL.md missing at {ki} — an agent cannot RUN a KI without "
                                 f"its protocol (thin/unbuilt KI); refuse rather than improvise")
        missing.append("SKILL.md MISSING — no protocol; nothing here is runnable")

    # TOOLS --------------------------------------------------------------------------------------
    tools = _tools(ki)
    if tools:
        if execute:
            lines.append("2. TOOLS (validated) — run each by its ABSOLUTE PATH with the project "
                         "python. They are NOT on PATH; do NOT search, do NOT disk-glob, do NOT "
                         "read them and re-implement their logic inline (they encode unit "
                         "conversions and silent-error traps your inline code WILL miss):")
            shown = tools[:_MAX_TOOLS_LISTED]
            lines += [f"     {PROJECT_PY} {t}" for t in shown]
            if len(tools) > len(shown):
                lines.append(f"     … +{len(tools) - len(shown)} more under {ki / 'tools'} "
                             f"(same invocation pattern)")
        elif mode == "inspect":
            lines.append(f"2. TOOLS — {len(tools)} validated tools under {ki / 'tools'}. You are "
                         f"in INSPECT mode: read them to plan/diagnose. Non-mutating probes ARE "
                         f"allowed (--help, preflight_check.py, grep/read); do NOT run the model "
                         f"pipeline and do NOT mutate any file.")
        else:   # edit
            lines.append(f"2. TOOLS — {len(tools)} validated tools under {ki / 'tools'}. You are "
                         f"in EDIT mode: you may modify KI files per your task, but do NOT run "
                         f"the model pipeline (a reviewer gate sits between your edit and any "
                         f"rerun), and NEVER weaken a tool or gate to make something pass.")
    else:
        missing.append("tools/ has no python tools — nothing validated to execute")

    # RUN-TIME ATTENTION (gated) -----------------------------------------------------------------
    if full:
        try:
            try:
                from .ki_attention import digest as _att_digest
            except ImportError:
                from ki_attention import digest as _att_digest
            model_hint = ki.parent.name if ki.name == "knowledge_infrastructure" else ki.name
            lines.append(_att_digest(model_hint, target_var, attention_budget))
        except Exception as e:
            missing.append(f"RUN-TIME ATTENTION digest unavailable ({type(e).__name__}: "
                           f"{str(e)[:90]}) — open dag.yaml / docs/format_spec.yaml yourself")
    else:
        man = manifest(ki)
        missing.extend(f"{a} absent" for a in man["missing"] if a != "SKILL.md")
        # G3 parity fix (2026-08-20): spec §5 — WHAT THIS MODEL PRODUCES — is an obligation, not a
        # KI_HARNESS_FULL luxury. The parity test caught this on its first run: with the flag off
        # (the default) the contract never told the agent what the model outputs. A compact digest
        # always renders; the full attention digest remains the flag-gated upgrade.
        outs = (man.get("outputs") or [])[:5]
        if outs:
            lines.append("2b. WHAT THIS MODEL PRODUCES (from dag.yaml; rank 1 = the headline "
                         "variable this model is judged by):")
            for o in outs:
                lines.append(f"     rank {o.get('rank','?')}: {o.get('name')} [{o.get('unit','?')}]"
                             + (f" — obs shapes: {', '.join(o.get('obs_shapes', [])[:2])}"
                                if o.get("obs_shapes") else ""))
            lines.append(f"     full detail: {ki / 'dag.yaml'} — or render the attention digest: "
                         f"{PROJECT_PY} -m ki_tools_common.harness.ki_attention '<model>'")
        else:
            missing.append("dag.yaml has no readable outputs — the agent cannot know what this "
                           "model produces")

    # RECOVERED TESTED KEYS (KI_PROMPT_KEYS.md, owner-approved 2026-08-18) -----------------------
    if execute:
        pf = ki / "preflight_check.py"
        lines.append("3. BEFORE ANY INPUT PREP —")
        lines.append("   a. Check SKILL.md's unit-conversion table FIRST. The model will NOT warn "
                     "you about wrong units — it runs silently and produces wrong results.")
        lines.append("   b. Verify every forcing/obs file's units from the FILE'S OWN attributes "
                     "(e.g. `xr.open_dataset(f)[v].attrs`), never from documentation.")
        if pf.is_file():
            lines.append(f"   c. Run `{PROJECT_PY} {pf}` and OBEY its report before executing.")
        lines.append("4. WHILE RUNNING — after each stage, confirm the output exists and values "
                     "are plausible BEFORE the next stage. Save the simulated time series to CSV "
                     "before computing any metric. NEVER report literature values as results — "
                     "run the model.")

    # FAILURE LADDER + JUDGE ---------------------------------------------------------------------
    trip = ki / "diagnostics" / "triplets.yaml"
    lines.append("5. ON FAILURE — strict order: (1) grep "
                 f"{trip if trip.is_file() else 'diagnostics/triplets.*'} for the error "
                 "(symptom → diagnosis → remedy; if a triplet matches, apply it and STOP "
                 "debugging); (2) SKILL.md troubleshooting/units section; (3) a prior successful "
                 "run's outputs; (4) only THEN manual debugging. NEVER weaken a tool or gate to "
                 "make it pass.")
    if execute:
        lines.append("6. NOT YOUR OWN JUDGE — you PRODUCE the run and report exactly what it "
                     "produced; do not declare your own metric the verdict.")

    if missing:
        lines.append("MISSING / LIMITS")
        lines += [f"- {m}" for m in missing]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("model_or_kipath")
    ap.add_argument("--var", default=None)
    ap.add_argument("--plan", action="store_true", help="inspect-only wording")
    ap.add_argument("--full", action="store_true")
    a = ap.parse_args()
    kp = a.model_or_kipath
    if not os.path.isdir(kp):
        from ki_path import resolve
        kp = resolve(kp)["ki_path"]
    print(contract(kp, execute=not a.plan, target_var=a.var, full=a.full or None))
