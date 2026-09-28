# ATS native Mac installation

The pinned source build, complete installation, and three native CLI probes passed locally. Fresh DS94 installation passed in1247.8seconds; the independent full installation gate passed native loading, linkage, startup and all five KI imports.

The intended native product is `binaries/Amanzi_ATS/install/bin/ats`, built from Amanzi `f8b03562ec6dea6257baf1250bddf889caef8ffb` and nested ATS `e23c8eef6773e1a055cbda74f1c7c4a553c7d6c5`. Full ATS physics uses the genuine Amanzi core. Upstream ATS/Amanzi physics-module choices are mutually exclusive; this scope does not require a separate `amanzi` executable. The existing KI runner already prefers `ats`, then `amanzi`. The runner itself is not proof that either native model is installed.

Source acquisition must be performed by the trusted helper before generic `acquire[build]`:

```
python3 ki/tools/build_amanzi_ats_native.py binaries/Amanzi_ATS --prepare-only
python3 ki/tools/build_amanzi_ats_native.py binaries/Amanzi_ATS
```

The first call fetches pinned Git sources with a filtered, initially unchecked-out clone and exact software-only sparse patterns. It includes Amanzi `tools/py_lib` , ATS `testing/CMakeLists.txt` build metadata the install-required software schema `doc/input_spec/schema/amanzi.xsd`, and software utility `tools/input/UpdateSpec_210to211.py`. The schema is software metadata, not a populated scientific case. Scientific examples, test datasets and recursive demo submodules are excluded. Preparation also fetches genuine upstream ATS tags with a blob filter, verifies HEAD remains pinned, and records tag object IDs plus the CMake metadata hashes. The second call builds the native model freshly and records its provenance. A future DS launcher can run `--prepare-only` during preparation; it must not copy model executables, objects or model libraries. The manifest's ordinary build commands are appropriate only after that source preparation, because the current generic acquisition code otherwise performs a full checkout before invoking helper commands.

Place explicit same-host provider paths in workspace `amanzi-ats-build-config.json`. The following provider descriptions identify the audit dependencies, whose TPL and model builds have completed; these are not a model readiness claim:

- `tpl_prefix`: genuine `work/amanzi-ats-native/tpl-install`, including `share/cmake/amanzi-tpl-config.cmake` after the final TPL install.
- `cmake`: genuine CMake3.31.10 in `work/amanzi-ats-native/tool-venv/bin/cmake`.
- `build_python`: genuine Python3.11 environment launcher, preserving its venv path.
- `mpi_prefix`: genuine MPICH4.3.1 prefix, currently `/opt/homebrew/opt/mpich`.

The helper validates these providers. A setup-tool denial of direct external-prefix inspection does not establish that same-host dependencies are missing; inspect the trusted helper's result before attempting a replacement dependency build. The helper does not modify the supplied dependency providers.

`tools/ats-configure-options.json` is derived from the root's prepared `model-configure-args.json`. It enables full ATS/unstructured physics, MSTK, SuperLU, HYPRE, CLM, Silo and Epetra; disables standalone Amanzi physics, PETSc, Alquimia/PFLOTRAN/CrunchTope, CUDA/OpenMP, ELM API and all tests/regression execution, including the independently default-enabled ENABLE_UnitTest option. Scientific solver capabilities excluded by those deliberate options must not be claimed. Builds use two jobs; singleton startup uses the known MPICH `FI_PROVIDER=tcp FI_TCP_IFACE=en0` environment.

After actual native success, use only `ats --version`, `ats --print_version`, and `ats --help` in an empty temporary directory with closed stdin and a25-second bound. Each explicitly finalizes Kokkos and exits0 before any input-file checks in the pinned ATS `src/executables/main.cc`. Record native arm64 shape, file hash, actual dynamic linkage, complete stdout/stderr, exit status, both compiled Git hashes in `--print_version`, and no created files. No XML, mesh, parameters, forcing or model simulation is needed.

Validation requirements:

1. Revalidate the two hash-guarded build-system repairs against the final build: quote the empty detached-branch CMake string in AmanziVersion.cmake, and expose STATE_SOURCE_DIR outside BUILD_TESTS. Neither changes scientific source or invents version labels. Add further repairs only if proven necessary.
2. Confirm the installed `bin/ats` path and all runtime libraries. Do not assume the CMake output-directory override works; upstream uses a nonstandard property.
3. Confirm the final installed TPL cache, exact provider versions/ABI and configure options. The TPL installation and fresh-workspace helper reproduction both passed.
4. Confirm that building all enabled software targets followed by `cmake --install` works without absent disabled targets or excluded data files.
5. Check generated version labels alongside compiled Git hashes; version scripts inspect available tags, so version text alone does not establish identity.
6. Independently validate the native build and helper, then perform a fresh DS installation with no native model preseed. Mark the manifest verified only after that receipt.

## Full installation and retained DS94 evidence

Building only target `ats` is insufficient for upstream install: the first real install stopped because `src/utils/xml_to_yaml` had not been built. The helper builds the default all target at two jobs before installing; preserve this ordering and keep all four test options disabled, including ENABLE_UnitTest. The tool may install genuine converters/utilities, but installation verification must never invoke them with scientific files.

For the fresh DS workspace, prepare only the two pinned, software-only source checkouts and the explicit same-host provider JSON. Do not copy root build objects, libraries or executables. Record the absence of `ki-build` and `install/bin/ats` before the helper build. The actual TPL cache identifies the stable dependency prefix and MPICH ABI; the NetCDF SuperBuild header repair belongs to that already-built provider and is not a third model-source patch.

Attest both repository HEAD and tree IDs and every materialized tracked regular source file's SHA256 against its pinned Git blob, accepting exactly the two recorded CMake patch outputs in Amanzi and no ATS changes. Record omitted sparse files and do not materialize them for hashing. Preserve the tag/ref IDs, sparse pattern hashes, both version-generation scripts and generated version headers. Compiled version labels and both compiled Git abbreviations backed by exact checkout hashes must agree with the pinned source; native product hashes are workspace-specific and must be measured freshly, not copied from the root proof.

After a successful full install, preserve `install_manifest.txt`, its SHA256 and every installed path's type, size, SHA256 or symlink target. Require real arm64 `install/bin/ats`, every installed model dylib and static archive, and the actual installed software utility files such as `xml_to_yaml`. Record `file`, `otool -L` and `otool -l` for ATS and installed native libraries, resolving links and rpaths: model libraries must come from this fresh workspace and dependencies only from the declared genuine TPL/MPI/compiler/system providers. Flag unresolved links or references to root model build/install trees.

Run only the three bounded installation CLI probes from separate empty directories with stdin closed and known singleton MPI environment. Preserve complete stdout/stderr, elapsed time, return code and no-created-files proof. Build-tree success alone is insufficient: repeat on `install/bin/ats`. Finally obtain an independent current-engine receipt and source/native audit of the preserved DS workspace. Do not infer pass from the Python wrapper, compiler output or a generic zero exit alone.

Retained earlier failure: build-tree `--version` timed out at25seconds. The later installed-tree success is separate evidence; this earlier timeout is not rewritten. Fresh-workspace helper and DS94 proof subsequently passed.

Root installed proof now passed: ATS1.6.0_e23c8eef / Amanzi1.7-dev_f8b03562e, all three CLI probes exit0 without files. First installed `--version` took40.283s during cold dyld loading; `--print_version` took0.226s and `--help`0.249s. Help is on stderr, so the helper checks combined stdout/stderr and preserves each separately. A60-second bound accommodates measured cold loading; the original25-second timeout remains retained rather than reclassified as a pass.

The native build phase uses its own process group, a live16GiB free-space guard checked every2seconds, and a3600second maximum. On breach it terminates only that build group and retains build logs plus ki-native-build-status.json; it does not touch other builds or providers. Prepare-only behavior is unchanged.

## Verified installation scope

DS94 finished installed on2026-09-09 at14:20:51+0800 in1247.8seconds. Independent evidence verifies the two exact source pins across2592materialized tracked files, precisely the two CMake repairs,45installed model dylib hashes, and three native CLI probes. The current engine gate reports present, shaped, linked, responds and imports all true with no missing requirements. The DS agent repaired missing Python dependencies; the final Mac recipe now explicitly lists numpy, pandas, h5py, matplotlib and lxml.

The manifest is marked partial because verification covers installation of full ATS physics with the Amanzi core and KI imports, not standalone Amanzi physics, model cases or scientific workflow compatibility. No scientific simulation was run. Raw run result and independent evidence are preserved under work/mac-ds-repair-94-ats-native-20260908; the active v19 snapshot was not modified.
