# OpenGeoSys 6.5.7 on Apple Silicon

The official wheel provides a genuine Python console entry point for its compiled
solver. Its `ogs._internal.provide_ogs_cli_tools_via_wheel.ogs_with_args` imports
`OGSSimulation` and `check_command_line_arguments` from `ogs.OGSSimulator`, then
calls the latter. Version/help exits before constructing a simulation. Installation
verification requires both the compiled extension import and the installed `ogs`
entry point startup. The KI's `tools/run_ogs.py` is orchestration, not the solver.

Use Python 3.13 and `ogs==6.5.7` in the declared
`binaries/OpenGeoSys/venv`. Keep its actual Python launcher in `kiss.toml` and its
pip-generated `bin/ogs` as the declared product. Leave `OGS_USE_PATH` unset or zero.
The arm64 wheel audited here is `ogs-6.5.7-cp313-cp313-macosx_12_0_arm64.whl`,
SHA256 `f65ed5fb8b8a1ae1d02991bca0f2d49b761091f34962c7b26afdbbf666c9a6d7`.

Upstream documentation: https://www.opengeosys.org/6.5.7/docs/devguide/advanced/python-wheel/

This establishes installation/startup only. No scientific project, mesh, or
simulation is needed or validated by these checks.
