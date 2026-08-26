#!/bin/bash
# Install Wflow.jl from Deltares GitHub (monorepo - package is in Wflow/ subdir)
set -e

JULIA=KISSPATH_BINARIES/julia-1.10.7/bin/julia
JULIA_ENV=KISSPATH_KI_ROOT/wflow/knowledge_infrastructure/julia

echo "Julia version:"
$JULIA --version

echo ""
echo "Installing Wflow.jl from Deltares GitHub (subdir=Wflow)..."
$JULIA --project=$JULIA_ENV -e '
    using Pkg
    println("Adding Wflow package from Deltares GitHub (subdir=Wflow)...")
    Pkg.add(url="https://github.com/Deltares/Wflow.jl.git", subdir="Wflow")
    println("Precompiling...")
    Pkg.precompile()
    println("Done!")
    using Wflow
    println("Wflow loaded successfully! Version: ", pkgversion(Wflow))
'

echo "Installation complete!"
