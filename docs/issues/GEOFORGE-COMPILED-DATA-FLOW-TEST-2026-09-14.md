# Compiled Mac data-flow acceptance: AquaCrop / DeepSeek

Dates: 2026-09-14–15 (Asia/Shanghai). This is a **workflow test**, not an AquaCrop simulation or a
scientific validation result. No national files, replacement/synthetic data,
model executions, Git pushes or published releases are authorized by this report.

## What the user should experience

1. **Describe the study.** Read the selected KI's actual input requirements:
   variables, units, temporal sampling, spatial footprint, warm-up, soil/terrain
   attributes and management assumptions. Do not start from a hard-coded CMFD,
   Huai or VIC recipe. Ask only about missing choices that change the study.
2. **Discover candidates.** Search the local GeoForge catalogue separately for
   each input category and KI-mentioned source. Apply spatial/date filters;
   a global product need not contain the local town's name. Show which facts
   are catalogue claims, when the cache is stale, and what has not been checked.
   A sparse lexical search is not evidence that the database lacks the input.
3. **Check the actual delivery route.** For a server subset, send the exact
   catalogue ID, WGS84 bbox, native variables and applicable start/end dates to
   the read-only estimate endpoint. Static datasets need not have dates.
   Do not infer clipping support, output bytes, file counts or coverage from
   the catalogue. A server outage is different from unsupported clipping.
4. **Review and approve.** Present the actual estimated bounds, native grid/CRS,
   variables, time span, source I/O, output size, limitations and missing inputs.
   The user selects the data and explicitly approves acquisition. An estimate
   does not create a job. Unknown coverage permits only explicit inspection
   acquisition, not a claim of complete inputs. Download permission is not
   approval to run the scientific model.
5. **Prepare the subset on the server.** Create the job only after acquisition
   approval. Track queued/running/ready/failed/cancelled/expired. Failure should
   identify the exact request and stage, with a safe retry path. Do not silently
   substitute a national file, another region or another data source.
6. **Download and inspect.** Fetch the manifest and every selected part. Verify
   sizes/hashes and actual file structure, coordinates, dates, native variables,
   units, calendar and missing values. Server response success alone is not proof
   of correct scientific data. Preserve provenance and distinguish pending checks.
7. **Connect the data to the KI.** Bind acquisition evidence to the exact approved
   inventory item and request. Run the planned KI conversion/validation tools,
   retaining each transformation. Only then determine whether model inputs are
   usable. Unresolved soil lookups, Tmin/Tmax, management or observations remain
   explicit gaps; they are not filled by invented defaults.

The protocol is shared; not every dataset uses the same processing operation.
For example, a soil class raster may need a separate attribute-table lookup,
whereas meteorological NetCDF needs spatial and temporal selection. A table
without a clipping operation should have a truthful lookup/direct/manual route,
not be forced through a raster clipper.

## Live test setup

- GUI served by the **compiled ARM64 Mac executable**, not `python -m kiss_cli`.
- Dedicated loopback test port 61823; existing installed models under the normal
  workroot. Only new test projects were used. The user's older native app was
  not terminated; temporary test servers were replaced individually by PID.
- Provider: configured **DeepSeek API / deepseek-chat**.
- KI: installed **AquaCrop**, selected as a contrast to the extensively exercised
  VIC/CaMa pair, not described as a statistically random sample.
- Goal: rainfed summer maize at an example location near Hengshui,
  115.7 E / 37.7 N, 1989. First discover and prepare small real data, max 100 MB;
  wait for data approval; no model execution, national download or fabricated data.
- Same initial user prompt was used for fresh comparisons; no prior transcript
  was copied into those new sessions.

## Failures found by testing the flow first

### Initial rebuilt app: unsupported clipping claims

Session `d3788b0aa114` read KI material, inspected the project and searched the
catalogue. It correctly asked before executing, but claimed server clipping was
available and offered 1–3 MB / 96 files **without a real clipping estimate**.
No subset estimate state had been written. These figures were not verified.

A follow-up challenged those claims and asked for real read-only estimates.
The agent explicitly retracted them and reported failed requests and a stale
catalogue. The original client exposed only the generic message
`Observation data request failed`, not the HTTP status or a retained request
card. This was a coached correction, **not** an unaided pass.

### Revised build r2: better outage reporting, incomplete search

Fresh session `12c22152af17` correctly reported HTTP 530 / stale catalogue and
did not claim it had estimated clipping. However, it performed only one visible
catalogue-search tool action, found two irrelevant statistics records, and
prematurely asked the user for data instead of separately looking up the sources
already mentioned by the KI. The exact query was not retained by the old trace;
do not assert its particular keywords from the assistant's prose.

This is an additional discovery-flow gap, not proof that the database lacks
CMFD or soil data. It motivated explicit query semantics and total-count evidence.

## Client changes made in this test batch

- `obs_access`: shared discovery rules distinguish configured tools from current
  availability; catalogue-only evidence labels live delivery/estimates unchecked.
  Search results echo filters and show both match count and catalogue count.
  Explain lexical AND matching and separate category/source searches.
- `gui`, `api`, Database KI documentation: require real read-only estimates before
  presenting clipping as verified. Do not label every configured database as
  currently available. These instructions aid reasoning; they are not a guarantee
  that arbitrary provider prose is factually correct.
- HTTP 5xx errors retain a safe status code/message without forwarding response
  bodies, credentials, private source paths or signed links.
- `obs_subset`: failed estimates persist their exact public request and safe
  failure stage/code/status in the project. They cannot be approved, even for
  inspection. Explicit retry makes only another estimate; success still needs
  user approval before job creation.
- Frontend: failed-estimate card shows the blocked stage and a retry-only button.
  It does not show approval/download buttons for that failed request.

## Verification boundaries

The database API returned **HTTP 530** on independent unauthenticated reachability
checks during the run. The app's authenticated catalogue access also reported
HTTP 530. This establishes a live service/gateway availability blocker; it does
not diagnose its internal deployment cause or prove that all dataset processors
are broken.

No successful new server job, downloaded subset, prepared AquaCrop input or model
simulation should be inferred from this test. Earlier saved-file and mock-server
tests are documented separately and are not substitutes for this live flow.

Focused client tests after the initial changes: 164 passed, one loopback bridge
test excluded from that command. With the additional sparse-query regression,
the data/estimate/contract subset is 90 passed. Shared flow suite: 79 passed,
2 skipped, with the existing NumPy/NetCDF binary-size warning. Frontend parsing,
isolated failed-card action/escaping assertions, Python compilation and diff
whitespace checks passed.

## Final r3 result: discovery/failed-estimate path exercised, end-to-end blocked

Fresh session `9d6f8374c8e0` received the same original goal, without a corrective
follow-up. It performed 21 displayed tool actions, searched multiple data
categories, and submitted **four actual read-only estimates**. The on-disk
request states, not just assistant prose, confirm them:

| Dataset ID | Requested variables | Time |
| --- | --- | --- |
| `cmfd_china_daily_010` | `lrad,prec,pres,rhum,shum,srad,temp,wind` | 1989-01-01 to 1989-12-31 |
| `soilgrids_cold_china_disk3` | `bdod,clay,phh2o,sand,silt,soc` | static; omitted |
| `hwsd_china` | empty selection (native raster) | static; omitted |
| `ggcmi_crop_calendar` | `maturity_day,planting_day` | omitted |

All used bbox `[115.6,37.6,115.8,37.8]`. All failed at the estimate stage with
`code=server_unavailable`, `http_status=530`, `eligible=false`, no job ID,
no acquisition approval and no acquisition receipt. Native variable validity
and actual coverage could not be established while the server was unavailable.

The real compiled browser UI showed all four failed requests, unknown sizes,
HTTP 530, and **only retry-estimate actions**, not approval/download buttons.
Clicking retry for CMFD increased its attempt count from 1 to 2, preserved its
exact scope and acquisition ID, and again returned HTTP 530. No job or download
was created. There were no files under the project's `inputs/` directory
(ordinary empty scaffolding directories existed).

Local evidence:

```text
/Users/leo/kiss/projects/2026-09-14-请用本机已安装的-AquaCrop-为华北平原衡水附近一个示例农田-115.7-E-37.7-N--9d6f8374c8e0/
  memory/transcript.jsonl
  runs/project-events.jsonl
  .geoforge/subsets/82c93ded3661480ba5c45e653b38dc8e.json  # HWSD
  .geoforge/subsets/d81a58e793364abf97b911ea7d8549a7.json  # CMFD, two attempts
  .geoforge/subsets/f1747face885424b9b53c310be92a9c9.json  # SoilGrids
  .geoforge/subsets/f235838b4edd48fda3aa1b2bbddaaa1b.json  # crop calendar
```

### Still not a scientific-plan pass

The final agent response still had issues that must not be hidden by the improved
delivery status:

- It excluded CMFD 3-hourly and DEM candidates using whole-product sizes even
  though a small subset might fit. Those candidates need real estimates.
- It called the 0.2-degree window “3 × 3” without a returned snapped-grid result.
- It proposed a longer 1988–1989 period than the actual 1989 estimate. Such a
  changed request needs a new estimate and review, not reuse of this evidence.
- AquaCrop's actual weather tool requires daily `MinTemp`, `MaxTemp`, precipitation
  and reference ET. A daily mean `temp` record is not proof that extrema or ET0
  are available. Any derivation/aggregation needs a valid input source and an
  explicit method, not invented daily ranges.
- `lookup_hwsd` reads both a soil raster and a separate attribute CSV; a raster
  crop alone does not establish the full soil profile. Preparation/tool portability
  and actual scientific checks were not exercised by this blocked run.

These are remaining planning/data-compatibility problems. This batch improves
the shared discovery instructions and deterministic acquisition-state UI; it
does not guarantee every provider sentence or model plan is scientifically correct.
Kimi was not rerun in this batch. After service recovery, continue through actual
estimate validation, user approval, job completion, download and KI input checks;
then repeat with another provider/model before declaring generalized success.

## Final compiled Mac artifact

```text
/Users/leo/kiss/builds/dist-data-flow-20260914-r3-v0.6.52/GeoForge Desktop.app
```

This is a local test rebuild of version 0.6.52, distinguished by its build
directory. No public version/release metadata was changed or published.

- ARM64 PyInstaller build completed successfully.
- `codesign --verify --deep --strict` passed (ad-hoc build, not a notarization claim).
- Bundled `harness-status AquaCrop`: `ready=true`, `flow_ready=true`, all nine
  declared flow modules loaded; generated harness contract length 5,965 characters.
- Executable SHA-256:
  `62c41843576a334b9d8af3124430770388598b60405fb7476075b676771f927a`.
- Final focused client regression: **165 passed, 1 deselected** (loopback bridge).
  Shared flow regression remains **79 passed, 2 skipped**.

Browser-testing guidance prompted independent new sessions and UI verification,
not merely tool-output assertions. The `agent-browser` executable was unavailable;
the existing supported browser controller was used for all UI interactions.
