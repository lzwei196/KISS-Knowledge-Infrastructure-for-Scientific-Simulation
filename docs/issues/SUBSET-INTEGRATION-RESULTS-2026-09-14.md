# Server-side subset integration — first tested implementation

## What changed

- `kiss/kiss_cli/obs_subset.py`: project-scoped estimate, explicit approval,
  job status/cancellation, bounded all-parts download and SHA-256 verification.
- `obs_access.Client`: authenticated JSON POST support, reusing the app's token
  and proxy configuration. No credential is sent to the model.
- `gui.py`, `web/app.html`: Project status → Server-side data subsets. The UI
  shows requested/output bounds, variable/year scope, output bytes versus source
  I/O, pending approval, server progress, ready/download states and failures.
- API `search_observation_data` gains `subset_request`; the Kimi/CLI database
  helper gains `--subset`. Both can estimate only, not approve a server job.
- Database KI instructions explain acquisition approval versus scientific-plan
  approval, and require explicit subsequent input validation and plan binding.

## Flow and boundaries

Estimate → user approves exact request → server job → status polling → download
all parts → size/hash checks → publish project input directory → scientific
validation still pending.

Requests are native-grid only in this first Desktop integration. Estimates older
than 15 minutes, incomplete/unknown coverage, transformations, missing units of
delivery, or outputs over 2 GiB are not auto-eligible. Actual output has a bounded
estimate-overrun allowance. No partial files are published as inputs. File names,
part indices, manifest job/dataset identity, counts and totals are checked; CMFD
variable/year pairs and bounds must agree with the estimate. A model run is not
authorized by this separate acquisition approval.

Unsupported estimates stay in review and retain the existing catalogue/manual
delivery route. HTTP failure is not disguised as “manual data available”.

## Live evidence

Date: 2026-09-14. Endpoint: `https://app.geoforgehhu.com/api/obs`.

CMFD request: `cmfd_china_daily_010`, bbox `[115,37,117,39]`, daily prec/temp,
1989-01-01 through 1990-12-31.

- Estimate: 4 parts, 1,168,000 output bytes; 1,635,387,306 source I/O bytes.
- Job: `06826e5782dd4e45`, ready. An identical request reused the ready job.
- Actual download: **1,085,656 bytes**, 4 NetCDF files, all SHA-256 checks passed.
- Files opened with netCDF4: each 365 × 20 × 20 (time/lat/lon); respective years
  1989 and 1990, Jan 1 through Dec 31. Daily timestamps are 10:30.
- Actual file units: prec `kg m-2 s-1`, temp `K`.
- The source UI was tested with real form inputs, approval click, automatic status
  polling and download click. Final visible status: integrity verified, scientific
  checks pending. Browser error log empty at that checkpoint.
- GUI project: `output/subset-gui-test/projects/2026-09-14-new-session--f3411c54a9cb`.
- Independent client test files: `output/subset-live-2026-09-14/inputs/geoforge_subsets/926ebaef5efc4029946b48a1c0532f27`.

These were direct client and GUI integration tests, NOT fresh DeepSeek/Kimi model
turns. Agent-facing interfaces are implemented but provider-driven progression
through this new subset flow still needs a live test. No VIC/CaMa simulation,
calibration, full-forcing preparation or cell-by-cell comparison to national
source files was performed.

## Additional backend probes

For bbox `[115,37,115.1,37.1]`:

| Dataset | Result |
| --- | --- |
| `china_dem_90m` | subsettable raster; estimate 30,752 bytes |
| `hwsd_global` | subsettable categorical raster; estimate 288 bytes |
| `avhrr_landcover` | subsettable categorical raster; estimate 200 bytes |
| `hwsd_china` | **HTTP 500** from estimate |

Raster estimates omit `coverage_complete` / `missing`. Desktop conservatively
leaves them in review; it does not infer full coverage from a successful crop.
Backend should provide full-source coverage, clipping/intersection semantics and
the same explicit coverage indicators as CMFD. For `hwsd_china`, return the
documented non-subsettable/manual response if unsupported, or fix the source
reader; HTTP 500 currently prevents an actionable fallback.

## Tests and remaining work

- 55 subset/client tests pass. Broader client/flow selection: 130 passed with one
  loopback test blocked by sandbox binding; that exact test passed when rerun with
  loopback access. Python compilation and JavaScript syntax checks passed.
- Finish provider-driven tests, attach subset receipts to the scientific input
  inventory through the normal reviewed-plan path, and test scientific preparation.
- Resume/range download, cancellation during an active local transfer and automatic
  continuation after a Desktop restart are not implemented yet. Server jobs can be
  polled again, and failed downloads can be retried without accepting partial data.
- UI/source tested; no new packaged app was built or Git/release pushed this turn.
