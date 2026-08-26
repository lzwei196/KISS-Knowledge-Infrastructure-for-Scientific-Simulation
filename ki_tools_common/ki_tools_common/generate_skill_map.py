#!/usr/bin/env python3
"""generate_skill_map.py — project the KI MAP section into SKILL.md (2026-08-17).

WHY
---
SKILL.md is the entry point: the first (often only) file an agent reads before running the
model. The KI has grown components that FILE 1 predates — measured across the 271 complete
process-model KIs, SKILL.md mentions dag.yaml in 9%, validation_convention in 3%, the papers
index in 1%. The components that define what the model IS and how it is JUDGED are invisible
from the front door.

The map is DERIVED data — which components exist is a fact about the directory — so it is
PROJECTED by this script, never hand-written (hand-written inventories are how manifests went
stale). Idempotent: the section lives between markers and is replaced wholesale on re-run.

    python3 generate_skill_map.py --ki_dir <KI>          # write/refresh the map
    python3 generate_skill_map.py --ki_dir <KI> --check  # exit 1 if stale/absent, write nothing

Placement: immediately after the MANDATORY EXECUTION POLICY guardrail block (the map is the
second thing an agent should see), or at the top if no guardrail exists yet.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

BEGIN = "<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->"
END = "<!-- KI-MAP:END -->"


def _count_triplets(ki: Path):
    import yaml
    f = ki / "diagnostics" / "triplets.yaml"
    if not f.is_file():
        return None
    try:
        d = yaml.safe_load(f.read_text())
    except Exception:
        return "unparseable"
    if isinstance(d, list):
        return len(d)
    if isinstance(d, dict):
        for k in ("triplets", "diagnostic_triplets"):
            if isinstance(d.get(k), list):
                return len(d[k])
    return "unrecognised"


def _count_papers(ki: Path):
    import json
    f = ki / "docs" / "gathered_papers.json"
    if not f.is_file():
        return None
    try:
        return len(json.load(open(f)))
    except Exception:
        return "unparseable"


def build_map(ki: Path) -> str:
    """The rendered section. Rows appear ONLY for components that exist — the map never claims
    what the directory does not hold, and never invents a row for a missing file."""
    rows = []

    def row(when, path, purpose):
        rows.append((when, path, purpose))

    if (ki / "preflight_check.py").is_file():
        row("FIRST, always", "`preflight_check.py`",
            "run it (`python preflight_check.py`): proves env/binary/data are usable and emits a "
            "machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a "
            "healthy environment.")
    n_tools = len([p for p in (ki / "tools").rglob("*.py")
                   if "__pycache__" not in p.parts]) if (ki / "tools").is_dir() else 0
    if n_tools:
        row("to run the pipeline stages", f"`tools/` ({n_tools} tools)",
            "the executable pipeline. Read each tool's argparse (`--help`) before composing a "
            "command; SKILL.md's stage table says which tool serves which stage.")
    stage_docs = sorted((ki / "docs").glob("s[0-9]*_*.md")) if (ki / "docs").is_dir() else []
    if stage_docs:
        row("before running a stage", f"`docs/s*_*.md` ({len(stage_docs)} stage docs)",
            "per-stage procedure, verification and traps — the how-to that SKILL.md's overview "
            "compresses.")
    nt = _count_triplets(ki)
    if nt is not None:
        row("on ANY error, before debugging", f"`diagnostics/triplets.yaml` ({nt} entries)",
            "symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; "
            "the answer usually exists. Never renumber or rewrite entries.")
    if (ki / "dag.yaml").is_file():
        row("to know what an output IS", "`dag.yaml`",
            "the model's identity: every output's medium, units, `validation_rank` (1 = the "
            "headline variable) and observability. Scoring and obs-binding read THIS — when "
            "asked 'what does this model predict', the dag is the answer, not a guess.")
    if (ki / "docs" / "format_spec.yaml").is_file():
        row("when building inputs / parsing outputs", "`docs/format_spec.yaml`",
            "exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with "
            "`ki_tools_common/generate_format_spec.py` after changing either — never hand-edit.")
    if (ki / "docs" / "validation_convention.yaml").is_file():
        row("to judge a run's skill", "`docs/validation_convention.yaml`",
            "how this model's field judges it validated: per-`dag_variable` metrics, directions "
            "and CITED pass-bands. A run is graded against these, not against intuition.")
    np_ = _count_papers(ki)
    if np_ is not None:
        row("for claims and thresholds", f"`docs/gathered_papers.json` ({np_} papers)"
            + (" + `docs/papers_index.md`" if (ki / "docs" / "papers_index.md").is_file() else ""),
            "the literature this KI is judged by; each entry's `text_path` is fetched full text "
            "in the central paper cache. `role: benchmark` marks the model's own skill paper.")
    if (ki / "knowledge_infrastructure.yaml").is_file():
        # kind-aware wording (codex): the dag-derived projector contract is a PROCESS-MODEL fact.
        # For libs/data KIs/couplers there is no per-kind projector yet — do not imply one.
        if (ki / "dag.yaml").is_file():
            row("for a machine-readable summary", "`knowledge_infrastructure.yaml`",
                "the manifest (package, pipeline, validation tier, counts) — projected by "
                "`ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, "
                "never hand-edit.")
        else:
            row("for a machine-readable summary", "`knowledge_infrastructure.yaml`",
                "the manifest (package, pipeline, counts). No per-kind projector exists yet for "
                "this KI kind — keep it consistent with the KI's contents when editing.")
    if (ki / ".kdt_evolution.jsonl").is_file():
        row("what past runs learned", "`.kdt_evolution.jsonl`",
            "append-only memory of previous runs and fixes on this KI.")

    lines = [BEGIN,
             "## KI map — what to read, and when",
             "",
             "| when you need | read | why |",
             "|---|---|---|"]
    for when, path, purpose in rows:
        lines.append(f"| {when} | {path} | {purpose} |")
    lines.append("")
    lines.append(f"*Projected {dt.date.today().isoformat()} from the KI's actual contents — "
                 f"{len(rows)} components present. Refresh: "
                 f"`python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*")
    lines.append(END)
    return "\n".join(lines)


def _marker_state(text: str):
    """(#BEGIN, #END, ordered_ok). Refuse anything but the two clean states (codex #2):
    a one-sided, duplicated or reversed marker pair means a previous splice went wrong, and
    writing into that file would duplicate sections or eat body text."""
    nb, ne = text.count(BEGIN), text.count(END)
    ordered = nb == ne == 1 and text.index(BEGIN) < text.index(END)
    return nb, ne, ordered


def _strip_date(t: str) -> str:
    import re
    return re.sub(r"\*Projected \d{4}-\d{2}-\d{2}", "*Projected", t)


def _splice(skill_text: str, section: str) -> str:
    nb, ne, ordered = _marker_state(skill_text)
    if nb == 1 and ne == 1 and ordered:
        pre = skill_text[:skill_text.index(BEGIN)]
        post = skill_text[skill_text.index(END) + len(END):]
        # codex #1: if the section differs ONLY by its date stamp, keep the file as it is —
        # otherwise every daily run rewrites 450 files to change a date.
        have = skill_text[skill_text.index(BEGIN):skill_text.index(END) + len(END)]
        if _strip_date(have) == _strip_date(section):
            return skill_text
        return pre + section + post
    # insert after the guardrail: the first non-blank blockquote run that CONTAINS the mandatory
    # header (codex #4 — a leading BOM/blank lines must not push the map above the guardrail).
    lines = skill_text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    # kimi: a YAML frontmatter block (---\n ... \n---) may precede the guardrail. Skip it, or
    # the map would be prepended ABOVE it — breaking the frontmatter and burying the guardrail.
    if i < len(lines) and lines[i].strip() == "---":
        for k in range(i + 1, len(lines)):
            if lines[k].strip() == "---":
                i = k + 1
                while i < len(lines) and not lines[i].strip():
                    i += 1
                break
    j = i
    if j < len(lines) and lines[j].lstrip("\ufeff").lstrip().startswith(">"):
        while j < len(lines) and (lines[j].lstrip().startswith(">") or not lines[j].strip()):
            j += 1
        block = "\n".join(lines[i:j])
        if "MANDATORY EXECUTION POLICY" in block:
            return "\n".join(lines[:j]) + "\n" + section + "\n\n" + "\n".join(lines[j:])
    # no guardrail block found — insert after any frontmatter (position i), else at the top
    return "\n".join(lines[:i]) + ("\n" if i else "") + section + "\n\n" + "\n".join(lines[i:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ki_dir", required=True)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the map is absent or stale; write nothing")
    a = ap.parse_args()
    ki = Path(a.ki_dir)
    skill = ki / "SKILL.md"
    if not skill.is_file():
        print(f"REFUSED: {skill} does not exist — the map is spliced into SKILL.md, "
              f"it does not create one")
        sys.exit(2)

    # codex #3: preserve the file's own newline convention — read bytes, splice on LF, write back
    # in the original style, or a mechanical backfill turns into whole-file CRLF churn.
    raw = skill.read_bytes()
    crlf = raw.count(b"\r\n") > 0 and raw.count(b"\r\n") >= raw.count(b"\n") // 2
    try:
        # kimi: errors="replace" would silently turn legacy-encoding bytes into U+FFFD and then
        # WRITE THEM BACK — corrupting the file. A SKILL.md we cannot decode is a SKILL.md we
        # refuse to edit.
        current = raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as _ue:
        print(f"REFUSED: {skill} is not valid UTF-8 ({_ue}) — fix the encoding by hand; "
              f"splicing would corrupt it")
        sys.exit(2)

    nb, ne, ordered = _marker_state(current)
    if (nb or ne) and not (nb == 1 and ne == 1 and ordered):
        print(f"REFUSED: malformed KI-MAP markers (BEGIN x{nb}, END x{ne}"
              f"{', reversed' if nb == 1 and ne == 1 else ''}) — repair the file by hand; "
              f"writing into it would duplicate sections or eat body text")
        sys.exit(2)

    section = build_map(ki)

    if a.check:
        if BEGIN not in current:
            print("STALE: no KI map section"); sys.exit(1)
        have = current[current.index(BEGIN):current.index(END) + len(END)]
        if _strip_date(have) != _strip_date(section):
            print("STALE: map does not match the KI's current contents"); sys.exit(1)
        print("OK"); sys.exit(0)

    new = _splice(current, section)
    if new != current:
        while True:
            b = skill.with_suffix(f".md.bak.{dt.datetime.now():%Y%m%dT%H%M%S_%f}")
            try:
                b.touch(exist_ok=False); b.write_bytes(raw); break
            except FileExistsError:
                continue
        out = new.replace("\n", "\r\n") if crlf else new
        skill.write_bytes(out.encode("utf-8"))
        print(f"KI map written into {skill} ({section.count('| ')} rows)")
    else:
        print("KI map already current")


if __name__ == "__main__":
    main()
