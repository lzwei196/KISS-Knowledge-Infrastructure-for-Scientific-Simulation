# Stage 2 — Search the live catalogue

Run the exact Desktop-projected command or:

```text
tools/search_catalogue.py "Bengbu 51080 discharge" --limit 25
```

Use `--query` only as an equivalent spelling when a caller requires named
arguments. Paginate with `--offset` rather than increasing the limit above 100.
The command must be launched by GeoForge Desktop because the process-local
endpoint and capability are intentionally absent from an ordinary terminal.

On failure, preserve the actual error. Never search Keychain, home directories,
localhost ports, package caches, or source trees for an alternative connector.
