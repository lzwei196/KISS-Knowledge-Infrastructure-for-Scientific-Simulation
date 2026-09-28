# CRHM: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://github.com/srlabUsask/crhmcode.git
Windows recipe source ref: `master`

Initialise the official spdlog submodule before configuring the native CMake build. Retain the real CRHM CLI and support tree. A help command may exit 1 after printing usage; inspect that output. The Windows MAX_PATH workaround is not a Mac requirement.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.
