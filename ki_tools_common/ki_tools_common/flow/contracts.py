"""flow.contracts — the prompt text for each turn of the flow.

Plan v3 map A5. The per-KI contract itself is the harness's (`contract()`,
harness/ki_harness.py L188-330) — imported, never re-implemented.

What is adopted from chat and where it came from:
  * planning wording        prompt_composer.py `_MODEL_PLANNING` L159-177 and
                            `_ATA_PLANNING` L179-196 (picks fixed, justify, inputs
                            auto vs missing, ONE grouped message to the user, pin
                            decisions, no execution)
  * plan block shape        pre_planner.render_plan_block L296-346
  * grounding line          cli_process_manager.py L1291-1297
  * discipline rules        cli_process_manager.py `_exec_discipline_parts` L353-405,
                            REWRITTEN (codex): no "Ask 'Shall I proceed?'", no
                            CLAUDE.md, no HydroCraft plot-script paths, no
                            resolution block
  * validity / judge        cli_process_manager.py L1304-1309, L1332-1334
  * completion              cli_process_manager.py L1335-1345 + the desktop's
                            headless long-job rule (prompt.py L62-79)
  * receipt line            kiss_cli/harness_runtime.py `receipt_line` L133-141
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ki_tools_common.harness.ki_harness import contract, KiHarnessError

from .states import State, FlowContext


def _ki_contract(ki_root: Path, mode: str) -> str:
    """Never silently downgrade (plan v3 B2): execute mode on a KI with no protocol raises."""
    try:
        return contract(str(ki_root), mode=mode)
    except KiHarnessError:
        if mode == "execute":
            raise
        return (f"[KI HARNESS v1] {ki_root}: no SKILL.md — nothing here is runnable. "
                f"Plan only; the execution turn will refuse this KI until it has a protocol.")


# ---------------------------------------------------------------------------
# Discipline — one source, every execution turn (chat's lesson, CPM L1310-1321)
# ---------------------------------------------------------------------------

def discipline(ki_count: int = 1) -> str:
    return (
        "⚠️ EXECUTION DISCIPLINE (MANDATORY) ⚠️\n"
        "1. VERIFY EACH STEP: after every step check the output file exists and its values are "
        "plausible, and say so, BEFORE the next step. Never chain steps blind.\n"
        "2. NO DUPLICATES: before running anything, check whether the output already exists and "
        "whether the same job is already running. Never launch the same generation twice.\n"
        "3. STATE YOUR DATA: name the forcing source and the terrain/static data the approved plan "
        "picked, and why they fit this location and period. Do not switch sources on your own — "
        "that is a re-plan.\n"
        "4. NO SHORTCUTS: never a 'simplified approach', never a hand-written substitute for the "
        "model or for a KI tool, never literature values reported as results. If the model needs "
        "many input files, generate all of them with the KI tools. If a step takes time, run it "
        "and wait.\n"
        "5. DEBUGGING PROTOCOL, in this order and no other: (1) grep the KI's "
        "diagnostics/triplets.* for the error keyword and apply the remedy if it matches — then "
        "STOP debugging; (2) the KI's SKILL.md troubleshooting/units section; (3) a prior "
        "successful run's outputs or the model's own example; (4) only then targeted manual "
        "fixes. No blind retries.\n"
        "6. NO SUB-AGENT EXECUTION: do not hand simulation, input preparation, downloads or "
        "plotting to child agents — they do not carry this contract or the plan. Advisory "
        "sub-agents (look something up, read a paper) are fine.\n"
        f"7. {'EVERY selected model runs; ' if ki_count > 1 else ''}KI TOOLS ARE EXECUTABLES, not "
        "reference code: run them by absolute path with the project interpreter. Do not read "
        "them and re-implement their logic inline.\n"
        "8. PROGRESS: the user sees your output live. One step per block, a blank line between "
        "steps, '---' between stages, a status line BEFORE any command longer than ~30 s.\n"
    )


PROGRESS_LONG_JOBS = (
    "[LONG JOBS] Launch anything long detached (setsid nohup … &) and WAIT for it in this same "
    "turn with a bounded until-loop; ending the turn while a job runs kills the run, and "
    "'done' is judged by receipts, not by your last message.\n"
)


# ---------------------------------------------------------------------------
# Planning turn
# ---------------------------------------------------------------------------

_PLAN_SCHEMA_NOTE = (
    "[PLAN FILES — WRITE EXACTLY THESE]\n"
    "  runs/plan.json           : {schema_version:'1.0', goal, selected_kis:[…], coupling:[…], "
    "steps:[{id, ki, tool:'<absolute path to a shipped tool under <KI>/tools/, a protocol-declared sN_stage/ script, or the model binary the KI declares under binary.path in knowledge_infrastructure.yaml; or null>', kind, inputs:[inventory "
    "ids], outputs:[…], status:'planned', env?:{NAME:'value'}}], scientific_choices:[{id, kind, options, picked, "
    "high_impact:true|false, decision?}], unresolved_questions:[…], created_at}\n"
    "  runs/data-inventory.json : {schema_version:'1.0', items:[{id, required_by:[KI…], "
    "status:'missing'|'resolved'|'ready', acceptable_sources:[…], chosen_source, dataset_id?, "
    "local_paths:[…], agent_resolvable:bool, needs_user:bool, decision?, acquisition_id?, "
    "requirements?:{bbox:[west,south,east,north],start:'YYYY-MM-DD',end:'YYYY-MM-DD',variable:'prec,temp'}}]}\n"
    "  Save known data requirements per inventory item; do not invent unknown grid or dates. "
    "Search with those same filters. The project's status panel uses requirements to compare "
    "coverage and identify manual downloads versus agent preparation. Search match.status is "
    "metadata-only: covered is not scientific validation; unknown needs inspection and "
    "insufficient requires a different selection or explicit revised scope. Acceptable sources "
    "are alternatives, not a chosen dataset.\n"
    "  For every inventory item pinned from the GeoForge Database add one scientific choice "
    "{id:'data:<item id>', kind:'data_source', item:'<item id>', options:[dataset ids you considered, "
    "including the one you picked], picked:'<dataset id>', rationale:'one sentence', high_impact:true}. "
    "GeoForge shows those candidates to the user with delivery, size and coverage from the catalogue; "
    "the user may pick another one on the approval card, and GeoForge re-pins the item itself. "
    "List real candidates only (ids returned by search_catalogue), never invented ones.\n"
    "  Use the KI's declared input names (dag.yaml inputs) as inventory ids wherever they apply; "
    "GeoForge reads the KI's source_kind, format and notes for each and decides on the card whether "
    "GeoForge fetches it, the run prepares it with the KI's default tool, or the user must provide it. "
    "Set decision: 'user' on an item only when the user should supply their own file instead of the "
    "KI default. Do not mark inputs missing or needs_user by yourself.\n"
    "  dataset_id is the exact GeoForge Database id when the input comes from the catalogue; "
    "GeoForge verifies it and records delivery, size and coverage on the item. A catalogue "
    "input is 'resolved', not 'missing', even before download. For server clipping, call "
    "describe_dataset then estimate_clip (CLI geoforge-db --describe / --subset ...) for the study "
    "bbox, period and native variables, then give the inventory item that dataset_id, "
    "delivery 'subset' and the same bbox/variables/period in requirements. GeoForge joins the "
    "item to the matching estimate itself (you may also copy the acquisition_id), re-estimates "
    "it before the card, and starts the server job when the user approves the plan: there is "
    "no separate data approval. Unknown coverage is shown on the card as inspection-only; it is "
    "not model-ready. After approval GeoForge fetches every served dataset, server clip and "
    "manual delivery itself, before execution starts, and signs a receipt for each. Inspect and "
    "prepare KI inputs before simulation; never manufacture acquisition/approval files. "
    "For whole-file delivery, never pin an unresolved whole-product parent "
    "(a national grid of hundreds of GB): use search_catalogue with parent_id "
    "(CLI obs-search --resolve PRODUCT --variable prec,temp --start YYYY-MM-DD --end YYYY-MM-DD "
    "--time-step daily --bbox west,south,east,north). Pin only actual returned items[].id; never "
    "construct child IDs. Each child inventory item describes its own year/variable requirements; "
    "the plan must include all files needed for the full simulation and warmup period. "
    "spatial_filter_applied:false means national files with local extraction, not clipped downloads. "
    "Show total download bytes and explicit local preprocessing steps before approval.\n"
    "  For gridded forcing, choose by the model grid extent/cells, required variables and period, "
    "not a basin-name match alone. Catalogue bbox filtering is not spatial clipping. Verify "
    "the actual downloadable unit. Prefer matching spatial tiles or verified grid extraction; "
    "if only a larger regional/national package exists, disclose its coverage, size and local "
    "extraction requirements as a scientific choice for user confirmation. Do not claim a "
    "basin download link is a grid-specific link.\n"
    "  A draft of both is already there. Correct it; do not invent a different format. 'ready' "
    "means the file exists on disk at local_paths — you may NOT download anything in this turn, "
    "so only files that already exist can be 'ready'. Every step input must reference an "
    "inventory ID, not a filename. Add upstream-generated intermediate inputs to the inventory "
    "with their producer/source and missing status until they exist. Keep unsupported steps "
    "tool:null with an unresolved question; never invent an executable path. A preflight check "
    "is host-managed, not a pipeline tool: represent it as kind:'check', tool:null with a note "
    "that GeoForge will verify the installation after approval; do not use preflight_check.py "
    "as a step tool. A shipped tool's required environment belongs in that step's optional env "
    "object before approval. Use only literal values or ${PROJECT}/${KI_ROOT}; never put PATH, "
    "HOME, interpreter startup variables, credentials, shell expressions, or personal/system "
    "paths there. GeoForge passes exactly this approved environment to that step.\n"
)


def planning_block(kis: dict[str, Path], plan: dict, inventory: dict, project: Path,
                   ambiguous: dict | None = None, partners_to_ask: list[str] | None = None,
                   replan_reason: str = "", wrappers: dict | None = None,
                   database_access_mode: str = "direct") -> str:
    """The read-only planning turn. kis = {model_id: ki_root}."""
    names = ", ".join(kis)
    s = plan.get("summary") if isinstance(plan.get("summary"), dict) else {}
    coupling = plan.get("coupling") if isinstance(plan.get("coupling"), list) else []
    lines = [
        f"[MODE: PLANNING — design the run for {names}; NO execution]",
        "The app has ALREADY resolved the models and derived a first plan from each KI's own "
        "files (below). Your job, in THIS turn:",
        "  1. The model picks are FIXED — justify each for this question in one sentence"
        + (" (except where the app flagged an ambiguous name — ask about that)." if ambiguous else "."),
        "  2. Confirm the location, period, resolution and the forcing source the plan picked "
        "(read the KI's SKILL.md and dag.yaml to check the choice is right for this model).",
        "  3. Go through runs/data-inventory.json: which inputs are auto-resolved (a dataset on "
        "this machine, a forcing provider, an upstream model) and which are MISSING. Check the "
        "disk for files that already exist. Do not download anything.",
        "  4. Collect EVERY question for the user into ONE grouped message: missing data you "
        "cannot obtain yourself, licences/logins, and high-impact scientific choices (forcing "
        "source, calibration target, extent/period). Offer 2-5 concrete options each.",
        "  5. Write runs/plan.json and runs/data-inventory.json (format below), then stop.",
        "Do NOT prepare inputs, do NOT compile, do NOT download, do NOT run any model binary or KI "
        "pipeline tool. Read scripts and existing verification reports instead. Do not assume "
        "--help or preflight is side-effect-free: some scripts run preprocessing on import. "
        "Approval and execution happen in a LATER, separate session — do not ask "
        "'shall I proceed'; the app asks the user.",
    ]
    if database_access_mode == "direct" and wrappers and wrappers.get("obs_search"):
        lines.append(
            "[AUTHENTICATED OBSERVATION CATALOGUE] When an observation or forcing input is "
            "missing, query the live GeoForge Database through the Desktop host with "
            f"`{wrappers['obs_search']} <keywords>` (filters: --bbox minlon,minlat,maxlon,maxlat "
            "--start YYYY-MM-DD --end YYYY-MM-DD --variable name --category forcing|gauge|... "
            "--delivery served|manual; --limit/--offset). Records carry bbox, point, period, "
            "delivery, size, parent_id and notes; read notes for coverage written in prose. "
            "Run this command yourself instead of asking the user whether the database has data. "
            "The Desktop retains the token; this read-only adapter returns sanitized metadata only. "
            "Pin the exact dataset id, delivery type, variables, extent and period in the inventory; "
            "never download during planning. A dataset with delivery 'manual' is a normal choice: "
            "pin it, and after approval GeoForge shows the user the download link and target folder "
            "and waits for the files. Do not call manual delivery a dead end."
            " Manual delivery is never a reason to ask the user which data to use: pick the best-fitting dataset yourself, pin it, and state the choice in scientific_choices with your reason. Ask the user only when a scientific choice is genuinely open (site, period, evaluation target), and then with request_user_action, one question at a time, recommending a default.")
    elif database_access_mode == "direct" and wrappers is None:
        lines.append(
            "[AUTHENTICATED OBSERVATION CATALOGUE] When an observation or forcing input is "
            "missing, call search_catalogue yourself during planning instead of asking "
            "the user whether the database has data. It returns live GeoForge Database "
            "metadata but no credentials. Pin the exact dataset id, delivery type, variables, "
            "extent and period in the inventory. You never download: after the user approves the "
            "plan, GeoForge fetches every pinned dataset itself and signs a receipt. A dataset with "
            "delivery 'manual' is a normal choice: pin it; GeoForge shows the user a private card "
            "with the link and target folder and waits for the files. Do not call manual delivery "
            "a dead end."
            " Manual delivery is never a reason to ask the user which data to use: pick the best-fitting dataset yourself, pin it, and state the choice in scientific_choices with your reason. Ask the user only when a scientific choice is genuinely open (site, period, evaluation target), and then with request_user_action, one question at a time, recommending a default.")
    elif database_access_mode == "snapshot":
        lines.append(
            "[GEOFORGE DATABASE: CACHED CATALOGUE MODE] The Desktop will append the path to a "
            "sanitized catalogue snapshot. Inspect that file; no live database query tool is "
            "available in this mode. Clearly identify stale or unavailable metadata.")
    else:
        lines.append(
            "[GEOFORGE DATABASE: DISABLED] Database discovery is disabled for this project turn. "
            "Do not claim that the catalogue was searched or that a dataset is available.")
    if replan_reason:
        lines.append(f"[RE-PLAN] {replan_reason}. Correct the existing draft rather than "
                     "restarting the study. Nothing is approved for this revision; save both "
                     "files and stop for host validation.")
    if ambiguous:
        lines.append("[AMBIGUOUS MODEL NAMES — ASK] " + "; ".join(
            f"'{k}' could be {v}" for k, v in ambiguous.items()))
    if partners_to_ask:
        lines.append("[COUPLED PARTNER NOT SELECTED — ASK] the plan names a coupling partner that "
                     "is not in the run: " + ", ".join(partners_to_ask) + ". Ask whether to include "
                     "it, or narrow the study. Never build a substitute for a model that is not "
                     "in the run.")
    lines.append(
        f"[PLAN DRAFT — derived from the KIs' dag.yaml/cards] models={plan.get('selected_kis')} "
        f"inputs={s.get('total_inputs')} auto_resolved={s.get('auto_resolved')} "
        f"needs_user={s.get('asked_of_user')} coupling={[c.get('edge_id') for c in coupling if isinstance(c, dict)]}\n"
        f"  files: {Path(project) / 'runs' / 'plan.json'}, {Path(project) / 'runs' / 'data-inventory.json'}")
    lines.append(_PLAN_SCHEMA_NOTE)
    for mid, root in kis.items():
        lines.append(f"===== {mid} " + "=" * max(4, 60 - len(mid)))
        lines.append(_ki_contract(Path(root), "inspect"))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Execution turn
# ---------------------------------------------------------------------------

def grounding_line(project: Path, plan: dict, approval: dict) -> str:
    """cli_process_manager.py L1291-1297, verbatim shape."""
    r = Path(project) / "runs"
    return ("[STAGE GROUNDING — execute the carried plan; do not re-derive]\n"
            f"USE THE PLAN/INPUTS AT: {r / 'plan.json'}, {r / 'data-inventory.json'}, "
            f"{r / 'plan.coupling.yaml'}\n"
            f"APPROVED: by {approval.get('approved_by')} at {approval.get('approved_at')} "
            f"(plan sha256 {str(approval.get('plan_sha256'))[:12]}…); decisions = "
            f"{json.dumps(approval.get('decisions') or {}, ensure_ascii=False)}\n"
            "Execute the plan handed off from planning; do NOT disk-glob for it, do NOT re-plan "
            "the scope, do NOT re-select models.\n")


def execution_block(kis: dict[str, Path], plan: dict, approval: dict, project: Path,
                    provider: str = "", wrappers: dict | None = None, short: bool = False) -> str:
    """The execution session's contract. Raises KiHarnessError if a selected KI has no
    protocol (plan v3 B2: never fall back to run wording).

    wrappers: {"run_tool": "<cmd prefix>", "fetch": "<cmd prefix>"} for CLI providers;
    None for API providers (their tools write receipts themselves)."""
    lines = [grounding_line(project, plan, approval)]
    if short:
        lines.append(discipline(len(kis)))
        return "\n".join(lines)
    for mid, root in kis.items():
        lines.append(f"===== {mid} " + "=" * max(4, 60 - len(mid)))
        lines.append(_ki_contract(Path(root), "execute"))
    lines.append(discipline(len(kis)))
    lines.append(PROGRESS_LONG_JOBS)
    if wrappers:
        lines.append(
            "[RECEIPTS — HOW A RUN BECOMES REAL]\n"
            f"  model / KI tool runs : {wrappers.get('run_tool', 'run-tool')} --step <plan step id> "
            f"<KI> <tools/xxx.py> -- [tool args]\n"
            f"  downloads            : {wrappers.get('fetch', 'fetch')} --item <inventory id> "
            f"--step <plan step id> <url>\n"
            "  (options BEFORE the positional arguments; tool arguments after `--`)\n"
            "  GeoForge Database data (served, server clips, manual Baidu deliveries) is already "
            "fetched and receipted by GeoForge before this execution turn; find it under inputs/ "
            "via the data receipts. Missing catalogue data is a plan change (request_replan), not "
            "something to download here.\n"
            "  These write a signed receipt (command, binary hash, exit code, input/output hashes). "
            "A model run or download done any other way has NO receipt and can never make the "
            "project 'done' — the app lists it as an unreceipted artifact.\n")
    else:
        lines.append(
            "[RECEIPTS] Every run_ki_tool / run_calibration / fetch_data call writes a signed "
            "receipt. Outputs that no receipt names cannot make the project 'done'. GeoForge "
            "Database inputs (served, server clips, manual deliveries) were fetched and receipted "
            "by GeoForge before this turn; find them under inputs/ via the data receipts.\n")
    lines.append(
        "[VALIDATION — NOT YOUR OWN JUDGE] The app validates every output against the KI's "
        "dag.yaml (exists, non-empty, no NaN/Inf, complete time axis, physically required "
        "positive values, units). You PRODUCE the run and report exactly what it produced; you do "
        "not declare a metric the verdict, and a FAILED validation is never a result.\n"
        "[DONE MEANS] every planned step has a receipt and validation passed. Do not claim "
        "completion while a detached job is still running — wait for it in this turn.\n")
    lines.append(
        ("[RE-PLAN TRIGGERS] If you find you need another model, a substitute for a model or a "
         "core algorithm, a different data source, or a different extent/period/scenario/"
         "calibration target: STOP, say 'REPLAN_REQUIRED: <why>' and end the turn. GeoForge then "
         "starts the re-planning turn for you. Do not continue on a plan the user did not approve.\n"
         if wrappers else
         "[RE-PLAN TRIGGERS] If you find you need another model, a substitute for a model or a "
         "core algorithm, a different data source, a different tool input, or a different extent/"
         "period/scenario/calibration target: call request_replan(reason) and then write_plan "
         "with the corrected plan in this same turn. Do not improvise around the approved plan; "
         "the user approves the revision before anything else runs.\n"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Receipt line (extends kiss_cli/harness_runtime.receipt_line L133-141)
# ---------------------------------------------------------------------------

def receipt_line(ctx: FlowContext, ki_root: Path, contract_text: str, provider: str,
                 session_id: str = "", implementation_path: Path | None = None) -> str:
    skill = Path(ki_root) / "SKILL.md"
    skill_sha = hashlib.sha256(skill.read_bytes()).hexdigest() if skill.is_file() else ""
    impl_sha = ""
    if implementation_path and Path(implementation_path).is_file():
        impl_sha = hashlib.sha256(Path(implementation_path).read_bytes()).hexdigest()
    mode = {State.EXECUTING: "execute", State.VERIFYING: "inspect"}.get(ctx.state, "inspect")
    import time as _t
    # fields from the issue's "Harness receipt" schema: harness_marker, harness_mode,
    # harness_sha256, ki_name, ki_root, skill_sha256, provider, session_id, injected_at
    return ("[GEOFORGE HARNESS RECEIPT] harness_marker=[KI HARNESS v1] "
            f"harness_mode={mode} harness_sha256={impl_sha} flow_state={ctx.state.value} "
            f"enforcement={ctx.enforcement.value} ki_name={Path(ki_root).parent.name if Path(ki_root).name == 'knowledge_infrastructure' else Path(ki_root).name} "
            f"ki_root={ki_root} skill_sha256={skill_sha} provider={provider or ctx.provider} "
            f"session_id={session_id} injected_at={_t.strftime('%Y-%m-%dT%H:%M:%S%z')} "
            f"contract_sha256={hashlib.sha256(contract_text.encode('utf-8')).hexdigest()}")
