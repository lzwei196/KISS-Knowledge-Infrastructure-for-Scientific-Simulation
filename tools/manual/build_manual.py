"""Build the GeoForge Desktop guides (HTML and PDF) from Markdown source.

    python tools/manual/build_manual.py --version 0.6.55 --install-web-guides

Sources: docs/manual/<version>/{src,quickstart,calibration}/<lang>/NN-*.md.
Output: docs/manual/<version>/GeoForge-Desktop-<KIND>-<LANG>-v<version>.html/.pdf
PDFs use headless Chrome or Edge; quickstart page counts use PyMuPDF or pypdf.
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

REPO = Path(__file__).resolve().parents[2]
TITLES = {
    "en": ("GeoForge Desktop", "User manual", "Contents", "Version"),
    "zh-CN": ("GeoForge 桌面版", "使用手册", "目录", "版本"),
}
KINDS = {
    "manual": ("Manual", {"en": "User manual", "zh-CN": "使用手册"}),
    "quickstart": ("Quickstart", {"en": "Quickstart · 3 pages", "zh-CN": "快速上手 · 3 页"}),
    "calibration": ("Calibration", {"en": "Calibration guide", "zh-CN": "参数校准指南"}),
}
CSS = """
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
:root { --ink:#1d2530; --mute:#5b6675; --line:#dde3ea; --accent:#2f6fe4; --warn:#a15c00; --soft:#f4f7fb; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", system-ui, sans-serif;
  color: var(--ink); font-size: 10.5pt; line-height: 1.55; margin: 0; }
.cover { height: 250mm; display: flex; flex-direction: column; justify-content: center; page-break-after: always; }
.cover h1 { font-size: 34pt; margin: 0 0 4mm; } .cover .sub { font-size: 16pt; color: var(--mute); }
.cover .ver { margin-top: 14mm; color: var(--mute); }
.toc { page-break-after: always; } .toc h2 { border: 0; }
.toc ul { list-style: none; padding-left: 0; } .toc li { margin: 2mm 0; font-size: 11.5pt; }
.toc a { color: var(--ink); text-decoration: none; }
section.chapter { page-break-before: always; }
h1 { font-size: 21pt; margin: 0 0 4mm; color: var(--ink); }
h2 { font-size: 14pt; margin: 7mm 0 2mm; padding-bottom: 1mm; border-bottom: 1px solid var(--line); }
h3 { font-size: 11.5pt; margin: 5mm 0 1.5mm; }
p, li { orphans: 3; widows: 3; }
img { max-width: 100%; max-height: 150mm; display: block; margin: 3mm auto 1.5mm; border: 1px solid var(--line);
  border-radius: 6px; page-break-inside: avoid; }
code { font-family: Consolas, "Cascadia Mono", Menlo, monospace; font-size: 9.5pt; background: var(--soft);
  padding: 0 1.2mm; border-radius: 3px; }
pre { background: var(--soft); padding: 3mm; border-radius: 5px; overflow-wrap: anywhere; white-space: pre-wrap; }
pre code { padding: 0; background: none; }
table { border-collapse: collapse; width: 100%; margin: 3mm 0; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid var(--line); padding: 1.6mm 2.2mm; text-align: left; vertical-align: top; }
th { background: var(--soft); }
blockquote { margin: 3mm 0; padding: 2.4mm 3.5mm; border-left: 3px solid var(--accent); background: var(--soft);
  border-radius: 0 5px 5px 0; page-break-inside: avoid; }
blockquote p { margin: 0.5mm 0; }
blockquote.caution { border-left-color: var(--warn); background: #fff6e9; }
blockquote.todo { border-left-color: #b03a2e; background: #fdecea; }
a { color: var(--accent); }
@media screen { body { max-width: 860px; margin: 0 auto; padding: 24px; } .cover { height: auto; padding: 60px 0; } }
"""
QUICKSTART_CSS = """
@page { size:A4; margin:12mm 14mm; }
body { font-size:10.2pt; line-height:1.42; }
section.chapter { page-break-before:auto; break-after:page; }
section.chapter:last-child { break-after:auto; }
h1 { font-size:23pt; margin:0 0 3mm; }
h2 { font-size:13pt; margin:4mm 0 2mm; }
h3 { font-size:11pt; margin:3mm 0 1mm; }
p { margin:2mm 0; } li { margin:1.5mm 0; }
ul,ol { margin:2mm 0; padding-left:6mm; }
img { max-height:58mm; max-width:100%; object-fit:contain; }
table { font-size:9pt; } code { font-size:9pt; }
.page-kicker { color:#2f6fe4; font-weight:600; letter-spacing:.05em; margin-bottom:2mm; }
.page-footer { border-top:1px solid #dde3ea; margin-top:4mm; padding-top:2mm; color:#5b6675; font-size:8.5pt; }
blockquote { padding:2mm 3mm; margin:2mm 0; }
@media screen { section.chapter { border-bottom:1px solid #dde3ea; padding:16px 0 28px; } }
"""


EMBED_WIDTH = 1600   # px; screenshots are captured at 2560 px, which only bloats the page


def image_data(path: Path) -> tuple[str, bytes]:
    """The image as embedded: downscaled to EMBED_WIDTH and stored as JPEG (which PDF printing keeps as is) when Pillow is available."""
    try:
        from PIL import Image
    except ImportError:
        return "image/png", path.read_bytes()
    with Image.open(path) as img:
        img = img.convert("RGB")
        if img.width > EMBED_WIDTH:
            img = img.resize((EMBED_WIDTH, round(img.height * EMBED_WIDTH / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88, optimize=True, subsampling=0)
    return "image/jpeg", buf.getvalue()


def nested_fences(md_text: str) -> str:
    """Python-Markdown's fenced_code ignores fences inside list items: turn an
    indented ```fence``` into the indented code block that lists do support."""
    def block(match: re.Match) -> str:
        indent, body = match.group(1), match.group(2)
        lines = [line[len(indent):] if line.startswith(indent) else line.lstrip() for line in body.splitlines()]
        return "\n".join(indent + "    " + line for line in lines)
    return re.sub(r"^( +)```[\w-]*\n(.*?)\n\1```[ \t]*$", block, md_text, flags=re.M | re.S)


def chapter_html(md_text: str, image_root: Path) -> tuple[str, str]:
    md_text = nested_fences(md_text)
    title = next((line[2:].strip() for line in md_text.splitlines() if line.startswith("# ")), "")
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists", "attr_list", "toc"],
                             extension_configs={"toc": {"slugify": slugify_unicode}})

    def embed(match: re.Match) -> str:
        src = match.group(2)
        path = (image_root / Path(src).name) if not src.startswith("data:") else None
        if path and path.is_file():
            mime, raw = image_data(path)
            src = f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        return f'{match.group(1)}"{src}"'

    body = re.sub(r'(<img[^>]*?src=)"([^"]+)"', embed, body)
    # Style the callouts by their first bold word.
    body = re.sub(r"<blockquote>\s*<p><strong>(Caution|注意|警告)", r'<blockquote class="caution"><p><strong>\1', body)
    body = re.sub(r"<blockquote>\s*<p><strong>\[(Screenshot to add|To be completed|待补充截图|待 GeoForge)",
                  r'<blockquote class="todo"><p><strong>[\1', body)
    return title, body


def build(version: str, lang: str, pdf: bool, kind: str = "manual") -> list[Path]:
    root = REPO / "docs" / "manual" / version
    source_root = root / "src" / lang if kind == "manual" else root / kind / lang
    src = sorted(source_root.glob("[0-9][0-9]-*.md"))
    if not src:
        raise SystemExit(f"no chapters in {source_root}")
    name, _, contents, ver_word = TITLES.get(lang, TITLES["en"])
    filename_kind, subtitles = KINDS[kind]
    subtitle = subtitles.get(lang, subtitles["en"])
    if kind == "quickstart" and len(src) != 3:
        raise SystemExit("quickstart must have exactly three source pages")
    chapters = []
    for i, path in enumerate(src):
        title, body = chapter_html(path.read_text(encoding="utf-8"), root / "images" / lang)
        chapters.append((f"ch{i:02d}", title, body))
    toc = "".join(f'<li><a href="#{cid}">{html.escape(t)}</a></li>' for cid, t, _ in chapters)
    front = (f'<div class="cover"><h1>{name}</h1><div class="sub">{subtitle}</div>'
             f'<div class="ver">{ver_word} {version} · Windows</div></div>'
             f'<div class="toc"><h2>{contents}</h2><ul>{toc}</ul></div>')
    if kind == "quickstart":
        front = ""
        chapters = [(cid, title, f'<div class="page-kicker">GEOFORGE DESKTOP {version} / {i + 1} OF 3</div>' + body
                     + f'<div class="page-footer">{html.escape(subtitle)} · {i + 1} / 3 · GeoForge {version}</div>')
                    for i, (cid, title, body) in enumerate(chapters)]
    doc = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{name} · {subtitle}</title>'
           f"<style>{CSS}{QUICKSTART_CSS if kind == 'quickstart' else ''}</style></head><body>"
           + front
           + "".join(f'<section class="chapter" id="{cid}">{body}</section>' for cid, _, body in chapters)
           + "</body></html>")
    tag = {"en": "EN", "zh-CN": "ZH-CN"}.get(lang, lang)
    out_html = root / f"GeoForge-Desktop-{filename_kind}-{tag}-v{version}.html"
    out_html.write_text(doc, encoding="utf-8")
    outputs = [out_html]
    if pdf:
        out_pdf = out_html.with_suffix(".pdf")
        chrome = next((p for p in (os.environ.get("CHROME"),
                                   r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                                   r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                                   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
                       if p and Path(p).is_file()), None)
        if not chrome:
            raise SystemExit("Chrome or Edge is needed to print the PDF (or pass --no-pdf)")
        profile = tempfile.mkdtemp(prefix="manual-pdf-")
        try:
            subprocess.run([chrome, "--headless=new", f"--user-data-dir={profile}", "--no-pdf-header-footer",
                            f"--print-to-pdf={out_pdf}", out_html.as_uri()],
                           check=True, capture_output=True, timeout=300)
        finally:
            shutil.rmtree(profile, ignore_errors=True)
        outputs.append(out_pdf)
        if kind == "quickstart":
            try:
                import pymupdf
                with pymupdf.open(out_pdf) as document:
                    count = len(document)
            except ImportError:
                from pypdf import PdfReader
                count = len(PdfReader(out_pdf).pages)
            if count != 3:
                raise SystemExit(f"quickstart must be exactly 3 PDF pages, got {count}: {out_pdf}")
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default="0.6.55")
    parser.add_argument("--langs", default="en,zh-CN")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--kinds", default="manual,quickstart,calibration")
    parser.add_argument("--install-web-guides", action="store_true",
                        help="Copy final self-contained HTML/PDFs into the bundled offline guide folder")
    args = parser.parse_args()
    for lang in args.langs.split(","):
        for kind in args.kinds.split(","):
            kind = kind.strip()
            if kind not in KINDS:
                parser.error(f"unknown guide kind: {kind}")
            for path in build(args.version, lang.strip(), not args.no_pdf, kind):
                print(f"{path}  ({path.stat().st_size // 1024} KB)")
                if args.install_web_guides:
                    destination = REPO / "kiss/kiss_cli/web/guides" / f"{kind}-{lang.strip()}{path.suffix}"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, destination)


if __name__ == "__main__":
    main()
