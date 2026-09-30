# Compiled Mac live acceptance — 2026-09-29

Status: resumed with an additional test-only OS write guard after the user requested continuation; approval/download acceptance remains pending. This report records actual app/provider activity, separately
from the fixture-based regression report for the preceding source fixes.

## Build and isolation

- Built the current dirty `mac-version` source (base `963164e8`), preserving all
  prior Claude/Codex work, with the checked-in PyInstaller spec. Version remains
  0.6.54; this is not a release and nothing has been pushed.
- Build root: `kiss/dist-live-20260929.boeCi7/` (ignored build artifact).
- Compiled app: `artifacts/GeoForge Desktop.app` below that root; ad-hoc deep/strict
  signature verification passed. No Developer ID/notarization claim.
- Started the packaged binary's actual GUI server at `http://127.0.0.1:58755/`,
  port allocated by the OS, with isolated `workroot/`. Operated its real browser UI.
  The existing app at port 64866 was not stopped or changed.
- API and Database access use the app's existing configured credentials, not copies
  in this report or test artifacts. No raw credentials were read or printed.
  Settings, catalogue cache, imported KIs and login state are still shared; the
  app's normal startup catalogue refresh is not a fully isolated profile.
- Existing AquaCrop software was selected through **Use already-installed software**
  with `/Users/leo/kiss/aquacrop` as the external read/execute candidate. Generated
  setup files were intended to remain in isolated `workroot/aquacrop`. That
  protection FAILED: shell copy/chmod operations followed a workspace symlink
  into the original installation; details below. The old saved PASS was not
  copied: the current preflight ran again.

## Real case

- Session: `86c8a4e53b8d`, **Live DS Harbin AquaCrop 20260929**.
- Project: `workroot/projects/2026-09-29-Live-DS-Harbin-AquaCrop-20260929--86c8a4e53b8d/`.
- Selected AquaCrop and DeepSeek API (`deepseek-chat`) through the UI.
- Request: representative Harbin point 45.75 N, 126.65 E; rainfed soybean;
  real CMFD 3-hourly and complete HWSD inputs where available; sequential planning,
  period and validation asked separately, approval before fetching/running.
  All new inputs and outputs remain inside the test project. No invented forcing,
  no generic soil silently presented as observed soil, no observational accuracy claim.
- Controller will choose a bounded one-season test, explicitly accepting/disclosing
  appropriate model defaults rather than implying locally calibrated parameters.

## Provider observations

- Kimi Code was actually started from the compiled setup UI to verify the existing
  AquaCrop installation. It exited 1 with `provider.auth_error: 403` and explicitly
  reported the account's weekly usage quota exhausted. No Kimi scientific work ran.
  No subscription/account change or retry loop was attempted.
- The host then correctly left the isolated installation unverified. Its final
  preflight also reported the isolated `venv/bin/python` did not yet exist: with the
  provider unable to start, external runtime binding had not been completed.
- Switched the setup provider to DeepSeek through the UI. Host-recorded preflight
  completed with 14 passed and 0 failed. This checks entry existence/executability,
  syntax, imports, object construction and KI files—not a full scientific run.

## User's APEX-test comparison: correcting the scope of the finding

The user's screenshot refers to `1072ba3dc2d3`, **APEX-test**, at
`/Users/leo/kiss/projects/2026-09-29-APEX-test--1072ba3dc2d3/`.
This session was inspected read-only. Its provider is also DeepSeek API,
`deepseek-chat`. Its pending question was not answered or approved by this test.

| Evidence | User's APEX-test | Isolated AquaCrop test |
| --- | --- | --- |
| Product inspected | `cmfd_china_daily_010` | `cmfd_china_3hr_010` |
| Initial tool path | Searches, `describe_dataset`, `estimate_clip` | Four searches, no describe or estimate |
| First-pass subset discovery | Successful without corrective instruction | Omitted; national-file metadata presented as acquisition limit |
| Subsequent subset discovery | Already present | Successful after explicit controller correction; assisted recovery |
| Actual data download | None; awaiting approval | None; approval withheld |

APEX persisted `.geoforge/subsets/6a035d4f69b24cb3a9fdc5933a350516.json`:

- bbox `[125.5,46,128.5,49]`, 1956-01-01 through 2024-12-31.
- Seven variables: `prec,pres,rhum,shum,srad,temp,wind`.
- `subsettable: true`, complete coverage, 30×30 cells, 483 parts.
- Estimated output 317,331,000 bytes (~317 MB); source I/O 197,614,144,718
  bytes is server-side input work, not the proposed user download size.
- Status `awaiting_approval`; Flow remains `PLANNING`; no acquired input files
  or receipts observed. This proves working subset discovery/estimation, not
  completed downloading, input conversion or simulation.

APEX's current `setup-request.json` recommends the daily subset. However, its
alternative C still presents CMFD three-hourly as a 604 GB national/manual
download, without an observed three-hourly describe/estimate in this session.
The successful daily path must not be generalized into a failure; nor does it
establish correct discovery for the three-hourly alternative.

The isolated AquaCrop recovery estimate
`.geoforge/subsets/4b3c866234bb43fa9130e0d171cc7cf8.json` is eligible for
2003, bbox `[126.6,45.7,126.7,45.8]`, `prec,pres,temp,wind`: 1×1 cell,
four parts, 23,360 estimated output bytes versus 5,010,498,256 source I/O bytes.
That is not evidence of a complete forcing set: radiation/humidity remain to be
resolved. Its initial national-download rationale also persisted in the inventory
at inspection; a working estimate alone does not make the plan consistent.

The first AquaCrop resolver result retained `spatial_filter_applied:false` and a
spatial note distinguishing national delivery units from a possible clipping
service. The agent did not call describe/estimate before concluding national
downloads were necessary. Available evidence therefore does NOT support a
blanket CMFD/server outage, removal of Desktop clipping, or inability of DeepSeek
to use the tools. The observed defect is inconsistent capability checking during
planning. Raw provider tool result bodies are not all persisted, so this report
does not claim a complete replay of every response field.

## Separate safety failure: original AquaCrop entry overwritten

- Original `/Users/leo/kiss/aquacrop/ki/run_and_score.py` now matches the generated
  `workroot/aquacrop/run_and_score_entry.py` byte-for-byte: 3167 bytes, mode 0755,
  SHA-256 `6546ece2f35b8dade139b6a12d0f368356dd87d3f62ddd548e17a46e251034a5`.
  Modification time: 2026-09-29 17:08:07 +0800.
- Setup log lines 147–174 record copy/chmod operations against a destination
  symlink. These are consistent with following the symlink into the original
  install. The provider's later statement that it left that install unchanged
  is contradicted by the file evidence.
- The new entry invokes genuine AquaCrop but fixed maize/SiltLoam with bundled
  `champion_climate.txt`, 1982–1983. It is a package smoke runner, not the planned
  Harbin soybean simulation. The narrated 12.652 t/ha was not independently
  established from persisted command stdout and is not an acceptance result.
- The isolated preflight matches the current repository and packaged template
  except expected path substitutions; it was not weakened. Nevertheless its
  14/14 PASS does not check preservation of the external installation.
- Timestamp inspection found one changed source file in the original install,
  plus generated `load_forcing` import bytecode. There is no full pre/post hash
  inventory, so that is not a proof of all other bytes remaining identical.
- The canonical repository runner is clean (8511 bytes) and matches seven older
  bundles. Reapplying original install paths produces an 8557-byte canonical
  reconstruction. No proven exact pre-test backup was found, so no restoration
  has been performed and possible old local edits have not been silently erased.
- The isolated server PID 24728 on port 58755 was stopped. User app PID 21029
  remains running. No further plan approval, data download or scientific run was
  initiated. APEX-test was not changed.

## Acceptance checkpoints

- [x] Compile/package and verify signature.
- [x] Real UI creates isolated named project and selects provider/KI.
- [x] Attempt Kimi; record external quota blocker honestly.
- [ ] Safe verification of existing model software: preflight passed, but external
      source preservation FAILED; not accepted.
- [ ] Sequential planning preserves scope and offers real available sources.
- [ ] Review, explicit approval and matching plan/inventory/bindings.
- [ ] Actual authenticated downloads; inspect format, variables, bounds, times,
      contents and acquisition receipts.
- [ ] Actual model execution and fresh output/receipt evidence.
- [ ] Distinguish execution success from scientific validation.

The diagnosing-bugs workflow is being used to capture live failures first, before
attributing them to prompts, Desktop code, KI tools, providers or the database.

## Continued test, evening of September 29

- User explicitly requested continuing the test. No restoration of the original
  runner was inferred from that instruction; it remains unchanged from the
  recorded overwritten hash pending a separate recovery choice.
- Restarted the same compiled app directly under `sandbox-exec` with a test-only
  `(deny file-write* (subpath "/Users/leo/kiss"))` rule. This protects existing model
  installations/projects, including symlink targets. It is additional test
  containment, NOT evidence that the product's protection defect has been fixed.
- Disposable-fixture checks verified denial of append/create/chmod/rename/delete,
  protected-directory rename, symlink writes, protected-source hardlinks and
  child-process writes, while reads and writes elsewhere still work. Nested
  `sandbox-exec` was rejected on this Mac, so this guarded continuation is DS API
  only; Kimi security was not disabled. Kimi's earlier quota blocker remains.
- Accepted FC explicitly as an uncalibrated initial-water test assumption. Set a
  100 MB acquisition budget, preserving the one-season 2003/Harbin case.
- DS then exposed the four-variable CMFD describe limitation and asked to
  supplement radiation/humidity from daily CMFD. Controller accepted conditionally
  with required checks for sampled schema, temporal resolution and actual units.
  Describe is sampled-header evidence, not an exhaustive whole-product inventory.
  At that checkpoint all saved three-hourly requests still requested only four
  variables: no exact `srad/shum` rejection had been established.
- DS submitted a plan claiming two automatic CMFD subsets and manual HWSD soil.
  The actual approval card instead classified ALL 23 inventory items as run-time
  preparation (15 step outputs plus eight other prepared items). The first eight
  saved inventory rows had been reduced to IDs/status/boolean flags, without the
  actual acquisition details. Downloaded data was incorrectly `resolved` despite
  no acquired files. Controller did NOT approve this inconsistent review.
- Used the real **Modify the plan** UI. Requested correct acquisition bindings,
  actual downloads in the review, an in-budget soil subset plus real attributes,
  and correction of the weather-preparation ordering. Also explicitly allowed a
  1.2 m root-depth cap for this integration test with the original default recorded;
  this is not a calibrated agronomic recommendation. No source edits were made to
  make the live case pass.
