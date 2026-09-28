# PHREEQC native Mac installation

Use the official USGS batch source `phreeqc-3.8.6-17100.tar.gz`, SHA256
`b5c4a6dfea1a6bb6a3436857a50346bb943904a49582714494b4f1b1e54e64e1`.
This is the full PHREEQC engine, not an IPhreeqc library or Python substitute.

From the installation workspace, run:

```sh
python3 ki/tools/build_phreeqc_macos.py
```

The helper requires genuine CMake, clang/clang++ and curl. It extracts software
and distributed database resources, verifies the original source hashes, and
builds the actual `phreeqc` target with one compiler job. It excludes example
cases and documentation PDFs. Source backups and before/after hashes remain in
the installation tree. Its optional `--archive` argument accepts only the same
SHA256-verified official archive.

The original CLI interprets `--version` as an input filename and repeatedly
prompts even with stdin closed. A previous timed-out probe was incorrectly
classified as installed; that result has been corrected and preserved in the
test audit. A running input loop is not installation readiness.

The transparent CLI change checks `--version` after constructing the genuine
engine object, calls its existing `write_banner()` method, and returns before
`main_method()` processes inputs. It neither replaces the engine nor changes
its scientific calculations. The original banner supplies version `3.8.6`.
The only other change omits documentation/example CMake subdirectories from
this software-only build. Regression tests and simulations are disabled.

Verify the full native executable at
`binaries/PHREEQC/source/phreeqc-3.8.6-17100/build/phreeqc` with `--version` from
an empty directory and closed stdin. Require exit0, the `PHREEQC-3.8.6` banner,
and no new files. Native library linkage must resolve. Preserve the distributed
database directory for future user-supplied science runs, but do not run those
cases during installation.
