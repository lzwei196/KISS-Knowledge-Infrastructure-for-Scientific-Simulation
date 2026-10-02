# GeoForge Desktop 0.6.56 Windows release verification

Windows 0.6.56 packages the illustrated English and Chinese quickstarts into the installer and portable app. Each quickstart is exactly three pages: connect DeepSeek, install and verify SHAW, then approve and inspect the official Trial run. The README explains the Desktop, KI, KDT and optional data-access roles and provides direct Windows downloads.

The reviewed guide edition remains **0.6.55**, including the October 2 illustrated revision. Its filenames and screenshots retain that edition number because the application workflow is unchanged. All 12 offline HTML/PDF files are included in this release, along with six separately downloadable PDFs.

## Fresh checks for this release

- **28 focused tests and 15 subtests passed** for release metadata, reviewed guide hashes, offline routes, missing-file handling and language-specific links. Tests used Python 3.11 with UTF-8 mode off and the actual Windows **cp936** default encoding; only terminal output was UTF-8.
- The frozen bundle passed checks for **127 scientific KIs**, **127 Windows installation notes**, **23 Windows recipes**, bundled Python, the agent bridge without Python on PATH, Unicode bridge IPC, harness/Flow readiness, calibration dependency readiness, 11 application HTTP routes and **all 12 offline guide routes**.
- The actual installer installed into a fresh isolated directory, exited 0, and installed the exact tested executable. The installed application passed the same checks. Uninstallation exited 0 and removed the application executable. No pre-existing GeoForge per-user uninstall registration was replaced.
- The application, console bridge and installer carry version **0.6.56** in their Windows version resources. The portable ZIP passed a complete CRC check; both executables, the manifest and all 12 guides match the tested bundle.
- An independent payload audit matched **76 compiled application/shared modules plus the entry point** to source and **4,259 data files** to their source trees. All 76 module implementations also match public 0.6.55; the scientific and application implementation is unchanged. The data audit covers UI, guides, 127 KIs, system KIs, model recipes, shared helpers and the calibration framework.

The build source is `59dfcbec0ae0482d8cdaab6646b02b3aa87ac8dc`; subsequent release commits contain README and this report only. `Windows-release-validation.json` records both the build and final release-tag commits. The executable SHA-256 is `b69951a877ffcf450fb9694959d01b3122c9d2723827f518c32205139b05f158`.

| Release asset | Bytes | SHA-256 |
|---|---:|---|
| `GeoForge-Desktop-Setup-v0.6.56-Windows-x64.exe` | 154,149,516 | `09d48b0462bad067ce3b36e6a0c23974312f8e08480df9b172328fa36bc13fa9` |
| `GeoForge-Desktop-v0.6.56-Windows-x64.zip` | 225,841,300 | `1c1ca173d61d2ee6a27d54b2c61efb30daddcf537a538ca8a9237dfee27840ec` |

## Inherited scientific evidence and scope

The earlier [0.6.55 acceptance](WINDOWS_RELEASE_0.6.55_2026-10-02.md), [CRHM/VIC/SHAW official-example runs](WINDOWS_E2E_CRHM_VIC_SHAW_2026-10-01.md), and [native SHAW calibration/reference-recovery checks](WINDOWS_CALIBRATION_2026-10-02.md) remain dated evidence for the unchanged implementation. Their full-suite and scientific-run counts are not presented as fresh 0.6.56 runs. No new paid AI turn, native model experiment or authenticated GeoForge Database transfer was performed for this documentation and packaging update.

Model software and KDT are installed separately when needed. KI presence, installation readiness and structural KI checks do not validate the science of a new study. Database access requires separate activation; some data deliveries require user involvement. The earlier documented installation assistance and CLI supervision limits still apply.

Release: [Windows 0.6.56](https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/windows-v0.6.56). All assets are covered by `SHA256SUMS-Windows.txt`. Earlier Windows releases and separate macOS/Linux assets remain available.
