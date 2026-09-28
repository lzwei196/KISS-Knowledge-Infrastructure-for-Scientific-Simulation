# Catalogue-backed Desktop planner: live acceptance checkpoint

Date: 2026-09-28. Branch: `mac-version`, base HEAD `bdf2522e` with the existing local planner changes. This is a source-app test, not a rebuilt-app or release qualification.

## Scope and authorization

The user explicitly authorized sending cached dataset metadata (names, variables and coverage) to Kimi. An isolated Desktop source server used the real session/chat/provider/Flow handlers, a public APEX KI, and a synthetic single-point Harbin maize scenario at 45.75 N, 126.65 E for 2003–2005.

The test copied a whitelist of 1,106 catalogue records into an isolated app cache; the production snapshot path produced the project copy. Credential fields and URLs were excluded. Existing projects, personal skills, API keys, DB credentials and actual datasets were not copied. Normal Kimi login was used. The DB client was deliberately unavailable so no Keychain lookup or authenticated server call could occur. Approval, acquisition, installation, preflight and model execution were forbidden.

This test can establish catalogue discovery and question/answer behavior. It cannot establish live authorization, native source schema, subset readiness or successful delivery. Missing live estimates are expected in this fixture, not evidence that the remote subset service is broken.

## Observations

The actual Desktop catalogue endpoint returned cached results quickly:

| Query, constrained to the test area and period | Returned | Elapsed |
|---|---|---:|
| CMFD | 5 records | 0.015 s |
| HWSD | 5 records | 0.011 s |
| soil | 180 matches, first 20 returned | 0.012 s |

These were controller sanity queries, not claimed as Kimi tool invocations. Kimi's snapshot reads were separately captured. Unknown-bbox records remain candidates rather than being proven to cover Harbin; query success is not a relevance or suitability certificate.

| Interview turn | Observed decision | Time to question |
|---|---|---:|
| 1 | Forcing: exact `cmfd_china_3hr_010`, `cmfd_china_daily_010`, or user files | 94.352 s |
| 2 | Soil: HWSD China, Global, raster-only, or user files; explained raster/attribute-table dependency | 100.202 s |
| 3 | CO2: recognized a scalar parameter decision, not a dataset download | 67.690 s |

All three turns finished naturally. The controller answered using explicit custom-answer actions tied to each issued request ID. It selected `cmfd_china_3hr_010` and then `hwsd_global` as proposed sources, not as approval of the whole-product download. It kept actual schema, coverage, companion-file contents and project clip estimates unresolved. It supplied 375 ppm only as a synthetic test input, not as a verified observational value.

The bounded run ended after 481.13 seconds at its eight-minute overall test limit. Turn four had run for 83.773 seconds and was actively inspecting management/GGCMI/NPK requirements; it had not reached the per-turn timeout. No live DB client was invoked, so missing credentials did not cause this stop. Three custom answers were recorded; a later reply explicitly retained `cmfd_china_3hr_010` and `hwsd_global`. Host and four planning-worktree copies of the two draft files remained byte-identical, with no `Write` observations. Final plan consistency is therefore unverified, not passed. The requested continuation was subsequently cancelled when the user asked for a build; no continuation ran and all isolated test processes were stopped.

## What remains wrong or unproven

1. **Delivery wording is still misleading.** The snapshot contains whole-product `manual` delivery and large catalogue sizes but no subset-capability metadata for these sources. Kimi emphasizes roughly 649 GB for CMFD and 1.87 GB for HWSD. Those are not a project download estimate. A planner must distinguish parent-product metadata from an available, pending or unsupported project clip; it must not infer that no clip service exists from this snapshot.
2. **Recommendations still exceed their evidence.** The soil recommendation expects a package to contain both required files while explicitly acknowledging those contents are unverified. The CO2 question calls 375 ppm “scientifically correct” while its cited external reference was not checked in this test. This is not proof the value is wrong, but the evidence does not justify that wording or certify a project default.
3. **Latency remains substantial.** Cached lookup is milliseconds, while questions take roughly one to two minutes. Improving the cache alone does not solve model reading/reasoning/response latency. This test does not establish a statistically controlled speed benchmark.
4. **The completed plan remains a separate acceptance condition.** Remembering choices in chat does not prove that final `plan.json` and `data-inventory.json` use the same selections, paths and period. Do not mark final approval/download behavior passed from intermediate question cards.

## Independent source-binding reproduction

A separate synthetic regression exercises real `FlowSession.write_plan → flowrun.after → plan_review.issue → plan_review.respond`. Its inventory selects source A while its scientific data choice selects source B. Both records are synthetic; there is no network or model execution.

| Path | Outcome |
|---|---|
| Finalization | Validator returns no errors; review shows B selected while the acquisition row/inventory still identifies A. |
| Current browser-shaped approval, submitting radio B | Host re-pins to B and requires an unsigned re-review; the second approval is consistent. |
| Direct response handler, valid approve action but no `choices` map | Host signs an approval containing contradictory item A / choice B decisions. |

This demonstrates a contradictory initial review and an incomplete-payload approval gap. It does **not** demonstrate an ordinary current-browser wrong download: the current browser sends radio values and its tested path corrects the mismatch. Nothing was downloaded by the reproduction. Consistency should be enforced before both issuing the review and signing approval, rather than relying on the browser to repair a contradictory draft.

Reproduction command already run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 /private/tmp/geoforge-source-binding-audit.XMcc4W/reproduce.py
```

## Evidence and limitations

Live evidence: `/private/tmp/geoforge-kimi-catalogue.ycvo1y/` contains sanitized catalogue/filter metadata, actual catalogue endpoint results, issued question records, explicit test answers and timestamped provider activity. This directory is local temporary evidence, not a published artifact.

The test used app HTTP handlers, not browser clicks. No changes to production code were made during the live test. No claim is made about other providers, other KIs, a complete approved plan, authenticated describe/estimate, download or simulation.
