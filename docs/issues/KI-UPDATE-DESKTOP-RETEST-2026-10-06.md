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

At the time of this source report, the clean CRHM native rerun remains pending. Installation
checks, accepted plans and application regression tests are separate evidence
from reference-case execution and field validation. The active downloaded KI
snapshot is separate from the source repository's bundled model tree.
