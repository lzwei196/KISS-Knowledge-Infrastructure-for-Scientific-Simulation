# GeoForge DB / simulation follow-up — 2026-09-13

Reviewed Claude's `docs/HANDOFF-2026-09-13.md` and preserved the existing uncommitted changes.
No plan was automatically approved, no provider turn was launched, and no application instance was restarted.

## Live project state checked

Session `c9ca97b2ca5d` remains `EXECUTING`, with a waiting manual-download request for
`inputs/raw/cmfd`. That destination does not currently exist. The approval is dated
2026-09-13 15:52:22 +0800, plan hash
`ad7b87cac2d148db1f266e400a4d89657c001d3f38ae112b992511714bc97e1c`.
There are no model-run receipts bound to this latest plan. The older receipts do not
prove that the current plan ran. This is a data-delivery blocker, not evidence that VIC failed.

The handoff identifies the selected forcing as a manual-delivery CMFD Huai subset.
Do not silently replace it with another forcing source or synthetic data. The user must
place the selected data through the existing Project status handoff, or approve a new plan.

## Additional local fixes

- Download handoff no longer accepts an unspecified destination, an empty directory,
  hidden cache contents, symlinks, or common partial-download files as delivered data.
- Local inventory readiness no longer treats an empty directory as ready.
- Served-download readiness requires a valid signed receipt and unchanged recorded raw
  files; merely creating a receipt JSON or retaining a stale receipt is not sufficient.
- Documented the actual macOS token storage security properties in `secret_store.py`:
  mode-0600 file storage is not encryption or isolation from same-user processes.

Presence remains distinct from scientific validation: even a complete downloaded file
must be checked for expected variables, temporal/spatial coverage, format, and units by
the KI. A valid download checksum alone does not prove a shapefile has its sidecars.
The status reader currently checks raw-file hashes; performance on multi-GB receipted
datasets still needs measurement before claiming the periodic UI refresh is inexpensive.

## Regression coverage

Added tests for partial/hidden/symlink downloads; missing handoff destination; empty local
directories; forged receipts; deleted and modified downloaded payloads. The flow library
baseline passes 78 tests with 2 skips and an existing NumPy binary-compatibility warning.
Desktop baseline inside the restricted sandbox passed 376 tests, with two localhost-bind
tests denied by the sandbox and one skip. The final desktop rerun with localhost permission
passed **381 tests, 1 skipped, 121 subtests**, including the new regressions.

## Next live acceptance

1. Supply CMFD through Project status and explicitly continue.
2. Inspect the delivered data before preprocessing. Do not equate file presence with
   completeness or interpret historical receipts as current-plan execution.
3. Run preprocessing, real VIC, routing where scientifically applicable, and validation;
   require receipts and inspect actual output files, not only the agent's final message.
4. Repeat with Kimi separately after the DeepSeek run; preserve the same data and approval
   requirements. Neither provider's end-to-end completion is claimed by this follow-up.

Changes here are source-only: no rebuild, commit, push, or release was performed.
