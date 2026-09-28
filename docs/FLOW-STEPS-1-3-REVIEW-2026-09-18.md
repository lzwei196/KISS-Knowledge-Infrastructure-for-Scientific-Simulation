# Review of FLOW-TARGET steps 1–3 (independent, from code, 2026-09-18)

Read: `FLOW-TARGET-2026-09-17.md`, `FLOW-TARGET-REVIEW-2026-09-17.md`, `FLOW-AS-IS-2026-09-16.md`, then
`ki_tools_common/flow/{states,policy,receipts,approval}.py`, `kiss_cli/{acquire,flowrun,obs_subset,obs_access,
api,flowgate,gui,setup,cli,projectrun}.py`, `web/app.html`, and the tests. Suites: `kiss/tests` 502 passed
(1 skipped, 4 deselected); `ki_tools_common/tests/flow` 79 passed. Line numbers are from the uncommitted
`mac-version` tree. No code was modified; two scratch scripts were run to confirm B-1 and B-3.

## Verdict

The state machine, the pre-signing re-estimate, the hash-based join and the host-driven pass are implemented
as designed and B1/B2/B4 hold: nothing writes the plan files after the signature, every route to EXECUTING
passes through ACQUIRING, and the agent has no tool that downloads. The manual (Baidu) path, however, does not
work with the real client: the destination check added to `Client.download` fires before the "manual" answer,
and the GUI crashes on the "Files are in place" message, so B3 is satisfied only under the test's fake client.
Fix the three blocking items (all small), then this is mergeable; the should-fix list is real but not urgent.

## Blocking issues

### B-1. Manual datasets can never be receipted with the real client

**What.** Once the user places the files, the next acquisition pass marks the item `failed` instead of signing it.

**Why.** `acquire.run` asks the server for the handoff info on every pass
(`kiss/kiss_cli/acquire.py:229`) and only then checks the placed files (`:231`). The new early check in
`Client.download` (`kiss/kiss_cli/obs_access.py:402-409`) raises `destination_not_empty` as soon as
`inputs/observations/<id>/` holds a file, which is before the `served: False` branch (`:424-427`) can return.
The `ObsAccessError` is caught at `acquire.py:237-238` → `status="failed"` → overall `failed` →
`acquisition_failed` → BLOCKED. Retry repeats it. `_placed_receipt` (`acquire.py:142-155`) is unreachable in
production. Confirmed with a scratch call: real `Client.download("large-1", project)` with one placed file
raises `destination_not_empty` without touching the network. The test
`test_manual_catalogue_credentials_go_to_private_card_and_placed_files_get_a_receipt`
(`kiss/tests/test_flowgate.py:159-164`) passes only because its `FakeClient.download` skips that check.

**Same root cause, second symptom.** A served item whose folder is populated but has no valid receipt (extract
succeeded, `record_download` failed; or a legacy agent download whose receipt cannot be rebound) is also
permanently `failed`: `_served` (`acquire.py:112-117`) has no branch for `destination_not_empty`.

**Minimal fix.** In `acquire.run` manual branch: build the row from the item alone, call `_placed_receipt`
first, and only when it returns `None` ask the server for link/code. In `_served`: catch
`ObsAccessError.code == "destination_not_empty"` and surface an actionable message ("folder X holds files with
no receipt; move them away or Modify") instead of the raw error. Add a test that runs `acquire.run` twice
against the real `Client.download` with `_request` stubbed.

### B-2. "Files are in place" crashes the chat handler (`NameError: waiting`)

**What.** Any message sent while a no-options request card is waiting (the new `flow-manual-download` card, the
legacy single download card) raises before `flowrun.pre()` runs.

**Why.** `kiss/kiss_cli/gui.py:3230` reads `waiting.get("kind")`, but `waiting` is not defined anywhere in
`_stream_session_chat` (pyflakes: `undefined name 'waiting'` twice; the only assignments are in other methods
at `:2507` and `:3447`). The manual card is not diverted to `flow_pending` (`:3166-3170` covers only the
approval and blocked ids), has `options == []` (`acquire.py:171-179` passes none), so the branch
`elif not options:` at `:3224` is taken on every message. The "Files are in place, continue" button sends a plain
text message with no `action` (`web/app.html:1722-1728`), so it lands exactly here. The line predates this
work (blame 2026-09-13), but step 3 makes it the only way to leave ACQUIRING with a manual dataset.

**Minimal fix.** `waiting` → `pending` on `gui.py:3230`. Add a GUI-level test that posts a chat message while a
`kind: download` card without options is pending.

### B-3. Stale entries in `.geoforge/acquisition.json` poison every later pass

**What.** After BLOCKED → Modify → replan that renames or drops the failed item, the re-approved plan is
BLOCKED again with the old error, forever.

**Why.** `acquire.run` loads the previous file and keeps its `items` (`acquire.py:198-200`); nothing prunes ids
that are no longer in `needed(plan, inventory)` and nothing resets on a new `approval_sha256`. The verdict is
computed over all entries (`:240-248`), so one stale `failed` (or `waiting`) entry decides the overall status.
Confirmed with a scratch run: a file holding `{"forcing": {"status": "failed"}}` under an old approval plus an
empty inventory under a new approval returns `failed`. "Modify" is the designed recovery for a fetch failure,
and modifying usually means changing that very item, so the recovery path is the trigger.

**Minimal fix.** In `run()`, after `needed = needed(plan, inventory)`, keep only
`items = {k: v for k, v in items.items() if k in {str(i["id"]) for i in needed}}` (or discard `items` when
`doc.get("approval_sha256") != approval`). One test: failed entry, replan drops the item, next pass is `done`.

## Should-fix (real bugs, not constraint violations)

1. **Re-issued approval card cannot be opened again.** `_issue_card` derives the id from the plan hash only
   (`flowrun.py:975`), so the card re-issued at Approve because a clip grew has the same id; the browser's
   `SEEN_ACTIONS` key is `${sid}:${request.id}` (`app.html:1030-1031`), so the modal never reopens, and the
   Project-status "One thing needs you" card renders no button for `kind: choice` (`app.html:1459-1464`). The
   chat says "The updated card is in the chat" (`flowrun.py:293`) but nothing is clickable until a page reload.
   Smallest fix: key on `request.id + created_at` in `maybeShowAction`, and add a "Respond" button in the
   human-request card that calls `showActionPicker(request, CUR.id)`. Same fix answers the dismissed-card
   problem noted in the progress notes.
2. **Two acquisition passes can run at once.** `poll_acquisition` is called from the `/data` route without the
   session lock (`gui.py:1109-1116`, `:1690-1698`; `ThreadingHTTPServer` at `:4274`), while `pre()` runs under
   `sessions.lock(sid)`. `_ACQ_POLL_LOCK` guards only the timestamp (`flowrun.py:477-481`). Two overlapping
   passes: both `Client.download` the same served item, the second fails in `_extract_zip`
   (`destination_exists`) → BLOCKED although the data is there; two in-memory `ctx` objects each `move()` from
   ACQUIRING and the last `save()` wins, so BLOCKED can overwrite EXECUTING. Receipts and jobs are safe
   (receipt file per item id, `approve()` idempotent under `_lock`). Fix: one `threading.Lock` per project
   around `acquire_then_continue`; the poll uses `acquire(blocking=False)` and returns `None` if busy.
3. **One transient estimate failure at Approve is permanent.** `refresh_estimate` returns early for any
   non-pending state (`obs_subset.py:234-235`), and `_estimate_attempt` on failure sets `estimate_failed`
   (`:462-469`). So: server hiccup at the Approve click → `changed_since_review` reports the error (`:247-248`)
   → card re-issued → every later Approve click short-circuits on the failed state and re-issues again. The only
   exit is Modify. Also `pre()` discards the `stamp_inventory` return value (`flowrun.py:285`) and writes the
   inventory anyway. Fix: let `refresh_estimate` retry `estimate_failed` states (as `retry_estimate` does) and
   treat stamp errors at Approve like a changed estimate (say so on the card).
4. **Baidu link and code sit in an agent-readable file.** `setup-request.json` and every archived
   `setup-request-<ts>.json` (`setup.py:273-283`) live at the project root; `read_project_file` /
   `list_project_files` have no exclusion (`api.py:949-969`). The N-row card writes url and code into `rows` and
   into `message` (`acquire.py:164-182`). Pre-existing (recommendation 7 of the design review was not adopted),
   but the constraint text is "only the request card the user reads". Fix: exclude `setup-request*.json` from the
   two read tools, or move flow cards under `.geoforge/requests/`.
5. **Flow cards clobber any other waiting request.** `_manual_card` (`acquire.py:182`) and
   `_acquisition_card` (`flowrun.py:421`) overwrite `setup-request.json` unconditionally. In the legacy
   EXECUTING convergence path (`flowrun.py:646-657`) that can replace a pending agent `request_user_action`
   card. Fix: skip writing when a different waiting card exists, and report it in the pass result.
6. **`rows[].url` is not validated.** `request_user` accepts only `http(s)` for the top-level url
   (`setup.py:113-115`) but the rows are written raw (`acquire.py:180-182`) and rendered as `href`
   (`app.html:1458`). A hostile or compromised server answer with `javascript:` in `baidu_url` becomes a link
   in the webview. Fix: apply the same scheme check in `_manual_row`.
7. **`_placed_receipt` and `data_path_present` disagree.** The receipt scan skips `.part/.partial/.crdownload/.tmp`
   (`acquire.py:147-148`) while the presence check also skips `.download/.aria2/.bc!` and refuses symlinks
   (`setup.py:233-238`). A Baidu client's `.bc!` partial, or a symlink to a file outside the project, gets hashed
   into a signed receipt (the latter is then rejected by `_inside` on every check and re-signed every pass).
   Fix: share one suffix tuple and skip `is_symlink()`.
8. **Items already on disk are downloaded again.** `needed()` (`acquire.py:29-39`) keeps every consumed item
   with `delivery in ACQUIRABLE` regardless of `status == "ready"` / `local_paths`. If the local copy sits at the
   default destination, B-1's `destination_not_empty` blocks the plan; elsewhere, it is fetched twice.
9. **Legacy EXECUTING sessions with placed manual files never converge.** Same mechanics as B-1 but in
   `turn()` (`flowrun.py:646-657`): `[DATA STATUS] ... failed (destination_not_empty)` on every turn, the agent is
   told not to fetch, and nothing offers the user a way out.
10. **A subset job whose folder exists is unrecoverable.** `download()` refuses an existing target
    (`obs_subset.py:632-633`); after the "recording failed" branch (`:683-687`) leaves the folder in place,
    every Retry hits the same `ValueError`. Fix: on `downloaded`-folder-present with a valid
    `acquisition_receipt`, re-verify and rebind instead of refusing.
11. **`provider_note` is lost on the re-issued card.** `pre()` passes `""` (`flowrun.py:291`) so the card reads
    "Tool policy: " (`:954`). Read it back from `pending["plan_review"]["tool_policy"]`.
12. **`(ACQUIRING, "cancel")` is dead.** Defined at `states.py:133`, never fired. The only cancel is the panel
    route (`gui.py:1960` → `obs_subset.cancel`), which turns the next pass into `failed` → BLOCKED, without
    revoking the approval. Either wire a Cancel option into the acquiring message/card or delete the move.
13. **B4 only partly done.** `.geoforge/data-binding-status.json` is still written (`obs_subset.py:385`,
    `flowrun.py:309-312`) and read into Project status (`flowrun.py:886`, `app.html:1476`);
    `runs/inventory-updates.jsonl` is still written (`obs_subset.py:379`, `flowgate.py:342,439`) and read by
    nobody. `plan_data_status` reads four sources, not three.
14. **Whole-file clip vs. a `variable` requirement.** An estimate with `variables: []` (raster, selection
    unsupported) never matches an item that states `variable: "prec"` (`obs_subset.py:149-157`), and
    `stamp_item` then raises "Acquisition variable differs" (`:209-211`). The agent must delete the requirement
    to bind. Treat an empty request variable list as covering any requirement.
15. **`poll_acquisition(project, setup_ok=True)` default** (`flowrun.py:466`) fakes `setup_verified` evidence
    for any caller that forgets the argument. Make it required.

## Nits

- Dead code: `cmd_obs_download` (`cli.py:431-460`), the `download_observation_data` schema and handler
  (`api.py:641-657`, `:1262-1299`), `flowgate.fetch_observation` (`flowgate.py:348-454`, now always denied by
  `check_tool`), `"search_observation_data"` in `_BASE_API` and `DATABASE_API_TOOLS` (`policy.py:44-49`; no schema
  carries that name any more), the `off`-mode `hidden.add("download_observation_data")` (`flowgate.py:139-140`).
- `acquire._served` and `flowgate.fetch_observation` are the same twenty lines; delete the latter.
- `_manual_card` dedupes on item ids only (`acquire.py:161-163`); a changed code or path keeps the old card.
- `match_item` binds a single distinct candidate silently when the item has no requirements at all
  (`obs_subset.py:190-192`); the card shows bytes and parts but not the bbox/period that were bound
  (`flowrun.py:922-929`). Show them, or require `bbox` on subset items.
- Two items naming one estimate are not rejected (recommendation 2). It works (`approve()` is idempotent,
  `bind_approved` signs one receipt per item), so this is a documentation gap, not a bug.
- `download()` still fsyncs per 1 MB chunk (`obs_subset.py:653`; design review Q10).
- `_LOCKS` dicts never shrink (`obs_subset.py:26`, `flowrun.py:461`).
- Every new user-facing string in `flowrun._acquisition_message`, `_acquisition_card`, `acquire._manual_card`
  and the `set_stage` texts is English only; `app.html` localises only the chrome around them.
- `[DATA STATUS]` in execution turns (`flowrun.py:654-657`) is good; it should also name the step ids that
  consume the unfinished items so the agent can skip exactly those.
- `pre()` branch 1c treats any BLOCKED as acquisition-blocked (`flowrun.py:338-343`); `plan_missing` is unused
  today, so this is latent.
- `pre()` line 296-298 signs only when `check() != "OK"`; that is right for the rerun path but reads as if a
  stale OK approval could be inherited by a fresh card. A one-line comment would help.

## Answers to the 14 questions

1. **B1.** No re-estimate or inventory write after signing. Writers of `runs/data-inventory.json`:
   `after()` PLANNING (`flowrun.py:1100`), `turn()` first draft (`:586`), `flowgate.write_plan` (`:290`, gated to
   PLANNING/REPLAN_REQUIRED by `api_tools`), and `pre()` approve **before** `approval.approve`
   (`:283-286` then `:295-298`). `stamp_item` writes `catalogue.size`, `acquisition_offer` and
   `estimate_summary` (`obs_subset.py:216-226`); at Approve the inventory is rewritten only when
   `changed_since_review` is non-empty (`flowrun.py:284`), so a benign re-estimate leaves the hash intact even
   though the subset state file now holds slightly different bytes. `bind_approved` stamps a deep copy
   (`obs_subset.py:355`). No host path produces DRIFT; `evidence.json`, `inventory-updates.jsonl`,
   `acquisition.json` and the subset files are outside the hash (`approval.py:132-140`).
2. **B2.** `_MOVES` at `states.py:131-135` match the review table. Every route to EXECUTING goes through
   `_start_execution` → `acquire` (`flowrun.py:503-508`): approve click (`:314`), FAILED/FAILED_VALIDATION rerun
   (`:351-353`), `setup_verified()` (`:1346`), and a replan re-enters via the approve click. `SETUP_VERIFIED →
   resume → APPROVED` then runs a second pass which is a no-op when receipts exist. No double move: each caller
   loads one `ctx` and `acquire_then_continue` moves once per outcome. Restart: `acquire.run` is idempotent for
   served (receipt found or rebound before any download), subset (`advance_approved` → `download()` on
   `downloaded` re-verifies and rebinds), manual (re-signs what is there) — subject to B-1 and should-fix 10.
   Concurrency: yes, two passes can overlap (should-fix 2); double receipts are harmless (one file per item id),
   double jobs are prevented by `approve()`'s `job_id` check, a double manual card is byte-identical, but a
   second served download fails on `destination_exists` and the two `ctx.save()` calls race.
3. **B3.** The receipt holds `source="manual placement (Baidu Pan)"`, `request_url=""`, paths and hashes
   (`acquire.py:151-154`); `acquisition.json` entries carry only `expected_path` (`:225,236`);
   `_acquisition_message` prints paths and "the link and code are in Project status" (`flowrun.py:491-495`);
   `after()`'s EXECUTING reminder prints title and expected path (`:1131-1138`); `projectrun.report` is not
   called for the manual card. The link and code exist in `setup-request.json` rows/message and its archives
   (should-fix 4). Robustness: `.part`-style files are skipped but the list is shorter than
   `data_path_present`'s, symlinks are followed, empty dirs and nested dirs are handled
   (should-fix 7). `evidence()` reaches COMPLETED with a placed dataset: the test at
   `test_flowgate.py:185-186` shows no unreceipted artifact under the manual folder — but only with the fake
   client (B-1).
4. **B4.** No writer outside PLANNING/REPLAN_REQUIRED/`after()`/`pre()`-before-signing (see 1).
   `inventory-updates.jsonl`: written at `obs_subset.py:379`, `flowgate.py:342,439`; zero readers; dead.
   `data-binding-status.json`: written at `obs_subset.py:385`, `flowrun.py:309`; read at `flowrun.py:886` and
   rendered at `app.html:1476`; alive. `data-proposal.json`: no references remain.
5. **Host join.** bbox: both sides go through `_bbox`/`float` (`obs_subset.py:77,137-140`), so equal JSON numbers
   compare equal; different precision falls through to the single-candidate rule and is then caught by
   `stamp_item`'s per-key check (`:209-211`), which names the offending key. Variables: `variable_terms`
   (sorted, casefolded) on both sides (`:145,154`, `obs_access.py:719-731`); empty request list vs. named
   requirement is a false mismatch (should-fix 14). start/end: same `_iso` on both sides. Single candidate:
   binds silently only when the item has no requirements at all (`:186-192`); with any requirement the
   mismatch is caught. Explicit id with stale hash: looked up among pending candidates by hash, else an error
   naming the situation (`:173-179`); a missing state file surfaces as an `[Errno 2]` string (nit). Two items →
   one estimate: not rejected anywhere; works. `delivery: subset` with no candidates: `stamp_inventory`
   routes it to `stamp_item` (`obs_access.py:1170-1177`) → "no clip estimate on file … call estimate_clip"
   → planning repair.
6. **Re-estimate.** Missing `estimate_summary` (legacy card): all comparisons are skipped, only blockers
   count (`obs_subset.py:249-258`), so it is treated as unchanged; acceptable because `after()` always stamps
   a summary before a card is issued now. Smaller is unchanged by design (+10 % / 16 MB one-sided). Failed
   refresh: reported as changed, card re-issued, but never retried (should-fix 3). Re-issued card: KI roots
   are rebuilt from `catalog` and `ctx.selected_kis` (`flowrun.py:287-289`), `fs.state` is already
   WAITING_FOR_USER so no second `needs_user` move; `provider_note` is lost (should-fix 11); the same card id
   means the modal does not reopen (should-fix 1). Loop: bounded by user clicks, never signs automatically.
7. **Turn-ending rule.** `_handoff_made` (`api.py:1974-1988`): `write_plan` only on "Plan files written",
   `request_user_action` always, `report_project_progress` only with `selected_kis` and
   `ready_for_planning=True` with empty `missing` — consistent with `promote_auto_choice`
   (`flowrun.py:1503`). A side question in PLANNING is nudged, and `after()` then starts a repair round anyway;
   consistent with the design ("planning turns end with a tool call") but each such question costs a nudge
   plus a repair replay. Independent of `text_tool_retries` (checked first, `:2074-2095`); worst case is one
   text-tool retry + one nudge + one transport retry. Transport retry `continue`s before anything is appended
   to `messages` (`:2065-2070`); `_anthropic_turn`/`_openai_turn` raise before returning, so no partial state.
   Cost bound: two provider calls of up to `TIMEOUT` each.
8. **`advance_approved`.** Not a consent violation: the job is created only when
   `approval.check == OK` and the approved inventory names the id (`obs_subset.py:389-409`), which is the
   design's consent. Agent reachability: `fetch_observation` → `check_tool("download_observation_data")`
   (`flowgate.py:398`) is denied in every state since the tool left `API_TOOLS_BY_STATE`; the CLI
   `obs-download` goes through the same method (`cli.py:439`); the panel routes expose only
   `refresh/download/cancel/retry_estimate/estimate` (`gui.py:1960`). Closed.
9. **`_rebind_existing`.** Safe: it only re-signs file sets that already hash-match a *signed* receipt
   (`acquire.py:75-89`, `_read_all` verifies signatures); an agent-written file cannot match unless byte-identical
   to something already receipted. The marker `/<safe id>/` with both slashes does not match `hwsd` against
   `hwsd_china` (`:74,79`); `_safe_component` maps `/` to `_` so ids that differ only in punctuation could collide
   (theoretical). `rebound_extracted_files` as `transform_tool`: acceptable — the extracted files were hashed
   in the original receipt's `processed_files`, so the chain of custody is intact; it is recorded, not hidden.
10. **Early destination check.** No legitimate new-flow caller relies on a non-empty destination: `_served`
    never passes `destination`, and `CHILD_ID` children default to their own folder
    (`obs_access.py:255-266`); `_extract_zip` already refused non-empty targets (`:270-273`). The regression
    is the manual branch ordering (B-1) and the retry-after-partial case.
11. **GUI.** Routing of `flow-acquisition-blocked` and `flow-approve-*` to `pre()` is consistent
    (`gui.py:3166-3170`). The manual card is meant to go through the generic handler
    (`download_placed` → `resume`) and then `pre()` ACQUIRING re-runs the pass — consistent in design, broken
    by B-2. `SEEN_ACTIONS`: confirmed (should-fix 1); smallest fix is keying on `id + created_at` and adding a
    "Respond" button to the human-request card. XSS: every row field goes through `esc()`
    (`app.html:1458`); the href scheme is not validated (should-fix 6).
12. **Legacy sessions.** EXECUTING with unreceipted served items: `_receipt_for` fails (no
    `selection_sha256`), `_rebind_existing` re-signs from the old receipt or its extracted files — converges.
    Subset items: `advance_approved` → `bind_approved` writes a new receipt with a selection — converges.
    Manual items with placed files: B-1 → `failed` every turn (should-fix 9). Old single-row pending
    `download` card: `plan_data_status` still recognises it by title suffix (`flowrun.py:847-848`) and
    `after()` still reminds (`:1131-1138`); the next pass replaces it with the N-row card. Note that the
    tightened `evidence()` (`receipts.py:581-590`) no longer binds any receipt lacking `selection_sha256`, so
    legacy receipts count only after the convergence pass re-signs them.
13. **Untested.** `acquire.run` against the real `Client.download` (would have caught B-1); GUI message with a
    no-options card pending (B-2); stale `acquisition.json` after a replan (B-3); `poll_acquisition` rate limit
    and `setup_ok=False` → SETUP_REQUIRED; concurrent passes; `_manual_card` dedupe and clobbering; the re-issued
    approval card's id/`provider_note`; `changed_since_review` with a failed refresh at Approve, then a second
    click; `plan_data_status` rows for `failed`, `waiting_for_you` (N-row) and `acquired`; the intake estimate cap
    reset on a new turn; `presentation()` after `cancel`; `_placed_receipt` with `.bc!`, symlink, nested dirs;
    `needed()` with a `ready` item; `_rebind_existing` with two datasets sharing a prefix.
14. **Other.** Dead code list in Nits; the `_served`/`fetch_observation` duplication; `[DATA STATUS]` lacks
    step ids; i18n gaps; the `cancel` move; B4 leftovers; `poll_acquisition` default.

## Tests to add

1. `acquire.run` × 2 with the real `obs_access.Client` and a stubbed `_request` returning `served: False`:
   pass 1 → waiting card; place files; pass 2 → receipt, card cleared (B-1).
2. `acquire.run` served item whose folder holds files but no receipt → actionable error, not a bare
   `destination_not_empty` (B-1 second symptom).
3. GUI: POST a chat message while a `kind: download` card without options is waiting → reaches `pre()`
   (B-2).
4. `acquisition.json` with a `failed` entry for an item the replan dropped → next pass `done` (B-3).
5. `poll_acquisition`: second call inside `ACQ_POLL_SECONDS` returns `None`; `setup_ok=False` lands in
   SETUP_REQUIRED, not EXECUTING.
6. Two threads calling `acquire_then_continue` on one project → one download, final state consistent
   (after should-fix 2).
7. Approve click with a failed refresh, then a second click after the server recovers → signs
   (after should-fix 3).
8. Re-issued approval card has a new id and keeps `tool_policy`.
9. `_manual_card`: same items, changed code → card updated; different waiting card present → not clobbered.
10. `plan_data_status`: rows report `failed` from `acquisition.json`, `waiting_for_you` from an N-row card,
    `acquired` from a subset receipt.
11. `estimate_clip` cap: 5 allowed, 6th refused, fresh `FlowSession` resets.
12. `presentation()` after `cancel`: job listed with `cancelled`, no authorization fields.
13. `_placed_receipt`: `.bc!` and symlinked files excluded; nested files included.
14. `needed()` skips a `status: ready` item with present `local_paths` (after should-fix 8).

---

## Resolution (2026-09-18, after the review)

Blocking:
- **B-1 fixed.** `acquire.run` manual branch checks placed files before asking the server; `_served` turns
  `destination_not_empty` into an actionable "files without a receipt" error. Verified with the real
  `Client` against the live server (`grdc_asia_discharge_daily_20260511`): pass 1 → card, pass 2 → placed
  receipt, card cleared, no link/code outside the card. Tests: `test_manual_path_with_the_real_client_signs_placed_files`,
  `test_served_folder_without_receipt_is_an_actionable_failure`.
- **B-2 fixed.** `waiting` → `pending` in `_stream_session_chat`; `download_placed` now checks every row of the
  N-row card. Guard test: `test_chat_handler_never_reads_a_local_before_assigning_it` (order-aware AST check,
  shown to fail on the original line).
- **B-3 fixed.** `acquire.run` keeps only entries for items still needed and discards all entries on a new
  approval. Test: `test_stale_acquisition_entries_do_not_survive_a_replan`.

Should-fix done: 1 (card id includes the inventory hash; `SEEN_ACTIONS` keys on id + created_at; a
"Respond" button on the Needs-you card reopens any dismissed choice card), 2 (per-project lock around every
pass; the poll skips when a chat pass holds it), 3 (`refresh_estimate` retries `estimate_failed`; stamp errors at
Approve re-issue the card), 4 (`setup-request*.json` hidden from `list_project_files` / `read_project_file` at
any depth, with test), 5 (`_manual_card` never clobbers a different waiting card), 6 (row url must be http(s)),
7 (shared `PARTIAL_SUFFIXES`, symlinks skipped), 8 (`needed()` skips `ready` items whose local path is present),
10 (`download()` re-verifies a published folder against its acquisition receipt instead of refusing forever),
11 (`tool_policy` carried onto the re-issued card), 12 (dead `cancel` move deleted), 13 (`inventory-updates.jsonl`
writes removed; `data-binding-status.json` stays, it has a reader), 14 (empty request variable list covers any
named requirement), 15 (`poll_acquisition(setup_ok)` required).

Nits done: `download_observation_data` schema/handler, `fetch_observation`, `cmd_obs_download` and the
`obs-download` parser removed; `search_observation_data` out of the policy sets; contract text updated.

Not done (deferred to step 4/5): i18n of the new host strings, `[DATA STATUS]` naming consumer step ids,
per-chunk fsync throttle, `_LOCKS` growth, `_manual_card` dedupe on rows (now compares full rows), the
single-candidate join shown on the card.

Suites after resolution: `kiss/tests` 507 passed; `ki_tools_common/tests/flow` 79 passed.
