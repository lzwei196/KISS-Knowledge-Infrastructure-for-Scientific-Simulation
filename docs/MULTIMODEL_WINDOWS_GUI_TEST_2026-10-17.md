# Windows GUI / DeepSeek multi-model test — 2026-10-17

## Verdict and scope

**Latest continuation, 2026-10-18:** Disk cleanup allowed the real SHAW GUI/DS
tracer to finish: Setup and project KDT, fresh project preflight, one original
Trial native execution, five CSVs from the unchanged KI reader, and a result
figure. Independent comparison verified all mapped CSV values/dates and all
eleven soil nodes. Strict reference acceptance still fails one original check:
out.out has 601 lines rather than 599; all four numeric checks pass. These are
source-GUI results, not a new release or all-model acceptance.

The subsequent read-only discussion exposed an actual lifecycle bug: DS could
revoke approval and rewrite a plan. The old approval remains revoked and the
new draft unapproved; historical evidence is preserved without restoring
authority. Immutable read-only turns, explicit next-phase archiving, and bounded
outputs/ media discovery are now implemented and regression-tested. Final GUI
acceptance and its precise scope are recorded at the end of this report.

**Tracer-bullet update, 17:17 local:** EPANET's GUI Setup now completed the real
DeepSeek → three independent reviews → KDT verification → guarded adoption →
fresh host preflight chain. All **13 preflight checks passed** and the GUI shows
“已在本机验证”, with no outstanding user action. This closes the Setup maintenance
handoff for the supported EPANET repair. It is not proof that all model KIs or
new scientific projects are end-to-end ready.

## Initial multi-model findings (before the tracer repair)

**EPANET's native case and KI reader passed independent numerical checks; SHAW
produced reference-matching core numerical results, with remaining failures.**
No new host-approved **project E2E** has completed. Installation, KI selection
and failure recovery were exercised through the source GUI with DeepSeek at
`http://127.0.0.1:8800`. Published Windows **0.6.60 is unchanged**.
WRF setup was cancelled for disk capacity, DSSAT is paused, EPANET is held by
preflight/maintenance integration, and SHAW finished with failed preflight.
This does not claim all shipped KIs, other operating systems, scientific
accuracy beyond the reference cases, or a tested new release installer.

- Isolated run root: `D:/GeoForge-MultiModel-Fresh-20261017`.
- Only released settings and KDT engines were copied into the new profile.
  No installed model, project, verification receipt or prior output was reused.
- Official main selected: `da6a06f68971b7ba0fe261189ee83f80e682deb6`.
- WRF-Hydro selected scope: `4db30b5775f9f8c992cc251db01a527f`.
- DSSAT selected scope: `7f507c86954e19ca21ad6aa3463c663c`.
- SHAW post-fix selected scope: `183e548ba3950ab1b3de84989b21f8e8`.
- EPANET selected scope: `0e43efd56b8a66892a884f43c0b925d5` (same main revision).
- The full-library update still rejected six packages: **BMI,
  Climate_Projection, EPIC, ESMF, MODFLOW6 and PyMT**. Scoped selection did not
  turn that full-library failure into a pass. No new data KIs were delivered.
- Source/release-baseline `__pycache__` artifacts are baseline state, **not a
  newly established 0.6.60 release defect**, and are excluded from this round's
  regression count.

## Actual GUI observations

| Model / attempt | Observed result | What this establishes |
|---|---|---|
| WRF-Hydro, latest selected KI | Python and shared-helper preparation succeeded. Host `make`, `gfortran`, MPI and netCDF requirements were missing. Partial DS tooling work was cancelled when D: was almost full. | Partial setup only; no native run or reader acceptance. |
| DSSAT, original D: workspace | WinLibs downloaded; disk exhaustion left partial extraction and missing CRT files. | Toolchain installation failed; this is not a DSSAT simulation result. |
| DSSAT, new C: workspace | GUI rebound setup to `C:/GeoForge-Tests-20261017/DSSAT`; the fresh binding was validated. An archive downloaded, but setup ended with failed preflight and requested system tools. | Root rebinding worked; installation readiness is still unproven. |
| DSSAT recovery | GUI Help opened discussion `81fe4317c7ff`. Three DS turns ran in project `PLANNING`, without installer tools; the third repeated the write-boundary issue despite persisted choices A/A2. The decision card is preserved and DS is now idle. | Actual direct-resume routing gap, not lost choices or established DS amnesia. Ordinary project-plan approval can eventually enter setup, but Help did not directly resume the installation attempt. No new DSSAT binary exists in the C: root. |
| SHAW selection | Before the host correction, GUI refused selection with `Official installation manifest is missing: SHAW`. After correction, the same official revision passed real package/KDT checks and opened a new selected scope with “需要手动设置”. | Confirmed GUI recovery. It remains unverified software; 55 regression tests (40 existing + 15 new) and independent review passed. |
| EPANET latest selection and fresh setup | Selection passed. DS built genuine OWA EPANET v2.2 with MinGW, then staged the binaries and ran the official tutorial plus KI reader. Independent audit confirms all 83 values, 16 expected checks and 1,225 exported numeric fields. | Native case and reader passed; three host preflight path/layout checks still fail, so installation/project readiness is not granted. |
| SHAW native Trial | DS obtained the official distribution and ran the shipped Trial. Independent audit confirms all five input hashes, all four core numerical checks, and 301-row temperature/moisture tables with 11 depth nodes. | Native output verified; `out.out` has 601 vs 599 lines, official-reader output is not established, and final preflight has 6 critical failures. |

Observed source GUI behavior must not be attributed to the unchanged published
installer. A downloaded archive, prepared Python environment or completed agent
turn is not equivalent to current preflight plus successful native execution.

The SHAW host correction accepts an absent installation recipe using the same
unverified, in-memory fallback as ordinary setup. A malformed existing recipe
still fails. It neither edits the KI nor skips publication/KDT verification.
The 55 regression tests used an isolated source overlay and a synthetic KDT
engine, with real scoped builder/signing and negative-gate tests. Independent
review found no blocker; this does not count as native SHAW verification.

The first post-fix GUI retry failed during archive extraction with actual
`[Errno 28] No space left on device`. The archive is 137.33 MiB, expanding to
244.0 MiB, exceeding the remaining D: capacity together. The test launcher's
update home was then changed to `C:/GeoForge-Tests-20261017/ki-updates-shaw`;
only the archive cache was copied and official selection was requested anew.
Existing D: profiles, projects and failed-attempt evidence were retained.
The subsequent real GUI selection succeeded with KDT engine
`631e5c50cb0cd812447f67358dd9c162658155ea` (`engine_override: false`). Its SHAW
receipt states `PublishedPackageAccepted`, `kdt.ok: true`, desktop checks passed,
and `native_regression: not_run`. Through the GUI, root was saved as
`C:/GeoForge-Tests-20261017/SHAW`, then DeepSeek setup started. DS independently
identified the `python_env/bin/python` versus `venv/Scripts/python.exe` mismatch
and read the shipped Trial reference-case files. That diagnosis is not a run.
Independent read-only inspection confirmed all host records agree on the C:
SHAW workspace, and all nine case-package files match the selected source.
SHAW's official distribution initially downloaded only 4,832,807 bytes in 240
seconds; DS resumed and completed the 14,071,821-byte archive, then produced the
native Trial output described below. The acquisition delay was real network
throughput, not a missing forcing dataset.

## Independently retained native evidence

### EPANET

- Workspace: `C:/GeoForge-Tests-20261017/EPANET`.
- Source: OWA `v2.2`, local HEAD `4d8d82ddc260fce216af9321fc3d9a4646ac6827`;
  Release/MinGW build recorded in `source/EPANET-OWA-v2.2/build2/CMakeCache.txt`.
- Actual AMD64 PE executable and DLL exist; staged binaries match build bytes.
- Retained results: `outputs/tutorial/tutorial.rpt`, `tutorial.out` (binary),
  `csv/nodes.csv`, and `csv/links.csv`.
- All 83 official excerpt values agree at printed precision (maximum difference
  0.00); all 16 additional checks pass. Both CSVs have 175 rows, 7 IDs and 25
  hourly timestamps; all 1,225 numeric fields agree with the saved report.
- The binary output is 9,976 bytes with EPANET magic `516114521`. The report
  records completed analysis with no Error lines.
- All 27 active KI files match their retained host baseline. The attempted
  direct KI edit did not change them. Candidate text in `.kdt-drafts` is not a
  verified/adopted KI repair.
- Latest final preflight: `.geoforge/preflight/2855f00c8dfb/execution.json`,
  return code 1, source intact, no readiness receipt. The binary location,
  Linux `.so` and source-tree tutorial checks remain failed.
- DS's initial claim that the historical USEPA commit did not exist is not
  established by its shallow checkout; this report does not repeat that claim.
- Plot of the retained KI-reader CSVs: run-root
  `figures/epanet-real-tutorial.png` (also SVG, with hash provenance JSON).
  Plot generation did not run the model or change the KI.

### SHAW

- Native output: `C:/GeoForge-Tests-20261017/SHAW/build/runs/trial_reference`.
- Independent calculations: cumulative ET **4.0 mm**, water-balance error
  **0.0 mm**, final snow depth **4.5 cm**, final SWE **9.2 mm**; all equal the
  case's recorded expectations. Both profiles contain 301 rows / 11 nodes,
  from day 338 hour 12 to day 350 hour 24 in 1986.
- Five output line counts agree; `out.out` is **601 vs 599**. The strict
  reference check therefore remains failed. No official-reader CSV is proven.
- Native exit code zero is DS-reported; saved numerical output was independently
  verified. Do not treat the report as a signed native execution receipt.
- Windows path contradiction: preflight line 29 requires
  `model/shaw/shaw303` to be a file, while line 31 and lines 262–264 require
  `model/shaw/Shaw303` to be a directory with the five inputs. They resolve to
  the same directory on this filesystem. The runner shares the lower-case
  default. This cannot be fixed by copying another executable over the directory.
- Final preflight `3c9a606a9666`: **30 pass / 6 critical fail**. One is the
  file/directory collision; five use obsolete `python_env/bin/python` rather
  than the valid bound `venv/Scripts/python.exe`. Source intact, no readiness
  receipt. An extensionless real binary's startup check now passes; extension
  absence alone must not be blamed for the remaining failures.

## Latest KI source checks — not executed

The extracted latest catalog is retained at:
`D:/GeoForge-MultiModel-Fresh-20261017/profile/KISS/ki-updates/quarantine/df7b30a44791`.
Paths in this section are relative to that directory. Quarantine is evidence,
not an activated library or permission to bypass verification.

Nine relevant DSSAT/SHAW files were compared with downloaded main `5d1f6b5`;
all nine SHA-256 hashes were unchanged. The current findings are therefore:

- **WRF-Hydro:** all 49 KI files also match the prior inspected `5d1f6b5`
  baseline. `kiss/manifests/WRF_Hydro.yaml:3` declares Mach-O/ELF; lines 25–28
  require Fortran, MPI and netCDF tooling. There is no matching Windows recipe
  or bundled `DOMAIN`/`FORCING`/`.TBL` reference-case input set. In
  `models/WRF_Hydro/preflight_check.py:25`, the binary/launcher bind to the
  `wrf_hydro/source/trunk/NDHMS/Run` and `deps/mpich-install` layouts; line 28
  uses the legacy Python token and lines 30–36 require five runtime tables.
  The `.exe` suffix does not establish a Windows binary or compatible build.
- **DSSAT preflight:** `models/DSSAT/preflight_check.py:205` checks `MODEL.ERR`;
  lines 206–213 also require the China cultivar directory and four cultivar
  files, including when the small runner uses its generic `IB0035` cultivar.
- **DSSAT temporary paths:** `tools/run_reference_case.py:363` and
  `tools/dssat_workdir_setup.py:1178` still force `/tmp`; the latter uses
  unconditional `os.symlink` from line 1211. These are Windows compatibility
  concerns identified by reading code, not new observed native failures.
- **DSSAT delivery:** the Windows manifest has neither `runtime_paths` nor
  `runtime_data`. There is no `test_cases` package. A bundled generic soil and
  `tools/run_reference_case.py` exist, but that runner fetches public weather.
- **SHAW paths:** `models/SHAW/preflight_check.py:22` constructs
  `ROOT/python_env/bin/python`; lines 26–31 construct the server binary and
  distribution layout. Ordinary token substitution does not infer these roles.
- **SHAW interfaces:** downloaded `s6_execution/tools/run_shaw.py:271` has no
  `--inp_file` argument and regenerates the control file. Do not assume the
  patched bundled-source interface is present in this new KI.
- **SHAW data/reader:** all five official Trial input hashes match the case
  manifest. `parse_shaw_output.py:45` explicitly reads `DAY HR YR`; the older
  shifted-column reader is not the version inspected here.
- **EPANET:** `models/EPANET/preflight_check.py:20`–28 assumes an extensionless
  executable and `libepanet2.so`; lines 149–169 require that library and a
  source-tree tutorial despite a complete bundled reference case. Windows
  binary binding is supported by the runner's explicit `--binary`, but that
  does not resolve the preflight's library/layout assumptions. These static
  concerns are distinct from the source-build discrepancy observed by DS.

## Reference-case delivery and current acceptance

| Case | Verified delivery | Remaining qualification |
|---|---|---|
| SHAW `test_cases/trial` | Five authentic input files, hashes matched; JD338–350, 1986. Fresh output matches ET 4 mm, snow depth 4.5 cm and SWE 9.2 mm. | Native core values passed; strict output-line count, Windows preflight and official-reader acceptance remain incomplete. |
| CRHM `test_cases/badlake` | Official project plus 1.9 MB observation forcing; both hashes matched; three HRUs, hourly 1973–1976. Windows recipe exists. | Practical Windows fallback. Expected output is tied to v4.7_16; a different build needs numerical review, not blind whole-file-hash acceptance. |
| EPANET `test_cases/tutorial` | Official 1,316-byte input and 4,105-byte reference excerpt, hashes matched; 24-hour network, 83 reference numbers. | Fresh native case and KI reader passed; host preflight still requires Linux `.so`/build paths, so project readiness is not granted. |

Delivery checks alone do not count as case execution; the separate native
evidence above establishes the EPANET and SHAW results. EPANET's retained
`.rpt`, binary `.out`, `nodes.csv` and `links.csv` support the reader audit and
figure. Its bundled reference runner deletes temporary output, so its initial
reported pass alone did not establish retained project evidence.

## App gaps and next acceptance checks

| Gap | Evidence / classification | Required next check |
|---|---|---|
| Missing installation recipe blocks KI selection | Observed SHAW refusal in the earlier [closure check](../kiss/kiss_cli/scoped_ki_updates.py#L60); correction is applied and real GUI re-selection passed. | Closed for KI selection; native setup and case execution remain separate requirements. |
| Setup Help lacks direct installation continuation | Observed: discussion `81fe4317c7ff` used project `PLANNING`, lacking installer tools; A/A2 remained saved. Ordinary project-plan approval is a longer possible route. | Restore the correct bounded setup context for direct retry; preserve existing decisions and required approvals. |
| Setup cannot hand a KI repair to KDT | EPANET received explicit KDT-only repair approval, preserved it, blocked direct KI writes, and prepared Markdown; then asked for the same approval again. | Add a host-controlled Setup repair handoff: review → KDT verification → adoption → fresh preflight. Repeated approval is not the missing capability. |
| Setup inventory and command allowlist | Setup difficulties observed; [setup dispatch](../kiss/kiss_cli/api.py#L2401) separately enforces executable admission. | Ensure DS sees supported installation operations and receives actionable denials; do not bypass the boundary through child scripts. |
| Tool-result diagnostics | Installation/preflight failures are real; an agent completion message alone is insufficient. | Surface the concrete current error and preserve it through Help/continuation. |
| Local system-dependency binding | [Dependency check](../kiss/kiss_cli/install.py#L176) uses host `shutil.which`; this is a code finding. | Verify explicitly bound workspace compilers/libraries are recognized consistently by setup, probes and model launch. |
| Disk-capacity preflight | D: extraction failure and cancellation were observed. | Check download/extraction capacity before large acquisitions; report partial state and recover safely. |
| Selection/setup race and stale state | Cross-workspace/scope regression target; not independently established as a separate failure in this report. | A late selection/status response must not overwrite the active scope, root or attempt. |

Correct DSSAT's setup/discussion handoff; complete SHAW setup and Trial; resume
WRF-Hydro only with its actual compiler/MPI/netCDF prerequisites and adequate disk.
For each, require fresh project preflight, native case output, reader agreement
and all mandatory current receipts before reporting end-to-end completion.

The KDT integration gap is confirmed in code: ordinary Setup callbacks expose
only built-in setup and Python preparation (`gui.py:4595`), while project
maintenance requires a saved session (`gui.py:5353`) and the layout
`project/models/<KI>/ki` (`ki_investigation.py:1226`). Setup uses `<setup>/ki`.
`setup.py:1281` delivers the approval note correctly, but `setup.py:1482`
promises a complete KDT loop that Setup's tool surface cannot perform.
Keep the KI-write guard intact and connect the existing verified workflow.

## Local evidence index

- Run audit: `audit/launch-freeze-103855.json` under the isolated run root.
- GUI screenshots: `screenshots/01-wrf-latest-setup.jpg`, `02-shaw-missing-manifest.jpg`, `03-dssat-recovery-repeated-question.jpg`, and `04-shaw-latest-selection-fixed.jpg`.
- Final GUI states: `screenshots/05-epanet-final-gui.jpg` and `06-shaw-final-gui.jpg`.
- Actual EPANET result figure: `figures/epanet-real-tutorial.png`, with SVG and provenance JSON alongside it.
- Update record: `profile/KISS/ki-updates/last-report.json`; selected scope metadata: each scope's `.geoforge-library.json`.
- WRF status: `workroot/scopes/4db30b5775f9f8c992cc251db01a527f/wrf_hydro/status.json`.
- D: DSSAT status: `workroot/scopes/7f507c86954e19ca21ad6aa3463c663c/dssat/status.json`.
- Rebound DSSAT: `C:/GeoForge-Tests-20261017/DSSAT/{kiss.toml,status.json}`.

No credentials or complete provider logs are included in this report.

## EPANET Setup maintenance tracer — implementation and real GUI acceptance

The host now exposes an issue-only repair request to API and CLI setup agents.
The request ends the API tool turn; the host waits until provider workers have
drained, then owns the repair under the same setup lease. Providers cannot supply
an adoption path, fake verification receipt or replacement content through this
capability. Unsupported maintenance remains explicitly blocked.

The common adapter captures one bounded, stable review context and binds the
selected source, effective recipe, saved configuration and helpers. Three
separate agents review that context. A separate deterministic EPANET maintenance
policy changes only recognized path declarations in `preflight_check.py`,
`tools/run_epanet.py` and `knowledge_infrastructure.yaml`; the official case,
scientific calculations and check logic are protected. Existing published
evidence is reused through the maintenance KDT gate, not substituted for native
or scientific validation.

Adoption retains previous KI bytes and outputs, invalidates previous readiness,
and records pending preflight before replacing the KI. Normal setup preflight
then checks the adopted bytes. Authenticated maintenance lineage is separate
from the original upstream projection, so reopening/retrying does not pretend
the repaired KI was generated by the old upstream projection. Unchanged saved
configuration bytes are preserved; real binding changes invalidate the proof.

Real GUI evidence:

- Selected official source remains `main@da6a06f68971` in scope
  `0e43efd56b8a66892a884f43c0b925d5`.
- DeepSeek received the existing KDT-only authorization through the ordinary
  Setup UI and independently submitted `request_ki_repair`. No tool-by-tool
  coaching was supplied during this turn.
- Investigation `2c039bc83c974d53`: all three reviewer roles completed;
  KDT verification succeeded and adoption completed.
- New host preflight `4678cf2d470e`: **13 pass / 0 fail**, real engine startup,
  real DLL and shipped tutorial resolved correctly; saved execution record is
  under the EPANET workspace's `.geoforge/preflight` directory.
- Screenshot: run-root `screenshots/07-epanet-kdt-setup-verified.jpg`.
- Restart/retry acceptance: the test host was restarted and the same GUI showed
  verified status. Clicking “让 Agent 重新检查” created fresh preflight
  `29cc82869892`, again **13 pass / 0 fail**, with unchanged adopted KI digest
  `66ff74f754e28b4384a6a70830bec8413b77de09775ad76432b77eecf458a9d1`.
  Screenshot: `screenshots/08-epanet-restart-recheck-verified.jpg`.
- The agent also invoked the reference helper again before adoption. That helper
  deletes temporary output, so the retained native results and figure from the
  earlier numerical audit are not claimed as newly retained post-adoption output.
- KI tutorial and upstream tutorial differ in LF/CRLF bytes (1,316 vs 1,392
  bytes); normalized text agrees. Byte identity between those two files is not
  claimed.

Validation sets (overlap; do not add these counts): 118 combined setup/bridge/
lineage tests, 101 EPANET/legacy-maintenance tests, and 81 investigation/guard/
adapter tests passed. Independent code review found no blocking issue. These
test fixtures are distinct from the real GUI/KDT/preflight evidence above.

Remaining scope: this is a supported EPANET maintenance recipe plus reusable
Desktop orchestration. SHAW's separate Windows collision, WRF-Hydro toolchain,
DSSAT recovery, new-project materialization and reapplying repairs after a
different upstream revision still need their own acceptance tests. Published
Windows 0.6.60 remains unchanged; no release or push was performed in this turn.

## SHAW continuation — exact repair implemented, GUI adoption pending capacity

The shared Setup review/KDT/adoption lifecycle now recognizes the separate
`shaw_runtime_paths` recipe. The additive maintenance registry preserves the
sealed EPANET validator, old dispatch gate and Setup adapter bytes. Adding SHAW
does not invalidate an existing approved EPANET repair: a read-only check of the
real EPANET adoption `2c039bc83c974d53` accepted its original signed record and
unchanged digest after these additions.

The SHAW recipe accepts only the recognized published implementation. It binds
the saved Windows Python interpreter and installed `binaries/shaw/shaw303.exe`
consistently in preflight, the runner and package manifest. The executable's PE
header is checked before the manifest type changes from ELF to PE. The
case-insensitive `shaw303` file / `Shaw303` directory collision is avoided by
using the existing executable, without relocating the official distribution.
All preflight check logic, reference inputs, numeric expectations and readers
remain unchanged. Both reviewed capitalization-only variants of the official
Trial control file are recognized for the installed distribution; the actual
selected bytes remain part of the runtime identity.

Validation sets overlap: 83 recipe/EPANET/guard tests passed, including 44 SHAW
cases; 59 Setup/investigation/EPANET tests passed, including six SHAW lifecycle
cases. Independent code review found no blocking issue. Read-only recognition
against the real installed SHAW KI returned exactly the intended three changes.
These results are code-level evidence, not a real SHAW KDT adoption or a new
native run. The source host was restarted at 12:45:38 UTC; its freeze is
`audit/launch-freeze-204538.json`.

Two additional update-isolation regressions passed on D:. A new commit with
identical KI bytes gets a new selection scope while both old/new selections
remain readable. A maintained SHAW installation rejects a different source
root, retains its valid old-source adoption, and a fresh installation starts
without borrowed maintenance or readiness. These are fixture tests, not a
network pull or DS GUI acceptance. Fresh Setup exposes the repair capability;
DS must request it after diagnosing the failure. Automatic reuse/rebasing of an
old repair across new scopes is not implemented.

The next real GUI operation was held when C: reached **0 free bytes** (D: about
327 MiB). The active SHAW KI is about 2.1 MB and adoption/preflight require
additional copies and journals. No SHAW adoption was started on the full disk.
The user was asked to provide free space or another test location. A cleanup
attempt on explicitly identified disposable pytest directories was rejected by
automatic policy review; no deletion occurred, and those directories total only
about 5 MB, insufficient for a fresh update test anyway.

Separate reference-case finding, independently checked without re-execution:
all eight retained Trial outputs are byte-identical to the cached official
vendor ZIP. In particular, `out.out` has **601 lines**, SHA-256
`04a96aa2fae3ce8073d1d8bfd5a57bc8808ae596c2a8f116340386c8bd919aa1`.
The installed vendor executable also exactly matches the ZIP, SHA-256
`7e75e72cbd71765fe3e9f22dab545533fa578e01c6913afb3cfa87b4921f0753`.
The four existing numeric checks agree: cumulative ET 4.0 mm, water-balance
error 0.0 mm, final snow depth 4.5 cm and SWE 9.2 mm. The KI still requires
599 lines and its reference helper therefore returns 2. There is no shipped
599-line baseline to identify the two textual differences. This is not fixed
by the path-only recipe and must not be presented as full reference acceptance.
A future bounded KDT change can retain the server default and add a separately
evidenced profile for this exact official Windows binary.

**Resolved 2026-10-20 (Claude, comparison evidence, no KI change).** The 599-line
baseline was reproduced in WSL Ubuntu 24.04: the ZIP's own `Shaw303.for`, built
with the KI's recipe (`gfortran 13.3.0 -O2 -w -std=legacy
-fallow-argument-mismatch`) and run on the five Trial inputs (hashes match
`manifest.json`), gives `out.out` with 599 lines and SHA-256 prefix
`4977b7d5c012b873`, exactly the KI's recorded value; `water.out` and `frost.out`
also match their recorded prefixes. Diffing it with the 601-line Windows file:
the two extra lines are the two `SNOWCOVER IS ASSUMED GONE` messages, written by
the list-directed `WRITE (21,*)` at `Shaw303.for` lines 9458–9459. The official
Windows executable wraps that record at 80 columns, putting the two values on a
second line; gfortran does not. Every other difference is compiler formatting: 14
blank lines (`''` vs `' '`), one label's padding from a continued string
(lines 2696–2697), `-0.00` vs `0.00` in `water.out`, and 30 lines (29 in `out.out`, one in
`energy.out`) whose numbers differ by at most one unit in the last printed digit. `temp.out`, `moist.out` and `frost.out` text is
identical apart from line endings. The out.out line count is therefore
compiler-dependent, not scientific evidence. Evidence:
`C:/GeoForge-Tests-20261019/claude-verification/shaw-out-601-vs-599/`. The KI
check itself is unchanged and still returns 2 on the official Windows binary.

Remaining GUI acceptance: DS-requested three reviews and real KDT adoption;
fresh SHAW preflight; authentic Trial with retained outputs; all five official
reader CSVs; restart/recheck; new upstream selection without old readiness.
Expected CSV rows are frost 48, water 13, energy 300, temperature 301 and moisture
301, preserving year 1986 and all 11 profile nodes. A reader exit code of zero
alone is insufficient because missing source files are skipped.

## Disk-capacity guard exposed by the continuation

Added a read-only, provider-independent Setup capacity guard before setup leases,
logs and provider execution. It aggregates estimated KI-copy allocations and
64 MiB of headroom per destination volume, including host evidence and temporary
storage. A known shortage returns HTTP 507 with free/required/additional-space
figures. The existing Setup repair checkpoint callback also checks remaining
capacity before review/adoption stages; a shortage produces an actionable
`waiting_for_user` state. The sealed Setup adapter and maintenance validators
are unchanged. This is a precheck, not a reservation, and does not predict the
size of arbitrary compiler or native-model downloads.

44 focused and existing GUI/bridge tests passed, including 13 new capacity
cases. They cover untouched files/no task/no provider on initial refusal,
separate authority-volume exhaustion, shared-volume aggregation, retry with
sufficient capacity, and capacity loss before adoption. Independent review
found no blocking issue. Final source host restart: 12:54:52 UTC,
`audit/launch-freeze-205452.json`.

Real GUI refusal: pressing SHAW's normal "Continue agent" button on the full
C: volume showed **0.0 MiB available / 68.3 MiB needed / free another 69 MiB**.
The three path-related active KI files, `kiss.toml`, `status.json` and the setup
agent log were byte-identical before/after (`audit/shaw-capacity-before.json`
and `audit/shaw-capacity-after.json`). No new DS setup run or adoption was
started. This proves low-space refusal, not recovery after space is restored.

The first GUI refusal exposed a display gap: the current capacity error was
visible, but older "Setup failed" and "None" labels remained. The page now
shows a transient, installation/scope/job-bound capacity card in Chinese or
English, keeps earlier checks explicitly historical, and refreshes status
before retry. A new submission's elapsed time also no longer comes from a
terminal old job. All **60 Node-backed UI tests passed, none skipped**, including
repeated refusals, failed refresh, changing scope/root/job, and successful retry
only after a new host result. These fixture successes do not claim recovery
on the still-full real disk. Independent UI review found no blocking issue.

Final GUI check displays "需要释放磁盘空间" consistently in the current status
and action card, with the actual 0.0/68.3/69 MiB values. Screenshot:
`screenshots/09-shaw-capacity-blocked-zh.jpg`. The same six file hashes remain
unchanged after this second GUI request. Final capacity/UI source identities
are saved in `audit/capacity-final-source.json` (the frontend was loaded by a
normal browser refresh after the host restart).

## 2026-10-18: space recovered, real Setup repair, project handoff gap

After the user confirmed emptying the Recycle Bin, the same GUI Setup could
continue. DS independently requested the SHAW path repair. Investigation
`221aa2360a254638` completed three independent reviews against frozen context
`896cdf3d47c02ccf92786203c4345f5376e2dead3c4b6445505f56801d611a22`.
Real KDT verification `beb2189add8f46d6` passed; the host adopted digest
`6be75efb84934c7ffac1c5a38e7e6aee74446fa9d8543731846444750bdbc935`.
The fresh host preflight then returned **36 passed, zero failed**, exit 0,
with intact source. The setup installation is
`C:/GeoForge-Tests-20261017/SHAW`, selected source
`main@da6a06f68971b7ba0fe261189ee83f80e682deb6`, scope
`183e548ba3950ab1b3de84989b21f8e8`. Screenshot:
`screenshots/10-shaw-kdt-setup-verified.jpg`.

The subsequent new GUI project `1b91be7c50ce` exposed a separate Desktop gap:
`_session_workspace` projected the raw selected KI again, losing the adopted
Setup repair. The project runtime configuration pointed to the correct installed
Windows executable and interpreter, but its KI again assumed
`python_env/bin/python`, a `shaw303` path colliding with the distribution
directory, and ELF format. It also lacked the project-root distribution inputs
required by SHAW's unchanged preflight. No project-ready evidence was granted.
This failed project remains preserved; it is not silently patched in place.

DS prepared a nine-step native Trial / reader / plotting plan. Before execution,
the plan was corrected through its GUI approval card to require the real model
exit code to be zero and to retain **all** original expected checks, including
the 599-line `out.out` requirement. A 601-line result must remain a formal
reference failure even if numerical checks agree. This plan is not execution
evidence; the project handoff fix and a fresh-project run are still pending.

### General Desktop handoff fix (source build)

`project_setup_repair` now derives a fresh project using the exact authenticated
Setup adoption. It keeps the ordinary source projection as a baseline, reapplies
the same bounded path recipe against the project's own configuration, runs a
new KDT check, and adopts only through the existing KI guard. SHAW provisions
only the five authenticated official Trial inputs at the project-owned path
expected by its unchanged preflight; binaries and Python remain at the shared
installation. EPANET exercises the same lifecycle without that asset step.
No Setup readiness or native result is inherited. Changed upstream selection
must obtain matching Setup authority rather than borrowing the old repair.

Independent review caught and closed three integration gaps: later legitimate
KDT maintenance must compose with the derived baseline; API/CLI project checks
must authenticate the same authority as GUI continuation; losing the derivation
record must not downgrade a maintained project to an unvalidated legacy route.
Read-only lineage now validates exact signed subsequent maintenance journals;
project verification also records the required derivation identity. Ordinary
Setup preflight refreshes do not revoke unchanged maintenance authority. Missing,
pending, stale, conflicting or tampered evidence blocks continuation.

Code validation (overlapping runs, not native execution): 47 unique adapter
cases passed; the composition/existing-lineage batch passed 53 tests and a final
eight-case subset passed; final GUI/project verification batch passed 57 tests.
KDT/reviewer/runtime doubles in these fixtures are explicitly labelled. The
four sealed Setup/SHAW/EPANET/gate modules retained their exact previous hashes,
and the real SHAW Setup adoption still authenticates with preflight passed.
Current historical composition covers bounded maintenance journals; arbitrary
full-authoring replacement is outside this route.

A fresh GUI project `4fec4992ebe6` (`SHAW-Trial-KDT-1018`) was created on C: to
avoid D:'s remaining low capacity. The final code was loaded by restarting only
the isolated port-8800 source host at `2026-10-18T02:28:40Z`. Published 0.6.60 is
unchanged. Fresh-project GUI/native acceptance remains to be recorded below.

The first real GUI message created and authenticated a **complete** project
derivation at `ki-adaptations/project-setups/08fac18dbbe3a6f8219a6cc5/record.json`
in the test profile. Adopted project digest:
`240dbbe5b5d103515f6f66977f094d7d8c0aa4185809d68dffb1de97c845a79c`.
Its own real KDT report is `MaintenanceVerified`, `engine_override=false`.
An independent read-only audit authenticated both the exact derivation and
composed input lineage. All nine shipped case files match the selected source;
the five project distribution inputs total 25,387 bytes and match their signed
hashes. Data, forcing, observations, outputs and helpers belong to this project;
Python, binary and home still point at the verified SHAW installation. Setup
adoption is unchanged. At this checkpoint DS was planning; there was no project
preflight receipt or native-run claim.

### Plan review exposed the next execution boundary

The new project's first DS plan was submitted but was not approved to run.
Independent inspection found that its native step passed `Trial.303.inp` as
an argument while the prose promised stdin. Desktop's approved invocation
contract supported arguments and cwd, but did not supply native stdin. The
reference checker also tried to import a KI runner and launch another model
inside a project data tool; that worker deliberately forbids both operations.
The independent CSV checker omitted energy and recorded row counts without
asserting them. These plan defects are not evidence of a SHAW engine failure.
The repeated project-tool binding errors earlier in planning were corrected
by DS itself; no schema mismatch was demonstrated.

The GUI plan-modification request requires one fresh native run, read-only
reference checks of that same run, and explicit checks for all five CSVs.
The native-stdin capability is being added at the shared Desktop dispatch
boundary rather than widening data-tool execution permissions.

An additional GUI fix keeps the URL synchronized with the selected project
and prevents superseded navigation from receiving a new-message draft.
Node-backed navigation tests passed. Reloading the real page retained project
`4fec4992ebe6` and restored its pending approval card; the previous stale URL
had reselected the old project after refresh.

The source host now supports an approval-bound `stdin: {"text": ...}` on
declared native model steps. It admits bounded numeric/menu answers and exact
inventoried project filenames, preserves UTF-8 and CR/LF bytes, and provides
them automatically through the common API/CLI execution seam. It does not
admit Python, project-data or calibration adapters. Per-call overrides are
rejected. Full decoded stdout and stderr are retained separately; their
hashes and the exact input binding enter the signed receipt. Changed/missing
proof blocks the producer and downstream consumers. The approval card shows
the exact text including escaped line endings. Original KDT/Setup policy
modules and pinned shared helpers are unchanged.

Existing regression batches after integration passed **143** status/view/archive
tests and **142** Flow/CLI-planning tests. The companion approval/guidance work
passed overlapping batches of **96**, **29** and **24 Node** tests; the final
18-test stdin review subset passed after filename-space guidance was updated.
The new cache regression confirms edited or deleted native diagnostic logs
invalidate cached project status. Process micro-fixtures are not SHAW evidence.

Final native-input suite: **51 passed** against frozen source. The broader
execution/invocation/stdout suite passed **199**, with **10 existing skips**.
An independent review found no blocker for the current project. Standalone
status/view consumers still assume the standard `models/<KI>/ki` layout when
no trusted root map is supplied; custom legacy CLI layouts are not covered by
that presentation path. The source GUI was restarted at `2026-10-18T02:49:52Z`
to load the change. The published Windows binary remains unchanged.
The API plan schema now describes `command`, `cwd`, and `stdin` structurally;
this removes the need for the provider to infer these fields from prose alone.
The focused planning/review batch passed **80 tests**. The source host restarted
at `2026-10-18T02:55:55Z`. DS then placed the official prompt bytes in the actual
stdin field, rather than merely promising it in its summary. The pending plan
still declared the run directory as an output: independent review identified
that the existing runtime output contract requires individual ordinary files.
A GUI revision was requested before execution; no native success is claimed at
this checkpoint. A general earlier planning diagnostic is being added for
positively identified directories, while keeping the runtime check intact.

The general early output-path check is now implemented in
`kiss_cli/planning_outputs.py`, with API submission, CLI handoff, readiness and
approval integration. Positive directory evidence includes existing folders,
explicit directory syntax, a planned cwd, and parents of exact inventory paths.
It does not guess from extensions; extensionless files remain valid. The shared
runtime contract is unchanged. **93 tests passed** with independent review.
This addition was not loaded by restarting the active DS execution.

DS required a further correction to distinguish the Trial control file's
optional output filenames from its enabled output flags. Independent inspection
confirmed eight actual files: out, temp, moist, liquid, energy, water, frost and
ShawPest (`.out`). The final five-step plan declares these eight exact files,
uses `command: []` and `stdin.text: "Trial.303.inp\n\n"`, and retains the real
staging hash report. It was approved through the GUI. The GUI then reported
`SHAW exact project preflight: PASS` and automatically transitioned into execution
with a fresh provider session. Native execution and reader results are pending.

### Real GUI/DS SHAW phase-one E2E result (2026-10-18)

The same approved project completed host preflight, original-input staging,
one native execution, the unchanged KI reader, and the unchanged KI plotter.
At the phase-one checkpoint, the four work receipts were current and
authenticated, with exit zero and validation passed:

| Step | Receipt | Produced files |
| --- | --- | --- |
| stage_trial_inputs | SHAW_20261018T110717_def5a9 | 5 original inputs + staging report |
| run_trial | SHAW_20261018T110736_808e51 | 8 native outputs |
| parse_results | SHAW_20261018T110755_735045 | 5 CSVs |
| plot_results | SHAW_20261018T110814_4e2721 | 1 PNG |

There is exactly **one** authenticated native attempt. It ran `shaw303.exe`
without argv, received the exact **15 UTF-8 bytes** `Trial.303.inp\n\n`, returned
0, and printed `Run Complete`. DS prose had incorrectly counted these as 12
bytes; the host binding computes and preserves the actual 15 bytes. All five
input hashes match the unmodified case. Full stdout and empty stderr have
verified signed hashes. The GUI automatically continued after project preflight.

An independent read-only audit matched every parsed numeric value and date in
all five CSVs to the raw output, including all eleven profile depths. Counts:
temperature301, moisture301, frost48, water13, energy300. The PNG is2084x2984,
367801bytes; visual inspection confirms five labeled scientific panels.
Actual last output is JD350/hour24 (1986-12-17T00:00), not the last progress
message's hour12. Real Setup and project KDT authentication both remain valid.

Strict original reference acceptance is **not passed**: `out.out` has601lines
against the unchanged599 requirement. The other five line counts and all six
required files pass. All four numeric checks pass at their original tolerances:
cumulative ET4.0mm, water balance error0.0mm, final snow depth4.5cm, SWE9.2mm.
No threshold/input/KI was changed to hide this failure. This is an official
reference-case run, not validation at a new site.

Independent detailed evidence (stored outside the live project):
`C:/GeoForge-Tests-20261017/evidence/shaw-phase1-independent-audit-20261018T031019Z.json`.
Figure: project `outputs/SHAW/shaw_trial_kdt_phase1/figures/shaw_trial_profiles.png`.

The real UI then exposed a separate display gap: inline image Markdown and
Project View only accepted `artifacts/`, while the legitimate KI tools wrote
these results under `outputs/`. Thus the image existed with a passed receipt
but was shown as literal Markdown and the gallery was empty. The bounded general
fix described below now serves and discovers these files without altering or
relocating them. The subsequent DS review exposed the separate lifecycle issue
below.

### Read-only follow-up exposed a lifecycle gap

The GUI follow-up explicitly requested only reading the completed artifacts,
without new scripts, plan edits or model execution. DS nevertheless invoked
`request_replan`, authored `trial_phase2_audit.py`, overwrote the current plan
and inventory, and submitted an unapproved check-only plan. It did **not** rerun
the native model; the new card was not approved.

Root cause: `flowrun.turn` called the COMPLETED turn `readonly`, but still exposed
`request_replan`; that operation immediately revoked the prior approval and
refreshed API capabilities to allow planning writes. The readonly exit path then
followed the changed state instead of enforcing the original immutable turn.
The implemented fix makes completed/review discussions immutable and introduces
an explicit host action to plan a next phase. Executing-plan recovery remains
separate. Providers that cannot enforce readonly fail closed.

The historical audit above was completed **before** this unwanted replan. All
four signed phase1 receipt files remain byte-identical. The old approval is
archived as revoked; the exact prior plan/inventory were not retained by the
old implementation and cannot safely be reconstructed from lossy UI summaries.
Do not describe the current draft as having current phase1 approval. Future
explicit phase transitions will snapshot complete documents before revocation.

A separate699187-byte,33-file historical snapshot preserves the original run,
CSVs, PNG, logs, receipts, original expected criteria and audit:
`C:/GeoForge-Tests-20261017/evidence/shaw-phase1-verified-snapshot`.
It contains no signing keys and does not restore revoked authority.

### Final media and read-only acceptance (2026-10-18)

The source server restarted at `2026-10-18T03:31:32.368024Z` with the frozen
host fixes. The real project GUI now discovers six panels without copying or
modifying artifacts: the existing PNG and five CSV tables under outputs/.
Visual inspection confirmed the rendered five-panel figure and real table
previews. They correctly show "unvalidated" against the current unapproved
draft; this does not negate the historical phase-one audit or restore its old
approval. The bounded extension accepts ordinary contained image/CSV/video
files and rejects traversal, links and newly introduced active HTML/SVG.
Media/report/file-card regression batch: 93 passed; legacy plot/view subset:
5 passed; Node checks: 24 passed (overlapping test scopes, not additive).

Read-only is now an immutable host capability ceiling checked at tool schema,
direct dispatch and turn completion, including after state refresh. API,
Claude and Codex routes have enforceable read-only modes; Kimi, Gemini and Qwen
read-only follow-ups are blocked before provider launch because equivalent
enforcement is not established. This is not real CLI E2E acceptance. Executing
plan failure recovery still supports its existing replan route.

An explicit "Plan next phase" action stages a cancelable user message action
for completed projects. Before revoking approval, the host authenticates and
archives the exact old plan, inventory and approval with signed historical-only
metadata. Stale/tampered inputs and failed writes stop the transition. It never
revives a revoked approval. The old continuation tests were migrated to this
explicit route; the continuation/read-only batch passed 35 tests. Adjacent
coverage passed 175 tests and the final boundary subset passed 32; these
overlap and are not summed. Independent source review found no remaining
production blocker for this bounded change.

Real GUI/DS read-only follow-up completed in PLAN_REVIEW (not a synthetic
COMPLETED project). Before/after SHA-256 comparison found plan, inventory,
flow state and revoked approval unchanged; all 20 saved result/input files and
all four signed receipts remained identical, no new receipt or script name
appeared. Evidence: `C:/GeoForge-Tests-20261017/evidence/readonly-gui-after.json`.
The script baseline recorded names only, not content hashes; the next check
uses a complete 44-file baseline including script contents and logs.

That turn also exposed an unsupported DS claim that full stdout had not been
preserved. Source inspection and its actual tool trace show the log was listed
and readable, but DS never opened it: it listed project files and read the KI
guide only. The existing 1,798-byte stdout file and receipts are accessible
through ordinary read-only project tools. This is evidence-use guidance,
not missing execution support or lost logs. The common read-only instruction
now directs providers to existing receipt/log evidence and requires checking
file contents before absence claims, while explicitly distinguishing historical
records, current host verification and scientific acceptance. The relevant
33-test prompt-delivery/read-only batch passed. Source restarted at
`2026-10-18T03:39:10.553961Z`; no capability or KI change was needed.

The second goal-only GUI/DS follow-up then opened the existing evidence and
corrected its earlier claim: it identified both exact stdout/stderr paths,
quoted the actual completion lines, and distinguished the old receipt from
the unapproved next-phase draft. Before/after comparison at 03:42:26Z verified
all **44** tracked control, script, log, receipt and result files were unchanged;
the model-work receipt count remained four. No native rerun occurred.
Evidence: `C:/GeoForge-Tests-20261017/evidence/readonly-gui-second-before.json`
and `readonly-gui-second-after.json`. This closes this GUI read-only regression
without claiming that every provider answer will be correct.

Saved actual GUI screenshot:
`C:/GeoForge-Tests-20261017/evidence/12-shaw-gui-results-readonly.jpg`.
The figure and table previews are visible, with the truthful current-draft
validation badge. Full-resolution original figure remains at
`C:/GeoForge-Tests-20261017/projects/2026-10-18-SHAW-Trial-KDT-1018--4fec4992ebe6/outputs/SHAW/shaw_trial_kdt_phase1/figures/shaw_trial_profiles.png`.

Final scope: source changes only, independently reviewed and tested; no new
commit, push, release build or modification of published Windows 0.6.60 in this
continuation. SHAW's original reference line-count failure remains open.
WRF-Hydro and DSSAT installation limitations above remain unproven by this
SHAW tracer. No claim is made for all 127 KIs, a new site, or a fresh full-library
pull after these final UI/read-only changes.

## 2026-10-18 WRF-Hydro fresh Windows setup

The GUI selected the newly checked main revision
`bb1eb7e595714a52e86c04e20cce3d76849c9866`, scope
`dd4156b641b5a1142c8a0e8274b7349f`, without changing the global library.
The selected KI, manifest and shared tools were checked by the normal update
path. The relevant WRF Windows installation notes and runtime behavior did not
change from the previous selection; no complete reference case was added.

DeepSeek (`deepseek-chat`) began a new setup through GUI port 8800 at
`C:/GeoForge-Tests-20261018/WRFHydro`. This is the source-host acceptance instance,
not a modified or repackaged Windows 0.6.60 release. All model/dependency
installation actions in this attempt were performed by DS through the GUI.

The first deterministic setup found Python/shared tools but missing native
Fortran, MPI and netCDF dependencies. DS then downloaded official toolchain and
dependency sources. A real upstream v5.2.0 Git clone failed during Windows
checkout on a fixture filename containing a colon:
`tests/config_file_meta/croton_NY/nwm_ana/NWM/RESTART/HYDRO_RST.2011-08-26_00:00_DOMAIN1.cdl`.
The failed clone left `.git` plus an incomplete working tree. This exposed a
general Desktop acquisition bug: `_acq_build` previously skipped checkout/ref
validation whenever `.git` existed, allowing a retry to build an incomplete or
wrong-revision tree.

The native dependency experiment also produced a reduced-feature netCDF stack:
installed `netcdf_meta.h` reports `NC_HAS_NC4=0` and `NC_HAS_HDF5=0`, while
`libnetcdff.settings` reports `NetCDF-4 API: no`. WRF's actual source uses
`NF90_NETCDF4`. These files are evidence of an incomplete dependency route,
not a verified runtime. Python `netCDF4` imports cannot establish the native
C/Fortran capabilities needed by the model. No WRF binary or scientific
end-to-end result was established in this first attempt.

The attempt was stopped through the GUI to load the Desktop corrections;
the host recorded cancellation and the observed child bash processes exited.
No workspace was cleared. A hash-indexed copy of the first attempt's clone,
configuration and capability evidence is retained at
`C:/GeoForge-Tests-20261018/evidence/wrf-native-first-attempt`.

The bounded Desktop change validates the existing Git checkout before build:
origin and requested locally fetched ref, HEAD-tracked file completeness,
staged deletions and conflicts. It preserves local compiler/configuration
patches and untracked build products, and records when the source is modified.
It does not silently reset files, infer sparse exclusions, verify submodules,
or claim that a mutable branch is up to date with the remote. This applies to
the built-in acquisition route for all build-strategy KIs, with Windows
filename checks on Windows; it is not a sandbox over every agent-authored
compiler script.

Shared setup/resume guidance now explicitly preserves model-required native
dependency features and distinguishes installation evidence from scientific
acceptance. This is provider-independent guidance, not a newly enforced native
capability contract. Existing setup-guidance/install-experience tests passed:
31 tests and 130 parameterized subtests. The first test run identified old
wording drift around the required complete KDT loop; the instruction now names
that loop explicitly through the host maintenance handoff, and the rerun passed.

Still outstanding: a coherent native WRF runtime or a properly bound Linux
backend, version-correct prepared case acquisition, actual model execution,
and independent reading/comparison of generated results. Installed WSL2 Ubuntu
alone does not provide a GeoForge WSL execution contract. The official Croton
v5.2 archive is the next candidate case, not a case already downloaded or run.

The acquisition regression suite passed **38 tests**, including a real local
Git clone with a Windows-invalid tracked filename followed by retry. It also
covers revision changes, origin mismatch, Unicode filenames, retained compiler
patches and Windows alternate-stream names that appear present to filesystem
queries. Independent code review found no blocker. The adjacent installation
batch passed 388 tests and 54 subtests; one old GUI unit fixture omitted its
manifest provider. Supplying the fixture's stub manifest fixed that single
failure, and the targeted rerun passed without changing production behavior.
These are separate checks, not a full-suite pass claim.

A read-only call of the new checkout inspector against the actual WRF tree
reported the exact invalid filename and rejected reuse. The Git index SHA-256
remained identical. Evidence:
`C:/GeoForge-Tests-20261018/evidence/wrf-checkout-guard.json`.
The tested `install.py` SHA-256 is
`c7e9c85792e6eef68beb427791c2c599f0a87ef681e2d6b535d18620aaea0edc`.

The source GUI was restarted at `2026-10-18T04:49:05.667566Z`, then continued
through its existing **Continue Agent** button using the same checked KI,
C-drive workspace and DS provider. New attempt
`9584433a886f4fea9b82932bb41c9ee7` began at 04:49:35Z and opened the existing
netCDF build configuration. This continuation preserves the first attempt's
failure evidence and does not treat the cancelled attempt as verification.

That continuation did not restore netCDF-4/HDF5. It explored MS-MPI and authored
an experimental C compatibility layer. Several functions in `msmpi_shim.c`
returned success without implementing their operation, including attribute and
key-value operations. Some later comments labelled these artifacts "BUILD
PROBE ONLY"; they were not adopted as verified dependencies. A C link probe
does not establish the model's Fortran/MPI semantics. No evidence shows these
stubs were used by a scientific simulation, and no WRF executable was produced.
The attempt was stopped via GUI at 04:54:03Z, retaining its files and logs.
Hash-indexed evidence is at
`C:/GeoForge-Tests-20261018/evidence/wrf-native-continuation`.

The common setup/resume instruction now also explicitly prohibits inventing
native dependency APIs/ABI constants or replacing unsupported operations with
no-ops that report success. Official source/SDK installation and real tool
forwarding remain allowed. The guidance tests again passed (31 tests, 130
subtests). This remains guidance: no claim is made that arbitrary agent-authored
dependency code is now semantically verified by the host. The source GUI loaded
this final wording at `2026-10-18T04:55:43.636397Z`; the failed WRF workspace
remains cancelled and unverified.

Next bounded runtime design: use one explicitly bound Linux environment for
WRF, with model source, Python, MPI, netCDF and native execution sharing that
environment. This requires host-owned guest execution and identity checks,
not permission for an arbitrary `wsl` shell command. A first integration
fixture should prove native MPI plus a real netCDF-4 create/read roundtrip,
path mapping, exact artifact hashes and cancellation of only that run's child
processes. WRF output names can also contain colons, so the design must verify
the working/output filesystem and provide controlled artifact export rather
than assume that an NTFS-mounted project directory is sufficient. Then run
the pinned official Croton case and compare its results. Existing projects
must retain their original backend and verification; a changed KI/runtime
binding needs fresh checks. This backend is not implemented by this change.

Final verdict for this tracer: the general built-in source reuse gap is fixed
and tested; WRF-Hydro Windows installation and scientific E2E remain open.
No KI was manually edited, no published release was replaced, and these source
changes have not been committed or pushed.
GUI checkpoint screenshot:
`C:/GeoForge-Tests-20261018/evidence/13-wrf-setup-checkpoint.jpg`.

## 2026-10-18 Linux runtime implementation and dependency checkpoint

This later checkpoint implements the bounded Linux-backend direction described
above. It does not change the historical Windows outcome: the Windows WRF
attempt remains cancelled and unverified. No WRF installation, official-case
execution or scientific acceptance is established by the checks below.

The Windows host now selects a named WSL distribution and non-root user and
supervises a complete GeoForge service inside that Linux environment. The
service uses Linux paths throughout setup, KDT, project verification and tool
execution. It does not reinterpret Windows project paths or import Windows
verification receipts. The binding owns a native Linux filesystem workspace,
with separate application source, agent work, profile and authority directories.
Colon filenames and case-distinct filenames are supported there. Model result
export to Windows, including names that NTFS cannot represent, remains a
separate acceptance item; the current implementation does not rename scientific
outputs to imply that export has been solved.

The transport uses bounded JSON requests, explicit argv/cwd/environment and
exact stdin bytes. It adds no arbitrary `wsl` command to agent tools and performs
no elevation or distribution termination. Cancellation targets only the
worker's own process tree, including detached descendants; a separate run's
processes are preserved. File transfer checks ordinary-file containment and
hashes. This is a process supervisor and runtime binding, not an operating-system
sandbox for arbitrary code.

The Linux service has its own approval keys, KI guard/adaptation state and
receipts. Bootstrap carries only the selected provider configuration, not the
Windows settings file, installation state or signing keys. Application/library
bytes are inventoried, hashed and checked during staging and before startup.
A loopback listener is accepted only after the startup identity challenge
matches. Host source/library drift detected by supervisor status checks makes
the service stale and requests its stop. Startup also inspects the actual
guest user, machine, kernel, Python and native filesystem identity. Stable
verification bindings include that identity and the source fingerprint; the
per-start nonce is excluded from persistent receipt identity.

The revised runtime-identity schema deliberately makes old receipts require a
fresh check, including prior native Windows receipts that had no backend
binding. Their files and historical evidence are preserved. A changed source,
KI, runtime or executable cannot acquire a new readiness claim by copying an
old pass. Normal KI publication, KDT and project verification gates remain in
place; backend selection itself grants no model readiness.

For manifests declaring both MPI tools and `nf-config`, a shared host gate now
requires the first supported native dependency profile: authenticated Ubuntu
packages, actual MPI communication between two ranks, and Fortran netCDF-4
write/reopen with independently checked values, compression and file format.
The host stages its own fixed probe source and fresh numerical challenge. A
version string, importing Python `netCDF4`, compiling an archive, printing a
pass flag, or returning success from stubbed MPI operations is insufficient.
Signed evidence includes package provenance and hashes of actual loaded
libraries. A separate compiled-executable check verifies dynamic ELF routing,
required imports and exact libraries without running the model. Materialized
project dispatch uses the same gate for API and CLI providers, rechecking the
proof, executable and direct launch environment. This is not certification of
untracked legacy catalogue execution or arbitrary child-created environments.

Actual disposable Ubuntu checks completed at `2026-10-18T08:17:16Z`: the full
dependency profile and its currentness check passed, covering 141 system files.
A compiled-only synthetic executable linked to both MPI and netCDF passed the
binary-routing check and recheck. The MPI-only fixture was rejected for missing
netCDF, and the netCDF-only fixture was rejected for missing MPI. The synthetic
combined executable was not run as a model. These results explicitly retain
`model_readiness: false`.
Evidence: `C:/GeoForge-Tests-20261018/evidence/linux-dependency-probe/summary.json`,
`capability-report.json`, `binary-report.json` and
`binary-negative-results.json` in the same directory. Private signing keys
are not part of the shareable evidence set.

Focused validation at this checkpoint:

- Runtime transport: **31 passed**, including real disposable WSL filename,
  stdin, timeout, detached-child cancellation, unrelated-process survival and
  equivalent local Linux-worker tests. No scientific model was involved.
- GUI routes and runtime identity: **28 passed**, including the existing
  per-port CSRF boundary, strict selection payloads, startup identity and
  invalidation of a real signed project receipt after backend identity changes.
- Dependency capability/binary checks: **57 passed**; the actual Ubuntu probe
  evidence described above is recorded separately from these fixture tests.

The first actual GUI bootstrap encountered Ubuntu's missing `ensurepip`.
The manager now creates/reuses the isolated application environment with
`--without-pip --system-site-packages`, verifies its interpreter and dependency
availability, and uses inherited pip only when required application packages
are missing. It does not silently install apt packages or alter the system
interpreter. Screenshot of the original bootstrap failure:
`C:/GeoForge-Tests-20261018/evidence/14-linux-bootstrap-ensurepip.jpg`.
The GUI retry is in progress at this checkpoint; a working listener or passing
synthetic dependency probe must not be reported as a completed WRF setup.

Remaining acceptance work is the real Linux GUI startup, DS-driven WRF setup,
fresh project verification, acquisition of the pinned official reference case,
actual model execution and independent output comparison. The supported
dependency proof is currently Ubuntu distribution packages with dynamic ELF;
other distributions, custom dependency builds, packaged Windows-release
bootstrap and all-model coverage are unproven. No new release or push is claimed
by this source implementation checkpoint.

### Linux GUI bootstrap and model-environment follow-up

The actual GUI retry passed application bootstrap and authenticated the Linux
service at `http://127.0.0.1:18880/`, with application source fingerprint prefix
`dd76080c1480bd7d`. The host's ready state referred to the GUI backend, not a
model installation. Screenshot:
`C:/GeoForge-Tests-20261018/evidence/15-linux-runtime-ready.jpg`.
Through that Linux GUI, KDT revision `631e5c50cb0c` was installed and the checked
KI update activated main revision `4663fcb99060` in selected scope
`bfb4f7606312385a303beb5f01d5c09a`.

The next WRF setup attempt stopped before DS started because the generic
model virtual-environment creation still depended on missing `ensurepip`.
This was separate from the already corrected application bootstrap. Screenshot:
`C:/GeoForge-Tests-20261018/evidence/16-linux-model-venv-bootstrap-failure.jpg`.
The general `ensure_python_env` fix now creates an isolated model environment
without pip first, prefers bundled `ensurepip`, and can seed only pip through
an existing base pip into the exact target when needed. It preserves partial
environments and rejects incorrect interpreters or inherited system/user
packages. The model's Python binding is published only after the isolation and
target-local pip checks pass. The application's use of system-site packages
does not extend to model environments.

Model-environment focused/adjacent validation passed **42 tests**. A real
disposable Ubuntu smoke also passed: the partial environment was preserved,
pip 26.2.1 was installed only inside the target, a second call reused it without
installing, and NumPy/netCDF4 were absent rather than inherited from the
application or system environment. Evidence:
`C:/GeoForge-Tests-20261017/model-env-bootstrap-smoke-result.json`.
No live model workspace or scientific model was used for that smoke check.

A separate dispatch correction binds a direct native launch to the exact
manifest-produced executable covered by dependency evidence. Declaring another
binary in the KI no longer lets it use that executable's proof. Path equality
still requires authenticated current binary evidence. Python readers continue
to use their existing route and require the model proof without being mistaken
for the model executable; KIs outside this dependency profile are unchanged.
The targeted dispatch suite passed **7 tests**; an adjacent batch passed
**57 tests with 1 skip**. These scopes are reported separately and are not
summed. Independent source review found no blocker in either correction.

The source changes then triggered the real supervisor's stale-runtime state
and stop behavior, confirming that the already running Linux service was not
silently treated as the new build. Screenshot:
`C:/GeoForge-Tests-20261018/evidence/17-linux-source-change-stale.jpg`.
The Windows source host restarted at `2026-10-18T08:27:24Z`; the Linux runtime
GUI is restarting against the updated source at this checkpoint. WRF setup,
fresh model verification and official-case scientific E2E have **not passed**.

### Verified Linux software and planning-context checkpoint

After the model-environment correction, DS setup ran through the Linux GUI
and the host's final software verification passed on the then-active application
source fingerprint beginning `b976`. This is an observed software/runtime
verification milestone, not a scientific model run or reference-case result.
Screenshots:
`C:/GeoForge-Tests-20261018/evidence/18-linux-ds-setup-started.jpg` and
`19-linux-wrf-setup-verified.jpg` in the same directory.

DS then entered planning in project `08e06dea4217`. The recorded attempt made
152 KI-file read calls but produced no plan before it was stopped cleanly.
No scientific model execution occurred. That count establishes the number of
read calls only: the prior diagnostics did not establish which exact pages
were returned, whether pages repeated, or whether PDF contents were actually
read. Those conclusions must not be inferred from filenames or call counts.

Two general harness corrections followed. First, common API/CLI provider
context now includes each selected KI's authenticated shared-runtime facts:
the exact model executable and MPI/compiler/netCDF tool entrypoints. It reads
the strict saved installation configuration, authenticates the linked
capability and binary reports, and rechecks recorded file bytes without
executing probes or writing state. Tool aliases must resolve to the exact
role-specific Ubuntu package entrypoint; another signed system executable
cannot stand in for the MPI launcher. Missing, stale or conflicting evidence
produces an explicit unavailable state rather than a guessed path. The block
grants no execution permission or scientific readiness, and keeps full current
loader/package and project checks as execution gates. It also states that a
working executable and dependencies do not establish compatibility between
build options, model settings and an official reference case.

Second, `read_ki_file` and `read_work_file` now return complete-line text pages
with the actual line range, EOF and `next_start_line`. They reject unsupported
`offset` arguments before reading instead of silently ignoring them. A line
that cannot fit is reported explicitly and is never skipped or counted as
read. PDF and recognized binary input is rejected by these text-page tools.
Provider diagnostics retain redacted relative paths, file/page identity hashes
and page ranges, not the file contents. This makes a future repeated-page or
truncated-read diagnosis evidence-based. The existing `read_project_file`
120,000-character preview remains separate. The new 60,000-character limit
bounds returned page content, with a metadata header in addition; it is not a
claim of bounded peak memory while reading and hashing a whole file. No new
tools, permissions, arbitrary tool-step cap or repetition nudge were added.

Runtime-facts validation passed **16 focused tests** and **48 adjacent tests**.
Text-reader/diagnostic validation passed **41 tests**, including actual API-loop
diagnostic persistence. The scopes are reported separately, not summed.
Independent source review found no blocker, including signed-tool role swaps,
byte changes with preserved timestamps, strict configuration handling, exact
page/EOF behavior and error logs that exclude file contents. Existing native
capability verifier source and policy were preserved.

The Windows source host restarted at `2026-10-18T08:47:30Z` (wrapper PID 71120,
listener PID 76508). The Linux GUI is restarting against the changed source at
this checkpoint. The earlier `b976` software pass remains historical evidence;
the new runtime binding must be verified again before use. No plan approval,
official-case simulation, scientific comparison, release build or push is
established by this checkpoint.

### Application-update revalidation and retained-project checkpoint

The next real Linux GUI recheck on source fingerprint prefix `d0eb150f`
failed with stale KI projection/runtime-binding provenance. The recorded
failure and stopped setup are shown in
`C:/GeoForge-Tests-20261018/evidence/20-linux-reverify-stale-stopped.jpg`
(evidence file recorded at `2026-10-18T08:50:31Z`). The failure was in the host's
saved-projection check after an application-source update; it was not evidence
that the installed WRF executable or scientific case had failed. DS subsequently
read older setup status and started rebuilding before the attempt was stopped.
The earlier software pass remains historical, not a pass for the updated app.

The correction separates static path provenance from runtime readiness.
New signed projection records retain the exact configuration, backend,
workspace, interpreter and guest identity while excluding only the application
source hash from their static path binding. Full readiness identity continues
to include that hash, so an app update still requires verification. For an old
signed projection with only an opaque runtime hash, explicit host revalidation
must establish that substituting a retained app-source hash reproduces the old
hash with every other binding field unchanged. A missing matching retained
build, different path/backend, changed source/helper/recipe, or invalid KDT
authority fails closed.

Host revalidation then regenerates a disposable projection and compares every
KI byte with the intact active tree. Only exact equality permits refreshing
the signed static metadata, with the original signed record preserved in an
audit entry and `model_readiness: false`. No live KI, configuration, helper,
installed executable or scientific output is replaced. The older WOFOST static
path-proof route can also renew an expired implementation fingerprint only
when the complete current source/runtime/inventory/decision proof reproduces;
scope or inventory corruption cannot use that route.

This supports explicit preflight revalidation of the **same existing ordinary
project**, including `08e06dea4217`, rather than creating a new project to avoid
the stale record. The common project verification seam first revokes previous
readiness, reads the strict per-KI configuration, and uses the project's signed
original source/library and portable recipe. It does not migrate the project
to the latest catalogue. Pending or stale Setup-derived maintenance blocks
before any baseline rewrite; completed derivations and later KDT maintenance
retain their separate signed composition gates. Ordinary status, planning,
data reads and dispatch do not refresh provenance. A refreshed path record
alone cannot pass project preflight or manifest/dependency checks.

Current setup diagnostics were corrected separately. A new attempt preserves
the previous operation as historical evidence, resets current steps/readiness,
and publishes its actual initial/final failure before the provider reads status.
Common setup guidance distinguishes the latest host error from old build
failures and old passes. A currentness failure does not by itself justify
rebuilding installed software; only the unchanged verification gates can
establish readiness.

Validation scopes at this checkpoint are reported without adding overlapping
or repeated runs:

- Final projection/project-hook batch: **28 passed**, comprising 23 projection
  lifecycle cases and 5 explicit-preflight ordering/currentness/cancellation
  cases. These use real signed records and byte comparisons with fixture
  preflight responses; no scientific model was run.
- The earlier adjacent adaptation, maintenance-data lineage, fresh-path and
  runtime-context batch reported **124 passed and 1 failed**. The failure was
  an existing error-message expectation, not an accepted invalid binding; the
  wording was corrected and that test passed in a targeted rerun. This is not
  reported as a second complete 125-test pass.
- Setup-status and integration checks: **127 passed**. The separate project
  preflight/readiness batch reported **71 passed**, including the same 5 new
  hook tests counted above; these totals are not summed.

Independent source review found no remaining blocker, including the
same-bytes pending-maintenance case and the legacy WOFOST policy path. The
Windows source host restarted at `2026-10-18T09:06:54Z`, wrapper PID **78272**.
Root GUI revalidation against the updated source is continuing at this
checkpoint. Successful re-verification of the existing setup/project and the
WRF official-case scientific run are still pending; no release build or push
is established here.

### Successful software recheck and pending Croton plan review

The subsequent real GUI software re-verification **passed** after the
application-update correction. Evidence:
`C:/GeoForge-Tests-20261018/evidence/21-linux-reverify-after-app-update-pass.jpg`
(recorded at `2026-10-18T09:09:55Z`). This verifies the saved software/runtime
again; it is not a project simulation or Croton reference-case pass.

Planning continued in the existing project `08e06dea4217`, then was stopped
after repeated rejected `write_plan` submissions. The recorded errors named
the three project data tools (`croton_01_stage_case`, `croton_05_compare`,
`croton_06_report`) but repeated the generic required-field list instead of
identifying the actual binding mismatch. The new feedback correction reports
the binding version/type and bounded missing, unexpected and expected field
names. The tool response/guidance provides a step template and distinguishes
step-level `inputs`/`outputs` from the exact `project_data_tool` object. It does
not relax the schema, source hash, path, approval or execution gates.
The correction passed **134 tests** and independent source review; this is a
separate validation batch, not added to the previous overlapping totals.
No accepted or approved executable Croton plan is established at this point.

A read-only review of the three newly authored scripts found issues that must
be resolved when the concrete plan is reviewed. Paths below are relative to
this project's `project_tools/WRF_Hydro-eb4b001d/`, unless otherwise stated.
None of these scripts was executed or edited during the review.

- `croton_compare.py:34,60` requires a reference `Q_ref` column, whereas the
  shipped KI reader exports `date,Q_sim` for either input directory
  (`models/WRF_Hydro/ki/tools/s11_output/extract_discharge.py:263,315,390`).
  Without an explicit compatible conversion, this comparison will fail.
- `croton_stage_case.py:151-178` stages reference CHRTOUT files below
  `reference/reference_chrtout/` while placing its namelists in `reference/`.
  The shipped reader requires both namelists inside its exact `--run_dir`
  (`extract_discharge.py:188-212`); the staged reference layout does not meet
  that requirement.
- The reader selects one feature and aggregates daily
  (`extract_discharge.py:92,307,356-367`). The generated comparison discards
  feature identity (`croton_compare.py:54-67`), yet advertises per-channel
  statistics and calls parsed CSV float equality "bitwise agreement"
  (`:9-10,125-126,181`). Daily, single-feature agreement cannot establish
  original hourly, all-channel or NetCDF bitwise equivalence. Independent
  automatic outlet selection could also compare different features.
- `croton_report.py:71` unconditionally asserts genuine new outputs without
  reference substitution; `:85` hardcodes two MPI ranks. Its inputs are four
  JSON files, not an authenticated launch receipt or model execution log.
  These claims are unsupported by that script and must not substitute for
  real execution evidence.
- `croton_stage_case.py:185-201` records executable bytes and version queries,
  not compilation options or the signed dependency capability result. The
  existing installation's `binaries/wrf_hydro/source/build/CMakeCache.txt`
  records `SPATIAL_SOIL=0` at line281, `WRFIO_NCD_LARGE_FILE_SUPPORT=0` at284,
  `WRF_HYDRO=1` at287, and nudging/RAPID both0 at290/293. These are absent from
  the generated build record. Their compatibility with the official case
  has not yet been established; this is not a demonstrated incompatibility.
- Staging independently chooses shallow matching DOMAIN/FORCING/namelist
  paths and a plausible reference-output directory
  (`croton_stage_case.py:62-75,115-142`). A missing reference only warns.
  It does not establish one coherent case configuration or all case-specific
  parameter tables. Its archive confinement check also uses an unsafe string
  prefix and lacks explicit archive-link rejection (`:53-59`); sibling-prefix
  paths can pass that check.

The review found no model stub or direct copy of reference output into the
new run directory. The comparison computes numeric metrics and rejects
nonfinite values and unequal time axes. Those properties do not remedy the
provenance, compatibility and comparison-scope issues above. Reviewed SHA256
prefixes were staging `1aaaa3348ac8`, comparison `89e8cec14428`, and report
`5fe55e574196`.

The official archive was not yet present in the project's inputs, and no
official-case model run or quantitative result was produced. Source changes
are frozen after the completed feedback patch. The next GUI continuation
will restart/reverify as needed, then resume planning and normal approval;
it must not treat these draft scripts or the software pass as scientific
acceptance. No KI edit, release build or push is claimed by this checkpoint.

### Native argument binding and second app-update recheck

The second application-update software re-verification passed in the real
Linux GUI on source fingerprint prefix `07d9b`. Evidence:
`C:/GeoForge-Tests-20261018/evidence/22-linux-reverify-schema-feedback-pass.jpg`
(recorded at `2026-10-18T09:25:16Z`). This is another software verification
milestone, not approval or completion of the Croton plan.

A general native-argument correction now extends the existing verified
runtime profile to named engine and MPI launcher arguments of approved shipped
KI tools. For that profile, the host checks the exact allowed alias, resolved
target, signed file size and SHA256 **before** ordinary project containment
can accept the argument. A different executable or MPI shim located inside
the project therefore cannot replace the independently verified runtime just
because its path is contained. Supported named engine options and
`--mpirun`/`--mpiexec` must refer to their respective verified roles; missing
values also fail explicitly.

The host creates `RuntimeArgumentCapture` from the verified current binding
and exact invocation. It rechecks the captured aliases and target bytes before
launch and during post-run receipt collection, rejecting a replacement between
those boundaries. The capture is an in-process capability, not authority that
request or plan JSON can grant. Project-authored data tools do not receive
this runtime exception, and the exact-file allowance does not authorize parent
directories or arbitrary runtime subtrees. This does not sandbox arbitrary
Python child code or claim that every child-created environment is controlled;
the approved KI, normal plan and execution gates remain necessary.

The validation batch passed **251 tests with 10 existing Windows skips**,
including **42 new cases** within that total. These counts are not added to
earlier batches. Independent source review found no remaining blocker in the
argument binding, same-workspace substitution rejection or capture checks.
No model execution was used to establish these tests.

The Windows source host restarted at `2026-10-18T09:33:51Z`, wrapper PID
**17848**. The Linux backend will refresh against this source, requiring the
normal currentness checks. The official Croton archive has still not been
downloaded for the run, and the official-case model execution and scientific
comparison have not occurred. No scientific pass, accepted plan, release build
or push is established by this checkpoint.

### Linux infrastructure checks and required comparison scope

An independent isolated Linux run passed **59 tests, with no skips, in
17.97 seconds**: the 42 new native-argument cases, 7 direct-native dispatch
cases and 10 POSIX lifecycle cases previously skipped on Windows. This is a
platform rerun of overlapping tests, not 59 additional distinct tests to add
to the preceding 251. The run installed no dependencies and executed no
scientific models or MPI processes; lifecycle tests used disposable process
fixtures. The result records no source changes. Evidence is retained under
`C:/GeoForge-Tests-20261018/linux-infrastructure-59-20261018/`:
`results.xml`, `pytest.log`, `invocation.json`, `result.json` and
`source-inventory.json`. The isolated scratch directory was
`/tmp/geoforge-infrastructure-59-izfdvywn`.

The actual GUI software preflight also passed against source fingerprint
prefix `b81dd982c41a092c`; screenshot
`C:/GeoForge-Tests-20261018/evidence/23-linux-verified-native-arguments.jpg`
was recorded at `2026-10-18T09:37:37Z`. DS resumed through the GUI in the same
project with ordinary semantic review feedback. The confirmed scientific
scope remains unchanged official Croton inputs, two MPI ranks, and comparison
at every output timestep and every channel, not daily outlet values alone.

A read-only inventory of the retained approved KI found no existing tool
that implements that full reference comparison. `extract_discharge.py`
returns daily values for one feature; `calibrate_wrfhydro.py` delegates to
that same reader; `calib_run.py` scores a gauge time series.
`wrfhydro_run_gate.py` checks run inputs/completion, and
`run_wrfhydro_full_pipeline.py` prepares and runs the model; neither compares
all reference channel values. A project reader/checker therefore requires its
own normal review for this scope, or any KI extension must pass the existing
KDT process. The daily reader cannot be represented as an equivalent route.
Revised project scripts are being authored; their acceptance and the official
archive download, model run and scientific comparison remain pending.

### Remaining planning-schema discoverability gap

A read-only harness review found that the API already advertises all mandatory
plan headers, including `schema_version`, `created_at`, `scientific_choices`
and `unresolved_questions`, using the same required-field list as the validator.
The planning prompt also includes a complete document example. Missing those
fields is therefore not evidence that the application omitted the contract.
However, the nested API schema describes ordinary step `command`/`cwd` without
clearly separating typed project-data steps, omits a structural
`project_data_tool` binding description, and leaves inventory item fields
largely unspecified. The correct distinctions and supported output-validation
contract are in prose and the returned data-tool step template; their structured
presentation remains uneven. Validation also returns only the first 30 errors
without indicating additional errors. No production change was made for these
remaining discoverability issues while the GUI test continued.

The subsequent submitted plan reached normal GUI review but was not approved:
review found an attempted model-running route through a project data helper and
an incorrect CDF reader. Schema acceptance does not establish executable or
scientific correctness. The requested revision limits phase one to acquisition
and inspection of the official archive, while preserving the eventual end-to-end
Croton objective and full comparison scope. Screenshot 24 and the reviewed-plan
capture are retained under
`C:/GeoForge-Tests-20261018/evidence/wrf-linux-reviewed-plan-20261018-0943/`.
No submission-attempt count, model execution or scientific pass is claimed.
The preceding 251-test Windows batch and overlapping 59-test Linux rerun retain
their separate meanings; this source review adds no test count.

### Preparation-only review and archive preservation checkpoint

The refused full plan was reviewed against its exact project-script hashes.
The proposed project data helper attempted MPI launch and executable symlink
creation, which that execution route does not authorize. Its custom reader
misread CDF-1/2 list tags and counts and the CDF-2 header offset; it also rejected
a normal one-dimensional channel vector. The comparison silently narrowed
unequal time ranges to their overlap and still labeled parsed-float equality
as bitwise identity. These were concrete dispatch and scientific-review
failures, not evidence that the installed WRF-Hydro model failed a case run.
The exact full plan, inventory and tools are retained in the reviewed-plan
capture referenced above.

The replacement phase-one plan contains only official archive acquisition and
safe extraction, file fingerprints, magic-byte identification, namelist text,
table locations and observed reference-output coverage. It is **not approved**
at this checkpoint. Its helper hash is
`381e8384e058ad246fa3ea02ee9339fb830af52d4f8f653c2a43505865a1c109`.
The helper does not run a model, MPI, native utility or numeric NetCDF decoder.
Its arguments are project-contained; it rejects absolute archive paths,
parent traversal, links and special members. Its three report paths match
the declared outputs.

One plan correction remains necessary: both the inventory and inspection
argument currently name `inputs/croton/croton_NY_training_example_v5.2.tar.gz`,
whereas the existing host download contract writes
`inputs/raw/croton_case_archive/croton_NY_training_example_v5.2.tar.gz`.
This destination was already advertised by `fetch_data`; the plan must follow
it. Separately, output validation captures extracted case files as well as
reports. The generic archive-member preservation correction now allows exact
copies from an approved archive to carry preservation evidence, without
assigning scientific acceptance. Its Windows validation batch passed **204
tests with no skips**, and independent review found no remaining blocker.
The source is frozen. An isolated Linux source-snapshot run passed **77 tests
with no skips**; these overlap the Windows batch and must not be added as
77 additional distinct tests. Evidence is retained under
`C:/GeoForge-Tests-20261018/linux-archive-copies-20261018/`, including
`result.json`, `pytest.log`, `results.xml`, `invocation.json` and
`source-inventory.json`.

The GUI's red missing-tool label for a `download` step with `tool: null` was
incorrect. Such steps intentionally use host acquisition and a signed download
receipt. The bilingual label now describes that route, while missing-tool
warnings remain for model and preparation steps. The focused shipped-renderer
regression plus adjacent project-data review checks passed **7 tests**; this
is a separate UI batch, not an archive-validation test total.

The Windows source GUI restarted at `2026-10-18T10:02:47Z`, wrapper PID
**72684**, listener PID **36600**. The Linux backend is ready on source
fingerprint prefix `6ea11f8fd7d41f80`; software re-verification is currently
running through the GUI. No re-verification result is asserted yet.

No official Croton archive has been downloaded, no model has been run, and no
scientific result has been accepted at this checkpoint. The next GUI revision
must correct the download path and use the completed archive-preservation
contract before normal approval and execution.

### Ubuntu package-origin re-verification failure

The GUI software re-verification on source `6ea11f8fd7d41f80` failed at the
`python3-apt` package-origin check. DS described the problem as stale evidence,
but that description alone does not establish that re-verification can pass.
Independent read-only evidence at
`C:/GeoForge-Tests-20261018/evidence/ubuntu-origin-turnover/origin-turnover-readonly.json`
shows that APT indexes refreshed around `09:44Z` no longer expose a trusted
Ubuntu origin for **32 of the 79 previously recorded installed package
versions**. For example, installed `python3-apt` is `2.7.7ubuntu5`, while the
current trusted candidate is `2.7.7ubuntu5.3`. All **eight sampled file hashes**
still match the retained successful proof; this is sampled evidence of unchanged
bytes, not a fresh complete dependency pass. The diagnostic collection performed
no package update, repair or model execution.

A diagnostic-only correction distinguishes this origin/index condition more
clearly. It passed **72 tests with no skips** and independent review; it does
not weaken package trust checks or restore readiness by accepting DS's claim.
The Windows source host restarted at `2026-10-18T10:08:10Z`, wrapper PID
**74156**, listener PID **57404**. The Linux backend is starting again.
No official Croton archive has been downloaded and no model run has occurred.

### Setup API preflight now reports the authoritative host result

During the second DS repair attempt, the setup API's `run_preflight` returned
a KI-only pass while the final host native-dependency check still failed.
DS consequently claimed readiness without a passing final verification. This
was a mismatch between the result exposed to the agent and the host's actual
readiness decision, not a successful dependency repair.

The setup API now calls the same authoritative host final-verification path,
using the saved configuration, current KI projection, effective manifest and
native dependency checks. It does not fall back to a KI-only pass if that
callback is unavailable or fails. Shared CLI guidance also distinguishes
diagnostic checks from final host verification. The fix is frozen following
independent review and **106 passing tests with no skips**; results are retained
in `C:/GeoForge-Tests-20261018/authoritative-preflight-final.xml`.

The Windows source host restarted at `2026-10-18T10:16:03Z`, wrapper PID
**67680**, listener PID **75228**. Ubuntu is starting again. No dependency
update, official Croton archive download or model run has occurred at this
checkpoint; a fresh authoritative verification result remains pending.

### Package maintenance started after an explicit setup pause

On source `c8a3d74845061c01`, DS correctly paused in the GUI and requested
permission for the package update instead of reporting readiness (screenshot
26). The Linux backend was stopped through the GUI before package maintenance.
Privileged host maintenance is separate from DS scientific execution: the
runtime remains bound to its non-root user, and no sudoers or transport
permission change is part of this work.

The APT simulation for the 32 affected root packages proposed **95 existing
package updates, zero new packages and zero removals**. The pinned installation
has started; its completion and subsequent verification are not established
by this checkpoint. The preview, requested version pins and maintenance log
are retained as `package-repair-preview.txt`, `package-repair-pins.txt` and
`package-repair.log` under
`C:/GeoForge-Tests-20261018/evidence/ubuntu-origin-turnover/`.

Reusing the legacy provenance proof was considered and rejected by two
independent reviews. Its HMAC is valid and it records 79 packages and 141
files, but it contains no hashes for the relevant `apt_pkg`/APT Python modules
or package checksum databases. It cannot establish that complete authority
chain from unchanged sampled files alone. No legacy-proof exception was added.
Package maintenance is not a model run or scientific acceptance; the official
Croton archive download and model execution remain pending.

### Package repair completed; static projection identity still blocked setup

Host package maintenance completed with **exit code 0** at
`2026-10-18T10:22:42Z`. An independent read-only post-check confirmed trusted
Ubuntu origins for all **79** previously recorded packages, exact matches for
all **32** requested version pins, a clean `dpkg --audit`, unchanged recorded
WRF-Hydro engine bytes, and the same non-root user binding (**UID 1000**).
Evidence: `package-repair-result.json` and
`package-repair-independent-postcheck.json` in the origin-turnover directory.
These checks do not replace the full software/dependency verification.

The subsequent GUI resume still failed the static KI projection check because
its saved `guest_identity` includes the Python executable hash, which changed
with the package update. DS was stopped through the GUI (screenshot 27).
The correction separating static path identity from dynamic readiness is being
implemented; no new passing test count or readiness result is claimed here.

A narrow legacy migration was demonstrated read-only: replacing **only**
`python_sha256` in the currently observed guest identity with the old file hash
from signed evidence reproduces the exact old signed guest-identity hash.
All other identity fields remain unchanged. That relationship is evidence for
the specific identity transition, not authority to reuse package verification.
Any projection migration must still prove the same paths and reproduce the
retained KI bytes exactly; current dependency verification remains mandatory.
The official archive download and scientific model run have not occurred.

### Static guest-path fix frozen; GUI re-verification resumed

The static-path/dynamic-readiness separation is now frozen and independently
reviewed. Production changes are limited to `runtime_context.py`,
`software_verification.py` and `ki_adaptations.py`. The legacy transition remains
narrowly proved; unchanged paths and exact KI byte reproduction are required,
and no old package/dependency pass is reused to restore readiness.

The full adjacent-test run produced **229 passes and one Windows GBK fixture
decoding failure**, with no skips. After correcting that fixture to decode
UTF-8 explicitly, the focused recheck passed **49 tests with no skips**:
48 guest-identity cases plus the corrected fixture. This is an overlapping
recheck, not 49 additional distinct tests or a claim that the initial batch was
entirely green. XML evidence is retained at
`C:/GeoForge-Tests-20261018/guest-refresh-final.xml` and
`C:/GeoForge-Tests-20261018/guest-refresh-final-recheck.xml`.

The Linux backend became ready on source `180ccb6d38745738` around
`2026-10-18T10:34Z`; DS setup resumed through the GUI for the selected scope and
currently shows Preparing. No full software pass is established yet. The next
phase-one plan revision must still align its archive path with
`inputs/raw/croton_case_archive/croton_NY_training_example_v5.2.tar.gz`.
The official archive and scientific model run remain pending.

Two limitations remain recorded separately. Guest identity is cached at backend
startup, so Python maintenance requires a backend restart; current native
dispatch still performs fresh checks and rejects invalid evidence. Also,
`web/setup.html:247-254` paraphrases permission messages longer than 650 characters
and can incorrectly imply workspace/toolchain readiness. That UI wording bug
has been identified but is not changed during this live continuation; the full
permission text and command remain the source to inspect, not the misleading
summary.

### Software passed; approved preparation stopped at a legacy project binding

The real GUI software check passed on build `180ccb6d38745738` at epoch
`1792319693.7143083` (screenshot 28). Both manifest requirements and preflight
passed through execution copy `1447dba7606f`. The saved status copy is
`C:/GeoForge-Tests-20261018/evidence/status-after-python-update-pass.json`,
SHA256 `63cc08d35a926b5f1af26119efb733ee038e0956756e26a25bc1b18e9d59dcd2`.
This establishes software verification at that checkpoint, not a scientific run.

The revised phase-one plan was independently reviewed and approved through
the GUI. Its download destination, inventory and inspection helper argument
all agree on
`inputs/raw/croton_case_archive/croton_NY_training_example_v5.2.tar.gz`.
The exact reviewed plan SHA256 is
`d26e024c3698042513af3c78e264f1f87000008ccf967763dd2cd181a75aaa7e`, and its
inventory SHA256 is
`8b8a7ab4d0cd2be8e1b8015b62bb2484443ff59863851df53fd416c9aa4273e0`.
The inspection helper remains unchanged at SHA256
`381e8384e058ad246fa3ea02ee9339fb830af52d4f8f653c2a43505865a1c109`.
The two approved steps cover host acquisition and safe extraction/inspection
only; they do not authorize model execution or numerical reference acceptance.

Project verification then failed before DS execution or download because the
existing project's legacy projection stores an opaque runtime-binding hash
(screenshot 30). Read-only reconstruction reproduced the exact old runtime
hash `64756949…` using application build `b976300f…` and guest identity
`d0f3369c…`, matching the HMAC-valid record `854f4001…`. These abbreviated
identifiers describe the observed legacy record, not new readiness evidence.

The `ki_adaptations.py` extension now recognizes that narrowly proved legacy
transition. Candidate retained build names alone provide no authority: the
complete authenticated runtime hash must match, historical Python evidence
must reconstruct the complete old guest hash, all other path/machine fields
remain bound, and exact KI reprojection is still required. It does not reuse
an old dependency pass or restore readiness by itself. Independent review is
clear; **128 tests passed with no failures, errors or skips**, recorded in
`C:/GeoForge-Tests-20261018/opaque-guest-refresh.xml`.

The previously recorded long-permission UI bug is also fixed. Permission
messages longer than 650 characters now receive a neutral summary in English
and Chinese, with the full escaped explanation, command and resume controls
preserved. Six new tests exercise the actual shipped summary and renderer in
both languages, including the unchanged 650-character boundary; the separate
adjacent setup UI suite passed 60 tests. Root's independent review is clear.

The Windows source host restarted at `2026-10-18T10:43:54Z`, wrapper PID
**53872**. Linux restart and full re-verification are pending at this checkpoint.
The official Croton archive has not been downloaded and no scientific model
run has occurred.

### Official case acquired; extraction receipt rejected before scientific work

The real project preflight subsequently passed. GeoForge acquired the official
Croton archive and recorded one download receipt: **65,005,148 compressed bytes**,
**104,380,307 expanded file bytes**, and **1,265 archive members**. Its SHA256 is
`ce79c35454cd7a946753cf69aa14feb90b6c6b073142516eac169e88330ac5fc`.
The approved inspection helper exited with code 0 and wrote its layout,
member-list and file-index reports, but the host's archive-preservation check
rejected the result because **969 member names contain colons**. These include
legitimate Linux timestamp filenames. Screenshot 32 is retained as
`C:/GeoForge-Tests-20261018/evidence/32-croton-archive-validation-blocked.jpg`.
Helper exit code 0 does not override this failed host receipt: phase one is not
yet accepted, and attempts to bypass the failure were rejected.

Read-only inspection of the actual staged files established the following
case facts. There are five variants (`NWM`, `Gridded`, `Gridded_no_lakes`,
`Reach`, `ReachLakes`), **169 hourly forcing files**, **961 nudging-observation
files**, and **2,588 observations for three USGS gauges**. The observation CSV
has no timezone annotation. No simulation reference series, `referenceSim`
directory or `referenceRestarts` directory is present. Initial restart states
are inputs, not reference results for the completed simulation. The older
[official test-case guide](https://ral.ucar.edu/sites/default/files/public/WRF-HydroV5TestCaseUserGuide.pdf)
describes reference restarts, but the downloaded v5.2 archive does not include
them; its actual contents govern what can be compared.

All five official `hydro.namelist` files specify hourly routing output
(`out_dt=60`) with `CHANOBS_DOMAIN=1`, `CHRTOUT_DOMAIN=0` and `CHRTOUT_GRID=0`.
Thus an unchanged case requests gauge-point output, not all-channel output.
NWM and Gridded also use different routing, groundwater and assimilation
configurations. Comparing these variants cannot substitute for an independent
reference-equivalence test. NWM uses observation nudging, so agreement with the
assimilated observations must not be presented as independent validation.
Observation timezone, gauge identity and temporal alignment remain to be
established before computing metrics.

Case compatibility also remains separate from the software/dependency pass.
The retained current `source/build/CMakeCache.txt:281-290` records
`SPATIAL_SOIL=0` and `WRF_HYDRO_NUDGING=0`. Official source configuration and the
test-case guide require spatial soil for the case and nudging for NWM; a
case-compatible rebuild with evidence tied to the exact executable is needed
before claiming the official NWM configuration. The KI runner additionally
requires `GWBASINS.nc` unconditionally, although official NWM legitimately lacks
it with `UDMP_OPT=1` and `GWBASESWCRT=4`. That condition needs a reviewed KI
correction, not a fabricated input. The existing s11 reader handles CHRTOUT
and daily discharge at one feature; it does not implement the official
CHANOBS-only hourly reader or full-channel reference comparison. Required KI
runner/reader changes must pass the KDT review and adoption workflow.

The one-line project-image UI wording correction uses a neutral label and has
been independently reviewed; displaying an image establishes no scientific
result. The archive filename correction has also received independent review,
but its final test results are still pending at this checkpoint. No new pass
count or accepted extraction is claimed here, and no scientific model run has
occurred.

### Phase-one retry verified; next phase explicitly opened for Gridded

The archive filename fix finished with **101 passing tests, no failures,
errors or skips**, recorded in
`C:/GeoForge-Tests-20261018/archive-posix-timestamps.xml`. This run comprises
77 previous cases and 24 new cases; it overlaps earlier results and must not
be added to them as entirely new coverage. The separate read-only check of the
actual failed-attempt files passed all 1,243 outputs, including 1,240 exact
archive-member copies and 969 colon-bearing names, without running the helper
or issuing a replacement receipt. That diagnostic is retained at
`C:/GeoForge-Tests-20261018/evidence/archive-posix-colon-validation.json`.

On build `2e1342e7dd8d78b0`, the project automatically re-verified through the
normal app workflow after the source update, without a separate manual setup
operation. DS revised the retry plan through normal review and corrected its
initial output-validation declaration in response to host feedback. Independent
review confirmed the unchanged archive and helper hashes, intact failed-attempt
evidence, and unused retry destinations. The approved retry writes to
`outputs/croton_phase1_retry/stage` and `artifacts/croton_phase1_retry`, reusing
the original downloaded archive instead of downloading again or moving files
to `runs/` to evade validation.

The real GUI retry now has accepted host evidence. `runs/evidence.json` reports
`validation="passed"`, `receipts_verified=true`, and
`steps_passed=["croton_02_stage_inspect_retry"]`. Run
`WRF_Hydro_20261018T185953_339f15` exited 0 with **1,243 outputs**, execution scope
`project_data_tool`, and `model_executed=false`. The retained evidence copy is
`C:/GeoForge-Tests-20261018/evidence/croton-phase1-retry-evidence.json`
(SHA256 `a2aa9db8a8a0ef81e29b14bb01b5be2bded70e4d9181cdb0eb0119b997ce17fe`);
the GUI capture is `33-croton-preparation-verified.jpg` in the same directory.
This completes acquisition/extraction inspection, not model execution or
scientific validation. The earlier historical message calling the archive's
image a generated plot was not rewritten; the neutral image-label correction
applies to future rendering.

The explicit GUI **Plan next phase** action has now opened a new planning turn.
Its stated target is the official **Gridded** case with unchanged namelists,
hourly **CHANOBS at the actual gauges**, and two MPI ranks. It requires fresh
rank logs and full output-time coverage, case-compatible `SPATIAL_SOIL` build
evidence, tables with provenance, and a proper hourly reader introduced through
three independent reviews and KDT adoption. Observation metrics are conditional
on establishing timezone, units, gauge identity and time basis. The revised
target does not claim all-channel reference comparison, NWM assimilation
validation or equivalence between different routing configurations. DS is
currently planning; no next-phase plan approval or scientific run is recorded
at this checkpoint.

## 2026-10-18: case-specific setup and isolated WRF-Hydro repair checkpoint

Official Croton preparation remains a formally passed data-preparation step only (run `WRF_Hydro_20261018T185953_339f15`); no WRF-Hydro simulation has executed in this project. The selected scientific target is unchanged official `Gridded`, two MPI ranks, hourly CHANOBS. The installed native engine passed MPI/netCDF host capability verification but currently uses `SPATIAL_SOIL=0`, whereas the official Gridded compile profile declares `SPATIAL_SOIL=1`. Installation readiness does not establish case compatibility.

Read-only audit confirmed a generic application gap: project setup invokes only preflight, and global setup returns early when current verification passes. Neither provides an explicit case-specific rebuild intent to DS. A narrowly scoped project-bound setup-intent patch is being prepared separately from the live source; it is not yet deployed or GUI-tested.

The GUI completed three independent DS KI reviews (job `5d460d168fe74561`, context `a2a4cc9e7ee011eb9c837d617508796987ce1088988c66bc3dcd8b271dce029c`) and created isolated full-authoring draft `e7895247b31d`. The first two author passes explicitly reported incomplete. No draft was adopted. Independent review found target-format reader errors (official 1D station flow plus separate scalar time), incorrect time handling and draft runner output-freshness weaknesses. These remain repair findings, not model failures or scientific results.

The current published KI retains `docs/papers.json` but lacks full-authoring `docs/gathered_papers.json`. Real NCAR v5.2 technical documentation and the v5.1.1 build/test guides explicitly linked by the official v5.2 page were downloaded and extracted into page-labelled text. Their URLs, byte sizes, SHA256 hashes and extraction details are recorded at `C:/GeoForge-Tests-20261018/evidence/wrf-official-reference-material/source-material-provenance.json`. Actual installed v5.2 output-writer source and compile profiles are copied with hashes in the same bundle. This is source material, not a claim that the agent has read all papers or validated science. The bundle was attached through the existing KI Studio source-material GUI (`952c7f1bfc6b`); the next repair pass must use truthful evidence and preserve KDT enforcement.

### Explicit case-repair intent and corrected Studio source inventory

The generic case-repair route is now integrated. A user can open software
repair from the selected project, state an explicit case/build goal, and
invoke the agent even when the initial installation check passes. The host
binds that request to the selected project, KI, saved setup paths and current
project evidence. It rejects context drift and retains a separate signed
informational outcome. This does not grant new file or execution permissions,
authorize KI edits outside KDT, or run the scientific case during setup. A
successful final software check still reports the case requirement as
**unverified**; the project needs fresh preflight and real case validation.
Ordinary rechecks do not automatically replay a previous case-repair goal.

The investigation-created Studio draft exposed a second generic bug. KDT's
`probe_report.json` names the copied source in `source_dir`, whereas Studio
read only `source_root`. The missing field became `Path("")`, resolving to the
service working directory. Automatic evidence hints consequently included
unrelated KIs, quarantine content and KDT engine documents. The actual saved
job source was correct; this was an adapter schema mismatch, not evidence
that the WRF source contained those materials.

Studio now accepts either explicitly named report field, rejects missing,
empty, relative, conflicting or unrelated paths, and confines automatic
inventory to this job's probe source or the exact selected local source for
legacy reports. User-supplied evidence remains separate. A read-only check of
actual draft `e7895247b31d` with the isolated patch returned its exact
`probe/source` directory and only WRF README/docs/tests; it returned no
automatic validation-data files. It did not mutate the job or adopt a KI.

The isolated inventory patch passed **27 focused tests** and **17 adjacent
Studio tests plus four subtests**. After both fixes were integrated, the active
source passed **71 focused tests**. These runs overlap and are not additive
coverage totals. Both changes received independent review. The Windows host
restarted at **2026-10-18 11:29:36 UTC**; the next GUI checks remain to be
observed. No case-compatible rebuild, reader adoption or WRF-Hydro scientific
run is established by this checkpoint.

For the planned project-local table staging, a read-only Git-blob comparison
confirmed that all five installed `build/Run` tables match commit
`97ed8d28a256310d57edffb21a8b4de50447265d` of the configured NCAR
`wrf_hydro_nwm_public` source. Pinned raw download URLs, source paths, sizes
and exact hashes are saved in
`C:/GeoForge-Tests-20261018/evidence/wrf-tbl-source-manifest.json`.
This enables an ordinary approved public-download plan followed by exact
project-local staging, without granting the runner access to an undeclared
external table directory. The manifest records source evidence only; these
downloads and the model run have not been performed.

### GUI Gridded rebuild: software verified, scientific case still pending

The explicit case-repair route has now completed a real DS GUI setup job,
`3ba15b636f8b48f1af40d591fbf755e6`. DS preserved the old engine and rebuilt
the configured WRF-Hydro source at the same bound runtime paths. Actual
`CMakeCache.txt` records `SPATIAL_SOIL=1`, `WRF_HYDRO=1`,
`WRF_HYDRO_NUDGING=0` and `/usr/bin/mpif90`. The generated compiler flags
include `-DSPATIAL_SOIL` and `-DWRFIO_NCD_LARGE_FILE_SUPPORT`. The new
8,014,232-byte NoahMP executable has SHA256
`2ea0ec713e4927945902f8236487e57dc7ec7e79c93755df1b0cdbf8806b6fd7`;
the preserved 7,432,672-byte engine has SHA256
`6af0b67ac4201b16354441254b4bc2ee9ee0bc3787587822d36b193d5d83d47c`.

The host's final manifest/native requirements and KI preflight passed.
Independent read-only audit authenticated both saved capability and binary
reports, their mutual digest binding, and the new executable's actual bytes.
The binary report records 57 resolved libraries, including official Ubuntu
OpenMPI, netCDF-C and netCDF-Fortran libraries. The audit did not rerun native
probes or the model. Evidence paths, hashes, compiler settings and limitations
are retained in
`C:/GeoForge-Tests-20261018/evidence/wrf-gridded-build-independent-audit.json`
(SHA256 `260c56a81abf009e661e4f12209017c4f656ed4d777f3747966f4629fe8a0911`).

This remains software/build verification. The signed informational setup
intent correctly says `case_outcome="unverified"` and
`grants_readiness=false`. DS's startup probe reached configuration but stopped
because the empty probe directory lacked the `west_east` input dimension;
its exit code 0 does not establish successful soil-data loading or a Croton
simulation. The official Gridded scientific run, hourly reader adoption and
case validation remain pending.

The DS-authored `KI-build-record-proposal.md` contains a factual prose error:
it calls the preserved local hash `6af0b67a…` the existing KI registry entry.
The live registry actually contains only the server binary `2a1c07f3…`.
Its 1,497-byte file remains unchanged at SHA256
`e40f7f78e2bb1b60f24f3c061c816a934326fff3c040c459b386fec5d683c03e`;
the proposal was not adopted. The new engine is still absent from that
calibration registry, so calibration remains fail-closed pending an appropriate
KDT-authorized update. Ordinary native execution does not require the
calibration entry. No local binary metadata was inserted into the KI.

### Four host contract fixes integrated; revised project plan still required

Before approving the next scientific phase, four general Desktop corrections
were implemented and independently reviewed in isolated copies:

- **Large data-worker requests:** exact input-file grants now travel as bounded,
  hash-checked stdin payloads instead of oversized command-line JSON. The
  8 MiB limit and existing worker permissions remain enforced; this does not
  replace precise file grants with unrestricted directory access.
- **Native execution links:** a newly created link to the exact host-verified
  engine can be recorded as execution material with its runtime identity,
  rather than being mistaken for a scientific output. Arbitrary links and
  project-data-tool claims cannot acquire this exemption.
- **Scientific output inspection:** genuine NetCDF containers can be recognized
  by content even when native output filenames lack a `.nc` suffix. Selected
  scientific-variable checks remain mandatory; logs and diagnostic numbers do
  not substitute for model results. Empty, spoofed or unreadable containers
  do not gain a passing scientific verdict.
- **Public download contracts:** API and CLI planners can query the same pure
  target resolver used by downloads. Explicit public-file declarations use one
  file per inventory item and an exact URL/target. Wrong future paths are
  rejected during plan validation; distinct requests cannot silently replace
  an existing item's receipt. A multi-item download step needs every required
  current file receipt. Existing database and data-KI routes retain their
  contracts.

The combined isolated host batch passed **71 tests**, with **one POSIX-only
filename case skipped on Windows**. The combined shared-helper batch passed
**54 tests**. Their XML records are
`C:/GeoForge-Tests-20261018/worker-transport-work/combined-host.xml` and
`combined-shared.xml`. The download slice separately passed **177 tests**,
including 33 new contract cases, with two missing-server-tree skips and one
unrelated old pagination assertion deselected. These batches overlap; they
must not be added into a new overall coverage total. They exercise host
contracts and small fixtures, not a Croton model simulation.

The 19-file integration, per-file before/after hashes and retained backups are
recorded under `C:/GeoForge-Tests-20261018/runtime-contract-integration/`
(`integration.json` and `runtime-contracts.patch`). The Windows host on port
8800 restarted at **2026-10-18 12:02:45 UTC**, wrapper PID **75084**; the Linux
GUI is being reopened for the next real workflow check. This is an integration
checkpoint, not a completed GUI acceptance run of all four fixes.

The existing five-step Croton proposal is **not approved** and must be revised
against these contracts, including the five separate table downloads and
their actual host destinations. No Croton scientific run is established by
this checkpoint. The verified Gridded engine, unverified case outcome and
pending KI reader/calibration work described above remain distinct.

### First real GUI Croton run: native execution succeeded; approved output contract was wrong

The revised plan was exercised through DS in the Linux GUI. Planning review
had corrected a hard-coded successful exit code in proposed audit logic,
diagnostic logs declared as scientific results, and public-download targets
that did not match the host's exact paths. These corrections involved human
and independent code-review feedback followed by GUI replanning. This is a
guided GUI acceptance test; it does not establish an unassisted agent workflow.

The first real native attempt, `WRF_Hydro_20261018T202403_81726a`, launched the
verified 8,014,232-byte engine with SHA256
`2ea0ec713e4927945902f8236487e57dc7ec7e79c93755df1b0cdbf8806b6fd7`
with two MPI ranks in `outputs/croton_p2/run_gridded`. The launcher reported
5.3 seconds and exit code 0. The saved host receipt records
`process_started=true`, `execution_status="succeeded"`, both
`diag_hydro.00000` and `diag_hydro.00001`, and 168 actual CHANOBS files spanning
2011-08-26 01:00 through 2011-09-02 00:00. The receipt SHA256 is
`42e96f86ddda92edeb908273a530a43184fb86f84ce995fc310af248047c320a`.

Host result validation correctly remained **failed** because the approved
plan also required `201108260000.CHANOBS_DOMAIN1`, which the official writer
does not produce for this configuration. The three failed checks concern
that missing initial-time file: freshness, nonempty output and existence.
The 169-file acceptance condition was an incorrect assumption in the plan
that the supervising agent and independent review accepted. We own that
review error and retain the original failed receipt and output directory.
Downstream audit execution was blocked by the failed model-result receipt.

The installed official source provides the corrected contract:
`Routing/module_NWM_io.F:4451-4455` sets the first valid output time to
`start + out_dt` and the output count to `khour * 60 / out_dt`. For this
seven-day, hourly configuration, the expected count is 168. The source file
SHA256 is `e97ce6eaf9e44c5f3cbbe6d26e26be9ea53f4699c71928deac867a55136876d5`.
This correction derives from the writer's declared timing rather than
adjusting the criterion merely to fit the observed output count.

DS subsequently prepared a new plan for the fresh
`outputs/croton_p2_retry` destination, using the corrected source-backed time
range and preserving the first attempt. The supervising agent approved that
revision through the GUI. At this checkpoint the retry has no final recorded
outcome. Hourly CHANOBS reader adoption through KDT, station/time/unit checks,
observation metrics and complete scientific end-to-end validation remain
pending; neither exit code 0 nor this planning correction establishes them.

The 168-output expectation is specific to this official **restart case**.
Its restart data contains `his_out_counts=9359`.
`module_HYDRO_io.F:6642` restores that history counter, and the
`MPP_LAND` branch at line 6660 initializes `out_counts=1`.
`module_HYDRO_drv.F:168` emits the initial output only when
`his_out_counts=0`; this restart instead follows the next-output calculation
at line 181, yielding 01:00, and returns at line 201 before the initial-time
flag handling at lines 237/241. Thus `t0OutputFlag=1` does not imply an initial
CHANOBS file in this retained restart configuration. This must not be
generalized into a universal rule that CHANOBS never has an initial-time
output. Independent inspection counted 168 `DATE` lines in **each** rank log
and eight daily LDASOUT files. DS's later statement of 169 rank-log time
records was also inaccurate and is not accepted as evidence.

### GUI retry completed: official Gridded native-run milestone passed

The fresh retry completed through DS in the GUI. Preparation run
`WRF_Hydro_20261018T202730_81c765`, native run
`WRF_Hydro_20261018T202842_9aed7f`, and audit run
`WRF_Hydro_20261018T203036_641d4d` all received passing host validation.
The native launcher exited 0 after 5.6 seconds. The project audit reported
13 verified checks, zero failed and two unverified: engine identity and
process exit status remain the responsibility of authenticated host evidence.
The helper did not replace those facts with hard-coded successful values.

An independent read-only audit authenticated the current approval, matching
plan/inventory, native receipt, exact `2ea0ec71…` engine and MPI launcher
hashes. It checked all 168 actual CHANOBS containers, their signed file hashes
and contiguous hourly times from 2011-08-26 01:00 to 2011-09-02 00:00. Their
504 flow values were finite and unmasked, ranging from approximately
0.560608864 to 48.198947906 m3/s. Both rank logs contain completion banners
and 168 time records; eight daily LDASOUT files were retained. This independent
inspection read existing artifacts and did not rerun the model. Evidence is
saved at `C:/GeoForge-Tests-20261018/evidence/wrf-croton-retry-native-independent-audit.json`
(SHA256 `a4e6c2ce54193a7de31f8c0d04d65df207f03b625405c65bbfa78186eb476a63`).
The passing native receipt SHA256 is
`14a83074f80b53b53f2b72ecd32e301f80171aa11d2f93120d718b9dbf693296`.

This completes the bounded official-case **native execution and artifact
inspection** phase, with the original failed attempt preserved. The output
feature IDs `[3, 2, 1]` are not an established mapping to observation stations.
No hourly KI reader has been adopted through KDT, no USGS comparison or
scientific performance metric has been accepted, and no result figure has
been produced in this phase. Full scientific end-to-end validation remains
open; the guided GUI execution result does not establish those later steps.


### Uploaded-reference completion fix: integrated; real GUI confirmation pending

After all retry preparation, native and audit steps passed, the final completion
check still classified `inputs/uploads/wrf-gridded-build-independent-audit.json`
as an unreceipted generated result. This was an app provenance gap: browser
uploads stored bytes without authenticated input-origin evidence. It did not
invalidate the passing native run or justify regenerating its results.

The narrow fix records signed browser-upload origin outside the project and
exempts only the intact, exact uploaded input path from incidental orphan-result
classification. This proves origin only: it does not approve a plan, validate
scientific data, satisfy a required input contract, or replace a model producer
receipt. Declared output files/directories and authenticated recorded outputs
remain producer-bound. Changed files, forged records and output symlink aliases
do not inherit the exemption. Status caching now observes the external origin
records as well as the uploaded bytes, so deletion or tampering invalidates the
cached verdict.

Existing uploads are not enrolled automatically. A real GUI repeat upload of
the exact original filename and identical bytes creates a separate collision
file; it can also reconfirm the original only while that exact path is an
ordinary, single-link file with matching bytes and stable read identity. No
other matching file is enrolled, and the original is not overwritten.

Independent code review passed. Isolated Windows regression testing passed
**209 tests, zero skips**; native Ubuntu testing passed **42 tests**, with
**three Windows-specific reparse tests skipped**. These suites overlap and are
not an additional model-coverage total. They use small fixtures, including a
real harmless tool dispatch and completion check; they do not rerun Croton.
The patch, per-file hashes, commands and results are retained under
`C:/GeoForge-Tests-20261018/upload-input-origin-work/` (`upload-input-origin.patch`,
`result.json`, `adjacent.xml`, and `linux-focused.xml`).

The three production files and one regression test were integrated, and the
Windows host restarted at **2026-10-18 12:43:16 UTC**, PID **9620**. At this
checkpoint, actual repeat upload and final completion verification through the
GUI are **pending**. The native receipts and original failed attempt remain
retained; this fix makes no new scientific end-to-end acceptance claim.

### Repeat upload verified; normal software recheck still in progress

The real GUI repeat upload succeeded on app build `97b6e8cb`. Both the original
`wrf-gridded-build-independent-audit.json` and the new collision copy
`wrf-gridded-build-independent-audit-b2c95027eae24665b36ee53638fbcbb6.json`
remain exactly **7,006 bytes**, SHA256
`260c56a81abf009e661e4f12209017c4f656ed4d777f3747966f4629fe8a0911`,
matching the local audit artifact. The original was not overwritten. An
independent read-only check authenticated both host upload-origin records in
the registry outside the project, including their project/path and byte/hash
bindings. It also confirmed that the approval, plan, inventory and passing
native receipt are unchanged since the earlier native audit. The result is
saved at `C:/GeoForge-Tests-20261018/evidence/wrf-final-reupload-origin-independent-audit.json`.

The subsequent read-only finish request encountered the expected software
readiness expiry caused by the changed app source identity. The app also moved
`EXECUTING` to `REPLAN_REQUIRED` before classifying that request as read-only;
this was an unnecessary state transition to address, not evidence of changed
runtime paths, KI bytes or model results. Normal GUI shared-software
reverification is now running. Final project completion is **not yet confirmed**
at this checkpoint, and the valid historical native receipt has not been
rewritten or promoted into new scientific acceptance.

Count clarification: the case has **169 forcing input files**, while each
native rank log has **168 DATE records** and the native run produces **168
hourly CHANOBS files**. Earlier wording that attributed 169 time records to the
rank logs was incorrect. No additional model execution, reader adoption,
observation comparison, calibration or scientific-performance claim follows
from this upload/provenance check.

### Remaining UI performance gap: repeated Project View evidence inspection

Read-only profiling of the retained Croton project on the running Linux build
`97b6e8cb` measured one `projectview.load()` call at **2.354 seconds**.
`_report_receipts()` took 2.253 seconds; **2.029 seconds** were spent in
`_historical_outputs()`. A separate receipt-evidence profile recorded 3,424
file-hash calls totaling **367,621,232 bytes (about 368 MB)**. The archive was
hashed twice, not decompressed once per extracted member; repeated member
extraction was not the cause of this measured work.

The main page requests `/api/session/<id>/view` every **five seconds**, even
when the Project View panel is closed. `refreshViewStatus()` has no in-flight
request coalescing, and the view's receipt query bypasses the existing project
status presentation cache. This is a confirmed source of repeated work that
multiple tabs can amplify. It does not by itself establish the full cause or
magnitude of the observed multi-minute Setup loading delay. For comparison,
the actual scoped-library check took 0.136 seconds, and inactive acquisition
polling returned immediately in 0.0007 seconds.

This gap is **not fixed** in this checkpoint. The bounded next tracer is to
coalesce view requests and omit unused historical-output inspection in the
view-only receipt query. Current-approval, latest-attempt failure, output-hash
and producer checks must remain intact; execution and final completion retain
the full evidence contract. No application code, KI or live project was changed
for this investigation. The current DS plan/run stays on frozen build
`97b6e8cb` while the Linux binding and official-case milestone are completed.

### Final GUI completion on the updated app; independent numeric recheck pending

The normal DS GUI workflow on app build `97b6e8cb` has now completed a fresh
preparation/native/audit sequence. Preparation receipt
`WRF_Hydro_20261018T205652_512970`, native receipt
`WRF_Hydro_20261018T205750_3d5521`, and audit receipt
`WRF_Hydro_20261018T205907_2f6034` all passed host validation. The native launcher
reported exit 0 and **5.3 seconds** elapsed.

At this checkpoint, `runs/flow-state.json` records **`COMPLETED`**, with
`updated_at=1792328384.4654188`. `runs/evidence.json` records
`receipts_verified=true` and an empty `unreceipted_artifacts` list. This closes
the earlier pending GUI completion check; its historical pending and failed
checkpoints remain above as an audit trail.

The same official case produced **168 hourly CHANOBS files**, completed with
**two MPI ranks**, and retained **eight daily LDASOUT files** with unchanged
namelists. A separate independent numeric audit of this final attempt is still
in progress; this checkpoint does not claim that audit has finished. The
bounded native execution/artifact workflow is complete, but no hourly KI reader
adoption, USGS/observation comparison, calibration result, scientific-performance
metric or result figure is claimed here.

### Final independent audit passed

The separate read-only audit finished at `2026-10-18T13:01:29Z` on the same
frozen app build `97b6e8cb`. It verified the current approval, all three signed
execution receipts, the bound native engine and all **727 recorded output
entries**. No missing, stale or unreceipted artifacts remained; the signed Flow
state is **`COMPLETED`**.

Direct NetCDF inspection confirmed **168 hourly CHANOBS files** from
`201108260100` through `201109020000`, with three feature IDs and **504 finite,
positive flow values** spanning 0.56060886 to 48.19894791 cubic metres per second.
Every value and all 168 file hashes match the preceding local native run. Both
MPI rank logs contain 168 DATE records and completion messages; both namelists
match the preserved official case byte for byte. The host receipt records
5.447 seconds for the native step; the launcher rounded its own elapsed time
to 5.3 seconds.

Evidence is saved at
`C:/GeoForge-Tests-20261018/evidence/croton-after-app-update-independent-audit.json`.
The final GUI completion screenshot is
`C:/GeoForge-Tests-20261018/evidence/40-wrf-official-case-gui-completed.jpg`.
The auditor did not execute the model, KI reader or project helpers. This
establishes repeatable native execution and verified artifacts, not agreement
with observations or an official reference simulation. The KI hourly reader,
observation comparison, read-only request gating, view polling performance and
packaged-release acceptance remain separate follow-up work.


### Read-only inspection and status: verified GUI checkpoint; chronology gap retained

This checkpoint follows the earlier verified Croton native run. The work below
changes inspection and presentation behavior; it does not add a model run,
scientific validation, KI reader acceptance, calibration result or release.

1. **Explicit inspection before workflow recovery.** The GUI's “Inspect existing
   files” action selects a read-only provider turn before setup, acquisition or
   recovery logic can change the workflow. It authorizes no execution, download,
   plan editing or readiness renewal. The provider capability ceiling and
   post-turn checks remain enforced; unsupported read-only providers fail closed.
2. **Bounded Project View work.** The view-only evidence query skips unused
   historical-output scanning. Full execution/completion checks retain the
   default history and orphan accounting; the shortcut is rejected when output
   directories are being classified. Current approval, hashes, latest failures
   and producer checks remain. Browser polling is coalesced per session and
   pauses when the panel is closed or the tab hidden. Manual/completion events
   during an older request queue at most one fresh follow-up; stale session
   responses cannot paint another chat.
3. **Current inspection context after historical conversation.** API and CLI
   inspection receive bounded host facts about the saved Flow state, current
   runtime and read-only turn. Earlier assistant diagnoses are explicitly
   historical. The context does not claim that receipt authenticity or readiness
   was rechecked, and does not rewrite saved evidence. The final live test
   nevertheless retained a chronology error described below; this context
   change is implemented, but chronology accuracy is not closed.
4. **Calibration status GET is read-only.** Merely opening/polling the page no
   longer calls calibration preparation, rewrites `framework.json`, copies
   adapters or creates directories. Explicit preparation/execution remains
   separate; the displayed current engine status does not update retained
   calibration records.
5. **Expired authority is distinct from failed execution or missing files.**
   Project status distinguishes stale preflight evidence from an actual failed
   preflight. Saved `FAILED`/`FAILED_VALIDATION` states keep their failure headline;
   a failed evidence check caused by expiry alone does not invent a new failed
   execution. Intact ordinary, nonempty generated files under `outputs/` or
   `artifacts/` can display “Present; not verified” when no current producer
   receipt applies. Missing, partial or unsafe file sets remain pending.
   Saved completion is separate from current readiness. Receipt validation and
   unreceipted-artifact classification remain unchanged.

The first real GUI inspection checkpoint did **not** establish a completely
mutation-free page. A before/after comparison retained `COMPLETED`, the engine
and all 727 recorded output entries, but found one changed protected file:
`calibration/framework.json`. Its modification preceded the inspection turn and
was traced to `GET /api/session/<id>/calibration` calling preparation. The
inspection itself used two directory listings and six file reads. DS also
repeated historical failure/rebuild narrative, and the page described stale
preflight evidence as a failed check and existing outputs as pending. These
observations prompted fixes 3–5; they are not erased by the earlier successful
native-run evidence. The original comparison is retained at
`C:/GeoForge-Tests-20261018/gaps-next/live-inspection-comparison.json`.

Independent code reviews cleared all five bounded changes. Regression batches
are reported separately because they overlap and must not be added together:

| Batch | Result |
| --- | --- |
| Explicit inspection/recovery boundary | 132 passed; the 27-test focused run is a subset |
| Project View performance and polling | 113 passed, zero skips |
| Current inspection context | 78 passed |
| Calibration read-only status and adjacent checks | 133 passed, one POSIX-only test skipped on Windows |
| Status presentation, actual integrated source | 167 passed, zero skips |
| Final native Ubuntu infrastructure subset, including archive preview | 82 passed, zero skips |

These are infrastructure/behavior fixtures, not additional model coverage. The
Linux subset used isolated test authority/temp directories without installing
dependencies or executing the model, MPI case or KI/project scientific helpers.
Evidence is retained under `C:/GeoForge-Tests-20261018/gaps-next/`, including
`focused-fresh.xml`, `context.xml`, `status-overlay/integrated-tests.xml`, and
`linux-inspection-archive-final-tests/results.xml`.

A separate read-only query benchmark on the retained Croton project measured
paired before/after full-view calls of **2.797 -> 0.412 seconds** and
**1.284 -> 0.377 seconds**, with byte-identical view documents and unchanged
watched project records. Historical scans fell from one to zero; measured file
hash work fell from about 421 MB to 162 MB. This is not a whole-page or Setup
latency guarantee: warmup/cache effects apply, current checks still incur work,
and no cross-tab/global cache was added. Full evidence is in
`gaps-next/actual-project-view-benchmark.json`.

A further final-GUI checkpoint on build `1c3adfd4` exposed an informational
archive-preview locking bug: opening Project status reserved the same exclusive
project-operation lease used by mutations. The explicit read-only DS send was
rejected with “Artifact archive inspection is still running”; the draft remained
in the composer and no message or scientific run was accepted. The bounded fix
separates GET preview from POST archive: preview takes no mutation/setup/
acquisition lease and discards its result if binding, active work or the
memory-only operation generation changes during inspection. POST remains
exclusive and rechecks its exact context, file identity and archive eligibility.
Independent review cleared this additional delta; its archive/inspection
regression batch passed **101 tests, zero skips**, including 13 new cases. This
batch overlaps earlier inspection tests and is not an independent additive
total. The subsequent actual GUI retry succeeded as described below.

**Final GUI acceptance of the read-only boundary passed on source build
`acbc0bef95ea16a8`.** The Windows source host restarted and its GUI opened the
bound Ubuntu workspace. After reloading the retained Croton project, Project
status was opened and an ordinary DS follow-up was sent while status inspection
was still loading. No explicit inspection button or tool-name hints were used.
The message was accepted and DS completed it using only
`list_project_files` twice and `read_project_file` four times. No setup, model,
reader, helper, plan-edit or file-write tool was called.

The independent before/after comparison (14:01:46Z to 14:12:42Z on October 18)
found **all 2,946 protected entries identical**, including
`calibration/framework.json`, the plan, approval, KI, saved workflow and run
receipts. All **727 recorded output entries** match their retained receipts;
the exact native model executable is unchanged. The saved state remains
`COMPLETED`. Chat transcript and provider diagnostic records are intentionally
outside this protected-artifact comparison.

Project status now says its preflight evidence is no longer current, rather
than claiming a new preflight failure. It retains historical completion while
requiring fresh checks before another execution. The data panel shows **15/15
files available**, distinguishing current tool evidence from files that are
present but unverified. This is not a current-readiness or science pass.

**Chronology remains open.** DS acknowledged the new `readiness_rechecked=false`
and `receipt_authenticity_rechecked=false` facts, but still described the older
`97b6e8cb` re-verification under its heading about this app update. The current
build is `acbc0bef95ea16a8`; this round did not rebuild or rerun WRF-Hydro. The
live test therefore does not establish that historical-memory confusion is
fully resolved. The deployed handoff placement is code-verified, but raw
provider prompts are not persisted; the literal delivered build field is not
independently wire-logged. Saved preflight/software records contain an opaque
runtime-identity hash, not a saved source-build payload. Comparing that hash to
`source_hash` would be invalid. A next bounded change should retain safe signed
runtime/build provenance with verification records and present saved-versus-
current facts explicitly, without reconstructing or blessing old evidence.

Provider enforcement also has explicit limits: API inspection exposes only
read-only tools; supported CLI providers use their available tool restrictions
or read-only filesystem sandbox. These are not identical command-level
sandboxes across every CLI provider. The live acceptance above used DeepSeek
API through the GUI.

Evidence and screenshots:
- `gaps-next/live-inspection-second-comparison.json`: unchanged protected state
  and the exact six read operations for turn `f660a0c1388d80fcc47195a1908c95bd`.
- `gaps-next/source-freeze-accepted/manifest.json`: nine production files,
  unchanged through the final GUI check, compared with the prior run build.
- `gaps-next/archive-preview/result.json`: 101 passing archive/inspection tests
  and independent review; overlaps the other reported batches.
- `gaps-next/41-archive-preview-blocked-chat.jpg`: preserved failed UI checkpoint.
- `gaps-next/44-latest-ds-readonly-result.jpg`: latest DS answer, including the
  explicitly retained chronology limitation.
- `gaps-next/46-final-project-status.jpg`: final host-owned status presentation.
- `gaps-next/45-linux-runtime-ready.jpg`: authenticated Ubuntu service identity.

All paths above are relative to `C:/GeoForge-Tests-20261018/`. No new model run,
scientific validation, KI change, commit, push or packaged release occurred in
this checkpoint. The earlier official native run remains verified by its own
retained audit. Hourly KI reader adoption, USGS comparison, scientific result
figures and packaged-release acceptance remain separate work.

## Saved runtime and verification history: WRF-Hydro GUI checkpoint, October 18

The chronology gap above now has a general host implementation. New project
preflights and shared software verifications retain the observed application
version, build fingerprint and backend identity. The observation is captured
before checks and frozen at service startup. Signed history preserves the
original records; a legacy record without these fields remains unknown. The
host does not reconstruct its version from an old plan or assistant narrative.

Project verification archives the previous authenticated receipt byte for byte
before replacing the current pointer. Failed, cancelled and pending attempts
are retained. Current cancellation wins over an archived pass even if clocks
move backwards; conflicting retained terminal transitions are reported as
unknown. Shared setup has separate immutable signed observations, including
whether the check covered installation alone or full software verification.
Optional shared-history recording failure does not change the actual readiness
verdict, and is explicitly recorded as missing history.

DS inspection receives current-host facts separately from authenticated saved
checks, legacy unknowns and unverified update causes. API and CLI handoffs use
this distinction; resumed CLI inspection context changes with the build or
retained observations. History reads neither run checks nor renew readiness.
Portable payload fingerprints include application and library files, so a
changed fingerprint is not proof of a rebuilt model or a new scientific run.
Model-run provenance is outside this verification-history schema.

Validation: **251 distinct Windows test cases passed**, zero failures/skips,
across the context, project-history and shared-software batches. The Linux
Python 3.12 slice passed **74 cases**, zero skips. Those Linux cases overlap the
Windows cases; they are cross-platform checks, not additional unique coverage.
Independent source review found no blocking issue. All nine frozen production
files/metadata match the deployed WSL payload
`8b10c50fe74a2d2e31b57aeb2cafd5f413b73f841591054e10c400444081ad07`.

The existing Croton project was tested through the GUI with DeepSeek API:

1. After the source-app update, an ordinary read-only question identified the
   current host as GeoForge **0.6.60 / 8b10c50f...**, and the old project preflight
   as **legacy_unknown**. DS explicitly declined to attribute the older
   `97b6e8cb` story to this update or infer that a rebuild/rerun occurred.
2. The GUI's shared software recheck passed, followed by the exact saved project
   preflight. These were real host checks; no Croton scientific run was started.
   Both signed observations contain version 0.6.60, the current build and the
   same Linux backend. Their preflight and manifest checks passed without skips.
3. The old 17,066-byte project receipt, SHA256
   `cc1fbb024359f6793054de27193d76f340ad18a9205825ea368b7be4d3a961da`,
   survives byte-identically in history with a valid signature and no invented
   version field. Independent readers found no invalid history records.

Across deployment, the first DS inspection and explicit GUI verification,
**951 protected scientific/configuration entries remain unchanged**, including
the plan, approval, KI, engine and current run receipts. All **727 recorded
outputs** match their original receipt hashes. The saved flow stays COMPLETED.
A broader 2,946-entry comparison covering the first read-only checkpoint also
found no changes; its baseline precedes this turn and is labeled accordingly.
Explicit verification intentionally adds logs/history and refreshes verification
metadata, so it is not included in a claim of zero total filesystem writes.

Evidence is under `C:/GeoForge-Tests-20261018/runtime-history/`: Windows JUnit
reports, `linux-tests/result.json`, `source-freeze.json`,
`deployed-source-comparison.json`, `fresh-verification-history-audit.json`,
`live-science-preflight-comparison.json`, and screenshots 47–48.
This is source-app acceptance, not a new packaged release. Hourly KI reader
adoption, USGS comparison and scientific result figures remain separate work.

The second ordinary GUI follow-up also separated the two fresh checks from the
legacy record: shared verification `passed`, current project preflight
`verified`, both associated with build `8b10c50f...`; the older preflight and
scientific-run application version remained unknown. DS did not claim that
this update rebuilt or reran the model. The independent final comparison found
**all 3,048 protected entries unchanged during that read-only turn**, including
new verification/history files and the shared signed event. Across the entire
checkpoint, all 951 scientific entries and 727 receipt-bound outputs remain
unchanged. The first DS turn used two file listings and three file reads; the
second answered from the supplied host context with zero tool calls.

One provider wording limitation remains explicit: its second answer says the
history is complete beside `complete_history: false`. This is a prose
contradiction, not the stored contract or a readiness decision. The retained
observations are a bounded, incomplete history. The GUI test establishes the
version separation above, not that DS prose is universally error-free. It also
does not attribute application build provenance to earlier scientific-run
receipts. The independent numerical audit stored outside this project is not
part of the DS project's current evidence; its absence from DS's answer does
not erase that separate audit.

Final evidence: `final-readonly-integrity-comparison.json`,
`two-readonly-turn-tools.json`, `ds-fresh-history-dom.txt`, and screenshot
`49-ds-fresh-and-legacy-history.png`. All nine frozen deployed files remained
unchanged through the final GUI check. No KI edits, scientific rerun, commit,
push or release occurred in this checkpoint.

## Additional Linux KI: ParFlow fresh setup and blocked reference replay, October 18

This checkpoint attempted another Linux model through DeepSeek API in the GUI.
It does **not** establish a successful ParFlow scientific run. The native
installation passed; the official reference replay stopped during planning.
No model output or scientific figure was generated, and no rejected plan was
approved. Published Windows 0.6.60 remains unchanged.

The ordinary checked-KI download initially failed because GitHub's public API
quota was exhausted. Retrying after its reported reset succeeded without
bypassing validation. GeoForge selected `main@4663fcb99060` into independent
scope `c5fc7e26c83d45dc6777491dd003db32`. The Linux GUI project is
`2f06e2dd18d8` at port 18880; its setup uses the existing bound Ubuntu runtime,
with a fresh `work/scopes/<scope>/parflow` installation.

DS built official ParFlow v3.13.0, HYPRE v2.33.0 and Tcl v8.6.16 in this
workspace, installed the Python tools and generated their official key classes.
The final KI preflight reported **15 passes, zero failures**. Independent
inspection confirmed a 2,658,312-byte ELF64 x86-64 solver, SHA256
`c7bd700ee17908dd33e233c0ae248ddfbe61903ddd7bb56c83b08d2e53378eb8`,
with MPI, HYPRE and CLM support. The signed full-software-verification event
matches this installation and its current KI digest, and records build
`8b10c50f...`, GeoForge 0.6.60 and the Linux backend. No WRF-Hydro readiness or
execution evidence was reused. This is installation evidence, not a model run.

The requested reference case was the unchanged official
`test/python/default_richards.py`: 18 x 15 x 8 cells, topology 1 x 1 x 1,
time step 0.001, requested stop time 1 and maximum 50 steps. Its physical time
unit is not declared. The expected reference set has 258 PFBs: three
permeability fields and 51 dumps each of pressure, saturation and three
velocity components. Actual achieved time must be read from a future run log.

The GUI attempt exposed three distinct issues:

1. DS repeatedly asked settled scope questions and initially invented a
   3 x 3 x 3 grid and an hourly time unit. Project readers cannot inspect the
   installation's retained source directory, but DS had not attempted a read
   that proved files absent. This access limitation does not justify invented
   case facts. The shared planning prompt had conflicting "EVERY interview
   turn" wording despite its existing reference-replay exception.
2. DS submitted invalid plan forms: an interpreter used as a KI tool, arbitrary
   project scripts without typed bindings, and an external environment path.
   Host rejection was correct. Its claim that declared native binaries and all
   project data adapters are forbidden was false; those routes already exist.
3. A genuine KI interface gap remains. The Python runner expects
   `run_<name>.py` and pressure outputs directly in its run directory; the
   unchanged official script writes under `test_output/default_richards`.
   Python-mode environment handling also needs to provide the saved ParFlow
   installation. An exact renamed copy alone is insufficient. The source tree
   has no matching pre-generated `default_richards.pfidb` for direct execution.
   The official Tcl alternative requires topology arguments that the KI runner
   does not forward and covers a different, shorter case. A changed execution
   wrapper must not be disguised as a data conversion or used to weaken gates.

The bounded follow-up is a KDT-reviewed KI execution interface for the official
script, working directory, output location and saved runtime environment,
retaining original scientific settings. Then repeat project preflight, plan
review, native execution, reference comparison and KI result reading in the GUI.
Static reader issues to test separately: fixed porosity 0.4 versus case porosity
1.0; date-only timestamps despite undeclared model time units; and reporting
discovered dumps even when individual reads are skipped. These have not yet
been demonstrated on a fresh local solver output. Upstream Python velocity
comparisons also have reversed tolerance arguments and repeat the y check for
z; an independent comparison is required in addition to upstream's verdict.

One general source fix landed in this checkpoint: questions are now explicitly
conditional on unresolved material decisions, settled reference cases proceed
to both planning documents, and inaccessible files are identified as an
access/acquisition gap. **29 focused tests passed, zero skipped** (18 shared
planning and 11 GUI prompt integration). Independent review found no issue in
these new hunks. This prompt change is **not yet deployed or GUI-retested**;
approval, KDT and native execution gates were not changed.

Evidence: `C:/GeoForge-Tests-20261018/parflow-e2e/` contains screenshots 50--52,
the DS planning transcript, exact upstream source hashes, the complete reference
checklist and a read-only numerical audit script. Its nine self-checks include
missing/altered/invalid output failures; they are audit-code tests, not model
passes. The independent setup audit is
`C:/GeoForge-Tests-20261018/evidence/parflow-setup-independent-audit.json`.
No KI edit, native scientific run, commit, push or release occurred here.

## 2026-10-19: independent WRF-Hydro rerun, engine identity and observation comparison

This check was independent of GeoForge and read-only for the project. It reran
the native model in a separate WSL scratch directory, `~/claude-verify-20261019`,
and changed no project, KI, runtime or receipt. Evidence is in
`C:/GeoForge-Tests-20261019/claude-verification/`.

**Inputs.** All 186 staged Gridded files were byte-identical to the official
`croton_NY_training_example_v5.2.tar.gz` (SHA256 `ce79c354…ac5fc`): DOMAIN,
RESTART, both namelists and 169 forcing files. All five TBL files also match
the Run tables of a v5.2.0 build.

**Engine identity.** The bound binary (`2ea0ec71…`) was built from NCAR commit
`97ed8d28`, which is tag `nwm-v2.1-beta3`. Its `.version` file and every
CHANOBS file report `code_version: v5.2.0-beta3`. NCAR's repository has both a
stale **branch** named `v5.2.0` at that commit and the release **tag** `v5.2.0`
(`1571e9f6`, 2021-07-23). `git clone -b v5.2.0` selects the branch. The release
is 12 commits later: compiler-compliance (`intent`, `volatile`, print syntax),
build, NUOPC/Cray and NWM-output metadata changes. None of those commits
changes Noah-MP physics or channel routing. Future setup should check out the
tag explicitly, for example `git checkout tags/v5.2.0`, and verify `.version`.

**Reruns** with `mpirun -np 2` on the same staged inputs:

| Engine | Result against GeoForge's 504 streamflow values |
| --- | --- |
| Same beta3 binary | Identical (max difference 0.0); 168 CHANOBS, 8 LDASOUT, both completion banners |
| Fresh v5.2.0 build (`1571e9f6`, same CMake options plus `-fallow-argument-mismatch`, but no `CMAKE_BUILD_TYPE`, so `-O2` instead of Release `-O3`) | Max difference 0.0122 m3/s; metrics identical to three decimals |

GeoForge's run is therefore reproducible, but it is a **v5.2.0-beta3** result.

Correction (same day): the 0.0122 m3/s difference comes from the optimisation level, not the
source version. The scratch build had no `CMAKE_BUILD_TYPE` (`-O2`); GeoForge's recipe builds
`Release` (`-O3`). The engine later rebuilt by GeoForge setup from the v5.2.0 tag with Release
flags reproduces the beta3 run's 504 streamflow values exactly (maximum difference 0.0).
It should not be described as exact v5.2.0 until the engine is rebuilt from the
release tag and the binding is reverified.

**Observation comparison.** The case's `USGS_obs.csv` has three gauges, not
one. Each was matched to a CHANOBS feature by the official NWM
`Route_Link.nc` gage coordinates: 01374559 → feature 1 (0.3 km),
01374581 → feature 2 (0.2 km) and 0137462010 → feature 3 (1.3 km).
Observation times were read as UTC: the record spans 05:00 to 04:45, which
matches a local-standard-time query window. Treating them as local time makes
every score worse. Scores below compare instantaneous values on the hour over
2011-08-26 05:00 to 2011-09-02 00:00 UTC (164 hours).

| Gauge / feature | NSE | KGE | PBIAS | Peak sim vs obs (m3/s) | Peak timing |
| --- | ---: | ---: | ---: | --- | --- |
| 01374559 / 1 | 0.609 | 0.694 | +6.9% | 23.99 vs 22.20 | 3 h early |
| 01374581 / 2 | 0.527 | 0.670 | +24.4% | 48.20 vs 44.46 | 5 h early |
| 0137462010 / 3 | −0.324 | −0.201 | −26.0% | 21.02 vs 55.22 | 34 h late |

The two upstream gauges are captured reasonably for an uncalibrated training
case. The outlet gauge is not. Its output point is 1.3 km from the gauge, and
the simulated hydrograph there is strongly attenuated and delayed. The Gridded
configuration includes lakes, but this check did not establish whether a lake
lies upstream of feature 3. The station mapping and the lake representation
both need review before any outlet claim. This is one event at
three gauges: it is not calibration, skill acceptance or a KDT-adopted reader
result. The KI hourly reader still needs adoption through KDT. The scoring
script is retained with the evidence.

## 2026-10-19: pre-push regression checks and fixes

Codex was preparing to push this source to `windows-version` when its session
ended. Its last change was an untested packaging fix: the Windows build now
ships Linux-readable source under `linux-runtime/`, because the frozen bytecode
archive cannot run on Linux. `test_linux_runtime_packaging.py` now builds a
bundle from the spec's own file list and checks that the WSL sidecar gets the
same source inventory and fingerprint as a source checkout. A patched source
GUI also started on an isolated port and served the app and `/api/status`.

The first full desktop run had 84 failures. Every failing file passed at the
committed `HEAD`, so all came from the uncommitted changes. Causes and fixes:

| Tests | Cause | Fix |
| ---: | --- | --- |
| 58 | `gui.py` read the new `readonly` preflight field directly; test stand-ins lack it | Read it with `getattr`, as other new call sites already do |
| 8 | Older tests compared raw text with the new paged read output | Compare the page's file content |
| 7 | Every fresh project resolved the snapshot's pinned helpers, although only maintained setups use them | Resolve them only when a setup-maintenance adoption exists |
| 5 | Fresh projects now need a manifest; a bare test handler had none | Test stubs the manifest; links are still refused before any write |
| 2 | A runtime binary retargeted during a run aborted receipt recording | Skip the engine-link exemption and keep a failed receipt |
| 4 | Test fixtures predated new behaviour: KI root (2), stronger setup wording, locked byte reads | Fixtures and assertions updated |

The retarget fix preserves Codex's contract that alias classification refuses
a changed engine. The flow layer now checks the binding first and records the
attempt as failed instead of writing no receipt. The shared suite needed one
checklist entry: `flow/public_downloads.py` is now listed in `UPSTREAM.json`.

The real-WSL transport tests were not run. They are reserved for a disposable
WSL fixture, and the available distribution is the user's own Ubuntu.
