# KI maintenance with retained evidence — 2026-10-12

## Contract

The investigation workflow now supports a bounded maintenance mode after its
three independent reviews. It freezes an intact host-managed source, checks the
existing published bibliography, generates the selected repair in a KDT Studio
draft, and runs current whole-package KDT/doctor checks. A separate signed
`MaintenanceVerified` receipt binds the source, candidate, recipe, verifier and
protected evidence. It is not a full authoring, publication, native-runtime or
scientific-validation receipt.

The two supported recipes are:

- `tool_inventory`: update derived inventory fields using the reviewed canonical
  public-tool counting rule. Other manifest values and bytes stay unchanged.
- `preflight_reporting`: add structured reporting to the recognized existing
  preflight checks. Original checks, paths, decisions and exit behavior remain
  unchanged. Restricted behavior fixtures must pass in addition to KDT.

Changes to papers, equations, scientific criteria, reference data, unrelated
tools or file membership require full authoring. `papers.json` is never renamed
or promoted to `gathered_papers.json`; metadata does not prove full-text reading.
Normal authoring/import/export acceptance remains unchanged.

Project adoption requires the exact verified candidate and original active
baseline, quiescence, fresh plan review and a new preflight for the adopted
digest. The previous tree is retained. Maintenance does not register a portable
repair for other projects or alter the global library.

## Real SHAW GUI test

Owned development GUI: port 8795, v11 source. Project `cd93028eda4b`, named
`SHAW maintenance 中文`. DeepSeek prepared the project without running the
scientific model. All subsequent KI mutations were made by GUI maintenance
actions, not shell edits.

1. Started investigation `324d14e3d9174871`; all three independent DeepSeek
   reviewers finished against one frozen context.
2. Selected **Maintenance — reuse unchanged evidence / Tool inventory**.
3. Created Studio draft `e973934d2b31` and ran the real installed KDT gate.
4. Verification `ae0aa0bd7fbf4e81` returned `MaintenanceVerified`, no failures.
5. Clicked **Apply repair and continue**; adoption completed.

Exact applied change:

```diff
 summary:
-  total_tools: 13
+  total_tools: 12
```

The before/after inventory confirms one modified file,
`knowledge_infrastructure.yaml`, with no added or removed files. Every other
file, including the bibliography, model tools and reference cases, is unchanged.
The validation values `best_nse: 0.9486`, `best_kge: 0.891` and `best_r: 0.9816`
are unchanged; they are historical KI values, not new measurements.

- Before digest: `59fe1046f659772809fdd40aa92633b993443b259e3ddcbaa18d6a9c02b7d902`
- Applied digest: `4cf628d2d63a82a3c0d3e628c8c7479b91b6f11a84687c84f2bd78c3d5797bc5`
- Native readiness remains false and the exact adopted digest requires preflight.
  The resumed agent paused about the reference-case execution location; no new
  scientific run was approved or performed in this maintenance test.

Evidence under `D:/GeoForge-Setup-Tracer-20261010`:
`maintenance-shaw-before.json`, `maintenance-shaw-result.json`,
`maintenance-shaw-verified.jpg`, and `maintenance-shaw-applied.jpg`.

## Rejected-download boundary

The old active VIC snapshot has an invalid Windows file alias. Existing older
VIC project copies are not host-enrolled, so they cannot silently acquire a
trusted maintenance baseline. The fresh quarantine contains an intact VIC with
an authentic signed publication rejection.

The new investigation source chooser accepts an opaque server-issued identity
for a rejected download. The host resolves it against the current signed update
report and verifies the exact source bytes before freezing review context. An
authentic rejection proves origin and identity, not acceptance. Such a source
can receive three reviews, a bounded draft and current KDT verification; it
cannot be applied to a project or activated in the library by this workflow.

The real GUI test also exposed and fixed a selection bug: selecting a known KI
for diagnosis used the execution integrity gate, preventing selection of
rejected VIC before the repair workflow could open. Selection now checks known
identity only. It grants no enrollment/readiness and skips calibration-code
copying for a non-intact KI. Actual run/setup guards still reject an unverified
KI. The picker now shows backend errors and preserves the current conversation
instead of replacing it with an error response.

The first VIC investigation, `13ab8f51231347e2`, then failed all three reviewers
before model calls: the context builder recreated safe package aliases, while
the reviewer boundary correctly refused all links. The fix stores alias targets
and canonical evidence paths in the packet manifest without creating filesystem
links. Canonical text still passes redaction and binary/size filtering. Actual
KI sources and repair candidates retain their aliases. A regression now passes
the generated bundle through the real reviewer boundary. Evidence copying also
preserves Windows CRLF instead of duplicating carriage returns. The failed
attempt is retained, and the next attempt freezes a new context.

## Real VIC GUI test

Project `c07f402f5777`, named `VIC maintenance 中文`, selected the authenticated
rejected VIC package from main `889a6e70332e31b21911efb0a08ac2fa2a067e03` in
quarantine `c4a5ae135ab6`. The corrected selection did not enroll or execute it.

The new investigation `92b365f3da604321` completed all three real DeepSeek reviews
against a link-free frozen packet. Selecting **Preflight reporting** produced
Studio candidate `6e3cab1883f2`. The actual installed KDT returned
`MaintenanceVerified` with no failures. All seven behavior fixtures passed:
software present with/without data, each required binary absent, each required
binary nonexecutable, and preservation of an original filesystem exception.
These are controlled in-memory preflight fixtures, not native model runs.

After the final comparison-display correction, GUI KDT verification was rerun
on the same candidate and source with verification ID `f95386700edd4290`. The
successful maintenance diff now uses the authenticated complete inventory;
unchanged aliases are not falsely shown as unexamined. Failed maintenance and
ordinary authoring retain their existing advisory comparison behavior.

- Source digest: `b8e8c6dbb9bfa4902047987c504c14dadc763db9f8ffbe87d7e0ee4d8b35a499`
- Candidate digest: `4094e2117e00d5f55c75d5a74b16034b37daeb8f319d5e352c707fae5e7c6486`
- Exactly one changed entry: `preflight_check.py`.
- 72 other file/directory entries are unchanged, including all four aliases.
- No entries were added or removed, and the rejected source remains unchanged.
- No VIC project KI was created, no adoption occurred, and no readiness was
  granted. The GUI explicitly labels this **Draft verification only — not
  applied** and does not offer Apply.

VIC's remaining activation step is a separate, explicit consumer for a verified
maintenance package. It must bind an authenticated source/receipt to a local
import and fresh runtime projection/preflight. This round does not bypass normal
authoring import or the all-package official update gate to achieve activation.
The active catalogue's legacy invalid VIC alias is also unchanged.

Evidence under `D:/GeoForge-Setup-Tracer-20261010`:
`maintenance-vic-before.json`, `maintenance-vic-result.json`,
`maintenance-vic-verified-final.jpg`, `maintenance-vic-verified-zh.jpg`,
and `server-v15-source-hashes.json`. The English and Chinese result screens
both show the single-file repair and the explicit draft-only limitation.
All 12 recorded server source hashes match the final running development build.

## Validation and limits

Automated tests cover protected-evidence changes, forged/stale receipts, source
and target drift, wrong-target adoption, recipe mismatch, workers/quiescence,
unsafe preflight syntax, behavior changes, three-review requirements, rejected
source identity, and separation from ordinary authoring acceptance. Mock-based
boundary tests do not replace the real GUI KDT result recorded above.

Recorded overlapping regression suites (do not add their counts):

- 314 passes in 100.77 seconds for maintenance core/recipes/adoption and existing
  investigation/provider/UI behavior (`maintenance-final-tests.xml`).
- 90 passes in 35.66 seconds after the selection fix
  (`maintenance-selection-tests.xml`).
- 151 passes in 20.42 seconds after the alias/context fix
  (`maintenance-alias-tests.xml`).
- 66 passes in 22.77 seconds after the complete maintenance comparison fix
  (`maintenance-comparison-tests.xml`).

Independent read-only audit of the actual SHAW result confirmed its three
reviewers, current signed receipt, one-line repair, 37 unchanged files, exact
adopted baseline, absent execution approval, `REPLAN_REQUIRED` state and pending
preflight. The applied KI and receipt also survived GUI server restarts.
Independent audit of the actual VIC source, draft and receipt also confirmed
the complete 73-entry comparison, four preserved aliases, seven passing
fixtures, no source mutation and no activation/native/scientific claim.

This is source development and GUI verification, not a compiled release. No
commit, push, release upload, official-library activation or new database/model
validation is claimed by this report.

## Extension to DSSAT, WOFOST and WRF-Hydro

The next GUI round extended the generic maintenance mechanism beyond SHAW and
VIC. The `tool_inventory` recipe now refreshes recognized existing generated
SKILL index rows and counts as well as the manifest. It preserves all other
SKILL bytes, including bibliography and scientific prose. It does not create
missing sections or accept ambiguous markers/invocations. A new explicit
`package_contract` recipe combines inventory and additive preflight reporting
when both repairs are needed. Both choices remain behind the three independent
reviews, exact source/candidate binding, current whole-package KDT and reporting
behavior fixtures. No file-membership or scientific-change permission was added.

The English/Chinese GUI names the combined choice **Tool inventory + preflight
reporting / 工具清单 + 预检报告**. The owned v16 server source hashes are recorded in
`D:/GeoForge-Setup-Tracer-20261010/server-v16-source-hashes.json`. The recipe
implementation update intentionally makes earlier unapplied maintenance source
receipts stale; fresh source capture is required. SHAW's already-applied intact
project baseline is preserved.

### DSSAT: real GUI maintenance verification

Three independent DeepSeek reviews completed for authenticated rejected source
main `889a6e70332e31b21911efb0a08ac2fa2a067e03`. Investigation
`d139ef12d2a94dbe`, Studio draft `b9eb3ea9c8a5`, and final KDT verification
`7828d744afb340ff` produced `MaintenanceVerified`.

- Candidate digest: `8141a7fc9a82a0192fba49601f780959ab2bc933c4fd31f25e740f842addba7c`.
- Only `SKILL.md` and `knowledge_infrastructure.yaml` changed: the generated
  index includes the shipped `tools/run_reference_case.py`, and counts become 20.
- 58 other inventory entries are unchanged. Tool code, bibliography, DAG,
  calibration rules and the original rejected source are preserved.
- This is a verified draft only; no application or runtime readiness was granted.

The native engine still exists, but the required four authoritative
`Genotype/China/*_China.CUL` files remain missing. The published reference runner
also retains `/tmp` and suffixless executable assumptions. This round establishes
the metadata repair, not a fresh DSSAT crop simulation.

### WRF-Hydro: real GUI combined maintenance verification

The first current-project draft request correctly refused because this new
project had no prepared KI. A new investigation explicitly selected the
authenticated rejected update source instead of silently enrolling it.
Investigation `df359ebeb4604b3f`, Studio draft `64f27b48e088`, and verification
`e04f5489cd6f48b9` completed all three real DeepSeek reviews and current KDT.

- Candidate digest: `324b444396923c1e29a3892d1737ef4b186e6b01d9cc0f5611a3a1ce488b6488`.
- Three files changed: generated SKILL inventory, manifest, and additive
  `preflight_check.py` reporting; tool count becomes 16.
- 56 other inventory entries are unchanged; all five reporting behavior
  fixtures pass. Original failure conditions/exit behavior are preserved.
- Draft-only status is explicit. No project/library adoption, WSL binding,
  executable-version acceptance or scientific readiness was granted.

The inspected WSL executable belongs to a different source revision from the
KI's declared 5.2.0 engine. An exact 5.2 source checkout exists, but no corresponding
built executable was established. Reviewers also retained separate scientific
and documentation findings; the maintenance recipe did not silently repair them.

`maintenance-crop-results.json` independently authenticates both real GUI
receipts, all six final reviewer reports and their evidence-read citations,
complete file preservation and absence of activation. Screenshots:
`maintenance-dssat-verified.jpg`, `maintenance-wrf-verified.jpg`.

### WOFOST: real setup and model-smoke evidence

WOFOST has no applicable inventory/reporting maintenance correction. Its
published source retains a strict Python 3.12 check and Unix-style paths. GUI
setup first examined the existing `C:/Python313/python.exe` PCSE installation.
DeepSeek created workspace-local path bridges, and all imports and the
entrypoint passed. Preflight `f7095c2c2c4f` still correctly failed the 3.12 check:
37 passed, one critical failure and four advisory data failures. All 55 protected
KI files remained unchanged.

That attempt produced a fresh 272-day Wangjiaba wheat smoke (1979-10-01 through
1980-06-28), with final DVS 2.0, TWSO 1531.8634 kg/ha and TAGP 9212.2458 kg/ha. The
audit found that the hydraulic-only input omitted the shipped WAV 50 and the
runner therefore used its default WAV 20. This is a modified-input runtime
smoke, not a faithful shipped-case reproduction or observed-data validation.
The agent's suggested “accept 3.13” choice could not authorize a pass; the host
retained the failure. First-attempt evidence is in
`maintenance-wofost-smoke-audit.json`.

The GUI then selected a new workspace-local installation with explicit
instructions to satisfy the existing requirement. DeepSeek downloaded official
Python NuGet 3.12.10, installed PCSE, repaired the launcher layout and saved the
actual interpreter binding. The host reloaded that configuration and ran final
preflight `d66953c40eca` through `python_env/bin/python.exe`, which resolves to
the workspace's `python312/tools/python.exe`. It passed 38 checks with zero
critical failures and four advisory data warnings; declared package requirements
also passed. The GUI shows **Verified on this machine / No action needed**.
All 55 KI files are still byte-identical. The separate 3.12 smoke used synthetic
weather; it must not be conflated with the real-data 3.13 smoke or a project E2E.

Screenshot: `maintenance-wofost-verified.jpg`. WOFOST's runner/site-parameter
handling remains a separately reviewed KI issue before faithful case acceptance.

The independent final audit is `maintenance-wofost-python312-audit.json`.
It checks the actual interpreter binding, installed runtime provenance, matching
execution identities, final host preflight and the unchanged 55-file KI inventory.
The Chinese combined-maintenance screen is captured in
`maintenance-wrf-verified-zh.jpg`.

### Extension validation and remaining scope

The integrated extension suite passed 180 tests in 29.38 seconds
(`maintenance-crop-extensions-tests.xml`). Four additional model-contract tests
cover a signed two-file DSSAT receipt, rejected human scientific prose edits,
three-file WRF projection with real reporting fixtures, and the inability of
passing fixtures to override KDT failure. Their recipe/core/guard batch passed
90 tests; these overlap the 180-test suite and must not be added together.

This round changes maintenance source code and validates real GUI workflows.
It does not activate the rejected official library, import maintained rejected
packages, build/push a release, or establish DSSAT/WRF-Hydro/native-new-site E2E.

A final setup-status consistency fix clears stale `installation_only` and
`installation_ready` fields when the host records full agent verification.
Four regression cases failed before the fix; the two targeted setup suites then
passed 85 tests in 22.27 seconds, including installation-only behavior preservation
(`maintenance-wofost-full-finalization-tests.xml`). This changes future status
records, not the previously saved model evidence. The owned development server
was restarted as v17, with source hashes saved in `server-v17-source-hashes.json`.
The GUI reopened WOFOST as verified and the saved WRF-Hydro draft as structurally
verified, draft-only. No model run was repeated for this status bookkeeping fix.

## WOFOST project handoff and bounded routing repair — later checkpoint

### Completed app fix: fresh project helpers use the final runtime

The real GUI project `beb888d10e00`, named `WOFOST runtime 中文`, initially could
not start even a read-only diagnosis. Setup had correctly changed the saved
interpreter from Python 3.13 to 3.12, but its older immutable helper projection
still contained the earlier Python binding in three files. Fresh-project
preparation incorrectly tried to rebind that active shared setup copy. The
existing integrity guard correctly refused this operation.

`Handler._session_config` now resolves the project's final scenario paths and
selected installation runtime first, then prepares a separate helper projection
under `models/<KI>` for the new project. The KI is materialized against that
matching helper/runtime pair. Shared configuration objects are copied before
modification. Existing projects keep their saved pair and validate its recorded
bytes; missing or altered helpers and changed runtime bindings still require
explicit repair. Fresh helper destinations reject directory aliases before
writing. Snapshot and bundled-library paths are covered.

The GUI retry reached DeepSeek's inspection and read-only diagnosis summary.
This closes the observed setup-to-project handoff failure; it does not establish
a new model run or transfer installation readiness into project readiness.
Screenshots are `wofost-project-handoff-before.jpg` and
`wofost-project-handoff-after.jpg` under the evidence directory below.

The independent preservation comparison recorded `all_preserved: true`:

- All 55 protected shared-installation KI files are unchanged.
- All 62 recorded old helper files are unchanged.
- Recorded shared setup state, including `kiss.toml`, `status.json` and the
  installation/placement/job records, is unchanged.
- Recorded Python executable identities are unchanged.

Evidence: `D:/GeoForge-Setup-Tracer-20261010/wofost-handoff-preservation-before.json`
and `wofost-handoff-preservation-after.json`. The latter compares the baseline
after the GUI handoff retry and isolated provider fixtures. It does not claim
that no new project files were created.

### Implemented extension: WOFOST stage-six parameter routing

Independent design review approved a new explicit recipe,
`wofost_parameter_routing`; the earlier inventory/reporting recipes did not
authorize this edit. It supports only the recognized existing
`tools/s6_execution/run_wofost_simulation.py`. A whole-runner AST identity and an
exact source-span replacement preserve all unrelated bytes, including CRLF.
Unknown variants are unavailable, and unsupported models retain their existing
recipe choices.

The projection moves the six supplied site keys (`IFUNRN`, `NOTINF`, `SSI`,
`SSMAX`, `WAV`, `SMLIM`) from the loaded soil mapping into PCSE's native
`WOFOST72SiteDataProvider`. It preserves supplied values and the original input
dictionary. Absent `WAV` retains the runner's existing fallback of 20; absent
`SMLIM` retains PCSE's default of 0.4. The shipped Wangjiaba values remain
`WAV=50` and `SMLIM=0.31`. No soil file, equation, weather value, acceptance
criterion or literature evidence is changed. This repairs routing for inputs
that previously failed with duplicate parameters; it does not prove numerical
equivalence to the earlier smoke that changed those inputs.

Any candidate that changes this tool must pass real native-provider fixtures
and the current whole-package KDT/doctor gate. Selecting a different recipe
cannot bypass the fixture requirement. The receipt records the exact source,
candidate, fixture protocol, interpreter and imported runtime content. The
project's saved runtime configuration is checked again before saving or applying
the result. The low-level adoption guard validates the receipt and runtime
content; the investigation workflow additionally owns project-configuration
matching, the three reviews and readiness invalidation.

All 53 real PCSE 6.0.13 provider fixtures passed in Python 3.12. They cover
previously valid inputs, each site key, all six together, native conversions,
boundaries, invalid values, unchanged input dictionaries and unrelated duplicate
errors. The expected provider is assembled independently from the candidate's
projection. Fixtures use a controlled subprocess with `-I -S -B`, a scratch
home/settings directory and a fresh bytecode-cache prefix. They execute only the
reviewed routing fragment and native parameter providers, never the candidate
module or a model engine.

`wofost-routing-native-provider-report.json` records these results and 955 runtime
file identities. Its flags are explicitly `native_provider_execution: true`,
`model_execution: false` and `scientific_validation: false`. The signed
maintenance receipt remains separate from full authoring and native/scientific
acceptance. The English/Chinese GUI describes this limited scope and offers the
choice only for the selected current-project WOFOST KI, including when several
KIs belong to an investigation. Rejected-download drafts cannot use this
runtime-dependent recipe.

Known limits are deliberate:

- The reviewed fixture environment is standalone Python 3.12 with the pinned
  PCSE 6.0.13 sources. Virtual environments fail closed: Python 3.12 `-S` can
  otherwise inspect base-environment packages instead of the selected venv.
  An isolated venv loader is a separate follow-up.
- `tools/s5_engine_config/configure_pcse_engine.py` retains the related routing
  issue. Stage five and the older diagnostic prose are outside this stage-six
  repair.
- A policy/module change invalidates older unapplied maintenance captures and
  receipts. New review context must be captured after the implementation is
  frozen; old receipts are not promoted to the new policy.

### Validation, open app gap and pending GUI work

These regression runs overlap; their counts must not be added:

- Helper lifecycle implementation: 100 focused lifecycle/UI passes, 138
  runtime/path passes and 13 final helper/handoff passes. Independent helper,
  adaptation and update checks also passed 40 tests in 14.28 seconds.
- Native routing module: 30 tests, including the 53 provider fixtures, passed
  (`wofost-routing-provider-tests.xml`).
- Runtime-sensitive maintenance integration: 82 focused tests passed in 31.75
  seconds, including 22 dedicated interface-boundary cases.
- GUI and repair-author integration: 124 tests passed after the multi-KI menu
  correction.
- Independent final combined review: 219 tests passed in 36.36 seconds across
  the native routing module, runtime boundaries, maintenance/model contracts,
  investigation, repair authors and GUI. No remaining blocker was found for
  this scoped implementation.

One observed app gap remains open. After an explicitly read-only diagnosis and
instruction to stop without drafts, the host displayed:
`[GeoForge: the turn ended without a plan or a question; asking DeepSeek (API) to finish it]`.
DeepSeek then wrote `runs/plan.json` and `data-inventory.json`. The plan remained
awaiting approval and **Not now** was selected; no model ran. The completion
nudge needs to respect a read-only summary/stop request instead of forcing a
planning artifact. The agent also claimed that a `project_tools` date adapter
could not be plan-bound despite typed `project_data_tool` support. Its actual
tool errors are being audited; that claim is not yet an established capability
limitation.

**Pending at this checkpoint:** fresh three-way GUI reviews on the frozen v20
implementation, creation and real KDT verification of the WOFOST routing draft,
GUI adoption, fresh project preflight, and a faithful reference run with archived
unchanged inputs. `server-v20-source-hashes.json` records the development build.
The provider-fixture report is not a completed GUI repair, reference-case result
or observed-data validation. No compiled release, push or publication is claimed.

### Real WOFOST GUI repair and adoption confirmed

The subsequent v20 GUI investigation `b94907cc6b7b4dd5` completed three separate
DeepSeek reviews against the same intact frozen context. Studio candidate
`c2d7c46557f4` passed the actual installed KDT gate and all 53 native PCSE provider
fixtures with verification `90e1431c5e494019`. **Apply repair and continue** then
completed transaction `a1232945401c4674` for this project only.

Independent read-only audit authenticated the signed investigation, frozen
source, current maintenance receipt and applied guard baseline. It also checked
the reviewers' evidence reads, complete file inventory, current native runtime
content and exact saved project runtime/helper binding. The audit did not rerun
KDT, provider fixtures, preflight or a model.

- Source digest: `5bac24f63c422cb5acd593b6c1f57e0ffd3abe23b38fb59226c3db779a0616f6`.
- Candidate and applied digest:
  `3acb934edb8be032977ce60c66f3b37a0104b036bdd9aa51725efd6f361efcba`.
- Exactly one modified file: `tools/s6_execution/run_wofost_simulation.py`.
  Its SHA-256 is `7ae460a7d52218a238f94f31d2976e0a0a527199f0e4d516c55ab3a416646f92`.
- All 54 other KI files are unchanged, with no added or removed files. The
  adopted tool exactly matches the deterministic maintenance projection.
- The active guard is intact with origin `verified_maintenance_candidate`.
  The runtime receipt and helper marker remain current.
- After adoption, the shared installation still matches all recorded original
  files: 55 KI files, 62 helper files, five setup-state files and three runtime
  executables. Its guard remains intact.
- Flow state is `REPLAN_REQUIRED`, no execution approval exists, and preflight
  remains pending for the exact adopted digest. Project `can_run` is false.

Evidence: `D:/GeoForge-Setup-Tracer-20261010/maintenance-wofost-routing-result.json`.
This supersedes the earlier pending GUI-repair checkpoint. Fresh project
preflight and a faithful reference run are still pending; no new crop output or
observed-data validation is claimed.

### Next app gaps: diagnosis completion and typed data preparation

The follow-up planning audit located the forced completion nudge in session
`beb888d10e00`, message 7 (or `memory/transcript.jsonl`, line 8). The transcript
contains the read-only stop summary, the host nudge, two
`write_project_data_tool` calls and five `write_plan` attempts. The shared planning
completion contract currently insists on a plan or question. A proposed fix is
a turn-local typed diagnosis/deferred-review completion outcome respected by
both the provider nudge and common `flowrun.after`, including API and CLI
providers. It must not change project execution state or grant approval.

The date-adapter problem is more specific than the agent's unsupported-tool
claim. The five records in `.geoforge/plan-validation.jsonl` include two KI-tool
path errors. A read-only in-memory replay with the real generated adapter
reproduced that error without a `project_data_tool` binding and returned no
validation errors with the valid typed binding. The original rejected proposal
bodies are deliberately not retained, so the missing-binding diagnosis is an
inference from the error branch and replay, not inspection of those payloads.

A valid existing binding uses the returned absolute tool path and top-level
`project_data_tool` fields `version: 1`, `purpose: converter`, the returned
`source_sha256`, literal arguments, `cwd: .` and a bounded timeout; the step is
`kind: prepare` and references its input/output IDs. Better contextual error
messages and a ready-to-use returned step should expose that supported route.

Legacy reference files under `KI/outputs/wangjiaba` are outside the existing
worker read grants. The GUI **+Files** route can stage exact files under
`inputs/uploads`; uploading does not approve execution. Any future host grant
should name exact read-only data files, not permit broad KI-tree execution.

Two additional data-format gaps remain distinct from the repaired KI: the
generic rectangular CSV output check rejects PCSE's metadata preamble, and the
current adapter contract permits YAML output only as an unchanged input copy.
The two earlier generated adapters omit the PCSE preamble and do not produce
the first 1980 agromanagement campaign, so neither establishes faithful case
preparation. The existing KI weather writer also rounds values and forces
`SNOWDEPTH` to `NaN`. The next reviewed change should declare explicit model-data
formats in the plan binding and verify their preserved source bytes/tokens,
rather than relax validation for all `.csv` or `.yaml` outputs. That work and the
eventual reference run have not been completed by this checkpoint.

### Explicit PCSE data formats implemented and reviewed — v21 checkpoint

The next bounded app change is now implemented in the host's shared flow code.
`write_project_data_tool` can return a version 2 binding with explicit
`output_formats` for PCSE weather CSV or single-campaign agromanagement YAML.
Each contract names its output ID, literal project-relative output path, format
and exact date convention or campaign date. The authoring result also contains
a step template with the binding. Version 1 retains its existing checks; no
format is inferred from a filename and an explicit format failure cannot fall
back to generic CSV checks or unchanged-copy acceptance.

The weather parser requires all eleven native site metadata fields, the exact
eight-column header, canonical dates, daily continuity and finite numeric
values. Only explicit numeric `NaN` is accepted for missing snow depth. Blank
snow would make PCSE silently skip that day and is rejected. Metadata is parsed
as bounded literal assignments without execution; extra `=` characters are
rejected to match the native reader. The YAML parser accepts one explicitly
named campaign with the exact crop-calendar structure and null event fields.
It rejects duplicate keys, anchors, aliases, custom tags, multiple documents
and oversized or deeply nested content. These are bounded format contracts,
not a general permission to generate arbitrary YAML or modify model science.

The plan binds the adapter source and invocation plus its explicit output
contracts. The signed receipt additionally binds the complete step, validator
policy and source digest. Completion rechecks current file paths, sizes and
hashes. Changed files, aliases,
hardlinks, missing reports and stale policies fail closed. Size mismatches are
rejected before opening replacement artifacts, and hashes use bounded reads.
A later authentic failed or invalid attempt remains the latest attempt; it
cannot expose an older pass as current success. Every report continues to
declare `scientific_validation: not_performed` and `model_ready: false`.

These validators run in GeoForge's **host bundled flow code**. They are separate
from the immutable helper pair used by model subprocesses. Restarting the
updated host does not require overwriting this project's pinned KI helpers.
Startup now requires the format module, and all three packaging specifications
include both shared project-data modules. This is source and startup coverage;
no newly compiled release is claimed.

The real shipped reference-data fixture verifies a date-only conversion of all
4,018 weather rows from 1980-01-01 through 1990-12-31. Every preamble/header byte
and every non-date token and newline is preserved. The agromanagement fixture
retains the exact bytes of the first 1980 campaign. The active project's source
files match the quarantined published KI exactly: weather SHA-256
`2d1744a3a10d1dc0b88eb59fae849213a7490791d51a127860db388b6fb1390c`
(182,050 bytes) and agromanagement SHA-256
`0bc12c873c7292f3c310204b657fc4c25592924b92d6967212396bdd52123917`
(3,168 bytes). Repository fixture copies differ only in CRLF versus LF, which
was independently checked; the GUI converter must retain its actual input
bytes rather than substitute repository copies.

Validation counts overlap and must not be added together:

- The parser's initial independent suite passed 65 tests in 0.64 seconds;
  later public-contract cases are included in the combined suites.
- Independent final review passed 233 tests in 35.46 seconds across explicit
  formats, output contracts, existing data adapters, placeholders and flowgate.
- The implementation owner's final combined suite passed 267 tests in
  40.86 seconds, including guarded-worker execution, receipts and regressions.
- Shared flow/receipt/core tests passed 91 cases with two skips: real-data
  derivation fixtures need an unavailable server `ata-kdt` tree for VIC and
  CaMa-Flood. No new parser or guarded-worker case was skipped; link checks ran.
- An additional root-run packaging, review, reference-input and placeholder
  selection passed 43 tests; this also overlaps the other selections.

Independent review found no remaining blocker for this format slice. These
tests executed the guarded data worker and parsed temporary fixture copies;
they did not run WOFOST or certify a crop result. The v21 source identity is
saved in `D:/GeoForge-Setup-Tracer-20261010/server-v21-source-hashes.json`.
**Still pending:** the actual GUI-authored faithful
converter, its reviewed plan and execution receipts, fresh project preflight
where required, and the native reference-case run. The separate read-only
diagnosis completion/nudge issue remains open.

### First v21 GUI planning review — converter execution still pending

The live GUI accepted the new typed adapter binding and reached plan review.
Review of the DeepSeek-authored draft found three corrections needed before
approval: its project-root parent depth was wrong, it attempted to hash a soil
file without declaring that read input, and its `weather`/`agro` output IDs did
not match the downstream model step's inventory input IDs. **Modify plan** was
selected in the GUI and the agent is correcting the draft. These are draft
review findings, not evidence of a completed converter or model run.

The UI showed a preparing-stage label while the signed project state remained
`PLANNING`. That is a possible wording/state-display gap, not evidence that a
model was executing. The faithful preparation receipt and native reference
result remain pending.

### Fresh GUI preflight reproduced the next path gap

The subsequent GUI preflight failed with 14 critical checks: the constructed
Python and model-entrypoint paths were missing, and twelve import probes could
not start that missing interpreter. All 20 canonical tool-file checks and four
KI document/diagnostic checks passed. One optional elevation-data directory was
also absent. Those failed import probes do not establish that the packages are
missing from the correctly configured interpreter.

The preflight builds server-layout paths from the project root:
`python_env/bin/python`, `models/WOFOST/run_and_score.py` and
`models/ki_tools_common`. Independent read-only inspection found all three
constructed targets absent while the saved interpreter, actual
`models/WOFOST/ki/run_and_score.py`, and pinned helper directory exist.
The next bounded repair therefore corrects these path bindings while retaining
every existing Python-version, import, file, criticality and exit-status check.
Its retained-KI adoption still requires three reviews, KDT and a new successful
project preflight; a static path proof cannot claim successful execution.

The signed failed report was independently authenticated at
`.geoforge/project-verification/ea68e5fb72b86a6a680c7ebb.json`, with complete
captured output at `.geoforge/preflight/761ec9dcb5b0/output-656c3639.txt` in the
same WOFOST project. It records preflight-only execution, return code 1, intact
source and no changed inputs or newly created KI paths. The active KI guard
still has digest
`3acb934edb8be032977ce60c66f3b37a0104b036bdd9aa51725efd6f361efcba`.
No model or project data adapter ran in this attempt. The new path-repair code
is being reviewed separately; no successful native reference result is claimed.

### Runtime-path maintenance and status correction reviewed — GUI adoption pending

The explicit `wofost_runtime_paths` recipe is now implemented and independently
reviewed. It recognizes the complete published preflight and runner ASTs, then
changes only three preflight path assignments and the matching manifest binary
path. The manifest uses the exact absolute runner inside the active project KI;
the current declared-binary resolver does not accept a relative declaration.
All other bytes, checks, Python-version requirements, imports, scientific
contracts and published evidence remain protected. It does not copy a runner,
install a runtime or create compatibility aliases.

The path recipe has a separate, complete two-file projection; it cannot borrow
a competing inventory correction for the manifest. Current KDT checks remain
mandatory. Its signed static report binds the exact saved configuration,
selected interpreter, unchanged runner, pinned helper marker and helper files.
The investigation reloads the current per-model configuration before verification
and adoption. Runtime drift, incomplete reports, extra edits and changed policy
invalidate adoption. Three reviews, normal guarded adoption, plan review and a
fresh project preflight are still required. The report explicitly records that
no native preflight, model execution or scientific validation occurred.

Independent validation passed 177 module/UI/author tests in 12.94 seconds and
35 additional maintenance lifecycle tests in 25.34 seconds. The module owner's
latest standalone selection passed 46 tests; that count overlaps the independent
selection and includes later hardlink cases. The lifecycle fixtures exercise
real projections, signatures, file identities and guards, with fixture KDT and
provider responses; they do not represent another live GUI or model run.
The integration owner's final overlapping regression selection passed 308 tests
in 110.18 seconds, plus one separate adopted-routing-baseline policy-change test
in 0.87 seconds. Already adopted, intact KI bytes remain guarded across a later
maintenance-policy change; an unapplied old maintenance receipt does not become
current merely because its candidate bytes remain unchanged.

The reproduced failure also exposed a status-display bug: the GUI had shown
the shared installation's pass beside an idle “Ready to continue” label after
the exact project preflight failed. The status projection now reads the selected
project's authenticated preflight receipts. Failed, cancelled or stale proofs
override idle/completion status, and the panel distinguishes project-preflight
counts from shared-installation counts. Independent status tests passed 73 cases
in 5.91 seconds, including failed → passed → runtime drift, forged receipts,
and English/Chinese rendering. A read-only check against this actual project
returned `failed`, `can_run: false`; its receipt remained byte-identical.

At this checkpoint the new code has not yet been demonstrated after the GUI
restart. Runtime-path repair adoption, a successful fresh project preflight,
faithful converter execution and the native WOFOST reference run remain pending.
The separate read-only diagnosis/nudge issue also remains open.

Before the v22 GUI repair, independent read-only preservation evidence was saved
as `D:/GeoForge-Setup-Tracer-20261010/wofost-runtime-path-before-adoption.json`.
It records 69 KI entries including directories, 56 pinned helper files, ten
runtime/launcher/DLL files, the exact saved configuration and 17 frozen v22 host
source files. The KI digest and previously adopted stage 6 routing tool remain
unchanged from the values recorded above. Only this audit file was written;
the active KI, runtime and failed-preflight receipt were not modified.

The retained path recipe is project-local. Automatic recognition and application
during a new upstream pull or fresh materialization is **not implemented yet**.
Each new source still requires its own materialization and verification, and
this recipe recognizes only the pinned preflight and runner ASTs with their
exact role substitutions. Closing that fresh-pull lifecycle gap is a separate
step after this project's GUI repair and fresh preflight are demonstrated.

### v22 GUI status and three-review checkpoint

The restarted GUI now shows **Project needs attention** and **0 / 1 project
preflights passed** for the failed project. This was independently inspected in
`D:/GeoForge-Setup-Tracer-20261010/wofost-v22-status-corrected.jpg`; the panel
explicitly distinguishes the shared installation's pass from this project's
failed preflight.

All three DeepSeek reviews completed for investigation `1f08d7ee9ec0434b`, bound
to frozen context
`9e98584bee2cf4d3b9edd6fc73f059f210e785cabdad0e8fc03ff7bba96ba78f`.
The independently authenticated reports agree on the path-composition defect
and confirm that the earlier stage 6 routing repair remains present. The
runtime, data/science and reproducibility reviewers read 58, 47 and 37 evidence
items respectively; this does not imply that every bundled file was read.

The principal reviewer cautions were checked without execution:

- The per-model `models/WOFOST/kiss.toml` is authoritative for this repair and
  matches the pinned helper marker. The project-level default configuration
  serves a different scope and is not borrowed by the repair.
- The helper marker's `binding.source_files` hashes refer to portable source;
  its top-level `files` hashes refer to materialized helper bytes. Their 15
  differences are expected projection differences, not evidence of corruption.
  The complete current helper marker and configuration checks pass.
- The package's unchanged `run_and_score.py --help` readiness probe belongs to
  its FAOSTAT/South-Africa verifier. The Wangjiaba plan separately and explicitly
  invokes `tools/s6_execution/run_wofost_simulation.py`. Restoring the package
  probe does not choose a different scientific runner or validate this case.
- Current plan approval was `OK`, and the actual project adapter matched the
  source SHA in its plan. The apparent `[redacted]` code line was a review-bundle
  substitution; the actual adapter contains no such literal.

No unresolved finding blocks this narrow path repair. Weather conversion and
its native reader, crop execution, output-reader agreement, and all scientific
claims remain unverified. Stage 5 and Quick Start guidance still need separate
KI maintenance; the path repair does not silently absorb those changes.

The GUI created candidate `f1fbf74c1cf0` and verification `9b641d1451b5485d`
passed the whole current KDT and static path checks. Independent read-only
receipt validation confirms candidate digest
`75246a8db803636d73a57c744c16b7d8e10fe0de890edb02d7e1038f1705c0ee`
and exactly two changed files: `preflight_check.py` and
`knowledge_infrastructure.yaml`. Stage 6 is byte-identical to the previously
adopted routing fix. GUI adoption and subsequent fresh preflight are still
pending at this checkpoint.

The first GUI apply attempt then exposed a separate host lifecycle bug:
`Cannot apply repair while project is SETUP_RUNNING`. Independent read-only
inspection confirms that Flow remains `SETUP_RUNNING` while the latest signed
project preflight is `failed` (`can_run: false`), the current plan approval is
`OK`, and the investigation remains verified with no apply transaction. The
previous post-agent preflight failure did not finalize the setup state. The
existing apply guard is correctly refusing this state and must remain intact.
The next host fix will finalize failed setup consistently across API and CLI
providers; it must not turn a failed preflight into readiness. Adoption remains
pending. Session files alone do not establish process liveness; the idle GUI
observation is separate evidence.

The host lifecycle correction is now independently reviewed: six source lines
make both API and CLI post-agent branches call the existing `setup_failed`
transition when the host check returns false. This returns `SETUP_RUNNING` to
`SETUP_REQUIRED` without clearing the failed receipt, changing approvals,
granting readiness or weakening the repair guard. Eight new cases cover API/CLI,
shared/repaired setup and failure/success, including a harmless real fixture
preflight and signed failure receipt. Pending user requests and successful
setup behavior are preserved. Independent execution of these cases and existing
handoff/project-verification tests passed 18 tests in 6.04 seconds. GUI
reproduction after restart is still pending. General Stop-before-final-check
and provider-exception cleanup are outside this narrow fix.

The v23 GUI retry now demonstrates that correction: authenticated preflight
attempt `d600f922fb9f452c88a6f23a0f29b1e7` failed on the unchanged KI, and the host
returned Flow to **`SETUP_REQUIRED`**. It did not record readiness or run the
model. Independent evidence is saved in
`D:/GeoForge-Setup-Tracer-20261010/wofost-v23-setup-failure-recovery-audit.json`.
The full KI inventory, pinned helper inventory/marker, recorded runtime files
and saved configuration all match the before-adoption snapshot. Only the
expected host `gui.py` source changed between the recorded v22 sources and v23.

The failed retry changes the project evidence, so investigation
`1f08d7ee9ec0434b` now correctly fails the full source-state freshness check:
“Project or selected KI changed since investigation; create a fresh context.”
Its candidate remains a verified two-file correction, but adoption requires a
new frozen context and three fresh reviews. The same candidate bytes do not
override that requirement. Path repair adoption remains pending.

The replacement investigation `2ed71e42c3994e7f`, context
`b01ac6da33615dd2460c288c42e31815d71ae18b1d5027fec2cafeba4ac33335`,
ended **`review_failed`** with only two completed reviewers. The data/science
reviewer cited `project/.geoforge/plan-review-requested` without reading it;
the evidence-read gate rejected that report. It must not count as a completed
third review. The runtime reviewer independently identified the three incorrect
preflight bindings and manifest path, but the replacement issue text had only
referred to “the same bounded two-file scope.” A new capture should state that
scope in full and obtain all three valid reports. No KI repair was adopted by
this failed review attempt.

The review harness now reports all invalid/unread citations in a submitted
report together, rather than revealing one per correction attempt. Its initial
instructions explicitly require a successful per-file API `read_evidence` call;
a listing, manifest entry or another reviewer's reading cannot satisfy that
requirement. The same two correction attempts, 64-round bound and time limit
remain in force. The host neither inserts citations nor credits unread files.

Future failed reviewer rows retain separate, bounded and redacted diagnostic
fields for their exact frozen context: round count, correction count, validation
errors and read records. These fields do not become an accepted report or feed
combined findings. Failed/cancelled/unsupported roles still prevent a repair
draft. The historical data/science failure above did not retain those detailed
fields, so its earlier correction history cannot be reconstructed from the saved
record; only its final unread-citation rejection is established.

Independent citation/reviewer/investigation validation passed 117 tests in
75.47 seconds. The implementation owner's overlapping selection also passed
117 tests in 76.80 seconds; these are the same selection, not 234 distinct
cases. Twelve new cases cover both API wire formats, several unread citations,
missing/unsafe paths, listing-only rejection, signed failed-role lifecycle,
diagnostic bounds, redaction and context matching. This is harness validation;
no new live review, KI adoption, project preflight or model result is claimed.

The actual v24 retry used investigation `1a96d585b0cb4a0f`, context
`cf1b12b26114352731456a1539c84bc877fe835e2dfbaf32b495d3c454ee60f4`.
Its stored 2,516-character issue explicitly names the two files and all three
preflight assignments. Runtime and data/science reviews completed at 55/56
rounds with 67/61 read records. The runtime report explicitly supports the
three-assignment plus manifest-path scope and keeps the existing package
`--help` probe separate from the Wangjiaba stage 6 run.

The reproducibility reviewer exhausted the unchanged 64-round budget after
78 reads, including many small pages of repeated context, and submitted no
accepted report. The job correctly remains **`review_failed`**. Its signed
diagnostic record now retains the 64-round count and read history, demonstrating
the new failure-diagnostic retention in the actual GUI workflow. No report in
this attempt used citation correction, so it does not yet demonstrate successful
live use of batched citation feedback. Review budgeting and retrying only
incomplete reviewers against the same intact context are the next host workflow
step; no KI adoption has occurred.

The next host patch is independently reviewed and ready for v25. API reviews
now warn near the end of their existing budget and reserve the last three rounds
or final 60 seconds for reporting. Tools are unavailable in that phase; attempted
tool calls are denied without execution and use the existing correction
allowance. The 64-round, 900-second and two-correction limits are unchanged.
The initial API/CLI prompt quotes the current issue and lists useful paths from
the sealed packet before historical chat records. This navigation provides no
citation-read credit and consults no live path from session metadata.

The GUI can retry failed or cancelled review roles using the job's original
connection. It retains completed reports unchanged only in the same signed job
and frozen context. Each retry starts an independent conversation without the
other reviewers' answers. Full source/context freshness is checked before
launch, before saving the replacement result, and at finalization; changed
sources require a new investigation. The host keeps at most six prior failed
attempt records with an explicit dropped-record count. Failed findings never
become accepted reports. Three completed reviews are still required before a
draft, followed by the unchanged KDT and adoption gates.

The backend selection passed 138 tests in 82.79 seconds; the GUI/UI selection
passed 130 tests. Independent execution of the 21 new completion/retry cases
passed in 7.98 seconds. Those 21 cases overlap the backend selection and another
root execution, so these counts must not be added as distinct coverage. Cases
include both API wire formats, reserved reporting and denied late tool calls,
API/CLI issue navigation, source/context drift, cancellation, bounded history,
unchanged completed reports, original-connection enforcement, operation leases
and GUI polling before the background worker starts. No concrete review blocker
remains in this patch. The live v25 incomplete-role retry, path-repair adoption,
fresh project preflight and Wangjiaba model execution are still pending at this
checkpoint. The pre-retry evidence is recorded in
`D:/GeoForge-Setup-Tracer-20261010/wofost-v25-review-before-retry.json`.

A separate v25 startup display gap was reproduced during the live retry. The
page initially showed `(none)` and “AI setup needed” while the authenticated
DeepSeek retry was already reading evidence, then recovered to four ready AI
connections without a settings change. This was a transient loading display,
not evidence that the working DB or AI token was invalid. A read-only audit
found that the page initializes provider state as empty/unavailable and delays
assigning fetched providers behind unrelated session/catalog status promises.
A Node replay of the shipped callback confirmed that a ready provider response
can remain undisplayed until the status request resolves. The provider endpoint
also gathers CLI health before returning API availability. The proposed separate
fix is explicit loading/error/loaded UI state and independent provider loading,
with a visible retry on fetch failure. No startup source changes or restart were
made for this finding; the current tracer remains the WOFOST repair.

The live v25 retry is now complete. Investigation `1a96d585b0cb4a0f` kept its
exact frozen context and retried only `reproducibility_risks` as attempt 2.
Independent authenticated inspection confirms both completed reviewer rows are
byte-equivalent under the recorded canonical JSON hashes. The previous failed
role remains separately recorded with its 64 rounds and 78 evidence reads;
none of its partial findings was promoted. The new reviewer completed in 30
rounds and used one citation correction: the host rejected a citation to the
previous stage 6 runner, the reviewer then read that exact file, and only the
corrected report was accepted. This demonstrates live citation recovery, though
the error in this attempt contained one missing read rather than several.

All three reports now exist against the same current packet. The new report
supports the bounded path repair and preserving the earlier routing correction.
Two claims need qualification: it describes only two failed imports, whereas
the complete authenticated preflight recorded 14 critical failures and one
advisory; and its statement that the plan remains valid cannot override the
host's required new approval after adoption or the pending plan corrections.
Reviewer opinions are analysis, not native execution evidence. The independent
audit is saved as
`D:/GeoForge-Setup-Tracer-20261010/wofost-v25-review-retry-audit.json`.
At audit time the new candidate was being verified; the active KI and prior
stage 6 routing digest were still unchanged. Repair adoption and the fresh
preflight/model run remain pending at this checkpoint.

The runtime-path correction has now been adopted through the GUI. Signed
investigation `1a96d585b0cb4a0f` reports apply transaction `801556f1840c4791`
complete, generation `83741fefc02b4fb1aca99f52e6741674`, candidate
`ddb8ed9dd2bb` and KDT maintenance verification `afd3241fb4d1494e`.
The active KI matches candidate digest
`75246a8db803636d73a57c744c16b7d8e10fe0de890edb02d7e1038f1705c0ee`.
Read-only independent receipt checks confirm the maintenance verification,
runtime-path proof and active KI guard remain current.

The full before/after inventory proves exactly two file changes:
`preflight_check.py` and `knowledge_infrastructure.yaml`. No files were added
or removed; the other 53 KI files are unchanged. The previous stage 6 routing
SHA remains `7ae460a7d52218a238f94f31d2976e0a0a527199f0e4d516c55ab3a416646f92`.
All 56 pinned helper files and their marker, ten recorded runtime files, the
saved model configuration, all three uploaded inputs and the upstream KI source
also match the before snapshot. Current host sources match the recorded v25
inventory. Expected repair history, approval/state resets and retained old KI
copies are separate adoption effects. Evidence is saved in
`D:/GeoForge-Setup-Tracer-20261010/wofost-runtime-path-adoption-audit.json`.

The GUI resumed the project agent after adoption. The signed transaction still
requires a fresh plan review and fresh project preflight; it does not grant
readiness or scientific validation. The independent audit ran no model,
preflight or KDT fixtures. The fresh host preflight and Wangjiaba end-to-end run
remain pending at this checkpoint.

Two subsequent app fixes are prepared and independently reviewed in isolated
scratch sources; neither was active during the adoption above. The startup
provider patch introduces explicit loading/error/ready states, starts provider
metadata loading independently of session/catalog verification, retains known
connections on fetch error, and offers a bounded retry. Independent execution
of its standalone browser-logic tests passed 12 cases with no skips. The owner
also checked the existing settings/parity and provider-kind behavior. Existing
session/provider locks remain in force. The prepared patch is under
`D:/GeoForge-Setup-Tracer-20261010/bootstrap-provider-scratch`.

The other patch gives an explicitly approved shipped KI `check` step a typed
`stdout_artifact` contract. It captures complete decoded stdout separately from
stderr and the truncated diagnostic tail, accepts only bounded strict JSON in
a fresh declared project output path, and binds the signed result to the full
step, inventory, invocation, validation policy and current artifact bytes.
Invalid/duplicate-key/nonfinite JSON, overflow, failed or stopped children,
changed approvals/KIs, collisions, aliases and stale receipts cannot pass.
A later failed attempt remains authoritative over an earlier pass. The receipt,
returned summary and evidence summary explicitly label this as a check artifact
with `model_executed: false`; it cannot become model execution evidence.

The stdout patch's independent dedicated run passed 49 tests in 29.61 seconds,
with no skips. One warning comes from Python's Windows reader thread when a
fixture deliberately emits invalid UTF-8; the assertion confirms no artifact
or passing evidence is produced even when the child exits zero. The owner's
final overlapping regression selection passed 210 tests with ten skips. All ten
skips are existing POSIX process-group/session/termination or SIGTERM receipt
cases on Windows; every stdout, parser and worker case ran. These counts are
not additive.
The 1 MiB artifact limit is checked after the existing collector returns and
does not bound process-output memory. This patch neither evaluates scientific
acceptance criteria nor runs the WOFOST model. Source and tests are staged in
`D:/GeoForge-Setup-Tracer-20261010/stdout-tracer-source`. The subsequent packaging
review confirms mandatory Flow startup import and hidden imports in all three
desktop specs; four independent startup/spec tests passed in 1.92 seconds.
These four are separate from the 49 dedicated cases above. Live activation and
an actual compiled application build are still pending at this checkpoint.
Shared API/CLI planning and execution guidance for the same contract has also
been independently checked: ten tests passed in 0.08 seconds against the staged
validator, including validation of the actual JSON example. It explicitly
declares the future output path while keeping its inventory status `missing`,
requires literal arguments and project cwd, and keeps the native reader
unchanged. These are prompt/contract tests, not an additional model run.

A read-only check of the proposed run found several incorrect draft criteria,
so they must be corrected before approval. The unchanged v22 adapter has SHA
`fe6a8fc6cfc8437f18d0fcf1f9d8da3c8ca52ff045c2459d095197de0c7f5309`
and already preserves all 4,018 weather rows from 1980-01-01 to 1990-12-31,
every non-DAY byte, and the exact first 11-line 1980 campaign. Its fixed output
directory `outputs/prepared_v21` is still absent and usable for this first run.
The native runner should consume the original uploaded soil file directly.
The draft's 4,019-row figure and equation of daily row count with campaign count
are incorrect. Its lower radiation bound of 2 MJ every day would reject actual
supplied days as low as 0.8856 MJ. Pre-sowing crop-variable blanks occur in the
shipped historical output and must be distinguished from nonfinite active-crop
results. The native saved summary is a list of campaign summaries, whereas its
stdout and the s7 reader contain daily row counts and differently named/rounded
metrics. Any later agreement assessment must compare the actual corresponding
fields with their stated precision. These are draft review findings, not model
results or changes to the supplied inputs.

The reviewed stdout capture, shared guidance and provider-loading patches are
now activated in the v26 source server. Its frozen 23-file source inventory is
`D:/GeoForge-Setup-Tracer-20261010/server-v26-source-hashes.json`. Root's
integrated selections passed 120 core tests (including the 53 dedicated stdout
and packaging cases), ten guidance tests, 12 browser-logic tests and 108 existing
UI tests. These overlap the earlier selections. No compiled release build is
claimed by this source-server activation.

The corrected four-step plan has been written and approved in the GUI. It uses
the unchanged v22 adapter with exact typed weather/agro outputs, the native
stage 6 runner with the original soil upload, and the native s7 reader with the
new explicit stdout artifact contract. The faulty custom agreement checker is
excluded. Some broad finite-value prose remains, but the rationale and approval
note explicitly allow June 1–14 pre-sowing crop blanks and state that this is
not observational validation. Actual result comparison is deferred until the
native output files exist. A crop-cache byte-identity baseline was recorded at
`D:/GeoForge-Setup-Tracer-20261010/wofost-v26-crop-cache-before-run.json`.
Fresh project preflight and execution are starting; their results remain
pending at this checkpoint.

### v26 actual WOFOST end-to-end result — 2026-10-13

The GUI run has now reached `COMPLETE`, with all six declared output files
present. Fresh authenticated project verification is `verified` with
`can_run: true`, attempt `e0590bef27fe4dc5b9a49460465db995`. Both the exact
project preflight and current manifest requirements passed. The preflight
returned zero, retained the source unchanged and captured its complete output;
the optional elevation-data advisory does not become a critical failure.

The independent stdlib-only audit passed all 66 checks. It authenticated the
current approval, Flow state and three execution receipts; verified the exact
approved plan, adapter and native tools; and checked all six current artifact
hashes. Weather preparation preserves all 4,018 dates, the original metadata
and every non-DAY byte. The first 1980 campaign is preserved byte-for-byte.
The original soil input, adopted KI, previous stage 6 routing repair, pinned
helpers, runtime and saved configuration remain unchanged. The native s7
reader's JSON was captured through the explicit check-artifact contract; its
receipt correctly records `model_executed: false`. The native stage 6 execution
has its own authenticated receipt. This audit executed no model or KI tool.

The native daily output contains 98 rows, from 1980-06-01 through 1980-09-06.
Final yield (`TWSO`) is 2,527.980880 kg/ha, above-ground biomass (`TAGP`) is
4,512.216363 kg/ha, maximum LAI is 0.93363018, and final DVS is 2.0. The
June 1–14 pre-sowing crop blanks are expected; crop values are finite once
present. Rounded s7 metrics agree with their corresponding native values.
These results demonstrate reference execution and internal consistency, not
validation against observations or exact reproduction of a historical target.

Two explanations in the agent's initial result text needed correction. Native
summary emergence (`DOE`) is June 21, when DVS is zero; the s7 reader reports
June 22 because it chooses the first day with `DVS > 0`. This is a definition
discrepancy, not a rounding offset. Also, installed PCSE aliases
`Wofost72_WLP_FD` to `Wofost72_WLP_CWB`; that selected configuration explicitly
uses `WaterbalanceFD` for freely draining soil. It is not a groundwater model,
and the alias does not show that a different scientific configuration ran.
The subsequent GUI discussion was read-only and did not replan or rerun.
Any change to the KI reader remains a separate KDT-reviewed maintenance task.

Evidence is saved under `D:/GeoForge-Setup-Tracer-20261010/` in
`wofost-v26-reference-run-audit.json`,
`wofost-v26-crop-cache-before-run.json`,
`wofost-v26-crop-cache-after-run.json`, and
`wofost-v26-end-to-end-result.png`. The crop cache is byte-identical before and
after the run. All 23 files in `server-v26-source-hashes.json` also remain
unchanged through execution. This closes the current retained-project WOFOST
tracer. No commit, push, compiled build or release was performed in this round.

The next setup tracer remains open: automatic path normalization after a fresh
KI pull is not implemented. The proposed hook runs after ordinary
`port.materialise` and before adaptation enrollment/provenance, distinguishes
the physical scratch destination from the final logical target, and uses a
separate staged proof. It must not relax the retained-project runtime-current
checks or inherit readiness from an older source. Setup, investigation replay
and bundled fresh materialization should share the same bounded projection,
while retaining existing project pairs. Tests must exercise real
`port.materialise` with LF and CRLF sources; manually reversing substitutions
does not cover its actual newline handling. Fresh source identity, signed
lineage and a new project preflight remain required. Broader DSSAT/WRF-Hydro
fresh-pull coverage and the separate read-only planning-nudge behavior are
still follow-up work; this WOFOST result does not close those gaps.

### Fresh-pull path implementation and DSSAT preparation — 2026-10-13

The next bounded path implementation is now prepared and under regression
review. It applies the recognized WOFOST two-file path overlay after ordinary
role materialization, using the final logical KI path even when the physical
candidate is still in a staging directory. The general role-substitution
behavior is unchanged. Signed retained-source proof binds the projection to
its source and target; existing saved project KI/helper pairs are preserved.
This does not create readiness or replace fresh runtime verification. It is
not a general transformation for DSSAT or arbitrary updated KI code.

Root's regression selections passed 225 tests: two disjoint selections of
160 and 65. The independent review selections of 163, 19 and 9 overlap these
checks and must not be added to that total. At this checkpoint, the fresh
bundled-KI path still needs its helper-marker binding seam corrected. Source
tests and review do not establish successful GUI activation, a fresh project
preflight, or a new model run. The end-to-end GUI check remains pending until
that correction is integrated and exercised.

The GUI's latest **Check again** completed against main
`889a6e70332e31b21911efb0a08ac2fa2a067e03` and again rejected 17 packages.
The active library remains snapshot `e3ed93f067f2f2693294d0ff5d1f98ad`, from
source commit `8352acb8a7e8d1842356e021a783864917ab1efe`. DSSAT's published
index still omits `tools/run_reference_case.py` and declares 19 tools instead
of 20. Its previously verified metadata-only draft has not established setup
readiness or a native simulation. No update success is claimed.

A separate read-only audit found a usable official DSSAT reference case in
the existing clean `DSSAT/dssat-csm-data` checkout at commit
`99c95b340acb9515c2d0a8ab582f5fbbf076f345`. Under
`D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/geoforge-workroot/dssat/dssat-csm-data`,
the Gainesville 1982 case includes `Maize/UFGA8201.MZX`, its native `.MZA`
harvest and `.MZT` time-series observations, all 365 daily rows in
`Weather/UFGA8201.WTH`, and profile `IBMZ910014` in `Soil/SOIL.SOL`.
The installed genotype file contains cultivar `IB0035`, and the Windows
`dscsm048.exe` exists. This dataset is separate from the downloaded KI; the
current and rejected DSSAT packages have no `test_cases` directory.

The four `Genotype/China/*_China.CUL` files are absent from the inspected local
installation and latest pulled Git tree, although DSSAT's preflight requires
them for every case. The separate `dssat_data` distribution bundle has not been
inspected: its cached manual metadata supplies no download URL, so its contents
remain unknown. This is not evidence that every upstream distribution lacks
these assets. The existing maintenance recipes cannot remove
or downgrade those checks. The valid unchanged-gate route is to restore the
authentic server assets. A case-specific prerequisite contract would be a
separate reviewed change: it must require the selected FileX's actual
cultivar/ecotype/species files and still reject a China case missing its
requested coefficients. It cannot manufacture coefficients or simply mark
all regional requirements optional. The public reference runner also retains
Windows path/launch assumptions and generates new inputs, so it is not the
faithful entry point for the unchanged Gainesville FileX. GeoForge already
supports a declared native-binary plan step once setup and binding pass.

Read-only evidence, exact asset hashes and remaining constraints are recorded
in `D:/GeoForge-Setup-Tracer-20261010/dssat-official-case-readiness-audit-20261013.json`.
The audit ran no model, preflight or KDT tool and downloaded nothing.

#### Intended DSSAT GUI run — pending

After setup is valid, DeepSeek should stage the official native case and
observations unchanged, use the correctly bound declared Windows executable,
and begin with treatment 1 in an approved short working directory. Native
support-file/profile paths, fresh execution receipts, `Summary.OUT`,
`PlantGro.OUT` and logs must be checked before comparing the matching native
observations. Historical scratch outputs are not evidence for this run.
GUI preparation, approval, fresh preflight and native DSSAT execution remain
pending. No new DSSAT end-to-end success, scientific validation, compiled
build, commit, push or release is claimed at this checkpoint.

### v27 fresh WOFOST verification and v28 DSSAT readiness repair — 2026-10-13

The fresh-path implementation and bundled helper-marker correction are now
integrated in v27 (11 changed source files). Root's two disjoint regression
selections passed 225 tests (160 plus 65); the previously reported independent
review selections overlap and are not additional tests. The projection stays
limited to the recognized WOFOST two-file path correction, keeps general role
materialization unchanged, distinguishes the final logical target from the
physical staging directory, and authenticates its retained source proof.
Existing saved project pairs remain preserved. Projection alone does not
grant readiness.

The fresh WOFOST project was then exercised through the GUI. Its exact current
project preflight and manifest requirements passed, with an authenticated
receipt reporting `verified` and `can_run: true`. The captured native preflight
contains 42 checks: all 38 critical checks and three optional checks passed;
one optional elevation-data check remains an advisory. The independent
read-only audit passed all 27 checks, including receipt authenticity, exact
saved configuration, signed projection lineage, helper binding and unchanged
source. All 26 v27 host source hashes, the older project's adopted KI, its six
v26 output artifacts and three execution receipts were unchanged. Evidence:
`D:/GeoForge-Setup-Tracer-20261010/wofost-v27-gui-preflight-audit.json`.
This closes the fresh WOFOST path-and-verification tracer, not another native
model run or validation against observations.

DSSAT exposed a separate app routing bug in the GUI: the fresh project's
authenticated paths were correct, but three host gates still rejected it
because the older shared setup KI had changed. A project was therefore sent
back into shared setup instead of being allowed to perform its own exact
verification. The proposed v28 correction classifies only shared `ki-edit`,
`ki-revision` and `snapshot-changed` reasons as eligible to attempt project
verification. It neither declares the project ready nor executes or repairs
the older edited KI. All other setup/runtime failures, coupled-KI checks,
project source/configuration/helper guards, real preflight and manifest checks,
and authenticated current receipts remain required.

Review caught a runtime fallback edge before integration: those shared reasons
can precede the missing-runtime check, while the generic configuration loader
can fall back to base Python. The v28 predicate now reads the exact saved
installation configuration and requires its selected absolute Python file;
it also rejects the frozen app launchers that would trigger discovery/fallback.
It performs no runtime discovery or substitution. Existing project bindings
still have to match. This correction does not add an in-place binary-content
guarantee beyond the existing verification contract.

The frozen v28 candidate passed the author's 59-test selection and an
independent run of all 25 dedicated cases (13.64 seconds); those 25 overlap
the 59 and must not be summed. The tests exercise API and CLI controller paths,
real harmless passing/failing preflights, all three permitted provenance
reasons, missing/malformed/foreign saved configurations, missing or frozen
selected Python, source/project/configuration/helper/receipt drift, coupled
and manifest requirements, Stop, and read-only planning. Independent code
review found no remaining blocker. At this checkpoint v28 integration and
its actual DSSAT GUI retry are pending; these test results are not a native
DSSAT execution result.

The library selection remains unchanged: main `889a6e70332e` was rejected for
17 packages, and the active library retains source `8352acb8a7e8`. DSSAT's
regional cultivar requirement, unchanged native Gainesville inputs, fresh
approval and actual model outputs still need to be resolved or verified in
the GUI. No native DSSAT success, compiled build, commit, push or release is
claimed here.

### v28 DSSAT checks and v29 recovery through the GUI — 2026-10-13

The v28 fix was integrated and exercised on the fresh Gainesville project at
`D:/GFTests/2026-10-13-DSSAT-Gainesville--b8b03523f587`. The host now reaches
the project's real DSSAT preflight instead of rejecting it on the older shared
KI's status. The independent audit passed all 44 checks. Its authenticated
failed receipt, attempt `0e00ec1811334337a0ffbcc2c421ea05`, contains 30
preflight checks: 25 passed and five critical data checks failed. The failures
are exactly the China directory and `MZCER048_China.CUL`,
`WHCER048_China.CUL`, `RICER048_China.CUL` and `SBGRO048_China.CUL`.
The selected Python, native binary startup, imports, bound helpers and KI
files passed their checks. Manifest requirements were not attempted after the
preflight failure. The GUI correctly reports `SETUP_REQUIRED`, 0/1 verified,
and scientific execution remains blocked.

The audit confirms unchanged project KI/configuration/helper/Python bytes,
unchanged shared installation assets and all 26 v28 host source hashes. The
shared KI guard was already failing in the baseline; the audit did not create
a new edit. The startup probe wrote only diagnostic files in its scratch
directory. There are zero native model-run receipts. Evidence is recorded in
`D:/GeoForge-Setup-Tracer-20261010/dssat-v28-gui-preflight-audit.json`;
the captured output is under project scratch `4ddec784b7e7/output-90db756c.txt`.
The root's additional 56-test readiness selection passed and overlaps the
earlier v28 tests; it is not an additional unique-test total.

Five official reference files were then imported using the GUI's **+Files**
file chooser: `UFGA8201.MZX`, `.MZA`, `.MZT`, `.WTH` and `SOIL.SOL`.
They are now under this project's `inputs/uploads`, where the agent has the
normal project read scope. All five hashes match the unchanged reference
checkout at `99c95b340acb9515c2d0a8ab582f5fbbf076f345`, including its
observations. The evidence is `dssat-gui-reference-import-audit.json` under the
same tracer directory. This import grants no model readiness or approval.
GeoForge already supports the declared DSSAT native binary in a plan; needing
a new KI replay wrapper is not an established execution-capability blocker.

The next GUI attempt exposed a host recovery gap. Selecting **Check with Agent**
for the manual `dssat_data` dataset while in `SETUP_REQUIRED` repeated the
failed preflight before DeepSeek could inspect the data requirement. v29 adds
an explicit host recovery card instead. **Review and revise plan** revokes the
old approval and enters `REPLAN_REQUIRED`, with the existing restricted
planning tools and a new approval required before acquisition or execution.
**Retry project preflight** reruns the real checks under the current approval;
the card explicitly explains that passing checks continue the already
approved plan. Ordinary chat does not silently retry a current failed check.

The card is bound to an authentic failed receipt, its current KI/configuration/
manifest identity, selected models and approval. Unknown or stale actions are
rejected without clearing the current request; unrelated waiting requests are
preserved. Revocation occurs before the state change, and atomic card writes
preserve an unrelated file even if the old destination is hardlinked. The
integration contains three production files and two dedicated test files.
All 40 new tests passed, including real failed/passing subprocess checks and
the actual chat-controller route for API, Claude, Codex and Kimi. Independent
testing passed those same 40 distinct cases (39 plus the separately added
crash-order case); these repeated runs are not additional unique coverage.
The final combined run after the wording correction passed 40 in 25.87 seconds.

Existing desktop regression selections passed 174 tests (125 flow/setup,
16 project-verification/terminal-failure and 33 acquisition cases). A separate
shared-core run passed 56 and skipped two real-data derivation fixtures
because the server's `ata-kdt` data/cards tree is absent on this Windows host;
those skips do not concern the recovery tests. The shared run also retained
an existing NumPy/NetCDF ABI warning. Exact integration hashes and selections
are saved in `project-preflight-recovery-v29-integration.json`.

The v29 GUI behavior is now confirmed: an ordinary message in the existing
failed DSSAT project displayed the new recovery card without another preflight.
Choosing **Review and revise plan** started DeepSeek's planning investigation;
the screenshot is `dssat-v29-recovery-card.png`. The independent point-in-time
audit passed all 25 checks: state is `REPLAN_REQUIRED`, current approval is
`MISSING`, and the authentic archived approval matches the signed recovery
context. The latest failed preflight attempt
`358d0d73ac614daea3824097c5abc956` remains blocked; there were two attempts
before and after recovery, zero model/download receipts and no new scientific
outputs. All 27 v29 host source hashes, project/shared protected files and five
imported reference files remain unchanged. Evidence:
`dssat-v29-gui-recovery-audit.json`. The `dssat_data` catalogue entry is
275.9 MB and marked for manual Baidu delivery, but no bundle download,
contents or cultivar availability has yet been established. The agent's
metadata investigation and revised plan are still in progress. Native DSSAT
execution, observed-data comparison and any release remain pending.

### DSSAT manual bundle handoff — 2026-10-13

DeepSeek completed the GUI replan and a new diagnostic plan was approved.
The app's authenticated manual-data handoff then obtained the Baidu share
metadata for `dssat_data`, including the `geoforge_obs/dssat_data` subfolder.
Its host-selected destination is
`D:/GFTests/2026-10-13-DSSAT-Gainesville--b8b03523f587/inputs/observations/dssat_data`.
This confirms that the acquisition workflow can reach a real manual handoff
before model setup passes; it does not show that the bundle was downloaded.

Opening the share was blocked by the browser's **SITE SECURITY POLICY**. The
browser reported that no automatic approval review or user-permission prompt
was attempted. No alternate route was used to bypass that policy. The user
has been asked for a local folder or archive path so the authentic bundle can
be inspected. No bundle bytes have been retrieved, and no scientific model
has run. Whether this bundle contains the four required China cultivar files
remains unknown; the earlier absence finding still applies only to inspected
Git and local installation trees.

The draft project inspection tool also used `inputs/downloads/dssat_data`,
which differs from the host's actual `inputs/observations/dssat_data` handoff
destination. This was caught before claiming a successful inspection. A GUI
plan correction is pending; the path mismatch is not yet reported as fixed.
No app source, native inputs, KI requirements or scientific acceptance criteria
were changed in this manual-handoff checkpoint.

DeepSeek subsequently corrected and resubmitted the plan and inventory through
the GUI. The inventory now specifies `inputs/observations/dssat_data`, and the
inspection tool's absolute `--bundle` argument points to that same host
destination. The adapter was recreated at its existing project path with
reported source SHA-256
`0f11c8ddbd54bbcffd754911e6ee63bf70b3bff222a1f828754ef549b8d5d39a`.
The revised submission is awaiting review and the independent final audit;
submission is not approval or a successful inspection. Its scope is bundle
acquisition followed by read-only inspection, with no simulation, installation
or KI edit.

The user asked what `dssat_data` contains and whether the web server already
has it. It is a supporting-data bundle, distinct from the KI's instructions
and tools, but its actual contents and presence on the web server have not
been verified. The global China-cultivar prerequisites may be broader than
the standard Gainesville case requires; that possibility is not permission to
remove or weaken the current checks. No local bundle folder or archive path
has been provided. Retrieval, contents inspection and native DSSAT execution
remain pending.

### Final DSSAT diagnostic checkpoint — 2026-10-13

The corrected plan, inventory, adapter code and arguments have now been
reviewed through the GUI. The independent audit passed all 27 binding and
preservation checks, confirming the matching destination and actual adapter
SHA-256 `0f11c8ddbd54bbcffd754911e6ee63bf70b3bff222a1f828754ef549b8d5d39a`.
The revised plan remains **unapproved** in `WAITING_FOR_USER`; approval is
`MISSING`, project readiness remains failed, and the two failed preflight
attempts are unchanged. There are no native model receipts, download receipts
or generated inspection report. All 27 v29 host source hashes and protected
project/shared/reference assets remain unchanged. Evidence is saved in
`D:/GeoForge-Setup-Tracer-20261010/dssat-v29-final-diagnostic-plan-audit.json`.
These checks authenticate the submitted bindings and preservation; they do
not certify that the future inspection can execute successfully.

The source now identifies the precise KI/data/setup contract gap. Published
`preflight_check.py` lines 205–213 unconditionally require the China directory
and all four regional cultivar files for every case; the desktop did not add
these checks. By contrast, `tools/dssat_workdir_setup.py` lines 1188–1223
merge the regional cultivar records only if that directory exists. The
Gainesville case's standard maize cultivar `IB0035` is already present in the
installed `MZCER048.CUL`, and its native soil profile is `IBMZ910014`. This is
static case evidence, not proof of a completed simulation. The Windows setup
recipe builds the pinned upstream DSSAT engine and retains its supplied Data
directory; it does not acquire the separate manual `dssat_data` bundle.
Thus the current installation procedure and the KI-wide readiness requirements
do not establish the same data prerequisites. A case-aware correction or
authentic supporting-data installation still needs its proper review; the
current checks have not been weakened. Neither the web server's filesystem
nor the Baidu bundle contents has been inspected.

The diagnostic draft also retains limitations that must be addressed or checked
once the real bundle is available:

- The project-data worker limits directory inputs to 256 files. The bundle's
  actual file count is unknown, so the complete library may be rejected before
  the inspection tool runs.
- The generated-report inventory entry incorrectly inherits the bundle's manual
  dataset metadata and catalogue size. Acquisition currently consumes only the
  bundle input, but the summary can repeat the download requirement. This does
  not indicate that a report exists.
- The adapter lists and hashes at most 500 CUL files and computes its China-file
  flags from that list. A truncated listing cannot establish absence. Its
  directory check also expects a `Data/Genotype/China` suffix, so the actual
  archive layout must be considered.

The corrected destination therefore closes the submitted path mismatch only.
The browser-policy block, unavailable local bundle and the diagnostic caveats
remain open. No further source change, bundle retrieval, installation, KI edit,
native DSSAT run, observational validation or release was performed.


### v30 source checkpoint: declared runtime data and authoring support — 2026-10-13

The user authorized automatic acquisition of genuine required setup data and a
KDT-reviewed correction that checks the requirements of the selected DSSAT case.
The v30 source changes are integrated; the server remains stopped while the
focused GUI tests finish. There is no v30 live-GUI success, new native DSSAT run,
observational validation, compiled release or publication claim at this checkpoint.

The optional `runtime_data` manifest contract declares a pinned HTTPS Git source,
full commit, target role and relative directory, and the exact source path,
SHA-256 and byte count of each required support file. This is standard runtime
support data; project forcing, soil, management, calibrated parameters and
observations still require their own declared case inputs. Read-only status and
project verification check current bytes and never acquire files. Explicit setup
preparation reuses the existing installer Git transport with no build commands,
restores only missing declared files, and refuses conflicts, aliases, hardlinks
and writes outside the selected managed setup workspace. It does not establish
model or scientific readiness. New setup may prepare the declared support data;
existing-installation discovery remains read-only. The explicit GUI data-only
repair action and its guarded project/shared-runtime binding are integrated but
await the fresh GUI tracer.

For DSSAT, the independent source audit read raw Git blobs at the engine recipe's
existing official commit `40793f8d654ca033d027ec3a6cea53cf2f546602` from
`https://github.com/DSSAT/dssat-csm-os.git`. It enumerated all 282 regular files
under Data. The proposed required-runtime contract includes the 275 files outside
Data/Help, totaling 2,379,567 canonical bytes. The seven Help documents are
explicitly excluded. The saved setup configuration maps `home/DSSAT/Data` to the
existing selected runtime; the portable contract contains no Windows drive alias.

All 275 installed runtime files match the official LF content in uniform CRLF
representation. The opt-in `text_newlines: lf_or_crlf` rule accepts only exact LF
or entirely CRLF text; mixed newlines, lone CR, NUL and other byte changes fail.
The declaration hashes canonical LF content, while receipts also bind the actual
raw file hash and byte count. With the field omitted, exact raw bytes are required.
Existing valid files are never rewritten. An empty isolated test workspace
successfully acquired all 275 files through the real pinned official Git source in
34.5 seconds. A repeat verified them without another acquisition. No active
installation, project, KI, engine build or scientific run was involved.

The three CHM Help files have different checkout bytes from their raw Git blobs.
The fresh isolated checkout reproduced the same expansion. The pinned upstream
`.gitattributes` explicitly sets `* text eol=crlf`, with binary exceptions only for
PDF and DOCX, explaining the CHM transformation. This is upstream checkout
attribute behavior, not a demonstrated GeoForge corruption. No help viewer was
tested, and the CHMs are neither certified nor replaced by the runtime contract.

Core implementation checks passed 202 tests plus four subtests in the isolated
candidate. A separate independent overlapping selection passed 105 tests plus
four subtests, and independently rechecked all 275 declared raw Git blobs, the
existing CRLF runtime files and the isolated LF acquisition. The initial integrated
core selection passed 147 tests; GUI integration tests are still pending here.
These are overlapping selections and must not be added as one distinct total.
The 108 warnings in the 202-test run are existing Python venv deprecations.
Legacy manifests omit the absent optional field from canonical serialization,
so this feature alone does not change their stored manifest identities. A regression
also verifies that authentic older project receipts remain usable when no new
contract is declared; changed declared data invalidates current project readiness.

Two other bounded source corrections are integrated for the next GUI pass.
Producer-aware inventory stamping distinguishes generated outputs from acquired
inputs, preventing a generated DSSAT report from inheriting a manual bundle's
catalogue metadata. Explicit download producers and genuinely external inputs
retain acquisition requirements. The KDT evidence importer now uses extended
Windows paths for nested Git packs, reserves only a new attachment destination,
and removes only its own partial copy on copy failure. Existing attachments,
name collisions, changed aliases and original source files are preserved. The
importer passed 23 tests plus four subtests, including six dedicated cases; an
independent run passed the same overlapping selection.

The live KDT authoring draft `ddc5420056bc` remains unadopted. Its metadata check
failed, and review found semantic flaws in the first draft. DeepSeek's next GUI
repair pass is pending; neither the proposed runtime-data contract nor a relaxed
case check has been accepted into the active KI by this source checkpoint.
KDT evidence and validation remain mandatory. The manual Baidu bundle has not
been retrieved, and the browser security-policy restriction has not been bypassed.

Evidence is under `D:/GeoForge-Setup-Tracer-20261010/runtime-data-evidence/`:

- `DSSAT-required-runtime-data-authoring-evidence.md` contains the full proposed
  contract and source rationale for GUI Studio attachment.
- `dssat-runtime-data-contract.json` file SHA-256 is
  `ca1a5427c0c74b11f4e48618bcc5e9b195ba29135bdf16f4253c4a831798781c`.
  This is the JSON file hash, not the separately canonicalized receipt-contract hash.
- `dssat-all-official-data-audit.json` retains all 282 source/installed file records.
- `dssat-runtime-data-real-acquisition-result.json` records the isolated missing-data
  acquisition and repeat verification; `runtime-data-independent-readonly-audit.json`
  records the independent source and representation check.
- `DSSAT-help-checkout-followup.txt` records the upstream attributes finding, refining
  the original authoring evidence's then-unresolved CHM conversion origin.
- `runtime-data-core-tests.xml` records the 202-test core selection.

The next proof is the actual v30 GUI path: repair the KDT draft, verify and adopt
only an accepted candidate, exercise explicit required-data preparation against
the selected runtime, then rerun exact project preflight before continuing the
approved DSSAT case. Data-only preparation must not create readiness or trap a
project behind unrelated shared-KI setup; that lifecycle is part of the GUI check.

### v30 live GUI checkpoint and prepared retry correction — 2026-10-13

The v30 server is now running with its 38-file source inventory frozen. DeepSeek
has started the second repair-authoring pass through the GUI, using the new
optional **Repair instructions** field. These instructions are recorded in the
authoring log, remain separate from the frozen independent reviews, and cannot
waive KDT validation or adoption checks. The first draft `ddc5420056bc` has not
been adopted: its KDT result had three required metadata failures, and source
review also found an undefined `DSSAT_GENOTYPE`, a soil-profile parse selecting
`180` instead of `IBMZ910014`, and an insufficient case heuristic. The current
pass is being instructed to remove that heuristic, declare the exact 275 official
runtime files and repair the metadata. A strict case wrapper is a subsequent
pass; these are work in progress, not accepted corrections.

The integrated GUI provides **Prepare required data** for the selected project.
It reads the project's guarded adopted KI and exact saved configuration, verifies
that its Python and runtime target match the managed shared installation, and
uses the existing setup job, cancellation and project-operation locks. It checks
the binding before and after preparation. The action does not run a model or
preflight and deliberately leaves verification required. New setup prepares an
opted-in contract after engine acquisition; existing-installation discovery stays
read-only. Read-only status and native-preflight recording enforce current
declared data even when there is no catalogue snapshot identity.

The root's integrated selections passed 147 core tests and 97 GUI tests; the
display follow-up repeated 23 tests successfully. The isolated GUI work passed
250 distinct tests, including the 41 dedicated data-action, installation, UI and
author-refinement cases. An independent reviewer repeated those 41 successfully.
The integrated and independent selections overlap the isolated counts and must
not be added. The final 41-case runs had no skips and nine existing Python venv
deprecation warnings. The final display change labels successful data-only
preparation **Verification required**, rather than **Verification failed**.

A further lifecycle seam was found and fixed only in the isolated v31 candidate:
successful data preparation writes shared status `verification-required`, but
the project-verification route previously recognized only shared KI provenance
failures. With an otherwise intact shared KI, this could send retry back through
old shared setup rather than verify the project's repaired KI. The candidate
adds this one status to the route into exact project checks; it grants no
readiness. Strict saved-runtime validation, source/project/helper guards, actual
preflight, manifest requirements and signed project receipts remain mandatory.
The tests use an intact shared KI and a separately guarded project KI, execute
the real data-only action and harmless project preflight through API and Claude
routes, and verify that deleted data, changed helpers, missing runtime, coupled
dependency failure and failed native preflight remain blocked. Eleven dedicated
tests and 25 existing provenance tests passed, 36 distinct cases. Independent
review verified the frozen candidate hashes and repeated all 11 dedicated tests:
11 passed in 17.89 seconds, with no skips or warnings and no blocking findings.
The v31 patch awaits integration between active DS passes; it is not part of
the running v30 source.

The v31 candidate and baseline hashes are recorded in
`D:/GeoForge-Setup-Tracer-20261010/runtime-data-project-retry-v31/runtime-data-project-retry-v31-manifest.json`.
The GUI candidate hash is
`8045654d21c3f774cce7e2003524fc86239a6d88b29e3bd43ed5c74e01116429`.
No live KI adoption, required-data GUI success, new native DSSAT run, readiness,
compiled release or publication is claimed at this checkpoint. The Baidu bundle
remains uninspected; the new official-data contract does not establish its contents.

### Verification failure recovery prepared for v32 — 2026-10-13

The real v30 DSSAT verification of investigation `e0f8b69815af4aa2`, linked to
Studio draft `ddc5420056bc`, reached the separate portable-reuse check and was
rejected because the effective installation recipe changed. The verifier stored
`verification_failed`, but the GUI worker's generic error handler overwrote it
with `failed` and discarded the verification record. That older generic state
could not enter a new authoring or verification attempt through the backend.
This was a repair-workflow bug; the rejected candidate was not adopted.

The isolated v32 recovery patch preserves the specific verification failure,
its failed verification identity and visible error, and releases the operation
lease normally. Older authenticated generic failures may offer a fresh attempt
only when the three complete reports still identify the same frozen context and
the draft still identifies the exact Studio candidate. Every attempted mutation
still checks all current frozen sources and context; a new verification executes
the complete current gates. Failed, cancelled or interrupted adoption never gains
this draft-recovery route. The previous host error is also included in the next
author's context. No old verification authority is restored, and no adoption or
scientific execution starts automatically.

The new tests reproduce the real portable-registration recipe rejection through
the GUI worker using a sealed KDT test fixture. The unchanged candidate fails a
new attempt; a corrected test candidate must pass a fresh check before adoption
can be offered. They also cover legacy failure recovery, stale source/context,
wrong candidate or Studio identity, mismatched reviews, signature tampering,
cancel/adoption states, and bilingual error rendering after the worker lease
clears. The combined selection passed 208 tests in 114.11 seconds, including 23
dedicated cases. Independent review repeated those 23 in 29.44 seconds, with no
skips, warnings or blocking findings. These counts overlap.

The reviewed recovery patch and exact baseline/candidate hashes are in
`D:/GeoForge-Setup-Tracer-20261010/verification-recovery-v32/verification-recovery-v32-manifest.json`.
Its GUI baseline is the v31 retry correction. The root has stopped v30 and
integrated that v31 correction plus the separately reviewed v32 adaptation change;
the recovery delta awaits integration and a fresh GUI retry at this checkpoint.
Native DSSAT execution, KI adoption and project readiness remain unproven.

### Repair author log feedback loop: diagnosed; v34 candidate prepared — 2026-10-13

The GUI subsequently started authoring again under v32. The broader third DSSAT
repair pass ended honestly as `author_failed`: its final JSON said `incomplete`,
reported no edits and admitted that it had not inspected the current candidate.
The retained log contains five successful tool markers: one KDT listing, one
workspace listing and three workspace reads. The author identified those reads
as the two completed author logs and its own active log. There were no write
markers. This is not evidence of a model run, successful repair or KDT acceptance.

The log filename timestamp to the observed terminal job timestamp spans 48.257
seconds. The explicit host error is an incomplete author report, rather than a
time or round-budget exhaustion. This author loop allows 64 rounds and 900
seconds, with 8,192 maximum output tokens per API response. Exact round and token
usage were not retained by the GUI handoff and cannot be reconstructed from the
log. The response itself contained a long summary; there is no host compaction
step in this author loop. The audit is
`D:/GeoForge-Setup-Tracer-20261010/dssat-author-pass3-harness-audit.json`.

The host prompt contributed to the detour by asking the author to inspect current
files and prior `runs/repair-author-*.log` records first. Its own live output log
was already present in that same readable workspace. The next GUI attempt was
therefore narrowed to the validator, with current candidate/evidence reads and
no log reconnaissance; the runner remains a separate pass.

The isolated v34 harness correction makes candidate files and supplied evidence
the first source of truth. Completed logs remain available only as optional
history for a specific unresolved question. Both API and CLI prompts identify
the current log explicitly and prohibit reading it. The API's actual workspace
listing/read tools exclude only that active file identity, including canonical
and hardlink aliases; an independent completed file with the same content stays
readable, and this pass's log becomes ordinary history for a later pass. No
history is deleted, no evidence is truncated, and no budget, verification or
adoption gate changes. CLI enforcement here is the shared prompt rule, not a
new claim of file-level OS isolation.

The isolated selection passed 70 tests in 10.22 seconds, including nine new
actual-tool, API-wire and CLI-prompt cases, with no skips or warnings. Patch and
hash manifest are under
`D:/GeoForge-Setup-Tracer-20261010/author-log-scope-v34/`.
Independent review passed the same nine dedicated cases in 1.29 seconds, with
no skips, warnings or blocking findings; those nine are included in the 70-case
selection. The source hashes were independently checked. Live integration is
pending at this checkpoint; the active validator-only GUI pass is not interrupted
or changed by this source work.

### v32 integrated checkpoint and remaining DSSAT work — 2026-10-13

The v31 project-retry correction, the v32 additive runtime-data adaptation gate
and the v32 verification-failure recovery are now all integrated. The root's
integrated checks passed 64 tests plus a separate 23-case recovery selection,
87 focused tests in total. These repeat portions of the isolated and independent
suites above; they are not an additional distinct feature-test total. The source
inventory is frozen at 38 files, and launcher process 62252 is starting the v32
server. This records source integration and tests, not a successful server health
check or a completed GUI retry.

The last DSSAT authoring pass declared the exact 275 official runtime files and
passed both portable and runtime KDT checks. Adoption was still rejected by the
separate effective-recipe comparison. The new comparator permits only an absent
runtime-data contract to become a valid explicit requirement from the unchanged
engine recipe's exact repository and full pinned commit. Every other effective
recipe field must remain identical. The declared target must be a strict child
of the unchanged installation directory, and each file must preserve the exact
case-sensitive source-subtree mapping. This proves the same pinned source content;
it does not assert that `home/DSSAT/Data` and the engine build checkout are the
same physical directory. Existing contracts cannot be removed or replaced under
this exception, and source, Python, binary, dependency or installation changes
remain rejected. Existing runtime-data path and acquisition restrictions still
apply.

The registered repair remains keyed to the original upstream context. A fresh
projection of that same source can reuse the reviewed stronger requirement;
changed upstream source, recipe or helper identity requires reconciliation.
The dedicated adaptation selection passed 53 tests. Across that selection and
the broader baseline adaptation/runtime-data run, 146 distinct cases passed;
the broader run emitted three existing Python venv deprecation warnings. An
independent reviewer passed the overlapping initial 48 cases and found no source
blocker. Lifecycle tests use explicit synthetic KDT acceptance fixtures, not a
claim of scientific KDT validation. The patch inventory and exact hashes are in
`D:/GeoForge-Setup-Tracer-20261010/runtime-data-adaptation-v32/runtime-data-adaptation-v32-manifest.json`.

The GUI recovery correction retains a specific verification failure and its
diagnostics, and permits a fresh guarded authoring or verification attempt when
the original context and candidate still match. It does not revive the rejected
verification. The v31 route lets a data-only action's `verification-required`
status proceed to actual checks of the exact project KI and saved runtime;
it does not treat data preparation as model readiness. Both corrections are now
part of the integrated source, superseding their earlier pending status above.

The remaining work is bounded and still open:

- **GUI repair and adoption:** retry the rejected DSSAT candidate under v32 and
  complete current verification and explicit adoption. The draft remains
  unadopted at this checkpoint; the new host exception is not adoption evidence.
- **Case-specific requirements:** DSSAT phase 3 has not started. The strict case
  wrapper must check the selected experiment's actual soil, cultivar, weather
  and management requirements through the KDT workflow. Official standard data
  does not establish that regional China assets or other case inputs are present.
- **Live data and preflight lifecycle:** exercise the GUI's explicit required-data
  action against the adopted project contract, then require a fresh passing
  exact-project preflight. The real isolated 275-file acquisition is established;
  a successful live GUI data action and project readiness are not yet established.
- **DSSAT end-to-end result:** resume the approved case through DeepSeek in the
  GUI only after those checks pass, inspect genuine model outputs and the reader,
  and report any observational comparison separately. No new native DSSAT run
  or validated scientific result is claimed here.
- **Distribution and unresolved external material:** a new compiled Windows
  release is not claimed. The Baidu bundle remains uninspected under the earlier
  browser restriction. The seven excluded Help documents, including the three
  CHMs affected by upstream checkout attributes, remain outside the required
  runtime-data contract and have not been tested in a help viewer.

No active project, KI, runtime data or application state was changed to write
this checkpoint; it is a documentation update only.

### v34 live checkpoint: validator repair under review — 2026-10-13

The v33 portable-path correction and v34 author-harness correction are now
integrated with baseline/candidate hash checks. The root's focused integrated
selection passed 45 tests in 1.56 seconds; these overlap the earlier isolated
selections and are not an additional distinct total. The v34 GUI is running
with launcher 68748, listener 80252 and a frozen 38-file source inventory.
The earlier `{KI}` path false positive is corrected. Actual GUI KDT verification
`1d8f8f0711e24b7c` still rejected new `/absolute/path/...` CLI examples in the
candidate. That is a remaining portable-draft defect, not the earlier parser
false positive, and the candidate remains unadopted.

The first focused DeepSeek validator pass completed through the GUI and added
`tools/validate_selected_case.py`, bringing the reported public tool count to 21.
Independent testing ran only an isolated copy of this non-model CLI. The unchanged
official Gainesville treatment 1 passed, correctly identifying IB0035 → IB0001,
soil IBMZ910014, 365 weather days and the original 13 mm irrigation event. This
establishes a useful parser positive, not native execution or project readiness.

Of 27 isolated cases, 13 met their stated expectation and 14 exposed gaps:
12 false acceptances and two false rejections of valid native-format boundaries.
The exact tested source hash was
`a9e2c33359d104a4a196bf2119f4d4bec1c07e533438b92b9d58aaad2b25276d`.
All 280 copied official case/runtime files and fixture metadata were preserved.
The concrete remaining validator work is:

- Resolve every selected treatment factor and simulation-control level; missing
  initial-condition, planting, fertilizer and selected control rows currently pass.
- Use native fixed columns for the simulation name/model and cultivar/ecotype
  fields; valid long simulation names and one-word cultivar names are misread.
- Reject malformed weather values, header-only soil, garbage species content,
  wrong-model cultivar overrides and profile paths that do not bind the inputs.
- Preserve the exact reference irrigation event; changed amount/code or blank
  irrigation selection must not silently become a different experiment.

The source-grounded report
`D:/GeoForge-Setup-Tracer-20261010/dssat-validator-phase3-review.txt` was attached
through the GUI. DeepSeek is now repairing only that validator under the new
candidate-first harness. Its latest revision has not yet been independently
retested. The canonical runner remains a separate next step: it must preserve
the original case bytes, create and validate the exact native profile, call the
same case validator immediately before launching DSSAT, and retain real output
and failure evidence.

Current status supersedes the earlier “phase 3 has not started” checkpoint:
host recovery and harness changes are integrated; case validation is in active
repair; portable KDT acceptance, explicit adoption, the live required-data action,
fresh project preflight and native DSSAT end-to-end execution are still pending.
No candidate was adopted and no native DSSAT model was executed in this round.

### v34 validator retest: bounded reference guard still required — 2026-10-13

The repaired validator was independently tested at exact SHA-256
`d1dee965576131a14a457e2c4a963899094d5bb6f8c19f342b7c14729d9e1ce2`.
The unchanged official Gainesville treatment 1 still passes. All 27 earlier CLI
regressions now meet the revised supported-scope expectations, and all six authored
format tests pass. Fixed-field parsing and required selected sections improved;
the selected genotype files now match the pinned runtime-data hashes and declared
newline policy. A one-word cultivar name parses correctly in the independent
parser check, while changing the full published genotype file is intentionally
rejected by this bounded interface. Profile path resolution is explicitly left
to the future canonical runner, so these results do not prove native path binding.

Seventeen additional CLI boundary cases found nine remaining gaps in broader
parser/structure claims. Examples include minimal fake soil layers, missing
selected management, changing MI to zero, invalid initial-condition/date fields,
an impossible calendar day, and using another filename or treatment to evade
reference-only checks. These do not require a general DSSAT parser for this tracer:
the required next boundary is exact SHA-256 identity of all five original input
files plus treatment 1, followed by byte-identical staging and the same validator
on the exact staged inputs/profile immediately before native launch. Comparing
source and staged bytes alone would also preserve a modified experiment and is
therefore insufficient. The public validator claims must match this limited scope.

A separate strict-JSON correction is pending: an irrigation `nan` value correctly
fails the case, but remains NaN in its diagnostic result and serializes as invalid
standard JSON. The failure result must replace nonfinite values with an explicit
null/error and serialize with `allow_nan=False`.

Actual GUI KDT verification `6f17a92877a14faf` remains blocked by the added test
file's tool inventory/count mismatch: the declaration says 21 while the package
contains 22 counted files. This must be reconciled in the KDT draft. Host source
v34 remains frozen; no KI has been adopted and no native DSSAT model has run.

Full evidence is
`D:/GeoForge-Setup-Tracer-20261010/dssat-validator-phase3-repair-review.txt`, with
isolated results under `dssat-validator-review-d1dee965/`. The review used 45
distinct validator CLI invocations (27 regressions, 17 added boundaries and one
JSON-output case), six authored tests and separate parser/hash/I/O checks.
The original fixture tree and live candidate hash were preserved. These are
validator tests, not model execution, readiness, calibration or scientific validation.

### DSSAT runner review and KDT acceptance checkpoint — 2026-10-13

The new `tools/run_gainesville_reference.py` now passes the independent isolated
runner review: 18 intercepted-launch cases, 20 native-output-format parser
fixtures and six authored tests passed. This is the current selection; do not
add it to overlapping historical counts. The review confirms both the official
CRLF runtime and canonical LF representation reach the expected intercepted
launch. Existing run directories, missing or changed reference inputs, late
staged-input/profile drift and contradictory profile bindings stop before launch.
Missing, inconsistent or malformed result records and native error-output fixtures
remain failures. All purported native output in these tests is explicitly synthetic;
the reviewer did not execute the engine, and baseline files remained unchanged.
Evidence: `D:/GeoForge-Setup-Tracer-20261010/dssat-runner-review-f9cbecad/final-isolated-results.json`
records `all_expectations_met: true` and `native_model_executed: false`.

Following a final docstring-only rephrase, actual GUI KDT verification
`47e420dc057b45a6` passed for both the portable candidate and its Windows project
snapshot. The accepted project-snapshot digest is
`bb44d60539d3224821dbadf1734a2a4d91b4065eacbde70ba7911f93946b05e0`.
The final runner hash is
`18304402d49c88ae5ed07aae3af2253b010a7d4b8f160da408be3d021c8d7cb7`;
independent comparison confirmed its executable AST matches the tested runner
with docstrings excluded, and the validator, authored tests and Windows manifest
are unchanged. That comparison is recorded in
`D:/GeoForge-Setup-Tracer-20261010/dssat-runner-final-bounded-review.txt`.
The earlier inventory/count failure no longer blocks this verification. A minor
host quality gap remains: the portable-path lexer can mistake slash-separated
prose for an absolute path. The draft prose was rephrased; the gate was not waived.

Explicit adoption, fresh actual project preflight and the native DeepSeek GUI
run are the next pending steps. Passing KDT and intercepted runner tests does not
establish native execution, observed fit, calibration or end-to-end completion.
This checkpoint changes documentation only; host source v34 remains frozen.

### v35: adopted DSSAT repair, prepared data, project recheck route — 2026-10-13

The GUI has now explicitly adopted KDT verification `47e420dc057b45a6` into
project `b8b03523f587`, with accepted project digest
`bb44d60539d3224821dbadf1734a2a4d91b4065eacbde70ba7911f93946b05e0`.
The GUI's **Prepare required data** action then succeeded against that exact
project KI: all 275 declared official runtime files match. This supersedes the
earlier pending adoption/data-action checkpoints. It does not establish a passing
project preflight or native model execution, and says nothing about the separate
uninspected manual Baidu bundle.

The next actual GUI attempt exposed a host routing bug. The Setup page URL retained
`session=b8b03523f587`, but its recheck POST dropped the session and entered generic
shared setup. That route correctly rejected the previously edited shared KI,
instead of checking the newly adopted project KI. The existing v31 fix covered
project chat/retry; it did not cover this Setup-page POST. No fresh project
preflight was produced by that failed attempt.

The v35 correction is now integrated from the reviewed hash manifest. A
session-scoped Setup page uses the existing project's guarded KI and strict saved
configuration through an explicit project-preflight endpoint. It checks the
selected shared interpreter and runtime bindings, verifies the pinned project
helpers, and runs the existing real project preflight and manifest requirements.
It neither rematerializes the KI nor invokes generic shared setup. The project
operation lock and shared setup lease prevent overlap; Stop targets the exact
attempt and revokes a pass if cancellation is accepted during finalization.
Project checks do not mark shared installation readiness, approve a plan or start
the model. The page now polls and displays the project result, keeps its session,
and returns to the same project.

The final dedicated selection passed 31 cases: 26 controller cases and five Node
UI cases, with no skips or warnings. Independent execution passed the same 31 in
20.23 seconds; the root's integrated live-source run passed them in 19.99 seconds.
These repeat executions are not additive counts. Tests include the real data-only
action followed by exact-project recheck, passing and failed preflights, damaged
bindings, missing runtime data without acquisition, overlapping operations,
late Stop and post-pass binding changes. All four candidate hashes and live
baselines matched the frozen manifest before integration, and the patch check
passed. Evidence package:
`D:/GeoForge-Setup-Tracer-20261010/project-setup-preflight-v35/project-setup-preflight-v35-manifest.json`.

The v35 server is starting on port 8795 with launcher 74056. At this checkpoint,
the **actual fresh GUI project preflight and native DSSAT run remain pending**.
The next tracer is to pass that check, execute the unchanged official Gainesville
treatment 1 through the approved DeepSeek GUI plan, and inspect authentic native
outputs and the reader. Intercepted runner tests and successful data preparation
must not be reported as that run.

Remaining scope is limited but explicit:

- Complete the real DSSAT project preflight and native reference run; then report
  any comparison with the shipped observation separately from execution success.
- Keep broader DSSAT cases outside this exact five-input, treatment-1 reference
  guard until their own case contracts and fixtures are reviewed. General parser
  coverage, new-site performance and calibration are not established here.
- New upstream KI revisions still need their own source/policy checks. The latest
  17-package update rejection and other model-specific compatibility gaps are not
  resolved by this DSSAT repair or by the bounded WOFOST fresh-path projection.
- The manual `dssat_data` bundle and remote server filesystem remain unverified.
  The project-data inspection input-file cap and large-bundle traversal limits
  remain separate follow-ups; required runtime-data preparation does not use that
  inspection as its acceptance proof.
- The portable-path lexer's prose false positives and a new compiled Windows
  release remain separate work. No build, release upload or push is claimed in
  this checkpoint.

Only this issue document was changed to record this checkpoint; no live project,
KI, runtime or application state was changed by the documentation update.

### v36: real project preflight passed; exact runtime arguments repaired — 2026-10-13

The v35 project-scoped GUI check now passed against the adopted DSSAT KI. Actual
preflight capture `709b61554b56` reports 21 critical checks passed, four optional
checks passed and five optional China-data checks absent. The authentic project
verification receipt is `ee7a426aaa644846a089724410822d96`, with `state: verified`.
Its runtime-data evidence covers the exact target and all 275 declared files.
This supersedes the earlier pending project-preflight checkpoint. Optional
regional data absence is not proof that the separate manual bundle lacks those
files, and this pass alone is not a native case run.

The next real GUI execution attempt stopped before model launch in
`kiss_cli/runtime_arguments.py`. The executable was already explicitly declared
and bound by the current receipt, but its installation is under the saved
`home/DSSAT/build/bin` path; the existing argument rule required the separate
`binaries` role. The runner's exact `--runtime-data` directory was also declared
and verified, but there was no corresponding external argument allowance. The
plan reached this dispatch check because review-time validation resolves the
project KI/configuration but does not perform the same external argument check.

The v36 fix is integrated from the frozen two-file patch. A trusted KI tool may
name its exact signed native executable under either the saved `home` or
`binaries` role. Only `--runtime-data` may name the exact support-data root in the
current project receipt. Current verification still rechecks the data contract,
ordinary path constraints and every declared file's actual identity. Positional
paths, output options, undeclared executables, parent/sibling/child paths,
alternate aliases, stale receipts and project-authored data tools do not gain
this capability. This is an argument capability for reviewed KI tools, not an
operating-system read/write sandbox. Executable binding pins its declared path
and resolved target; this change does not add executable-content hashing.

Independent execution of the focused selection passed 99 cases in 66.97 seconds:
51 new runtime-data/home-layout cases and 48 existing runtime-argument cases,
with no skips or warnings. Both API and CLI exercise the real common dispatch
using a harmless Python wrapper that records arguments; the native executable
is never run in those tests. Missing/changed data, representation changes,
alias replacement, wrong configurations and missing/current-proof failures remain
blocked. The implementer's overlapping run also passed all 99; do not add these
repeat counts. Both candidate and live-baseline hashes matched the manifest and
the patch check passed. Evidence package:
`D:/GeoForge-Setup-Tracer-20261010/runtime-arguments-v36/runtime-arguments-v36-manifest.json`.
The production module SHA-256 is
`cd7b9aa1ef3236ce431a067b129688da11bc6d98b7c89a234bf62abbef195faa`.

The v36 server is starting on port 8795 with launcher 59140; its frozen source
inventory is `D:/GeoForge-Setup-Tracer-20261010/server-v36-source-hashes.json`
(39 files). **The actual GUI native retry and resulting DSSAT outputs are still
pending.** No native execution, observed fit or end-to-end success is inferred
from the successful preflight or these harness tests. Early review-time path
diagnostics remain a separate usability improvement; no readiness-before-setup
requirement was added to planning. No new compiled release is claimed.

This checkpoint updates documentation only; it changes no project, KI, runtime
or live application state.

### v37: native DSSAT reference replay and strict execution evidence — 2026-10-13

The real DeepSeek GUI run now completed both approved executable steps in the
fresh `outputs/DSSAT/gainesville_replay_20261013_verified` directory. The native
receipt `DSSAT_20261013T125338_a62e75` and reader receipt
`DSSAT_20261013T125344_3ae8d9` both record exit code zero and passed validation.
The host preflight again passed all 21 critical checks. The native run produced
129 consecutive daily PlantGro records (1982-02-26 through 1982-07-04), exactly
one treatment-1 Summary record, and no ERROR.OUT. The actual saved replay report
is 144,183 bytes; the native host receipt retains hashes for all 313 changed
files. The approved invocation, including `--receipt`, was executed exactly.

This fixes two gaps exposed by the preceding real run. Ordinary KI calls with an
explicit approved command now enforce its literal argument array and resolved
working directory at the common API/CLI dispatch boundary. CLI derives its cwd
from that approved step. Receipt evaluation also rejects an authentic attempt
with a different invocation. For ordinary steps with declared output inventory
items, every exact output must be fresh and nonempty. Numeric validation covers
the declared scientific results; an explicit `json_report_v1` field validates a
strict structured report without counting it as numerical model evidence.
Other changed files remain hashed supporting artifacts. Unknown policies,
partially declared output contracts, missing outputs, stale bytes and changed
supporting artifacts fail closed. Typed data, stdout and calibration contracts
keep their own validators. Legacy absent-command plans retain their old argument
scope; wholly symbolic output IDs absent from the inventory retain the old
all-changed-files validator and receive no supporting-file exemptions.

The integrated selection passed 155 tests in 70.49 seconds, with one existing
invalid-UTF8 negative-test thread warning. Independent review separately passed
55 invocation and 47 output-contract cases, with overlapping counts not added.
All 11 integrated files matched their reviewed manifests; the source server
started with 40 frozen production files. Packaging declarations were checked,
but no new executable was built or published.

Independent read-only audit confirmed the five official case inputs remain
byte-identical to their published anchors; all 275 installed runtime files match
the pinned contract; 274 staged runtime files are byte-identical and the remaining
DSSATPRO file is the intended local profile. The executable copy matches the
selected runtime. Native HWAM is 2,293 kg/ha against the official MZA observation
of 2,929 kg/ha: signed difference -636 kg/ha and PBIAS -21.7139%. This is one
reference-case workflow, not new-site scientific validation or calibration;
r, NSE and KGE are undefined for the single yield pair.

Evidence: `D:/GeoForge-Setup-Tracer-20261010/dssat-v37-real-native-result-audit.json`.
The old `DSSAT_20261013T123107_ff6599` receipt remains failed and byte-unchanged;
all its 312 recorded output hashes remain intact and its omitted runner report
remains absent. The new run does not retroactively relabel that attempt.

At this checkpoint, the overall project remains incomplete for one separate
reason: after both receipted steps passed, DeepSeek wrote an extra one-row
`hwam_replay_timeseries.csv` outside a receipted tool. GeoForge correctly lists it
as the sole unreceipted artifact. A reversible GUI archive action is being tested
to preserve such files for review without treating them as model evidence.
Other remaining gaps are the stale shared-KI readiness banner, unanswered older
question visibility, provider turns that stop after preflight, broader KI data
declarations and fresh-update coverage, and actual new-site/calibration studies.

### v38: GUI recovery and completed reference workflow — 2026-10-13

The reversible archive action is integrated and exercised through Project status
in the live GUI. The sole extra file,
`outputs/DSSAT/gainesville_replay_20261013_verified/hwam_replay_timeseries.csv`,
was moved to the project review archive with its 302 bytes intact (SHA-256
`dc87377f847cb18a94b4f3c99021d288b892130b11372ede4ac2bb5b6e2d4e6d`).
Archive identity `f78195d46f644c27a8dc031d1ca1b942` has a signed host audit;
the GUI exposes downloads of both the preserved file and the audit. This does
not turn the extra CSV into model evidence. Required inventory files, approved
file arguments and every authentic historical receipt's referenced inputs and
outputs remain protected. Context, file identity and idle-operation checks are
repeated at the atomic move boundary; path aliases and hardlinks are rejected.

The integrated archive selection passed 105 tests in 32.28 seconds with no
warnings or skips. Independent review separately passed 61 host cases and 27 UI
cases; these overlapping runs are not additional test counts. The reviewed eight
file changes include packaging declarations. The live v38 source checkpoint
contains 41 production files. No new Windows executable was built or published.

A status-only DeepSeek continuation used two read tools, without rerunning
DSSAT or the reader and without creating replacement output files. The normal
host evidence evaluation then advanced the signed Flow state to `COMPLETED`.
Project status visibly reports **Project complete** and **Flow completed with
current approved execution evidence**, with all five workflow stages checked.
The preceding successful native and reader receipts remain the evidence for
this completion. Earlier failed attempts are retained as failed attempts.

GUI evidence is saved outside the live project:

- `D:/GeoForge-Setup-Tracer-20261010/dssat-v38-archive-gui.png`
- `D:/GeoForge-Setup-Tracer-20261010/dssat-v38-project-complete.png`
- `D:/GeoForge-Setup-Tracer-20261010/dssat-v38-result-dashboard.png`

The bounded outcome is now a completed Windows reference-case workflow using
DeepSeek in the GUI: automatic preparation/verification of the declared 275
runtime support files, KDT-reviewed case-aware checks, real native execution,
the reviewed observed-yield reader, signed evidence and a result view. The five
official case inputs were imported unchanged; this does not claim automatic
acquisition of every new site's inputs or of the Baidu data bundle. All 21
critical preflight checks remain enforced. The yield remains 2,293 versus 2,929
kg/ha, with one observed pair and no r/NSE/KGE or calibration claim.

Remaining gaps observed in this tracer:

- The shared-KI readiness banner still says verification is needed despite the
  adopted project KI passing; sidebar counts and older questions can also be
  stale. The data inventory cards retain generic preparation/scientific-check
  labels after the reference workflow completes, so their scope needs clearer
  explanation. One result-view report card links to the chart instead of the
  runner report.
- Provider guidance still needs to prevent stopping after preflight or writing
  additional outputs outside an approved run. Detection and reversible recovery
  now work, but this test required explicit continuation.
- Runtime data/case declarations and fresh-update tests need broader KI coverage;
  no 127-model coverage is claimed. The most recent upstream pull rejected 17
  packages and retained the earlier validated snapshot. Portable-path prose
  false positives and large input-inspection limits remain open.
- Legacy plans without explicit commands/output declarations retain their
  previous validation semantics. New-site accuracy, calibration studies and
  compiled release verification remain separate work.

Final independent read-only audit:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v38-gui-archive-completion-audit.json`.
The archive signature and exact preserved bytes passed. Authenticated Flow is
`COMPLETED`; saved and freshly recomputed evidence both pass, with two current
steps passed and zero missing, stale or unreceipted files. The same five run
receipt filenames remain; all signatures are valid and the four pre-archive
raw-receipt hashes captured for comparison are unchanged. All old and new
recorded model-output hashes remain intact, and the old failed receipt remains
failed. Plan and inventory hashes, signed approval issuance/content, runner,
reader and five case inputs are unchanged. All 41 v38 production source hashes
match the frozen checkpoint. No model rerun or receipt rewrite was needed.

### v39: current project status and bounded execution continuation — 2026-10-13

The header now reads the current project's signed preflight projection, rather
than the shared library's installation label. Unknown, missing, failed or stale
project evidence cannot inherit a shared-library pass. Project/session/KI
revision changes invalidate the display cache; ordinary overlapping polls share
one in-flight request so slow responses can still render. The data panel reads
the retained adopted KI and its actual role bindings. File-availability and
receipt labels distinguish technical completion from scientific validation.
Opened external-project model/message summaries survive background pointer-only
list refreshes; unopened external metadata is labelled unknown. Authenticated
planning/acquisition phases take precedence over stale agent progress captions.

After a provider ends a verified, approved execution with steps still missing,
the host may offer one continuation within that same user turn. It rechecks the
current approval, plan/inventory, selected KIs, exact project preflight receipts,
required inputs, stop state, pending human requests and run evidence. The
continuation receives the exact pending steps and signed scope; common API/CLI
dispatch admits only steps that were and still are missing. Passed steps cannot
repeat. A closed same-turn scope rejects delayed commands, while a new explicit
user turn retains ordinary rerun behavior. Provider errors/limits and observed
tool refusals suppress continuation. CLI prelaunch refusals are recorded as a
signed turn-bound blocker, not as invented run evidence. No approval, scientific
threshold or receipt-policy check was weakened.

Independent review passed 78 dedicated cases (32 status, 46 continuation).
The integrated live-source selection passed 151 tests and 2 subtests in 38.21
seconds, without warnings. Additional overlapping UI/status and bootstrap runs
passed 87 and 12 cases respectively; these counts are not additive. Tests include
real harmless preflight and subprocess execution through API/CLI wrappers,
premature provider completion, passed-step denial, stop/question/error/context
changes, slow status polling and genuine signed status receipts.

Integration evidence:
`D:/GeoForge-Setup-Tracer-20261010/v30-integration-aebbaa62571c.json` (18 files).
Independent review:
`D:/GeoForge-Setup-Tracer-20261010/v39-independent-patch-review.json`.
The v39 source server has 42 frozen production files in
`D:/GeoForge-Setup-Tracer-20261010/server-v39-source-hashes.json`.
Three packaging specs include the new continuation module; no compiled release
has been built or published.

The next DSSAT GUI plan uses the same five official inputs, installed runtime,
KDT-adopted runner and reviewed reader, with fresh output base
`outputs/DSSAT/gainesville_replay_20261013_v39`. Independent plan review passed
20 checks and confirmed all 813 protected pre-existing files unchanged. The plan
is awaiting normal GUI approval at this checkpoint; no v39 model run is yet
claimed. Audit: `D:/GeoForge-Setup-Tracer-20261010/dssat-v39-plan-review-audit.json`.

The subsequent real GUI execution passed after one normal plan approval, without
another manual continuation message. The host ran all 21 critical project
preflight checks successfully; DS then completed the native replay and reviewed
reader in its first execution turn. Native receipt
`DSSAT_20261013T200012_536ad0` and reader receipt
`DSSAT_20261013T200022_e6f93a` are authentic, current and passed. The UI now shows
`Project preflight passed` and `Project complete`, and its opened-project sidebar
retains the actual DSSAT/message summary. The fallback continuation mechanism was
covered by the automated API/CLI premature-final tests; this real run did not
need or exercise automatic provider re-entry.

The native output contains 129 continuous daily records. Simulated HWAM is
2,293 kg/ha against the original observed 2,929 kg/ha, an absolute difference of
636 kg/ha and signed PBIAS of -21.71%. This is a technical reference-case replay,
not new-site scientific validation or calibration. One observation pair cannot
support r, NSE or KGE.

Independent read-only audit confirmed authenticated Flow `COMPLETED`, two passed
current steps, no missing steps and no unreceipted files. All 813 protected prior
files, the five original inputs, runtime source data and all 42 frozen host files
are unchanged. Only the two intended run receipts were added; the earlier failed
receipt remains failed and the archived CSV remains preserved. No fresh CSV was
created. Evidence:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v39-real-native-result-audit.json`.

The final presentation check exposed a separate report-card defect: DS supplied
the chart SVG as the path for two JSON report cards because Project View accepted
only files under `artifacts/` and excluded JSON. Native output and receipt checks
still pass, but those cards do not open their named reports. A bounded follow-up
is being prepared to link the original output reports directly, without copying
reports or rerunning the scientific tools.

### v40: direct report links in Project View — 2026-10-13

The bounded follow-up adds original `outputs/**/*.json` links for `file` panels.
Media remains under `artifacts/`. The host rejects traversal, internal project
paths and linked aliases, checks file identity, and records current receipt
association separately from scientific validation. File cards render an explicit
download of their actual path with the original filename, even when the MIME
type could otherwise select an image renderer. API, CLI and English/Chinese GUI
instructions now agree on this contract and prohibit substituting a chart for a
report or copying reports merely to publish a link.

The integrated selection passed 65 tests (including actual HTTP response bytes
and headers, shipped JavaScript rendering, current/stale/tampered receipt
association, path bounds and existing Project View behavior). Independent review
passed the 54 dedicated new cases and checked all six integration file hashes.
Evidence: `D:/GeoForge-Setup-Tracer-20261010/v40-independent-report-links-review.json`.
Integration: `D:/GeoForge-Setup-Tracer-20261010/v30-integration-6abe742fa844.json`.
The restarted v40 source app has 43 frozen production files in
`D:/GeoForge-Setup-Tracer-20261010/server-v40-source-hashes.json`. At this
checkpoint, the existing DSSAT dashboard still awaits its GUI-only correction;
the native v39 run and its evidence remain the execution result under test.

The GUI-only correction then completed through DS in two tool calls:
`read_project_file` and `publish_project_view`. The seven cards now retain the
same descriptive values and unchanged chart, and the two file cards point to the
original v39 output JSON reports. Clicking both cards in the GUI downloaded
`replay_receipt.json` (143,889 bytes) and `hwam_comparison.json` (5,449 bytes)
with their original filenames. Both downloaded SHA-256 values exactly match the
saved model/reader reports. Download evidence:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v40-gui-download-audit.json`.

Final independent audit confirms 1,634 of 1,635 protected project files remained
byte-identical. The sole change was the host re-signing `runs/flow-state.json`
when closing this presentation turn; it remains authentic and `COMPLETED`.
Plans, approval, current evidence, all seven run receipts, native outputs, KIs,
case inputs, all 282 external runtime files and all 43 frozen host files are
unchanged. There are still two passed current execution steps and zero missing
steps or unreceipted files. No native run, preflight or numeric artifact was
added. Both report cards carry the correct current receipt association and
original file hash; neither implies scientific validation. Audit:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v40-view-only-preservation-audit.json`.

GUI screenshots:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v39-project-complete.png`,
`D:/GeoForge-Setup-Tracer-20261010/dssat-v40-gui-results.png`, and
`D:/GeoForge-Setup-Tracer-20261010/dssat-v40-original-report-links.png`.
These source changes are tested locally; this round did not compile, publish or
push a release.

### v41: fresh update and reusable recipe identity — 2026-10-13

A fresh **Check again** in the KI Library GUI fetched main
`889a6e70332e31b21911efb0a08ac2fa2a067e03`. Validation again accepted 110 of
127 model packages and rejected 17, so **nothing was activated**. The active
snapshot remains `e3ed93f067f2f2693294d0ff5d1f98ad`, from source
`8352acb8a7e8d1842356e021a783864917ab1efe`. The two data KIs in the 129-entry
GUI catalogue are bundled fallbacks, not newly updated upstream packages.

The fresh candidate and validation report are retained under
`C:/Users/Administrator/AppData/Roaming/KISS/ki-updates/quarantine/c23b724da3e1`.
The downloaded archive SHA-256 is
`8a373ec514a8ede5d22ae73da31994d9af14219b4f7ffc48a4750cb6ffa26213`.
Independent before/after audit confirms the active pointer, all three recorded
DSSAT/WOFOST projects, their inputs, bindings, outputs and receipts, 578 external
runtime/shared files and all 43 frozen v40 host files are unchanged. Evidence:
`D:/GeoForge-Setup-Tracer-20261010/v41-before-pull-preservation-audit.json`,
`D:/GeoForge-Setup-Tracer-20261010/v41-after-pull-audit.json`, and
`D:/GeoForge-Setup-Tracer-20261010/v41-fresh-pull-rejected.png`.

This pull exposed an app composition defect separate from the package
rejections: the two Windows recipe merge paths use different top-level YAML key
ordering. DSSAT's effective recipe is unchanged, but those byte differences
unnecessarily prevent an exact-source portable repair match. A bounded fix is
under isolated test and independent review at this checkpoint. It must retain
the required `verified: unverified` reset, authenticated source provenance,
strict repair identity checks, and fresh package/runtime verification. It must
not use the previously composed active library as a new source authority.

The fix is now integrated. Composition preserves authenticated raw bytes only
when the full typed document remains unchanged after the readiness reset;
otherwise both merge paths serialize top-level fields in the same order while
preserving nested recipe and command/dependency list order. Actual DSSAT fixture
output matches the prior 1,440-byte recipe exactly (SHA-256
`6be27e50a739d18753595b3e6dd4ee1b44b852c53739f0e06ffe87824b016ada`).
Changed engine, dependencies, required data, source and shared helpers still
require reconciliation rather than reusing an old repair or runtime receipt.

Independent review passed 112 distinct tests. The first integrated run caught
two test imports that assumed an unpackaged tests directory; those were corrected
to package-relative imports, independently checked, and the real integrated suite
then passed **112 tests in 20.39 seconds**, with no skips. Integration manifests:
`D:/GeoForge-Setup-Tracer-20261010/stable-overlay-v41/stable-overlay-v41-manifest.json`
and `stable-overlay-v41-test-imports-manifest.json`. Integration audits:
`D:/GeoForge-Setup-Tracer-20261010/v30-integration-69d6df52d239.json` and
`v30-integration-7ed95777c30f.json`. The restarted v41 app has 44 frozen production
files in `D:/GeoForge-Setup-Tracer-20261010/server-v41-source-hashes.json`.
The post-fix GUI pull and fresh-project native run remain to be tested at this
checkpoint; no successful main-library activation is claimed.

The post-fix GUI pull then completed at the same main commit, still 110 accepted
and 17 rejected, with no activation. Its new quarantine is
`C:/Users/Administrator/AppData/Roaming/KISS/ki-updates/quarantine/fe85aa8d1c59`.
Independent read-only comparison proves the composed DSSAT recipe now matches
the original exact hash above, and the complete DSSAT KI matches the retained
source digest `94baa89ec37244148d6bfe02b91b78688e4fc686ce3c7bb7abb666d395c5d15c`:
no changed, added or removed files. The stale tool inventory is still correctly
rejected. Evidence:
`D:/GeoForge-Setup-Tracer-20261010/v41-dssat-incoming-identity-fe85aa8d1c59.json`
and `v41-post-fix-pull-rejected.png`.

A fresh GUI project, session `ecb160cb3978`, was created after that pull at
`D:/GFTests/2026-10-13-DSSAT-fresh-pull-v41--ecb160cb3978`.
Its initial DS planning request uses the retained validated library plus normal
registered repair reuse. The five unchanged official Gainesville files and the
previously reviewed reader source were uploaded through **+Files**; no old
approvals, outputs or receipts were copied. New setup, plan review, preflight and
native run evidence are required before this fresh project can be called E2E.

Fresh-project materialization reused authenticated portable adaptation
`ef602c46ff7047dfba1dc4f0ca0ae526` automatically. Runner SHA `18304402…d7cb7`
and newly registered project reader SHA `703eda3a…0665` match the reviewed
sources. The per-model configuration correctly points to the installed DSSAT
runtime and the project's own helper copy. **Prepare required data** verified
all 275 declared files with zero acquisition commands; its successful result was
not retained visibly in the setup summary (a presentation gap). The exact-project
preflight then passed. Evidence:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v41-fresh-project-materialization-audit.json`.

The first DS plan exposed a separate host catalogue bug: a free-text source and
inventory label `dssat_runtime_data_tree` were fuzzy-matched to `dssat_data`,
which introduced an unrequested manual bundle download. The reviewed GUI plan
revision specified `existing_local`, exact installed paths and current readiness;
it also added the actual `output_validation: json_report_v1` field that DS had
initially mentioned only in prose. The resulting 11-item, three-step plan passed
17 independent checks. No KI, input, runtime or numerical evidence was edited to
clear either finding. Plan audit:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v41-preexecution-plan-audit.json`.

After one normal approval of that corrected plan, DS completed the native runner
and reader in its first execution turn. Authentic Flow is `COMPLETED`, with two
passing current receipts, no missing steps and no unreceipted artifacts. The
runner used all 12 approved argument tokens, including `--receipt`. Native
`Summary.OUT` and `PlantGro.OUT` were freshly produced, with 129 daily records;
HWAM is again 2,293 versus the unchanged observed 2,929 kg/ha (signed bias
-21.7139%). This is technical end-to-end reproduction of this reference case,
not new-site validation or calibration. One pair cannot support r/NSE/KGE.
The fallback automatic continuation was not used by this live execution.

Independent audit confirmed exact source/staged case bytes, executable identity,
all 275 installed data files, unchanged protected project sources, unchanged
approved step definitions/inventory and all 44 frozen host sources. The generic
host wrapper step is recorded as `kind: check`; the inner native-engine command,
exit and actual model outputs are evidenced separately by the replay report.
Evidence:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v41-fresh-real-native-result-audit.json`.

The remaining WOFOST stage-6 reuse gap is distinct: its repaired parameter
routing is project-local and has no portable adaptation record. A fresh project
receives correct path projection but still the old stage-6 tool. Promoting such
maintenance repairs needs an explicitly scoped reuse record, portable source
reproduction, three reviews and current KDT/runtime checks; it must not silently
replay a materialized project KI or label maintenance as full scientific validation.

The fresh v41 presentation-only turn is also verified. All 314 native/report
files, both signed receipts, 128 protected project files, 275 runtime files and
the executable remain unchanged. The exact plan and approval remain valid and
Flow stays authentic and complete. Seven Project View panels expose the four
metrics, two original JSON reports and a descriptive comparison SVG. The GUI
download of the original native report is byte-identical to its project source
(SHA-256 `e48b643bf05c67662444778cba7085012778c6c7a804d745b16492c5d71af930`).
Evidence: `D:/GeoForge-Setup-Tracer-20261010/dssat-v41-view-only-preservation-audit.json`.
Screenshots: `dssat-v41-gui-results.png`, `dssat-v41-reports-and-figure.png`
and `dssat-v41-comparison-figure.png` in the same evidence directory.

### v42: prevent labels from selecting database downloads — 2026-10-13

The reproduced catalogue bug is fixed in `kiss_cli/obs_access.py`. Arbitrary
inventory/source labels no longer fuzzy-select database acquisition. Explicit
validated dataset IDs, exact/annotated catalogue source selections and exact
legacy item IDs retain their existing behavior. A label such as
`dssat_runtime_data_tree` now stays a label; it does not silently request the
unrelated manual `dssat_data` bundle. This does not certify unresolved inputs,
grant approval, rewrite saved inventories or bypass acquisition/readiness gates.

The five-file candidate received independent review and 123 distinct passing
tests, with one existing POSIX permission test inapplicable on Windows. After
all GUI jobs became idle and preservation checks passed, the owned v41 server
was stopped, only those five reviewed files were integrated, and the integrated
suite passed **123 tests, one skip in 2.85 seconds**. The restarted v42 app has
44 frozen production files. Manifest:
`D:/GeoForge-Setup-Tracer-20261010/explicit-catalogue-binding-v42/explicit-catalogue-binding-v42-manifest.json`.
Integration audit: `v30-integration-a4987e462086.json`; source freeze:
`server-v42-source-hashes.json`. A fresh GUI planning regression remains to be
checked at this checkpoint. The completed native reference run above used v41;
it is not relabeled as a v42 run. No release has been compiled or published.

The first v42 GUI draft (session `247ee55e14cf`) did not satisfy the regression:
DS described a native runner in prose but submitted only host preflight. The
runtime inventory row correctly remained unbound, but was not consumed, so that
draft is **not a pass**. The submitted plan identity captured before validation
matches the saved one-step plan exactly; there is no evidence of the host
dropping a step. A plain follow-up could not overwrite the pending review,
as intended. The GUI **Modify the plan** choice is being used for the correction.
Evidence: `dssat-v42-first-planning-audit.json` and
`dssat-v42-first-plan-submission-audit.json` in the evidence directory.
Returning saved step IDs/counts from `write_plan` would be a separate useful
provider-guidance improvement; it has not been implemented in this checkpoint.

The corrected GUI regression now **passes all 15 independent scoped checks**.
The saved plan contains host preflight and the canonical
`DSSAT:run_gainesville_reference` wrapper, which genuinely consumes
`dssat_runtime_data_tree` with the required free-text source, `resolved` status
and empty paths unchanged. No dataset, delivery, catalogue or acquisition fields
were added; `acquire.needed` is empty. The 12 runner arguments resolve to the
correct paths under `cwd: "."`; all three separate output paths and the actual
receipt inventory `json_report_v1` policy are present. The GUI visibly shows
both steps with no false manual-download card.

This is deliberately a planning regression, not another native run. The new
project remains authentic `WAITING_FOR_USER`, with approval missing and preflight
unverified (`can_run: false`). No acquisition/model receipts or numerical outputs
exist. The completed v41 project's 314 run files, two receipts, 128 protected
files and view remain unchanged, as do the 275 runtime files, prior DSSAT/WOFOST
projects and all 44 v42 frozen host files. Final evidence:
`D:/GeoForge-Setup-Tracer-20261010/dssat-v42-gui-planning-regression-audit.json`;
GUI screenshot: `dssat-v42-two-step-review.png`.

Remaining gaps at this checkpoint: 17 upstream package rejections prevent
latest-main activation; WOFOST's stage-6 maintenance repair is still project-local;
successful Prepare-required-data results are not retained visibly in setup;
and DS still needed correction when its prose exceeded its submitted plan.
No general all-model, all-provider or new-site validation is claimed.

### Explicit post-update E2E check — 2026-10-13, approximately 22:31 China time

The user asked to establish E2E after an actual KI update. A new GUI **Check
again** attempt on the unchanged v42 source fetched main `889a6e70332e` and
freshly checked all 127 packages. It again returned 110 accepted and 17 rejected,
with `activated: false`. Candidate evidence is retained at
`C:/Users/Administrator/AppData/Roaming/KISS/ki-updates/quarantine/b66bd22f3df4/validation-report.json`.
The active library remains source `8352acb8a7e8`, snapshot
`e3ed93f067f2f2693294d0ff5d1f98ad`. The source/archive/composed candidate hashes
match the prior v41 pull; the new pull did not bring corrected upstream packages.

There is currently no supported per-model official replacement route: the
updater activates a complete validated snapshot, ordinary import rejects an
existing catalogue name and requires full authoring verification, and rejected
update maintenance remains draft-only. No alternate route was used to activate
an unaccepted package. Native execution on a newly activated main revision is
therefore still blocked at package acceptance. The successful v41 fresh-project
run remains valid evidence for the retained source plus reviewed repair only.

The failure groups are eight stale tool-index/count packages; VIC's report
contract and WRF-Hydro's report/count; three framework-kind contract mismatches;
and EF5, VELMA, EPIC and Climate_Projection's additional package/evidence issues.
These static results do not establish native model failures. See the current
published-validation handoff for exact package names and corrections.

Evidence prefix `v43-update-attempt-*` denotes this audit attempt, not new app
code. Before-pull audit and rejection screenshot are saved under
`D:/GeoForge-Setup-Tracer-20261010/`. No model rerun, KI edit, approval, compilation,
push or release was performed in this check.

Independent after-pull audit confirmed all 127 verification reports have fresh
timestamps and newly signed results; only the archive cache was reused. Active
state and marker are byte-identical. All five protected project trees/receipts,
578 external runtime/shared files and 44 frozen v42 source files are unchanged.
Incoming DSSAT's complete 51-file KI and Windows recipe match the retained source
exactly; its unchanged stale inventory still causes publication rejection.
Audit: `D:/GeoForge-Setup-Tracer-20261010/v43-update-attempt-after-pull-audit.json`.

### Independent code review — 2026-10-13, approximately 23:15 China time

**Verdict: not yet ready for the intended release.** Three fresh reviewers,
without the implementation conversation, reviewed runtime/setup, execution
evidence, and KDT/publication/Windows packaging. They reviewed the actual dirty
working tree at `1136e56e6bf27b8361d7495a80904c31529afd59`, not just that commit.
Four P1 findings were reproduced in isolated scratch state. No product source,
live project, KI, runtime, GUI/API state or release was changed by this review.
The 223 source/spec files captured before review are byte-identical afterward.

1. **Setup can certify a new path while testing the old embedded path.**
   `kiss/kiss_cli/gui.py:3813` reloads the final saved configuration and reruns
   preflight using an already materialized KI. In the reproduction, the final
   binaries role points to a nonexistent directory, but the immutable preflight
   reads its previous `binaries/ready.txt` literal. Setup returns success and
   reports `can_run: true`, even though projection validation correctly rejects
   the stale runtime provenance. A fresh project independently reprojects and
   fails preflight, so this is false installation readiness and a broken handoff,
   not a demonstrated model-execution bypass. Validate/rebuild the projection
   against the saved configuration before publishing readiness; preserve KDT
   and identity enforcement.

2. **An approved tool step with an unsupported kind can disappear from completion.**
   `ki_tools_common/ki_tools_common/flow/plan.py:1155` does not validate step
   `kind`; `flow/receipts.py:1098` only includes recognized kinds. A two-step plan
   containing a shipped-tool step with `kind: "read"` passes review validation.
   After only the first step runs, evidence omits the second step and
   `flowrun.after()` transitions to `COMPLETED`; the second output never exists.
   Reject unsupported kinds before approval and make completion fail closed
   for every approved tool-bearing step.

3. **Changing recorded input bytes does not make the current completion stale.**
   `flow/receipts.py:1204` compares recorded inputs with other recorded output
   writers, but not the present input file. Rewriting the external input named
   in an approved invocation leaves the authentic receipt tied to the current
   approval and `stale_steps: []`, `validation: passed`, `receipts_verified: true`.
   The fixture demonstrates the host freshness omission, not model behavior.
   Preserve historical execution evidence while marking the current result stale
   when a recorded input changes or disappears, including dependent steps.

4. **The compiled Windows bundle cannot compute WOFOST path-policy identities.**
   `kiss/kiss_cli/ki_fresh_paths.py:25` and `ki_path_contracts.py:40` read their
   module source via `Path(__file__).read_bytes()`. The Windows spec uses PYZ and
   does not ship those Python source files as data. A real isolated PyInstaller
   6.22.2 probe containing byte-identical complete copies of both modules succeeds
   from source and raises `FileNotFoundError` for both functions when frozen.
   Its inert `port.py` fixture is not reached by either failure. This blocks
   WOFOST materialization and affected projection/maintenance verification.
   Use a stable identity mechanism supported by frozen importers or explicitly
   package the required sources, and verify the full Windows build afterward.
   This probe is not a full desktop release build.

The execution reviewer also confirmed an existing compatibility limitation:
legacy plans without declared output contracts can remain verified after a
result CSV is deleted (`flow/declared_outputs.py:76`). This is a known requirements
gap, separate from the modern input-freshness defect. The bounded KDT review
found no additional substantiated P1/P2 publication/adoption defect; this is not
a proof of unrestricted KDT-engine or scientific correctness.

Verification: runtime suites **124 passed**; execution continuation/invocation
suites **101 passed**; publication suite **52 passed**; adaptation/maintenance
suites **84 passed**. The original independent execution reproductions were
**3 passed**, asserting the three observed defects/limitations. A later attempt
to strengthen that scratch fixture stopped with **2 passed, 1 failed** because
the newly written scratch configuration had incorrect encoding. The confirmed
proof JSON files predate that attempt; the current scratch test file contains
that later enhancement. Do not describe it as a clean final rerun. Tests use
isolated state and harmless subprocesses; selected KDT engine/recipe checks are
explicit fixture doubles. No new native model or GUI E2E was run in this review.

Evidence root:
`D:/GeoForge-Setup-Tracer-20261010/independent-review-20261013/`

- `review-source-manifest.json` and `review-source-preservation.json`:
  223 source/spec files checked, zero drift.
- `runtime/binding-repro/result.json` and
  `runtime/binding-repro/project-containment-result.json`.
- `execution/pytest-independent-final/test_unknown_tool_kind_is_appr0/unknown_kind_proof.json`.
- `execution/pytest-independent-final/test_external_consumed_input_c0/changed_input_proof.json`.
- `kdt-release/frozen-probe/frozen-result.json`.

Suggested fix order: reject omitted steps; invalidate current results on input
change; validate final setup projection; make policy identity work in the frozen
build. Close the legacy output-contract gap as well. Then repeat the Windows GUI
acceptance sequence with an actually accepted KI update, fresh project, setup,
approval, DS continuation, native execution and verified outputs. The previously
proven DSSAT/WOFOST runs remain valid within their documented scope. They do not
resolve these host gaps or the 17 package rejections preventing main activation.

### Independent-review corrections — 2026-10-14

The four reproduced host findings and the legacy output-currentness limitation
have fixes in the working tree. Existing project results and KI evidence are
preserved. This checkpoint does not mean that the rejected main library update
has been activated or that every model has been tested.

- Setup now checks that the materialized KI agrees with the final saved runtime
  configuration before reporting readiness. Read-only status also invalidates
  older false-ready records. It does not rewrite an immutable KI to conceal a
  mismatch; an unused installation workspace or restored matching configuration
  remains the supported recovery.
- Plan validation rejects unsupported step kinds, malformed explicit kinds and
  incompatible download/tool combinations. Completion also checks old approved
  plans so that an unsupported tool step cannot disappear from required work.
- Current evidence checks input and output existence and bytes, invalidates
  dependent work and preserves authentic historical receipts. This includes
  legacy output receipts. Status and continuation explain that affected work
  needs rerunning rather than claiming it remains completed.
- Before launch, the shared API/CLI execution path captures consumed inventory
  files and bounded case directories, including default/configuration inputs
  absent from command arguments. Calibration uses the same capture. Signed
  coverage detects changed directory membership. Descriptive managed-runtime
  rows remain descriptive; broad command arguments such as `--project-root .`
  do not authorize scanning arbitrary host files.
- Path-policy identity works with PyInstaller's frozen code loader. Source and
  frozen identities include executable code and constants, while excluding
  deployment-specific debug paths. Missing or unreadable implementation code
  fails closed. Older policy proofs require fresh verification.

Independent rechecking found two additional coverage defects while these fixes
were under development: inventory-only default inputs were not captured, and
an approved output created under a case subdirectory incorrectly made the run
stale. Both were corrected and independently retested: **31 passed**. The wider
execution suite then caught an overly broad bare `inputs` artifact exemption;
the original untracked-file guard is retained. Final suite, build and GUI
acceptance evidence is recorded below as it completes.

Focused runtime/setup suites: **260 passed**. Frozen-identity suites:
**185 passed**, plus a real isolated PyInstaller probe with matching source and
frozen identities. These counts overlap other suites and must not be summed as
unique tests. Fixtures prove host behavior, not scientific model validity.

Audit root: `D:/GeoForge-Setup-Tracer-20261010/fixes-20261014/`.
Independent currentness review: `review-execution/review-result.json`.

Final expanded regression: **462 passed, 5 skipped** in 71.12 seconds. The five
skips require the absent server or `ata-kdt` checkout (desktop/server parity and
real VIC–CaMa coupling data). They are not skipped native DSSAT failures. One
existing NumPy binary-size warning was emitted. Independent bare-input artifact
guard verification additionally passed **10 tests**. See
`execution/execution-final-results.xml`, `execution/execution-fix-report.json`
and `gui-independent/bare-root-results.xml`.

Full Windows packaging, final source v45: the existing
`kiss/GeoForgeDesktopWindows.spec` built successfully with PyInstaller 6.22.2.
All **227** source/spec/metadata hashes matched the freeze before and after the
build and executable smoke check. Distribution: **4,730 files, 458,766,125
bytes** under `fixes-20261014/windows/dist/GeoForge Desktop 0.6.58 Windows`.
The executable's PE version is 0.6.58; its actual `--help` exits successfully.
`--version` is not supported and returns an argument error; it is not counted
as a passing version command. Eight modules extracted from the actual bundled
PYZ match the current source identities, including the final receipt guard.
Main executable SHA-256:
`a4b69bef825c7c2addadc93b20ff48015d08a3346761623e81feab6e7d97b32e`.
Optional netCDF plugin DLL warnings remain untested; this smoke check does not
establish those optional compression backends. No release was uploaded by this
checkpoint. Full build evidence is in `fixes-20261014/windows/`.

Fresh GUI acceptance uses `DSSAT fixes v45`, session `d6a338a357c2`, at
`D:/GFTests/2026-10-14-DSSAT-fixes-v45--d6a338a357c2`, with DeepSeek API
`deepseek-chat`. Five case files were uploaded through the GUI and independently
confirmed byte-identical to the earlier official-case inputs. All live plan,
reader and execution changes go through DS and normal GUI review.

This acceptance exposed planning/reader defects before execution, which must
not be hidden by a final successful run:

1. DS initially declared unchanged uploaded input paths as replay outputs. The
   GUI review returned that plan to DS; the native step now declares only
   `Summary.OUT`, `PlantGro.OUT` and `replay_receipt.json` as its required outputs.
2. The shipped `tools/s9_output_parsing/parse_summary_out.py` has an empty
   `SUMMARY_FILE_PATH` global and no CLI argument handler. An independently
   copied invocation exits 1 even when a Summary path is supplied. DS's initial
   claimed positional interface was incorrect. The KI stays unchanged; an
   explicitly reviewed project-data reader is the scoped workaround, using
   `write_project_data_tool` and a source-hash-bound invocation. A permanent KI
   correction still requires the KDT maintenance workflow.
3. The first project reader got the reference yield right but silently lost
   native dates; a six-digit synthetic numeric value also lost its first digit.
   Independent testing found its column windows were based on heading starts
   instead of native right-aligned field ends. DS was asked to correct the
   parser and re-register its source and plan before approval. This illustrates
   why registration and a passing process are not scientific reader validation.

Evidence: `fixes-20261014/gui-independent/initial-submitted-plan/`,
`reader-invocation/`, `typed-reader-first/`, including the copied native-file
probe and `numeric-window-evidence.json`. These are independent scratch tests;
they did not modify the live project or generate its native results.

The corrected parser needed a consolidated reviewer-guided repair after DS
introduced tuple-unpacking and MZA-table errors. The final registered reader
`55c03d5d862f77e84f5c794ed55897e6400693b37296a44cd9d8d66580c61be0`
is semantically identical to the independently tested scratch candidate:
real reference values and dates, six-digit fields, and refusal of missing/NaN
harvest weights all checked. Source registration remains an approval binding,
not proof of numeric correctness.

First actual GUI execution: exact project preflight passed; DS automatically
continued into execution. Native receipt `DSSAT_20261014T101532_37c9d0` and
comparison receipt `DSSAT_20261014T101539_4f875f` both passed. The native run had
129 PlantGro rows and yielded HWAM **2293 kg/ha** against MZA **2929 kg/ha**:
bias **-636 kg/ha (-21.7139%)**. Native dates were PDAT 1982057, ADAT 1982133,
MDAT 1982185. The host captured all five declared case-input hashes, including
files not supplied as individual command arguments.

The host correctly withheld final completion because DS also used an
unreceipted write to create `artifacts/gainesville_t1_hwam_comparison.csv`.
Both model/reader steps passed, with no stale steps or plan errors, but that
extra numerical file remained unverified. Normal recovery was requested in the
GUI: a reviewed four-step plan using a fresh native folder
`outputs/DSSAT/gainesville_verified`, the unchanged tested reader, and a typed
JSON-to-CSV export whose declared output is the exact extra CSV path. Existing
native results and authentic historical receipts are retained. This is an
explicit review/retry, not an uninterrupted first-attempt success.

The four-step replan exposed another generated-exporter error: DS rewrote it
against JSON field names absent from the actual comparison file. The corrected
47-line exporter was independently tested against that file and a missing-key
case, then registered through the GUI with source SHA-256
`8e5c7b8984ffcdca96b7779bcff387877f01e59ae631ee73405f7baabf259aa1`.
The comparison reader remained byte-identical. DS initially stopped after the
new approval with a proposal to start; a manual continuation message was needed.

Actual native replay and comparison passed again in `gainesville_verified`,
under current approval `798004b3...`. The export attempt
`DSSAT_20261014T102838_c14034` failed: the project-data worker refused to replace
the existing CSV even though that exact destination was now explicitly approved.
The original file was preserved, and the host truthfully kept `export_csv`
missing with `receipts_verified=false`. This was a real app recovery gap, not a
DSSAT model or database failure. The intermediate failure evidence is retained
under `gui-independent/export-containment-failure/`.

The recovery change preserves the existing destination bytes under protected
`.geoforge/output-preimages/`, signs their hashes against the current approval,
step and reviewed source, and links the manifest from the new execution
receipt. Only the exact declared output may be replaced. Consumed inputs,
input-directory descendants, undeclared existing files and linked targets
remain protected. The worker rechecks the old bytes before its first write;
changed or disappeared destinations fail closed. Partial failures retain the
original bytes and the failed receipt without silently restoring or concealing
the attempt. These saved originals are provenance, not validated model outputs.
Contradictory inventory and typed-format output paths are rejected before backup
or launch. Existing source and receipt policy bindings are retained so the
already successful native and reader steps do not need rerunning.

Independent review caught and corrected the disappearing-destination case and
the contradictory-path case before the final source freeze. The earlier v45
Windows build is a historical checkpoint; the recovery change requires its own
v46 build and GUI acceptance, recorded below when complete.

Recovery regression on final v46 source: **135 passed** for worker, typed
outputs and currentness; **148 passed, 11 skipped** for execution, adapters,
continuation, status and calibration integration. The latter skips cover
POSIX shell adapters, process groups and signals on this Windows host.
Independent reviewers passed **20** and **11**
focused checks, including separate negative probes. Counts overlap earlier
suites. Audit: `execution/output-recovery/output-recovery-report.json`.

Actual v46 GUI retry succeeded in one DS turn, with no plan change and no native
or reader rerun. Export receipt `DSSAT_20261014T104535_6d1415` passed under the
same approval `798004b3...`. Host evidence reports all three executable steps
passed, `receipts_verified=true`, no stale steps and no unreceipted artifacts.
The old failed export remains in history as superseded. Preflight is a separate
host check; DS's statement that all four steps have execution receipts is
imprecise. The current native and reader receipts are respectively
`DSSAT_20261014T102830_e431a6` and `DSSAT_20261014T102835_824048`.

The three-row regenerated CSV reports native 2293, observed 2929 and comparison
bias -636.0 kg/ha (-21.7139%). Its original 118-byte content is retained with
SHA-256 `8b403b985576c4ca6f0f22178002fc24345ae2f130ddef2c7b39539a9fad6538`.
The preimage manifest matches the new signed receipt metadata. The independent
audit confirmed all **635** protected files from both earlier attempts remain
unchanged, as do all **3,625** files in the original preservation baseline and
all **227** v46 source-freeze entries. The earlier failed receipt's input hash
describes the old CSV; its mismatch with the regenerated CSV is historical,
and the matching original bytes remain available in the preimage.

The full v46 Windows package built and its actual executable `--help` passed.
Nine PYZ module identities, the standalone worker and bundled shared receipt
source matched the frozen source. Main executable SHA-256:
`52232058c90b1a53c330f1ef56278d2b1d6f2102735b0a9a46ce5fe10a5ce12d`.
The complete runnable package and evidence are retained at
`fixes-20261014/windows/v46-baseline/`.

The final Project status check then exposed a separate presentation/lifecycle
defect: the old "CSV export refused overwrite" question remained pending and
overrode the completed evidence. Dismissing its modal with "Not now" had not
resolved it, and the later successful retry did not retire it. Screenshot:
`fixes-20261014/dssat-v46-stale-question.jpg`. Execution acceptance passed, but
this UI gap needs a bounded lifecycle fix and another frozen build before
calling the status workflow complete.

The question lifecycle correction is a read-only projection: an unchanged
generic question from before a later user turn becomes **earlier unanswered
history** only when that later turn has authenticated completion, a current
approved plan, passing current receipts and current project preflights. It does
not answer, delete or approve any option. Future turns bind the exact question
bytes to a signed host turn record; older projects use conservative file-change
and host-turn timing. Ambiguous timing leaves the request active. Same-turn and
new questions, changed question bytes, permission/download/login/licence and
approval cards remain active. Stale evidence prevents the history projection.
The shared request projection serves both popup and Project status, and a late
callback cannot reinstate the old question over a newer permission request.
English and Chinese status views show the retained question as unanswered
history. No KI, receipt policy or model results were edited for this change.

Independent lifecycle checks passed **42** tests including the renderer and
**25** focused real API/receipt cases in a second review. These counts overlap;
the complete owner regression and final GUI/build acceptance follow below.

Final lifecycle validation covers **345 passed, 10 skipped**, including 26 new
cases and the real GUI `/request` route. The expanded run initially had one
outdated assertion expecting "rewritten" from the earlier currentness message;
only that assertion was updated to the existing diagnostic, and its targeted
rerun passed. Production code stayed frozen. Audit:
`execution/request-lifecycle/request-lifecycle-report.json`.

Actual **v47 GUI reload acceptance passed** in the retained DSSAT project:
the obsolete modal did not reopen; Project status showed **Project complete**,
1/1 project preflights passed and all five stage checkmarks. The old question
appeared separately as **Earlier unanswered question**, explicitly granting no
permission. No DS/model turn was needed for this correction. Its raw request
file stayed byte-identical and still records `status=waiting`; only the current
presentation changed. The same approval and three current successful receipts
remain in force. Screenshots: `dssat-v47-complete.jpg` and
`dssat-v47-question-history.jpg` in the audit root.

Final independent preservation checks: **635** prior-attempt files unchanged;
**3,625** original protected project/runtime/library files unchanged;
**227** v47 source/spec/metadata hashes unchanged. The native-wrapper step is
declared `check` by the KI, so the generic status caption conservatively calls
the phase data preparation. The actual native DSSAT execution is established
separately by its output files and replay receipt; no scientific validation is
inferred from a stage label.

Final **v47 Windows build passed** in 48.33 seconds. The 0.6.58 package contains
4,730 files / 458,801,058 bytes at
`fixes-20261014/windows/dist/GeoForge Desktop 0.6.58 Windows`. The actual
executable `--help` passed; all 12 extracted module identities match source,
and bundled worker, shared receipt code and `app.html` bytes match exactly.
Main executable SHA-256:
`d651084ef887f1ebb0672789220c30819914db7870070e74cfdb0dbed1589971`.
No source hash changed during build, smoke test or GUI acceptance. This turn
did not publish a release or test the entire native packaged GUI; scientific
execution used the source GUI and the packaged executable received CLI/archive
checks. Optional netCDF dependency warnings remain outside this acceptance.

Remaining work is distinct from the desktop fixes accepted here: DS needed
reviewer-guided plan/reader corrections and one continuation nudge before the
successful recovery; the shipped DSSAT reader's CLI contract still needs its
proper KI/KDT correction. No new main-library pull was attempted in this turn.
The retained validated snapshot remains active after the prior 127-package
update rejected 17 candidates, so this is not evidence of a successful latest-
main update or coverage of all 127 models. The single Gainesville observation
supports the reported bias, not correlation, NSE, calibration or model skill.

## 2026-10-14: DSSAT reader full KDT repair and latest-pull recheck

Audit root: `D:/GeoForge-Setup-Tracer-20261010/dssat-kdt-20261014`.
The v47 source GUI remains frozen on port 8795; this work changes a KDT draft
and its adopted portable adaptation, not application source or the old v45 project.

The GUI repair project `DSSAT reader KDT` (`aecd399ba097`) supplied the actual
native Summary.OUT, native OPSUM.for writer, reader contract, baseline probes,
and genuine previously retrieved literature. Three independent DeepSeek
reviews used frozen context `b844a0730a1f1f9fea18059d956ad31abc5a36d256230ab63be855c2380613e2`
in investigation `6e5bf110616c4334`. The full-authoring workflow was used because
the bounded maintenance recipes do not permit scientific reader changes.

DeepSeek authored and refined draft `cfd9ae590d35` through the GUI. Independent
checks caught and returned incorrect precipitation typing, omitted diagnostic
warnings, changed-header geometry, truncated rows, invalid six-digit dates,
input/output aliasing and temporary-file collisions, plus malformed synthetic
fixtures. The final reader has a real `--summary` / `--json-out` CLI, preserves
legacy parsing APIs, uses original-coordinate end-anchored field windows,
validates dates and numeric values, and preserves input/existing output bytes
on rejected operations. Stage-9 guidance and the corresponding diagnostic
records were corrected. Exactly six existing files changed and three top-level
test/fixture files were added; scientific thresholds, native runner, install
recipe and literature records were unchanged.

Final acceptance: **49 independent tests passed**, **102 shipped checks passed**,
and the fixture checksum check passed. Reader SHA-256:
`a59f284a400d8c4b327ee8cb55b38199115d8c827ac336352471e9ec897d2871`.
Native fixture SHA-256:
`f5d8b696b12d3a0cfba4118facb1cfa46194df0f1abebf009e208ae380af96bb`.
Tests executed scratch copies; this is parser evidence, not fresh native E2E.

Actual GUI KDT verification `66c55490558b4720` passed both portable and
project-resolved runtime gates. GUI adoption completed. Portable revision:
`6dc3d11c04909862e1503ac0a1f64bee7556ee280ad2b84e7b355e5566e261ae`;
adopted runtime digest:
`88ae24d8eed8ca29c45f9aacb3343fb7f00ac3b6c764746ea435ad66c1720c38`.
Independent provenance checks confirm the registry selects this reusable
adaptation (`5176a4a3...`) and that adopted bytes equal the tested reader.
The local repair has **not** been published upstream. A reviewable nine-file
patch, baseline and test evidence are in `upstream-handoff-6dc3d11c0490.zip`.

The requested normal GUI latest pull checked main commit
`889a6e70332e31b21911efb0a08ac2fa2a067e03`: **127 checked, 110 accepted,
17 rejected, activation=false**. Quarantine: `fc990307f33d`. DSSAT's incoming
package still has a stale tool index missing `tools/run_reference_case.py`
and a manifest count of 19 versus 20 actual public tools. The current active
snapshot (`e3ed93f...`, source `8352acb...`) was kept unchanged. No gate was
bypassed. Exact DSSAT source, shared-helper and installation-recipe identities
are identical between the latest checked candidate and the retained source,
so the new reader adaptation remains compatible; this is not successful
whole-library activation. Full diagnostics: `latest-pull-validation-report.json`.

Fresh GUI project `DSSAT repaired reader E2E` (`ae539d093d0b`) was created after
that pull attempt. Its signed projection selects the new portable repair;
the reader hash matches, helpers and paths belong to the new project, and all
five uploaded official case inputs match their preserved hashes. Native
execution and current receipts are tracked below when available.

The first fresh native run succeeded, and the repaired KI reader returned
the correct values. Its receipt was nevertheless `warning`: the plan omitted
the structured JSON report contract, so the generic numeric-table validator
rejected the nested JSON envelope. GeoForge correctly withheld completion
and marked the downstream comparison non-current. Receipts
`DSSAT_20261014T130755_bb0c8f`, `DSSAT_20261014T130801_e39c1a`, and
`DSSAT_20261014T130814_ba0edd` and all `fresh_reader` outputs are preserved.
This was a plan declaration error; the reader and desktop validators were
not changed to hide the warning.

DeepSeek revised the plan through the GUI, declaring `json_report_v1` only
for the two ordinary KI JSON reports, leaving native Summary.OUT/PlantGro.OUT
under scientific validation and retaining typed validation for the comparison
tool. All three commands and six output bindings moved to the previously
absent `outputs/DSSAT/fresh_reader_verified`. Independent review confirmed
the five inputs, three tool identities, exact typed-tool arguments and new
paths before normal GUI approval. The comparator had separately passed nine
independent probes, including the actual MZA treatment-1 observation and
rejection of wrong, fractional and non-finite treatment/observation values.

The GUI rerun completed with three **passing** receipts:

| Step | Receipt | Result |
| --- | --- | --- |
| Native DSSAT replay | `DSSAT_20261014T131416_a7f0c2` | exit 0; 129 daily PlantGro rows |
| Actual repaired KI reader | `DSSAT_20261014T131422_a27934` | 1 record, 99 columns, no warnings |
| Observed/simulated comparison | `DSSAT_20261014T131426_247f9a` | JSON and CSV produced |

Actual native values: HWAM **2293 kg/ha**, CWAM **6556 kg/ha**, PRCP
**660.7 mm**. The supplied treatment-1 observation is **2929 kg/ha**;
bias is **-636 kg/ha (-21.71%)**. One yield pair does not support r/NSE/KGE
or a calibration/skill claim. This is the unchanged Gainesville reference
case, not a new-site or live-database test.

The GUI Project status now shows **Project complete**, **1/1 project
preflights passed**, all five stages checked and all six new output entries
marked **Produced (tool receipt)**. Screenshot:
`dssat-repaired-e2e-complete.jpg` in the audit root. The phase caption still
conservatively says data preparation because the KI declares its native
runner as `kind: check`; native execution is independently evidenced by the
receipt and native output bytes. The five uploaded inputs are displayed as
present rather than scientifically verified; their staged identities and
selected-case checks are recorded by the actual native replay.

The repair is locally adopted through KDT and demonstrably reused in a fresh
project after a normal update check. The entire latest library was **not**
activated: its 17 upstream package failures remain. Relevant DSSAT/helper/
recipe bytes match the latest checked candidate. The reader repair has not
been pushed upstream or included in a new release by this turn.

Final independent audit (`final-e2e-strict-audit.json`) confirms authenticated
flow state `COMPLETED`, valid approval/signatures, three passing current
receipts with exact invocation/input bindings, and no missing/stale steps,
invalid outputs or unreceipted artifacts. Earlier warning outputs remain
historical evidence and do not satisfy the new steps. Preservation report
`comparison-final-e2e-completed.json` confirms 6,242 of 6,243 protected files
unchanged; the one intended replacement is the selected adaptation registry.
The new portable source and project projections are recorded additions.
All 227 frozen application-source identities remain unchanged.
The final independent summary (`final-e2e-summary.json`) also confirms all
316 files in the initial attempt and its three receipt files are unchanged,
the verified result figure matches the actual pair, and no pending request
remains. Exact host semantics are `completion_scope=data_preparation` and
`science_complete=false`; technical/native-run success is not scientific
validation of model skill.

## 2026-10-14: desktop enforcement gaps and compiled Windows acceptance

Audit root: `D:/GeoForge-Setup-Tracer-20261010/gaps-v48-20261014`.
This round changes application enforcement, then tests the previously
KDT-adopted DSSAT reader in a fresh project. The reader itself was not edited
again. Existing receipt authentication and declared-output validators were
preserved byte-for-byte; new review checks do not invalidate historical runs.

Closed application gaps:

| Gap | Change and verification |
| --- | --- |
| Auto KI intake could inspect upstream text instead of the compatible approved repair | Host catalogue, API reads and CLI read roots now resolve the signed, KDT-approved effective source before selection. Lookup does not grant execution readiness or expose the adaptation registry parent. 202 targeted tests plus independent negative checks passed. A fresh Auto KI DeepSeek GUI chat read portable DSSAT revision `6dc3d11c0490...` and its real runner/reader CLI. |
| Plans could omit the JSON report contract | New plan reviews and approval clicks reject ambiguous/conflicting output contracts. Structured reports require `json_report_v1`; genuine numeric scientific JSON retains numeric validation. Typed project-tool outputs retain their own contract. 26 new planning tests and 20 independent negative cases passed. |
| A plan could call nonexistent paths ready, or put arguments where a typed executor ignores them | Review verifies every consumed ready path, distinguishes earlier producers, and rejects ignored top-level `command`/`cwd` on typed steps. Guidance distinguishes per-KI runtime bindings from neutral workspace defaults. 42 focused path/invocation tests passed with adjacent review/calibration coverage. |
| Frozen application preflight could falsely go stale | Packaging now includes the unchanged loose `runtime_data.py` source required by its own identity check. Three packaging specs and their tests were updated; actual Windows bundle parity passed. macOS runtime behavior was not exercised. |
| Generic completion labels overstated scientific progress | Status and EN/ZH UI now say **Approved execution completed** for authenticated execution completion, while leaving independent scientific validation unestablished. No inference of native execution is made from `kind: check`, filenames or agent claims. Native execution is audited separately. |
| A delayed approval response could render in another chat | The frontend rechecks the selected session and busy state after the asynchronous response. Eight actual shipped-JavaScript race cases passed; the combined UI suite passed 45 tests. |

These test counts describe different focused suites and must not be added
as though all were disjoint. Full commands/results are retained in the audit
directory. Production source was frozen before each packaging acceptance.

The final v51 Windows package was launched as the desktop server on port8796.
Executable SHA-256:
`618313e7dd4a6d182de8b88aaeb9d79d7bbd185cb2a10d7bb6f6425628cef602`.
All228 frozen source files matched after build, all21 inspected PYZ modules
matched, and seven loose source copies matched. This acceptance used the
compiled executable's GUI through the browser, not the source Python server;
the native desktop webview/window lifecycle was not tested.

Fresh project `DSSAT packaged explicit KI` (`600f01eebb4d`) used five unchanged
official Gainesville UFGA8201 files, the existing installed native runtime,
and the approved portable reader. DS needed several reviewer-guided planning
corrections before execution: literal runtime paths, native runner arguments,
reader output parent, typed argument placement, treatment-aware MZA parsing,
strict comparison identity/units and real CSV formatting. The final project
helpers passed 37 scratch checks. Reviewed helper identities were
`19d99232cad19685b5025b861f49cdcbe8310e6f4731e3539d36e82f0ad47ba0`
(MZA reader) and
`7fc1287dc14670c3125374903ba149c232d5a03ac06ef1f7b4e3d9db1d41fda8`
(comparison). They were submitted through the GUI's project-tool interface;
no unapproved KI edit or validator waiver was used.

Two uploaded proposal JSON files were explicitly declared as ready reference
attachments, preserving their provenance without treating them as observations
or scientific results. Independent review confirmed the final plan and
16-item inventory exactly matched the reviewed proposal before normal GUI
approval. Native output paths were absent before execution.

After approval, DS passed the exact project preflight and **continued without
another prompt** through the four real executions and the host plot tool:

| Step | Fresh receipt | Result |
| --- | --- | --- |
| Native Gainesville replay | `DSSAT_20261014T162251_669942` | Passed; actual pinned binary, unchanged staged inputs, 129 PlantGro daily records |
| Repaired KI Summary.OUT reader | `DSSAT_20261014T162258_1bf6c0` | Passed; one record, 99 columns, no reader warnings |
| Project MZA observation reader | `DSSAT_20261014T162302_e96e2a` | Passed; actual treatment-1 observation |
| Project comparison | `DSSAT_20261014T162305_1e1dfd` | Passed; consumes the actual reader and observation JSON, consistent JSON/CSV |

The strict independent audit found a valid signed approval and four current
passing receipts, Flow `COMPLETED`, no missing/stale steps, no invalid outputs,
no unreceipted artifacts and no pending request. Exact status semantics are
`completion_scope=approved_execution`, `execution_complete=true`, and
`science_complete=false`. Evidence:
`acceptance/v51-fresh-e2e-audit.json`.

Actual HWAM is **2293kg/ha**, observed **2929kg/ha**, bias **-636kg/ha
(-21.7139%)**. The SVG was generated from the fresh comparison CSV; the
independent presentation check verified its labels and bar ratio. This is
technical end-to-end execution of a fixed reference case, not a new-site,
live-database, calibration or model-skill test. One observation cannot support
r, NSE or KGE. DS's final prose contains a contradictory phrase "not
end-to-end"; it does not alter the independently verified execution scope.
Screenshots: `windows-v51/dssat-fresh-complete.png` and
`windows-v51/dssat-fresh-figure.png`.

Preservation:1,277 of1,278 protected old-project files remained byte-identical,
with no additions. The sole change was the previously documented automatic
`calibration/framework.json` availability/dependency metadata refresh; old
native results and receipts were unchanged. See
`independent/final-v51-preservation-source-audit.json`.

Remaining limits at this checkpoint: the latest normal pull still rejects17
upstream packages and retains the last validated library; the KDT reader repair
is locally adopted but not yet published upstream. DS's repeated plan repairs
mean autonomous planning quality is not proven. A live Claude Code intake
attempt stopped before reading because its saved OAuth session expired.
A live Codex intake attempt exposed a separate duplicate `--sandbox` launch
argument; the following checkpoint records that fix and its acceptance.
No public release or push occurred in this checkpoint.

### v52: Codex launch composition and final package

The live Codex check exposed two launcher errors: the base policy and flow
policy both supplied `--sandbox`, and resumed turns placed exec-level
`--sandbox`/`--add-dir` options after the `resume` subcommand. The installed
Codex0.148.0 parser rejected those commands before any KI read. The minimal
fix in `kiss/kiss_cli/providers.py` gives the flow policy one sandbox selector
and places exec-level options before `resume`. It retains existing network
configuration, directory identities and sandbox modes, including planning's
absence of additional writable roots. No CLI authentication or user config
was changed.

All88 focused regression checks passed and were independently repeated;
these include six real installed-CLI parser probes for fresh/resumed intake,
planning and execution. The adjacent suite had451 passing tests plus42 passing
subtests and **two existing fixture failures**. Both reproduced with preserved
pre-fix provider code: one supplies a nonserializable `SimpleNamespace`
manifest, and the other supplies a noncanonical Windows temp-path spelling to
the exact-path gate. A reviewer normalized only the latter fixture in memory
and it passed. These failures are retained and disclosed, not waived or
represented as a fully green broad suite. Evidence:
`codex-cli-argv/fix-summary.json` and
`independent/codex-flow-independent-review.json`.

v52's only production-source difference from v51 is `providers.py`. All228
frozen source files remained unchanged during build;22 extracted modules
(including the launcher), seven loose sources and three expected CLI smoke
results matched. Executable:
`windows-v52/dist/GeoForge Desktop 0.6.58 Windows/GeoForge Desktop.exe`.
SHA-256:
`8a89399d274a424c9cc4a43786870cc3ecc5ec5a876257bdb38475556a5fdac9`.
Root launched this actual package on8796, PID75092. v51 and earlier servers
were stopped only after their agent turns were idle.

The completed DSSAT project was reopened under v52 and independently
reverified without rerunning the model. The same signed approval, four run
IDs and all331 tracked files (including four receipt files and317 output
files) were unchanged. The live packaged status endpoint reports
`COMPLETED`, verified preflight, execution complete, scientific validation
unestablished and no errors. Evidence:
`acceptance/v52-reopened-e2e-audit.json` and
`acceptance/v52-reopened-preservation.json`.

Live Codex coverage remains **blocked, not passed**. The new launcher gets
beyond the previous parser errors, but a CLI-default attempt was rejected
because configured `gpt-6-astra` requires a newer CLI. A separate GUI chat
selecting `gpt-5.5` was rejected because the inherited reasoning effort `max`
is unsupported for that model (supported values end at `xhigh`). Neither
attempt read a KI, and no successful live resumed turn is claimed. The GUI
offers no per-chat effort selector. The saved attempt snapshots are
`windows-v52/codex-default-model-attempt-ui.txt` and
`windows-v52/codex-explicit-model-attempt-ui.txt`. Claude remains separately
blocked by its expired OAuth session. Fresh/resumed parser acceptance is
established by tests; full CLI-provider runtime acceptance is still open.

The local compiled DS/DSSAT reference workflow is accepted. Remaining work is
upstream KI publication/update failures, DS planning quality, provider
configuration/compatibility guidance and broader model/platform coverage.
This is a local test build; no Windows release or source push was performed.
