# macOS installation status — 2026-09-10

This update consolidates the current Mac installation work. It does not claim that every KI installs successfully or that every KI has a dedicated Mac recipe.

- 127 KIs covered; 246 DeepSeek installation attempts including retries.
- 114 latest installed, 3 failed, 10 needs-user.
- 80 KIs have dedicated Mac manifests; 47 do not. Shared manifests and agent-assisted installation account for some other successful installs.
- Six installed results are the explicitly declared Python variants of HEC_HMS, KINEROS2, LPJ_GUESS, QUINCY, VELMA and WASP. Their exact runner identities, hashes, dependency imports and clean help startup are checked. These results do not verify official upstream installations or scientific equivalence.

## Remaining failures

| KI | Unresolved issue |
|---|---|
| COAWST | Coupled ROMS + SWAN + MCT build/startup remains unverified. WRF is optional; WRF and WW3 are not both mandatory. A later upstream missing-input patch is only staged locally, uncompiled, and is not included here. |
| ROMS | Native executable crashed with SIGSEGV. Preflight now rejects signal crashes; the native crash remains unresolved. |
| DualSPHysics | Required GenCase is a Linux executable in the tested package; a native solver alone does not satisfy this KI. |

Needs-user records: APEX, CE_QUAL_W2, DLBreach, DNDC, DayCent, Delft3D, EPIC, HEC_RAS, OpenFOAM, RZWQM2. Reasons include source access, release matching and platform availability; this status does not automatically imply the user must perform an action.

## Validation and limits

Engine suite: 316 passed, 1 skipped, 121 subtests passed. COAWST preflight: 11 additional mocked checks. Six fresh declared-variant DS retries passed. The Apple Silicon app was rebuilt, ad-hoc signed, strictly verified and launched with all 127 catalogue entries. These are installation checks, not scientific validation.

Historical evidence has known scope/proof limits: Pywr's earlier installer log reports a timestep; pyBadlands reports model construction. CWatM and Climate_Projection have unresolved verification-depth gaps. Recorded totals retain those historical outcomes and must not be read as uniformly complete independent scientific-engine attestations.

Some native recipes require separately provisioned build dependencies and model-specific configuration described in their installation documents. `verified` labels describe the recorded recipe evidence, not universal portability to every Mac.

The scheduled test task is paused. Raw run logs, credentials, machine environments and compiled artifacts are not committed. See [per-KI manifest coverage](mac-manifest-coverage.md) for the current recipe inventory.
