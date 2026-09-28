# Native GeoClaw installation on macOS arm64

The KI declares the Fortran GeoClaw solver, not only Clawpack Python configuration utilities. Install both the actual `xgeoclaw` native product and the declared Python dependencies in the workspace.

Use Clawpack v5.14.0 commit `5ce53b4814a3e03536fa17e8ae05e65960194c56` from https://github.com/clawpack/clawpack. Initialize its pinned `geoclaw`, `amrclaw`, `clawutil` and `riemann` submodules. Their commits are respectively `11479f675dd8bb19066a2430c28206999cebf299`, `98ba14a90986943846a1c019f0cbad82765a60f1`, `807d01379a1d4fb47f3e4f355dd74b85afd6a4bd`, and `789c2b0d2d91694f715dcffed8ce0990871c465b`.

Copy only `geoclaw/examples/tsunami/bowl-radial/Makefile` into a fresh `native-build` directory. That upstream Makefile chooses the standard GeoClaw core and official Riemann routines without custom application source overrides. Run only `make -j1 .exe` there with absolute `CLAW` source root, `FC=gfortran`, and `CLAW_PYTHON` set to a real Python interpreter. The build scripts use the Python standard library. Do not execute default make or data, topo, output, plots, all targets. No scientific case inputs are required to compile. Parallel make produced a real truncated Fortran module race in the local audit; serial make avoids it.

The native product is `native-build/xgeoclaw`. Probe it in an empty temporary directory, with closed stdin and a short timeout. The source `geoclaw/src/2d/shallow/amr2.f90` calls `opendatafile` on `claw.data` before simulation setup; `amrclaw/src/2d/opendatafile.f` prints `*** in opendatafile, file not found:claw.data` and stops when that scientific input is absent. Retain this actual native receipt; do not generate a dataset or substitute the Python interpreter to force success. This validates the baseline native solver installation, not a configured scientific application or optional dispersive/surge capabilities.

Official compilation target documentation: https://www.clawpack.org/makefiles.html

Local audit built the genuine Mach-O arm64 solver with unmodified upstream source using serial make. Empty-directory `--version` startup returned 0 and printed the exact missing `claw.data` message above. Evidence is retained outside the shipped KI in `work/geoclaw-native-build.json`, `work/geoclaw-native-build.log`, and `work/geoclaw-native-startup.json`. Fresh DS installation verification remains pending.
