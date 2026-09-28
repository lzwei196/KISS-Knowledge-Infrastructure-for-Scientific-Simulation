# VELMA: declared Python variant on macOS

This recipe installs **velma-python-4layer**, the implementation already declared in both the Mac and Windows KI metadata. Its version description is `run_velma.py velma_4layer (lumped daily reimplementation)`. It does not install the official upstream VELMA application or establish scientific equivalence with it.

The real engine is the existing bundled `tools/run_velma.py`. Its SHA256 is `051af5442a787087d41e58982040caa6c8500145f593941a18e5f7a29e722123`. No runner code or equations were changed for this installation contract. The script contains no path-substitution tokens; the materialized workspace copy must retain these exact bytes.

Install the genuine manifest-listed Python dependencies into the installation workspace venv, retain its own Python launcher, and keep the original runner under the workspace KI directory. Acquisition is `bundled`; there is no separate PyPI model package to invent or official binary to substitute.

The fixed `python_script` gate binds the exact implementation id, relative runner path and SHA256. It uses the workspace Python, verifies dependencies, then runs only `--help` with closed stdin from an empty directory. Require exit0, the runner's help output, no timeout and no created files/directories. An interpreter version, generic dependency imports alone, or argparse exit2 from unsupported `--version` is insufficient.

The existing runner's argparse help path exits before model construction, input reads or scientific execution. Do not invoke simulation/calibration functions, instantiate models, run full scientific preflight checks, or create input datasets during installation. The broader scientific workflow remains unchanged and is outside this installation test.

Verification status remains unverified until a fresh dedicated installation test passes. Historical interpreter/import/argument-error receipts are retained separately and are not promoted by adding this manifest.

## Installation verification

Fresh DeepSeek installation passed on 2026-09-09: exact runner hash, required imports and clean bounded help startup. This verifies the declared Python variant only. Official upstream installation and scientific equivalence are not established.
