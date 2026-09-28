# macOS Wflow package installation

The Julia executable is the language runtime. The actual model is Wflow in the pinned KI project. Keep the existing Project.toml and Manifest.toml; do not run the old install_wflow_pkg.sh because it adds the current upstream branch. The retained Manifest pins Wflow tree 2a5f25884436c1d3038d40b7be4185d59c9533e7.

Extract official Julia archive into binaries/julia-1.10.7. Create julia_depot in this workspace. Replace /WORKSPACE in the following argv arrays with the actual absolute workspace path. Send argv directly to run_setup_command, never shell wrappers. Set JULIA_NUM_PRECOMPILE_TASKS=1 and JULIA_NUM_THREADS=1. These exact fixed expressions are recognized by the installation guard.

Install (no examples or scientific data):
```json
[
  "/WORKSPACE/binaries/julia-1.10.7/bin/julia",
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

Load and check the real package (first compilation may take several minutes, use setup command timeout up to allowed maximum; then the independent probe should be warm):
```json
[
  "/WORKSPACE/binaries/julia-1.10.7/bin/julia",
  "--startup-file=no",
  "--history-file=no",
  "--threads=1",
  "--project=/WORKSPACE/ki/julia",
  "-e",
  "using UUIDs\nlength(ARGS) == 6 || error(\"invalid arguments\")\nproject, depot, name, uuid, version, symbols = ARGS\nrealpath(Base.active_project()) == realpath(joinpath(project,\"Project.toml\")) || error(\"wrong project\")\nempty!(LOAD_PATH); append!(LOAD_PATH,[\"@\",\"@stdlib\"])\nempty!(DEPOT_PATH); push!(DEPOT_PATH,realpath(depot))\nm = Base.require(Base.PkgId(UUID(uuid),name))\nstring(Base.PkgId(m).uuid) == uuid || error(\"wrong UUID\")\nstring(pkgversion(m)) == version || error(\"wrong version\")\nf = realpath(pathof(m))\nroot = realpath(depot)\nstartswith(f,root*string(Base.Filesystem.path_separator)) || error(\"module outside depot\")\nfor s in split(symbols,\",\")\n    isdefined(m,Symbol(s)) || error(\"missing package binding\")\nend\nprintln(\"@@KISS-JULIA-PACKAGE-OK@@\")\nprintln(f)",
  "/WORKSPACE/ki/julia",
  "/WORKSPACE/julia_depot",
  "Wflow",
  "d48b7d99-76e7-47ae-b1d5-ff0c1cf9a818",
  "1.1.0-dev",
  "Model,run"
]
```

This only resolves package dependencies and loads the Julia module, verifies its UUID/version and Model/run bindings without invoking either. Do not download model inputs or call Wflow.run. Call test_installation after this completes.
