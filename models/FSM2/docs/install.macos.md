# FSM2: Mac installation guidance

Learned from windows-version fbed40b08f2d7c552c5c332a912b5a65f3d8855c on 2026-09-08. This is unverified Mac guidance, not a Mac installation result.

Official source: https://github.com/RichardEssery/FSM2.git
Windows recipe source ref: `f0c86be12274354c958c2b71661cefefd6ae79f3`

Use the pinned official source and its upstream compil.sh build configuration. The Windows installation learned that the default ASCII build uses PROFNC=0 and does not require NetCDF or MPI. Use native gfortran, preserve the ordered Fortran module/source list, and read the upstream script before reproducing its OPTS.h definitions. Do not change science defaults. Empty stdin may produce an EOF in the namelist reader after successful startup; no simulation is required.

Keep installation within the selected workspace. Verify the actual native product and required package imports. Preserve explicit blockers and installation evidence.
