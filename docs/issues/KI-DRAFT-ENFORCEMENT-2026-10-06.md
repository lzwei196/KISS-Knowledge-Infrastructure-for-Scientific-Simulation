# Shared KI draft enforcement — 2026-10-06

GeoForge owns the acceptance policy for every CLI and direct API provider:
draft edits do not acquire authority from the provider's final response.

## Implemented boundary

- KI Studio, ZIP import and changed/new library KIs use the actual installed KDT
  structural verifier and the Desktop package checker. Candidate preflight code
  is statically checked; structural verification runs only a host-generated
  deferred preflight, never the candidate's untrusted native model commands.
- Host signatures bind the full candidate content, gate policy and actual KDT
  verifier source. Acceptance records live outside authoring workspaces. A changed
  file, forged report or altered verifier cannot retain acceptance.
- Activation checks the copied candidate again. Studio exports the exact verified
  projection. Missing or modified KDT installations produce an actionable refusal;
  the current active library remains available.
- Active source and working KI baselines are stored by the host. A single signed
  host inventory records existing installed versions as legacy baselines, not
  newly KDT-verified or scientifically verified versions. A new `--models` folder
  cannot restart migration: its contents need exact recorded legacy provenance
  or current KDT acceptance. Ordinary setup writes cannot edit an active KI.
- The shared CLI runner, direct API tools, native tool dispatcher and software
  preflight check active KI integrity. Changed files cannot be counted as current
  software-ready evidence. Installation metadata stays beside the KI rather than
  rewriting its contents on every status update.
- Library readiness rechecks canonical and installed KI integrity. Old successful
  reports without exact revision evidence remain history and request a recheck;
  status reads never enroll files or modify those reports. Installation-recipe
  agents use the same protected roots for both CLI and API providers.

## What the gate proves

`Verified` here means the exact package passed structural checks. Native software
verification and reference-case/scientific acceptance remain separate evidence.
Reports explicitly record native regression as not run by the structural gate.
No SHAW, CRHM or VIC scientific result is changed or newly certified by this work.

This is a host integrity and acceptance boundary. Vendor CLI processes running
with the user's operating-system permissions are not an OS sandbox. File drift
is detected and blocked; arbitrary same-user filesystem writes cannot honestly
be described as impossible. Preservation does not imply that an unknown
background child process has stopped.

The optional three-reviewer investigation, one combined repair report and
project-specific Apply-and-resume UI remain a separate workflow layer. This
change establishes the shared gate those operations must use. It does not add
automatic project migration or relax approved scientific criteria.

## Validation

The focused suites exercise authentic host hashing/signatures with controlled
KDT test engines, failed/missing gates, post-check changes, forged reports,
Windows preflight handling, every configured CLI provider and setup/API paths.
Those controlled engines are test doubles; they do not prove that a scientific
model or a live provider has run.

GUI checks used the real reviewed KDT engine at commit
`631e5c50cb0cd812447f67358dd9c162658155ea`:

- The existing SWAT+ Studio candidate passed KDT and Desktop structure checks.
  Report `fe141a5f6d4b4cc2` enabled Import for that exact revision. No import or
  native SWAT+ run was performed.
- Reopening the candidate for editing invalidated its previous report and
  disabled Import. The stale state survived a GeoForge restart; another real
  verification was required to enable Import again.
- A validate-only ZIP of the shipped HYDAT data KI was refused for three KDT
  format requirements: the opening execution policy, at least three stage
  documents and `diagnostics/triplets.yaml`. The library stayed at 129 entries.
  This is a package-format gap for a future import/update, not evidence that the
  existing HYDAT reader or database fails. Legacy baselines remain available.
- The previously modified KDT checkout was replaced through Studio's Repair
  control, with the old checkout preserved in a `.replaced-*` directory.
- The final build restarted with all 129 catalogue entries. The CRHM Library view
  retained the successful check from 15:27 and displayed `Recheck KI revision`,
  with its original preflight steps still visible. The SWAT+ structural report
  remained current after restart. No scientific model was rerun for these checks.

Final full Desktop regression (`python -m pytest kiss/tests -q`) passed:
**2,341 passed, 35 skipped, 352 subtests passed**, exit code 0, in 472.63 seconds.
The skips cover platform-specific fixtures and unavailable server-copy parity;
they are not claimed as tested. All 339 fingerprinted Desktop source, test and
shared-helper files were unchanged during the run. `git diff --check` passed.

Local evidence is retained in `D:/GeoForge-Release-Checks-20261006/`:
`ki-gate-final-desktop.log`, `ki-gate-final-desktop.xml` and
`ki-gate-final-source-stability.json`. This is a tested source change, not a new
Windows installer release.
