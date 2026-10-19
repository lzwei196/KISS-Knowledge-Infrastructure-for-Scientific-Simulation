"""Render permission requests with the real shipped summary and escaping code."""
import html
import json
import subprocess

import pytest

from .test_setup_verification_ui import NODE, PAGE, RUNNER as SETUP_RUNNER


pytestmark = pytest.mark.skipif(NODE is None, reason="Node is required")

# Reuse the DOM/transport fixture, but remove its summary stub and explicitly
# load the production summary, permission classification, escaping and draw().
RUNNER = SETUP_RUNNER.replace(
    "managedWorkspacePermission:()=>false,requestSummary:r=>r.message,",
    "",
).replace(
    "shipped('function activeSetupJob(','function fmtSize(');",
    """const escStart=page.indexOf('const esc=');
vm.runInContext(page.slice(escStart,page.indexOf('\\n',escStart)),context);
shipped('function managedWorkspacePermission(','function drawLLM(');
shipped('function activeSetupJob(','function fmtSize(');""",
).replace(
    "__calls:[...calls],",
    "__summary:context.requestSummary(context.STATE.request),__calls:[...calls],",
)


def render(request, zh):
    state = {
        "name": "WRF_Hydro", "workdir": "/home/user/wrf_hydro",
        "software": {"state": "setup", "can_run": False},
        "request": {"kind": "permission", "status": "waiting", **request},
        "install_location": {"installation_mode": "existing"},
        "job": None,
    }
    result = subprocess.run(
        [NODE, "-e", RUNNER, str(PAGE)],
        input=json.dumps({"states": [state], "zh": zh}),
        capture_output=True, text=True, encoding="utf-8", check=True, timeout=10,
    )
    return json.loads(result.stdout)[0]


def escaped(value):
    return html.escape(value, quote=False).replace('"', "&quot;")


@pytest.mark.parametrize("zh", [False, True])
def test_long_package_permission_uses_neutral_summary_preserves_full_request(zh):
    message = (
        'Native verification failed; package updates need permission. <script>bad()</script> & "quoted"\n'
        + "APT provenance check requires authenticated package updates. " * 20
    )
    command = 'sudo apt-get install "libnetcdff-dev=4.5.4" && echo "<pending>"'
    result = render({"title": "Permission <needed>", "message": message, "command": command}, zh)
    expected = (
        "设置需要完成下面的操作。继续前请展开查看完整说明。" if zh else
        "Setup requires the action below. Expand the full explanation before continuing."
    )
    assert result["__summary"] == expected
    content = result["#need"]["html"]
    assert f"<p>{expected}</p>" in content
    assert "local toolchain are ready" not in content
    assert "工具链已经准备好" not in content
    assert f'<div class="request-report">{escaped(message)}</div>' in content
    assert f"<code>{escaped(command)}</code>" in content
    assert "<script>" not in content and "<needed>" not in content
    assert ("查看完整技术报告" if zh else "View the full technical report") in content
    assert 'id="resume"' in content and not result["#resume"]["disabled"]
    assert ("我已完成 — 继续" if zh else "I've done this — continue") in content


@pytest.mark.parametrize("zh", [False, True])
@pytest.mark.parametrize("length", [80, 650])
def test_short_permission_retains_original_text_and_escapes_it(zh, length):
    prefix = '<img src=x onerror="bad()"> & approval needed. '
    message = prefix + "x" * (length - len(prefix))
    result = render({"title": "Permission", "message": message}, zh)
    assert result["__summary"] == message
    content = result["#need"]["html"]
    assert f"<p>{escaped(message)}</p>" in content
    assert "<img" not in content
    assert 'class="request-report"' not in content
    assert 'id="resume"' in content and not result["#resume"]["disabled"]
