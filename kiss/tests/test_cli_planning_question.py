"""Native CLI question transport, with real serialization and host request handling.

The provider subprocess/socket are replaced; the emitted helper, request parser,
capability check, registered-project resolution and turn gate are real. No live
provider, credentials, database, model or acquisition is used.
"""
from __future__ import annotations

import io
import hashlib
import hmac
import json
import shlex
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from kiss_cli import cli, execution, flowrun, gui, projectrun, sessions, setup as setup_flow


QUESTION = {
    "kind": "choice", "title": "Which forcing source?",
    "message": "The KI documents Source A for this study. Choose a source before the plan is finalized.",
    "options": [
        {"id": "source-a", "label": "Source A (recommended)",
         "description": "Evidence: KI/docs/forcing.md", "response": "Use Source A"},
        {"id": "own-files", "label": "Use my files", "response": "I will provide my files"},
    ],
    "allow_note": True,
}


def test_question_progress_keeps_the_actual_card_and_all_candidates(project_case):
    payload = {**QUESTION, "options": [
        {"id": f"source-{i}", "label": f"Source {i}"} for i in range(12)]}
    card = flowrun.request_planning_question(project_case.project, payload)
    state = projectrun.load(project_case.project)
    assert state["stage"] == "planning"
    assert state["status"] == "waiting_for_user"
    assert state["blocker"]["kind"] == "choice"
    assert state["blocker"]["title"] == card["title"]
    assert state["blocker"]["options"] == card["options"]


@pytest.mark.parametrize("state,expected", [
    ("PLANNING", "planning"), ("PLAN_REVIEW", "planning"),
    ("REPLAN_REQUIRED", "planning"), ("ACQUIRING", "acquiring"),
    ("EXECUTING", "running"),
])
def test_phase_labels_separate_planning_acquisition_and_execution(state, expected):
    flow = flowrun._flow()
    assert flowrun.display_stage(flow, flow.states.State(state)) == expected


@pytest.fixture
def project_case(tmp_path, monkeypatch):
    monkeypatch.setenv("GEOFORGE_FLOW_KEYS", str(tmp_path / "keys"))
    monkeypatch.setenv("GEOFORGE_FLOW_REGISTRY", str(tmp_path / "registry"))
    workroot = tmp_path / "workroot"
    session = sessions.create(workroot, ["M"], "cli:kimi")
    project = sessions.project_path(workroot, session)
    ki_root = tmp_path / "kis" / "M"
    (ki_root / "tools").mkdir(parents=True)
    (ki_root / "SKILL.md").write_text("# M\nUse only the real model.\n", encoding="utf-8")
    (ki_root / "dag.yaml").write_text(
        "outputs:\n- var: discharge\n  validation_rank: 1\n  unit: m3/s\n"
        "processes:\n  modules:\n  - id: run\n    inputs: []\n    outputs: [discharge]\n",
        encoding="utf-8",
    )
    ki = SimpleNamespace(name="M", root=ki_root)
    cfg = SimpleNamespace(root=project, python=sys.executable, roles={})
    flowrun.pre(project, "run M for 2003", ["M"], [ki], None, None)
    launcher = tmp_path / "bin" / "geoforge-flow"
    launcher.parent.mkdir()
    launcher.write_text(flowrun._FLOW_HELPER, encoding="utf-8")
    monkeypatch.setattr(flowrun, "_launcher_path", lambda: launcher)
    monkeypatch.setattr(flowrun, "_database_launcher_path", lambda: None)
    monkeypatch.delenv("KISS_PROJECT", raising=False)
    turn_id = execution.begin_turn(project)
    monkeypatch.setenv("GEOFORGE_TURN_ID", turn_id)
    monkeypatch.setenv("GEOFORGE_TURN_PROJECT", str(project))
    return SimpleNamespace(project=project, workroot=workroot, ki=ki, cfg=cfg,
                           launcher=launcher, turn_id=turn_id)


def _bridge(case, body, capability="test-capability", question_capability=None):
    """Call the real route method without a TCP port or HTTP test server."""
    handler = gui.Handler.__new__(gui.Handler)
    handler.workroot = case.workroot
    handler.agent_database_token = "test-capability"
    handler.headers = {"X-GeoForge-Agent-Token": capability}
    if question_capability is not None:
        handler.headers["X-GeoForge-Question-Token"] = question_capability
    handler.rfile = io.BytesIO(body)
    response = {}

    def respond(value, code=200):
        response.update(code=code, value=value)

    handler._json = respond
    handler._post_agent_flow_command(len(body))
    return response


def _run_helper(case, cwd, monkeypatch, payload=QUESTION):
    """Run the shipped launcher code against the route, not a hand-created card."""
    seen = []

    def urlopen(request, timeout=None):
        assert request.full_url == "http://127.0.0.1:12345/api/agent/flow-command"
        seen.append(json.loads(request.data))
        response = _bridge(case, request.data, request.get_header("X-geoforge-agent-token"),
                           request.get_header("X-geoforge-question-token"))
        data = json.dumps(response["value"]).encode()
        if response["code"] >= 400:
            raise urllib.error.HTTPError(request.full_url, response["code"], "rejected", {}, io.BytesIO(data))
        return io.BytesIO(data)

    monkeypatch.chdir(cwd)
    monkeypatch.setenv("GEOFORGE_AGENT_FLOW_URL", "http://127.0.0.1:12345/api/agent/flow-command")
    monkeypatch.setenv("GEOFORGE_AGENT_DATABASE_TOKEN", "test-capability")
    monkeypatch.setenv("GEOFORGE_AGENT_QUESTION_TOKEN", gui.Handler._question_capability(case.project))
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(sys, "argv", [str(case.launcher), "ask-question", json.dumps(payload)])
    namespace = {"__name__": "test_launcher"}
    exec(compile(flowrun._FLOW_HELPER, str(case.launcher), "exec"), namespace)
    rc = namespace["main"]()
    return rc, seen


@pytest.mark.parametrize("provider", ["claude", "kimi", "codex"])
def test_native_question_crosses_real_transport_and_pauses_without_plan_submission(
        project_case, provider, monkeypatch, capsys):
    case = project_case
    turn = flowrun.turn(case.project, [case.ki], case.cfg, "cli", provider, None,
                        "run M for 2003", database_access_mode="off")
    command = turn.wrappers["request_user_action"]
    assert shlex.split(command) == [str(case.launcher), "ask-question"]
    assert f"{command} '<JSON object>'" in turn.extra_prompt
    if provider == "claude":
        assert f"Bash({command}:*)" in " ".join(turn.policy.argv_delta)
        assert "setup-request.json" not in " ".join(turn.policy.argv_delta)
    cwd = turn.planning_worktree or case.project
    rc, requests = _run_helper(case, cwd, monkeypatch)
    assert rc == 0, capsys.readouterr().err
    assert requests == [{"argv": ["ask-question", json.dumps(QUESTION)], "cwd": str(cwd),
                         "turn_id": case.turn_id, "turn_project": str(case.project)}]
    question = setup_flow.request(case.project)
    assert question["status"] == "waiting" and question["title"] == QUESTION["title"]
    if cwd != case.project:
        assert not (cwd / setup_flow.REQUEST_FILE).exists()
    result = flowrun.after(case.project, turn, "Please choose the forcing source.")
    assert not result.retry_planning and not result.continue_now and result.request is None
    assert flowrun.current_state(case.project) == "PLANNING"
    assert not (case.project / "runs/approval.json").exists()
    assert not (case.project / "runs/plan-review.json").exists()
    assert not (case.project / "runs/plan-validation.txt").exists()


def test_question_is_idempotent_and_cannot_replace_an_unanswered_one(project_case):
    project = project_case.project
    first = flowrun.request_planning_question(project, QUESTION)
    before = (project / setup_flow.REQUEST_FILE).read_bytes()
    assert flowrun.request_planning_question(project, QUESTION)["id"] == first["id"]
    with pytest.raises(ValueError, match="already waiting"):
        flowrun.request_planning_question(project, {**QUESTION, "title": "A second question?"})
    assert (project / setup_flow.REQUEST_FILE).read_bytes() == before
    setup_flow.resume(project, "Use Source A")
    second = flowrun.request_planning_question(project, {**QUESTION, "title": "Which time period?"})
    assert second["id"] != first["id"]
    assert list(project.glob("setup-request-*.json"))


@pytest.mark.parametrize("payload", [
    [], {**QUESTION, "kind": "permission"}, {**QUESTION, "approval": True},
    {**QUESTION, "options": [{"id": "enable_https", "label": "Yes"}]},
    {**QUESTION, "options": [{"id": "approve", "label": "Yes"}]},
    {**QUESTION, "options": [{"id": "allow-kimi-read-once", "label": "Yes"}]},
    {**QUESTION, "options": [{"id": "same", "label": "A"}, {"id": "same", "label": "B"}]},
    {**QUESTION, "options": [{"label": "A", "command": "run model"}]},
    {**QUESTION, "title": ""}, {**QUESTION, "allow_note": "yes"},
])
def test_question_rejects_permission_approval_or_malformed_payloads(project_case, payload):
    with pytest.raises(ValueError):
        flowrun.request_planning_question(project_case.project, payload)
    assert not (project_case.project / setup_flow.REQUEST_FILE).exists()


@pytest.mark.parametrize("state", ["NEW", "EXECUTING", "ACQUIRING", "WAITING_FOR_USER", "COMPLETED"])
def test_question_is_refused_outside_planning_and_intake(project_case, monkeypatch, state):
    monkeypatch.setattr(flowrun, "current_state", lambda _project: state)
    with pytest.raises(ValueError, match="refused"):
        flowrun.request_planning_question(project_case.project, QUESTION)
    assert not (project_case.project / setup_flow.REQUEST_FILE).exists()


@pytest.mark.parametrize("state", ["PLANNING", "REPLAN_REQUIRED", "RESOLVING_KIS"])
def test_question_permitted_states(project_case, monkeypatch, state):
    monkeypatch.setattr(flowrun, "current_state", lambda _project: state)
    assert flowrun.request_planning_question(project_case.project, QUESTION)["status"] == "waiting"


def test_bridge_refuses_missing_capability_unregistered_cwd_and_project_override(project_case, tmp_path):
    case = project_case
    body = {"argv": ["ask-question", json.dumps(QUESTION)], "cwd": str(case.project)}
    assert _bridge(case, json.dumps(body).encode(), capability="wrong")["code"] == 401
    body["cwd"] = str(tmp_path / "unregistered")
    assert _bridge(case, json.dumps(body).encode())["code"] == 400
    body["cwd"] = str(case.project)
    body["argv"] += ["--project", str(case.project)]
    assert _bridge(case, json.dumps(body).encode())["code"] == 400
    assert not (case.project / setup_flow.REQUEST_FILE).exists()


def test_standalone_cli_uses_validator_and_parent_project_from_worktree(project_case, monkeypatch, capsys):
    case = project_case
    turn = flowrun.turn(case.project, [case.ki], case.cfg, "cli", "kimi", None, "run M")
    monkeypatch.chdir(turn.planning_worktree)
    assert cli.main(["ask-question", json.dumps(QUESTION)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "waiting"
    assert setup_flow.request(case.project)["title"] == QUESTION["title"]
    assert cli.main(["ask-question", "not JSON"]) == 3
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize("payload", [[], None, "not an object", 42])
def test_bridge_rejects_nonobject_envelopes_without_a_handler_crash(project_case, payload):
    result = _bridge(project_case, json.dumps(payload).encode())
    assert result["code"] == 400
    assert "JSON object" in result["value"]["message"]
    assert not (project_case.project / setup_flow.REQUEST_FILE).exists()


@pytest.mark.parametrize("token", [None, "", "wrong", "test-capability"])
def test_question_requires_separate_project_capability(project_case, token):
    case = project_case
    body = json.dumps({"argv": ["ask-question", json.dumps(QUESTION)],
                       "cwd": str(case.project)}).encode()
    response = _bridge(case, body, question_capability=token)
    assert response["code"] == 401
    assert not (case.project / setup_flow.REQUEST_FILE).exists()


def test_project_a_capability_cannot_create_project_b_question(project_case):
    case = project_case
    other = sessions.create(case.workroot, ["M"], "cli:kimi")
    other_project = sessions.project_path(case.workroot, other)
    flowrun.pre(other_project, "run M", ["M"], [case.ki], None, None)
    body = json.dumps({"argv": ["ask-question", json.dumps(QUESTION)],
                       "cwd": str(other_project)}).encode()
    project_a_token = gui.Handler._question_capability(case.project)
    assert project_a_token != gui.Handler._question_capability(other_project)
    response = _bridge(case, body, question_capability=project_a_token)
    assert response["code"] == 401
    assert not (case.project / setup_flow.REQUEST_FILE).exists()
    assert not (other_project / setup_flow.REQUEST_FILE).exists()
    # The same registered destination succeeds only with its own capability.
    response = _bridge(case, body, question_capability=gui.Handler._question_capability(other_project))
    assert response["code"] == 200
    assert setup_flow.request(other_project)["title"] == QUESTION["title"]


def test_runtime_env_scopes_question_capability_without_exposing_derivation_key(project_case, monkeypatch):
    case = project_case
    secret = b"host-only-question-signing-secret"
    monkeypatch.setattr(gui.Handler, "agent_question_secret", secret)
    monkeypatch.setattr(gui.Handler, "agent_database_token", "visible-app-token")
    monkeypatch.setattr(gui.Handler, "agent_database_url", "http://127.0.0.1/catalogue")
    monkeypatch.setattr(gui.Handler, "agent_flow_url", "http://127.0.0.1/flow")
    env = gui.Handler._agent_runtime_env(case.project)
    token = env["GEOFORGE_AGENT_QUESTION_TOKEN"]
    assert token == gui.Handler._question_capability(case.project)
    assert "GEOFORGE_AGENT_QUESTION_TOKEN" not in gui.Handler._agent_runtime_env()
    forged = hmac.new(b"visible-app-token", b"geoforge-question-v1\0" +
                      str(case.project.resolve()).encode(), hashlib.sha256).hexdigest()
    assert token != forged
    assert secret.decode() not in json.dumps(env)
    assert env["GEOFORGE_AGENT_DATABASE_TOKEN"] == "visible-app-token"


def test_helper_refuses_question_without_owning_project_token(project_case, monkeypatch, capsys):
    monkeypatch.setenv("GEOFORGE_AGENT_FLOW_URL", "http://127.0.0.1:12345/api/agent/flow-command")
    monkeypatch.setenv("GEOFORGE_AGENT_DATABASE_TOKEN", "test-capability")
    monkeypatch.delenv("GEOFORGE_AGENT_QUESTION_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", [str(project_case.launcher), "ask-question", json.dumps(QUESTION)])
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: pytest.fail("no request may be sent"))
    namespace = {"__name__": "test_launcher"}
    exec(compile(flowrun._FLOW_HELPER, str(project_case.launcher), "exec"), namespace)
    assert namespace["main"]() == 3
    assert "owning project session" in capsys.readouterr().err


def _windowed_streams(monkeypatch):
    # The windowed frozen Windows Desktop has no sys.stdout/sys.stderr, and
    # Python 3.11 argparse writes usage there without a guard. Set in the test
    # body: pytest reinstalls its capture streams between setup and call.
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)


@pytest.mark.parametrize("argv", [["run-tool", "--bogus"], ["fetch"]])
def test_bridge_answers_invalid_arguments_without_console_streams(project_case, monkeypatch, argv):
    body = json.dumps({"argv": argv, "cwd": str(project_case.project)}).encode()
    _windowed_streams(monkeypatch)
    response = _bridge(project_case, body)
    assert response["code"] == 400
    message = response["value"]["message"]
    assert message.startswith("invalid Agent flow command arguments\n")
    assert "usage: kiss" in message
    assert sys.stdout is None and sys.stderr is None


def test_bridge_answers_help_without_console_streams(project_case, monkeypatch):
    body = json.dumps({"argv": ["run-tool", "--help"], "cwd": str(project_case.project)}).encode()
    _windowed_streams(monkeypatch)
    response = _bridge(project_case, body)
    assert response["code"] == 200
    assert response["value"]["ok"] is True and response["value"]["returncode"] == 0
    assert "usage: kiss run-tool" in response["value"]["stdout"]
    assert sys.stdout is None and sys.stderr is None
