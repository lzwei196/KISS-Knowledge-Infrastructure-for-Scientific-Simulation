# GeoForge Database desktop integration

Status: implemented on the macOS development branch; release version not yet assigned.

## User flow

1. The user pastes an activation token in **AI settings**, selects whether GeoForge Database
   should use the configured proxy, and chooses an Agent access mode: live direct query (default),
   cached catalogue snapshot, or disabled.
2. The token is stored by the operating system credential service. The browser receives only a
   configured flag and a fixed mask.
3. The project data panel searches the live GeoForge Database catalogue and shows dataset id, kind,
   variables, spatial coverage, period, domains, format, delivery mode and size.
4. In the default **Direct through GeoForge Desktop** mode, API providers use the typed
   `search_observation_data` host tool and CLI providers such as Kimi, Claude and Codex invoke the
   exact Desktop-owned `GeoForge_Database` task-workflow KI adapter. The adapter calls a randomized
   loopback endpoint in the currently running Desktop process. Both routes query current records and
   return the same sanitized metadata; neither route exposes the persistent activation token.
5. In **Cached catalogue snapshot** mode, the Desktop creates
   `.geoforge/database/catalogue.json`. It contains scientific metadata but no token, signed URL,
   Baidu link or extraction code. Disabled mode exposes neither the live tool nor the snapshot.
   In every enabled mode, the Agent must compare records with each selected KI's real input
   contract and pin an exact catalogue id in `runs/data-inventory.json`; no data is downloaded
   during `PLANNING`.
6. After the user approves the plan and the Flow state is `EXECUTING`, the Agent uses
   `download_observation_data` or `obs-download`. The gate rejects an id that was not pinned to the
   inventory item and an item that is not consumed by the approved plan.
7. A served file is downloaded to a temporary location, hashed, compared with
   `X-Content-SHA256`, retried once on mismatch, and atomically moved or safely unpacked below the
   project's `inputs/` directory. GeoForge then writes a signed receipt and provenance record.
8. A manual dataset opens the existing private user-action panel with its Baidu link, extraction
   code and exact destination. The Agent sees only that a handoff was shown and must wait.

## Security boundaries

- Activation tokens are never stored in `settings.json` and never returned to the web UI.
- Agent tools receive catalogue results, not the bearer token.
- CLI Agents inherit a random, process-local capability and loopback URL. The capability grants only
  the explicitly exposed read-only catalogue endpoint and expires when Desktop exits. It is not the
  GeoForge Database activation token.
- `~/.kiss/bin/geoforge-db` is a materialized copy of
  `kiss/system_kis/GeoForge_Database/tools/search_catalogue.py`; it never executes an App Bundle or searches
  user folders. `~/.kiss/bin/geoforge-flow` similarly forwards only the fixed `run-tool`, `fetch`
  and `obs-download` commands to Desktop, where the existing Flow gate validates them.
- Catalogue pages shown to the UI or an Agent pass through the same field-level sanitizer.
- A catalogue outage is written explicitly into the planning snapshot; an Agent may not turn an
  unavailable query into a claim that data exists or was downloaded.
- Downloads require an approved plan, the `DOWNLOAD` capability, an exact inventory id match and a
  consuming plan step.
- Destination paths are resolved below `<project>/inputs`; absolute or traversal paths fail.
- ZIP members that are absolute, traverse upward or are symbolic links fail before extraction.
- Partial or corrupt files never appear in the project input directory.
- Manual-delivery credentials are displayed through the user-action path and are not returned in
  Agent tool output.

## Main implementation files

- `kiss/kiss_cli/secret_store.py` — native macOS, Windows and Linux credential storage.
- `kiss/kiss_cli/obs_access.py` — authenticated catalogue client and verified download helper.
- `kiss/kiss_cli/flowgate.py` — approval, inventory, step and receipt enforcement.
- `kiss/kiss_cli/api.py` and `kiss/kiss_cli/cli.py` — provider-neutral Agent tools and CLI wrappers.
- `kiss/system_kis/GeoForge_Database/` — KDT-single system task-workflow KI, diagnostics, preflight and read-only
  CLI catalogue adapter.
- `kiss/kiss_cli/gui.py` and `kiss/kiss_cli/flowrun.py` — short-lived loopback capability endpoints
  and stable launchers that avoid re-executing the app from Documents.
- `kiss/kiss_cli/web/app.html` and `library.html` — Settings and project data-panel UI.

No activation token belongs in source, build artifacts, logs, tests or release metadata.
