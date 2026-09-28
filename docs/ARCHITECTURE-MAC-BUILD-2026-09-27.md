# C5: Mac test build, 2026-09-27

## Artifact and source identity

- Desktop version: **0.6.54**, bundle build number `0654`, Apple Silicon (`arm64`).
- Test-build label: **architecture-C4-20260927**. The version number has not been bumped for a public release.
- Source at build time: local `mac-version`, baseline HEAD `96ac8a5b`, plus the then-uncommitted C1–C4 implementation and tests documented in the four checkpoint reports.
- App: `/Users/leo/kiss/builds/dist-architecture-c4-v0.6.54-20260927/GeoForge Desktop.app`.
- ZIP: `/Users/leo/kiss/builds/dist-architecture-c4-v0.6.54-20260927/GeoForge-Desktop-v0.6.54-architecture-C4-20260927-macOS-arm64.app.zip` (214 MiB as displayed by `ls -lh`).
- ZIP SHA-256: `3c66117d2cec867343c4b1897fc50f46f2e4688b4e4247522b08251a80fc1200`.
- Inner executable SHA-256: `d57a342be48b5933b9db666ce5f09ebd6c486bcaf1d97e8ce42ea40cb1a9b1e1`.

The bundled release manifest/changelog remain the historical v0.6.54 release metadata, not a claim that this test build is the old published artifact. This document records the test-build identity. No commit, push, tag or GitHub release was made during the build turn. The subsequent source push adds a dated branch-checkpoint entry to the repository changelog; that documentation-only addition is not inside the already-verified ZIP.

## Build

Python 3.13.12, PyInstaller 6.22.2, macOS 15.7.3 arm64:

```sh
python3 -m PyInstaller --clean --noconfirm kiss/GeoForgeDesktop.spec \
  --workpath kiss/build-architecture-c4-v0.6.54-20260927 \
  --distpath /Users/leo/kiss/builds/dist-architecture-c4-v0.6.54-20260927
```

Build succeeded. The checked-in spec was used unchanged. PyInstaller ad-hoc signed the bundle; `codesign --verify --deep --strict` passed. This is not Developer ID signing or notarization.

The output is outside Documents to avoid unnecessarily repeating protected-folder access. Existing app bundles and processes were not replaced, stopped or launched. No guarantee is made that a new ad-hoc build shares prior macOS permissions.

## Frozen-artifact verification

All CLI commands below ran through this app's inner executable from a temporary directory outside the source repository, without `--models` overrides.

| Check | Observed result |
|---|---|
| `list --json` | Exit 0; 127 KI packages found |
| `harness-status VIC` | `ready: true`, `flow_ready: true`, `[KI HARNESS v1]`, 5,363 contract characters; origins inside this bundle |
| `harness-status MODFLOW6` | `ready: true`, `flow_ready: true`, `[KI HARNESS v1]`, 8,048 contract characters; origins inside this bundle |
| `calibration-status` | Ready; required dependencies and all seven backend-module probes available |
| `run-tool --project <empty temporary directory> --step smoke VIC tools/not-run.py` | Expected exit 2: no `kiss.toml`; no files created and no tool launched |
| Embedded Python archive | `execution`, `plan_review`, `project_status`, harness implementation, shared receipts and tool-trust modules present |
| Compiled-code comparison | Eleven Desktop modules match source compilation after normalizing code-object filenames |
| Bundled source/UI comparison | `web/app.html`, shared `receipts.py`, `decisions.py` and `declared.py` byte-identical to current source |
| Bundle version/signature | Version 0.6.54; strict deep signature verification passed |

The eleven compared Desktop modules are `execution`, `plan_review`, `project_status`, `gui`, `flowrun`, `api`, `acquire`, `obs_subset`, `flowgate`, `setup` and `cli`.

Packaging detail: an initial over-strict archive assertion expected `flow.decisions` and `flow.declared` in the compiled archive, but they are shipped as reachable bundled source under the existing spec. Both source files match, and frozen `flowgate.load()` successfully imports all eleven required Flow submodules. The CLI's printed `flow_modules` list still names only nine; it is not the complete loader check. No packaging or application code was changed in this build turn.

Key payload hashes:

- `web/app.html`: `6a22c39e6186fd94f6c723e08491e4159d00553627d5d28f313a78da41de1ce4`
- Shared `flow/receipts.py`: `fb72338ea4382adcc9a11d08d5100b71a69b05f28b8cfd6b7c9dcca1ef5bf6a3`
- Harness implementation: `2c71f65452555f37c3a38b4216ca8f79a401ac81d59ac30befdfd977fa8dd5e8`

## Boundaries and manual check

The immediately preceding source regression remains **814 passed, 5 skipped, 121 subtests passed**, with one pre-existing native-extension warning. That full suite was not rerun during this build-only turn; production/test source was unchanged. Frozen probes are additional checks, not substitutes for live acceptance.

No GUI server, provider, data download, scientific model, real project or keychain operation was started by these probes. In particular, `gui --no-browser` was deliberately not used: it still loads saved settings and starts catalogue refresh. Manual GUI, live DS/Kimi/database, real simulations and Windows acceptance remain pending.

For manual testing, quit the older GeoForge instance before opening this exact app bundle. Check that Plan Review preserves your choices, approval applies to the displayed plan, and the project panel distinguishes acquired data from scientifically validated inputs. Report the dated build label when comparing behavior.
