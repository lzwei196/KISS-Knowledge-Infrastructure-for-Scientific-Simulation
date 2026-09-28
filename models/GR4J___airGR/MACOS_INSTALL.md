# Native airGR installation on macOS arm64

The KI uses the actual INRAE airGR R package, whose GR4J implementation is compiled Fortran. Rscript by itself and the KI Python helper scripts are not the model.

Observed on this host: R 4.5.1 arm64 with airGR 1.7.8, matching the KI version. Official source: https://cran.r-project.org/src/contrib/Archive/airGR/airGR_1.7.8.tar.gz ; SHA256 `92e96f1f0ac30a8cdbf0759d1199d49bcd9082a5535359712a4c36340ebae705`.

Install into the model workspace, specifically `<workspace>/R/library`, matching the KI tools and preflight, with `R CMD INSTALL --library=<absolute-library> <archive>`. Keep the entire installed package. It contains `airGR/libs/airGR.so` plus its R namespace, metadata and runtime assets.

The host CRAN R installation expects `/opt/gfortran/bin/gfortran`, which is absent. The verified source build instead used an isolated `R_MAKEVARS_USER` file within the workspace, containing:

```
FC = /opt/homebrew/bin/gfortran
F77 = /opt/homebrew/bin/gfortran
FFLAGS = -fPIC -O2
FCFLAGS = -fPIC -O2
FLIBS = -L/opt/homebrew/opt/gcc/lib/gcc/current -lgfortran -lquadmath
```

These are actual host toolchain paths; verify them on another Mac. Do not modify user/global R configuration. Export `R_MAKEVARS_USER` only for the installation subprocess. The source package compiled and passed R's temporary and final library-load checks without model source changes.

Installation-only verification must run Rscript with `--vanilla`, load `library(airGR, lib.loc=<absolute-library>)`, assert the loaded DLL path is exactly `<absolute-library>/airGR/libs/airGR.so`, check packageVersion is 1.7.8, and check the registered Fortran routine `frun_gr4j` and R function `RunModel_GR4J` exist. This verifies the official compiled model loads without running it. Do not run example datasets, calibration, or any RunModel function. Do not execute the .so as an executable or substitute `Rscript --version` for the package check.

The manifest declares an explicit `r_package` contract with `library_root: workspace` and relative `library: R/library`. Older contracts without `library_root` retain their existing library location relative to the model install prefix. The installer verifier uses a fixed native package load probe for this contract. Local native verification alone is not a completed DS attempt.
