# Alpine3D: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://gitlabext.wsl.ch/snow-models/alpine3d.git
Windows recipe source ref: `7188347dc69bcc7b99fad0e3f6523584b57b8414`

The Windows evidence confirms the MeteoIO and Snowpack runtime dependency stack. Its NSIS executable is Windows-only. For macOS use the official native source/build instructions and compatible MeteoIO/Snowpack libraries; never rename the Windows installer as a model binary.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.
