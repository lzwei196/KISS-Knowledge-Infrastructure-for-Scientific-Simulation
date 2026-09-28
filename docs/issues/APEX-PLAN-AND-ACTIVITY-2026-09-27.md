# Harbin APEX: activity display and plan/data-choice audit

Date: 2026-09-27. C1–C4 source checkpoint `bdf2522e` was pushed to `origin/mac-version` before this follow-up. No new release or push to main.

## 1. Activity: reproduced and fixed in source, not the running app

The screenshot showed Claude's `geoforge-db "soil attribute table" --limit 10` next to a turn duration of 8m40s. That did not establish an eight-minute database request.

Read-only checks of session `0b38494ab17c` found it had advanced to writing the data inventory. Claude was alive; no child process was observed at that inspection. Exact request latency cannot be reconstructed from the old activity state. The project was still in PLANNING, with no evidence of model execution or downloaded inputs.

Two independent reproductions:

- Shipped JavaScript: after the initial agent reply, status polling did not put updated activity in the chat itself. The first two renderer regressions failed.
- Actual `providers.run` with fixture subprocess events: a Claude `tool_use` followed by its matching `tool_result` left the tool labeled active. The event timestamp was also refreshed by non-work events.

The follow-up changes:

- Claude tool starts/results are associated by call ID; parallel pending calls remain tracked. Returning a tool is not a scientific-success claim.
- Meaningful work has its own timestamp, separate from heartbeat/usage chatter. Unknown CLI lifecycle shapes remain observations rather than invented completion; Codex's text-only route stays text-only.
- The status response adds action state, action duration, last safe action summary, work silence and whether any work event has actually been observed.
- A status card stays visible above the active agent reply, including after narration has started. Turn duration and observed tool duration are separate. Old/unknown actions are labeled as observations.
- Poll age continues advancing if a status refresh fails. Disclosure nodes remain stable across timer ticks, preserving keyboard focus/open state; only the heading is a live announcement region.
- No automatic retries, new execution limits, approvals, process stops or model-policy changes were added.

Verification checkpoints: 839 tests and 121 subtests passed in the broad run, with five server-reference skips and the pre-existing native-extension warning. Two further startup/first-event regressions were then added, observed failing, and fixed; the final focused lifecycle/renderer files passed 27 tests and two subtests. The broad run therefore predates those last two safeguards, not a claim of a single final frozen-tree run.

After the final safeguards, the combined activity lifecycle, activity renderer, project-status renderer and runtime suite passed **206 tests and two subtests**. `git diff --check` also passed.

All activity tests use local fixtures. The already-running compiled app was not patched, stopped or restarted. These follow-up source changes are not included in the earlier compiled ZIP or pushed checkpoint.

## 2. CMFD is present; the final plan and review disagree

Scope: read-only audit of the same session's saved plan, inventory, issued card, subset estimates and relevant Claude tool-result records. No approval, new provider call, download or project mutation.

Project: `/Users/leo/kiss/projects/2026-09-27-模拟哈尔滨地区玉米生长--0b38494ab17c`.

### Real discovery and estimate evidence

The agent searched, described and estimated both CMFD records. These facts came from actual tool results, not only assistant narration.

| Record | Native fields exposed by describe | Saved estimate |
|---|---|---|
| `cmfd_china_daily_010` | `lrad, prec, pres, rhum, shum, srad, temp, wind` | 16,702,400 bytes; complete for requested `prec, rhum, srad, temp, wind`; eligible |
| `cmfd_china_3hr_010` | `prec, pres, temp, wind` | 106,895,360 bytes; incomplete; requested `rhum` and `srad` missing for every requested year |

Both estimates use 1995-01-01 through 2020-12-31 and bbox `[125.8, 45.2, 127.4, 46.3]`. The final inventory instead asks for 1991-01-01 through 2016-12-31 and bbox `[126.7, 45.7, 126.8, 45.8]`, around the representative point. The earlier estimate is evidence of availability for its own request, not approval-ready evidence for the final changed request.

The describe results report `source_file_schema`, `CMFD_V0200`, `obs_subset/3`, and `coverage_scope: inspected_sample_files`. No explicit Tmax/Tmin fields were returned. The returned metadata does not itself establish `temp`'s daily aggregation method. Whether missing three-hour radiation/humidity reflects missing files, indexing or routing remains a server-side inspection question. Combining three-hour temperature with daily variables was not assessed; feasibility must not be assumed.

Relevant saved estimates:

- `.geoforge/subsets/30fcc511fa58434c9e0b3559c1ccc315.json` (daily).
- `.geoforge/subsets/0586fecd06274a7093075b7b150ce4fb.json` (three-hour).

### Confirmed representation defects

1. Both `scientific_choices[data:precipitation]` and `[data:air_temperature_max]` set `picked=forcing_provider:nasa_power`, but their offered options contain only the two CMFD IDs. The inventory also chooses NASA. A bounded read-only check that selected values belong to offered options fails.
2. `plan_review._data_choices` builds options only from catalogue IDs. NASA's provider ID is not represented. The issued forcing baseline is empty rather than the narrated NASA default. Several non-data picks also differ from their full option strings (site/scale, period, NGN, elevation, CO2).
3. The card uses catalogue delivery and whole-product sizes: approximately 225.57 GB daily / 604.56 GB three-hour CMFD, marked manual. It does not join the project-scoped subset offer. It must not relabel the 16.7 MB *old-scope* offer as current; it should explain that re-estimation is needed.
4. HWSD had a 50,688-byte clip estimate, but no coverage-completeness evidence. Desktop labeled it `coverage_unknown_inspection_only`. That is an unresolved suitability/evidence issue, not proof that a full 1.87 GB global download is the only possible route.

Sources: `runs/plan.json`, `runs/data-inventory.json`, `runs/plan-review.json`, `setup-request.json`; Desktop `kiss/kiss_cli/plan_review.py`; shared `flow/plan.py` validates choice shape but does not enforce selected-option membership before display.

### What is not necessarily wrong in the science configuration

The APEX KI explicitly documents the v0806 binding and template spin-up. `tools/s5_update_control.py` defines `NGN_READ_ALL=2345`; this supports the plan's read-all selection. These details should not be rejected simply because the presentation is technical.

There is nevertheless a KI documentation conflict worth a separate correction: `dag.yaml` says NGN=0 reads all, while the actual S5 tool warns it generates weather for v0806. The current plan followed the tool's 2345 setting. This audit did not change the KI.

### Required next correction (not implemented by this read-only plan audit)

Validate that plan, selected source and offered choices agree before issuing a review. Represent supported external forcing providers explicitly, rather than silently dropping them. Show project-specific delivery/size/coverage when scope matches; otherwise require fresh estimates. Explain missing variables versus missing datasets distinctly. Ask for user choices in plain language, keeping model codes in details. Do not auto-approve or silently switch the live session's forcing source.

## 3. Old/new comparison requested by the user

Question: did the C1–C4 architecture improvements remove or break the previously available CMFD cut service?

**Finding: no clipping regression reproduced; the plan/card defects above reproduce in both versions.** This is not a claim that the current end-to-end data experience is correct, or that the live server has been retested today.

### Compared versions

- Previous source: `96ac8a5b06581cb70a31b40ba4edc7d961addbad`.
- Pushed C1–C4 source: `bdf2522e374dd9092500ae17f28f597abfd9127a`.
- Older compiled artifact: `/Users/leo/kiss/builds/dist-flow-rework-v0.6.52/GeoForge Desktop.app` (September 19 executable). No previous v0.6.54 artifact was found under the builds directory.
- Current compiled artifact: `/Users/leo/kiss/builds/dist-architecture-c4-v0.6.54-20260927/GeoForge Desktop.app`.

Read-only extraction of the compiled Python code, without launching either app, confirmed that `obs_access` and `data_contract` are unchanged. Of 33 functions in `obs_subset`, only `bind_approved` differs: existing download receipts now go through shared reuse inspection. Estimate, request construction, clipping preference, inventory refresh, approval, advancement and download remain unchanged. Old compiled `flowrun._data_choices` and new compiled `plan_review._data_choices` are equivalent; the entire compiled `renderPlanReview` function is byte-identical.

### Differential tests

Command, run against each source tree:

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib -q kiss/tests/test_obs_subset.py kiss/tests/test_flowrun.py -k 'test_obs_subset or clip or acquisition or manual_card'
```

Results: previous **46 passed, 82 deselected** (7.88 s); current **46 passed, 82 deselected** (7.93 s). These use isolated fixtures, not the live data service.

An additional offline replay of the actual saved Harbin request scopes gives identical old/new results:

1. The matching 1995–2020 request attaches the eligible 16,702,400-byte CMFD estimate as `delivery=subset`.
2. Attempting to attach that offer to the changed 1991–2016/smaller-area requirement rejects the scope mismatch.
3. `prefer_clip` for the changed requirement issues a new estimate request and remains a subset acquisition with an eligible fixture response. The fixture does not establish the real size or live eligibility of the new request.

Replay: `/tmp/geoforge-cmfd-previous.2FwAc6/replay_cmfd.py`, with the source root as its argument. The isolated previous source archive is in the same temporary directory.

### Failing reproduction of the real plan/card inconsistency

```sh
python3 /tmp/geoforge-cmfd-previous.2FwAc6/replay_review.py --check-consistent
```

This reads the saved plan/inventory and local catalogue without refreshing, issuing a review or approving anything. Both old and current actual choice functions receive the same inputs. Results:

```text
old_new_rows_equal: true
old_new_baseline_equal: true
data:precipitation: picked=forcing_provider:nasa_power; picked_is_offered=false; displayed_default=""
data:air_temperature_max: picked=forcing_provider:nasa_power; picked_is_offered=false; displayed_default=""
CMFD daily option: manual, 225.57 GB
CMFD three-hour option: manual, 604.56 GB
AssertionError: PLAN/CARD BUG: the selected source cannot be selected in the card (both versions)
```

A minimal one-choice replay also confirms that attaching eligible subset metadata to an inventory item does not change `_data_choices`' catalogue-wide candidate label. Repeating the replay produced the same output. Existing green clipping tests cover selected inventory acquisition but miss this candidate-option/prose/selection inconsistency.

### Meaning for this session

CMFD was not absent. The agent's recorded reason for preferring NASA was the variable combination needed by its APEX plan, not a disabled cut service. This reason is agent reasoning, not an independently verified claim that NASA is the only viable source: the returned daily schema does not establish the aggregation of `temp`, and combining suitable CMFD products was not assessed. The three-hour estimate reported incomplete requested variable coverage; whether the cause is underlying files or server indexing/routing remains open.

The Desktop must reconcile chosen source, offered alternatives, request scope, estimated delivery and displayed plan before asking the user to approve. Rolling back C1–C4 would not remove the reproduced card defects. No production code, live project, approval, provider process or download was changed in this comparison. Only this diagnostic report and isolated temporary replay scripts were added/updated.
