# Automatic acquisition must continue during a manual download

Date: 2026-09-28. Source changes based on `mac-version` commit `963164e8`.
Not a compiled build or a live scientific-run acceptance report.

## Observed problem

The AquaCrop Harbin project had an approved plan, Flow `ACQUIRING`, a CMFD
subset marked `pending` / last reported `running`, and a manual yearbook
marked `waiting`. No downloaded input was recorded. Its chat reply showed only
the manual-file reminder and said “Nothing runs until the files are there.”

This does **not** prove the remote CMFD job failed. The saved state proves the
request started; it does not prove the resulting files were downloaded.

## Reproduction and cause

The diagnosing-bugs skill guided a red-to-green reproduction at the actual
frontend timer seam, separate from the acquisition implementation:

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest -q \
  kiss/tests/test_acquisition_poll_ui.py \
  kiss/tests/test_acquisition_mixed_delivery.py
```

Before the fix, the real idle-page timers made only `/api/sessions` and
`/api/session/<id>/view` requests over 15 simulated seconds. With the agent
turn finished and both panels closed, nothing invoked host acquisition.
That test failed; four real approval/acquisition tests passed. Directly
invoking the existing host poll could finish the automatic subset while
keeping the manual request outstanding, irrespective of inventory order.

Thus the cause was the missing desktop continuation trigger, compounded by
manual-only status wording—not an acquisition loop that refused every
automatic source because a manual source existed.

## Changes

- A same-origin, CSRF-protected `POST /api/session/<id>/acquire` advances the
  existing approved acquisition pass. It is separate from read-only `/run`
  status; no agent turn or scientific tool is invoked by this command.
- The idle frontend refresh continues approved automatic inputs after a turn
  ends, with either panel closed. It remembers started projects when switching
  chats, avoids overlapping requests, retries connection failures, and stops
  when automatic work ends or the project is archived. The existing host
  rate limit and per-project acquisition lock remain in force.
  Already-started downloads do not wait for a slow status read in another chat;
  repeated current-chat status reads are also deduplicated.
- Current, approved acquisition evidence supplies a small status projection
  with automatic rows, manual rows, and counts. Mixed status retains the
  manual blocker while identifying both host work and user action. Raw remote
  errors, signed links and extraction codes are not copied into this summary.
- A live chat banner shows server processing/download state or acquired files
  alongside outstanding manual inputs. A receipt is required before showing
  an automatic input as acquired. Acquisition is not scientific validation.
- Automatic background checks do not sign newly appearing manual files: a
  copy in progress is not a completed user handoff. The user's explicit
  continuation still checks and receipts manually placed files. Existing
  project-panel polling uses this automatic-only mode too.

## Verification scope

Four new suites cover the real review/acquisition path, shipped JavaScript
timers and banner, real request handlers/security checks, and read-only status
projection. They use isolated projects, fixture transports and actual shared
approval/receipt checks. No live database requests, DS/Kimi turns, or model
runs are part of these tests. The existing user's project was only inspected,
not changed or restarted.

Verification results:

- Full Desktop suite: **1,112 passed, 1 skipped, 123 subtests passed**. Localhost
  test permission was used; all transports/accounts remained test fixtures.
- Final review reproduced a slow-current-status-read edge case: the visible
  chat could delay unrelated tracked downloads. Its new shipped-JavaScript
  test failed before separating those requests and passed after the correction.
- Final focused acquisition/request/UI/status suites: **102 passed**, including
  that last correction and the clarified source-data wording. The full suite
  was not repeated after these final two small changes.
- JavaScript syntax and `git diff --check` passed. No debug instrumentation
  was added to production code.

This continuation runs while the application page is open. It is not a new
OS background service and does not promise downloads after quitting the app.
Already tracked projects continue when switching chats; opening an approved
pending project after a restart discovers and resumes its automatic work.
Compiled-app/native-GUI acceptance and live CMFD completion remain separate.

## Review round (2026-09-28)

An adversarial review confirmed eleven defects in this change and refuted one
further claim (the Retry and chat paths still sign a manual copy the user
declares complete, exactly as before this change; no fix). Each fix below has
a test that failed before the fix and passes after it.

- **Stale Flow writes (F1, F5).** A pass could write back a Flow state it had
  loaded before waiting on the acquisition lock. A background pass overwrote
  "Change the plan" (approval revoked, Flow back in `ACQUIRING`, project
  stuck), and a chat pass overwrote the `BLOCKED` state a tick had just
  written. The chat pass now re-reads Flow under the lock and stops unless it
  is still `ACQUIRING`; "Change the plan" runs under the same lock with a
  re-read; every pass re-reads Flow and approval after acquisition and moves
  or saves nothing unless Flow is still `ACQUIRING` with an OK approval.
- **Silent stop after background completion (F6).** When a tick receipted the
  last automatic input, Flow entered `EXECUTING` with no agent turn and no
  cue. No timer starts a turn. Status now reports "approved data acquired, run
  not started" (`EXECUTING`, or `SETUP_REQUIRED` with its own "software setup
  needed" wording; every approved input has an intact receipt; no agent turn
  open and no turn or report since Flow moved on) as waiting for the user, and
  the banner offers **Start the approved run**, which sends an ordinary chat
  message through the normal send path (a typed draft is kept; the button is
  disabled until the next status). The pending chat reply again says the run
  starts once every input has a receipt.
- **Manual card lost (F8).** A tick turned a confirmed manual input whose file
  later changed back to `waiting`, without a card. Ticks still set such an
  input back to `waiting` (they never sign a manual file, not even a
  replacement for one already handed off), but now reissue the manual card
  when a manual input waits with no open card; an open card is never
  rewritten. Only **Files are in place, continue** signs a manual file.
- **Copy-in-progress status (F7, F9).** A copy growing in a waiting manual
  destination made every status read "evidence unreadable" and relabelled an
  acquired input as pending, which restarted ticks. Waiting manual destinations
  and the host's own dot-prefixed temporary downloads under `inputs/`
  (`.subset-*`, `.*.part`) are no longer part of the evidence-change stamp (a
  receipt names what counts, and writing it still invalidates the cache); the
  filter runs on `inputs/` only, with precomputed string prefixes. A recorded delivery whose receipt cannot be
  confirmed right now shows as "Receipt check pending" and does not count as
  pending.
- **Idle cost (F2, F10).** The visible chat's status is read every 5 s only
  while it is acquiring and not already advanced by its own `/acquire` tick
  (whose response carries the status), never while the page is hidden, with a
  30 s fallback read that discovers acquisitions started elsewhere; the
  ready-to-start state, which only the user changes, uses that fallback. A
  rate-limited `/acquire` tick reuses its first status read.
- **Banner (F3, F4).** Title and footer follow the outstanding work
  (automatic and manual, automatic only, manual only, ready to start) in
  English and Chinese. Opening another chat clears the previous chat's banner
  before the new status loads, also when that read fails.
- **Test gap (F11).** A test now checks that the Project Status panel poll is
  automatic-only; reverting that line makes it fail.

A second review (two reviewers) of that round confirmed ten findings (some
duplicates), now fixed as folded into the bullets above: a background finish
into `SETUP_REQUIRED` stopped silently; a tick re-signed a replacement manual
file mid-copy and could enter `EXECUTING` on partial data; "ready to start"
also matched after an execution turn had run and kept the 5 s poll going; the
host's own `.subset-*` download still made status "evidence unreadable"; the
waiting-destination filter added ~60% to a 30k-file stamp (0.83 s -> 1.35 s;
now 0.82-0.90 s); a tracked visible chat sent `/acquire`, `/run` and a second
`/acquire` per tick; the Start button discarded a typed draft. Each has a
test that failed before its fix. A test also locks in that an agent-reported
failure outranks "ready to start" (it fails when that branch is moved above
the failure branch).

Known limits: a reissued manual card carries the destination but not the
Baidu link or extraction code (a tick does not ask the database for them); the
next chat message's full pass fills them in. "Change the plan" now waits for a
background pass already holding the lock, so it can wait for a subset download
in progress.

Verification after the second review (supersedes the numbers above): focused
suites **211 passed** (197 after the first review round); full Desktop suite
**1,163 passed, 1 skipped, 123 subtests passed**; shared Flow suite **134
passed, 4 skipped** (server trees absent). The working tree also held another party's uncommitted,
still-changing edits to `kiss/kiss_cli/execution.py`,
`kiss/tests/test_execution.py`,
`ki_tools_common/ki_tools_common/flow/receipts.py` and
`ki_tools_common/tests/flow/test_flow_core.py`; they are not part of this
change, but their tests are included in the full and shared counts. Source only: not compiled, no live CMFD
completion and no native-app acceptance.
