# Windows setup and KI update checkpoint — 2026-10-17

This source checkpoint fixes failures exposed by a fresh Windows WOFOST setup,
official KI update, and DeepSeek-driven GUI run. It is not a new binary release:
the published Windows 0.6.60 installer and portable archive remain unchanged.

## Why a previously working case failed again

A working project had already acquired its interpreter, paths and local KI
repairs. A fresh installation or a newly downloaded KI did not necessarily have
those same bindings. Setup could therefore look ready while a later tool used
the wrong environment, an old server path, or an incompatible provider API.
Separately, stale state and weak execution feedback made a failed attempt look
like progress or completion. Passing a retained case did not cover those paths.

## What this checkpoint changes

| Area | Shared application behavior | Remaining model or platform limit |
|---|---|---|
| Setup | Bind the selected interpreter and helper revision; remove inherited host Python import paths; distinguish fresh setup from retained installations; report status for the exact setup root. | Managed Python bootstrap currently covers fresh Windows x64 setup. Other platforms need equivalent provisioning and acceptance. |
| KI updates | A new setup can select independently verified official KIs and their declared dependencies, with a signed scope. Invalid unrelated packages do not enter that selection; existing global and project libraries are preserved. | Every selected package must still pass KDT. This does not repair invalid upstream packages or claim a successful whole-library update. |
| Paths | Bind paths to the selected runtime, reject stale identities, and recheck after changes. | Strict adaptation of recognized server hardcoded paths is still WOFOST-specific. Ordinary role substitution is shared; arbitrary paths in all 127 KIs are not covered. |
| Project data | Review exact declared inputs, allow authenticated non-executable bundled KI data, and retain unchanged data through verified maintenance lineage. Reject missing input declarations and give precise path diagnostics. | A KI still needs its actual case data or an acquisition route. Reviewed Python data tools are not an OS sandbox. |
| Execution | Require current successful receipts for declared upstream producers before their consumers run. Recheck input/output bytes; retain failed history without presenting it as the current attempt. | Independent plan branches remain independent. Host completion checks do not validate the scientific quality of model results. |
| Continuation | Give providers the current host verdict and relevant failure facts; preserve plan-submission errors; avoid claiming a plan was accepted before validation. | The real GUI test included normal user selections, plan review/corrections and approvals; it was not an unattended first-attempt run. |
| Windows state writes | Use unique temporary files, process/thread locking and bounded retries for specific Windows sharing errors. Preserve persistent errors and the previous valid state. | This addresses file replacement races, not arbitrary concurrent edits to stale in-memory state. |
| KI maintenance | Keep separate reviews, KDT verification, authenticated adoption and retesting. Report actual applied changes separately from reviewers' earlier hypotheses. | The supported PCSE runner/crop repairs are versioned WOFOST recipes. Model semantics remain in the KI and require their own evidence. |

These host gates are used by the supported API and CLI execution paths. A shared
gate is not proof that every provider/model combination has passed a live case.
Existing external Python installations are used without installing or upgrading
packages in them; package imports can still create caches.

## Real WOFOST acceptance

The GUI test used DeepSeek, a fresh Python 3.12.10 environment and PCSE 6.0.12.
The selected official KI revision was
`5d1f6b5335a0622a3dd1b28b18164830e43b5cee`. The whole-library update at that
revision rejected BMI, Climate_Projection, EF5, EPIC, ESMF, MODFLOW6 and PyMT;
WOFOST was independently checked in its own selection. No data-KI tree existed
in that same official source snapshot.

Two project-local KI repairs went through GUI review, KDT, adoption and a fresh
preflight: preserving eight soil and six site values in the PCSE runner, and
adapting the crop reader to the actual provider mapping API. The final native
model, official result reader and three SVG figures completed successfully.

| Evidence | Observed result |
|---|---|
| Case | Wangjiaba maize, rainfed WLP_FD, 1980-06-01 through 1980-09-07 |
| Executable steps | All 8 passed under the final approval |
| Native output | 99 daily rows |
| Final yield | 2267.1084 kg/ha |
| Final biomass | 3923.7587 kg/ha |
| Maximum LAI | 0.7638748 |
| Figure source audit | All 1,188 CSV cells matched current native output; all three figures used the full 99 rows |
| Final host state | Completed; no current failed, missing, stale, invalid or unreceipted outputs |

The independent local audit is named
`final-independent-wofost-e2e-20261017.json` (SHA-256
`10a67b9a5ff8b1b6e9553f44e9a075bcb975eccef66dc039e3f193d6d30bf55c`).
The result archive and screenshots were delivered separately; private runtime
profiles, credentials and project directories are not part of this commit.

This demonstrates execution and result-reading consistency, not agreement with
observations. Two descriptive KI issues remain: the crop metadata infers a winter
crop from the presence of VERNSAT, and the reader's first-positive-DVS emergence
date differs by one day from the native DOE field. The crop validator was
explicitly called with `false` for winter-crop validation; the runner independently
selected maize/Grain_maize_201. Those two emergence-date definitions are not
treated as equal.

## Pre-push checks and evidence boundary

Independent code review found a source-only assumption in the new scoped
updater's implementation fingerprint. A frozen application may have no readable
module file. The fix uses the existing complete-module identity helper, which
supports both source and frozen loader code. Tests require old acceptances to
be rejected when implementation identity changes; no old proof is grandfathered.

The broader regression run also exposed two error-handling gaps: the scoped
request wrapper returned a conflict for malformed or missing sessions instead
of HTTP 400/404, and the secondary input lookup crashed on malformed inventory
IDs before returning the core validator's rejection. Both now report the
appropriate errors while retaining scope and approval checks. Older fixtures
were updated to declare required invocation bindings and maintenance policy
versions, and to load the real scoped-library UI helper.

The real GUI acceptance above predates these pre-push compatibility and
error-handling fixes. It remains historical evidence for that source snapshot,
not a claim that the final commit was already tested inside a rebuilt installer.
A new binary release must still pass the frozen/installed application and
installer checks.

| Check | Result |
|---|---|
| Full desktop regression sweep during integration | 5,841 passed, 46 failed, 37 skipped; 366 additional subtests passed. All 46 failures were classified and corrected below. |
| Recheck of every original failing case against the repaired source | 46 passed, no failures or skips. The malformed-session case now expects HTTP 400; its request and rejection-before-remote-call checks remain intact. |
| Complete shared-library regression after the input-validation fix | 455 passed, 7 skipped. |
| Standalone frontend tests | 24 passed. |
| Release asset-check tool tests | 4 passed. |
| Source-free scoped identity tests | 40 passed, including changed-code rejection and unavailable-loader rejection. This simulates the frozen import surface; it is not an installer test. |

The failures exposed two production error-handling defects (session
classification and malformed inventory IDs), alongside outdated test
expectations/fixtures: missing request headers, missing scoped UI dependencies,
required invocation/input bindings, maintenance policy versions, and the
malformed-session HTTP expectation. All session cases were rechecked against
the final 400/404 contract.
No failed assertion was removed and no production approval/data-access gate was
relaxed to make these tests pass.

Affected suites were also rerun separately: request routing (68), bundled-data
and maintenance-lineage handling (96), shared input contracts (18), maintenance
dispatch (43), question/review lifecycle (87), request-header and scoped GUI
fixtures (157), and preparation/output-completeness checks (37). These counts
overlap the full sweep and each other; they are not additional unique test
totals. The final verification is a full sweep followed by repairs and targeted
rechecks, not a second clean full-suite run of the final commit.

Desktop skips cover unavailable server files, POSIX-only behavior and an
explicit opt-in official-download integration. Shared skips cover unavailable
server files and external DLBreach/SUMMA executables. Private local JUnit reports
are retained as `prepush-desktop-regression.xml`,
`prepush-repaired-regression.xml` and `prepush-shared-regression.xml`.

## Next generalization step

Move model environment, executable, data and path requirements into a consistent
KI contract. On every install or update, resolve that contract for the current
OS, build a project-local binding, and verify it with the KI's real reference
case before declaring it ready. Keep model-specific API and scientific changes
inside KDT-reviewed KI maintenance. Validate this same lifecycle with DSSAT,
SHAW, VIC and other models rather than adding an unconditional path rewrite.

The shared Flow synchronization checklist also records the new input-grant
module so a later server/shared-library sync cannot silently omit it.
