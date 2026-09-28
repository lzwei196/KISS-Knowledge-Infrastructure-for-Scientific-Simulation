# Mac planner test build — 2026-09-28

Local test build, not a stable release. Version remains 0.6.54; dated identity is `planner-20260928`, Apple Silicon arm64. Built from `mac-version` HEAD `bdf2522e` plus the current planner/path/activity changes. The subsequent branch commit includes this report and a changelog entry, which were written after compilation and are not inside the already-built ZIP.

- App: `/Users/leo/kiss/builds/dist-planner-v0.6.54-20260928/GeoForge Desktop.app`.
- ZIP: `/Users/leo/kiss/builds/dist-planner-v0.6.54-20260928/GeoForge-Desktop-v0.6.54-planner-20260928-macOS-arm64.app.zip` (215 MiB).
- ZIP SHA-256: `8e6f3f8ac65b16b5f84680e45816c13f6c977e15244108c4fa9a200d4de2159d`.
- Executable SHA-256: `cff2c84d64911a18d1a404f7c05959b18aaaf0acb7ec438e579bc42d6c317511`.

Built with Python 3.13.12 and PyInstaller 6.22.2 using the checked-in spec unchanged:

```sh
python3 -m PyInstaller --clean --noconfirm kiss/GeoForgeDesktop.spec \
  --workpath kiss/build-planner-v0.6.54-20260928 \
  --distpath /Users/leo/kiss/builds/dist-planner-v0.6.54-20260928
```

## Verification

- Ad-hoc signing; `codesign --verify --deep --strict` passed. Not Developer ID signed or notarized.
- Frozen `harness-status APEX` outside the repository: `ready:true`, `flow_ready:true`, `[KI HARNESS v1]`, 4,965 contract characters, implementation origins inside this bundle.
- Frozen `list --json`: 127 KIs, including APEX. `calibration-status`: ready; all seven backend probes available.
- Independent archive audit: 72 compiled Desktop/shared Flow/harness modules structurally match fresh source compilation after code-filename normalization; 26 web/shared-source payload files are byte-identical. Includes `project_paths`, `flowrun`, `plan_review` and shared planning `contracts`.
- Source regression before build: 1,009 Desktop tests passed, 1 skipped, 123 subtests; shared Flow 131 passed, 4 skipped. Not rerun during the build-only operation.
- No existing app or project was overwritten or stopped. The new GUI was not launched automatically; isolated test processes were confirmed stopped.

Archive evidence: `/private/tmp/geoforge-compiled-planner-audit.QpMPzJ/report.json`.

## Manual test and limitations

Quit the older GeoForge instance before opening this exact app, then start a new test conversation. Check one-question-at-a-time planning, custom answers, source alternatives and retention of prior choices.

The previous app already used the shared draft builder and KI harness inspection contract. This update fixes interview/finalization coordination, not a replacement scientific planner. Requirements are read from `dag.yaml`, stages/tools from `SKILL.md`; ATA-derived vocabulary/output/coupling metadata remains supporting information.

Prefer planning-only testing: full plan/download acceptance, source-choice/inventory consistency, parent-product/subset wording and scientific recommendation quality remain open. The source-consistency defect documented in the catalogue acceptance report is not fixed in this build. No public release asset was replaced.

See [planner checkpoint](PLANNER-IMPLEMENTATION-2026-09-28.md) and [catalogue acceptance findings](issues/PLANNER-CATALOGUE-ACCEPTANCE-2026-09-28.md).
