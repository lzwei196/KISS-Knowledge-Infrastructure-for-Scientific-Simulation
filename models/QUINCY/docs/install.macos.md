# QUINCY: declared Python variant on macOS

This recipe installs **quincy-analytic-py**, the implementation already declared in both the Mac and Windows KI metadata. Its version description is `analytic reimplementation (QUINCYModel, monthly timestep)`. It does not install the official upstream QUINCY application or establish scientific equivalence with it.

The real engine is the existing bundled `tools/run_quincy.py`. Its SHA256 is `bf3e676c78629e5df329d5691a82e8646551162f3d99a81e34898677f0c4dfd2`. No runner code or equations were changed for this installation contract. The script contains no path-substitution tokens; the materialized workspace copy must retain these exact bytes.

Install the genuine manifest-listed Python dependencies into the installation workspace venv, retain its own Python launcher, and keep the original runner under the workspace KI directory. Acquisition is `bundled`; there is no separate PyPI model package to invent or official binary to substitute.

The fixed `python_script` gate binds the exact implementation id, relative runner path and SHA256. It uses the workspace Python, verifies dependencies, then runs only `--help` with closed stdin from an empty directory. Require exit0, the runner's help output, no timeout and no created files/directories. An interpreter version, generic dependency imports alone, or argparse exit2 from unsupported `--version` is insufficient.

The existing runner's argparse help path exits before model construction, input reads or scientific execution. Do not invoke simulation/calibration functions, instantiate models, run full scientific preflight checks, or create input datasets during installation. The broader scientific workflow remains unchanged and is outside this installation test.

Verification status remains unverified until a fresh dedicated installation test passes. Historical interpreter/import/argument-error receipts are retained separately and are not promoted by adding this manifest.

## Installation verification

Fresh DeepSeek installation passed on 2026-09-09: exact runner hash, required imports and clean bounded help startup. This verifies the declared Python variant only. Official upstream installation and scientific equivalence are not established.
