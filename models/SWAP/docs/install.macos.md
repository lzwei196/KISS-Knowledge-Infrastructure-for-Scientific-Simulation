# Native SWAP 4.2.0 installation scope

This recipe builds the exact KI repository revision
`7587ca3a5f037a7276f1c86059632f921f710775` (tag4.2.0) and native TTUTIL4.2.7
`bd8601dca3cfb449a79accddd39a566811f1a75e`. These repositories describe themselves
as unofficial convenience mirrors of Wageningen source, not official WUR releases.
WUR currently advertises4.3.0/4.3.1; these must not replace the KI's4.2.0.

Run `python3 tools/build_swap_macos.py` from the selected installation workspace
with genuine `/opt/homebrew/bin/gfortran`, Meson and Ninja available. The helper
validates each source's pinned Git blob hash, preserves originals, builds TTUTIL
locally, adapts the incompatible fully static executable link stanza, and adds the
early native version branch described below.
Its GNU legacy/free-line-length compiler flags accommodate the original Fortran.
The helper does not execute SWAP. The linked library is genuine Homebrew
libgfortran; it must remain available. Both compilation steps use one job.

A native arm64 build and startup boundary were measured successfully. The genuine
unmodified main has no help/version dispatch. It opens reruns.log, initializes
variables, enters ReadSwap, prints `running swap ....`, writes
`* Model version: Swap 4.2.0` to swap_swap.log, and rejects the absent swap.swp
before reading scientific inputs. With standard input closed, upstream fatalerr
then encounters EOF at line48, returns2, and prints a runtime backtrace. No model
inputs were created, no time-stepping routine was reached, and this is not a
successful model execution. A verifier must check this exact source-backed
boundary, emitted version log and source hashes, not broadly accept any failure.

The audited helper now adds a transparent native `--version` branch before any
files are opened or model initialization occurs. It reuses the original
`description.fi` assignment and prints `SWAP 4.2.0`, exiting0. The complete model
remains linked and all other arguments retain upstream behavior. Only this CLI
branch and the Darwin linker stanza are changed in the separate build copy;
pinned originals and Git blob hashes are preserved. `--help` is unsupported.
The corresponding source diff is `tools/macos-cli.patch`.

Independent contract: launch the genuine native binary with `--version` in an
empty directory, require exit0 and exact SWAP4.2.0 identity, reject unrelated
loader failures, and verify no files were generated. No special missing-input
failure acceptance is needed for the patched installation product.

Sources:
- https://github.com/SWAP-model/SWAP/tree/7587ca3a5f037a7276f1c86059632f921f710775
- https://github.com/SWAP-model/ttutil/tree/bd8601dca3cfb449a79accddd39a566811f1a75e
- https://swap.wur.nl/

## Observed DS installation result

DS repair 85 independently passed on 2026-09-09 in 553.6 seconds.
The engine confirmed genuine Mach-O presence, architecture, linked dependencies,
required Python imports, and `--version` exit0 with `SWAP 4.2.0`.
The retained installation-test.json reports installation_only=true, usable=true
and state=ready. This does not establish scientific execution or dataset readiness.
