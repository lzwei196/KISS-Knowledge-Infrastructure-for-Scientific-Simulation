# Dataset search and project actions — implementation slice

Local source changes, not a rebuilt/released app.

- Search keeps discovery candidates but attaches `match.status` (`covered`,
  `unknown`, `insufficient`) and per-dimension metadata checks. Full requested
  period and bbox containment are assessed separately from intersection search.
  Ranking prefers covered over unknown over insufficient candidates.
- Malformed, nonfinite and out-of-range bboxes and invalid/reversed dates are
  rejected. Month endpoints use actual calendar month lengths.
- Inventory items may store `requirements: {bbox, start, end, variable}`. Planning
  instructions and API search descriptions ask for explicit filters and retention
  of these requirements; unknown requirements must not be fabricated.
- Project status computes the same assessment from stamped catalogue facts and
  requirements. It distinguishes manual download, agent download after approval,
  existing files needing inspection, generated inputs after upstream preparation,
  coverage checks, and selecting different data. UI messages are Chinese/English.
- `acceptable_sources` no longer participates in automatic inventory ID selection.
  This does not yet fix the separate execution permission for alternatives.

## Boundaries

This is not a server grid/clip API implementation or a full scientific input gate.
Regional/national coverage is labelled as requiring local extent inspection and
extraction, not as a grid-specific download. Units, resolution and actual files
still need validation. Variable aliases are not guessed: uncertain name matches
remain unknown. Legacy plans without requirements remain unverified rather than
being silently rewritten. Approved plans are unchanged.

The remaining audit findings (real child-ID resolution, strict selected-source
execution binding, replan receipt identity and extracted-file verification) remain
open in DB-GRID-PIPELINE-CODE-AUDIT-2026-09-13.md. No end-to-end completion is claimed.
