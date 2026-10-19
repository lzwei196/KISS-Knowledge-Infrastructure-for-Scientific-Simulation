"""Exercise shipped file-card rendering and the actual API/CLI view guidance."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from kiss_cli import api, gui

PAGE = Path(__file__).parents[1] / 'kiss_cli/web/app.html'
NODE = shutil.which('node')
RUNNER = r'''
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const page=fs.readFileSync(process.argv[1],'utf8').replaceAll('\r\n','\n');
function fn(name){
  const start=page.indexOf('function '+name+'('), first=page.indexOf('\n',start);
  if(start<0)throw Error('Missing shipped function '+name);
  if(page.slice(start,first).endsWith('}'))return page.slice(start,first);
  const end=page.indexOf('\n}',start);if(end<start)throw Error('Unclosed function');
  return page.slice(start,end+2);
}
const ctx=vm.createContext({CUR:{id:input.sid||'case'},chineseUI:()=>!!input.zh,
  esc:v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])),
  encodeURIComponent});
for(const name of ['viewAsset','viewTable','viewPanel','projectViewPrompt'])vm.runInContext(fn(name),ctx);
ctx.panel=input.panel;
console.log(JSON.stringify(input.mode==='prompt'?vm.runInContext('projectViewPrompt()',ctx):vm.runInContext('viewPanel(panel)',ctx)));
'''


def render(panel=None, **kwargs):
    if NODE is None:
        pytest.skip('Node is needed to execute the shipped view renderer')
    result = subprocess.run([NODE, '-e', RUNNER, str(PAGE)],
        input=json.dumps({'panel': panel, **kwargs}), capture_output=True,
        text=True, check=True, encoding='utf-8')
    return json.loads(result.stdout)


def test_real_json_file_card_links_original_path_and_filename():
    path = 'outputs/DSSAT/gainesville_verified/replay_receipt.json'
    html = render({'id': 'report', 'kind': 'file', 'title': 'Native replay report',
                   'path': path, 'mime': 'application/json'})
    assert 'class="view-file"' in html and ' download="replay_receipt.json"' in html
    assert f'path={path.replace("/", "%2F")}' in html
    assert f'<span>{path}</span>' in html
    assert '<img' not in html and '<video' not in html
    assert 'scientific' not in html and 'verified</' not in html


@pytest.mark.parametrize('mime', ['image/svg+xml', 'image/png', 'video/mp4'])
def test_explicit_file_kind_does_not_become_media_by_mime(mime):
    html = render({'kind': 'file', 'path': 'artifacts/existing.svg', 'mime': mime})
    assert 'class="view-file"' in html and 'artifacts/existing.svg' in html
    assert '<img' not in html and '<video' not in html


@pytest.mark.parametrize('kind,mime,tag', [('image', 'image/svg+xml', '<img'),
                                         ('animation', 'video/mp4', '<video'),
                                         ('model3d', 'model/gltf-binary', '>3D<')])
def test_existing_media_and_model_cards_keep_their_renderer(kind, mime, tag):
    html = render({'kind': kind, 'path': 'artifacts/result.svg', 'mime': mime})
    assert tag in html and ' download=' not in html


def test_file_card_escapes_text_and_uses_only_its_session_asset_endpoint():
    path = 'outputs/<img src=x onerror=alert(1)>&report.json'
    html = render({'kind': 'file', 'path': path, 'title': '<script>bad</script>',
                   'caption': '<iframe src=evil>', 'url': 'https://evil.example'}, sid='a/b?c')
    assert '/api/session/a%2Fb%3Fc/view-asset?path=outputs%2F%3Cimg' in html
    assert '&lt;script&gt;' in html and '&lt;iframe' in html
    assert '<script' not in html and '<img' not in html and 'evil.example' not in html


@pytest.mark.parametrize('zh', [False, True])
@pytest.mark.parametrize('evidence', ['receipt_bound', 'unvalidated', None])
def test_output_media_visibly_distinguishes_technical_receipt_from_unvalidated_file(zh, evidence):
    html = render({'kind': 'image', 'path': 'outputs/run/profile.png', 'mime': 'image/png',
                   'file_provenance': {'scope': 'technical-file-association'}, 'evidence': evidence}, zh=zh)
    assert '<img' in html and 'view-evidence' in html
    if evidence == 'receipt_bound':
        assert ('不代表科学验证通过' if zh else 'does not establish scientific validation') in html
    else:
        assert ('文件未验证' if zh else 'Unvalidated file') in html
        assert ('当前有效回执' if zh else 'current receipt') in html


def test_legacy_artifact_renderer_does_not_gain_output_receipt_badge():
    html = render({'kind': 'image', 'path': 'artifacts/result.png', 'mime': 'image/png',
                   'evidence': 'unvalidated', 'title': 'Result — experimental / unvalidated'})
    assert 'view-evidence' not in html and 'experimental / unvalidated' in html


@pytest.mark.parametrize('zh', [False, True])
def test_composer_guidance_links_existing_reports_without_copying(zh):
    text = render(mode='prompt', zh=zh)
    assert 'outputs/**/*.json' in text and 'artifacts/' in text
    if zh:
        assert '不要用图表代替报告' in text and '复制报告' in text and '不代表科学验证' in text
    else:
        assert 'Never substitute a chart for a report' in text
        assert 'copy report bytes' in text and 'does not establish scientific validation' in text


def test_api_publish_tool_uses_same_direct_report_scope():
    tool = next(t for t in api.tool_schemas(None, project_mode=True)
                if t['name'] == 'publish_project_view')
    text = tool['description']
    assert 'outputs/**/*.json' in text and 'kind=file' in text
    assert 'Media paths' in text and 'artifacts/' in text
    assert 'Never substitute a chart' in text and 'copy report bytes' in text
    assert 'does not establish scientific validation' in text
    assert 'file' in tool['input_schema']['properties']['panels']['items']['properties']['kind']['enum']


def test_shared_cli_prompt_uses_same_direct_report_scope():
    text = gui.AUTOMATIC_SKILL_RULES
    assert '`file` panel' in text and '`outputs/**/*.json`' in text
    assert 'media need a `path` below `artifacts/`' in text
    assert 'Never substitute a chart' in text and 'copy report bytes' in text
    assert 'does not establish\n  scientific validation' in text


def test_installation_only_tools_still_cannot_publish_project_views():
    assert 'publish_project_view' not in {
        t['name'] for t in api.tool_schemas(None, project_mode=True, installation_only=True)}
