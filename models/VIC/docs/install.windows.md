# VIC: Windows installation experience

Latest independently checked build: **official release 5.1.0, native Stehekin run passed on 2026-10-01**. The source is [UW-Hydro/VIC tag `5.1.0`](https://github.com/UW-Hydro/VIC/tree/5.1.0), commit `14a371a8dbee7ea834152f8ac65e2d6d54a9c30a`. Build tools were TDM-GCC 10.3.0 and its `mingw32-make` on Windows x64.

The earlier 2026-09-05 record proved only executable startup. A fresh DeepSeek installation on 2026-10-01 initially selected `VIC.5.1.0.rc2` (`7db79d66ff960b4b7306b567f09fe6e65c3f95fd`), built a Windows executable, and passed its version probe. Its first real run crashed before producing output. The fixes below were tested on that build, then reproduced against the official final release. Keep the source revision in the installation record; RC2 is not the final release.

## Build from the official final release

Read SKILL.md and diagnostics first. These files preserve the working compiler/OS adaptations from the DeepSeek build; they are not a replacement model or a package installer:

- [`build-portability.patch`](../installer/windows/build-portability.patch): Windows Makefile settings, `-fcommon`, Winsock linkage for host metadata, and local POSIX compatibility headers/functions. No model equations or parameters are replaced.
- [`patch_vic_stdio.py`](../installer/windows/patch_vic_stdio.py): config-file seek/newline handling and diagnostic backtrace safety. It is idempotent, preserves source line endings, checks all expected source blocks before writing, and refuses unknown source layouts.

Use the configured installation workspace. In PowerShell, set `$vicSource` to its canonical `binaries/VIC-5.1.0` directory and `$vicKI` to this KI directory. Start with a fresh official checkout; retain an existing modified checkout before replacing it.

```powershell
git clone --branch 5.1.0 --depth 1 https://github.com/UW-Hydro/VIC.git $vicSource
git -C $vicSource rev-parse HEAD
# Must be 14a371a8dbee7ea834152f8ac65e2d6d54a9c30a.

git -C $vicSource apply --check "$vicKI/installer/windows/build-portability.patch"
git -C $vicSource apply "$vicKI/installer/windows/build-portability.patch"
python "$vicKI/installer/windows/patch_vic_stdio.py" --source-root $vicSource --report "$vicSource/windows-stdio-patch.json"
mingw32-make -C "$vicSource/vic/drivers/classic" model CC=gcc
& "$vicSource/vic/drivers/classic/vic_classic.exe" -v
```

Do not apply the build patch twice. `git apply --reverse --check` can identify an already-applied patch; the Python repair helper can be rerun safely. Retain the revision, diff, compiler output, and binary hash. The source header at the official final tag still contains a stale `5.0.1` version string; the verified tag/commit is the authoritative identity. Do not relabel an RC2 checkout as final merely to satisfy a version check.

The resulting canonical executable is `binaries/VIC-5.1.0/vic/drivers/classic/vic_classic.exe`. The final independently tested binary had SHA-256 `4c3335cea13f98174a0fcf667ade2691939f32ac6889cd98795ab05fed465fd1`; another correct local build may differ because VIC embeds build metadata.

## Why startup alone missed the failures

1. `count_force_vars()` and `count_nstreams_nvars()` flushed an input stream before saving its cursor. On the Microsoft CRT this discarded unread buffered text. A debugger observed the global-config position jump from byte 419 to EOF at byte 1481, leaving forcing format/types unread. The helper preserves the input cursor on Windows.
2. Windows text-mode `ftell`/`fseek` also mislocated the cursor in an LF-only config. Classic-driver global configs now open in binary mode, and config scanners skip blank CRLF lines explicitly. Both line endings retain identical scientific values.
3. The Windows backtrace shim returns zero frames/NULL symbols. Upstream `size_t i = size - 2` underflowed while trying to print the original configuration error, causing access violation `0xC0000005`. The helper checks the frame count and symbols first, so a bad config exits with its real error.

The same repair patterns apply to final `5.1.0` and RC2. The final patch set was applied to fresh files archived from the official final commit and reproduced all 12 tested build/parser/compatibility source files exactly after normalizing line endings.

## Independent native acceptance

Use the official [Stehekin classic inputs](https://github.com/UW-Hydro/VIC_sample_data/tree/997fc6bdc423cba72dac7895098d636172179967/classic/Stehekin), pinned sample commit `997fc6bdc423cba72dac7895098d636172179967`, and the final release's [ten-day global template](https://github.com/UW-Hydro/VIC/blob/14a371a8dbee7ea834152f8ac65e2d6d54a9c30a/tests/examples/global_param.classic.STEHE.feb.txt).

Download only the 16 `full_data_*` forcing files and four parameter files (`Stehekin_soil.txt`, `Stehekin_veglib.txt`, `Stehekin_vegparam.txt`, `Stehekin_snowbands.txt`), plus the template/provenance documentation. Preserve their original bytes and SHA-256 hashes. The forcing has 240 hourly records per cell for 1949-01-01 through 1949-01-10; the grid spacing is 0.125 degrees. The template already selects this period and full-energy mode. Replace only `$test_data_dir` and `$result_dir` with the local paths, and create the output directory.

```powershell
& "$vicSource/vic/drivers/classic/vic_classic.exe" -g "$caseRoot/global_param.txt"
```

Observed final-release results:

- LF config and CRLF config with blank lines both exited zero in approximately 4.8 seconds.
- Each run produced 48 nonempty files: 16 `fluxes`, 16 `snow`, and 16 `snowband`, each covering the expected 10 daily dates. Default output aggregation is daily although forcing/model steps are hourly.
- All numeric output values were finite; runoff/baseflow were nonnegative. For every cell/day, output precipitation matched the sum of the original 24 hourly precipitation values to within 0.00011 mm (output rounding).
- All 48 LF/CRLF output files were byte-identical. No unknown-config warnings remained.
- Removing `FORCE_FORMAT` deliberately returned exit code 1 with the specific forcing-format error, without an access violation.

Sample snow-band and canopy warnings remain visible; do not alter the official scientific inputs to silence them. The checked-in [verification record](../installer/windows/verification-2026-10-01.json) retains source URLs/revisions and input/output hashes. Full evidence is retained at `D:/GFVerify1001/VIC/` on the validation host, including source diffs, stdout/stderr, and `native-validation.json`.

## Desktop execution and scope

For an uploaded, model-ready case the smallest scientific plan is one `run` step invoking the declared absolute `vic_classic.exe` through `run_ki_tool`, with arguments `-g` and the project config path plus the approved `plan_step_id`. Keep outputs below the project. GeoForge records the native execution receipt; a startup probe is not this scientific run.

These checks establish native execution and basic input/output integrity for the official ten-day example. They do not establish calibration, observational skill, long-term water balance, state-file restart support, or routed gauge discharge. VIC cell runoff/baseflow are not streamflow. The generic `s6_post/grid_runoff_nc.py` also expects only flux files in its result directory; the default mixed flux/snow/snowband output directory is not a valid input to that tool.

The current KI preflight additionally requires CaMa-Flood 4.20 even for this standalone VIC example. The validation installation contains both executables and passes that check, but do not interpret CaMa availability as evidence that routing was run. Installation-only agents should perform startup checks; scientific acceptance belongs in a separately approved project or independent test workspace.
