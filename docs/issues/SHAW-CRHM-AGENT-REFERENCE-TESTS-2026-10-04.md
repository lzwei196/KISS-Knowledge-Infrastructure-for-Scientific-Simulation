# Running uploaded reference cases through the GeoForge agent

The intended behavior is simple: select a KI, ask the agent to run its shipped case, and let the agent discover the instructions, inputs, installed executable, run command and checks. A complete case should not require the user to supply those details again. This follow-up tests that behavior with real DeepSeek calls through the local GeoForge GUI/API, extending the earlier direct native tests.

## What was actually supplied

Both sessions received this request, replacing only the model name:

> Read the KI at D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/library-fixed/models/SHAW and run its shipped reference test case. Check the results and report any failure.

The engines were already installed and bound through GeoForge's normal existing-installation setup. DeepSeek performed setup checks. The chat request did not supply a command, test-case name, period, input list, executable path or pass criteria. The test driver inspected and approved the bounded plans through the app's normal approval cards under the user's authorization to run these tests. These were not unattended approvals, fresh engine downloads or independent new-site studies.

The source test app is at port 8791. Its staged library starts from main commit `cfdb57c16d1f14fc84dd97b6da92b6f83991673d`, includes the earlier reviewed reference-runner fixes and missing Windows guidance, and adds the SHAW platform fixes below. This is not the published Windows installer or proof of the normal updater.

## Results and friction found

| Session | Native result | Agent/host result |
| --- | --- | --- |
| CRHM `a819d961dcf3` | PASS: 26,280 hourly rows, 7,121,880 finite numeric values; original case checks. | Flow COMPLETED with signed receipt `CRHM_20261004T232156_1aaf5c`. An unnecessary reference-versus-new-study question required selecting the already-requested reference replay. |
| SHAW `64dda27b4f02` | PASS: all 26 checks; 301 hourly soil-profile records. | Flow COMPLETED. After setup fixes, the agent went directly to a reference plan. Its first execution supplied an unnecessary external-path environment variable, which the host rejected. The agent removed that variable and replanned itself; the revised approved run produced receipt `SHAW_20261004T233305_0087ae`. |
| CRHM fresh attempt `e54fba5782c0` | PASS; outputs match the independently verified native baseline. | Initially FAILED_VALIDATION: outputs were placed in `runs/badlake-reference-run1`, outside the host's result-collection roots. After the generic guidance fix and a plain continuation request, the agent selected `outputs/badlake-reference-run2` and reached Flow COMPLETED under the same approval. Its two earlier failed attempts remain in the history. |

Native completion alone is insufficient: the host must bind the actual outputs to the approved run and verify them. In the fresh CRHM attempt, the model succeeded but the host correctly refused to claim completion without output evidence. That is a Desktop agent-integration defect, not missing case forcing or a database delivery failure.

The CRHM recovery request was: “Continue the original CRHM reference-case task. Diagnose the failed validation and complete the reference run through GeoForge, preserving the existing evidence and the shipped inputs and checks. Report the verified outcome.” It supplied no commands or paths. The agent inspected the evidence and chose the corrected destination itself. It also corrected its initial guessed wrapper flag without operator instructions. Its earlier unnecessary Windows-versus-Linux criterion question was answered using the existing case contract; the later stronger guidance against that question has not been proven by another fresh session.

Independent SHAW auditing verified all five input files, all nine case-package files, the installed engine hash and all 16 signed output hashes/sizes. The signed receipt is bound to the current approval and plan. Six principal scientific output files are byte-identical to the earlier independent native baseline. The wrapper's materialised LF/CRLF difference changes its byte hash but not its normalized text; reference-case contents remain byte-identical.

Independent CRHM recovery auditing verified receipt `CRHM_20261004T234225_4b6dcb`, all seven signed output hashes/sizes, unchanged requested case files and the engine identity. The two original failed receipts and earlier native output are preserved byte-for-byte. The passing output matches the independent UTC baseline. The agent's prose incorrectly described one non-data line as a trailing record; the actual file begins with variable and units headers, and the measured row counts are correct. See the [SHAW audit](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/Agent-path-only/SHAW/completed-native-audit.json) and [CRHM recovery audit](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/Agent-path-only/CRHM-final/recovered-native-audit.json).

## Local changes

- Discover contained `test_cases` and their README/manifest/expected files in both single-KI and multiple-KI prompts. Ignore symlink destinations outside the KI.
- Tell the agent to reuse the shipped case's inputs, settings and checks for an explicitly requested replay. Do not launch a new-site interview or promote an informational cross-platform checksum into a new pass criterion.
- Explain the mapping from the selected catalogue source to its materialised working copy. A different user-specified path or revision still requires reconciliation.
- Carry result-directory guidance into planning and execution: scientific outputs go under a fresh `outputs/` directory, figures/reports under `artifacts/`, and prepared inputs under `inputs/`. The collector also retains `runs/logs/`; arbitrary other `runs/` directories are bookkeeping.
- Preserve the typed calibration engine's separate host-owned `calibration/runs/` destination; the ordinary KI output guidance does not relocate calibration results.
- Make an empty output receipt actionable while preserving the signed receipt and validation failure. The collector's scope and approval checks are not broadened.
- Fix SHAW's Windows setup paths and executable detection. `shaw303` and `Shaw303` cannot serve as distinct file/directory names on a case-insensitive filesystem. Decode native startup diagnostics with replacement for non-UTF-8 bytes so that the genuine Fortran EOF startup message can be checked. Abnormal exits and missing required imports still fail.

These changes do not invent model science or replace complete test cases with generic forcing. The native runners retain the uploaded scientific targets and tolerances. The dedicated fixed-case KI wrappers remain within the existing approved-tool policy.

## Verification and limits

The SHAW platform fix has 24 focused regression passes plus a real native startup probe. Prompt/materialisation review covered 124 distinct passing tests and one unavailable server-copy check. After the final contract wording changes, 15 prompt/integration tests and 73 shared Flow/contract tests passed; two environment-dependent shared tests were skipped. The output-feedback regression batch passed 93 tests with one skipped, including real fixture processes demonstrating that untracked outputs still fail while tracked outputs pass. These batches overlap and must not be summed as distinct coverage. Initial test invocation failures came from colliding test-package names and a missing isolated registry configuration; separate correctly configured invocations passed.

The final calibration-destination qualification passed the shared planning/API/CLI contract test and 33 focused output-feedback/calibration-binding tests. This is regression coverage of receipt handling, not a new real-model calibration experiment.

Actual provider transcripts, approval cards, run receipts and independent audits are retained under [Agent-path-only](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/Agent-path-only). Prior manual native evidence remains in the [earlier report](SHAW-CRHM-REFERENCE-TESTS-2026-10-04.md). The candidate overlay hashes are recorded in [library-agent-fixes.json](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/Agent-path-only/library-agent-fixes.json).

This establishes two authentic shipped cases, not all 127 KIs. It does not establish new-site data preparation, observation-based scientific validation, VIC or calibration in this round, fresh software installation, normal shared-tool updating, or a released Windows build. The extra CRHM question shows that consistent first-attempt behavior still needs acceptance testing even when the case itself is complete.
