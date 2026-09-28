# macOS Ribasim package installation

Use official Julia 1.12.5 ARM64. The Python ribasim package is the pre/postprocessing API; the Julia Ribasim package is the computational core. The package project pins official core subdirectory at commit 6e7dd978975057392493e32284d0fb18ab00081e. Do not instantiate the upstream repository root metaproject, which includes development tooling.

Keep LocalPreferences.toml next to Project.toml: [Ribasim] precompile_workload=false. This is a supported PrecompileTools preference disabling both setup and compile workloads; the source otherwise conditionally invokes a model example if generated_testmodels data exists. Never download or generate testmodels. See https://julialang.github.io/PrecompileTools.jl/stable/#Package-developers:-reducing-the-cost-of-precompilation-during-development .

Create workspace julia_depot. Replace /WORKSPACE with actual absolute workspace path, call run_setup_command with argv directly and timeout_seconds=1800 for the first compilation. Set JULIA_NUM_PRECOMPILE_TASKS=1, JULIA_NUM_THREADS=1.

Install:
```json
[
  "/WORKSPACE/binaries/julia-1.12.5/bin/julia",
  "--startup-file=no",
  "--history-file=no",
  "--threads=1",
  "--project=/WORKSPACE/ki/julia",
  "-e",
  "length(ARGS) == 2 || error(\"invalid arguments\")\nproject,depot = ARGS\nrealpath(Base.active_project()) == realpath(joinpath(project,\"Project.toml\")) || error(\"wrong project\")\nempty!(LOAD_PATH); append!(LOAD_PATH,[\"@\",\"@stdlib\"])\nmkpath(depot); empty!(DEPOT_PATH); push!(DEPOT_PATH,realpath(depot))\nENV[\"JULIA_PKG_PRECOMPILE_AUTO\"]=\"0\"\nusing Pkg\nPkg.instantiate(;allow_autoprecomp=false)",
  "/WORKSPACE/ki/julia",
  "/WORKSPACE/julia_depot"
]
```

Load/version/UUID/module-bindings probe (never invokes Model or run):
```json
[
  "/WORKSPACE/binaries/julia-1.12.5/bin/julia",
  "--startup-file=no",
  "--history-file=no",
  "--threads=1",
  "--project=/WORKSPACE/ki/julia",
  "-e",
  "using UUIDs\nlength(ARGS) == 6 || error(\"invalid arguments\")\nproject, depot, name, uuid, version, symbols = ARGS\nrealpath(Base.active_project()) == realpath(joinpath(project,\"Project.toml\")) || error(\"wrong project\")\nempty!(LOAD_PATH); append!(LOAD_PATH,[\"@\",\"@stdlib\"])\nempty!(DEPOT_PATH); push!(DEPOT_PATH,realpath(depot))\nm = Base.require(Base.PkgId(UUID(uuid),name))\nstring(Base.PkgId(m).uuid) == uuid || error(\"wrong UUID\")\nstring(pkgversion(m)) == version || error(\"wrong version\")\nf = realpath(pathof(m))\nroot = realpath(depot)\nstartswith(f,root*string(Base.Filesystem.path_separator)) || error(\"module outside depot\")\nfor s in split(symbols,\",\")\n    isdefined(m,Symbol(s)) || error(\"missing package binding\")\nend\nprintln(\"@@KISS-JULIA-PACKAGE-OK@@\")\nprintln(f)",
  "/WORKSPACE/ki/julia",
  "/WORKSPACE/julia_depot",
  "Ribasim",
  "aac5e3d9-0b8f-4d4f-8241-b1a7a9632635",
  "2026.1.0-rc2",
  "Model,run,RIBASIM_VERSION"
]
```

After warmup call test_installation. Keep compiled depot cached. Julia alone or import ribasim in Python does not pass the Julia core contract.

The fixed core load and independent workspace UUID/version check passed locally after289 dependencies compiled in1125seconds. Keep the warmed depot to avoid repeated first compilation. The bundled science runner retains its standalone CLI interface; this package-installation receipt does not claim that a standalone CLI has been installed. The preflight metadata now locates this explicit Julia core project/runtime/depot and distinguishes the Python authoring API from the computational runtime.
