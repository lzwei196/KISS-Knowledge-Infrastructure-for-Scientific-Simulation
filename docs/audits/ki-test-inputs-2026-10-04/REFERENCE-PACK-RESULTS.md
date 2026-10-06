# Three reference input packs: fresh Windows replay

Date: 2026-10-04. Local evidence; not a release or authenticated delivery result.

The [127-KI inventory](TEST-MATRIX.md) is a static declaration audit. This file
records separately executed reference cases. Three input packs were created from
retained real example files, freshly extracted and run with the existing native
Windows engines. The other 124 KIs were not executed in this round.

| KI / case | Pack inputs | Native result | Checks |
|---|---:|---|---|
| SHAW / Trial | 5 | PASS; 301 hourly records, 11 profile nodes | 22 checks; 7 output files match retained reference bytes; expected dates and finite values |
| CRHM / Bad Lake 1973 | 2 | PASS; 8,760 hourly records, 3 HRUs | 6 checks; retained output bytes match; expected dates and finite, nonnegative SWE |
| VIC / Stehekin 1949, 10 days | 21 | PASS; 16 cells, 48 output files | 211 checks; retained output bytes match; daily dates and finite values; precipitation matches summed hourly inputs |

Every engine exited zero within its 120-second limit. Inputs remained byte
identical to their retained sources. The portable runner stages only path/case
aliases: the CRHM observation reference, VIC directory placeholders, and SHAW
filename-case aliases where required. CRHM explicitly uses `TZ=UTC0`.

The ZIPs include input files, source provenance, expected member hashes, reference
output hashes, KI file hashes and a Python 3.10+ runner. They contain no native
executables or generated model outputs. The current KI revision is recorded as
context; these tests invoke the native engines directly, not the KI wrappers.

## Local artifacts

Directory: `D:/GeoForge-KI-Test-Packs-20261004/`.

| Archive | Bytes | SHA-256 |
|---|---:|---|
| `shaw-trial-303-reference.zip` | 17,037 | `9c6fbd41e7abaa096cad65a1a490275588487ff2b3e857a58f7e0e018e679d29` |
| `crhm-badlake-1973-reference.zip` | 334,001 | `4d355848239df34502a3d20e70e161a5cfd101f75479c2147bfe5340da61b17a` |
| `vic-stehekin-1949-10days-reference.zip` | 104,117 | `8f9f1b2598f64b41198611eda1506669a4b71c13e4c09b7b0a07081708b2e897` |

`index.json` records ZIP/result hashes, binary hashes, KI hashes and scope.
`runs/<case-id>/result.json` records checks and produced file hashes, alongside
the native stdout/stderr. ZIP CRCs, exact member sets and all expected bytes and
hashes were independently checked. Only a README minimum-Python correction was
made after replay; the index records verified byte identity of the executable
runner and all native inputs/case metadata across that correction.

The repository's generic offline verifier also passed all three final extracted
pack directories: 9 SHAW, 6 CRHM and 26 VIC manifest members. The remaining two
ZIP members are the manifest and its checksum list, which exclude themselves.

```sh
python tools/verify_ki_test_pack.py /path/to/extracted/pack
python /path/to/extracted/pack/run_reference.py --binary /path/to/engine --run-dir /path/to/new-run-directory
```

The first command proves expected member delivery only. It fails on missing,
changed, unlisted or nonportable members, and does not claim scientific validity.
Trust the outer ZIP/index hash before relying on a manifest. The second command
records a native reference replay and refuses an existing run directory.

## Still unverified

All three cases explicitly record `NOT_RUN` for new-site operation, authenticated
Database/Netdisk delivery, raw-data preparation, calibration and Desktop agent/UI
execution. Installation and cross-platform checks were not part of these replays.
They reproduce retained examples, not independent field-observation validation.
Byte comparison on another compiler/platform requires a justified numerical
comparison rather than silently relaxing the expected result.

No pack has been uploaded or attached to a release. Catalogue registration,
source distribution terms and the rest of the 127 case packs remain work items.
