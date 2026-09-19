# GeoForge Database KI

<!-- KI-MAP:BEGIN -->
- Contract: `knowledge_infrastructure.yaml`
- Workflow: `workflow/workflow.md`
- Stages: `docs/s1_scope_query.md`, `docs/s2_search_catalogue.md`, `docs/s3_report_selection.md`
- Diagnostics: `diagnostics/triplets.yaml`
- Preflight: `preflight_check.py`
- Visualization: `visualization_contract.yaml`
<!-- KI-MAP:END -->

## MANDATORY EXECUTION POLICY

This KI is a catalogue and data-proposal adapter, not a licence to search the user's
computer or contact a private database directly. Use only
`tools/search_catalogue.py` (or the exact Desktop command projected from it).
The GeoForge Database activation token remains inside GeoForge Desktop. Never
ask the user or Desktop to reveal it, never inspect Keychain/credential files,
and never substitute synthetic catalogue entries when the adapter fails.

During task intake and planning, search first when data availability can change
the model, period, domain, or plan. Report exact dataset IDs and the metadata
actually returned. If the adapter reports that Desktop is unavailable or that
authentication failed, quote that failure and stop the catalogue step; do not
scan home directories for another connector.

## Purpose

This task-workflow KI lets an Agent discover observation and forcing records
through a short-lived, least-privilege capability issued by the running
GeoForge Desktop process. It provides catalogue and actual source-schema metadata.
Use `--describe DATASET_ID` after finding a candidate and before choosing subset
variables. Names come from source files, not inferred catalogue aliases. Dataset
download remains a separate, user-approved flow step owned by Desktop.

## Workflow

1. Read [docs/s1_scope_query.md](docs/s1_scope_query.md) and form specific
   search terms from study area, variable, gauge/station, and period.
2. Follow [docs/s2_search_catalogue.md](docs/s2_search_catalogue.md) and call
   `tools/search_catalogue.py` once per materially different query.
3. Follow [docs/s3_report_selection.md](docs/s3_report_selection.md), present
   exact results, and ask the user to select data before any download.

The complete contract is also summarized in
[workflow/workflow.md](workflow/workflow.md). Common failures and their bounded
remedies are in [diagnostics/triplets.yaml](diagnostics/triplets.yaml).

<!-- KI-TOOL-INDEX:BEGIN -->
- `tools/search_catalogue.py` — query the Desktop-owned read-only catalogue adapter.
<!-- KI-TOOL-INDEX:END -->

## Inputs and outputs

Input: ordinary search terms plus optional `--limit` and `--offset`. Both a
positional query and `--query` are supported. Output: the server's sanitized
JSON catalogue response. Searches/descriptions do not write project files.
Subset estimates are saved as exploration history by Desktop. The plan's data
inventory is the proposal: an item that names the dataset and the study scope is
joined to its estimate by Desktop and approved with the plan. No operation here
authorizes a job or download, and none returns an activation token.

## Verification

Run `python3 preflight_check.py`. This validates the KI structure and helper
syntax without claiming that a user is activated or that the remote service is
online. Live authentication is tested by GeoForge Desktop's Database settings.
