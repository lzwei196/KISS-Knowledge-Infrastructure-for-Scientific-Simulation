"""Build the GeoForge Desktop manual (HTML and PDF) from its Markdown source.

    python tools/manual/build_manual.py [--version 0.6.54] [--langs en,zh-CN] [--no-pdf]

Source: docs/manual/<version>/src/<lang>/NN-*.md and images/<lang>/*.png.
Output: docs/manual/<version>/GeoForge-Desktop-Manual-<LANG>-v<version>.html/.pdf
The PDF is printed by headless Chrome or Edge; no other tools are needed.
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


def build(version: str, lang: str, pdf: bool) -> list[Path]:
    root = REPO / "docs" / "manual" / version
    src = sorted((root / "src" / lang).glob("[0-9][0-9]-*.md"))
    if not src:
        raise SystemExit(f"no chapters in {root / 'src' / lang}")
    name, subtitle, contents, ver_word = TITLES.get(lang, TITLES["en"])
    chapters = []
    for i, path in enumerate(src):
        title, body = chapter_html(path.read_text(encoding="utf-8"), root / "images" / lang)
        chapters.append((f"ch{i:02d}", title, body))
    toc = "".join(f'<li><a href="#{cid}">{html.escape(t)}</a></li>' for cid, t, _ in chapters)
    doc = (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><title>{name} · {subtitle}</title>'
           f"<style>{CSS}</style></head><body>"
           f'<div class="cover"><h1>{name}</h1><div class="sub">{subtitle}</div>'
           f'<div class="ver">{ver_word} {version} · Windows &amp; macOS</div></div>'
           f'<div class="toc"><h2>{contents}</h2><ul>{toc}</ul></div>'
           + "".join(f'<section class="chapter" id="{cid}">{body}</section>' for cid, _, body in chapters)
           + "</body></html>")
    tag = {"en": "EN", "zh-CN": "ZH-CN"}.get(lang, lang)
    out_html = root / f"GeoForge-Desktop-Manual-{tag}-v{version}.html"
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
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", default="0.6.54")
    parser.add_argument("--langs", default="en,zh-CN")
    parser.add_argument("--no-pdf", action="store_true")
    args = parser.parse_args()
    for lang in args.langs.split(","):
        for path in build(args.version, lang.strip(), not args.no_pdf):
            print(f"{path}  ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
