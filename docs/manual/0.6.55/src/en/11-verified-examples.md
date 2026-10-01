# 11 Verified Windows examples and current behaviour

The earlier FSM2 walkthrough shows real 0.6.54 screens and remains useful for learning the detailed workflow. This chapter records the additional 0.6.55 checks and directs new users to a short, reproducible SHAW case.

## Reproduce SHAW without a private data source

Open **Guide → Quickstart · 3 pages**. It covers AI setup, software setup and the full approved run. The official input download is [USDA-ARS Shaw303.zip](https://www.ars.usda.gov/ARSUserFiles/20520500/SHAW/303/Shaw303.zip). The five original files are directly inside its `Shaw303/` folder:

`Trial.303.inp`, `Trial.30.sit`, `Trial.30.wea`, `Trial.moi`, `Trial.tem`.

Upload these five inputs to a fresh SHAW chat. Do not upload precomputed files from `Shaw303/Output/Trial/` as if they were new model results. That folder contains the publisher's references for comparison. Keep inputs and reference output clearly separate.

Request genuine native execution through the KI, CSV parsing and plotting, with all original control choices preserved. Review the plan and approve the three executable steps. After running, inspect **Project status**, the raw tables, five CSVs and profile figure. A model's software-verification badge alone does not establish a completed scientific run.

## What was checked

| Model / official case | Real output checked | Acceptance |
|---|---|---|
| SHAW 3.03 / Trial | Six tables: temperature 301 rows, moisture 301, liquid 14, energy 300, water 13, frost 48; 11 profile nodes; all end 1986-12-17 00:00 | Printed values matched the official reference; five CSVs and the plot checked; all three Desktop steps completed with passing signed records |
| VIC 5.1.0 / Stehekin | 16 cells × ten days, 1949-01-01 to 1949-01-10; 48 flux/snow/snowband files | Original forcing/parameters preserved, finite output and precipitation aggregation checked; Desktop Completed |
| CRHM / Bad Lake | 8,760 hourly records, 1973-01-01 01:00 to 1974-01-01 00:00; three HRU SWE series | Original parameters/forcing preserved; raw result matched independent native run; Desktop Completed |

CRHM peak SWE was 36.38742, 65.86527 and 64.42825 mm for the three HRUs. The native executable reported `4.7_16`; an older manifest's `1.3.5` label is not evidence of the executable version. Executable identity was recorded independently.

These are official forward examples, not calibration or validation against field observations. Installs needed assistance: the first CRHM setup was blocked by acquisition/build work, VIC's first Windows build crashed on actual input, and SHAW needed runtime/dependency/path repairs. The failed attempts were preserved. Later successful results do not rewrite that history or promise unattended installation on every PC.

## Repairs that matter when using the app

- **Startup:** Windows loader/crash exits cannot pass merely because a file or banner exists. Preflight checks the configured interpreter and genuine executable.
- **SHAW:** managed binaries, all four compiler DLLs and matplotlib are checked. The wrapper stages original uploaded inputs, retains PEST/control settings and handles an authorized overwrite using the native model's own prompt. Every enabled output must still be fresh and complete.
- **VIC:** the Windows configuration cursor/newline and error-reporting repairs were reproduced on final 5.1.0; LF and CRLF inputs produce identical results. The phrase “classic driver” no longer selects the unrelated CLASSIC KI.
- **CRHM:** `TZ=UTC0` is applied only to the model process so host timezone does not change model civil-time calculations and SWE. It does not convert a station's geographical timezone. Merely shifting old output labels cannot fix a timezone-affected simulation.
- **Review:** materialized tools are checked against the selected project; generated output paths are not described as existing inputs. Tool or plan changes can invalidate an old approval.
- **Evidence:** named stdout/stderr diagnostic logs remain hashed evidence without being parsed as numeric output. Real scientific files still undergo numeric/completeness checks. Failed, stale or unrecorded results cannot be made successful by the AI's summary.

The fresh SHAW project reached **Completed** with three passing steps and no missing, stale, rejected or unrecorded outputs. Its older unsuccessful conversation was retained. If your project has a long history of incompatible plan changes, preserve it and use a fresh project with the same authentic inputs and a newly reviewed plan.

For parameter fitting and the separately tested native SHAW reference-recovery benchmark, read Chapter 10 or **Guide → Calibration guide**.
