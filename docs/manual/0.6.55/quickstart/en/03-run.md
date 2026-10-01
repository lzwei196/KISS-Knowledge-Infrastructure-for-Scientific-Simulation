# 3 Run, approve and check results

**Goal:** reproduce the publisher's SHAW Trial with the real model. This is a forward example check, not calibration against field observations.

## Send this request

> Run the authentic SHAW 3.03 Trial using my five uploaded original files. Preserve every scientific input and control flag. Stage the inputs in this project, run the installed native SHAW through the KI tool, export CSVs and plot the soil profiles. Do not use GeoForge Database, generate forcing or calibrate parameters. Report the actual row counts and dates; check temperature/moisture 301 each, liquid 14, energy 300, water 13 and frost 48, ending 1986-12-17 00:00.

## Review before execution

1. Answer the planning cards, one at a time. Use their buttons to save your choice.
2. On **Approve the plan?**, check SHAW only, the five authentic inputs, and executable steps for **run → parse → plot**. Confirm where the files will be written and that no calibration is proposed.
3. If anything differs, select **Modify the plan**. Otherwise select **Approve and start** and **Continue with this choice**. Approve only the exact plan shown.
4. Keep the app running. Open **◇ Project status** to see setup, execution and checking. A changed plan or tool may require a new review; a previous approval does not cover it.

## What the verified example produced

| Raw table | Rows | Check |
|---|---:|---|
| Temperature / moisture | 301 each | 11 soil nodes |
| Liquid water / energy | 14 / 300 | Complete reference period |
| Water balance / frost | 13 / 48 | Correct physical columns and units |

All six tables end at **1986-12-17 00:00**; the initial temperature/moisture profiles start at **1986-12-04 12:00**. The verified run matched the publisher's numeric values at printed precision and produced five CSVs plus a genuine plot.

**Finish check:** GeoForge must say **Completed**, with passing run records for all three steps. Open the CSVs and plot in **Results**. An AI claim of success, old files, or a warning/failed run record is not completion. Ask the agent to repair and rerun the affected approved step; do not delete your inputs.

For calibration, use **Guide → Calibration guide**. For other workflows and troubleshooting, open **Full user manual**. Both can be read offline from the same menu.
