# Desktop KI update test, 2026-10-06

This is a development test report, not a claim that all models passed or that a
new Windows installer has been published.

## Update observed in the GUI

GeoForge activated upstream commit
`8352acb8a7e8d1842356e021a783864917ab1efe`: 67 updated KIs, no additions or
removals. Models, installation manifests and shared tools came from the same
revision. The two data KIs remained the explicitly reported bundled fallback.
The Windows supplement retained 127 missing platform documents and 19 recipes,
and composed four recipes. Retained guidance is provenance, not proof that an
incoming tool implements the same Windows interface.

Static inspection found 58 model KIs with reference-case directories and 69
without them, including VIC. All 539 declared input files matched their recorded
sizes and hashes. DuMux's full manifest additionally names a missing generated
Python bytecode cache. None of these static checks proves a native model run or
that the forcing is suitable for a new site.

## Desktop defects corrected

- Fresh projects could copy missing files from an older installed KI after
  materializing the active snapshot. This resurrected removed reference wrappers
  and mixed versions. Snapshot projects now use the current snapshot's code,
  documents and cases, with the installed software bound separately. Existing
  project copies and results are preserved.
- Updates now keep models, manifests and shared helpers together, record their
  provenance, verify cached content and retain rejected candidates with detailed
  diagnostics. Configurable reference-case fallbacks and historical provenance
  are distinguished from mandatory runtime paths without rewriting case bytes.
- Previously verified software must be checked against a changed KI/helper/
  recipe identity. Open chat pickers refresh that status; setup displays old
  reports as history rather than current success.
- A new plan cannot describe staging or scientific checks in a custom
  `tool: null` step. It must bind a real KI tool or a reviewed project data tool.
  Only the canonical host preflight may omit its tool.
- Review applies the same environment-path containment checks as execution.
  An external `CRHM_BIN` value was previously accepted at review and rejected
  before launch. The corrected plan uses the explicitly declared executable
  argument and retains `TZ=UTC0` for the reference case clock.

## What the GUI rerun established

The initial CRHM and SHAW test projects were left unapproved after the mixed-file
defect was identified. Their old-wrapper mismatch must not be attributed to the
pristine upstream KI. CRHM's updated installation checks subsequently passed.
A new clean project produced a six-step plan with real data-tool bindings.
Review caught an inclusive-hour counting error, an always-true check and an
unwritten declared report in DS-authored adapters; corrections were requested
through the GUI before execution.

SHAW setup passed after its GUI agent enabled NTFS per-directory case sensitivity
for the installed `model/shaw` directory. This lets the `Shaw303` distribution
directory coexist with the extensionless `shaw303` executable. Read-only audit
confirmed the enabled flag and unchanged snapshot preflight, general runner,
case runner, manifest and expected-result bytes. This is a machine-specific
workaround for an unresolved portable Windows naming issue. The general runner
also regenerates control settings and does not expose the guide's documented
`--inp_file` / `--stage_from` interface for an unchanged Trial replay.

The same setup attempt recorded a native Trial run with return code zero and
four matching numeric criteria, but its unchanged reference runner returned
exit code two: `out.out` had 601 lines against 599 expected. This is a strict
reference failure, despite the successful installation check. The agent's
suggestion that the extra lines are harmless is not established without a
separate comparison.

The clean CRHM project (`92b9274afaba`) ran BadLake through the GUI on October 6.
The reviewed staging tool made exact copies of the two original inputs, then
the KI's `run_crhm.py` launched the declared Windows CRHM executable. The native
run returned zero and the unchanged reference criteria passed:

| Check | Result |
| --- | --- |
| Hourly records | 26,280; no gaps or nonfinite values |
| First / last record | 1973-01-01 01:00 / 1976-01-01 00:00 |
| Final basin flow | 0.07; expected 0.07 ± 0.02 |
| Final basin groundwater flow | 0.04638228; expected 0.04638228 ± 0.005 |
| Input size and SHA-256 | Both original files match |

The native receipt is `CRHM_20261006T161053_df7152`; the independent reference
check receipt is `CRHM_20261006T161120_e293ed`. The KI parser subsequently
produced the CSV (`CRHM_20261006T161124_1aaa98`). A separate read-only audit
confirmed the timestamps, row widths, finite values, original tolerances and
input hashes. Raw output SHA-256:
`565cd81b897ca6906be2e4b186120ed6bf8c017bd9435a9b28980a581d630839`.

The KI plotting tool generated five PNGs and returned zero, but its first host
receipt failed: the generic output validator decoded PNG binary content as
numeric text and found a spurious nonfinite token. All five images passed
independent image decoding. This is a Desktop receipt-validation defect, not a
CRHM model or data-service failure. The original failed plotting receipt
(`CRHM_20261006T161133_a55b4b`) is preserved.

The host fix validates PNG structure and decoded pixels, declares Pillow in
source dependencies and includes its decoder in all three bundle specifications.
Images remain presentation artifacts: image-only output cannot complete a
physical model step, and a valid figure cannot hide invalid numerical output.

The GUI retry passed under the existing approval
(`CRHM_20261006T163234_8c67b8`) in a separate `plots_retry` directory. Completion
initially remained blocked because the five original failed-attempt files were
still present without passing output evidence. After preserving exact copies of
those files, the failed receipt and its log in the external test archive, DS
regenerated only the original figure paths through the approved KI plot tool.
Receipt `CRHM_20261006T163517_1fae22` passed all five PNG integrity checks.
The host then reported **Completed**, with the earlier failed attempt retained
as superseded history. No model, raw check or parser was rerun; their recorded
input/output hashes and the original scientific criteria are unchanged. The
figures use a short title; the case-clock interpretation remains explicit in
the accompanying result explanation.

These are reference-case results, not a new-site calibration or validation
against field observations. Installation checks, accepted plans and application
regression tests remain separate evidence. The active downloaded KI snapshot is
separate from the source repository's bundled model tree. No fresh VIC native
run or claim that all 127 models pass is included in this test.

## Application regression evidence

The broad Desktop run recorded 2,224 passed, four outdated assertion failures
and 35 skips. After correcting those assertions, the affected and related
Desktop suites recorded 509 passed and one skip. The configured shared-library
release-workflow suite recorded 407 passed and seven skips. These suites
overlap; their pass counts must not be added. The original broad run is not
reported as failure-free. Subsequent focused tests cover the final staging,
environment review and PNG validation changes.

The final PNG/environment follow-up recorded 106 Desktop tests passed and 119
shared tests passed with three skips. It exercises the actual Desktop dispatcher
and signed receipts: PNG-only `run`, `model_run` and `route` steps cannot
complete; a plotting `process` can. Corrupt chunks, incomplete pixel streams,
truncated or invalid PNG end markers and unavailable decoders fail validation.
The `model_run` label now receives the existing numerical model-output checks.

This source update does not certify a newly frozen executable or installer.
The published Windows installer remains 0.6.56; packaging changes need the
separate build and installed-application smoke tests before a new release.
