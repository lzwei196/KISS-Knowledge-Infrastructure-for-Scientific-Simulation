# GeoForge Desktop guides 0.6.55

Windows release: [`windows-v0.6.55`](https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/windows-v0.6.55).

These guides are also bundled with [Windows 0.6.56](https://github.com/lzwei196/KISS-Knowledge-Infrastructure-for-Scientific-Simulation/releases/tag/windows-v0.6.56), whose installer and portable app include the illustrated quickstart revision. The 0.6.55 guide edition still describes the unchanged application workflow.

The quickstart was revised on 2026-10-02 into an illustrated SHAW Trial walkthrough. Both languages retain exactly three pages, with real 0.6.55 screenshots for DeepSeek settings, SHAW setup and completed execution, plus a temperature preview drawn from the verified native run. The Chinese edition uses the Chinese interface and chart labels. The release's supplemental `Quickstart-Illustrated` downloads contain this revision; the original installer and portable package retain their original bundled guides.

| Guide | English | 简体中文 |
|---|---|---|
| Exactly three pages: agent setup, KI setup, real SHAW run | [Quickstart PDF](./GeoForge-Desktop-Quickstart-EN-v0.6.55.pdf) | [快速上手 PDF](./GeoForge-Desktop-Quickstart-ZH-CN-v0.6.55.pdf) |
| Detailed workflow, real screenshots, troubleshooting | [Full manual PDF](./GeoForge-Desktop-Manual-EN-v0.6.55.pdf) | [完整手册 PDF](./GeoForge-Desktop-Manual-ZH-CN-v0.6.55.pdf) |
| Calibration protocol, evidence, tested SHAW reference recovery | [Calibration PDF](./GeoForge-Desktop-Calibration-EN-v0.6.55.pdf) | [参数校准 PDF](./GeoForge-Desktop-Calibration-ZH-CN-v0.6.55.pdf) |

Matching self-contained HTML files are generated beside each PDF. The app's **Guide / 使用指南** menu opens local HTML or PDF in the current UI language. It serves `/guide/{quickstart,manual,calibration}/{en,zh-CN}.{html,pdf}` from the bundled `kiss/kiss_cli/web/guides/` folder.

## Sources and scope

- `src/<language>/`: full manual; Chapter 10 contains the calibration guide, Chapter 11 documents the verified Windows examples.
- `quickstart/<language>/`: exactly three source files, one per PDF page.
- `calibration/<language>/`: separate calibration guide, also included in the full manual.
- `images/<language>/`: genuine app screenshots. The detailed FSM2 walkthrough preserves the 0.6.54 screenshots with an edition note; `07-guide.png` was captured from the 0.6.55 interface.
- `images/<language>/quickstart-01-agent.png` through `quickstart-03-run.png`: focused captures from the actual 0.6.55 application, with the API key masked. `quickstart-04-result.png` is a guide preview of the completed Trial's temperature CSV, not a screenshot of the app's full five-panel plot.
- `STYLE.md`: editorial rules. Prior editions remain intact in their own folders.

The SHAW quickstart uses the public official archive and five original Trial inputs. The calibration benchmark targets the publisher's reference temperature output; it does **not** use field observations or establish predictive scientific skill.

## Rebuild

```powershell
py -3.11 tools/manual/build_manual.py --version 0.6.55 --install-web-guides
```

Requires Python with `markdown`, Pillow, and either PyMuPDF or pypdf, plus Chrome or Edge. `--kinds quickstart` builds only that guide; `--langs en` selects one language; `--no-pdf` generates HTML only. The builder refuses quickstart PDFs whose page count is not three. To rebuild older editions, select their available kinds explicitly, for example `--version 0.6.54 --kinds manual`.

After changing calibration Markdown, copy the same content into full-manual Chapter 10 with headings nested one level deeper. Build all six PDFs, render them with Poppler, inspect the pages and copy all 12 final artifacts into the offline folder before packaging. The release pipeline must attach all six PDFs using their exact filenames above.
