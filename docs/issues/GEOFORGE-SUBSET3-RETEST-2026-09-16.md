# obs_subset/3 retest through the compiled app (DeepSeek), 2026-09-16

Build: `~/kiss/builds/dist-subset3b-v0.6.52`, session `ab97de8b62a9` (provider `api:deepseek`),
workroot `~/kiss/projects/describe-ui-20260915`. Flow used: chat → DeepSeek `describe` + fresh
estimates + one data proposal → user approval click in Project status → server jobs → download
buttons → file inspection. No model runs.

## Result per backend issue (B1–B7 from GEOFORGE-BACKEND-OPEN-ISSUES-2026-09-16.md)

| ID | Live result | Verdict |
|---|---|---|
| B1 CMFD time clip | 8 parts, each `time=2`, 1989-01-01 and 1989-01-02 (10:30 stamps), manifest `time_range` present and equal to file | **fixed** |
| B2 Sacks bounds | manifest `bounds` = cell edges `[115.000033,37.000033,115.083367,37.083367]`, plus `cell_centre_bounds`, `shape`, `spacing_deg`, `regular_grid`, `bounds_convention: cell_edges`; Desktop scope check passed; 9 members | **fixed** |
| B3 GGCMI job | job ready, 38 parts, 531,240 bytes, all readable; maize rf/ir plant 149 / maturity 257 | **fixed**, but see B3b |
| B3b missing-member report | estimate `n_files: 40`, manifest `n_parts: 38`, **no `unreadable_files` in manifest or job status** (contradicts the backend note). Missing: `mil_rf`, `sor_ir`. Desktop now derives the shortfall from the estimate and shows it | **open on backend**: publish the skipped member names |
| B4 raster selector | `china_dem_90m` + `variables: ["bogus"]` → HTTP 400 `variable_selection_unsupported`; empty list still valid | **fixed** |
| B5 stale cache | all six estimates/manifests stamped `processing_version: obs_subset/3`; fresh files, correct dates | **fixed** (as far as observable) |
| B6 metadata | describe carries `processing_version`, `source_version`, `units_authority: source_file`, `coverage_scope: inspected_sample_files`, `coverage_note`; CMFD `prec` delivered as `kg m-2 s-1` (native), catalogue label still `mm/day` | fixed on API; catalogue label is a data-team item |
| B7 HWSD parity | not retested (provenance audit is a backend/data task) | unchanged |

Downloaded and value-checked (netCDF4 / rasterio locally):
CMFD temp 272.5/270.2 K, pres 1023 hPa, prec 0; Sacks maize plant 130, harvest 254, tot.days 124;
DEM 124×124, 26–40 m, no nodata; HWSD Albers 10×12 and Geo 12×12, IDs 11476–11525, no nodata.

## Desktop changes made for obs_subset/3

- `obs_subset.PUBLIC` / `PART_PUBLIC` keep `processing_version`, `source_version`,
  `cell_centre_bounds`, `shape`, `spacing_deg`, `regular_grid`, `bounds_convention`.
- Manifest-level `processing_version`, `source_version`, `unreadable_files` are stored on the
  acquisition (`state['manifest']`) and in the signed acquisition receipt. A manifest whose
  processing or source version differs from the approved estimate is refused before transfer.
- Partial member delivery: `missing_members = estimate.n_files − manifest.n_parts` (or the
  `unreadable_files` list when the server sends one) → `content_validation.pending` gets
  `members_missing`; the Project status card shows "partial delivery: promised N, received M".
- `describe` keeps `processing_version`, `units_authority`, `coverage_scope`, `coverage_note`.
- New error code `variable_selection_unsupported` has a message and routes the agent to
  describe-and-revise (empty variable list) instead of a blind retry.
- Tests: `kiss/tests/test_obs_subset.py` (+5). Desktop suite 505 passed.

## Still open

- Backend: name the skipped members (B3b); fix catalogue `prec` unit label (B6); HWSD provenance (B7);
  optional member/crop selector (maize-only requests).
- Desktop: bundle a raster reader in the frozen app (`raster_reader_unavailable` for DEM/HWSD);
  the click targets in Project status shift while the panel polls, which made automated clicking
  land on the wrong control twice — a real user would see the same shift.
