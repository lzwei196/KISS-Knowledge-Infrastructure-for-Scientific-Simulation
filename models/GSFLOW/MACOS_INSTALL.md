# Native GSFLOW 2.3.1 installation

Public developer source: https://github.com/rniswon/gsflow_v2 at dcb53506fd0ce6ea21d3f0290724024420840bb2. Source embeds 2.3.1 12/15/2023. The USGS landing page is not a Git repository. Build full upstream Fortran/C code using pinned modflowpy/pymake and genuine gfortran/clang. Use a workspace Python environment for pymake and KI dependencies.

Apply the exact-source CLI helper before compiling. It only adds help/version exits ahead of scientific initialization; stock commands interpret --version as a missing control file. Keep source and final native autotest/gsflow product at the declared location. No scientific inputs, cases, or simulations are required for installation checking.

The trusted build helper runs the upstream make_gfortran.py from autotest, using ../GSFLOW/src and local target gsflow. An alternate target path from repo root fails pymake module-directory creation; use the helper's validated working directory.
