# Project-relevant data approval — desktop correction

## Changes

The previous panel displayed every estimate as a possible approval. The corrected
flow distinguishes exploration from an explicit, project-specific selection:

1. Agent searches and describes actual sources, then estimates candidate scopes.
2. Agent publishes only recommended acquisition IDs, a project summary, and a
   purpose for every selected request. Failed probes and unchosen alternatives
   stay in collapsed exploration history.
3. The current visible, idle project receives one review prompt per proposal
   revision. The panel shows purpose, dataset, region, period, fields, estimated
   size, and inspection limitations. Users can uncheck requests and approve the
   remaining scopes together. Viewing/closing the prompt is not approval.
4. The acknowledgement is persisted separately from signed acquisition consent.
   The pending badge remains; unchanged proposals do not repeatedly reopen.
5. Request/estimate changes invalidate the selected scope. Expired estimates must
   be refreshed. The batch validates every selected ID before creating any jobs.
   Remote partial failures preserve successful jobs; a duplicate approval does
   not create the same job again.

There is no newest-per-dataset heuristic: different regions/periods from the same
dataset can legitimately be needed. Existing estimates are not automatically
migrated into a chosen plan. Previously approved jobs remain visible separately.

## Interfaces and code

- New `kiss/kiss_cli/data_proposal.py`: publication, revision fingerprints,
  presentation/history split, persisted acknowledgement, current-selection
  checks and batch approval.
- API agent: `search_observation_data(subset_proposal={acquisition_ids,summary,purposes})`.
- CLI agent: `geoforge-db --propose JSON`; both helper implementations send a
  capability-protected POST to Desktop, not the database credentials.
- `gui.py`: a registered project is required for agent proposals. Agents can
  propose but cannot acknowledge/approve through that endpoint. Browser approval
  still requires the existing local request protections and exact proposal revision.
- `web/app.html`: selected data first, grouped review and checkbox selection,
  collapsed read-only exploration, manual estimate form in advanced controls,
  pending badge, no contradictory “no action needed” message for pending data.
- Shared database instructions and the database KI documentation now distinguish
  estimate history from user-facing proposals. `DESKTOP_CHANGELOG.md` records it.

Publication expresses an agent recommendation, not proof that it scientifically
satisfies the user's intent. The user must still review the purposes/scopes.
Acquisition approval is not simulation approval; missing-data/source suitability
checks remain separate.

## Raster selector correction

`data_contract.normalize_estimate()` now blocks nonempty requested variables when
the server does not confirm the selected names. Previously that was only a warning,
so an unsupported raster selector could receive inspection approval. Intentional
whole-raster requests (`variables: []`) remain supported. Presentation recomputes
legacy offers, and acquisition/download guards reject unconfirmed selections.

This is a desktop safeguard. It does not claim the server has fixed its raster
estimate behavior or implemented individual band selection.

## Verification

Focused data/flow/security suite: **218 passed**, 44.35 seconds, including isolated
loopback tests with fake remote responses. It covers proposal publication through
both provider transports, approval capability separation, project registration,
wrong/stale/unselected IDs, duplicate scopes, same-dataset different tiles,
acknowledgement persistence, partial failures/idempotence, and legacy raster
selector rejection. Frontend tests execute the shipped renderer in Node for
English/Chinese, escaping, selected-only controls, and collapsed history. Popup
guards also have source-level coverage; actual screen observations are below.

```text
PYTHONPATH=kiss python3 -m pytest kiss/tests/test_obs_describe.py kiss/tests/test_obs_access.py kiss/tests/test_obs_subset.py kiss/tests/test_data_contract.py kiss/tests/test_data_proposal.py kiss/tests/test_data_proposal_routes.py kiss/tests/test_data_proposal_ui.py kiss/tests/test_flowgate.py kiss/tests/test_flowrun.py kiss/tests/test_local_security.py -q
```

All three inline scripts parse. `git diff --check` passed.

## Compiled-app observations

Rebuilt local macOS 0.6.52 test bundle (not a published release). The existing
browser remains on `http://127.0.0.1:61823/`.

The previous DeepSeek test project now shows no proposal approval controls until
an explicit selection is submitted. Its unselected/failed estimates are collapsed.
Seven jobs that had already been approved in the old interface were found and
preserved separately; this change does not erase them or silently approve more.

A live Kimi follow-up was initiated through the GUI in session `5c4bfebf34bc`,
using the same five-family North China Plain test. It refreshed the estimates and
initially selected `elevation_m` for DEM. Acquisition
`700c6d6243eb411faed04a425042c79c` was blocked with
`variable_selection_unconfirmed`; Kimi then corrected it to an intentional
empty selector, acquisition `8bc36b16b85746a596c3ef3de0bdd0f4`.
This demonstrates an actual provider recovery from the desktop guard, not just
a fixture. No jobs/downloads were authorized by this follow-up test.

Kimi successfully published revision
`bb2500f2ec43d60cf659bc4d3274f2e45e0d5b26303b18f50c3e411174163d03`.
The current page automatically opened one review with exactly five selected
items, one approval button, and seven collapsed exploration records. Closing
the panel kept it closed through polling and a page reload/reopening of the
project. The persisted acknowledgement was true, while the Kimi project's job
count remained **zero**. This was a real GUI/provider/remote-estimate test; the
real approval click and data downloads were deliberately not performed.

The verbose agent summary was subsequently moved behind an expandable rationale,
with a short preview and sticky approval controls near the top. The frontend
tests were rerun successfully after that presentation-only adjustment.

Final bundle:
`/Users/leo/kiss/builds/dist-data-proposal-20260915-v0.6.52/GeoForge Desktop.app`.
Executable SHA-256:
`4ff9d86c030cd5150c289a77dc0d1ae5c4c1fb5dff09672f5dd475370637c25c`.
Deep strict signature verification passed (ad-hoc local signing, not notarization).
It was relaunched on the same port 61823. No Git push or release publication was
performed. Older user build folders and project evidence were preserved.

## Follow-up: user clicked approval and saw no visible response

The real click exposed a gap in the earlier verification: it had deliberately
stopped before approval. The server route rejected the click with
`Selected estimate is blocked or expired; ask the agent to refresh it`.
The selected estimates had exceeded Desktop's 15-minute validity window. No
jobs were created in the Kimi project. This was not a remote download stall.

The UI had rendered the cards while still valid, did not update pending estimate
expiry, and placed the error after all five long rows, below the visible area.
Thus the click failed closed correctly but the user could not see why.

The follow-up correction adds a browser-only `refresh_selection` action. It
re-estimates the exact selected requests, preserves purposes and existing jobs,
and creates a new revision for review without acquisition consent. All refreshed
estimates must pass the current guards before replacing the proposal; a failed
renewal keeps the old proposal. Old estimates remain in history. Changed or stale
proposal revisions fail before contacting the remote service. A renewal cannot
silently drop a variable filter or widen a region/date range.

The frontend now places action feedback beside the controls, displays expiry and
job status without expanding technical details, and offers direct estimate
renewal. Fresh estimates still require a review/approval click. This keeps the
approval boundary rather than extending validity or bypassing it.

Additional backend regression tests exercise expiry presentation, unchanged
request scopes, refreshed sizes, partial renewal failure, retained approved jobs,
stale/tampered proposals, rejected unconfirmed variables, and the actual local
POST route sequence: expired approval → renewal → fresh-revision approval.
These tests use fake remote responses; compiled live results are recorded below.

Final follow-up regression suite: **229 passed in 42.46 seconds**. The suite also
checks cancellation during renewal (must not revive the cancelled scope) and
cross-project responsiveness during a slow estimate request. Proposal-operation
locks are project-specific; commit checks use acquisition locks. Frontend tests
execute shipped JavaScript, including busy feedback, checkbox opt-outs across
renewal, expiry recovery, session-switch races, and GET-only retry after loss of
the post-approval status response (no repeated approval POST).

Rebuilt and relaunched the corrected app on port 61823:
`/Users/leo/kiss/builds/dist-data-approval-retry-20260915-v0.6.52/GeoForge Desktop.app`.
Executable SHA-256:
`f04a32065679af8f03a89eefafb581b8f1abfa132c65f45fd39fdf17c27f19ed`.
Deep strict ad-hoc signature verification passed.

Live browser check after local midnight on September 16:

- The Kimi test session now immediately shows **5 estimates need refresh**, not
  stale approval controls. Each selected row visibly reports expiration.
- Clicking **Refresh estimates (no acquisition)** displayed a spinner and the
  no-jobs/no-download message beside the control, then successfully refreshed
  all five estimates through the actual remote service.
- Scopes, fields, all-member limitations and estimated total **36.5 KB** remained
  unchanged. The panel displayed a fresh-review success message and the approval
  button; old estimates moved to history (12 unselected records).
- The attempted final approval click by the testing agent was blocked by the
  automation safety reviewer because the refreshed batch needs user approval
  before server job creation. No workaround was used. **Real job creation and
  downloads are not claimed as verified by this follow-up**; the final approval
  remains with the user in the visible panel.

### User approval confirmed, September 16

After the user reported clicking, the real app showed successful approval and
five actual server jobs. Both project state and the visible review panel were
checked. This supersedes the earlier not-yet-approved snapshot:

| Dataset | Server job | Status | Reported delivery bytes |
| --- | --- | --- | ---: |
| CMFD daily | `acb7d2c0a8704324` | ready | 181288 |
| Sacks crop calendar | `07889f89307f4560` | ready | 98384 |
| HWSD China | `074a6809bf404f18` | ready | 1610 |
| China 90 m DEM | `5622d1d0c07b4256` | ready | 6636 |
| GGCMI crop calendar | `852bc0c68458447d` | failed | — |

The four ready jobs report 287918 delivery bytes in total; these are actual
server-reported file sizes, not the earlier raw-data estimates. No local
download/checksum/content verification is claimed at this stage. The automation
safety reviewer blocked the test agent's download click pending explicit user
permission for downloads; no alternate transport was used to bypass it.

GGCMI failed after job creation, despite an accepted estimate with exact source
fields `maturity_day` and `planting_day`, a nonempty selection, bbox
`[115,37,115.5,37.5]`, and 40 member files. Desktop correctly displays the failed
job, but its saved public message alone does not establish the precise backend
cause. No repeated job was submitted.
