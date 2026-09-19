# CMFD link-delivery GUI test — 2026-09-14

## Scope and environment

Real DeepSeek API turn through the newly built GeoForge Desktop 0.6.52 GUI.
Project/session: `ace6c2c6377f`. Selected KIs: VIC and CaMa_Flood.
Build: `/Users/leo/kiss/builds/dist-resolver-links-v0.6.52/GeoForge Desktop.app`.

This is a **delivery-interface test**, not a VIC/CaMa simulation or scientific
forcing validation. Request: bbox `[115,37,117,39]`, 1989–1990, daily `prec,temp`.
No large-file download, installation, clipping, calibration or model run authorized
within this test plan. Private links and extraction passwords are omitted here.

## Observed results

- Agent used the resolver and selected four actual variable/year children:
  `cmfd_china_daily_010__prec_1989`, `cmfd_china_daily_010__prec_1990`,
  `cmfd_china_daily_010__temp_1989`, `cmfd_china_daily_010__temp_1990`.
- Resolver metadata reports approximately 1.18 GB total (size hints, not bytes
  measured from downloaded files).
- Source delivery extent is `[70,15,140,55]`, with
  `spatial_filter_applied=false`. The requested bbox does not imply a cropped file.
- Huai's `[112,31,120,35]` package was correctly excluded.
- Approval card shows the four file IDs, sizes, national extent and study extent.
- Initial plan included two unnecessary null-tool process steps and missing inputs
  for work outside this test. A GUI “Modify the plan” instruction removed those
  steps and reduced the plan to four download steps. Future-work questions remain
  in its narrative and should not be mistaken for requirements of link retrieval.

## Problems and incomplete checks

- The live page initially did not show the approval card; clicking Send did not
  submit a correction. Reload restored the card and the normal Modify workflow.
  Root cause is not yet established; do not describe this as fixed.
- The approval renderer labels null-tool download steps “no tool — cannot execute”,
  although the revised review no longer lists these as execution-readiness errors.
  Platform-managed delivery needs an accurate, explicitly identified renderer label.
- A fresh user approval was requested for link-only delivery. No approval was
  manufactured or written to disk. At this checkpoint the private link popup is
  **not yet verified**; query correctness is not end-to-end delivery success.
- No source files were downloaded or opened. File units, data values, completeness
  of VIC forcing and simulation readiness remain unverified.

## Next acceptance step

After the user approves the narrow link-delivery test, confirm that Desktop shows
all four corresponding share links, extraction codes and `path_in_share` values,
without leaking them to chat. Check that presenting the next item does not silently
overwrite the only visible handoff for the preceding item. Stop before downloads.

Server-side clipping is separately proposed in
`GEODATA-CLIPPING-SERVICE-REQUEST-2026-09-14.md`; it has not been implemented or deployed.
