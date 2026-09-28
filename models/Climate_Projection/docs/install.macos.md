# Climate Projection: Mac installation record

A real DeepSeek installation passed the independent Python import check on 2026-09-08. The software is the workflow shipped in this KI and GeoForge's bundled ki_tools_common library; there is no required PyPI distribution named climate_projection.

Prepare the normal workspace Python environment and bundled shared library. Satisfy the declared imports, including scipy, and the real dependencies of the shipped climate-workflow modules. The observed repair installed scipy after the initial environment lacked it. Preserve the workspace venv/bin/python launcher in kiss.toml.

The agent additionally imported the shipped extraction, delta calculation and forcing-conversion modules to confirm they loaded. Do not execute their data-processing functions, download CMIP6/NEX-GDDP datasets, or run a scenario during an installation-only test. A missing fictitious climate_projection PyPI package does not mean the already-shipped workflow needs a replacement implementation.
