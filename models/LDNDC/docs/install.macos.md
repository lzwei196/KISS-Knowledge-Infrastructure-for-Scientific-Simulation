# Official native Mac installation

The official public distribution is LandscapeDNDC1.37, revision12193, built
2026-03-03 for macOS arm64. Native `--version` and `--help` both exit0 without
creating files. The executable links only macOS system libraries.

Run `python3 tools/install_ldndc_macos.py` from the selected installation workspace.
It downloads the official versioned archive, verifies SHA256, and extracts only
bin/, Lresources, LICENSE, revision and ldndc.conf. It independently verifies the
native binary hash. It does not run install.sh or write to HOME, and does not
extract project examples or parameter datasets. Verify the genuine executable
with `binaries/ldndc/ldndc-1.37.mac64/bin/ldndc --version`.

Installation readiness is distinct from the legacy science preflight, which
requires external datasets and uses Linux-specific paths. Linux runners retain
those existing paths. Scientific execution and parameters are outside this
installation audit; do not fabricate their inputs to pass installation.

The model collection and crabmeat framework have different terms. Preserve the
bundled LICENSE; the official license page restricts redistribution/commercial
use of crabmeat without written permission. Public acquisition of this archive
requires neither authentication nor a personal-information form.

- https://ldndc.imk-ifu.kit.edu/download/download-model.php
- https://ldndc.imk-ifu.kit.edu/ldndc/downloads/public/packages/mac64/ldndc-1.37.mac64.2026-03-03.tar.bz2
- https://ldndc.imk-ifu.kit.edu/about/license.php

## Observed DS installation result

DS repair 87 independently passed on 2026-09-09 in 638.3 seconds.
The engine confirmed genuine Mach-O presence, architecture, linked dependencies,
required Python imports, and `--version` exit0 with `LandscapeDNDC 1.37 (revision 12193)`.
The retained installation-test.json reports installation_only=true, usable=true
and state=ready. This does not establish scientific execution or dataset readiness.
