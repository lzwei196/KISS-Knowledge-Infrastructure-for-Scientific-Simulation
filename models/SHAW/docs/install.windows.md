# SHAW: Windows installation experience

Observed 2026-10-01: SHAW 3.03 builds and runs natively on Windows x64. DeepSeek's GeoForge installation produced the executable, but independent verification found a missing transitive runtime DLL. After copying that DLL from the same staged compiler, the unchanged official Trial completed and matched the official reference tables. This is a repaired, independently verified installation, not an unattended installer success claim.

## Source and native build

Use the USDA-ARS [SHAW project](https://www.ars.usda.gov/pacific-west-area/boise-id/northwest-watershed-research-center/docs/shaw-model/) and [official 3.03 archive](https://www.ars.usda.gov/ARSUserFiles/20520500/SHAW/303/Shaw303.zip). The tested source is `Shaw303/Code+Debug/Shaw303.for`, 482,533 bytes, SHA-256 `b10bb45c984d7f9c1831f722fcd5a27f1d091ff08da4b6d838d2bcd51066a1fe`. `tools/fetch_shaw_build_source.py` retrieves and verifies this exact source member; it fails if the upstream archive changes. Run it from the installation workspace with an output path inside that workspace.

The observed compiler was [WinLibs GCC 16.2.0, UCRT x64, POSIX/SEH, r2](https://github.com/brechtsanders/winlibs_mingw/releases/tag/16.2.0posix-14.0.0-ucrt-r2). Its archive was `winlibs-x86_64-posix-seh-gcc-16.2.0-mingw-w64ucrt-14.0.0-r2.zip`, SHA-256 `d5dbafc4a170e762ca6143151ec918fb9e2c72736fb14cd704abebc6bdd5276a`. Keep compiler extraction paths short. No system-wide installation or administrator access was required.

Observed PowerShell compiler invocation, with `$project` set to the installation workspace and the verified compiler extracted under `b/mingw64`:

```powershell
$compilerBin = Join-Path $project 'b/mingw64/bin'
$binaryDir = Join-Path $project 'binaries/shaw' # use the configured [paths].binaries role
New-Item -ItemType Directory -Path $binaryDir -Force | Out-Null
$env:PATH = "$compilerBin;$env:PATH"
& "$compilerBin/gfortran.exe" -O2 -w -std=legacy -fallow-argument-mismatch -fno-automatic -o "$binaryDir/shaw303.exe" "$project/b/src/Shaw303.for"
Copy-Item -LiteralPath "$binaryDir/shaw303.exe" -Destination "$binaryDir/shaw.exe"
foreach ($dll in @('libgfortran-5.dll', 'libgcc_s_seh-1.dll', 'libwinpthread-1.dll', 'libquadmath-0.dll')) {
    Copy-Item -LiteralPath "$compilerBin/$dll" -Destination "$binaryDir/$dll"
}
```

The output was 412,998 bytes, SHA-256 `c3845f35b371c23d807f55f8f5dd2fef04fd5202ace78b33cfe4563ad98d4195`. Compiler flags preserve the legacy Fortran behavior; no scientific source/default changes were made. Executable hashes may differ with other toolchains.

All **four** listed DLLs must come from the same compiler distribution. The initial installation copied three and omitted `libquadmath-0.dll`, which `libgfortran-5.dll` imports. The resulting process returned `0xC000007B` with no output. File existence and a PE header did not establish a working runtime. Repairing the DLL set restored genuine execution. Do not copy arbitrary DLLs from unrelated installations.

Prefer `shaw.exe` and `shaw303.exe` as the actual Windows files. Windows treats `Shaw303` and `shaw303` as the same name, so an upstream source directory can block an extensionless executable alias. The KI wrapper and preflight resolve the `.exe` sibling.

The original DeepSeek build landed under `<workspace>/model/shaw`, the legacy Linux layout. A Desktop project correctly refused that external path because it lies outside the installation's configured `binaries` role. Copying the same executable and its four DLLs into `<binaries>/shaw` preserved every hash and made the installation usable through the normal tool boundary. Windows wrapper defaults and preflight now prefer this configured directory, with the legacy layout retained for existing standalone installs and Linux. Do not widen the Desktop argument guard or copy binaries into scientific output directories. An old preflight may still require `model/shaw/shaw.exe`; retain that legacy alias while updating an existing installation, but use the managed path for project runs.

The official archive also contains a vendor native `Shaw303/Shaw303.exe`, 1,207,808 bytes, SHA-256 `7e75e72cbd71765fe3e9f22dab545533fa578e01c6913afb3cfa87b4921f0753`. This exact vendor executable completed the Trial and produced all eight reference output files byte for byte on the tested Windows machine. It is an alternative to compiling; check upstream redistribution terms before bundling it.

## Verification and project inputs

Materialize the KI using the configured interpreter. The corrected preflight's `KISSPATH_PYTHON_ENV/bin/python` token resolves to the configured Windows `venv/Scripts/python.exe`; a path assembled as `root/python_env/bin/python` bypasses that mapping. Test imports of `numpy`, `matplotlib`, `ki_tools_common`, `ki_tools_common.soil_utils`, and `ki_tools_common.load_forcing` with that interpreter. Install plotting dependencies with `& $python -m pip install numpy matplotlib` in the installation's own virtual environment. The observed environment was Python 3.13.5 with its own `ki_tools_common`; the first Desktop plot failed because matplotlib was missing. The dependency repair installed matplotlib 3.11.2 into that virtual environment, with numpy 2.5.3 already present. Matplotlib is now a critical preflight import, so a future missing plot dependency cannot pass software verification.

`preflight_check.py` requires actual SHAW banner/prompt output and working imports. A bare SHAW launch reads its control filename from stdin; an EOF after the banner can be expected for that startup probe. An empty-output loader crash is a failure. The repaired installation passed all critical checks. Example Trial files and shared scientific datasets are informational checks: installing software does not establish a project's inputs. The run wrapper still requires all files named by the selected control file.

Obtain the five unchanged upstream files `Trial.303.inp`, `Trial.30.sit`, `Trial.30.wea`, `Trial.moi`, and `Trial.tem` in a fresh project run directory. Preserve the existing control, including its hourly SI flags and trailing PEST comparison configuration:

```powershell
& $python "$ki/s6_execution/tools/run_shaw.py" --workdir $run --inp_file Trial.303.inp --shaw_exe "$binaryDir/shaw303.exe"
& $python "$ki/s6_execution/tools/parse_shaw_output.py" --workdir $run --output_dir "$run/csv"
```

For files uploaded to a separate input directory, add `--stage_from $uploads`
to the run command. The wrapper copies the control and referenced input files
unchanged into `$run` before validation and native execution. It rejects paths
that escape those directories, input/output collisions, and replacement of a
different existing file. No separate staging tool or rewritten site is needed.

If generating a new control from the four separate input arguments, explicitly use `--mtstep 0` for hourly weather. The default `--mtstep 1` expects daily weather. Generated controls do not reproduce an existing Trial's PEST settings. On an authorized rerun, the wrapper supplies SHAW's own `Y` overwrite answer only when declared enabled outputs already exist. The native model performs the replacement; the wrapper does not delete or manufacture outputs. Freshness, complete time coverage and node-shape checks still apply, so unchanged old outputs cannot prove success.

The native build and corrected wrapper exited 0. Temperature and moisture each contained 301 rows and 11 nodes; energy 300 rows, water 13, frost 48, and liquid water 14. The initial profile was 1986-12-04 12:00; all six tables reached day 350, hour 24, year 86, normalized to **1986-12-17 00:00**. All timestamps and published numeric values matched the official Trial references exactly (maximum absolute difference 0.0 at the files' printed precision). GNU Fortran reported underflow/denormal status flags at normal termination. This does not assert equality of unrounded internal values or validation at a new site.

The wrapper checks every enabled output is fresh and nonempty and requires the
complete expected timestamps and site node count in each enabled temperature,
moisture, or liquid-water profile. A terminal row alone or an old output file is
insufficient. CSV readers reject truncated/ragged/nonfinite numeric rows; they
preserve `DAY HR YR`, normalize hour 24, distinguish precipitation from snowmelt,
compute net radiation from net solar plus net longwave, and convert SWE mm to cm
only when the column explicitly says cm. The plotting CLI uses actual nonuniform
depths from profile headers; `--depths` supplies explicit metre depths if a custom
file omits them. It never invents a 0–4 m grid.

Evidence retained locally under `D:/GFVerify1001/SHAW`: `provenance.json`, `baseline-summary.json`, `deepseek-native-summary.json`, `corrected-wrapper-summary.json`, `wrapper-vendor-clean.log`, `preflight.corrected.stdout.log`, and `staged-native-final-summary.json`. The staged native run, CSV export, and plot each exited 0; all five staged input files remained byte-identical to upstream. The earlier empty-output false-pass record is retained separately by the desktop test harness; it must not be presented as successful execution. Small authentic reference excerpts and provenance are included in `kiss/tests/fixtures/shaw_trial` for regression testing.

## Earlier attempt

The 2026-09-05 installation-only DeepSeek attempt ended `needs-user` after 164.8 seconds, classified `permission`; the independent check found no `<workspace>/model/shaw/shaw`. Its surviving record does not identify the original permission cause. The observed native build above supersedes that unresolved installation recipe without changing its historical outcome.
