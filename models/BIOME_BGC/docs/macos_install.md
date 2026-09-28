# Biome-BGC4.2 native Mac installation

The [NTSG project page](https://www.umt.edu/numerical-terradynamic-simulation-group/project/biome-bgc.php) links [bpbond/Biome-BGC](https://github.com/bpbond/Biome-BGC) as its source repository. Pin `f80d386d6d79ffe73dba46c28d15b40ee877d67b`, the original4.2 source commit, rather than a different Biome-BGCMuSo variant. Preserve the upstream copyright notice. Only software source is selected; example meteorology, parameters and cases are excluded.

From `binaries/biome-bgc/bgc-src`, run `python3 ../../../ki/tools/build_biome_native.py .`. The helper uses the real Apple C compiler, upstream makefiles and serial compilation, with explicit ROOTDIR to avoid inherited working-directory errors. It applies no numerical source changes and produces the native ARM64 `bgc` executable. The upstream all target also compiles companion utilities; never run its test target because that executes simulations.

Use `bgc -V` in an empty temporary directory with a bounded timeout. The source's option handler prints `BiomeBGC version 4.2` and exits0 before opening any initialization or meteorology files. Python interpreter availability, wrapper scripts and unsuccessful version probes do not establish installation. The local native audit passed with no files created; a fresh DS installation verification is still required. Scientific validation remains separate.
