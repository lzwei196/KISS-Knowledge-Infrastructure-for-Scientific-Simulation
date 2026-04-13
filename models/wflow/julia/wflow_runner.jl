#!/usr/bin/env julia
"""
wflow_runner.jl — Thin Julia wrapper for executing wflow models.

Called by Python tools via subprocess. Accepts a single argument: the path
to the wflow TOML configuration file.

Usage:
    julia --project=/path/to/julia_env wflow_runner.jl /path/to/config.toml

Exit codes:
    0 — success
    1 — argument error
    2 — Wflow load error
    3 — model execution error
"""

if length(ARGS) < 1
    println(stderr, "ERROR: Missing argument. Usage: wflow_runner.jl <config.toml>")
    exit(1)
end

toml_path = ARGS[1]

if !isfile(toml_path)
    println(stderr, "ERROR: TOML file not found: $toml_path")
    exit(1)
end

println("wflow_runner.jl: Loading Wflow package...")
try
    using Wflow
catch e
    println(stderr, "ERROR: Failed to load Wflow package: $e")
    println(stderr, "Ensure Wflow.jl is installed: julia -e 'using Pkg; Pkg.add(\"Wflow\")'")
    exit(2)
end

println("wflow_runner.jl: Starting model run with config: $toml_path")
try
    model = Wflow.run(toml_path)
    println("wflow_runner.jl: Model run completed successfully.")
    exit(0)
catch e
    println(stderr, "ERROR: Model execution failed: $e")
    # Print the full stack trace for debugging
    for (exc, bt) in Base.catch_stack()
        showerror(stderr, exc, bt)
        println(stderr)
    end
    exit(3)
end
