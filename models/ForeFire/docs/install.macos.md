# ForeFire native macOS installation

Build official firefront commit `0c0fa267fa0e6c0041c5802d3a92a2c3ceaae27a`, which reports version 2.5.0. The KI metadata's descriptive binding version is not a Git branch. The Apple Silicon manifest pins the source and declares the real native product at `binaries/ForeFire/source/repo/bin/forefire`.

Both NetCDF C and C++4 are required. CMake configuration was independently verified using `/opt/homebrew/opt/netcdf` and `/opt/homebrew/opt/netcdf-cxx` (the latter is genuine Homebrew 4.3.1_3). The upstream CMake detects `ncFile.h`, `libnetcdf-cxx4.dylib`, and `libnetcdf.dylib`. Do not fabricate Linux `.so` aliases or overwrite the C++ umbrella header with `netcdf.h`. Preserve the built sibling `lib/libforefireL.dylib` and its linkage.

This recipe builds the standalone serial engine. Disable optional MPI coupling, ANN helper, architecture-specific optimization, and LFS example-data checking with the upstream options shown in the manifest. These do not change model physics or the native product. Native verification uses `forefire -v` in an empty directory, plus actual imports of numpy, netCDF4, pyproj, scipy, fiona, shapely, ki_tools_common.load_forcing, lxml, and matplotlib. Do not run simulations or acquire scientific inputs. The legacy preflight's Linux library filename is not the macOS installation contract; the real native executable and macOS linkage must load.

The pinned source also compiled successfully with the two-job native target. An empty-directory `bin/forefire -v` probe returned exit 0 and `v2.5.0`; otool recorded its genuine dylib linkage. This local build audit does not count as a DeepSeek installation attempt.
