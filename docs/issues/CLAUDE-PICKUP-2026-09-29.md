# Local Claude pickup — 2026-09-29

Follow-up: [remaining flow fixes and Mac verification](REMAINING-FLOW-FIXES-2026-09-29.md)
records the later approved planning wording, acquisition recovery and expanded Stop
handling. The results/open items below describe this earlier pickup checkpoint.

## Scope and recovered state

The user asked to pick up the local Claude session titled **Multi-account access on Mac**.
The relevant session id is `c7060885-7508-406f-8514-39f38bb0c20a`; its latest work is
GeoForge Desktop planning, acquisition and execution, despite the older title.

Working branch: `mac-version`, base HEAD `963164e8`. Claude's changes and the earlier
mixed automatic/manual acquisition fix were uncommitted. They were preserved. No Git
pull, commit, push, rebuild, provider turn, live Database download or user-project mutation
was performed during this pickup.

Recovered changes include mixed-download continuation, latest-attempt completion evidence,
Stop propagation, interview-answer retention, uploaded-input binding, download-tool guards,
approval-bound notices, effective Database activation and the shared Flow upstream pin.

Recovered user choices:

- A required "you provide" input blocks approval until uploaded.
- Extracted files must be checked for integrity; carry that Desktop rule upstream.
- Redraft study-period/validation instructions and show them before applying.
- Do not automatically change the live Harbin example's scope or approval.

## Additional defects reproduced and fixed

### Database activation changed after review

The original gate ran during planning/card generation but not the final approval transaction.
Opening a Database-backed card, switching access off and clicking Approve still dispatched
the real acquisition path. The remote transport in the reproduction was a fixture.

`test_database_approval.py` initially had five failures and one passing public-source control.
The fix checks effective activation before remote estimate refresh and immediately before
signing. It leaves the project awaiting the user, reissues a restricted review, and allows
reactivation or plan modification. A setting change during an outstanding estimate is covered.

### Missing or changed uploaded inputs

A stale host upload record could survive deletion, while an agent-written nonexistent path
could also satisfy a "you provide" input. Both cases reached approval, including through the
actual acquisition dispatcher (no live network).

The binding step now clears missing host bindings, requires host-observed uploaded files,
rejects paths escaping the input folder and runs after remote estimate refresh. Changed files
require another review. Tests cover deletion, replacement during refresh, re-upload and intact
upload controls, and an escaping symlink.

### Planning answer notes

The option label was saved but the user's accompanying note was not. It could disappear from
later planning context after chat truncation. Notes are now separately saved and included in
the settled-answer block and cited-answer provenance. A real chat-handler fixture covers this.

### Settings disagreed with the Database gate

A stored token and old catalogue made both status pills appear connected even after the
cached server response rejected authentication. The host now supplies `effective_mode`, and
both Settings and the project-data panel display unavailable when that mode is off. Token
presence is still distinct from authentication availability. Tests execute the shipped
JavaScript in both languages and retain off, missing-token, offline-cache and active controls.

### SIGTERM-resistant CLI processes

The original Stop fix only politely terminated an agent CLI tree. A fixture CLI/tool ignoring
SIGTERM survived an acknowledged Stop. Two production regressions failed before the fix.

The host captures descendant process groups before signalling, gives them a five-second grace
period, then forcefully terminates surviving original groups. A child reparented after its
parent exits is still reached. Shutdown waits for scheduled escalation. Tests also ensure an
unrelated process group is not killed and a finished run can write its receipt during grace.

## Verification

- Recovered baseline: Desktop **1,226 passed, 1 skipped, 123 subtests** with local process
  inspection and loopback permissions. Shared Flow **137 passed, 5 skipped**.
- The first sandboxed Desktop run had 12 environment failures: process-table access and
  local socket binding were denied. The permitted baseline rerun passed; these were not
  treated as product defects. Initial combined-package collection also needed separate
  invocations because both packages use a `tests` namespace.
- Focused Stop verification after repair: **80 repository tests + 2 reproduction controls**
  passed. These use real local stand-in processes, not real providers or models.
- The final approval gate exposed a non-hermetic mixed-acquisition fixture: it simulated a
  successful Database transport but never simulated activation. The fixture now explicitly
  supplies a configured token state, direct mode and successful cached catalogue, without
  reading the developer's real settings or Keychain. All **32** mixed-acquisition and host
  acquisition-request tests pass with that precondition. The production gate was not weakened.
- Three older Flow/acquisition tests now also declare Database activation explicitly. They
  previously depended on the developer's settings; their targeted rerun passed all three.
- Final stable-source Desktop suite: **1,255 passed, 1 skipped, 123 subtests passed**
  in 218.40 seconds. Shared Flow suite: **137 passed, 5 skipped**. The five Flow skips
  require a server checkout/upstream copy not present here; its run also reported a
  NumPy/netCDF ABI-size warning. These suites ran separately with isolated Flow registry,
  keys and temporary directories, using `PYTHONPATH=kiss:ki_tools_common`.
- Commands: `python3 -m pytest kiss/tests -q -p no:cacheprovider` and
  `python3 -m pytest ki_tools_common/tests/flow -q -p no:cacheprovider`, with the
  isolated environment described above and local process/loopback permissions.
- The shipped HTML's inline JavaScript parsed successfully with Node `vm.Script`;
  `git diff --check` passed.

## Still open / not claimed

- The proposed new study-period/validation prompt text is **not applied** pending the user's
  approval. No implicit acceptance was inferred from the handoff request.
- `answered_by` checks that a cited host answer exists and displays it for review; it does
  not prove semantic equivalence between an agent's derived value and that answer. This is
  the explicitly chosen citation-plus-review design, not an exact-match enforcement rule.
- Ordinary chat attachments are not automatically assigned to a specific required input.
- In-process calibration, an already-running preflight and the built-in installer remain
  outside full Stop coverage. Fully detached daemons predating Stop are not discoverable by
  the tree walk. Windows still has direct-process rather than full-tree cancellation.
- Receipt cleanup taking longer than five seconds can be interrupted by forceful Stop.
- No compiled-app GUI acceptance, live token rejection, provider planning behavior, real
  download completion or successful scientific simulation is established by these tests.
