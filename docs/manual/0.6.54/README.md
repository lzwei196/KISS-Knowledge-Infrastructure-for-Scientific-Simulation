# GeoForge Desktop manual 0.6.54 — source

| Path | What it is |
|---|---|
| `GeoForge-Desktop-Manual-EN-v0.6.54.pdf`, `…-ZH-CN-….pdf` | The built manuals |
| `src/en/NN-*.md`, `src/zh-CN/NN-*.md` | Chapter source, one file per chapter, same names in both languages |
| `images/en/`, `images/zh-CN/` | Screenshots from the real app (2560 × 1640 or 2560 × 1800), same names in both languages |
| `STYLE.md` | Writing rules for both editions |
| `worked-example-timeline.json` | Timing of the FSM2 Alptal run shown in Chapter 5 |

## Build

```
python tools/manual/build_manual.py              # both languages, HTML and PDF
python tools/manual/build_manual.py --langs en --no-pdf
```

Needs Python with `markdown` (and Pillow, to embed smaller copies of the screenshots) and Chrome or Edge for the PDF. The HTML is written next to the PDF and is not committed (it embeds every image).

## Recapture the screenshots

All capture scripts drive headless Chrome over the DevTools protocol (`tools/manual/cdp.mjs`, Node 22, no npm packages). Start GeoForge with a clean demo work folder first, for example:

```
"GeoForge Desktop.exe" gui --port 8801 --no-browser --workroot D:\GeoForge-Manual
```

| Script | Captures |
|---|---|
| `capture_static.mjs` | Home, Settings pages, New chat dialog, Guide, KI Library, Observatory, Studio, empty chat, KI picker (01–13) |
| `capture_setup.mjs --prefix 14` / `--prefix 44` | KI Library entry and Agent setup page before / after FSM2 is verified |
| `capture_live.mjs [--fresh]` | The worked example: pins FSM2, sends the request, answers each question with its recommended option, asks for a plan change when the card says "Not ready to execute yet", approves, and captures every state (20–43). Makes real AI calls. |
| `capture_state.mjs --name NN-x [--scroll-to "text"]` | The current chat and Project status, read-only |

`capture_live.mjs` never reloads the tab that sends messages while a turn runs: in the 0.6.54 Windows build a reloaded tab ends the turn. Mid-run pictures come from that tab, switched to Chinese in place for the Chinese shots.

Screenshots `30-setup-running`, `31-setup-status`, `50-*` and `53-*` come from the first project (FSM2 not yet verified; the project that did not reach Completed); the rest of the worked example comes from the run in `worked-example-timeline.json`.
