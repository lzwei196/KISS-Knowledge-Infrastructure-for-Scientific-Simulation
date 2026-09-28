# Native SHAW 3.03 installation on Apple Silicon

The [official USDA distribution page](https://www.ars.usda.gov/pacific-west-area/boise-id/northwest-watershed-research-center/docs/shaw-model/) publicly links `Shaw303.zip`. No registration or license submission is needed to retrieve this archive. The standard Fortran source member is `Shaw303/Code+Debug/Shaw303.for`; do not select the separate CO2 beta version or Windows executable.

The full 14,071,821-byte ZIP may download at only 10–20 KB/s. `tools/fetch_shaw_build_source.py` retrieves only its audited source member by HTTP Range, checks the exact member name and source SHA256, and stops if the archive changes. Run it from the installation workspace using the configured Python, with `binaries/shaw/Shaw303.for` as its argument. The source hash is `b10bb45c984d7f9c1831f722fcd5a27f1d091ff08da4b6d838d2bcd51066a1fe`. This is a source-member hash, not a whole-archive hash. No scientific datasets are extracted.

Compile the unmodified genuine source:

```sh
gfortran -std=legacy -ffixed-line-length-none -fallow-argument-mismatch -O2 binaries/shaw/Shaw303.for -o binaries/shaw/shaw303
```

A local native compile on 2026-09-08 succeeded. A bounded `--version` startup in an empty directory with closed stdin displayed the SHAW Version 3.0.3 banner, then returned 2 with a Fortran EOF at source line 1557, `READ (5,100) IFILE`. The program ignores command arguments and asks for the input/output filename list. This confirms native loading and reaching the initial input prompt only; it does not validate a scientific run. Preserve this receipt for the verifier rather than inventing inputs, changing return codes, or patching the source to accept `--version`. Fresh DeepSeek installation verification is still required.
