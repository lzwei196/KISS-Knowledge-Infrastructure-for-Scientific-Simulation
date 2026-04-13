#!/usr/bin/env python3
"""
verify_pywr_installation.py — Check Pywr installation, solver, and dependencies.

Usage:
    python verify_pywr_installation.py

Output:
    JSON with pywr version, solver availability, and dependency status.
    Exit codes: 0 = all OK, 1 = pywr not installed, 2 = solver missing, 3 = partial
"""

import argparse
import json
import sys


def check_pywr():
    """Check Pywr import and version."""
    try:
        import pywr
        return {"installed": True, "version": pywr.__version__}
    except ImportError as e:
        return {"installed": False, "version": None, "error": str(e)}


def check_solver():
    """Check GLPK solver availability via Pywr."""
    try:
        from pywr.model import Model
        import tempfile
        import os

        # Minimal model JSON to test solver
        minimal = {
            "metadata": {"title": "solver_test"},
            "timestepper": {
                "start": "2000-01-01",
                "end": "2000-01-10",
                "timestep": 1
            },
            "nodes": [
                {"name": "input1", "type": "input", "max_flow": 10.0},
                {"name": "output1", "type": "output", "max_flow": 5.0, "cost": -10.0}
            ],
            "edges": [["input1", "output1"]]
        }

        tmpdir = tempfile.mkdtemp()
        model_path = os.path.join(tmpdir, "test_model.json")
        with open(model_path, "w") as f:
            json.dump(minimal, f)

        model = Model.load(model_path)
        solver_name = model.solver.name if hasattr(model.solver, "name") else type(model.solver).__name__
        model.run()

        # Cleanup
        os.remove(model_path)
        os.rmdir(tmpdir)

        return {"available": True, "solver": solver_name}
    except Exception as e:
        return {"available": False, "solver": None, "error": str(e)}


def check_dependencies():
    """Check key Python dependencies."""
    deps = {}
    for pkg_name, import_name in [
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("geopandas", "geopandas"),
        ("netCDF4", "netCDF4"),
        ("xarray", "xarray"),
        ("matplotlib", "matplotlib"),
        ("shapely", "shapely"),
        ("scipy", "scipy"),
    ]:
        try:
            mod = __import__(import_name)
            version = getattr(mod, "__version__", "unknown")
            deps[pkg_name] = {"installed": True, "version": version}
        except ImportError:
            deps[pkg_name] = {"installed": False}
    return deps


def main():
    parser = argparse.ArgumentParser(
        description="Verify Pywr installation and solver availability"
    )
    parser.add_argument("--json", action="store_true", default=True,
                        help="Output as JSON (default)")
    args = parser.parse_args()

    result = {
        "pywr": check_pywr(),
        "solver": check_solver(),
        "dependencies": check_dependencies(),
    }

    # Determine exit code
    if not result["pywr"]["installed"]:
        result["status"] = "FAIL"
        result["message"] = "Pywr is not installed"
        exit_code = 1
    elif not result["solver"]["available"]:
        result["status"] = "FAIL"
        result["message"] = "GLPK solver not available"
        exit_code = 2
    else:
        missing = [k for k, v in result["dependencies"].items() if not v["installed"]]
        if missing:
            result["status"] = "PARTIAL"
            result["message"] = f"Pywr OK but missing dependencies: {missing}"
            exit_code = 3
        else:
            result["status"] = "OK"
            result["message"] = f"Pywr {result['pywr']['version']} with {result['solver']['solver']} solver — all dependencies present"
            exit_code = 0

    print(json.dumps(result, indent=2))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
