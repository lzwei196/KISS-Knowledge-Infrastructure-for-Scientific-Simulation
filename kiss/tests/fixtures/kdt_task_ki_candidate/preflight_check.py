#!/usr/bin/env python3
"""Check the standard-library workflow runtime."""

import json
import sys

report = {
    "checks": [{
        "kind": "runtime",
        "subject": "python",
        "critical": True,
        "status": "pass" if sys.version_info >= (3, 10) else "fail",
        "fix": "Install Python 3.10 or newer and select it in GeoForge",
    }]
}
print("PREFLIGHT_REPORT=" + json.dumps(report))
raise SystemExit(0 if report["checks"][0]["status"] == "pass" else 1)
