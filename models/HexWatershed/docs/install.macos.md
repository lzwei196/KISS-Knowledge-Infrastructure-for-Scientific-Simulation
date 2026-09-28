# HexWatershed: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://github.com/pnnl/hexwatershed.git
Windows recipe source ref: `e96ef94547b19d2a6d7949a6c735c7ed4750a6f2`

Keep the official PNNL repository; do not replace it with a separate fork or Python wrapper. Inspect CMake for site-local /share/apps/gdal/2.3.1 and libgdal.so paths. Adapt build discovery to a real native Mac GDAL SDK and netCDF C++ headers, preserving the compiler/library ABI. Install pyflowline and all declared Python imports with resolved dependencies. Do not copy Windows MSYS2 runtime packages.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.
