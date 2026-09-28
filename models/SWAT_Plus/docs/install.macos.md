# SWAT_Plus: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://github.com/swat-model/swatplus
Windows recipe source ref: `cb442f7c05fc3bfc34349c446010f452d2737ca0`

Use the pinned official source with native CMake and gfortran. Discover the actual Mac executable name from the build output; do not copy the Windows versioned PE path. Revision 62 installation does not establish compatibility with the historical revision 59.3 scientific project. Verify startup only and preserve the upstream project format.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.
