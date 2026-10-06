# Uploaded SHAW and CRHM reference cases — Windows test result

Follow-up: real DeepSeek/approved Flow runs are now recorded in [the agent reference-case report](SHAW-CRHM-AGENT-REFERENCE-TESTS-2026-10-04.md). The scope and outstanding agent-run statements below describe the earlier direct-native test round.

Both newly uploaded reference cases pass with the local portability fixes described below. Native executables were run on Windows, first against the exact published cases, then through dedicated KI tools after GeoForge materialised the cases. This establishes reference-case execution, not new-site Database delivery or a DeepSeek/approved Flow run.

Source: KISS main commit `cfdb57c16d1f14fc84dd97b6da92b6f83991673d`, containing SHAW upload `05e9caede133b192b510812e6f4a28ae62a1a62b` and CRHM upload `7984fdf2c1683390ccb3b00b18725a25835d0abe`. Shared tools came from that same snapshot. The raw published snapshot is retained separately from the candidate with local fixes.

| Case | Exact uploaded runner on Windows | Fixed, GeoForge-materialised run |
| --- | --- | --- |
| SHAW 3.0.3 Trial, December 1986 | Exit 2: only the diagnostic `out.out` line count differed (601 versus 599). Native execution and all four scientific spot checks succeeded. | PASS. Both soil profiles have 301 hourly rows and 11 nodes; water, frost/snow and energy tables have the expected timestamps, column counts and finite values. Final ET 4.0 mm, water-balance error 0.0 mm, snow depth 4.5 cm, SWE 9.2 mm. |
| CRHM Bad Lake, January 1973–January 1976 | Exit 2: inheriting the Windows China timezone shifted output timestamps eight hours early. The complete output scan also found 61 non-finite values. | PASS with `TZ=UTC0` on the engine child only. All 26,280 hourly rows, 272 fields per row and 7,121,880 numeric values are structurally valid and finite. Final basinflow(1) is 0.07 and basingw(1) is 0.04638228. |

The seven input files and their manifests match the uploaded bytes. The original numeric targets and tolerances are unchanged. SHAW's six native output files are byte-identical before and after its runner fix. CRHM's fixed output is byte-identical to rerunning the original runner with `TZ=UTC0`; its SHA-256 differs from the recorded Linux output, so full cross-platform numerical equivalence has not been established.

## Fixes retained locally

- Preserve all `test_cases/**` bytes in Git checkouts and GeoForge materialisation. Text-mode copying and Windows Git newline conversion otherwise invalidate published checksums.
- Require input checksums before launching the engine, explicit executable selection, successful native completion, complete output checks, and retained result receipts. Deliberately corrupted scientific outputs now fail even when the final spot checks still pass.
- Treat SHAW's human-readable diagnostic line count as informational. Scientific table counts and numeric tolerances remain required.
- Set CRHM's reference-run child clock to `TZ=UTC0`; do not modify forcing times or the host timezone. This convention applies to reproducing this case, not to every forcing dataset.
- Add `tools/run_reference_case.py` to each KI. These wrappers run only their fixed shipped case, preserving the existing Flow tool policy rather than widening it to arbitrary scripts.
- Remove hardcoded server executable locations from the new SHAW, CRHM and BIOME_BGC case metadata/runners. BIOME_BGC's engine was not tested in this round; the small path fix removes a whole-library validation blocker.

## GeoForge integration

The source test GUI is available at [localhost:8791](http://127.0.0.1:8791/library), using `D:/GeoForge-KI-Prepared-Inputs-20261004` and the candidate library under `D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/library-fixed`. All 127 KIs load. Package validation reports zero blocking findings and 422 warnings; this does not mean all 127 models were executed.

Actual `port.materialise` and `setup.prepare_common` calls created independent SHAW and CRHM projects. Every reference-case file remained byte-identical, no unresolved or corrupted materialisation entries were found, and child import probes confirmed the updated `load_forcing`, `soil_utils` and `terrain` modules. Both materialised reference-tool wrappers then ran the real native executables and returned PASS.

The existing frozen Desktop updater remains a separate gap: it updates KIs/manifests but not paired shared tools, and the main-branch snapshot lacks 150 Windows guidance files required by the installed Windows bundle. This test used an explicitly staged complete snapshot plus those missing Windows guidance files. It does not claim that the normal updater successfully installed this version. Existing released GUI instances and the published release were left unchanged.

## Evidence and reproduction

Focused regression tests: 40 reference runner/wrapper tests and 14 Desktop materialisation/safety tests passed (54 total). Synthetic failure fixtures test validation behavior only; the two native PASS results above come from the authentic uploaded inputs. Independent mutations of actual early SHAW water/energy and CRHM basinflow values also correctly failed validation.

- [SHAW native result](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/Desktop-integration/SHAW-native/test-result.json)
- [CRHM native result](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/Desktop-integration/CRHM-native/test-result.json)
- [Materialisation and shared-module receipts](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/Desktop-integration/materialised/desktop-materialisation-evidence.json)
- [Independent corruption review](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/Desktop-integration/final-review.json)
- [Source and candidate manifest](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/fixed-library-manifest.json)
- [Plots and source hashes](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/artifacts/figure-source.json)

From a materialised KI directory, run either wrapper with an existing native executable and a new output directory:

```text
python tools/run_reference_case.py --binary /path/to/model-executable --output-dir /path/to/new-run
```

The retained directory contains the native outputs, logs and `test-result.json`. Input or scientific-result failures must not be repaired by changing expected values to match the run.

Follow-up acceptance still needed: new-site raw/prepared Database data, actual agent approval/execution, fresh installation through DeepSeek, VIC in this upload round, and calibration. A published Windows release needs the updater/shared-tool integration and its own release checks; these local tests do not certify one.

![Native reference results](D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/artifacts/reference-case-overview.png)
