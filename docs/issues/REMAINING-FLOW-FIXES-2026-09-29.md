# Remaining Desktop flow fixes — 2026-09-29

Follow-up to [Claude pickup](CLAUDE-PICKUP-2026-09-29.md), on the same uncommitted
`mac-version` working tree. The user asked to continue the remaining fixes. Existing
Claude changes were preserved. This document distinguishes source regressions from
compiled-app and live-provider acceptance.

## Planning questions

The previously proposed wording is now applied. Intake and planning use one shared
`flow.contracts.study_design_questions()` block. It separates simulation period from
validation, grounds proposed dates in checked coverage, preserves a user-supplied
period and offers custom dates. Observation overlap does not silently shorten the
simulation. Aggregate comparisons must not be called site-scale validation. GeoForge
Database candidates require activated access and real catalogue evidence; public and
user inputs remain valid without Database access.

This is agent guidance, not a deterministic scientific validator. No live DS/Kimi turn
was used to establish agent compliance. Seven shared prompt checks and four actual
Desktop intake adapter checks failed before the change and passed after it. The
intake checks capture API and CLI prompts with Database access both off and active.
No prompt test downloads data or edits a real user's project.

The shared-package upstream checklist records the new helper; it has not been synced
to the web server. An older shared package missing this helper is not a compatible
replacement for this Desktop source.

## Recovery and cancellation

Implemented changes:

- Manual download cards restore approval/item-bound URL, extraction code and share
  path from `.geoforge/manual-download-details.json`. This private host record is
  atomically written with mode 0600 and is excluded from agent API file reads and
  listings, in both project and setup modes. The ordinary acquisition ledger remains
  secret-free. Recovery does not poll the server for those details. Legacy projects
  without saved details explicitly ask for a chat refresh.
- Modify plan publishes a short-lived intent without waiting for the acquisition lock.
  The current admitted transfer may finish and retain its receipt. Before any next
  request and final state transition, the acquisition owner checks the intent and
  approval identity. Old or unidentified acquisition results cannot advance a new
  approval or overwrite its status. The queued modification returns to planning and
  retains the user's note for the next ordinary chat; it never starts an agent itself.
  An ambiguous crash during this transition requires confirmation.
- Each Desktop turn has a durable generation. Source CLI children, API tools and the
  native bridge retain their original identity. Clearing Stop for a later message does
  not revive commands from the previous turn. The explicit stopped summary persists
  until that new turn begins. This is cooperative cancellation, not a sandbox against
  an adversarial agent deliberately stripping its environment.
- Preflight and installer commands use the managed process runner. Calibration runs
  the existing engine in a supervised child, using the same source or frozen runtime.
  Installer download/hash/extraction work also runs in a supervised child, preserving
  the existing network timeout. Both private worker entrypoints reject inherited stale
  or wrong-project turn identities before work. Stopped/invalid worker results cannot
  reuse a prior success report; interrupted installations remain unverified.

Initial deterministic reproductions:

- `test_acquisition_recovery.py`: two failures — a restored manual card lost its
  URL/code/share path; Modify plan did not return while a download held the lock.
- `test_stop_generation.py`: two failures and one direct-CLI control passed — an old
  provider's command could run after a new message cleared Stop; turn finalization
  replaced the explicit stopped summary.
- `test_stop_sync_work.py`: three failures — preflight, calibration, and built-in
  installation continued beyond the actual Stop handler in local fixture processes.

Independent review added two red-confirmed acquisition races: Modify during receipt
lookup could admit another request, and an older result could advance a newly replaced
approval with missing inputs. Both now have regressions. Four direct worker replay
cases also went from exit 0 with writes to exit 130 without writes.

The diagnosing-bugs skill guided red-before-fix checks at real adapter/execution
boundaries. All transports, engines, and projects in these tests are isolated fixtures.
No credentials, live providers, external datasets, or user simulations are involved.

## Final verification

- Planning/intake/answer/Database focused Desktop tests: **83 passed**.
- Shared Flow suite after planning change: **144 passed, 5 skipped**; unavailable server
  reference checks were skipped. A pre-existing NumPy/netCDF ABI-size warning remains.
- Final focused acquisition/recovery suite: **148 passed**.
- Combined synchronous Stop, API handoff and private-file recovery checks: **54 passed**.
- Final integrated Desktop suite: **1,310 passed, 1 skipped, 123 subtests passed**
  in 226.46 seconds. The skip requires a server copy absent from this machine. The
  first integrated run had 1,307 passes and three stale CLI-question transport
  assertions (old `argv`/`cwd` envelope only). These now mint a real project turn and
  assert its `turn_id` and `turn_project`, rather than removing identity checks. The
  47-test focused transport/runtime rerun and then the full rerun passed; no production
  build inputs changed for this test correction.
- Full Desktop log: `/private/tmp/geoforge-flow-round.Sg5uwz/final-tests.log`.
  Tests used isolated `GEOFORGE_FLOW_REGISTRY`, `GEOFORGE_FLOW_KEYS` and pytest
  temporary directories, with process-table and loopback access. The Desktop and
  shared Flow suites ran separately because both packages have a `tests` namespace.
- Shipped inline JavaScript parses; `git diff --check` passes.

## Isolated Mac test build

- Apple Silicon arm64, unchanged version **0.6.54**; not a release. Based on local
  `mac-version` HEAD `963164e8` plus the current uncommitted changes, including the
  preceding Claude/Codex fixes. No installed application was replaced or opened.
- App: `/private/tmp/geoforge-flow-round.Sg5uwz/dist/GeoForge Desktop.app`.
  This is an ephemeral test artifact, not a published/downloadable release asset.
- Executable SHA-256:
  `526be4c65b79b144adf0dac4fb2a97280b00880c4a524eb947c5add5568b4c6b`.
- Built with Python 3.13.12 and PyInstaller 6.22.2 using the unchanged checked-in
  `kiss/GeoForgeDesktop.spec`; build log is in the same temporary root.
- Ad-hoc signature verification (`codesign --verify --deep --strict`) passed.
  Not Developer ID signed or notarized.
- **Nine frozen-worker tests passed:** successful calibration and download fixture
  round trips; cancellation of calibration, a blocked HTTP read and a blocked FIFO
  read; four stale/wrong-project direct worker rejection cases. These execute the
  real packaged binary; the engine, files and HTTP endpoint are local test fixtures.
- Frozen `harness-status APEX`, from outside the checkout with `PYTHONPATH` unset:
  `ready:true`, `flow_ready:true`, marker `[KI HARNESS v1]`, 4,845 contract characters;
  implementation and Flow origins are inside this bundle. Frozen calibration status
  is ready with all seven backend module probes available.
- Independent read-only archive audit: **72 compiled modules** match fresh source
  compilation after normalizing code filenames; **270 loose files** are byte-identical
  (8 web, 257 Flow, 5 harness), with no extra files in the audited payload trees.
  Audit: `/private/tmp/geoforge-flow-round.Sg5uwz/compiled-source-audit.json`.
- This report and final verification notes were updated after packaging. The bundled
  changelog contains the source changes but not those later results.

Reproduce the frozen-worker checks after building at the path above:

```sh
env GEOFORGE_TEST_FROZEN_EXE='/private/tmp/geoforge-flow-round.Sg5uwz/dist/GeoForge Desktop.app/Contents/MacOS/GeoForge Desktop' \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=kiss:ki_tools_common \
  python3 -m pytest kiss/tests/test_stop_sync_work.py -q -p no:cacheprovider \
  -k 'calibration_engine or calibration_worker_success_round_trip or download_worker_succeeds or blocked_http_read or blocked_fifo_read or private_worker'
```

Local process inspection and loopback access are required for the process/HTTP tests.

## Remaining acceptance and limits

- No live DeepSeek/Kimi planning, authenticated GeoForge Database download, CMFD
  completion, model simulation or calibration quality claim follows from these fixture
  tests. A separate live end-to-end acceptance is still needed.
- Some local KI materialisation/copy phases are cooperatively checked at boundaries.
  Installation-only readiness probes retain their existing bounded timeout (typically
  25–30 seconds). Stop is not claimed to interrupt every host operation instantly.
- Process-tree escalation was verified on macOS/POSIX. Windows needs independent
  verification; this round does not add a Windows process-tree mechanism.
- An admitted acquisition transfer can finish after Modify; that is intentional. The
  next request/model execution is blocked. Closing the app does not create an OS
  background download service.
- Scientific recommendation quality still depends on evidence and agent behaviour.
  Prompt tests verify instructions reach the provider, not that an agent follows them.
- `answered_by` still proves a cited host answer exists, not semantic equivalence with
  an agent-derived value; user review remains part of that design. Ordinary chat
  attachments are not automatically assigned to a specific required input.
- Shared Flow changes are documented in `UPSTREAM.json` but have not been pushed to
  the web harness. No commit, push or release is included in this round.
