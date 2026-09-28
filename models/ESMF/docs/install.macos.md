# ESMF: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://github.com/esmf-org/esmf.git
Windows recipe source ref: `99356176e374c49273893bbb9564705915dba621`

Learn the paired ESMF/ESMPy native-library contract: Python import alone is insufficient. If a native conda-forge Mac pair is available, use a workspace prefix and its real ESMF_RegridWeightGen, ESMF_PrintInfo and esmf.mk. Resolve library paths in that environment. Windows 8.4.0 build identifiers and Library/bin paths do not apply on Mac. Limit installation checks to startup/imports.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.
