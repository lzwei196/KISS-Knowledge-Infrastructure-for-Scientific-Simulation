# Published KI acceptance: desktop/KDT contract mismatch


Latest status, 2026-10-13: another real GUI retry completed at approximately **22:31 China time** on the frozen v42 development host. It checked **all 127 model packages: 110 passed publication checks, 17 were rejected**. Candidate main remains `889a6e70332e31b21911efb0a08ac2fa2a067e03`; it was not activated. Active snapshot/source remain `e3ed93f067f2f2693294d0ff5d1f98ad` / `8352acb8a7e8d1842356e021a783864917ab1efe`. The new full report is `C:/Users/Administrator/AppData/Roaming/KISS/ki-updates/quarantine/b66bd22f3df4/validation-report.json`; screenshot `D:/GeoForge-Setup-Tracer-20261010/v43-update-attempt-rejected.png` records the GUI result. The v43 prefix identifies this audit attempt, not a new host source version. No new model run, activation, push or release occurred in this retry.

The completed fresh-project DSSAT v41 reference run used the retained active source plus its reviewed portable repair. It proves that workflow, **not native E2E after activation of the rejected main revision**. A genuine post-update acceptance test still requires successful activation, a fresh project whose KI/helper provenance binds to that new snapshot, current data/runtime preflight, and new approved native output plus reader receipts. Existing completed projects must remain preserved. Repeating a retained-source run does not close that missing activation proof.

## Current server-agent handoff: 17 package-contract findings

Main commit: `889a6e70332e31b21911efb0a08ac2fa2a067e03`; raw Windows guidance: `1136e56e6bf27b8361d7495a80904c31529afd59`. The complete candidate is retained at `C:/Users/Administrator/AppData/Roaming/KISS/ki-updates/quarantine/c4a5ae135ab6`; its `validation-report.json` is the full report. Desktop evidence: `D:/GeoForge-Setup-Tracer-20261010/v9-update-report.json`, `v9-full-validation-result.jpg`, and `v9-crhm-before-update.json` / `v9-crhm-after-update.json`.

| Packages | Current finding / action |
|---|---|
| DSSAT, HEC_RAS, LDNDC, RZWQM2, SHAW, SimFire, SUMMA, SWAT_Plus | Regenerate stale public-tool indexes/counts through KDT. These findings alone do not show that a model failed to run. |
| VIC, WRF_Hydro | Emit the structured preflight report around the real checks; WRF_Hydro also has a stale tool count. Preserve failure exits and actual installation/input checks. |
| EPIC | Regenerate its tool index/counts and resolve the paper declared both deferred and validation evidence from authoritative authoring records. |
| EF5 | Supply the correct canonical DAG. Do not restore the quarantined wrong-model HYPE descriptor. |
| VELMA | Clarify the discharge output's water medium in the canonical DAG and regenerate its format projection; preserve scientific units and conversion. |
| BMI, ESMF, PyMT | Reconcile the authoritative framework/coupler KI kind with the desktop's supported package contract. Do not invent process-model evidence for libraries. This requires exporter/desktop agreement, not merely editorial changes. |
| Climate_Projection | Reconcile the task/workflow kind and the complete preflight/template/output/manifest findings in the full report using authoritative KI records. |

CRHM and WOFOST passed publication checks in this attempt. SHAW, DSSAT, VIC and WRF_Hydro did not. These are package-contract results, not runtime, database, calibration or new-site results.

The downloaded packages do not include the gathered-paper authoring evidence required by the normal KDT edit/adoption gate. Use the original authoring packages on the server, apply changes through KDT with the agreed independent reviews, regenerate derived files, and return the exact commit and gate reports. Do not fabricate literature records, transfer publication receipts to edited drafts, or publish this Windows-composed quarantine as the main authoring source. After publishing, retry the desktop GUI pull, then run fresh-project setup and actual reference cases against the activated revision.

The earlier four-package result below used intact existing baselines for 106 packages. That shortcut has been removed; it was not evidence of current KDT acceptance. The new 17-package result is the complete current acceptance check, not evidence that 13 models newly broke.

## Earlier four-package triage (same main commit, partial fresh validation)

Checked main: `889a6e70332e31b21911efb0a08ac2fa2a067e03`. Raw Windows guidance: `1136e56e6bf27b8361d7495a80904c31529afd59`. The fresh GUI attempt retained its complete candidate at `C:/Users/Administrator/AppData/Roaming/KISS/ki-updates/quarantine/1b6f7bc33d2f`; full result is `validation-report.json` there, also captured by `D:/GeoForge-Setup-Tracer-20261010/v8-update-report.json`. The update stopped at `package_validation`, after successful authenticated composition. The table refers to paths within that exact candidate.

| KI | Independently checked cause | Requested upstream correction through KDT |
|---|---|---|
| DSSAT | 20 public tools shipped; `SKILL.md:71` reports 19 and its generated index omits `tools/run_reference_case.py`. `knowledge_infrastructure.yaml:29` and `:241` still report 19; its tool list also omits the runner. | Regenerate the index and manifest, including the exact runner path and invocation; both counts become 20. Preserve the runner and scientific checks. |
| SWAT_Plus | 39 public tools shipped and indexed; `tools.count` and the file list agree. Only `knowledge_infrastructure.yaml:178` has stale `summary.total_tools: 40`. | Regenerate the manifest so the summary agrees at 39. |
| VELMA | `dag.yaml:262` already describes daily outlet discharge derived from runoff, but the KDT medium check searches literal words and does not recognize `discharge` or `runoff`. This is wording, not demonstrated bad runoff output. | Use an explicit scientifically accurate description, e.g. “Daily stream-water discharge at the watershed outlet …”; regenerate the matching `docs/format_spec.yaml` projection and rerun KDT. Do not change units/conversion or scientific bands. |
| VIC | `preflight_check.py:113–155` prints text and exits without emitting `PREFLIGHT_REPORT=` JSON. It imports no delegated reporter. `SKILL.md:29` and `:215` nevertheless promise that contract. The installed reviewed KDT independently requires it. | Preserve the real checks and add the structured report before either success/failure exit, with model ID and per-check kind/subject/critical/status/fix. Test both passing and failing checks. A comment containing the marker is not a repair. |

For the server agent: start from the current main version, confirm these findings still apply, make the corrections using the normal KDT edit/review workflow, regenerate dependent projections, and verify the final exact bytes. Return commit IDs and gate reports. Do not replace the KI with this quarantined desktop copy, because it includes separately composed Windows metadata. No model execution or database call was used for this triage, and none of these four findings establishes that scientific execution failed on the web server.

After those fixes are published, retry **KI updates → Check again** in GeoForge, then perform fresh-project setup/verification and reference-case execution against the actually activated snapshot. Keep the old project pinned during that test. The current pull alone does not complete that fresh E2E sequence.

The sections below retain the earlier 2026-10-10 attempts and design evidence. Their 110/17 and 108/19 figures are historical results from different attempts, not the current result above.

## Reproduction and verdict

The Windows GUI updater downloaded official main `889a6e70332e31b21911efb0a08ac2fa2a067e03`. The first attempt stopped on 11 reference-path occurrences across six KIs. Narrow classifier fixes, independent review and negative regressions removed those false positives without editing the KIs. The next attempt reached KDT and failed on ADCIRC with GBK decoding errors and a missing `docs/gathered_papers.json`.

The Windows encoding issue was fixed in the host's private verifier view. At that stage, a real ADCIRC structural recheck against reviewed KDT `631e5c50cb0cd812447f67358dd9c162658155ea` had no decoding error and no blocking doctor finding; its only remaining KDT failure was the gathered-papers requirement. The original candidate and engine were unchanged; no scientific model was executed.

This is a contract mismatch, not evidence that ADCIRC lacks a bibliography:

- `kiss/kiss_cli/papers.py:53` intentionally exports gathered records to `docs/papers.json`, removes `text_path`, and publishes DOI/title/access/role/serves metadata without private extracted texts.
- The root README documents that metadata-only distribution.
- Pinned KDT `verify_ki_structure.py:269` and `:501` count/require `docs/gathered_papers.json`; `dissection_spec.py:906` defines it as gathered/read literature with genuine fetched-text provenance. There is no documented published-package verification profile in this pinned engine.
- The exact ADCIRC candidate has 20 published paper records containing all six validation-reference DOIs. Four additional DAG citations are explicitly deferred/paywalled. Preserve that distinction; it is not permission to invent fetched-paper records.

Simply renaming the file, inventing `text_path`/retrieval status, or filtering the KDT failure would misrepresent the evidence. That retry correctly stayed blocked. The mismatch is separate from Windows runtime readiness and can affect other operating systems using the same authoring gate.

## Implemented published-package contract

GeoForge now has an explicit private publication profile for the exact reviewed KDT source. The installed upstream engine has not been edited and still has its original authoring contract. An upstream native publication profile remains a possible future replacement; the local implementation fails closed if the reviewed engine source changes.

- `kiss/kiss_cli/published_kdt.py` checks the exact normalized source hash of KDT `631e5c50cb0cd812447f67358dd9c162658155ea`, applies three reviewed literal literature changes, and compiles a private `verify` function with the existing host runtime view. All unrelated structural, source-equivalence, tool-index, diagnostic and preflight-contract checks remain. A process model still requires its validation convention; supported task-workflow literature remains advisory. Neither KI bytes nor engine bytes are rewritten. There is no filename alias, fabricated fetched-text record or failure-prose filter.
- `published_literature.py` validates the actual `docs/papers.json` exporter schema, package/model identity, counts, normalized DOI uniqueness, metadata types, roles/quantity-list types and declared citation keys. Its current policy is `published-literature-v2-exporter-parity`. A DOI declared in the DAG or validation convention but not duplicated in `papers.json` is an explicit audit warning with coverage counters: the exporter and pinned KDT do not require that duplication. Unknown citation keys, malformed metadata and a paper declared both deferred and validation evidence still fail. Title-only records are supported because `Paper.from_gathered` permits a title without a DOI; these and unknown DOI sentinels are reported without becoming DOI matches or fetched/read evidence. This corrects the additional closure requirement introduced by the historical v1 checker; it does not filter KDT failure text or alter scientific bands.
- `published_acceptance.py` has a separate policy, signature authority and result scope. Only the official updater issues the internal origin after extracting an exact official commit. It binds archive hash, source/effective snapshot hashes, package digests, component trees, overlay provenance and the reviewed verification implementation. Publication reports say `PublishedPackageAccepted`, `authoring_verification=false` and `published_metadata_only`; native/scientific execution is not claimed.
- Existing Windows notes/recipes from a host-enrolled KI still require that exact source to be intact. A missing baseline has a separate narrow route in `platform_guidance_provenance.py`: authenticate every selected guidance input against the fixed official Windows-branch commit/tree obtained through the updater's verified HTTPS transport. Local Git is only a byte store; each traversed tree/blob is hash-checked against that official tree, with exact bytes or an explicitly recorded CRLF/LF-only conversion. The signed evidence records the commit, blob SHA-1, official/local SHA-256 and conversion. Bounded requests/objects and an implementation-bound immutable proof cache avoid repeated network work. The helper checks current input bytes again and never enrolls or trusts the surrounding KI. A registered but changed/invalid baseline cannot use this fallback. Ordinary generic guidance outside a KI retains the signed first-use host inventory route. Source evidence has its own scope; neither route relabels the entire host library as official source.
- Activation requires a signed snapshot envelope covering every package and the complete effective snapshot. Under policy `official-published-ki-v2` and contract `all-packages-current-published-kdt-v1`, every incoming package must have a current signed publication report bound to its exact official origin and digest. Prior integrity is checked separately; an unchanged baseline cannot replace current KDT acceptance. Enrollment accepts publication evidence only at the matching managed snapshot revision, package name and digest. Copying a receipt elsewhere, changing bytes, or stripping the receipt/policy cannot recover an unsigned legacy acceptance path; old unsigned caches must be checked again.
- Studio, arbitrary imports, edits, repair adoption and `ki_verification.current_report` retain the authoring gate. Publication evidence cannot satisfy those paths. The publication profile fingerprint includes the host profile, metadata checker and acceptance implementation; it is captured before checking and compared afterward, so a verifier change during a check cannot be signed as a pass under the new identity. Snapshot reuse also requires current engine and doctor evidence.
- The updater aggregates all package failures for the handoff while refusing the complete activation if any package fails. It does not silently install only the passing subset.

Host signatures provide an application evidence boundary, not an OS sandbox against other programs running as the same user. Publication acceptance remains distinct from installed-runtime verification, the signed exact-project receipt, reference-case success and scientific evaluation.

## Contained aliases and Windows copy boundaries

Three older packages exposed a separate app issue: their same-KI tool-directory aliases were previously rejected by the tree identity, and older extraction could create link objects whose spelling was not traversable on Windows. Fresh extraction now creates native relative links. `ki_tree.py` walks canonical files once and records contained aliases as path/target relationships in a separate hash domain; link-free package hashes remain compatible. It rejects escape, absolute/drive targets, missing targets, chains, traversal cycles, junctions and unsupported reparse points. A link must physically resolve to the expected canonical file/directory on the current host. Old malformed quarantines are retained unchanged and remain blocked.

`ki_copy.py` preserves validated aliases across verification, import/export, materialization, repair/review copies and calibration setup. Copy and materialization reject a destination junction before resolving or writing to it. Reviewer aliases point only to the filtered/redacted context; omitted credentials/binaries do not become accessible through them. The safe verification preflight and calibration adapter detach their owned file aliases before replacement, avoiding accidental overwrite of other canonical tools. Calibration currently rejects an aliased `tools` root rather than guessing how to replace that directory. These checks preserve the existing KDT, integrity and exact-project gates; an alias is not evidence of installed software.

## Verification evidence

The earlier combined publication/update/classifier/authoring/project-guard suite passed **375 tests and 2 subtests**. It includes exact-source and AST-difference checks, unrelated KDT failures, metadata and citation negatives, publication/authoring crossover, Studio/import/repair rejection, receipt tampering, changed package bytes, source baselines, unsigned-cache downgrade prevention, verifier-fingerprint races and existing project execution gates. Structural-engine doubles are explicit in transport/boundary fixtures; hashing, signatures, enrollment and activation checks remain real. The pinned-source profile has separate tests, including an unchanged real ADCIRC source fixture that passes publication structure while still failing the default authoring requirement.

Subsequent independent checks passed **90 metadata/profile tests**, **25 guidance-provenance tests** and, after the final junction/calibration corrections, **72 alias-lifecycle/materialization/tree/extraction tests with 1 POSIX-only skip**. The last group includes real Windows junction and symlink fixtures. Independent review found and then confirmed fixes for physical link-target mismatches, destination-junction writes and adapter writes through file aliases. These are overlapping app-boundary suites, not a unique combined test total or model runs.

The earlier setup/runtime/GUI/execution/calibration suite passed **919 tests, 29 POSIX-only skips and 45 subtests** before this publication slice. Its results remain relevant to those unchanged boundaries; the final 375-test run rechecks the selected project guards with publication integration. These overlapping suites must not be added into one unique test total. Neither suite is native model or scientific E2E evidence. Independent review found no remaining blocking issue in the bounded implementation.

## Published metadata audit and server handoff

The current [v2 read-only audit JSON](D:/GeoForge-Model-Tests-20261010/published-literature-audit-v2.json) records every result against unchanged `D:/GeoForge-Model-Tests-20261010/ki-updates/quarantine/f00153640bfd`: **127 process-model KIs checked, 121 passed, 6 failed, 254 warnings**. It supersedes the [historical v1 audit](D:/GeoForge-Model-Tests-20261010/published-literature-audit.json), whose **49 passes and 78 failures** included the additional cross-file DOI-duplication requirement described above. No KI changes account for this difference; the v2 artifact verifies the metadata inputs stayed unchanged. Neither audit is full KDT acceptance, activation, installation or native/scientific validation. They executed no candidate/model code, created no receipt and changed no KI source. The snapshot had no `kiss/data_kis` component; no fallback data-KI catalogue was substituted or tested.

Examples for the server agent, with full paths and all findings in that JSON:

| KI | Published metadata finding |
|---|---|
| BMI, ESMF, PyMT | Required process-model bibliography, convention and DAG documents are absent. Check the intended package kind before treating these as scientific process models. |
| Climate_Projection | Required process-model convention is absent. |
| EF5 | `dag.yaml` is absent; this is a missing/quarantined DAG issue, not an alias-extraction problem. |
| EPIC | DOI `10.13031/2013.23153` is declared both deferred and validation evidence. |
| CRHM, SHAW, VIC, DSSAT | Pass v2 metadata validation with explicit exported-bibliography coverage warnings. The detailed missing DOI records remain in the audit for reconciliation; they are no longer extra publication blockers. |
| ADCIRC, WOFOST, WRF_Hydro | Pass this metadata audit; that does not establish full package or runtime success. ADCIRC's four explicitly deferred DAG papers remain warnings, not invented fetched evidence. |

Send the v2 audit JSON with this handoff. The server agent should reconcile the six failures and optional bibliography-completeness warnings against authoritative authoring records and the exporter, then make any KI correction through the normal KDT/review workflow. Establish whether a reference belongs in the exported bibliography, is wrong, or is genuinely deferred; do not add invented entries or change scientific bands to turn the gate green. A deferred paper cannot substitute for evidence claimed by a validation convention. Preserve the distinction between missing published metadata and an unavailable scientific paper.

A separate [read-only full structure audit](D:/GeoForge-Model-Tests-20261010/published-structure-audit.json) of that old quarantine recorded **108 passes and 19 failures** through KDT plus doctor with the safe host preflight stub. This includes three old physically broken alias trees; those archived objects were not repaired, so the result is not a verdict on a fresh extraction. Other failures concern package structure, counters/indexes, preflight contracts, kind/DAG requirements and the EPIC contradiction. The audit is unsigned, performed no candidate/model execution and did not activate a library. Its result must not be substituted for the fresh GUI pull outcome.

## GUI retry and remaining E2E work

The fifth GUI attempt, started at 15:25:04 China time, completed the complete package check against official main `889a6e70332e31b21911efb0a08ac2fa2a067e03`: **110 `PublishedPackageAccepted`, 17 `PublicationRejected`, zero activation**. The archive SHA-256 is `8a373ec514a8ede5d22ae73da31994d9af14219b4f7ffc48a4750cb6ffa26213`. Retained Windows guidance was authenticated against official Windows commit `1136e56e6bf27b8361d7495a80904c31529afd59`. All six internal directory aliases extracted correctly; CaMa_Flood and Lohmann_Routing now pass package checks. VIC passed alias handling but exposed its separate missing preflight-report contract.

The [GUI evidence manifest](D:/GeoForge-Model-Tests-20261010/gui-test-report.json), [screenshot](D:/GeoForge-Model-Tests-20261010/final-pull-verification-v5.png) and [complete rejected-candidate report](D:/GeoForge-Model-Tests-20261010/ki-updates/quarantine/2356a31713e0/validation-report.json) preserve the result. The update home has no activated `state.json`; no fresh project or scientific output was created. The GUI's two data KIs remain bundled fallbacks; the downloaded archive still has no `kiss/data_kis` component.

The final combined regression suite passed **522 tests, 1 POSIX-only skip and 2 subtests in 56.88 seconds**. A final presentation-only change then passed all **29 update UI tests** and was checked in the live browser: a concise rejection count precedes the complete expandable diagnostics. These tests overlap earlier counts and are not scientific model results.

| Fresh-pull package | Remaining verification finding |
|---|---|
| CRHM, WOFOST, ADCIRC, CaMa_Flood, Lohmann_Routing | Publication checks passed; runtime/E2E was not run. |
| SHAW | Manifest declares 13 tools; the shared counter finds 12. |
| DSSAT | New `tools/run_reference_case.py` is missing from the tool index; manifest declares 19 versus 20 tools. |
| VIC | Preflight prints human-readable status but does not emit the required `PREFLIGHT_REPORT=` record. |
| WRF_Hydro | Same preflight-report gap; manifest declares 17 versus 16 tools. |
| HEC_RAS, EPIC | Newly shipped conversion tools are absent from indexes/counts. EPIC additionally names DOI `10.13031/2013.23153` as both deferred and a validation reference. |
| LDNDC, RZWQM2, SimFire, SUMMA, SWAT_Plus | Stale manifest tool counts. |
| EF5 | Required `dag.yaml` is absent. The package explicitly quarantined the wrong HYPE descriptor as `dag.yaml.WRONG-MODEL-HYPE`; it must not be restored as EF5 evidence. |
| VELMA | Output `Q_sim_m3s` does not identify its medium in the canonical DAG description. |
| BMI, ESMF, PyMT | Missing preflight/report/template/model documents under the desktop's default process-model contract. These are framework/coupling packages: reconcile authoritative KI-kind export and desktop kind support before imposing simulation-only requirements. |
| Climate_Projection | Multiple template, preflight, manifest, diagnostics, output-format and validation-convention mismatches; see complete report. |

The bundled and freshly downloaded `ki_projection_common.py` are identical after CRLF/LF normalization. The reported counter mismatches are not explained by a different counter implementation in this attempt.

### Server-agent work order

Use main `889a6e70332e31b21911efb0a08ac2fa2a067e03` and the full validation report to reproduce the 17 package-contract failures. Regenerate derived tool lists/counts using KDT's canonical projectors; do not merely change declared numbers. Repair preflight reporting around real checks, retaining failure exit codes and the distinction between software installation and project input readiness. Resolve EF5, VELMA, EPIC and Climate_Projection from authoritative KI evidence. Export explicit authoritative KI kinds for framework/coupler packages and agree the supported desktop contract; do not invent simulation DAGs for libraries. Apply every KI edit through KDT with the agreed three independent full-context reviews. Publish only honest authoring/structural evidence, not fabricated native-run or fetched-paper evidence. Then repeat the GUI pull, verify exact Windows runtime bindings, and perform fresh project/reference-case and new-site E2E tests with saved outputs and readers.

After package acceptance, verify local runtime bindings, create a fresh project, verify that project's exact KI and configuration, and run fresh outputs through the native reader. DSSAT mandatory assets, WOFOST compatibility and a supported WRF-Hydro execution binding remain separate work. Historical output, bibliography checks and package import checks cannot substitute for a fresh reference case or new-site E2E run.

## WOFOST follow-on

The downloaded WOFOST still derives Unix-style paths and demands Python 3.12, while the inspected Windows installation is Python 3.13 with PCSE 6.0.13. The candidate runner also lacks the checkout's soil/site parameter separation; the shipped soil contains keys that conflict with `WOFOST72SiteDataProvider`. These are source findings, not fresh model outcomes. They require reviewed runtime/KDT work after package acceptance is resolved. See `D:/GeoForge-Model-Tests-20261010/wofost-source-audit.json`.

No release, push or KI-source repair was performed as part of this investigation.
