# MONICA on Apple Silicon

The official `3.6.56.OxygenDeficit_fix` tag resolves to `84f97cb37ff5dcd6a210d40f346de7130822cad7`, reporting 3.6.56.0. Submodules are `mas_cpp_misc` dc246c4ffd1bed8886e716c4f2968ea9edb54726 and schemas 4e3d7716d591cc0bfdfcb45ac28aa0008939ea87. The generated schemas require Cap'n Proto1.2.0 exactly.

Run `python3 ../../ki/tools/build_monica_native.py .` from workspace `binaries/MONICA`. It builds genuine dependencies with vcpkg2025.10.17 (`74e6536215718009aae747d86d84b78376bf9e09`) and the `monica-run` target with two jobs. An optional workspace `monica-build-config.json` may supply `{"vcpkg_root":"/absolute/path/to/genuine/pinned/vcpkg"}` to reuse build dependencies. Dependency checkout remains validated; model executable is rebuilt from official source.

Apple libc++ exposes vector<bool> proxy references. A hash-guarded one-line compatibility repair explicitly materializes the collection value type before JSON conversion. It changes no model equations. Local native build is 6,352,920 bytes, and links only system libc++/libSystem (dependency code is static). Both upstream `--help` and `--version` exit0 in an empty directory, creating no files. These exits precede JSON inputs/simulation in `src/run/monica-run-main.cpp:103–104`. No input datasets or model run are required for installation. Independent DS testing remains pending.
