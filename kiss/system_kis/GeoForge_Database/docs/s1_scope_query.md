# Stage 1 — Scope the catalogue query

Extract only facts the user supplied: study area or gauge, variable, time
period, product family, and model requirements. Start with the most selective
combination, such as `Bengbu 51080 discharge` or `CMFD Huai River 2001 2020`.
Do not turn a missing fact into a fabricated value. If one missing choice would
materially change the dataset, ask one concise question before planning.

Success means the query terms are traceable to the user's goal. This stage does
not access files, download data, or decide that a record is suitable.

For model forcing, establish the simulation grid cells or grid extent first.
Query with that bbox plus the required variables and time period, and inspect
the returned coverage and actual delivery unit. A geographic name is only a
discovery hint. Bbox filtering does not crop data or create a per-grid link.
Prefer matching spatial tiles or a verified clipping endpoint when available.
Catalogue matches, even fresh ones, are not evidence of current clipping capability.
Before saying a candidate can be clipped or asking to approve its download, obtain
an exact read-only estimate. Output bytes and part counts must come from that
response, never from catalogue size or a filename pattern. A failed estimate is
recorded in Project status with the request, failure stage and retry action; it
creates no job. Server outages are not proof that clipping is unsupported or
that the user must download a national package. Retry only the estimate first;
successful retry still requires acquisition approval.
Before selecting subset variables, read the actual source schema:

```text
geoforge-db --describe crop_calendar_global
```

API agents use `search_observation_data(describe_dataset_id="crop_calendar_global")`.
This authenticated read-only call returns real field names, units, dimensions,
per-file member information and the server's source version. It does not download,
create a job, or prove data quality. The Desktop re-fetches it on every describe
call; it does not substitute stale catalogue labels for source metadata.

For example, this source uses `plant`, `harvest` and `tot.days`, not the catalogue
labels `planting_day`, `harvest_day` and `growing_season_length`. This is an example,
not a universal alias map: use the response for the actual selected dataset.
Read file/member information as well: a variable selection currently includes all
matching crop files, not one chosen crop. Explain that scope before approval.
Raster band descriptions do not imply that the server accepts a band selector;
follow `select_by` and the returned notes. Coverage from inspected headers is not
necessarily complete product coverage; estimate the requested period separately.
If the meaning is unclear, ask the user; do not guess, silently convert units, or
drop a variable filter. HTTP 400 `unknown_variable` requires another describe and
a corrected request, not repeated retries or an empty list to bypass the error.

The Desktop bridge supports native-grid subset estimates:

```text
geoforge-db --subset cmfd_china_daily_010 --variable prec,temp --start 1989-01-01 --end 1990-12-31 --bbox 115,37,117,39
```

Run this from the registered chat project. API agents use `estimate_clip`.
This ONLY estimates and saves an exploration record; it creates no job and no
popup. Then write the plan: give the data-inventory item the dataset_id and the
same bbox/period/variables in `requirements` (or the returned acquisition_id).
Desktop joins the item to the estimate, shows the clip size on the approval card,
and starts the server job when the user approves the plan.
Only selected requests appear in the main approval card. Exploration records
remain in collapsed history, without approval buttons.

Ask the user to review the project's selected sources, output size, exact bounds
and missing coverage in that card. Only the user's approval creates a server job;
the user can then download all parts with checksum verification. Do not call
these browser-only actions from shell or manufacture approval state files.
The subset card is a data-acquisition approval, NOT approval to run the model.
Put the returned estimate `id` in the matching inventory item's `acquisition_id`,
with the exact `dataset_id` and `requirements` (bbox, variables, start/end).
One logical input may acquire many files; do not invent catalogue child IDs.
Desktop records the request fingerprint before plan review. After acquisition
and plan approval, it automatically attaches signed file receipts to that item
without changing the approved inventory. This also works when acquisition
happened before planning. An incompatible request or changed file is rejected.

If coverage is unknown, the user may explicitly choose **acquire for inspection**
in Project status. This does not assert complete coverage; empty, over-budget,
known-incomplete and unsupported requests remain blocked.
After approval, use `download_observation_data` (CLI `obs-download`) with the
selected dataset and inventory item to poll/advance the subset. Queued/running
is a status response, not a download receipt. Both API and CLI use the same
Desktop acquisition implementation. Do not make a separate shell download.

After download, inspect the recorded files and signed evidence; check units,
time/calendar, coordinates, missing values and model requirements, and execute
the KI's planned input-preparation/validation tools. **Acquired is not model-ready.**
Never manufacture a catalogue child ID for a subset or treat the existence of
the subset receipt as a successful simulation. An unsupported/incomplete estimate
does not authorize a fallback download; discuss an alternative delivery first.
If the backend only offers a larger basin/national package, explicitly disclose
its extent, download size and local extraction needs and obtain the user's
choice; never silently select a Huai package for a single-grid simulation.

For national CMFD, resolve actual delivery units through the same Desktop bridge:

```text
search_catalogue.py --resolve cmfd_china_daily_010 --variable prec,temp --start 1989-01-01 --end 1990-12-31 --time-step daily --bbox 115,37,117,39
```

This is a diagnostic example, not a complete VIC forcing specification. Use only
returned `items[].id` values. Record each child in the data inventory, with its
own variable/year requirements, and include all files needed for the simulation
and warmup. `coverage_complete:null` is unknown; false or spatial noncoverage
requires revising the request. `spatial_filter_applied:false` means the actual
download is not clipped. Show delivery extent and bytes before user approval.
Links and extraction codes are requested only after approval and remain in the
Desktop user handoff, never agent context.
