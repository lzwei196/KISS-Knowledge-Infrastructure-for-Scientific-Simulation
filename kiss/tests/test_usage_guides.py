"""Offline usage documents stay reachable in packaged Desktop layouts."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from kiss_cli import gui


def _get(path: str):
    handler = object.__new__(gui.Handler)
    handler.path = path
    responses = []
    handler._send = lambda *response: responses.append(response)
    handler.do_GET()
    assert len(responses) == 1
    return responses[0]


@pytest.mark.parametrize("kind", ["manual", "quickstart", "calibration"])
@pytest.mark.parametrize("language", ["en", "zh-CN"])
@pytest.mark.parametrize("extension", ["html", "pdf"])
def test_offline_guide_routes_use_bundled_web_assets(tmp_path, monkeypatch, kind, language, extension):
    web = tmp_path / "frozen" / "kiss_cli" / "web"
    (web / "guides").mkdir(parents=True)
    monkeypatch.setattr(gui, "PAGE", web / "app.html")
    body = ("<h1>真实离线指南</h1>".encode("utf-8") if extension == "html"
            else b"%PDF-1.7\n\x80\xffbinary content")
    (web / "guides" / f"{kind}-{language}.{extension}").write_bytes(body)

    code, received, content_type = _get(f"/guide/{kind}/{language}.{extension}?from=usage")
    assert code == 200
    assert received == body
    assert content_type == ("application/pdf" if extension == "pdf" else "text/html; charset=utf-8")


@pytest.mark.parametrize("route", [
    "/guide/../app.html", "/guide/manual/../../app.html",
    "/guide/manual/%2e%2e%2fapp.html", "/guide/manual/en.html/extra",
    "/guide/manual/en.txt", "/guide/unknown/en.html", "/guide/manual/fr.html",
    "/guide/manual/en%5c..%5capp.html",
])
def test_guide_route_does_not_serve_arbitrary_files(route):
    code, body, content_type = _get(route)
    assert code == 404
    assert json.loads(body)["error"] == "unknown usage guide"


@pytest.mark.parametrize("language, message", [("en", b"Please reinstall"), ("zh-CN", "请重新安装".encode())])
def test_missing_guide_explains_packaging_problem(tmp_path, monkeypatch, language, message):
    monkeypatch.setattr(gui, "PAGE", tmp_path / "app.html")
    code, body, content_type = _get(f"/guide/quickstart/{language}.pdf")
    assert code == 503
    assert message in body
    assert content_type == "text/html; charset=utf-8"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed for the UI language check")
def test_usage_links_follow_selected_ui_language():
    page = gui.PAGE.read_text(encoding="utf-8")
    script = page.split("function updateGuideLinks(){", 1)[1].split('\n$("#help").onclick=', 1)[0]
    code = """
const vm=require('node:vm');
const links=['quickstart','manual','calibration'].flatMap(guide=>
  ['html','pdf'].map(guideFormat=>({dataset:{guide,guideFormat},href:''})));
let chinese=false;
const context={chineseUI:()=>chinese,document:{querySelectorAll:()=>links}};
vm.createContext(context);
vm.runInContext('function updateGuideLinks(){'+JSON.parse(process.argv[1]),context);
context.updateGuideLinks();
const english=links.map(link=>link.href);
chinese=true;context.updateGuideLinks();
console.log(JSON.stringify([english,links.map(link=>link.href)]));
"""
    result = subprocess.run([shutil.which("node"), "-e", code, json.dumps(script)],
                            check=True, capture_output=True, text=True, encoding="utf-8")
    english, chinese = json.loads(result.stdout)
    assert english == [f"/guide/{kind}/en.{ext}" for kind in ("quickstart", "manual", "calibration")
                       for ext in ("html", "pdf")]
    assert chinese == [route.replace("/en.", "/zh-CN.") for route in english]
