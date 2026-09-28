# RHESSys: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://github.com/RHESSys/RHESSys.git
Windows recipe source ref: `91dccef178e5df33be2f8105f68e3cda819b7bb1`

Use the pinned official RHESSys 7.4 source and its makefile object whitelist. Preserve the upstream dynamic_field_lookup.py source-generation step and flex/bison parsers. Link to real native netCDF. Windows strndup/yywrap compatibility objects, UCRT runtime staging and DLL import libraries must not be copied to macOS. Keep scientific routines and boolean storage definitions unchanged.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.
