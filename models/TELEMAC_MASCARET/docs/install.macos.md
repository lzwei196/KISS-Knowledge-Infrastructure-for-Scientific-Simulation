# TELEMAC_MASCARET: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://gitlab.pam-retd.fr/otm/telemac-mascaret.git
Windows recipe source ref: `a040e817390e787c5395be95663381ae85a4c0e3`

Use the official pam-retd GitLab repository, not the project website. Set GIT_LFS_SKIP_SMUDGE=1 for clone and checkout; large Git LFS scientific datasets are not needed for installation. Learn the serial homere_telemac2d target and optional-component settings from Windows. Adapt the native CMake build and gfortran flags to Mac, preserving the real core libraries. Check the serial parallel/special linkage only if the native build exposes that dependency; do not copy Windows runtime libraries.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.

## Native runtime dictionary audit (2026-09-09)

Official v9.1 branch commit `1fe3b5141f7d9c9fa8fe6d6d0316c994a39c2d95` distinguishes a distributed runtime dictionary from scientific steering input. Preserve `sources/telemac2d/telemac2d.dico` with the installation. Its audited SHA-256 is `984985dabe1deba5c22d2b1a14ce07f2e38fc720aed071eef5512f72c9e46309`. The native serial core expects this dictionary as `T2DDICO` in its working directory. The official launcher performs that copy in `scripts/python3/execution/process.py:150-154`.

In `sources/telemac2d/lecdon_telemac2d.f:177-183`, the core opens `T2DDICO`, then opens `T2DCAS` (the scientific steering file), before parsing or simulation. `CONFIG` is optional launcher language/output metadata: `sources/utils/bief/read_config.f` explicitly uses defaults when it is absent. Do not create fake CONFIG or steering files for an installation test.

A proposed installation probe may copy only the hash-verified distributed dictionary to a fresh temporary probe directory, leaving scientific inputs absent. This needs explicit verifier support; documentation alone does not implement it. Only the resulting exact missing-`T2DCAS` boundary with a genuine native version banner can establish core startup; missing-`T2DDICO`, missing libraries, signals, and timeouts remain failures. The existing baseline remains failed until an independent native retest records this boundary. A TELEMAC2D startup check does not establish installation of every coupled solver.
