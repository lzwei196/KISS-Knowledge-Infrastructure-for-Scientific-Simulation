# GeoForge Desktop 0.6.55 Windows release verification

This release continues the Windows desktop testing requested after the Claude Code session **Geoforge desktop app test**. It includes the October 1 model and workflow repairs, an offline Usage menu, English and Chinese guides, and calibration approval and packaging fixes.

## Final source regression

The completed application source was held unchanged during both suites on Windows with Python 3.11, UTF-8 mode **off**, and the actual **cp936** default encoding. Only terminal output encoding was set to UTF-8. Each suite used an isolated Flow registry.

| Suite | Passed | Skipped | Additional subtests |
|---|---:|---:|---:|
| Desktop (`kiss/tests`) | 1,727 | 35 | 337 passed |
| Shared library, Flow, units and climate scenarios | 371 | 7 | — |

All **363 Python source/test file hashes** were identical before and after the suites. Desktop duration was 364.98 seconds. The shared suite emitted six existing warnings; the skipped tests include platform-specific cases. Focused test counts elsewhere overlap these suites and must not be added to the totals.

The shared command covered `ki_tools_common/ki_tools_common/tests`, `ki_tools_common/tests/flow`, `ki_tools_common/tests/test_units.py` and `ki_tools_common/tests/test_climate_scenarios.py` in a separate interpreter. Inline application JavaScript and `i18n.js` also passed Node's syntax check.

Local evidence is under `D:/GeoForge-Release-20261002/source-tests/`, including both logs, JUnit XML, summaries and the before/after source hashes.

## Application and documentation acceptance

The source-frozen acceptance executable passed the self-contained Windows smoke check: **127 scientific KIs**, **127 Windows installation notes**, **23 Windows recipes**, bundled Python, agent bridge without Python on PATH, Unicode bridge IPC, harness/Flow and calibration dependency readiness, and 11 application HTTP routes.

All **12 offline guide routes** returned the exact bundled HTML/PDF bytes with the correct content types: quickstart, manual and calibration, each in English and Chinese. Both frozen Usage menus were inspected in the actual browser frontend; guide links opened correctly. Each quickstart is exactly **three pages**: agent setup, KI/model setup and an official SHAW forward run. All six final PDFs are rendered and visually checked during manual production.

Final release-payload, installer installation/removal and publication evidence will be recorded below before the release is published.

## Scientific test scope

- [CRHM, VIC and SHAW official-example report](WINDOWS_E2E_CRHM_VIC_SHAW_2026-10-01.md): real native Desktop runs reached Completed with verified, signed receipts. These October 1 checks used DeepSeek, with documented assistance for installation. Their fixes are included in 0.6.55; this report does not relabel those historical runs as fresh 0.6.55 runs.
- [Calibration verification](WINDOWS_CALIBRATION_2026-10-02.md): genuine SHAW publisher-reference recovery, six synthetic optimizer backends, approval binding, immutable run evidence and Windows packaging checks. A requested 60-evaluation DDS experiment makes 64 native calls including probe, holdout and baseline work. Reference recovery is not validation against field observations.
- Calibration now binds the exact adapter/contract bytes and resolved settings before approval. API and CLI use the same guarded run path. Planning may author only the selected KI's two adapter files through a bounded operation. Missing/rejected holdout validation prevents scientific completion even when the optimizer finishes.

## Remaining limits

No authenticated GeoForge Database transfer or all-model scientific acceptance is claimed. The previously documented detached Git Bash process-supervision and general CLI setup-command-enforcement limits remain. Shared Flow changes are recorded in `ki_tools_common/ki_tools_common/flow/UPSTREAM.json` for reconciliation before a future upstream sync. See the [known-issues record](issues/WINDOWS-KNOWN-ISSUES-2026-09-30.md) for other inherited limits.

Only Windows release assets are updated. Earlier public Windows 0.6.54 assets and macOS/Linux releases are preserved.
