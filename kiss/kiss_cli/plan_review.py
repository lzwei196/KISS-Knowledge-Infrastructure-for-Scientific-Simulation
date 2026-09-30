"""Desktop Plan Review: issue one review, then respond to the user's click.

This module owns the displayed-card snapshot, saved answers and ordered signing
transaction. Shared Flow remains authoritative for decision records and approval.
It does not create subset jobs, acquire inputs or start scientific execution.

The browser payload and existing on-disk review/answer formats remain unchanged.
issue() is also used for unsigned re-reviews. respond() returns a disposition
so the turn driver can resume planning, wait, or start acquisition after approval.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import flowgate, projectrun, setup as setup_flow

APPROVAL_REQUEST_ID_PREFIX = "flow-approve-"

@dataclass(frozen=True)
class Response:
    """A review result, not permission to execute an arbitrary tool.

    Only approved allows the driver to start its existing acquisition flow.
    inventory is the same inventory covered by the saved approval.
    """
    disposition: Literal["unhandled", "waiting", "replan", "approved"]
    message: str | None = None
    replan_reason: str = ""
    inventory: dict | None = None


def _database_approval_block(inventory: dict) -> str | None:
    """An issued review is not evidence of current Database activation.

    Read only the host's cached activation state; never open Keychain or refresh
    the catalogue from a consent check. Public/user inputs do not need the DB.
    """
    from . import obs_access, settings
    from .acquire import ACQUIRABLE

    pinned = [str(item.get("id")) for item in inventory.get("items") or []
              if isinstance(item, dict) and
              (item.get("dataset_id") or item.get("delivery") in ACQUIRABLE)]
    if pinned and obs_access.effective_mode(settings.database_access_mode()) == "off":
        return ("GeoForge Database access is off or not activated, but this plan still needs it for "
                + ", ".join(pinned) + ". Nothing was approved or downloaded. "
                "Activate the Database in Settings and approve again, or choose “Modify the plan” "
                "to use public sources or your own files. Your saved choices are retained.")
    return None


def respond(project: Path, *, action: dict | None, pending: dict | None,
            ki_roots: dict[str, Path], note: str = "") -> Response:
    """Resolve one click against the host's persisted, issued review.

    Validate the reviewed files/display and readable answer history first; preserve
    real picks against that snapshot; refresh estimates; reissue unsigned when
    necessary; resolve decision provenance; then sign through shared Flow.
    No caller needs to repeat that ordering or interpret the persisted baseline.

    Expected data-refresh failures leave the pending card available for retry.
    Other storage errors propagate without deliberately consuming the card.
    """
    if not (pending and str(pending.get("id", "")).startswith(APPROVAL_REQUEST_ID_PREFIX)
            and action and str(action.get("request_id")) == str(pending.get("id"))):
        return Response("unhandled")

    project = Path(project)
    flow = flowgate.load()
    ctx = flow.states.FlowContext.load(project)
    if str(action.get("option_id") or "") != "approve":
        setup_flow.clear_request(project)
        ctx.move("modify")
        projectrun.set_stage(project, flow.states.DISPLAY_STAGE.get(ctx.state, "preparing"),
                             "Revising the plan")
        return Response("replan", replan_reason=note or "user asked for changes")

    pj, inv = flow.plan.read_artifacts(project)
    review = _issued_review(project, pending)  # host copy; never trust request.review
    if (pj is None or inv is None or review.get("plan_sha256") != flow.plan.sha256(pj)
            or review.get("inventory_sha256") != flow.plan.sha256(inv)):
        setup_flow.clear_request(project)
        ctx.move("modify")
        return Response("replan", replan_reason=
                        "The plan or inventory changed after review. Review this revision before approval.")
    displayed = action.get("shown") if isinstance(action.get("shown"), dict) else pending
    if review.get("shown_sha256") != shown_sha256(displayed):
        setup_flow.clear_request(project)
        ctx.move("modify")
        return Response("replan", replan_reason=
                        "The approval card changed after it was issued. Review the re-issued card before approval.")

    try:
        load_user_answers(project)  # a corrupt store must not consume the card
    except AnswersUnreadable as error:
        return Response("waiting", message=f"Your saved answers cannot be read ({error}). "
                        "Fix or remove that file, then approve again.")

    # Admission applies to plan mutations AND provenance. The agent's plan may
    # contain unrendered choices/options; those are not permissions from the user.
    baseline = review["baseline"]
    submitted = action.get("choices") if isinstance(action.get("choices"), dict) else {}
    picks = {cid: value for cid, value in submitted.items()
             if cid in baseline["suggested"] and isinstance(value, str)
             and value in baseline["options"].get(cid, [])}
    try:
        record_user_answers(project, baseline, picks)
    except AnswersUnreadable as error:
        return Response("waiting", message=f"Your saved answers cannot be read ({error}). "
                        "Fix or remove that file, then approve again.")

    from . import obs_access, obs_subset

    def reissue(reasons: list[str]) -> None:
        from . import settings
        fs = flowgate.FlowSession.open(project, ki_roots, database_access_mode=obs_access.effective_mode(
            settings.database_access_mode()))       # the setting, never an assumed "direct"
        provider_note = str((pending.get("plan_review") or {}).get("tool_policy") or "")
        issue(project, fs, pj, inv, provider_note, extra_why=reasons)

    repinned = apply_data_choices(pj, inv, picks)
    apply_choice_picks(pj, picks)  # same-click scientific picks survive any re-review
    if blocked := _database_approval_block(inv):
        flow.plan.write_artifacts(project, pj, inv)
        reissue([blocked])       # suppress cached DB options without fetching anything
        return Response("waiting", message=blocked)
    try:
        if repinned:
            errors = obs_access.stamp_inventory(inv, project=project)
        else:
            # Refresh before persisting same-click picks. If the request fails,
            # the original reviewed files/card stay valid and real answers remain.
            changed = obs_subset.refresh_inventory(project, inv)
            stamp_errors = obs_access.stamp_inventory(inv, project=project) if changed else []
            for error in stamp_errors:
                changed.setdefault("inventory", []).append(error)
        # Remote estimates may take time: bind the files that remain after that
        # work, so a deletion/replacement during refresh cannot sign old evidence.
        bound = bind_uploads(project, pj, inv)
    except AnswersUnreadable as error:
        return Response("waiting", message=f"Your saved answers cannot be read ({error}). "
                        "Fix or remove that file, then approve again.")
    except (obs_access.ObsAccessError, OSError) as error:
        return Response("waiting", message=f"The plan review could not refresh its data: {error}. "
                        "Approval has not started any work. Your saved choices are retained; try the review again.")

    if repinned or bound:
        # the user approves the card that names what will run, never a silent rebinding
        said = ((["data re-pinned to your choice: " + ", ".join(repinned)] if repinned else [])
                + (["your file is now named as the input: " + "; ".join(bound)] if bound else []))
        flow.plan.write_artifacts(project, pj, inv)
        reissue(said + (errors if repinned else
                        [f"{item}: {'; '.join(reasons)}" for item, reasons in changed.items()]))
        return Response("waiting", message=". ".join(s[0].upper() + s[1:] for s in said)
                        + ". The updated card is in the chat; approve it to start.")

    if changed:
        flow.plan.write_artifacts(project, pj, inv)
        why = [f"{item}: {'; '.join(reasons)}" for item, reasons in changed.items()]
        reissue(["clip estimates changed since you reviewed: "] + why)
        return Response("waiting", message="The server clip estimates changed since you reviewed the plan: "
                        + "; ".join(why) + ". The updated card is in the chat; approve again if it still fits.")

    # A remote estimate can take time. Re-read the host store before signing;
    # unreadable history must not be replaced by an earlier in-memory snapshot.
    try:
        answers = record_user_answers(project, baseline, picks)
    except AnswersUnreadable as error:
        return Response("waiting", message=f"Your saved answers cannot be read ({error}). "
                        "Fix or remove that file, then approve again.")
    records, invalid = decision_records(flow, pj, inv, answers, baseline=baseline)
    blocking = [display_input_id(i) for i in flow.decisions.open_inputs(records)] + invalid
    if blocking:
        flow.plan.write_artifacts(project, pj, inv)
        reissue(["still waiting on your decision: " + ", ".join(blocking[:8])])
        uploads = [f"inputs/user/{display_input_id(i)}/" for i in flow.decisions.open_inputs(records)
                   if str((records.get(i) or {}).get("value") or "").startswith("upload it to")]
        return Response("waiting", message="These still need your decision before anything runs: "
                        + ", ".join(blocking[:8]) + ". "
                        + (f"Upload your file with the Upload button on the card (it goes to "
                           f"{', '.join(uploads[:8])}). " if uploads else "")
                        + "Pick a data source on the card where one is offered; "
                        "for anything else choose “Modify the plan” and say what to use.")

    # This revision is inside the hash shared Flow signs. Never mutate inventory
    # after signing; clip job creation and binding belong to the turn driver.
    # Settings/credential state may have changed during the remote estimate.
    if blocked := _database_approval_block(inv):
        flow.plan.write_artifacts(project, pj, inv)
        reissue([blocked])
        return Response("waiting", message=blocked)
    pj["decision_revision"] = flow.decisions.revision_of(records)
    flow.plan.write_artifacts(project, pj, inv)
    if flow.approval.check(project) != "OK":
        decided = dict(records)
        if note:
            decided["note"] = {"input_id": "note", "source": "user", "value": note}
        flow.approval.approve(project, decided, by="user")
    setup_flow.clear_request(project)
    return Response("approved", inventory=inv)


def _ki_roots_for(plan: dict, project: Path | None) -> dict[str, Path]:
    """The materialised KI folders of the plan's KIs inside the project (models/<KI>/ki)."""
    roots = {}
    for name in plan.get("selected_kis") or []:
        if project is None:
            continue
        cand = Path(project) / "models" / str(name) / "ki"
        if (cand / "dag.yaml").is_file():
            roots[str(name)] = cand
    return roots


def input_groups(plan: dict, inv: dict, project: Path | None = None) -> dict:
    """Inputs in the three groups the user needs: fetch / you / run.

    Decided by the host from facts, never from the agent's bookkeeping: the catalogue
    delivery, the plan's step outputs, files on disk, and the KI's own declaration of
    each input (source kind, format, notes, the tool that prepares it). See
    ki_tools_common.flow.declared."""
    from . import obs_access
    flow = flowgate.load()
    items = [it for it in inv.get("items") or [] if isinstance(it, dict)]
    produced = {str(o) for st in plan.get("steps") or [] if isinstance(st, dict)
                for o in st.get("outputs") or []}
    declared = ()
    for root in _ki_roots_for(plan, project).values():
        declared = declared + flow.declared.declared_inputs(str(root))

    def _row(it, verdict):
        cat = it.get("catalogue") or {}
        return {"id": it.get("id"), "for": list(it.get("required_by") or []),
                "resolution": cat.get("resolution"),
                "dataset_id": it.get("dataset_id"), "size": cat.get("size"),
                "size_label": obs_access.size_label(cat.get("size")),
                "name": cat.get("name"), "how": verdict["how"],
                "declared": (verdict.get("declared") or {}).get("name"),
                "facts": {k: (verdict.get("declared") or {}).get(k) for k in ("format", "unit", "notes", "default_tool")},
                "target_path": f"inputs/user/{it.get('id')}" if verdict["how"] == "provide" else None,
                "note": flow.declared.instructions(it, verdict),
                "period": [cat.get("start_date"), cat.get("end_date")] if cat.get("start_date") else None}

    groups = {"fetch": [], "you": [], "run": []}
    for it in items:
        verdict = flow.declared.classify(it, declared, produced)
        groups[verdict["group"]].append(_row(it, verdict))
    return {"total": len(items), **groups}


def _data_summary(plan: dict, inv: dict, project: Path | None = None) -> str:
    """The text twin of the card's data section: fetch / you / run."""
    from . import obs_access
    g = input_groups(plan, inv, project)
    by_id = {str(it.get("id")): it for it in inv.get("items") or [] if isinstance(it, dict)}
    lines = [f"Data: {g['total']} inputs"]
    if g["fetch"]:
        lines.append(f"  ✓ GeoForge fetches after approval ({len(g['fetch'])})")
        for r in g["fetch"][:8]:
            it = by_id.get(str(r["id"]), {})
            es = it.get("estimate_summary") or {}
            what = (f"server clip, {obs_access.size_label(es.get('bytes')) or 'size unknown'}, {es.get('n_parts') or '?'} files"
                    if r["how"] == "clip" else f"{r['size_label'] or 'size unknown'}")
            lines.append(f"    {r['id']} ← {r['dataset_id']} ({what})")
    if g["you"]:
        lines.append(f"  ⬇ you ({len(g['you'])})")
        for r in g["you"][:8]:
            if r["how"] == "manual":
                lines.append(f"    download {r['dataset_id']} ({r['size_label'] or 'size unknown'}) from the Baidu link GeoForge shows after approval → {r['id']}")
            else:
                lines.append(f"    {r['id']}: {r['note'] or 'provide it'}")
    if g["run"]:
        kinds = {"on_disk": "already on disk", "generated": "made by a step", "default": "KI default method",
                 "prepared": "prepared during the run"}
        counts = {}
        for r in g["run"]:
            counts[r["how"]] = counts.get(r["how"], 0) + 1
        lines.append("  ⚙ the run prepares itself (" + ", ".join(f"{n} {kinds[k]}" for k, n in counts.items()) + ")")
        for r in g["run"]:      # every card names the uploaded file the approval will bind (issue #4)
            mine = [p for p in by_id.get(str(r["id"]), {}).get("local_paths") or []
                    if str(p).startswith("inputs/user/")]
            if r["how"] == "on_disk" and mine:
                lines.append(f"    {r['id']} ← your file {', '.join(mine[:3])}")
    for it in inv.get("items") or []:
        res = ((it or {}).get("catalogue") or {}).get("resolution") or {}
        if isinstance(it, dict) and res.get("spatial_filter_applied") is False:
            lines.append(f"  {it.get('id')}: uncut delivery extent {res.get('delivery_extent')}; "
                         f"study bbox {res.get('requested_bbox')}; local extraction required.")
    return "\n".join(lines)


def _data_choices(plan: dict, inv: dict, project: Path | None = None) -> list[dict]:
    """The candidates the agent considered per input, with catalogue facts, for the card.

    This is the missing step the user asked for: what the database holds for each input,
    shown before approval, with the recommendation preselected and the user free to pick."""
    from . import obs_access
    store = obs_access.load_catalogue() or {}
    by_id = {str(d.get("id")): d for d in store.get("datasets") or [] if d.get("id")}
    items = {str(it.get("id")): it for it in inv.get("items") or [] if isinstance(it, dict)}
    from . import obs_subset
    estimated = obs_subset.estimated_datasets(project) if project is not None else set()
    out = []
    for c in plan.get("scientific_choices") or []:
        if not isinstance(c, dict) or c.get("kind") != "data_source":
            continue
        item_id = str(c.get("item") or str(c.get("id") or "").replace("data:", "", 1))
        item = items.get(item_id, {})
        options = []
        for ds in c.get("options") or []:
            rec = by_id.get(str(ds))
            if rec is None:
                continue                # invented ids never reach the user
            option = {"dataset_id": str(ds), "name": rec.get("name"), "delivery": rec.get("delivery"),
                      "size": rec.get("size"), "size_label": obs_access.size_label(rec.get("size")),
                      "period": [rec.get("start_date"), rec.get("end_date")] if rec.get("start_date") else None,
                      "bbox": rec.get("bbox")}
            if (str(item.get("dataset_id")) == str(ds) and item.get("delivery") == "subset"
                    and item.get("acquisition_id")):
                # The host already validated/stamped this item's selected estimate.
                # Project clip facts, not the whole product's manual delivery/size,
                # belong on its option. Never borrow a clip from a different item or
                # fetch a fresh estimate while projecting the reviewed inventory.
                cat = item.get("catalogue") or {}
                scope = item.get("requirements") or {}
                size = cat.get("size")
                option.update(delivery="subset", size=size, size_label=obs_access.size_label(size),
                              period=[scope.get("start"), scope.get("end")]
                              if scope.get("start") or scope.get("end") else None,
                              bbox=scope.get("bbox"))
            elif option["delivery"] == "manual" and project is not None and str(ds) not in estimated:
                option["clip_checked"] = False      # bug #3: whole-product size; clipping unknown
            options.append(option)
        if not options:
            continue
        picked = str(c.get("decision") or c.get("picked") or items.get(item_id, {}).get("dataset_id") or "")
        out.append({"id": str(c.get("id")), "item": item_id, "picked": picked,
                    "rationale": str(c.get("rationale") or ""), "options": options})
    return out


def apply_choice_picks(plan: dict, choices: dict) -> list[str]:
    """Write NON-data card picks into the plan so a re-issued card keeps them (codex/kimi #5).
    A pick that is not one of the offered options is ignored."""
    done = []
    for c in plan.get("scientific_choices") or []:
        if not isinstance(c, dict) or c.get("kind") == "data_source" or not c.get("id"):
            continue
        pick = (choices or {}).get(str(c["id"]))
        if pick and str(pick) in [str(o) for o in c.get("options") or []]:
            c["decision"], c["decision_source"] = pick, "user"      # display only; provenance
            done.append(str(c["id"]))                               # comes from the answer store
    return done


def apply_data_choices(plan: dict, inv: dict, choices: dict) -> list[str]:
    """The user's picks from the card: re-pin the items, clear stale stamps. Returns changed item ids."""
    changed = []
    items = {str(it.get("id")): it for it in inv.get("items") or [] if isinstance(it, dict)}
    for c in plan.get("scientific_choices") or []:
        if not isinstance(c, dict) or c.get("kind") != "data_source":
            continue
        pick = choices.get(str(c.get("id")))
        if not pick or pick not in [str(o) for o in c.get("options") or []]:
            continue
        item_id = str(c.get("item") or str(c.get("id") or "").replace("data:", "", 1))
        item = items.get(item_id)
        if item is None or item.get("dataset_id") == pick:
            c["decision"], c["decision_source"] = pick, "user"
            continue
        c["decision"], c["decision_source"] = pick, "user"
        c["picked"] = pick
        item["decision_source"] = "user"
        for key in ("acquisition_id", "acquisition_request_sha256", "acquisition_offer", "estimate_summary", "catalogue"):
            item.pop(key, None)
        item["dataset_id"] = pick
        item["chosen_source"] = pick
        item.pop("delivery", None)
        changed.append(item_id)
    return changed


ANSWERS_FILE = "user-answers.json"          # under .geoforge/ — policy.ALWAYS_PROTECTED
INTERVIEW_NS = "interview"                  # planning-question clicks; `question:` is taken by open questions


def _answers_path(project: Path) -> Path:
    return Path(project) / ".geoforge" / ANSWERS_FILE


class AnswersUnreadable(RuntimeError):
    """The host-written answer store exists but cannot be read. Treating that as "no answers"
    would quietly turn every earlier user decision into a KI default (kimi review, 2026-09-26)."""


def load_user_answers(project: Path) -> dict:
    """What the USER actually answered, host-written. The plan files are agent-writable, so a
    provenance marker inside them proves nothing (codex/kimi review, 2026-09-25).

    A missing file means nothing was answered yet. Anything else that stops it being read is
    raised, so the approval refuses with the path instead of signing downgraded provenance."""
    path = _answers_path(project)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as e:
        raise AnswersUnreadable(f"{path}: {e}") from e
    try:
        doc = json.loads(raw)
    except ValueError as e:
        raise AnswersUnreadable(f"{path}: not valid JSON ({e})") from e
    if not isinstance(doc, dict) or not isinstance(doc.get("answers"), dict):
        raise AnswersUnreadable(f"{path}: unexpected shape (no answers map)")
    answers = dict(doc["answers"])
    for k, v in answers.items():
        val = v.get("value") if isinstance(v, dict) else None
        if val in (None, "") or (isinstance(val, (list, dict)) and not val):
            raise AnswersUnreadable(f"{path}: malformed entry {k!r}")
    return answers


def suggestion_baseline(plan: dict, inv: dict, rows: list | None = None) -> dict:
    """What the approval card showed as pre-selected, per choice id, and which inventory item
    each data choice answers — derived from the plan files, which the Approve click has just
    verified by hash against the card it was issued for. Same rules as `_data_choices` and
    `_card`, so the baseline is exactly what the user saw."""
    suggested: dict[str, str] = {}
    item_of: dict[str, str] = {}
    options: dict[str, list] = {}
    for row in (rows if rows is not None else _data_choices(plan, inv)):   # the rendered rows (B #2)
        opts = [str(o.get("dataset_id")) for o in row.get("options") or [] if isinstance(o, dict)]
        picked = str(row.get("picked") or "")
        # a pre-selection that is not among the rendered radios was never displayed: nothing
        # was shown as chosen for this row (codex review B4 #1)
        suggested[str(row["id"])] = picked if picked in opts else ""
        item_of[str(row["id"])] = str(row["item"])
        options[str(row["id"])] = opts
    for c in (plan or {}).get("scientific_choices") or []:
        # the UI lists only high-impact decisions (web/app.html renderPlanReview)
        if isinstance(c, dict) and c.get("id") and c.get("kind") != "data_source" and c.get("high_impact"):
            suggested[str(c["id"])] = str(c.get("decision") or c.get("picked") or "")
            options[str(c["id"])] = [str(o) for o in c.get("options") or []]
    return {"suggested": suggested, "item_of": item_of, "options": options}


def record_user_answers(project: Path, baseline: dict | None, picks: dict | None) -> dict:
    """Store the picks that are a real answer, at the moment of the click.

    The approval card pre-selects the recommendation and the UI submits EVERY checked radio
    (web/app.html L1339), so a pick equal to what the card recommended is not evidence that the
    user chose anything — it is the default coming back. Only a pick that DIFFERS from the
    recommendation (or answers something the card recommended nothing for) is recorded as the
    user's. Anything else stays a disclosed default.

    A data-source choice answers an inventory ITEM. `baseline` (see `suggestion_baseline`) says
    which, so the answer is stored under both `choice:<id>` and `item:<item>` — the reader never
    guesses across namespaces (kimi review, 2026-09-26).
    """
    suggested: dict[str, str] = dict((baseline or {}).get("suggested") or {})
    item_of: dict[str, str] = dict((baseline or {}).get("item_of") or {})
    options: dict[str, list] = dict((baseline or {}).get("options") or {})
    answers = load_user_answers(project)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    # Stores written before 2026-09-26 hold only `choice:` keys. The item a choice answers is
    # taken from the baseline (`item_of`), exactly as for new writes — never guessed from the
    # id's `data:` prefix alone, which is not proof of the binding (codex A2 #1). Only a record with
    # no `item` stamp is legacy: a modern record carries the binding it was written under, and
    # a replan that rebinds the same choice id to another item must not carry it over (A4 #1).
    for cid, item_id in item_of.items():
        legacy = answers.get(f"choice:{cid}")
        if isinstance(legacy, dict) and "item" not in legacy:
            if f"item:{item_id}" not in answers:
                answers[f"item:{item_id}"] = {k: v for k, v in legacy.items()}
            legacy["item"] = item_id          # stamped whether or not the item record existed:
                                              # a later rebinding must not reuse it (codex A6)
    for raw_id, value in (picks or {}).items():
        cid = str(raw_id)
        if value in (None, "") or (isinstance(value, (list, dict)) and not value):
            continue                     # what the reader rejects, the writer never stores (kimi A3)
        if str(value) == suggested.get(cid, object()):
            continue                     # the pre-selected recommendation came back untouched
        if cid in options and str(value) not in options[cid]:
            continue                     # not one of the choices the card offered (kimi B2 #3);
                                         # an empty menu offers nothing (codex B3 #4)
        answers[f"choice:{cid}"] = {"value": value, "at": stamp, "item": item_of.get(cid)}
        if item_of.get(cid):
            answers[f"item:{item_of[cid]}"] = {"value": value, "at": stamp}
    _save_answers(project, answers)
    return answers


def record_interview_answer(project: Path, pending: dict, resolved: dict, *, note: str = "") -> None:
    """Save one click on a planning-question card as `interview:<card id>` (issue #3).

    The click used to live only in the request file, which the next question archives, so an
    interview answer never reached the signed approval. Host-written, like approval picks."""
    value = str(resolved.get("response") if resolved.get("id") == "__custom_answer__"
                else resolved.get("label") or resolved.get("id") or "").strip()
    if not value:
        return
    answers = load_user_answers(project)
    answers[f"{INTERVIEW_NS}:{pending.get('id')}"] = {
        "value": value, "question": str(pending.get("title") or "")[:160],
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if note.strip() and resolved.get("id") != "__custom_answer__":
        answers[f"{INTERVIEW_NS}:{pending.get('id')}"]["note"] = note.strip()
    _save_answers(project, answers)


def _interview(answers: dict) -> dict:
    return {k: v for k, v in answers.items() if k.startswith(INTERVIEW_NS + ":") and isinstance(v, dict)}


def _interview_answer_text(answer: dict) -> str:
    return str(answer.get("value")) + (f" (your note: {answer['note']})" if answer.get("note") else "")


def settled_answers_block(project: Path) -> str:
    """Every interview answer, for each planning/intake turn. The chat replay keeps only the last
    20 messages, so early answers fell out of view and a replan could re-ask or override them."""
    try:
        answers = _interview(load_user_answers(project))
    except AnswersUnreadable as error:
        return (f"\n[ANSWERS THE USER ALREADY GAVE] The saved answers cannot be read ({error}). "
                "Tell the user; do not assume they answered nothing.\n")
    if not answers:
        return ""
    lines = [f"  {k} — {v.get('question') or '(question)'} → {_interview_answer_text(v)}"
             for k, v in answers.items()]
    return ("\n[ANSWERS THE USER ALREADY GAVE — SETTLED] The user answered these questions during "
            "this project. Treat each as decided: do not ask it again, and do not replace it with a "
            "KI example, worked-example period or your own default. If new evidence makes one of "
            "them unworkable, say why and ask about that one only. When a scientific_choice in your "
            "plan comes from one of these answers, set its `answered_by` to the listed id.\n"
            + "\n".join(lines) + "\n")


def cited_answers(plan: dict, answers: dict) -> dict[str, str]:
    """choice id → "question → answer" for each choice whose `answered_by` names a real interview
    answer. The plan is agent-writable: only the host store makes a citation count."""
    found = _interview(answers or {})
    out = {}
    for c in (plan or {}).get("scientific_choices") or []:
        rec = found.get(str(c.get("answered_by") or "")) if isinstance(c, dict) else None
        if rec and c.get("id"):
            out[str(c["id"])] = f"{rec.get('question') or '(question)'} → {_interview_answer_text(rec)}"
    return out


_USER_PROVIDES = {"user", "provide", "you"}    # the decision words flow.declared.classify reads


def _user_provides(item: dict) -> bool:
    return str(item.get("decision") or "").lower() in _USER_PROVIDES


def bind_uploads(project: Path, plan: dict, inv: dict) -> list[str]:
    """Issue #4: at the Approve click, name the files the user placed in inputs/user/<id>/ as that
    input (the folder the card's Upload button writes to). Their hashes go in the host answer store,
    so signing can tell this binding from local_paths the agent wrote. Mutates `inv`; returns
    "id → paths" for each input whose binding changed, so the caller re-issues the card."""
    project = Path(project)
    answers = load_user_answers(project)
    provide = {str(r["id"]) for r in input_groups(plan, inv, project)["you"] if r["how"] == "provide"}
    sha256_file = flowgate.load().receipts.sha256_file
    changed = []
    answers_changed = False
    for it in inv.get("items") or []:
        iid = str((it or {}).get("id") or "") if isinstance(it, dict) else ""
        key = f"upload:{iid}"
        if not iid or not (_user_provides(it) or iid in provide or key in answers):
            continue
        folder = project / "inputs" / "user" / iid
        try:
            upload_root = (project / "inputs" / "user").resolve()
            upload_root.relative_to(project.resolve())
            folder.resolve().relative_to(upload_root)
        except ValueError:
            raise OSError(f"The upload folder for {iid} is outside this project's inputs/user folder") from None
        files = sorted(p for p in folder.rglob("*") if p.is_file() and not p.name.startswith(".")) \
            if folder.is_dir() else []
        if not files:
            previous = answers.pop(key, None)
            if previous is not None:
                answers_changed = True
                if it.get("local_paths") == previous.get("paths"):
                    it["local_paths"] = []
                it["status"], it["needs_user"] = "missing", True
            continue
        for path in files:
            try:
                path.resolve().relative_to(folder.resolve())
            except ValueError:
                raise OSError(f"An uploaded file for {iid} points outside its input folder") from None
        paths = [p.relative_to(project).as_posix() for p in files]
        # ponytail: hashes every file on each Approve click; fine for tables and site files,
        # key on (size, mtime) first if multi-GB uploads become common
        digests = {rel: sha256_file(p) for rel, p in zip(paths, files)}
        if it.get("local_paths") == paths and (answers.get(key) or {}).get("sha256") == digests:
            continue
        it["local_paths"], it["status"] = paths, "ready"
        answers[key] = {"value": ", ".join(paths), "paths": paths, "sha256": digests,
                        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        changed.append(f"{iid} → {', '.join(paths)}")
    if changed or answers_changed:
        _save_answers(project, answers)
    return changed


def _save_answers(project: Path, answers: dict) -> None:
    p = _answers_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"schema": 1, "answers": answers}, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


# Fixed tags at the front of `rationale`: the disclosure splits on the tag, never on wording.
# (The shared record schema has no extra field; `rationale` is the one free slot it keeps.)
_KI_DEFAULT_TAG = "[ki_default]"
_SUGGESTION_TAG = "[suggestion_accepted]"
_KI_DEFAULT_WHY = f"{_KI_DEFAULT_TAG} KI protocol default (its dag.yaml / SKILL.md decides it)"
_SUGGESTION_WHY = f"{_SUGGESTION_TAG} planner recommendation shown on the card; accepted by approving the plan"
_LEGACY_SUGGESTION_WHY = "planner recommendation shown on the card; accepted by approving the plan"  # signed before the tag


def is_accepted_suggestion(rationale) -> bool:
    r = str(rationale or "")
    return r.startswith(_SUGGESTION_TAG) or r == _LEGACY_SUGGESTION_WHY


def decision_records(flow, plan: dict, inv: dict, answers: dict | None = None,
                     baseline: dict | None = None) -> tuple[dict, list]:
    """Who decided each thing the plan asked about — the web chat's schema (flow.decisions).

        user       the user answered it; taken ONLY from the host-written answer store
        ki_default the KI's protocol, or a planner recommendation the card showed and the user
                   accepted by approving; disclosed on every execution turn, never "their" choice
        open       nothing to fall back on — approving cannot answer it, so it must not start

    Ids are namespaced (`item:`, `choice:`, `question:`): desktop ids are free-form, and the
    shared schema reserves the bare names `site` and `period` for the web's scope records
    (a plain `period` choice would otherwise be unapprovable). Namespacing also keeps two
    same-named things in different namespaces from folding into one record.

    Returns (records, invalid); the caller refuses the approval while either blocks.
    """
    answers = answers or {}
    built: list[dict] = []
    invalid: list[str] = []
    seen: set[str] = set()
    # A value the card SHOWED and the user approved untouched was ACCEPTED, not decided by the
    # KI's protocol behind their back — say so. "Shown" is what the renderer shows: the data
    # rows `_data_choices` produces, with the value they pre-selected, and the high-impact
    # decisions (kimi gap-3 #5, codex G-4, B2 #2/#3).
    if baseline is None:
        baseline = suggestion_baseline(plan, inv)       # the approve path passes the ISSUED one
    _item_of = dict(baseline.get("item_of") or {})       # (codex review B3 #2): what the card
    _sugg = dict(baseline.get("suggested") or {})        # showed, not today's catalogue
    displayed_choice = {cid: _sugg.get(cid, "") for cid in _item_of}
    displayed_item = {item: _sugg.get(cid, "") for cid, item in _item_of.items()}
    displayed_decision = {cid for cid in _sugg if cid not in _item_of}   # rendered non-data choices

    def _add(ns: str, raw_id: str, source: str, value, why: str = "") -> None:
        iid = f"{ns}:{raw_id}"
        if iid.lower() in seen:
            invalid.append(f"{iid}: duplicate id in the plan — ids must be unique")
            return
        seen.add(iid.lower())
        built.append({"input_id": iid, "source": source, "value": value, "rationale": why or None})

    def _answer(ns: str, raw_id: str):
        rec = answers.get(f"{ns}:{raw_id}")          # its own namespace only — a choice id that
        return rec.get("value") if isinstance(rec, dict) else None   # happens to equal an item id

    for it in inv.get("items") or []:
        if not isinstance(it, dict):
            continue
        if not it.get("id"):
            invalid.append("an inventory item has no id")
            continue
        iid = str(it["id"])
        upload = answers.get(f"upload:{iid}")
        if isinstance(upload, dict) and upload.get("paths") and it.get("local_paths") == upload["paths"]:
            # bound by the host at the Approve click (bind_uploads), not merely named by the agent
            digests = ", ".join(str(d)[:12] for d in (upload.get("sha256") or {}).values())
            _add("item", iid, "user", str(upload["value"]),
                 f"your file in inputs/user/{iid} (sha256 {digests}), named on the card you approved")
            continue
        # Only a current host binding can satisfy "you provide". A path/source string
        # written by the agent is not evidence that the required upload exists.
        if _user_provides(it):
            _add("item", iid, "open", f"upload it to inputs/user/{iid}/")
            continue
        decision = it.get("decision")
        concrete = (it.get("dataset_id") or it.get("chosen_source") or decision
                    or (", ".join(str(p) for p in it.get("local_paths") or []) or None))
        answered = _answer("item", iid)
        if answered and str(answered) != str(concrete or ""):
            answered = None     # a replan re-pinned it: the saved answer is not what will run
        if answered:
            _add("item", iid, "user", answered, "you chose this on the approval card")
        elif it.get("needs_user") and not concrete:
            _add("item", iid, "open", f"{it.get('category') or 'input'} still needs your decision")
        elif concrete:
            why = _SUGGESTION_WHY if displayed_item.get(iid) == str(concrete) else _KI_DEFAULT_WHY
            _add("item", iid, "ki_default", str(concrete), why)
        else:
            kd = it.get("ki_default") or {}
            _add("item", iid, "ki_default",
                 str(kd.get("default_source") or kd.get("source_kind") or it.get("strategy")
                     or "the KI prepares it per its SKILL.md"), _KI_DEFAULT_WHY)

    interview = cited_answers(plan, answers)     # `answered_by` counts only if the host saved it
    for c in plan.get("scientific_choices") or []:
        if not isinstance(c, dict):
            continue
        if not c.get("id"):
            invalid.append("a scientific choice has no id")
            continue
        cid = str(c["id"])
        answered = _answer("choice", cid)
        if answered and str(answered) != str(c.get("decision") or c.get("picked") or ""):
            answered = None     # the plan moved on since the user answered (review A #3)
        if answered and c.get("kind") == "data_source":
            bound = (answers.get(f"choice:{cid}") or {}).get("item")
            now = str(c.get("item") or cid.replace("data:", "", 1))
            if bound and str(bound) != now:
                answered = None     # answered for another item; the id was rebound (review A5 #1)
        if answered:
            _add("choice", cid, "user", answered, "you chose this on the approval card")
        elif cid in interview and (c.get("decision") or c.get("picked")):
            _add("choice", cid, "user", str(c.get("decision") or c.get("picked")),
                 "you answered this in the interview: " + interview[cid])
        elif c.get("decision"):
            if c.get("kind") == "data_source":
                shown_val = displayed_choice.get(cid)
            else:
                shown_val = _sugg.get(cid) if cid in displayed_decision else None
            why = _SUGGESTION_WHY if shown_val is not None and shown_val == str(c["decision"]) else _KI_DEFAULT_WHY
            _add("choice", cid, "ki_default", str(c["decision"]), why)
        elif c.get("picked"):
            # a suggestion with no decision: accepted only if the card actually rendered it
            # (codex review B3 #1); otherwise the plan carried it and the user never saw it
            shown_val = displayed_choice.get(cid) if c.get("kind") == "data_source" \
                else (_sugg.get(cid) if cid in displayed_decision else None)
            accepted = shown_val is not None and shown_val == str(c["picked"])   # value, not row (B5 #2)
            _add("choice", cid, "ki_default", str(c["picked"]), _SUGGESTION_WHY if accepted else _KI_DEFAULT_WHY)
        elif c.get("high_impact"):
            opts = ", ".join(str(o) for o in (c.get("options") or [])[:6])
            _add("choice", cid, "open", f"{c.get('kind') or 'choice'}: {opts or 'needs your decision'}")

    # The planner saying "this is unresolved" is exactly an open input (Design B parity): the
    # card already lists these under "Waiting on you", so approval must not run past them.
    for n, q in enumerate(plan.get("unresolved_questions") or [], 1):
        if str(q or "").strip():
            _add("question", str(n), "open", str(q)[:300])

    invalid += [f"{r['input_id']}: {why}" for r in built
                for ok, why in [flow.decisions.validate_record(r)] if not ok]
    return flow.decisions.fold_payloads(built), invalid


def display_input_id(iid: str) -> str:
    """`item:forcing` → `forcing` for anything a person reads."""
    return str(iid).split(":", 1)[1] if ":" in str(iid) else str(iid)


def _card(flow, fs, plan: dict, inv: dict, provider_note: str) -> dict:
    """The PLAN_REVIEW card, in the shape setup.request_user renders (issue §UI)."""
    can = [f"prepare inputs for {k}" for k in plan.get("selected_kis") or []]
    edges = [c.get("edge_id") for c in plan.get("coupling") or [] if c.get("edge_id")]
    if edges:
        can.append("couple: " + ", ".join(edges))
    decide = [f"{c.get('kind')}: {', '.join(map(str, c.get('options') or []))} (suggested {c.get('picked')})"
              for c in plan.get("scientific_choices") or [] if c.get("high_impact") and not c.get("decision")]
    msg = (f"What I understood\n  {plan.get('goal')}\n\n"
           f"GeoForge can do itself\n  " + ("\n  ".join("✓ " + c for c in can) or "—") + "\n\n"
           + _data_summary(plan, inv, fs.project) + "\n\n"
           + ("You decide\n  " + "\n  ".join(decide) + "\n\n" if decide else "")
           + f"Steps: {len(plan.get('steps') or [])}   Tool policy: {provider_note}\n"
           f"Details: runs/plan.json, runs/data-inventory.json")
    intent = plan.get("intent") if isinstance(plan.get("intent"), dict) else {}
    steps = []
    for st in plan.get("steps") or []:
        if not isinstance(st, dict):
            continue
        tool = str(st.get("tool") or "")
        steps.append({"id": st.get("id"), "kind": st.get("kind"), "ki": st.get("ki"),
                      "tool": Path(tool).name if tool else None,
                      "env": sorted((st.get("env") or {}).keys()),
                      "inputs": list(st.get("inputs") or []), "outputs": list(st.get("outputs") or [])})
    try:
        cited = cited_answers(plan, load_user_answers(fs.project))
    except AnswersUnreadable:
        cited = {}      # the Approve click refuses an unreadable store; the card just omits citations
    decisions = [{"id": c.get("id"), "kind": c.get("kind"), "options": list(c.get("options") or []),
                  "picked": c.get("decision") or c.get("picked"), "decided": bool(c.get("decision")),
                  "high_impact": bool(c.get("high_impact")), "answered": cited.get(str(c.get("id")))}
                 for c in plan.get("scientific_choices") or [] if isinstance(c, dict)
                 and c.get("kind") != "data_source"]
    # DB gating: no cached Database records on the card while access is off or not activated
    data_choices = [] if fs.database_access_mode == "off" else _data_choices(plan, inv, fs.project)
    review = {"goal": plan.get("goal"), "kis": list(plan.get("selected_kis") or []),
              "coupling": edges, "study_area": intent.get("study_area"), "period": intent.get("period"),
              "data": input_groups(plan, inv, fs.project), "steps": steps, "decisions": decisions,
              "data_choices": data_choices,
              "tool_policy": provider_note, "blockers": [], "not_ready": []}
    return {
        "id": APPROVAL_REQUEST_ID_PREFIX + fs.flow.plan.sha256(plan)[:10] + "-" + fs.flow.plan.sha256(inv)[:6],
        "plan_review": review,
        "kind": "choice", "title": "Approve the plan?", "message": msg, "allow_note": True,
        "options": [
            {"id": "approve", "label": "Approve and start",
             "description": "Execution starts in a fresh session with the approved plan; every run and download gets a receipt.",
             "response": "Approved. Start the execution."},
            {"id": "modify", "label": "Modify the plan",
             "description": "Tell me what to change in the note; I will revise the plan and ask again.",
             "response": "Please revise the plan."},
        ],
    }


def issue(project: Path, fs, pj: dict, inv: dict, provider_note: str, *,
                turn_id: str = "", extra_why: list[str] | None = None) -> dict:
    """Show the one approval card for exactly this plan/inventory pair (WAITING_FOR_USER).

    There is no automatic approval: the card is the contract between the user and the run.
    Also used when the Approve click finds that a clip estimate changed."""
    from . import obs_access
    flow = fs.flow
    project = Path(project)
    # The approval UI is bound to exactly the reviewed pair, not just a plan filename.
    receipt = {"plan_sha256": flow.plan.sha256(pj), "inventory_sha256": flow.plan.sha256(inv),
               "turn": turn_id, "submitted_at": time.time()}
    _ok, why = flow.approval.may_auto_approve(pj, inv)
    # `may_auto_approve` answers "could this be approved with no user at all"; the desktop always
    # asks the user, and approving ACCEPTS a shown recommendation. Saying "undecided" about a
    # choice the click will accept made the card contradict the approval rule (kimi review #6).
    _suggested = {str(c.get("id")) for c in pj.get("scientific_choices") or []
                  if isinstance(c, dict) and c.get("picked") and not c.get("decision")}
    why = [w for w in why if not any(f"{cid!r}" in str(w) for cid in _suggested)]
    for c in pj.get("scientific_choices") or []:
        if isinstance(c, dict) and str(c.get("id")) in _suggested and c.get("high_impact"):
            why.append(f"{c.get('kind') or 'choice'} {c.get('id')}: defaults to "
                       f"{c.get('picked')} unless you pick another")
    why = list(extra_why or []) + list(why)
    manual = [it for it in inv.get("items") or []
              if isinstance(it, dict) and it.get("delivery") == "manual"]
    if manual:
        why.append("manual download needed: " + ", ".join(
            f"{it.get('dataset_id') or it.get('id')}"
            + (f" ({obs_access.size_label((it.get('catalogue') or {}).get('size'))})"
               if (it.get('catalogue') or {}).get('size') else "")
            for it in manual[:6]))
    ready = flow.plan.validate(pj, inv, list(fs.ki_roots), fs.ki_roots, for_execution=True)
    card = _card(flow, fs, pj, inv, provider_note)
    if why:
        card["message"] += "\n\nWaiting on you\n  " + "\n  ".join(why[:8])
        card["plan_review"]["blockers"] = list(why[:8])
    if ready:
        card["message"] += "\n\nNot ready to execute yet\n  " + "\n  ".join(ready[:6])
        card["plan_review"]["not_ready"] = list(ready[:6])
    doc = setup_flow.request_user(project, card)
    doc["id"] = card["id"]
    doc["plan_review"] = card["plan_review"]
    # Everything the card SHOWS is part of the contract: the request file the UI renders is
    # agent-writable, so the host keeps its own hash of the whole rendered card (title, message,
    # plan review, the action buttons) under runs/ and refuses a click on a card that no longer
    # matches it (codex review B #1, B2 #1).
    receipt["shown_sha256"] = shown_sha256(doc)
    receipt["baseline"] = suggestion_baseline(pj, inv, rows=card["plan_review"].get("data_choices"))
    # ^ what was shown, as values, from the SAME rendered rows — not a second catalogue read
    #   that could disagree with the card (kimi B2 #2, codex B4 #4)
    (project / "runs" / "plan-review.json").write_text(json.dumps(receipt), encoding="utf-8")
    doc["review"] = receipt
    (project / setup_flow.REQUEST_FILE).write_text(json.dumps(doc, indent=2), encoding="utf-8")
    if fs.state is not flow.states.State.WAITING_FOR_USER:
        fs.move("needs_user")
    projectrun.report(project, {"status": "waiting_for_user", "summary": card["title"], "blocker": doc},
                      source="flow")
    return doc


_SHOWN_KEYS = ("title", "message", "plan_review", "options", "allow_note")   # what the UI renders


def shown_sha256(doc: dict) -> str:
    """Hash of everything the approval card shows the user — title, message, the whole plan
    review (goal, data groups, data choices with their options, steps, decisions, blockers,
    tool policy) and the action buttons (id, label, description, response). The Approve click
    is valid only for a card that still shows exactly this (codex review B2 #1)."""
    shown = _json_canon({k: (doc or {}).get(k) for k in _SHOWN_KEYS})
    return hashlib.sha256(json.dumps(shown, sort_keys=True, ensure_ascii=False, default=str)
                          .encode("utf-8", "surrogatepass")).hexdigest()   # lone surrogates hash, not raise (B6 #2)


def _json_canon(v):
    """Hash what survives a JavaScript JSON round trip, so an unchanged card is never rejected
    (codex review B5 #1, B6 #1): every number becomes a double, as JSON.parse makes it (ints past
    2**53 lose precision the same way), and an integral double below 1e21 prints as an integer,
    as JSON.stringify prints it."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        d = float(v)
        if d != d or d in (float("inf"), float("-inf")):
            return str(v)
        return int(d) if d.is_integer() and abs(d) < 1e21 else d
    if isinstance(v, dict):
        return {str(k): _json_canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_canon(x) for x in v]
    return v


def _issued_review(project: Path, pending: dict | None) -> dict:
    """The host's own record of the card it issued (runs/plan-review.json). The copy inside the
    request file is never consulted: it is agent-writable, and any marker that would tell a
    legacy card from a tampered one is writable too (codex review B3 #3). A missing or unreadable
    record voids the click, and the card is re-issued — one extra click, once, for cards issued
    before the record existed."""
    path = Path(project) / "runs" / "plan-review.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, dict) or not doc.get("plan_sha256") or not doc.get("shown_sha256"):
        return {}          # a record without the card hash (issued before batch B) cannot verify
    bl = doc.get("baseline")   # a click: void, re-issue (codex review B4 #2)
    if not isinstance(bl, dict) or not all(isinstance(bl.get(k), dict) for k in ("suggested", "item_of", "options")):
        return {}          # a malformed or missing snapshot voids too, before anything is cleared (B5 #3)
    if (not all(isinstance(x, str) for x in bl["suggested"].values())
            or not all(isinstance(x, str) for x in bl["item_of"].values())
            or not all(isinstance(x, list) and all(isinstance(o, str) for o in x) for x in bl["options"].values())):
        return {}          # contents too, so the approve path never raises after clearing the card (B6 #3)
    return doc
