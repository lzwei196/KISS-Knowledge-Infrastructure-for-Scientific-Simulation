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

The final public executable passed the same frozen smoke check. A source-payload audit compared **15 changed compiled modules** and **443 bundled files** with the committed source; all matched. Its SHA-256 is `6a45b3d9c9b4dc0098210cbd3b3a027f7688df1b32d43b019666e0033a3f04ba`.

The actual installer was then run silently into the new isolated directory `D:/GeoForge-Release-20261002/installed-acceptance`. Installation exited 0, the installed executable had that exact SHA-256, and the installed application passed the complete smoke check including all 12 guide routes. Uninstallation exited 0 and removed the application executable. Existing user settings and installations were not replaced.

| Release asset | Bytes | SHA-256 |
|---|---:|---|
| `GeoForge-Desktop-Setup-v0.6.55-Windows-x64.exe` | 153,866,680 | `3f4d9ea6763dcf5b5cc0966235ab3a181cf0095af4248fa1b297f0f8dd608335` |
| `GeoForge-Desktop-v0.6.55-Windows-x64.zip` | 222,609,385 | `d1638ee9243992093efaedf12be2ec7783c69af3551b7070757686ac59561691` |

The portable archive passed a full ZIP integrity check; its executable matches the tested bundle. All six release PDFs byte-match their bundled counterparts. The final PDF lengths are 153/151 pages for the English/Chinese full manuals, 3/3 for the quickstarts, and 10/9 for the calibration guides. PDF and offline-asset hashes are recorded in `docs/manual/0.6.55/validation.json`.

Release target: [`windows-v0.6.55`](https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/windows-v0.6.55). `Windows-release-validation.json` records the exact tagged commit, installer results, scientific scope and artifact hashes. `SHA256SUMS-Windows.txt` covers every other uploaded asset. The manifest pins application code and guides to `3bf10f2e1de0720a5c5c5b2c46825f9051606579`; subsequent commits contain release metadata and audit-report updates only.

## Scientific test scope

- [CRHM, VIC and SHAW official-example report](WINDOWS_E2E_CRHM_VIC_SHAW_2026-10-01.md): real native Desktop runs reached Completed with verified, signed receipts. These October 1 checks used DeepSeek, with documented assistance for installation. Their fixes are included in 0.6.55; this report does not relabel those historical runs as fresh 0.6.55 runs.
- [Calibration verification](WINDOWS_CALIBRATION_2026-10-02.md): genuine SHAW publisher-reference recovery, six synthetic optimizer backends, approval binding, immutable run evidence and Windows packaging checks. A requested 60-evaluation DDS experiment makes 64 native calls including probe, holdout and baseline work. Reference recovery is not validation against field observations.
- Calibration now binds the exact adapter/contract bytes and resolved settings before approval. API and CLI use the same guarded run path. Planning may author only the selected KI's two adapter files through a bounded operation. Missing/rejected holdout validation prevents scientific completion even when the optimizer finishes.

The actual frozen DeepSeek session `77693a6010fc` used the normal adapter-authoring tool, typed plan submission and browser approval. It reached **Completed**, with cryptographic approval, all three receipt signatures and every recorded input/output hash independently verified. The fitted plot followed one failed unsupported-argument attempt; that superseded failure remains recorded. An independent 24-check audit passed. The final public executable separately repeated the same native DDS experiment: 60 optimizer evaluations, 64 successful native calls, zero console window handles, and identical fitted parameters and metrics. No additional provider turn was required for this final executable check.

Two inaccuracies in the provider's final prose are explicitly corrected in the calibration report: holdout and training RMSE are nearly equal, and the generated profile PNG shows fitted native results without a reference overlay. The verified scientific files, metrics and host completion state are the acceptance evidence.

## Remaining limits

No authenticated GeoForge Database transfer or all-model scientific acceptance is claimed. The previously documented detached Git Bash process-supervision and general CLI setup-command-enforcement limits remain. Shared Flow changes are recorded in `ki_tools_common/ki_tools_common/flow/UPSTREAM.json` for reconciliation before a future upstream sync. See the [known-issues record](issues/WINDOWS-KNOWN-ISSUES-2026-09-30.md) for other inherited limits.

Only Windows release assets are updated. Earlier public Windows 0.6.54 assets and macOS/Linux releases are preserved.
