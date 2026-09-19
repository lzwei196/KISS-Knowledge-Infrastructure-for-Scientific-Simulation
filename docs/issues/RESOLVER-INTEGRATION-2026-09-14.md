# Desktop resolver integration — 2026-09-14

Implemented from the backend connect handoff supplied on 2026-09-14.

## Connected surfaces

- API `search_observation_data`: `resolve_dataset_id`, `variable`, `start`,
  `end`, `time_step`, `bbox` select resolution instead of local text search.
- CLI `obs-search --resolve PRODUCT --variable ... --start ... --end ...
  --time-step daily --bbox ...` uses the same adapter.
- Process-local CLI helper and GeoForge Database KI helper pass these parameters
  through the existing authenticated Desktop capability bridge. No DB token is
  exposed to CLI agents.
- Backend request uses documented `/resolve?dataset_id=...&variable=...&start=...`
  parameters. No clipping URL is guessed.

## Plan and UI

Allowlisted resolver metadata is cached under the catalogue directory's
`resolved/` subdirectory, with a six-hour validity window for new plan stamping.
Child IDs must be actual catalogue/resolver records; merely matching a child-name
pattern is no longer sufficient. Missing catalogue for explicit DB selections
fails validation. Reported coverage gaps or spatial noncoverage block stamping.

Each selected child retains its size, variable/year, and resolver delivery extent,
requested bbox, spatial flag and completeness metadata. Project status displays
unique selected units, their total known size, study versus delivery extent and
required local extraction. Plan review also shows uncut delivery extent before
approval. A child's requirements should describe that child's contribution;
the plan must include every required year/variable for the whole run and warmup.

Download authorization no longer accepts `acceptable_sources` as a selection.
An explicit selected dataset takes precedence over other source fields. Existing
post-approval manual handoff remains private; child `size_hint` is now rendered.

## Live check

New adapter queried national daily CMFD for `prec,temp`, 1989-01-01 through
1990-12-31, bbox `[115,37,117,39]`:

- 4 actual child IDs returned and persisted in an isolated temporary metadata cache.
- 1,180,000,000 estimated bytes.
- `spatial_filter_applied: false`.
- `delivery_extent: [70,15,140,55]`.
- `requested_bbox: [115,37,117,39]`.
- `coverage_complete: true`, `covers_requested_bbox: true`.

No link disclosure or dataset download was requested by this check. No live
provider turn, approval, VIC run or CaMa run occurred.

## Remaining limits

This does not implement a server clipping service, Baidu automation, a full
bundle-completeness gate across all selected inventory items, or the previously
reported cross-plan receipt-identity/extracted-input verification fixes. Those
remain required before claiming complete autonomous scientific acceptance.
The UI was syntax-checked, not visually accepted in a newly compiled app.
No build, commit, push or release was performed for these changes.

## Tests

Added mocked resolver tests for exact query names, real-child persistence,
credential-field exclusion, partial/foreign results, unknown coverage, and
unselected-alternative download rejection. Flow library: 78 passed, 2 skipped
(existing NumPy binary-compatibility warning).

Full desktop run initially reported 390 passed, 2 failed, 1 skipped: the plan-data
test needed a proper catalogue fixture under the new fail-closed rule (corrected);
the separate Windows-name test reports existing tracked build/acceptance paths.
Do not interpret that full-suite run as a clean pass.

After fixture correction: resolver, flowgate, project-state and CLI-wrapper suites
passed **120 tests**. Final resolver/flowgate recheck including alternative rejection:
**59 passed**. Python compilation, UI JavaScript syntax and diff whitespace checks passed.
