from __future__ import annotations

import json
import io
import importlib
import importlib.util
import os
import ssl
import subprocess
import sys
import tempfile
import time
import types
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from kiss_cli import api, app as desktop_app, calibration, execution, clipboard, gui, harness_runtime, install, install_locations, kimi_security, mcp, observatory, paths, plotting, policy, port, preparation, projectrun, projectview, prompt, providers, runnable, sessions, settings, setup, shellenv, skilllib, software_audit, tls
from kiss_cli.catalog import Catalog
from kiss_cli.catalog import KI
from kiss_cli.manifest import Acquire, DataNeed, Manifest



def _process_run(completed):
    """A recorded subprocess result as the shared launcher reports it."""
    return execution.ProcessRun(
        "succeeded" if completed.returncode == 0 else "failed",
        completed.returncode, completed.stdout or "", completed.stderr or "",
        process_started=True)

class ProviderHealthTests(unittest.TestCase):
    def setUp(self):
        providers._HEALTH_CACHE.clear()

    def tearDown(self):
        providers._HEALTH_CACHE.clear()

    def test_claude_installed_but_logged_out_is_not_available(self):
        provider = providers.Provider(
            name="claude", binary="claude", argv=["claude", "{prompt}"],
            auth_probe=["claude", "auth", "status", "--json"],
        )
        result = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"loggedIn": False}), stderr="",
        )
        cleared = {name: "" for name in providers._CLAUDE_ENV_AUTH}
        with mock.patch.dict(providers.os.environ, cleared), \
             mock.patch.object(providers.shutil, "which", return_value="/bin/claude"), \
             mock.patch.object(providers.subprocess, "run", return_value=result):
            health = provider.health(refresh=True)
        self.assertTrue(health.installed)
        self.assertFalse(health.authenticated)
        self.assertFalse(health.usable)

    def test_claude_api_key_auth_is_available_even_if_oauth_is_logged_out(self):
        provider = providers.Provider(
            name="claude", binary="claude", argv=["claude", "{prompt}"],
            auth_probe=["claude", "auth", "status", "--json"],
        )
        result = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"loggedIn": False, "authMethod": "none"}), stderr="",
        )
        with mock.patch.dict(providers.os.environ, {"ANTHROPIC_API_KEY": "present"}), \
             mock.patch.object(providers.shutil, "which", return_value="/bin/claude"), \
             mock.patch.object(providers.subprocess, "run", return_value=result):
            health = provider.health(refresh=True)
        self.assertTrue(health.authenticated)
        self.assertTrue(health.usable)

    def test_unknown_future_claude_auth_schema_stays_selectable(self):
        provider = providers.Provider(
            name="claude", binary="claude", argv=["claude", "{prompt}"],
            auth_probe=["claude", "auth", "status", "--json"],
        )
        result = subprocess.CompletedProcess(
            [], 0, stdout=json.dumps({"state": "future-schema"}), stderr="",
        )
        with mock.patch.dict(providers.os.environ, {}, clear=True), \
             mock.patch.object(providers.shutil, "which", return_value="/bin/claude"), \
             mock.patch.object(providers.subprocess, "run", return_value=result):
            health = provider.health(refresh=True)
        self.assertIsNone(health.authenticated)
        self.assertTrue(health.usable)

    def test_codex_local_login_status_is_usable(self):
        provider = providers.Provider(
            name="codex", binary="codex", argv=["codex", "exec", "{prompt}"],
            auth_probe=["codex", "login", "status"],
        )
        result = subprocess.CompletedProcess(
            [], 0, stdout="Logged in using ChatGPT\n", stderr="",
        )
        with mock.patch.object(providers.shutil, "which", return_value="/bin/codex"), \
             mock.patch.object(providers.subprocess, "run", return_value=result):
            health = provider.health(refresh=True)
        self.assertTrue(health.authenticated)
        self.assertTrue(health.usable)

    def test_outdated_codex_is_not_usable_even_when_signed_in(self):
        provider = providers.Provider(
            name="codex", binary="codex", argv=["codex", "exec", "{prompt}"],
            auth_probe=["codex", "login", "status"], min_version=(0, 144, 0),
        )
        replies = [
            subprocess.CompletedProcess([], 0, stdout="Logged in using ChatGPT\n", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="codex-cli 0.140.0\n", stderr=""),
        ]
        with mock.patch.object(providers.shutil, "which", return_value="/bin/codex"), \
             mock.patch.object(providers.subprocess, "run", side_effect=replies):
            health = provider.health(refresh=True)
        self.assertTrue(health.authenticated)
        self.assertFalse(health.compatible)
        self.assertFalse(health.usable)
        self.assertIn("update required", health.detail)

    def test_cli_default_does_not_add_a_model_flag(self):
        provider = providers.Provider(
            name="codex", binary="codex", argv=["codex", "exec", "{prompt}"],
            model_flag="-m",
        )
        with mock.patch.object(providers.shutil, "which", return_value="/bin/codex"):
            self.assertEqual(provider.build("hello"), ["/bin/codex", "exec", "hello"])
            self.assertEqual(
                provider.build("hello", model="explicit-model"),
                ["/bin/codex", "exec", "hello", "-m", "explicit-model"],
            )

    def test_codex_network_is_enabled_only_after_project_approval(self):
        base = policy.Policy("Demo")
        args, _ = policy.codex_args(base)
        self.assertNotIn("sandbox_workspace_write.network_access=true", args)

        base.approve("network", "public-https")
        args, _ = policy.codex_args(base)
        self.assertIn("sandbox_workspace_write.network_access=true", args)

    def test_cli_without_local_auth_probe_is_available_but_unverified(self):
        provider = providers.Provider(
            name="kimi", binary="kimi", argv=["kimi", "-p", "{prompt}"],
        )
        with mock.patch.object(providers.shutil, "which", return_value="/bin/kimi"):
            health = provider.health(refresh=True)
        self.assertTrue(health.usable)
        self.assertIsNone(health.authenticated)
        self.assertEqual(health.detail, "installed; login checked on first use")

    def test_kimi_invocation_and_stream_shape_match_current_cli(self):
        provider = providers.PROVIDERS["kimi"]
        self.assertNotIn("--yolo", provider.argv)
        with mock.patch.object(provider, "path", return_value="/bin/kimi"):
            argv = provider.build("hello", model="kimi-for-coding")
        self.assertIn("kimi-code/kimi-for-coding", argv)
        self.assertEqual(
            providers._text_from_stream_json(
                json.dumps({"role": "assistant", "content": "Kimi reply"})
            ),
            "Kimi reply",
        )
        tool = providers._text_from_stream_json(json.dumps({
            "role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "ReadFile", "arguments": "{}"}},
            ],
        }))
        self.assertIn("ReadFile", tool)
        self.assertIn("[[GEOF_TOOL:", tool)
        activity = providers._safe_tool_activity(json.dumps({
            "role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "Bash", "arguments": json.dumps({
                    "command": "curl -H 'API_KEY=private-value' https://example.test/data"
                })}
            }]
        }), Path("/tmp/project"))
        self.assertEqual(activity[0], "Bash")
        self.assertIn("curl", activity[1])
        self.assertIn("[redacted]", activity[1])
        self.assertNotIn("private-value", activity[1])

    def test_kimi_project_scope_wraps_the_complete_process_tree(self):
        provider = providers.Provider(
            name="kimi", binary="kimi", label="Kimi Code",
            argv=["kimi", "-p", "{prompt}"], output="text",
        )
        wrapped = ["/usr/bin/sandbox-exec", "-f", "/tmp/kimi.sb",
                   "/bin/kimi", "-p", "hello"]
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(provider, "health", return_value=providers.ProviderHealth(
                 True, True, "signed in")), \
             mock.patch.object(provider, "path", return_value="/bin/kimi"), \
             mock.patch.object(settings, "kimi_security_mode", return_value="scoped"), \
             mock.patch.object(kimi_security, "wrap",
                               return_value=(wrapped, Path("/tmp/kimi.sb"))) as secure, \
             mock.patch.object(kimi_security, "cleanup") as cleanup, \
             mock.patch.object(providers.subprocess, "Popen") as popen:
            proc = popen.return_value
            proc.stdout = io.StringIO("")
            proc.wait.return_value = 0
            proc.stdin = None
            output = "".join(providers.run(provider, "hello", Path(td)))
        self.assertEqual(popen.call_args.args[0], wrapped)
        secure.assert_called_once()
        cleanup.assert_called_once_with(Path("/tmp/kimi.sb"))
        self.assertNotIn("project-scoped security", output)

    def test_cli_add_dirs_include_real_directories_granted_by_policy(self):
        provider = providers.Provider(
            name="kimi", binary="kimi", label="Kimi Code",
            argv=["kimi", "-p", "{prompt}"], output="text",
        )
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            coupled = root / "shared" / "binaries"
            project.mkdir()
            coupled.mkdir(parents=True)
            pol = policy.Policy("VIC")
            pol.add("read", coupled, "declared coupled model")
            with mock.patch.object(provider, "health", return_value=providers.ProviderHealth(
                     True, True, "signed in")), \
                 mock.patch.object(provider, "path", return_value="/bin/kimi"), \
                 mock.patch.object(settings, "kimi_security_mode", return_value="full"), \
                 mock.patch.object(providers.subprocess, "Popen") as popen:
                proc = popen.return_value
                proc.stdout = io.StringIO("")
                proc.wait.return_value = 0
                proc.stdin = None
                list(providers.run(provider, "hello", project, pol=pol))

            argv = popen.call_args.args[0]
            self.assertIn("--add-dir", argv)
            self.assertIn(str(coupled.resolve()), argv)

    def test_kimi_eperm_becomes_a_permission_event_not_a_node_stack(self):
        provider = providers.Provider(
            name="kimi", binary="kimi", label="Kimi Code",
            argv=["kimi", "-p", "{prompt}"], output="stream-json",
        )
        denied = "/Users/leo/.agents/skills"

        def spawn(*_args, **kwargs):
            stderr = kwargs["stderr"]
            stderr.write(
                "Error: EPERM: operation not permitted, realpath "
                f"'{denied}'\n    at async Object.realpath (node:fs)\n")
            stderr.flush()
            proc = mock.Mock()
            proc.stdout = io.StringIO("")
            proc.wait.return_value = 1
            proc.stdin = None
            return proc

        events = {}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(provider, "health", return_value=providers.ProviderHealth(
                 True, True, "signed in")), \
             mock.patch.object(provider, "path", return_value="/bin/kimi"), \
             mock.patch.object(settings, "kimi_security_mode", return_value="full"), \
             mock.patch.object(providers.subprocess, "Popen", side_effect=spawn):
            output = "".join(providers.run(
                provider, "hello", Path(td), runtime_events=events))
        self.assertEqual(events["permission"]["path"], denied)
        self.assertIn("needs permission to read", output)
        self.assertNotIn("Object.realpath", output)
        self.assertNotIn("exited 1", output)

    def test_kimi_auth_timeout_becomes_a_plain_connection_error(self):
        provider = providers.Provider(
            name="kimi", binary="kimi", label="Kimi Code",
            argv=["kimi", "-p", "{prompt}"], output="stream-json",
        )

        def spawn(*_args, **kwargs):
            stderr = kwargs["stderr"]
            stderr.write(
                "OAuth request to https://auth.kimi.com/api/oauth/token failed: "
                "fetch failed: Connect Timeout Error\n")
            stderr.flush()
            proc = mock.Mock()
            proc.stdout = io.StringIO("")
            proc.wait.return_value = 1
            proc.stdin = None
            return proc

        events = {}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(provider, "health", return_value=providers.ProviderHealth(
                 True, True, "signed in")), \
             mock.patch.object(provider, "path", return_value="/bin/kimi"), \
             mock.patch.object(settings, "kimi_security_mode", return_value="full"), \
             mock.patch.object(providers.subprocess, "Popen", side_effect=spawn):
            output = "".join(providers.run(
                provider, "请运行模型", Path(td), runtime_events=events))
        self.assertEqual(events["connection"]["service"], "auth.kimi.com")
        self.assertIn("网络", output)
        self.assertIn("不是 KI", output)
        self.assertNotIn("exited 1", output)
        self.assertNotIn("```", output)

    def test_claude_nested_tool_activity_is_visible(self):
        tool = providers._text_from_stream_json(json.dumps({
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "name": "Bash", "input": {}},
            ]},
        }))
        self.assertIn("[[GEOF_TOOL:Bash]]", tool)

    def test_blocking_agent_stream_emits_keepalives(self):
        def slow_stream():
            time.sleep(0.04)
            yield "finished"

        events = list(gui._with_heartbeats(slow_stream(), interval=0.005))
        self.assertIn(None, events)
        self.assertEqual(events[-1], "finished")

    def test_chat_forwarder_turns_idle_time_into_invisible_keepalives(self):
        def slow_stream():
            time.sleep(0.04)
            yield "finished"

        forwarded = []
        ok = gui._forward_chat_stream(
            slow_stream(), lambda piece: forwarded.append(piece) or True,
            interval=0.005,
        )
        self.assertTrue(ok)
        self.assertIn(gui.CHAT_KEEPALIVE, forwarded)
        self.assertEqual(forwarded[-1], "finished")

    def test_agent_activity_requires_evidence_before_claiming_a_download(self):
        self.assertEqual(
            gui._activity_kind(None, {"stage": "preparing", "status": "working"}, {}),
            ("unknown", "none"),
        )
        self.assertEqual(
            gui._activity_kind("download_data", {}, {}),
            ("data_transfer", "tool_event"),
        )
        self.assertEqual(
            gui._activity_kind(None, {}, {"input_growing": True}),
            ("data_transfer", "file_growth"),
        )

    def test_project_file_probe_detects_growing_inputs_without_reading_them(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            inputs = project / "inputs"
            inputs.mkdir()
            target = inputs / "forcing.bin"
            target.write_bytes(b"1234")
            first = gui._project_file_evidence(project, time.time() - 2, None)
            previous = dict(first, probed_at=time.time() - 4, input_bytes=1)
            second = gui._project_file_evidence(project, time.time() - 2, previous)
            self.assertTrue(second["input_growing"])
            self.assertEqual(second["latest_path"], "inputs/forcing.bin")

    def test_live_agent_snapshot_separates_process_from_transport(self):
        class RunningProcess:
            def poll(self):
                return None

        events = {"provider": "cli:claude"}
        gui._register_agent_run("status-test", events)
        events["_process_handle"] = RunningProcess()
        events["process"] = {
            "state": "running", "pid": 31415,
            "started_at": time.time() - 120,
            "last_event_at": time.time() - 95,
            "last_output_at": time.time() - 100,
            "activity": "Bash",
            "activity_detail": "python tools/prepare_forcing.py --year 2001",
        }
        try:
            status = gui._agent_run_snapshot("status-test")
        finally:
            gui._LIVE_AGENT_RUNS.pop("status-test", None)
        self.assertTrue(status["process_alive"])
        self.assertEqual(status["activity"], "Bash")
        self.assertIn("prepare_forcing.py", status["activity_detail"])
        self.assertGreaterEqual(status["event_silence_seconds"], 94)
        self.assertEqual(status["pid"], 31415)

    def test_live_agent_snapshot_reports_in_process_api_turn_as_running(self):
        events = {"provider": "api:deepseek"}
        gui._register_agent_run("status-api-test", events)
        try:
            status = gui._agent_run_snapshot("status-api-test")
            self.assertEqual(status["state"], "running")
            events["finished_at"] = time.time()
            self.assertEqual(gui._agent_run_snapshot("status-api-test")["state"], "finished")
        finally:
            gui._LIVE_AGENT_RUNS.pop("status-api-test", None)

    def test_streamed_openai_tool_call_deltas_are_reassembled(self):
        lines = [
            b'data: {"choices":[{"delta":{"role":"assistant","content":"Let me "}}]}\n',
            b'data: {"choices":[{"delta":{"reasoning_content":"hidden"}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","type":"function",'
            b'"function":{"name":"run_ki_tool","arguments":"{\\"tool"}}]}}]}\n',
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"_path\\":1}"}}]},'
            b'"finish_reason":"tool_calls"}]}\n',
            b'data: [DONE]\n',
        ]

        class Response:
            closed = False

            def __iter__(self):
                return iter(lines)

            def close(self):
                Response.closed = True

        handle = api.TurnHandle()
        with mock.patch.object(api, "_open", return_value=Response()) as opened:
            data = api._post("https://api.example/chat", {}, {"model": "m"},
                             provider="deepseek", wire="openai", handle=handle)
        self.assertTrue(opened.call_args.args[2]["stream"])
        message = data["choices"][0]["message"]
        self.assertEqual(message["content"], "Let me ")
        self.assertNotIn("reasoning_content", message)
        self.assertEqual(message["tool_calls"][0]["id"], "c1")
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]),
                         {"tool_path": 1})
        self.assertIsNotNone(handle.last_chunk_at)
        self.assertTrue(Response.closed)

    def test_streamed_anthropic_blocks_are_reassembled(self):
        events = [
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
            {"type": "content_block_start", "index": 1,
             "content_block": {"type": "tool_use", "id": "t1", "name": "read_file", "input": {}}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": "{\"path\": "}},
            {"type": "content_block_delta", "index": 1,
             "delta": {"type": "input_json_delta", "partial_json": "\"a.txt\"}"}},
            {"type": "message_stop"},
        ]
        data = api._assemble_anthropic(iter(events))
        self.assertEqual(data["content"][0], {"type": "text", "text": "Hi"})
        self.assertEqual(data["content"][1]["input"], {"path": "a.txt"})

    def test_stop_closes_the_live_api_stream_and_ends_the_turn(self):
        class Response:
            closed = False

            def __iter__(self):
                yield b'data: {"choices":[{"delta":{"content":"x"}}]}\n'
                raise ConnectionError("closed")

            def close(self):
                Response.closed = True

        events = {"provider": "api:deepseek", "_handle": api.TurnHandle()}
        gui._register_agent_run("stop-test", events)
        try:
            with mock.patch.object(api, "_open", return_value=Response()):
                handle = events["_handle"]
                real_attach = handle.attach

                def attach_then_stop(response):
                    real_attach(response)
                    self.assertTrue(gui._stop_agent_run("stop-test")["stopped"])

                with mock.patch.object(handle, "attach", side_effect=attach_then_stop):
                    with self.assertRaisesRegex(api.ToolError, "stopped by the user"):
                        api._post("https://api.example/chat", {}, {}, provider="deepseek",
                                  wire="openai", handle=handle)
            self.assertTrue(Response.closed)
            self.assertFalse(gui._stop_agent_run("no-such-session")["stopped"])
        finally:
            gui._LIVE_AGENT_RUNS.pop("stop-test", None)

    def test_truncated_tool_arguments_name_the_output_limit(self):
        lines = [
            b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","type":"function",'
            b'"function":{"name":"write_plan","arguments":"{\\"plan\\": {\\"goal"}}]}}]}\n',
            b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n',
            b'data: [DONE]\n',
        ]

        class Response:
            def __iter__(self):
                return iter(lines)

            def close(self):
                pass

        prov = SimpleNamespace(name="deepseek", base_url="https://api.example/chat", wire="openai")
        with mock.patch.object(api, "_open", return_value=Response()) as opened:
            _text, calls, _raw = api._openai_turn(prov, "m", "sys", [], [], "key")
        self.assertEqual(opened.call_args.args[2]["max_tokens"], api.MAX_OUTPUT_TOKENS)
        self.assertIn("output limit", calls[0][2]["_vendor_argument_error"])

    def test_post_does_not_retry_a_timed_out_generation(self):
        import urllib.error

        class Opener:
            calls = 0

            def open(self, req, timeout=None):
                Opener.calls += 1
                raise urllib.error.URLError(TimeoutError("timed out"))

        with mock.patch.object(api.urllib.request, "build_opener", return_value=Opener()), \
             mock.patch.object(api.time, "sleep"):
            with self.assertRaisesRegex(api.ToolError, "still generating"):
                api._post("https://api.example/chat", {}, {}, provider="deepseek")
        self.assertEqual(Opener.calls, 1)

    def test_missing_alias_and_duplicate_workdir_are_not_passed_to_cli(self):
        provider = providers.Provider(
            name="kimi", binary="kimi", argv=["kimi", "-p", "{prompt}"],
        )
        cfg = SimpleNamespace(relocation="sandbox", roles={})
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(provider, "health", return_value=providers.ProviderHealth(
                 True, True, "signed in")), \
             mock.patch.object(provider, "path", return_value="/bin/kimi"), \
             mock.patch.object(paths, "have_sandbox", return_value=False), \
             mock.patch.object(settings, "kimi_security_mode", return_value="full"), \
             mock.patch.object(providers.subprocess, "Popen") as popen:
            proc = popen.return_value
            proc.stdout = io.StringIO("")
            proc.wait.return_value = 0
            proc.stdin = None
            extra = Path(td) / "extra"
            extra.mkdir()
            list(providers.run(
                provider, "hello", Path(td),
                extra_dirs=[td, str(extra), str(extra), "/mnt/disk3"], cfg=cfg,
            ))
        argv = popen.call_args.args[0]
        self.assertNotIn(td, argv)
        self.assertEqual(argv.count(str(extra)), 1)
        self.assertNotIn("/mnt/disk3", argv)

    def test_local_cli_inherits_bundled_ki_tools_common(self):
        provider = providers.Provider(
            name="claude", binary="claude", argv=["claude", "{prompt}"],
        )
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(provider, "health", return_value=providers.ProviderHealth(
                 True, True, "signed in")), \
             mock.patch.object(provider, "path", return_value="/bin/claude"), \
             mock.patch.object(providers.subprocess, "Popen") as popen:
            common = Path(td) / "common"
            common.mkdir()
            cfg = SimpleNamespace(
                relocation="none", roles={"ki_tools_common": common})
            proc = popen.return_value
            proc.stdout = io.StringIO("")
            proc.wait.return_value = 0
            proc.stdin = None
            list(providers.run(provider, "hello", Path(td), cfg=cfg))
        inherited = popen.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(inherited[0], str(common.resolve()))

    def test_direct_api_hides_scratch_narration_and_normalizes_tool_activity(self):
        provider = api.ApiProvider(
            name="demo", label="Demo API", wire="openai",
            base_url="https://example.invalid", env_key="DEMO_API_KEY",
            models={"demo": "demo"}, default_model="demo",
        )
        turns = [
            ("Let me inspect every file first.", [("call-1", "list_ki_files", {})],
             {"role": "assistant", "content": "scratch", "tool_calls": []}),
            ("The project needs precipitation and PET.", [],
             {"role": "assistant", "content": "final"}),
        ]
        with mock.patch.dict(api.os.environ, {"DEMO_API_KEY": "test"}), \
             mock.patch.object(api, "_openai_turn", side_effect=turns), \
             mock.patch.object(api, "execute_tool", return_value="files"):
            output = "".join(api.run(
                provider, SimpleNamespace(), SimpleNamespace(), "system", "task"))
        self.assertNotIn("Let me inspect", output)
        self.assertIn("[[GEOF_TOOL:list_ki_files]]", output)
        self.assertIn("The project needs precipitation and PET.", output)

    def test_direct_api_retries_text_that_only_looks_like_a_tool_call(self):
        provider = api.ApiProvider(
            name="demo", label="Demo API", wire="openai",
            base_url="https://example.invalid", env_key="DEMO_API_KEY",
            models={"demo": "demo"}, default_model="demo",
        )
        fake_markup = (
            '[[GEOF_TOOL:run_ki_tool]]">\n'
            '<invoke name="run_ki_tool"><parameter name="tool_path">'
            'tools/prepare.py</parameter></invoke>'
        )
        turns = [
            (fake_markup, [], {"role": "assistant", "content": fake_markup}),
            ("I used the structured tools and checked the project.", [],
             {"role": "assistant", "content": "final"}),
        ]
        with mock.patch.dict(api.os.environ, {"DEMO_API_KEY": "test"}), \
             mock.patch.object(api, "_openai_turn", side_effect=turns) as turn:
            output = "".join(api.run(
                provider, SimpleNamespace(), SimpleNamespace(), "system", "task"))
        self.assertEqual(turn.call_count, 2)
        self.assertNotIn("<invoke", output)
        self.assertNotIn("GEOF_TOOL", output)
        self.assertIn("structured tools", output)

    def test_direct_api_has_no_implicit_step_limit(self):
        provider = api.ApiProvider(
            name="demo", label="Demo API", wire="openai",
            base_url="https://example.invalid", env_key="DEMO_API_KEY",
            models={"demo": "demo"}, default_model="demo",
        )
        tool_turn = ("", [("call", "list_ki_files", {})],
                     {"role": "assistant", "content": "", "tool_calls": []})
        turns = [tool_turn] * 45 + [
            ("preflight passed", [], {"role": "assistant", "content": "final"})]
        with mock.patch.dict(api.os.environ, {"DEMO_API_KEY": "test"}), \
             mock.patch.object(api, "_openai_turn", side_effect=turns) as turn, \
             mock.patch.object(api, "execute_tool", return_value="files"):
            output = "".join(api.run(
                provider, SimpleNamespace(), SimpleNamespace(), "system", "task"))
        self.assertEqual(turn.call_count, 46)
        self.assertIn("preflight passed", output)
        self.assertNotIn("stopped after", output)

    def test_setup_launch_error_is_recoverable_tool_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            tool = ki_root / "tools" / "run.py"
            tool.parent.mkdir(parents=True)
            tool.write_text("print('ok')")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            with mock.patch.object(
                    api.subprocess, "Popen",
                    side_effect=PermissionError(13, "Permission denied", str(tool))):
                output = api.execute_tool(
                    "run_setup_command",
                    {"argv": [str(tool)]},
                    SimpleNamespace(root=ki_root), cfg,
                    setup_mode=True,
                )
        self.assertIn("FAILED_TO_START: PermissionError", output)

    def test_deepseek_truncated_tool_arguments_are_recoverable(self):
        response = {
            "choices": [{"message": {
                "content": "",
                "tool_calls": [{
                    "id": "call-1",
                    "function": {
                        "name": "run_setup_command",
                        "arguments": '{"argv":["python3","tool.py"',
                    },
                }],
            }}],
        }
        with mock.patch.object(api, "_post", return_value=response):
            _, calls, _ = api._openai_turn(
                SimpleNamespace(base_url="https://example.invalid"),
                "demo", "system", [], [], "key",
            )
        self.assertEqual(calls[0][0:2], ("call-1", "run_setup_command"))
        self.assertIn("_vendor_argument_error", calls[0][2])


class FrozenRuntimeTests(unittest.TestCase):
    def test_materialise_uses_configured_python_executable(self):
        cfg = SimpleNamespace(
            python=str(Path("C:/work/venv/Scripts/python.exe")),
            roles={"python_env": Path("C:/work/venv")},
        )
        rendered, _count, unresolved = port.unsubstitute(
            "KISSPATH_PYTHON_ENV/bin/python tool.py\n"
            "KISSPATH_PYTHON_ENV/bin/python3 other.py\n",
            cfg,
        )
        self.assertFalse(unresolved)
        self.assertEqual(rendered.count("C:/work/venv/Scripts/python.exe"), 2)
        self.assertNotIn("venv/bin/python", rendered)

    def test_harness_import_is_repo_local_and_dependency_light(self):
        """No user-site/editable copy may make this release test pass."""
        repo = Path(__file__).parents[2]
        app_source = Path(__file__).parents[1]
        common_source = repo / "ki_tools_common"
        model = repo / "models" / "DSSAT"
        script = f"""
import sys
from pathlib import Path
sys.path[:0] = [{str(app_source)!r}, {str(common_source)!r}]
from kiss_cli.catalog import KI
from kiss_cli import prompt
from ki_tools_common.harness import MARKER
import ki_tools_common.harness.ki_harness as implementation
text = prompt.compose(KI('DSSAT', Path({str(model)!r})), headless=False)
assert MARKER in text
assert '[KI USAGE CONTRACT UNAVAILABLE]' not in text
assert Path(implementation.__file__).resolve().is_relative_to(
    Path({str(common_source)!r}).resolve())
print(MARKER, len(text), implementation.__file__)
"""
        result = subprocess.run(
            [sys.executable, "-S", "-c", script],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("[KI HARNESS v1]", result.stdout)

    def test_pyinstaller_specs_collect_harness_as_python_not_only_data(self):
        source = Path(__file__).parents[1]
        mac = (source / "GeoForgeDesktop.spec").read_text(encoding="utf-8")
        generic = (source / "KISS.spec").read_text(encoding="utf-8")
        for spec in (mac, generic):
            self.assertIn("ki_tools_common.harness.ki_harness", spec)
            self.assertIn("ki_tools_common.harness.ki_attention", spec)
            self.assertIn("ki_tools_common.harness.agent_spawn", spec)
            self.assertIn("ki_tools_common", spec)
        self.assertIn("str(KI_TOOLS_SOURCE)", mac)
        self.assertIn("str(KI_TOOLS_SOURCE)", generic)

    def test_every_ki_prompt_is_verified_and_carries_a_receipt(self):
        model = Path(__file__).parents[2] / "models" / "DSSAT"
        ki = KI("DSSAT", model)
        with mock.patch.object(
                harness_runtime, "verified_contract",
                wraps=harness_runtime.verified_contract) as verify:
            first = prompt.compose(ki, headless=False)
            second = prompt.compose(ki, headless=False)
        self.assertEqual(verify.call_count, 2)
        for text in (first, second):
            self.assertIn("[KI HARNESS v1]", text)
            self.assertIn("[GEOFORGE HARNESS RECEIPT]", text)
            self.assertIn("implementation_sha256=", text)
            self.assertIn("contract_sha256=", text)

    def test_broken_harness_stops_prompt_instead_of_using_fallback(self):
        model = Path(__file__).parents[2] / "models" / "DSSAT"
        with mock.patch.object(
                harness_runtime, "verified_contract",
                side_effect=harness_runtime.HarnessUnavailable("tampered")):
            with self.assertRaisesRegex(
                    harness_runtime.HarnessUnavailable, "tampered"):
                prompt.compose(KI("DSSAT", model), headless=False)

    def test_harness_status_returns_source_and_contract_hashes(self):
        model = Path(__file__).parents[2] / "models" / "DSSAT"
        result = harness_runtime.status(model)
        self.assertTrue(result["ready"], result)
        self.assertEqual(len(result["implementation_sha256"]), 64)
        self.assertEqual(len(result["contract_sha256"]), 64)

    def test_dssat_reference_case_bundles_a_valid_default_soil(self):
        soil = (Path(__file__).parents[2] / "models" / "DSSAT" / "tools" /
                "generic_soil.sol")
        text = soil.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("*IB00000001  IBSNAT"))
        self.assertIn("@  SLB  SLMH  SLLL  SDUL  SSAT", text)

    def test_vic_software_verification_does_not_require_global_project_data(self):
        source = Path(__file__).parents[2] / "models" / "VIC"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = paths.KissConfig.default(root)
            live = root / "ki"
            materialised = port.materialise(source, live, cfg)
            self.assertFalse(materialised.unresolved)
            for binary in (
                cfg.roles["binaries"] / "VIC-5.1.0" / "vic" / "drivers" /
                "classic" / "vic_classic.exe",
                cfg.roles["binaries"] / "cmf_v420_pkg" / "src" / "MAIN_cmf",
            ):
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("test executable")
                binary.chmod(0o755)
            # UTF-8 stdio only, so the "—" lines decode exactly; the preflight's
            # own file IO still runs under the real locale (no -X utf8).
            result = subprocess.run(
                [sys.executable, str(live / "preflight_check.py")],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SOFTWARE PREFLIGHT PASSED", result.stdout)
        self.assertIn("Project data not installed globally", result.stdout)

    def test_private_kdt_build_path_resolves_from_current_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source"
            source.mkdir()
            (source / "preflight_check.py").write_text(
                'BINARY = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/'
                '_work/Alpine3D/source/repo/bin/alpine3d"\n',
                encoding="utf-8",
            )
            cfg = paths.KissConfig.default(root / "chosen-install-folder")
            live = root / "live"
            report = port.materialise(source, live, cfg)
            materialised = (live / "preflight_check.py").read_text(
                encoding="utf-8")
        expected = (cfg.roles["binaries"] / "Alpine3D" / "source" /
                    "repo" / "bin" / "alpine3d")
        self.assertIn(str(expected).replace("\\", "/"), materialised)
        self.assertNotIn("KISSPATH_INTERNAL_NOT_SHIPPED", materialised)
        self.assertFalse(report.unresolved)

    def test_every_preflight_materialises_without_private_build_paths(self):
        models = Path(__file__).parents[2] / "models"
        with tempfile.TemporaryDirectory() as td:
            cfg = paths.KissConfig.default(Path(td) / "chosen-install-folder")
            stale = []
            for preflight in sorted(models.glob("*/preflight_check.py")):
                rendered, _, _ = port.unsubstitute(
                    preflight.read_text(encoding="utf-8"), cfg)
                if ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect" in rendered or
                        "/mnt/disk" in rendered or "/home/server" in rendered):
                    stale.append(str(preflight.relative_to(models)))
        self.assertEqual(stale, [], f"non-portable preflight paths: {stale}")

    def test_dssat_weather_fields_do_not_silently_drop_a_digit(self):
        script = (Path(__file__).parents[2] / "models" / "DSSAT" / "tools" /
                  "run_reference_case.py")
        # The refreshed real-case runner imports NumPy.  Load it before
        # patch.dict snapshots sys.modules; otherwise patch restoration removes
        # NumPy's extension modules and a later readiness check cannot safely
        # import them a second time in the same process.
        import numpy  # noqa: F401
        forcing = types.ModuleType("ki_tools_common.load_forcing")
        forcing.NASA_POWER_DAILY_PARAMS = ()
        forcing.NASA_POWER_DAILY_URL = "https://example.invalid"
        forcing.load_daily_forcing = lambda *args, **kwargs: None
        workdir = types.ModuleType("dssat_workdir_setup")
        workdir.DSSAT_BINARY = Path("dscsm048")
        workdir.DSSAT_DATA = Path("Data")
        workdir.create_workdir = lambda *args, **kwargs: None
        workdir.parse_summary = lambda *args, **kwargs: []
        workdir.run_dssat = lambda *args, **kwargs: None
        spec = importlib.util.spec_from_file_location(
            "geoforge_test_dssat_reference_case", script)
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(sys.modules, {
                "ki_tools_common.load_forcing": forcing,
                "dssat_workdir_setup": workdir}):
            spec.loader.exec_module(module)
        self.assertEqual(module._wth_field(1162.9), "  1163")
        self.assertEqual(len(module._wth_field(1162.9)), 6)
        self.assertEqual(module._wth_field(-30.8), " -30.8")
        with self.assertRaisesRegex(ValueError, "cannot fit safely"):
            module._wth_field(123456.0)

    def test_frozen_launcher_is_never_used_as_python(self):
        launcher = "/Applications/GeoForge Desktop.app/Contents/MacOS/GeoForge Desktop"
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", launcher), \
             mock.patch.object(install, "find_base_python", return_value="/usr/bin/python3"):
            self.assertEqual(install.runtime_python(launcher), "/usr/bin/python3")

    def test_old_app_launcher_in_a_saved_config_is_repaired(self):
        old = "/Applications/GeoForge Desktop.app/Contents/MacOS/GeoForge Desktop"
        current = "/tmp/GeoForge Desktop.app/Contents/MacOS/GeoForge Desktop"
        with mock.patch.object(sys, "frozen", True, create=True), \
             mock.patch.object(sys, "executable", current), \
             mock.patch.object(install, "find_base_python", return_value="/usr/bin/python3"), \
             mock.patch.object(install.shutil, "which", return_value=None), \
             mock.patch.object(install.Path, "is_file", return_value=True):
            self.assertEqual(install.runtime_python(old), "/usr/bin/python3")

    def test_source_interpreter_is_preserved(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertEqual(install.runtime_python(sys.executable), sys.executable)

    def test_configured_python_command_is_resolved_for_gui_and_cli_policy(self):
        discovered = "/opt/homebrew/bin/python3"
        with mock.patch.object(install.shutil, "which", return_value=discovered):
            self.assertEqual(install.runtime_python("python3"), discovered)

    def test_skipped_step_is_not_reported_as_an_independent_failure(self):
        step = install.Step(
            "preflight", False, "not run because acquisition failed", skipped=True,
        )
        self.assertEqual(step.mark, "SKIPPED")

    def test_source_install_tree_is_linked_to_the_ki_declared_location(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prefix = root / "binaries" / "Demo"
            binary = prefix / "build" / "bin" / "demo"
            binary.parent.mkdir(parents=True)
            binary.write_text("binary")
            binary.chmod(0o755)
            preflight = root / "preflight_check.py"
            preflight.write_text(
                "def check_file(path, label, executable=False): pass\n"
                f'check_file("{root.as_posix()}/Demo/build/bin/demo", "Demo", executable=True)\n'
            )
            ki = SimpleNamespace(preflight=preflight, root=root / "ki")
            cfg = SimpleNamespace(root=root)

            notes = install.place_where_the_ki_expects(ki, binary, cfg, prefix)

            # Windows may use a junction when unprivileged symlinks are
            # disabled; both provide one non-duplicated install tree.
            self.assertTrue((root / "Demo").is_dir())
            self.assertEqual((root / "Demo").resolve(), prefix.resolve())
            self.assertIn("linked install tree", notes[0])

    @unittest.skipUnless(os.name == "nt", "Windows executable suffix")
    def test_windows_exe_links_to_suffixless_declared_install_tree(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            prefix = root / "binaries" / "Demo"
            binary = prefix / "build" / "bin" / "demo.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"MZ")
            preflight = root / "preflight_check.py"
            preflight.write_text(
                "def check_file(path, label, executable=False): pass\n"
                f'check_file("{root.as_posix()}/Demo/build/bin/demo", '
                '"Demo", executable=True)\n'
            )
            notes = install.place_where_the_ki_expects(
                SimpleNamespace(preflight=preflight, root=root / "ki"),
                binary, SimpleNamespace(root=root), prefix,
            )
            self.assertTrue((root / "Demo").is_dir())
            self.assertEqual((root / "Demo").resolve(), prefix.resolve())
            self.assertIn("linked install tree", notes[0])

    def test_agent_distribution_is_placed_at_manifest_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = root / "binaries" / "daisy-package"
            binary = package / "bin" / "daisy-bin.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"MZ")
            (package / "bin" / "runtime.dll").write_bytes(b"dll")
            (package / "lib").mkdir()
            (package / "lib" / "crop.dai").write_text("crop")
            # A previous interrupted placement may leave a partial directory.
            (root / "binaries" / "Daisy" / "daisy-package").mkdir(
                parents=True)
            man = Manifest(
                model="Daisy", install_dir="Daisy",
                acquire=Acquire(
                    strategy="download",
                    produces="daisy-package/bin/daisy-bin.exe",
                ),
            )
            cfg = SimpleNamespace(roles={"binaries": root / "binaries"})

            placed, notes = install.place_agent_install(man, binary, cfg)

            expected = (root / "binaries" / "Daisy" / "daisy-package" /
                        "bin" / "daisy-bin.exe")
            self.assertEqual(placed, expected)
            self.assertTrue(expected.is_file())
            self.assertTrue((expected.parent / "runtime.dll").is_file())
            self.assertTrue(
                (expected.parents[1] / "lib" / "crop.dai").is_file())
            self.assertTrue(notes)

    def test_agent_single_executable_keeps_adjacent_windows_dlls(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(install.os, "name", "nt"):
            root = Path(td)
            binary = root / "binaries" / "Cell2Fire.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"MZ")
            (binary.parent / "tiff.dll").write_bytes(b"dll")
            man = Manifest(
                model="Cell2Fire",
                install_dir="Cell2Fire/source/repo/Cell2Fire",
                acquire=Acquire(
                    strategy="download", produces="Cell2Fire.exe"),
            )
            cfg = SimpleNamespace(roles={"binaries": root / "binaries"})

            placed, notes = install.place_agent_install(man, binary, cfg)

            self.assertTrue(placed.is_file())
            self.assertTrue((placed.parent / "tiff.dll").is_file())
            self.assertTrue(notes)

    def test_agent_install_normalises_implicit_windows_exe_suffix(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(install.os, "name", "nt"):
            root = Path(td)
            package = root / "scratch" / "rhessys"
            binary = package / "rhessys7.4.exe"
            binary.parent.mkdir(parents=True)
            binary.write_bytes(b"MZ")
            (binary.parent / "netcdf.dll").write_bytes(b"dll")
            man = Manifest(
                model="RHESSys", install_dir="RHESSys/source/repo",
                acquire=Acquire(
                    strategy="build", produces="rhessys/rhessys7.4"),
            )
            cfg = SimpleNamespace(roles={"binaries": root / "binaries"})

            placed, notes = install.place_agent_install(man, binary, cfg)

            expected = (root / "binaries" / "RHESSys" / "source" /
                        "repo" / "rhessys" / "rhessys7.4.exe")
            self.assertEqual(placed, expected)
            self.assertTrue(expected.is_file())
            self.assertTrue((expected.parent / "netcdf.dll").is_file())
            self.assertTrue(notes)

    def test_builtin_git_acquisition_inherits_selected_provider_proxy(self):
        with tempfile.TemporaryDirectory() as td:
            proxy_env = {"HTTPS_PROXY": "http://127.0.0.1:7897"}
            man = Manifest(
                model="Demo",
                acquire=Acquire(
                    strategy="build", repo="https://example.invalid/demo.git",
                    ref="main"),
            )
            with mock.patch.object(
                    install, "_run", return_value=(1, "network unavailable")) as run:
                step, _binary = install.acquire(
                    man, Path(td) / "Demo", sys.executable, env=proxy_env)

            self.assertFalse(step.ok)
            self.assertEqual(run.call_args.kwargs["env"], proxy_env)

    def test_pip_acquisition_ignores_package_import_chatter(self):
        man = Manifest(
            model="Noisy",
            acquire=Acquire(strategy="pip", package="noisy-package",
                            produces="noisy_package"),
        )
        noisy = (
            "Starting noisy scientific package!\n"
            "WARNING optional plugin unavailable\n"
            f"{install._IMPORT_PATH_MARKER}/tmp/site-packages/noisy_package/__init__.py\n"
            "shutdown message after marker\n"
        )
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(
                 install, "_run",
                 side_effect=[(0, "installed"), (0, noisy)],
             ):
            step, location = install.acquire(
                man, Path(td) / "Noisy", sys.executable,
            )

        self.assertTrue(step.ok)
        self.assertEqual(
            location, Path("/tmp/site-packages/noisy_package/__init__.py"),
        )

    def test_runnable_uses_only_executable_preflight_paths(self):
        with tempfile.TemporaryDirectory() as td:
            preflight = Path(td) / "preflight_check.py"
            preflight.write_text(
                "from pathlib import Path\n"
                "MODEL_EXE = Path('KISSPATH_BINARIES/crhm/build/crhm')\n"
                "def check_file(path, label, critical=True, executable=False): pass\n"
                "check_file(MODEL_EXE, 'CRHM executable', executable=True)\n"
                "check_file('KISSPATH_DATA/elev/dem.nc', 'DEM', critical=True)\n"
            )
            ki = SimpleNamespace(preflight=preflight)

            self.assertEqual(
                runnable.declared(ki),
                ["KISSPATH_BINARIES/crhm/build/crhm"],
            )

    def test_runnable_resolves_check_list_and_os_path_signatures(self):
        with tempfile.TemporaryDirectory() as td:
            preflight = Path(td) / "preflight_check.py"
            preflight.write_text(
                "import os\n"
                "KI_DIR = os.path.dirname(os.path.abspath(__file__))\n"
                "RUNNER = os.path.join(KI_DIR, 'tools', 'run_model.py')\n"
                "def check_file(checks, path, label, critical=True, executable=False): pass\n"
                "check_file([], RUNNER, 'runner', True, True)\n"
            )
            ki = SimpleNamespace(preflight=preflight)

            self.assertEqual(
                runnable.declared(ki),
                [str(preflight.parent / "tools" / "run_model.py")],
            )

    def test_pip_python_model_is_the_package_not_a_stale_binary_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            preflight = root / "preflight_check.py"
            preflight.write_text("# package checks are generated dynamically\n")
            ki = SimpleNamespace(
                name="COSIPY", preflight=preflight, root=root,
                meta={"language": "python"},
            )
            man = Manifest(
                model="COSIPY", binary_type="Python", install_dir="COSIPY",
                acquire=Acquire(strategy="pip", package="cosipymodel",
                                produces="cosipy"),
            )
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries",
                       "python_env": root / "venv"},
            )
            selected = str(root / "binaries" / "venv" / "bin" / "python")
            with mock.patch.object(runnable, "select_python", return_value=selected), \
                 mock.patch.object(runnable, "missing_imports", return_value=[]):
                verdict = runnable.check(ki, man, cfg, python=sys.executable)

            self.assertTrue(verdict.usable)
            self.assertFalse(verdict.needs_binary)
            self.assertEqual(verdict.kind, "python package")
            self.assertEqual(verdict.python, selected)

    def test_runnable_uses_windows_exe_for_suffixless_harvest(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(runnable.os, "name", "nt"):
            root = Path(td)
            expected = root / "binaries" / "CRHM" / "build" / "crhm.exe"
            expected.parent.mkdir(parents=True)
            expected.write_bytes(b"MZ")
            ki = SimpleNamespace(name="CRHM", preflight=None)
            cfg = SimpleNamespace(
                root=root, roles={"binaries": root / "binaries"},
            )

            found = runnable.find_binary(
                ki, cfg=cfg, harvested={"CRHM": "build/crhm"},
            )

            self.assertEqual(found, expected)

    def test_runnable_maps_posix_venv_python_to_windows(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(runnable.os, "name", "nt"):
            root = Path(td)
            expected = root / "venv" / "Scripts" / "python.exe"
            expected.parent.mkdir(parents=True)
            expected.write_bytes(b"MZ")
            preflight = root / "preflight_check.py"
            preflight.write_text(
                "def check_file(path, executable=False): pass\n"
                f"check_file({str(root / 'venv' / 'bin' / 'python')!r}, "
                "executable=True)\n"
            )
            ki = SimpleNamespace(name="PythonKI", preflight=preflight)

            # An interpreter path, even a real Windows venv launcher, is not a
            # model binary. Import/script contracts verify Python KIs instead.
            self.assertIsNone(runnable.find_binary(ki))

    def test_runnable_reads_import_module_from_preflight_signature(self):
        with tempfile.TemporaryDirectory() as td:
            preflight = Path(td) / "preflight_check.py"
            preflight.write_text(
                "REQUIRED_PACKAGE = 'geophires_x'\n"
                "def check_import(checks, python_path, module, label): pass\n"
                "check_import([], 'python', REQUIRED_PACKAGE, 'model')\n"
                "def check_python_import(checks, module, critical=True): pass\n"
                "check_python_import([], 'ribasim', critical=False)\n"
            )
            ki = SimpleNamespace(preflight=preflight)

            self.assertEqual(
                runnable.declared_imports(ki), ["geophires_x"],
            )

    def test_runnable_reads_semantic_file_and_loop_import_helpers(self):
        with tempfile.TemporaryDirectory() as td:
            preflight = Path(td) / "preflight_check.py"
            preflight.write_text(
                "PIHM_BINARY = 'KISSPATH_BINARIES/PIHM/flux-pihm'\n"
                "def add_file_check(checks, path, label, executable=False): pass\n"
                "def add_python_import_check(checks, module, critical=True): pass\n"
                "add_file_check([], PIHM_BINARY, 'model', executable=True)\n"
                "for module in ('numpy', 'pandas'):\n"
                "    add_python_import_check([], module)\n"
            )
            ki = SimpleNamespace(preflight=preflight)

            self.assertEqual(
                runnable.declared(ki), ["KISSPATH_BINARIES/PIHM/flux-pihm"],
            )
            self.assertEqual(
                runnable.declared_imports(ki), ["numpy", "pandas"],
            )

    def test_runnable_ignores_explicitly_optional_imports(self):
        with tempfile.TemporaryDirectory() as td:
            preflight = Path(td) / "preflight_check.py"
            preflight.write_text(
                "def check_import(checks, module, critical=True): pass\n"
                "check_import([], 'porepy', critical=True)\n"
                "check_import([], 'pypardiso', critical=False)\n"
            )
            ki = SimpleNamespace(preflight=preflight)

            self.assertEqual(runnable.declared_imports(ki), ["porepy"])

    def test_runnable_reads_named_import_module_list(self):
        with tempfile.TemporaryDirectory() as td:
            preflight = Path(td) / "preflight_check.py"
            preflight.write_text(
                "IMPORT_MODULES = ['lisflood', 'netCDF4', 'pcraster']\n"
                "def check_runtime_imports(checks, python_exe):\n"
                "    for module in IMPORT_MODULES:\n"
                "        pass\n",
                encoding="utf-8",
            )
            ki = SimpleNamespace(preflight=preflight)
            self.assertEqual(
                runnable.declared_imports(ki),
                ["lisflood", "netCDF4", "pcraster"],
            )

    def test_missing_imports_sees_ki_tools_and_common_sibling(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki = root / "ki"
            (ki / "tools").mkdir(parents=True)
            (ki / "tools" / "local_tool.py").write_text("VALUE = 1\n")
            common = root / "ki_tools_common" / "ki_tools_common"
            common.mkdir(parents=True)
            (common / "__init__.py").write_text("")
            (common / "metrics.py").write_text("VALUE = 1\n")

            self.assertEqual(
                runnable.missing_imports(
                    ["local_tool", "ki_tools_common.metrics"],
                    sys.executable, ki,
                ),
                [],
            )

    def test_missing_import_probe_uses_headless_environment(self):
        completed = subprocess.CompletedProcess([], 0, stdout="__GEOFORGE_IMPORT_PROBE_DONE__\n", stderr="")
        with mock.patch.object(
                runnable.subprocess, "run", return_value=completed) as run:
            self.assertEqual(
                runnable.missing_imports(["simfire.sim.simulation"],
                                         sys.executable),
                [],
            )
        env = run.call_args.kwargs["env"]
        self.assertEqual(env["SDL_VIDEODRIVER"], "dummy")
        self.assertEqual(env["PYGAME_HIDE_SUPPORT_PROMPT"], "1")
        self.assertEqual(env["MPLBACKEND"], "Agg")

    @unittest.skipUnless(os.name == "nt", "Windows conda activation layout")
    def test_conda_runtime_exposes_native_dlls_and_esmf_makefile(self):
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td) / "env"
            python = prefix / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"MZ")
            (prefix / "conda-meta").mkdir()
            for relative in (
                    "Library/mingw-w64/bin", "Library/usr/bin",
                    "Library/bin", "Library/lib", "Scripts", "bin"):
                (prefix / relative).mkdir(parents=True, exist_ok=True)
            esmf_mk = prefix / "Library" / "lib" / "esmf.mk"
            esmf_mk.write_text("ESMF_VERSION_STRING=8.4.0\n")

            env = paths.with_python_runtime(python, {"PATH": "C:\\base"})

            self.assertEqual(env["ESMFMKFILE"], str(esmf_mk.resolve()))
            path_items = env["PATH"].split(os.pathsep)
            resolved_prefix = prefix.resolve()
            self.assertEqual(path_items[0], str(resolved_prefix))
            self.assertLess(
                path_items.index(str(resolved_prefix / "Library" / "bin")),
                path_items.index("C:\\base"),
            )

    @unittest.skipUnless(os.name == "nt", "Windows conda activation layout")
    def test_runnable_probe_activates_recorded_conda_python(self):
        completed = subprocess.CompletedProcess([], 0, stdout="__GEOFORGE_IMPORT_PROBE_DONE__\n", stderr="")
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td) / "env"
            python = prefix / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"MZ")
            (prefix / "conda-meta").mkdir()
            (prefix / "Library" / "bin").mkdir(parents=True)
            esmf_mk = prefix / "Library" / "lib" / "esmf.mk"
            esmf_mk.parent.mkdir(parents=True)
            esmf_mk.write_text("ESMF_VERSION_STRING=8.4.0\n")
            with mock.patch.object(
                    runnable.subprocess, "run", return_value=completed) as run:
                self.assertEqual(
                    runnable.missing_imports(["esmpy"], str(python)), [],
                )

        self.assertEqual(
            run.call_args.kwargs["env"]["ESMFMKFILE"], str(esmf_mk.resolve()),
        )

    def test_missing_imports_treats_broken_interpreter_as_missing(self):
        with mock.patch.object(
                runnable.subprocess, "run", side_effect=FileNotFoundError()):
            self.assertEqual(
                runnable.missing_imports(["simfire", "xarray"], "missing-python"),
                ["simfire", "xarray"],
            )

    def test_select_python_reports_closest_workspace_environment(self):
        with mock.patch.object(
                runnable, "_python_candidates",
                return_value=["workspace-python", "system-python"]), \
             mock.patch.object(
                 runnable, "missing_imports",
                 side_effect=[["rasterio", "xarray"],
                              ["simfire", "rasterio", "xarray"]]):
            selected = runnable.select_python(
                None, "system-python",
                ["simfire", "rasterio", "xarray"],
            )
        self.assertEqual(selected, "workspace-python")

    def test_runnable_finds_exact_agent_build_in_model_tree(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(runnable.os, "name", "nt"):
            root = Path(td)
            built = (root / "binaries" / "Cell2Fire" / "Cell2Fire" /
                     "Cell2Fire.exe")
            built.parent.mkdir(parents=True)
            built.write_bytes(b"MZ")
            preflight = root / "preflight_check.py"
            preflight.write_text(
                "def check_file(path, executable=False): pass\n"
                "check_file('KISSPATH_BINARIES/Cell2Fire/source/repo/"
                "Cell2Fire/Cell2Fire', executable=True)\n"
            )
            ki = SimpleNamespace(name="Cell2Fire", preflight=preflight)
            cfg = SimpleNamespace(
                root=root, roles={"binaries": root / "binaries"},
            )

            self.assertEqual(runnable.find_binary(ki, cfg=cfg), built)

    def test_runnable_appends_exe_to_versioned_windows_binary_name(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(runnable.os, "name", "nt"):
            root = Path(td)
            built = (root / "binaries" / "RHESSys" / "source" / "repo" /
                     "rhessys" / "rhessys7.4.exe")
            built.parent.mkdir(parents=True)
            built.write_bytes(b"MZ")
            ki = SimpleNamespace(
                name="RHESSys", preflight=None, meta={"language": "c"},
            )
            man = Manifest(
                model="RHESSys", install_dir="RHESSys/source/repo",
                acquire=Acquire(
                    strategy="build", produces="rhessys/rhessys7.4"),
            )
            cfg = SimpleNamespace(
                root=root, roles={"binaries": root / "binaries"},
            )

            self.assertEqual(runnable.find_binary(ki, man, cfg), built)

    def test_runnable_finds_compiled_binary_in_managed_sibling(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(runnable.os, "name", "nt"):
            root = Path(td)
            built = root / "binaries" / "crhm" / "bin" / "crhm.exe"
            built.parent.mkdir(parents=True)
            built.write_bytes(b"MZ")
            ki = SimpleNamespace(
                name="CRHM", preflight=None, meta={"language": "cpp"},
            )
            cfg = SimpleNamespace(
                root=root, roles={"binaries": root / "binaries"},
            )

            self.assertEqual(
                runnable.find_binary(
                    ki, cfg=cfg,
                    harvested={"CRHM": "source/repo/build/crhm"},
                ),
                built,
            )

    def test_runnable_understands_keyword_only_executable(self):
        with tempfile.TemporaryDirectory() as td:
            preflight = Path(td) / "preflight_check.py"
            runner = Path(td) / "tools" / "run_model.py"
            preflight.write_text(
                f"RUNNER = {str(runner)!r}\n"
                "def check_file(checks, path, label, *, executable=False): pass\n"
                "check_file([], RUNNER, 'runner', executable=True)\n"
            )
            ki = SimpleNamespace(preflight=preflight)

            self.assertEqual(runnable.declared(ki), [str(runner)])

    def test_compiled_model_does_not_use_helper_python_as_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            python = root / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"MZ")
            preflight = root / "preflight_check.py"
            preflight.write_text(
                "def check_file(path, executable=False): pass\n"
                f"check_file({str(python)!r}, executable=True)\n"
                "check_file('KISSPATH_BINARIES/TELEMAC/bin/telemac2d', "
                "executable=True)\n"
            )
            ki = SimpleNamespace(
                name="TELEMAC", preflight=preflight,
                meta={"language": "fortran"},
            )
            cfg = SimpleNamespace(
                root=root, roles={"binaries": root / "binaries"},
            )

            found = runnable.find_binary(ki, cfg=cfg)

            self.assertNotEqual(found, python)
            self.assertEqual(found.name, "telemac2d.exe")

    def test_compiled_startup_marker_accepts_later_missing_project_input(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            binary = root / "telemac2d.exe"
            binary.write_bytes(b"MZ")
            ki = SimpleNamespace(
                name="TELEMAC_MASCARET", preflight=None,
                meta={"language": "fortran"},
            )
            man = Manifest(
                model="TELEMAC_MASCARET", binary_type="PE32",
                startup_marker="2D VERSION 9.1 FORTRAN 2003",
                acquire=Acquire(strategy="build", produces="telemac2d.exe"),
            )
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root},
            )
            output = (
                "READ_CONFIG: FILE CONFIG NOT FOUND: CONFIG\n"
                "2D    VERSION 9.1    FORTRAN 2003\n"
                "Fortran runtime error: Cannot open file 'T2DDICO': "
                "No such file or directory\n"
            )
            completed = subprocess.CompletedProcess(
                [str(binary), "--version"], 1, stdout=output, stderr="",
            )
            with mock.patch.object(runnable, "find_binary", return_value=binary), \
                 mock.patch.object(runnable, "_file_kind", return_value="pe"), \
                 mock.patch.object(runnable.platform, "system", return_value="Windows"), \
                 mock.patch.object(runnable.os, "access", return_value=True), \
                 mock.patch.object(runnable.subprocess, "run", return_value=completed):
                verdict = runnable.check(ki, man, cfg, python=sys.executable)

            self.assertTrue(verdict.usable)
            self.assertTrue(verdict.linked)
            self.assertTrue(verdict.responds)
            self.assertEqual(verdict.detail, "2D VERSION 9.1 FORTRAN 2003")

    def test_startup_marker_does_not_hide_actual_runtime_gaps(self):
        failures = {
            "missing DLL": (
                "2D VERSION 9.1 FORTRAN 2003\n"
                "error while loading shared libraries: libmodel.dll"
            ),
            "missing command": "helper: command not found",
            "missing interpreter": (
                "/usr/bin/env: missing-python: No such file or directory"
            ),
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            binary = root / "model.exe"
            binary.write_bytes(b"MZ")
            ki = SimpleNamespace(
                name="Compiled", preflight=None,
                meta={"language": "fortran"},
            )
            man = Manifest(
                model="Compiled", binary_type="PE32",
                startup_marker="2D VERSION 9.1 FORTRAN 2003",
                acquire=Acquire(strategy="build", produces="model.exe"),
            )
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root},
            )
            for label, output in failures.items():
                completed = subprocess.CompletedProcess(
                    [str(binary), "--version"], 1,
                    stdout=output, stderr="",
                )
                with self.subTest(label=label), \
                     mock.patch.object(runnable, "find_binary", return_value=binary), \
                     mock.patch.object(runnable, "_file_kind", return_value="pe"), \
                     mock.patch.object(runnable.platform, "system", return_value="Windows"), \
                     mock.patch.object(runnable.os, "access", return_value=True), \
                     mock.patch.object(runnable.subprocess, "run", return_value=completed):
                    verdict = runnable.check(
                        ki, man, cfg, python=sys.executable,
                    )
                self.assertFalse(verdict.usable)
                self.assertFalse(verdict.linked)

    def test_pip_wrapped_compiled_model_uses_import_contract(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(runnable, "select_python", return_value=sys.executable), \
             mock.patch.object(runnable, "missing_imports", return_value=[]):
            root = Path(td)
            ki = SimpleNamespace(
                name="SWMM", preflight=None, root=root,
                meta={"language": "c"},
            )
            man = Manifest(
                model="SWMM", binary_type="Python+C", acquire=Acquire(
                    strategy="pip", package="pyswmm", produces="pyswmm",
                ),
            )
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries", "python_env": root / "venv"},
            )

            verdict = runnable.check(ki, man, cfg, python=sys.executable)

            self.assertTrue(verdict.usable)
            self.assertFalse(verdict.needs_binary)


class EnvironmentAndTlsTests(unittest.TestCase):
    def test_interactive_login_environment_is_nul_delimited(self):
        shellenv._done = False
        completed = SimpleNamespace(stdout=b"PATH=/custom/bin:/usr/bin\0TOKEN=a=b\nc\0")
        with mock.patch.dict(shellenv.os.environ,
                             {"HOME": "/tmp/geoforge-home", "SHELL": "/bin/zsh",
                              "PATH": "/usr/bin:/bin"}, clear=True), \
             mock.patch.object(shellenv.platform, "system", return_value="Darwin"), \
             mock.patch.object(shellenv.subprocess, "run", return_value=completed) as run:
            shellenv.adopt()
            argv = run.call_args.args[0]
            self.assertEqual(argv[:4], ["/bin/zsh", "-i", "-l", "-c"])
            self.assertTrue(argv[-1].endswith("env -0"))
            self.assertTrue(shellenv.os.environ["PATH"].startswith("/custom/bin"))
            self.assertEqual(shellenv.os.environ["TOKEN"], "a=b\nc")
        shellenv._done = False

    def test_tls_context_verifies_certificates(self):
        ctx = tls.context()
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)


class ProxySettingsTests(unittest.TestCase):
    def _base_env(self):
        return {key: None for key in settings.PROXY_ENV_KEYS}

    def test_auto_proxy_detects_and_applies_the_mac_system_proxy(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(settings, "_path", return_value=Path(td) / "settings.json"), \
             mock.patch.object(settings, "_BASE_PROXY_ENV", self._base_env()), \
             mock.patch.object(settings.urllib.request, "getproxies", return_value={
                 "https": "http://127.0.0.1:7897"}), \
             mock.patch.dict(settings.os.environ, {}, clear=True):
            settings.update({"proxy_mode": "auto"})
            state = settings.masked()
            self.assertEqual(state["proxy_effective"], "http://127.0.0.1:7897")
            self.assertEqual(state["proxy_source"], "system")
            self.assertEqual(
                settings.with_provider_proxy("cli:claude", {})["HTTPS_PROXY"],
                "http://127.0.0.1:7897")
            self.assertNotIn(
                "HTTPS_PROXY", settings.with_provider_proxy("cli:kimi", {}))

    def test_manual_proxy_can_be_replaced_or_disabled_without_restart(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(settings, "_path", return_value=Path(td) / "settings.json"), \
             mock.patch.object(settings, "_BASE_PROXY_ENV", self._base_env()), \
             mock.patch.object(settings.urllib.request, "getproxies", return_value={}), \
             mock.patch.dict(settings.os.environ, {}, clear=True):
            settings.update({"proxy_mode": "manual",
                             "proxy_url": "http://127.0.0.1:7897/"})
            self.assertEqual(settings.load()["proxy_url"], "http://127.0.0.1:7897")
            self.assertEqual(
                settings.with_provider_proxy("cli:codex", {})["HTTP_PROXY"],
                "http://127.0.0.1:7897")
            settings.update({"proxy_mode": "off"})
            self.assertNotIn(
                "HTTP_PROXY", settings.with_provider_proxy("cli:codex", {}))
            self.assertEqual(settings.masked()["proxy_effective"], "")

    def test_proxy_provider_selection_includes_github_updates_by_default(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(settings, "_path", return_value=Path(td) / "settings.json"), \
             mock.patch.object(settings.urllib.request, "getproxies", return_value={
                 "https": "http://127.0.0.1:7897"}):
            self.assertEqual(
                set(settings.masked()["proxy_providers"]),
                {"network:github", "network:obs", "cli:claude", "cli:codex"})
            settings.update({"proxy_providers": ["cli:kimi", "api:anthropic"]})
            self.assertEqual(
                set(settings.masked()["proxy_providers"]),
                {"cli:kimi", "api:anthropic"})
            self.assertEqual(
                settings.proxy_url_for("cli:kimi"), "http://127.0.0.1:7897")
            self.assertEqual(settings.proxy_url_for("api:deepseek"), "")

    def test_old_saved_proxy_selection_adopts_new_github_target_once(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(settings, "_path", return_value=Path(td) / "settings.json"), \
             mock.patch.object(settings.urllib.request, "getproxies", return_value={
                 "https": "http://127.0.0.1:7897"}):
            settings.save({"proxy_mode": "auto",
                           "proxy_providers": ["cli:claude"]})
            self.assertIn("network:github", settings.proxy_providers())
            settings.update({"proxy_providers": ["cli:claude"]})
            self.assertNotIn("network:github", settings.proxy_providers())

    def test_manual_proxy_rejects_missing_or_credential_bearing_addresses(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(settings, "_path", return_value=Path(td) / "settings.json"), \
             mock.patch.object(settings, "_BASE_PROXY_ENV", self._base_env()), \
             mock.patch.dict(settings.os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "proxy address is required"):
                settings.update({"proxy_mode": "manual", "proxy_url": ""})
            with self.assertRaisesRegex(ValueError, "credentials are not stored"):
                settings.update({"proxy_mode": "manual",
                                 "proxy_url": "http://user:secret@127.0.0.1:7897"})


class KimiSecurityTests(unittest.TestCase):
    def test_profile_reopens_only_the_approved_project_under_home(self):
        home = Path.home().resolve()
        project = home / "Documents" / "GeoForge project"
        text = kimi_security.profile(cwd=project)
        deny = f'(deny file-read* (subpath {kimi_security._literal(home)}))'
        allow = f'(allow file-read* (subpath {kimi_security._literal(project)}))'
        self.assertIn(deny, text)
        self.assertIn(allow, text)
        self.assertIn(
            f'(allow file-read* (subpath '
            f'{kimi_security._literal(home / ".agents" / "skills")}))',
            text,
        )
        self.assertLess(text.index(deny), text.index(allow))
        self.assertIn("(deny file-write*)", text)

    def test_shared_agent_skills_are_read_only_kimi_runtime_not_project_data(self):
        home = Path.home().resolve()
        skills = home / ".agents" / "skills"
        text = kimi_security.profile(cwd=home / "Documents" / "GeoForge project")

        self.assertTrue(kimi_security.is_runtime_read_path(skills))
        self.assertTrue(kimi_security.is_runtime_read_path(skills / "example" / "SKILL.md"))
        self.assertIn(
            f'(allow file-read-metadata (literal '
            f'{kimi_security._literal(home / ".agents")}))', text)
        self.assertIn(
            f'(allow file-read* (subpath {kimi_security._literal(skills)}))', text)
        self.assertNotIn(
            f'(allow file-read* (subpath '
            f'{kimi_security._literal(home / ".agents")}))', text)
        self.assertNotIn(
            f'(allow file-write* (subpath {kimi_security._literal(skills)}))', text)

    def test_scoped_kimi_uses_explicit_skills_instead_of_watching_home(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            user_skills = cwd / "user-skills"
            user_skills.mkdir()
            project_skills = cwd / ".agents" / "skills"
            project_skills.mkdir(parents=True)
            with mock.patch.object(
                    kimi_security, "runtime_read_roots",
                    return_value=[cwd / ".kimi-code", user_skills]):
                dirs = kimi_security.explicit_skill_dirs(cwd)

            self.assertIn(user_skills.resolve(), dirs)
            self.assertIn(project_skills.resolve(), dirs)
            self.assertNotIn(Path.home().resolve(), dirs)

    def test_scoped_kimi_watches_a_private_home_but_keeps_real_login_state(self):
        original = {"HOME": str(Path.home()), "PATH": "/usr/bin"}
        updated, isolated = kimi_security.scoped_environment(original)
        try:
            self.assertNotEqual(updated["HOME"], original["HOME"])
            self.assertEqual(Path(updated["HOME"]), isolated)
            self.assertTrue(isolated.is_dir())
            self.assertEqual(
                Path(updated["KIMI_CODE_HOME"]),
                (Path.home() / ".kimi-code").resolve(),
            )
            self.assertEqual(original, {"HOME": str(Path.home()), "PATH": "/usr/bin"})
        finally:
            kimi_security.cleanup_home(isolated)
        self.assertFalse(isolated.exists())

    def test_kimi_security_setting_defaults_safe_and_rejects_unknown_modes(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(settings, "_path", return_value=Path(td) / "settings.json"):
            self.assertEqual(settings.masked()["kimi_security_mode"], "scoped")
            self.assertIn(settings.masked()["platform"], {"windows", "macos", "linux"})
            settings.update({"kimi_security_mode": "full"})
            self.assertEqual(settings.masked()["kimi_security_mode"], "full")
            with self.assertRaisesRegex(ValueError, "unknown Kimi security mode"):
                settings.update({"kimi_security_mode": "everything"})

    def test_database_access_mode_defaults_direct_and_rejects_unknown_modes(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(settings, "_path", return_value=Path(td) / "settings.json"), \
             mock.patch("kiss_cli.obs_access.token_configured", return_value=False):
            self.assertEqual(settings.masked()["database_access_mode"], "direct")
            settings.update({"database_access_mode": "snapshot"})
            self.assertEqual(settings.masked()["database_access_mode"], "snapshot")
            with self.assertRaisesRegex(ValueError, "unknown database access mode"):
                settings.update({"database_access_mode": "raw-token"})


class ClipboardTests(unittest.TestCase):
    def test_macos_clipboard_falls_back_to_pasteboard_commands(self):
        replies = [
            subprocess.CompletedProcess([], 0, stdout="copied text", stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
        with mock.patch.object(clipboard.platform, "system", return_value="Darwin"), \
             mock.patch.object(clipboard, "_mac_read", return_value=None), \
             mock.patch.object(clipboard, "_mac_write", return_value=None), \
             mock.patch.object(clipboard.subprocess, "run", side_effect=replies) as run:
            self.assertEqual(clipboard.read_text(), "copied text")
            self.assertTrue(clipboard.write_text("new text"))
        self.assertEqual(run.call_args_list[0].args[0], ["/usr/bin/pbpaste"])
        self.assertEqual(run.call_args_list[1].args[0], ["/usr/bin/pbcopy"])
        self.assertEqual(run.call_args_list[1].kwargs["input"], "new text")

    def test_macos_clipboard_prefers_the_bundled_native_pasteboard(self):
        with mock.patch.object(clipboard.platform, "system", return_value="Darwin"), \
             mock.patch.object(clipboard, "_mac_read", return_value="native text") as read, \
             mock.patch.object(clipboard, "_mac_write", return_value=True) as write, \
             mock.patch.object(clipboard.subprocess, "run") as run:
            self.assertEqual(clipboard.read_text(), "native text")
            self.assertTrue(clipboard.write_text("new text"))
        read.assert_called_once_with()
        write.assert_called_once_with("new text")
        run.assert_not_called()

    def test_native_window_keeps_pywebview_edit_menu_on_main_thread(self):
        source = (Path(__file__).parents[1] / "kiss_cli" / "app.py").read_text(encoding="utf-8")
        self.assertIn("webview.settings['SHOW_DEFAULT_MENUS'] = True", source)
        self.assertIn("webview.start()", source)
        self.assertNotIn("webview.start(_install_edit_menu)", source)

    def test_native_project_folder_picker_returns_one_selected_folder(self):
        with tempfile.TemporaryDirectory() as td:
            native = SimpleNamespace(FOLDER_DIALOG="folder")
            bridge = desktop_app._DesktopApi(native)
            selected = str(Path(td) / "research")
            bridge.window = SimpleNamespace(
                create_file_dialog=mock.Mock(return_value=(selected,)))

            self.assertEqual(bridge.choose_project_parent(td), selected)
            bridge.window.create_file_dialog.assert_called_once_with(
                "folder", directory=td, allow_multiple=False)

    def test_native_project_folder_picker_starts_at_existing_ancestor(self):
        native = SimpleNamespace(FOLDER_DIALOG="folder")
        bridge = desktop_app._DesktopApi(native)
        bridge.window = SimpleNamespace(create_file_dialog=mock.Mock(return_value=None))
        missing = Path(tempfile.gettempdir()) / "not-created" / "new-location"

        self.assertIsNone(bridge.choose_project_parent(str(missing)))
        bridge.window.create_file_dialog.assert_called_once_with(
            "folder", directory=str(Path(tempfile.gettempdir())),
            allow_multiple=False)


class SessionProjectTests(unittest.TestCase):
    def test_new_session_can_live_under_a_user_selected_parent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "geoforge-state"
            selected = root / "research-projects"
            selected.mkdir(parents=True)

            session = sessions.create(root, project_parent=selected)
            project = sessions.project_path(root, session)

            self.assertEqual(project.parent, selected.resolve())
            self.assertTrue(project.name.endswith(f"--{session['id']}"))
            pointer = json.loads(
                (root / "sessions" / f"{session['id']}.json").read_text(encoding="utf-8"))
            self.assertEqual(pointer["project_root"], str(project))
            loaded = sessions.load(root, session["id"])
            self.assertEqual(sessions.project_path(root, loaded), project)
            self.assertEqual(sessions.list_all(root)[0]["project_path"], str(project))

    def test_new_session_creates_a_missing_selected_parent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "geoforge-state"
            selected = base / "new" / "nested" / "research-projects"
            self.assertFalse(selected.exists())

            session = sessions.create(root, project_parent=selected)
            project = sessions.project_path(root, session)

            self.assertTrue(selected.is_dir())
            self.assertEqual(project.parent, selected.resolve())
            self.assertTrue((project / "inputs" / "uploads").is_dir())

    def test_new_session_explains_when_selected_parent_cannot_be_created(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            blocker = base / "already-a-file"
            blocker.write_text("not a folder")

            with self.assertRaisesRegex(ValueError, "could not create project location"):
                sessions.create(base / "state", project_parent=blocker / "child")

    def test_external_project_is_archived_beside_its_selected_parent(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "geoforge-state"
            selected = base / "research-projects"
            selected.mkdir()
            session = sessions.create(root, project_parent=selected)
            project = sessions.project_path(root, session)
            (project / "outputs" / "result.txt").write_text("kept")

            self.assertTrue(sessions.delete(root, session["id"]))
            self.assertFalse(project.exists())
            self.assertEqual(
                len(list((selected / "_archived").rglob("result.txt"))), 1)

    def test_new_session_rejects_a_relative_project_location(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaisesRegex(ValueError, "absolute"):
                sessions.create(Path(td), project_parent="relative/folder")

    def test_project_plot_is_created_and_only_project_artifacts_are_served(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            project = sessions.project_path(root, session)
            output = project / "artifacts" / "yield.svg"
            plotting.render_svg({
                "kind": "line", "title": "Yield", "x_label": "Year",
                "y_label": "kg/ha", "series": [{
                    "name": "DSSAT", "x": [2010, 2011], "y": [8338, 8102],
                }],
            }, output)
            self.assertIn("<svg", output.read_text(encoding="utf-8"))
            self.assertIn("artifacts/yield.svg", gui._artifact_state(project))
            resolved, ctype = gui._resolve_artifact(
                root, session["id"], "artifacts/yield.svg")
            self.assertEqual(resolved, output.resolve())
            self.assertEqual(ctype, "image/svg+xml")
            with self.assertRaises(ValueError):
                gui._resolve_artifact(root, session["id"], "../session.json")

    def test_project_plot_supports_a_separate_right_axis(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "growth.svg"
            plotting.render_svg({
                "kind": "line", "title": "Growth", "x_label": "Day",
                "y_label": "Dry weight (kg/ha)", "y2_label": "LAI",
                "series": [
                    {"name": "Biomass", "x": [0, 1], "y": [0, 16000]},
                    {"name": "LAI", "x": [0, 1], "y": [0, 4], "axis": "right"},
                ],
            }, output)
            svg = output.read_text(encoding="utf-8")
            self.assertIn("LAI (right axis)", svg)
            self.assertIn("rotate(90)", svg)
            self.assertNotIn("-960", svg)
            self.assertIn('y="508" text-anchor="middle">Day</text>', svg)

    def test_project_view_publishes_safe_dynamic_panels(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            artifacts = project / "artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "depth.svg").write_text("<svg></svg>")
            (artifacts / "stations.csv").write_text(
                "station,peak_m\nA,2.4\nB,1.8\n", encoding="utf-8")
            state = projectview.publish(project, {
                "title": "Flood progression", "summary": "Real model output",
                "skills": ["geopandas"], "kis": ["Delft3D"],
                "panels": [
                    {"kind": "metric", "title": "Peak depth",
                     "value": 2.4, "unit": "m"},
                    {"kind": "map", "title": "Maximum depth",
                     "path": "artifacts/depth.svg"},
                    {"kind": "table", "title": "Stations",
                     "path": "artifacts/stations.csv"},
                ],
            })
            self.assertTrue(state["customized"])
            loaded = projectview.load(project)
            self.assertEqual(len(loaded["panels"]), 3)
            self.assertTrue(loaded["revision"])
            self.assertTrue(all(panel["revision"] for panel in loaded["panels"]))
            self.assertEqual(loaded["panels"][2]["table"]["columns"],
                             ["station", "peak_m"])
            path, mime = projectview.resolve_asset(
                project, "artifacts/depth.svg")
            self.assertEqual(path, (artifacts / "depth.svg").resolve())
            self.assertEqual(mime, "image/svg+xml")
            with self.assertRaises(projectview.ProjectViewError):
                projectview.publish(project, {
                    "title": "Unsafe", "panels": [{
                        "kind": "image", "title": "Escape",
                        "path": "../outside.png",
                    }],
                })

    def test_project_view_auto_discovers_old_chat_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            artifacts = project / "artifacts"
            artifacts.mkdir(parents=True)
            (artifacts / "flow.webm").write_bytes(b"video")
            (artifacts / "result.png").write_bytes(b"image")
            state = projectview.load(project)
            self.assertFalse(state["customized"])
            self.assertEqual({panel["kind"] for panel in state["panels"]},
                             {"animation", "image"})
            first_revision = state["revision"]
            first_ids = {panel["path"]: panel["id"] for panel in state["panels"]}
            first_panel_revisions = {
                panel["path"]: panel["revision"] for panel in state["panels"]
            }
            (artifacts / "result.png").write_bytes(b"new-image-data")
            changed = projectview.load(project)
            self.assertNotEqual(changed["revision"], first_revision)
            self.assertEqual(
                {panel["path"]: panel["id"] for panel in changed["panels"]},
                first_ids,
            )
            changed_panel_revisions = {
                panel["path"]: panel["revision"] for panel in changed["panels"]
            }
            self.assertNotEqual(
                changed_panel_revisions["artifacts/result.png"],
                first_panel_revisions["artifacts/result.png"],
            )
            self.assertEqual(
                changed_panel_revisions["artifacts/flow.webm"],
                first_panel_revisions["artifacts/flow.webm"],
            )

    def test_api_project_plot_reads_columns_directly_from_csv(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            ki_root = project / "models" / "Demo"
            ki_root.mkdir(parents=True)
            csv_path = project / "outputs" / "growth.csv"
            csv_path.parent.mkdir(parents=True)
            csv_path.write_text(
                "DAP,CWAD,LAID\n0,0,0\n80,8000,4\n160,16000,1\n"
            )
            cfg = SimpleNamespace(root=project, python=sys.executable, roles={})
            result = api.execute_tool(
                "create_project_plot", {
                    "output_path": "artifacts/growth.svg",
                    "source_path": "outputs/growth.csv",
                    "x_column": "DAP", "kind": "line",
                    "y_label": "kg/ha", "y2_label": "LAI",
                    "series": [
                        {"name": "Biomass", "y_column": "CWAD"},
                        {"name": "Leaf area", "y_column": "LAID", "axis": "right"},
                    ],
                }, SimpleNamespace(root=ki_root), cfg, project_mode=True,
            )
            svg = (project / "artifacts" / "growth.svg").read_text(encoding="utf-8")
            self.assertIn("created growth.svg", result)
            self.assertIn("Leaf area (right axis)", svg)
            self.assertIn("160", svg)

    def test_session_has_project_layout_and_full_append_only_memory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            project = sessions.project_path(root, session)
            for expected in (
                    "session.json", "README.md", "memory/transcript.jsonl",
                    "inputs/forcing", "inputs/observations", "outputs", "runs",
                    "models", "artifacts"):
                self.assertTrue((project / expected).exists(), expected)

            for i in range(sessions.MAX_MESSAGES + 5):
                sessions.append_message(
                    root, session, {"role": "user", "text": f"message {i}"})
            sessions.save(root, session)
            loaded = sessions.load(root, session["id"])
            archived = (project / "memory" / "transcript.jsonl").read_text(encoding="utf-8").splitlines()

            self.assertEqual(len(loaded["messages"]), sessions.MAX_MESSAGES)
            self.assertEqual(loaded["message_count"], sessions.MAX_MESSAGES + 5)
            self.assertEqual(len(archived), sessions.MAX_MESSAGES + 5)

    def test_project_run_tracks_agent_work_without_claiming_an_adaptive_harness(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            started = projectrun.begin_turn(
                project, "Model maize near Harbin", ["DSSAT"])
            self.assertEqual(started["status"], "working")
            self.assertEqual(started["selected_kis"], ["DSSAT"])

            preparing = projectrun.report(project, {
                "stage": "preparing", "status": "working",
                "summary": "Preparing weather and soil inputs",
                "selected_kis": ["DSSAT"],
            })
            self.assertEqual(preparing["stage"], "preparing")

            finished = projectrun.finish_turn(project)
            self.assertEqual(finished["status"], "idle")
            self.assertEqual(finished["stage"], "preparing")
            self.assertTrue((project / "runs" / projectrun.STATE_FILE).is_file())
            self.assertTrue((project / "runs" / projectrun.EVENTS_FILE).is_file())
            self.assertIn("There is no adaptive or\nproject-specific KI harness",
                          projectrun.prompt_block(project))

    def test_agent_can_replace_goal_only_when_it_reports_one(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            original = projectrun.begin_turn(
                project, "Run the Xinxiang crop case", ["APEX"])
            projectrun.report(project, {
                "stage": "preparing", "status": "working",
                "summary": "Continuing preparation",
            })
            self.assertEqual(projectrun.load(project)["goal"], original["goal"])
            projectrun.report(project, {
                "stage": "results", "status": "complete",
                "goal": "Run the Riesel rainfed corn acceptance case",
                "summary": "Riesel case completed",
            })
            self.assertEqual(
                projectrun.load(project)["goal"],
                "Run the Riesel rainfed corn acceptance case")

    def test_project_run_turns_one_human_request_into_one_visible_blocker(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            projectrun.begin_turn(project, "Run a protected model", ["Demo"])
            state = projectrun.finish_turn(project, request={
                "status": "waiting", "kind": "licence",
                "title": "Download under your licence",
                "message": "Use the official portal.",
                "url": "javascript:alert(1)",
                "options": [
                    {"id": "copy", "label": "Copy into project",
                     "description": "Keep this project self-contained",
                     "response": "Copy the executable into outputs/bin"},
                    {"id": "share", "label": "Allow shared directory"},
                ],
            })
            self.assertEqual(state["status"], "waiting_for_user")
            self.assertEqual(state["blocker"]["title"],
                             "Download under your licence")
            self.assertIsNone(state["blocker"]["url"])
            self.assertEqual(state["blocker"]["options"][0]["id"], "copy")
            self.assertEqual(state["blocker"]["options"][0]["response"],
                             "Copy the executable into outputs/bin")
            resumed = projectrun.report(project, {
                "stage": "preparing", "status": "working",
                "summary": "The user supplied the file",
            }, source="user_upload")
            self.assertNotIn("blocker", resumed)

    def test_legacy_json_is_migrated_but_kept_as_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sid = "abcdef123456"
            legacy = root / "sessions" / f"{sid}.json"
            legacy.parent.mkdir(parents=True)
            legacy.write_text(json.dumps({
                "id": sid, "title": "Old flood run", "created": 100,
                "models": ["VIC"], "messages": [
                    {"role": "user", "text": "old message", "ts": 100},
                ],
            }))

            loaded = sessions.load(root, sid)
            project = sessions.project_path(root, loaded)

            self.assertTrue(legacy.exists())
            self.assertTrue((project / "session.json").exists())
            self.assertIn("old message", (project / "memory" / "transcript.jsonl").read_text(encoding="utf-8"))

    def test_delete_archives_project_instead_of_erasing_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            project = sessions.project_path(root, session)
            (project / "inputs" / "uploads" / "important.csv").write_text("data")

            self.assertTrue(sessions.delete(root, session["id"]))
            self.assertFalse(project.exists())
            kept = list((root / "projects" / "_archived").rglob("important.csv"))
            self.assertEqual(len(kept), 1)

    def test_finder_opens_only_the_exact_session_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            project = sessions.project_path(root, session)
            with mock.patch.object(sessions.platform, "system", return_value="Darwin"), \
                 mock.patch.object(sessions.subprocess, "Popen") as popen:
                opened = sessions.open_in_file_manager(root, session)
            self.assertEqual(opened, project)
            popen.assert_called_once_with(["/usr/bin/open", str(project)])

    def test_finder_can_open_project_data_but_rejects_paths_outside_chat(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            project = sessions.project_path(root, session)
            forcing = project / "inputs" / "forcing"
            weather = forcing / "weather.csv"
            weather.write_text("date,rain\n2000-01-01,2\n")
            with mock.patch.object(sessions.platform, "system", return_value="Darwin"), \
                 mock.patch.object(sessions.subprocess, "Popen") as popen:
                opened_folder = sessions.open_in_file_manager(
                    root, session, "inputs/forcing")
                opened_file = sessions.open_in_file_manager(
                    root, session, "inputs/forcing/weather.csv")
            self.assertEqual(opened_folder, forcing.resolve())
            self.assertEqual(opened_file, weather.resolve())
            self.assertEqual(popen.call_args_list, [
                mock.call(["/usr/bin/open", str(forcing.resolve())]),
                mock.call(["/usr/bin/open", "-R", str(weather.resolve())]),
            ])
            with self.assertRaises(ValueError):
                sessions.open_in_file_manager(root, session, "../outside")
            with self.assertRaises(ValueError):
                sessions.open_in_file_manager(root, session, str(root))

    def test_model_workspace_uses_shared_software_and_session_data(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "projects" / "scenario"
            project.mkdir(parents=True)
            package = root / "models" / "Demo"
            package.mkdir(parents=True)
            (package / "SKILL.md").write_text(
                "input=KISSPATH_FORCING/weather.nc\n"
                "output=KISSPATH_OUTPUTS/result.nc\n"
                "software=KISSPATH_HOME/Demo/bin/model\n")
            ki = KI("Demo", package)
            shared = paths.KissConfig.default(root / "shared-install")
            fake_handler = object.__new__(gui.Handler)
            fake_handler._config = lambda _ki: shared

            run_ki, cfg = gui.Handler._session_workspace(fake_handler, project, ki)
            project = project.resolve()

            materialised = (run_ki.root / "SKILL.md").read_text(encoding="utf-8")
            self.assertEqual(cfg.roles["binaries"], shared.roles["binaries"])
            self.assertEqual(cfg.roles["home"], shared.roles["home"])
            self.assertEqual(cfg.roles["forcing"], project / "inputs" / "forcing")
            self.assertEqual(cfg.roles["outputs"], project / "outputs" / "Demo")
            self.assertIn((project / "inputs" / "forcing").as_posix(), materialised)
            self.assertIn((project / "outputs" / "Demo").as_posix(), materialised)
            self.assertIn((shared.roles["home"] / "Demo" / "bin" / "model").as_posix(),
                          materialised)

            # A project-local deck can be resolved for review, but changing
            # active bindings requires explicit adoption and cannot silently
            # rewrite the already enrolled KI.
            deck = project / "outputs" / "Demo" / "case-one"
            deck.mkdir(parents=True)
            (deck / "INPUT.DAT").write_text("ready")
            model_home = project / "models" / ki.name
            original_config = (model_home / paths.CONFIG_NAME).read_bytes()
            original_ki = (run_ki.root / "SKILL.md").read_bytes()
            saved = paths.KissConfig.load(model_home)
            saved.roles["static"] = deck
            saved.roles["binaries"] = project / "untrusted-binaries"
            (model_home / paths.CONFIG_NAME).write_text(saved.dumps(), encoding="utf-8")
            rebound = gui.Handler._session_config(fake_handler, project, ki)
            self.assertEqual(rebound.roles["static"], deck)
            self.assertEqual(rebound.roles["binaries"], shared.roles["binaries"])

            changed_config = (model_home / paths.CONFIG_NAME).read_bytes()
            with self.assertRaisesRegex(ValueError, "path bindings changed"):
                gui.Handler._session_workspace(fake_handler, project, ki)
            self.assertEqual((run_ki.root / "SKILL.md").read_bytes(), original_ki)
            self.assertEqual((model_home / paths.CONFIG_NAME).read_bytes(), changed_config)

            # Direct edits are retained as evidence and refused, rather than
            # overwritten by a fresh copy or accepted as a new baseline.
            (model_home / paths.CONFIG_NAME).write_bytes(original_config)
            edited = b"unverified local edit\n"
            (run_ki.root / "SKILL.md").write_bytes(edited)
            with self.assertRaisesRegex(ValueError, "Active KI changed"):
                gui.Handler._session_workspace(fake_handler, project, ki)
            self.assertEqual((run_ki.root / "SKILL.md").read_bytes(), edited)

    def test_session_overlay_reuses_missing_local_assets_without_replacing_code(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            shared = root / "shared"
            session = root / "session"
            (shared / "reference").mkdir(parents=True)
            (shared / "reference" / "licensed.exe").write_bytes(b"MZasset")
            (shared / "tools").mkdir()
            (shared / "tools" / "run.py").write_text("old shared code")
            (session / "tools").mkdir(parents=True)
            (session / "tools" / "run.py").write_text("current bundled code")

            copied = gui._copy_missing_assets(shared, session)

            self.assertIn(Path("reference/licensed.exe"), copied)
            self.assertEqual((session / "reference" / "licensed.exe").read_bytes(),
                             b"MZasset")
            self.assertEqual((session / "tools" / "run.py").read_text(),
                             "current bundled code")

    def test_old_apex1501_status_is_not_treated_as_v0806_verification(self):
        self.assertTrue(gui._stale_apex1501_verification({
            "ok": True,
            "steps": [{"detail": "[OK] APEX1501 binary found"}],
        }))
        self.assertFalse(gui._stale_apex1501_verification({
            "ok": True,
            "steps": [{"detail": "[OK] APEX0806 Riesel run completed"}],
        }))

    def test_uploaded_data_is_confined_to_the_session_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            saved = sessions.save_upload(root, session, "../../weather data.csv", b"rain")
            project = sessions.project_path(root, session)
            self.assertEqual(saved.parent, project / "inputs" / "uploads")
            self.assertEqual(saved.name, "weather_data.csv")
            self.assertEqual(sessions.input_files(root, session)[0]["relative_path"],
                             "inputs/uploads/weather_data.csv")
            # an upload for one plan input lands where the plan card told the user
            for_item = sessions.save_upload(root, session, "site.csv", b"x", item="../site_geometry")
            self.assertEqual(for_item.parent, project / "inputs" / "user" / "site_geometry")
            message = {"role": "user", "text": "Use this weather table",
                       "attachments": ["inputs/uploads/weather_data.csv"]}
            self.assertIn("inputs/uploads/weather_data.csv",
                          sessions.message_text(message))
            session["messages"].append(message)
            self.assertIn("FILES ATTACHED TO THIS MESSAGE",
                          sessions.transcript(session))

    def test_project_provenance_summarises_downloads_and_deduplicates_copies(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            project = sessions.project_path(root, session)
            provenance = {
                "upstream_source": {
                    "repo_url": "https://github.com/example/model-data",
                    "files_fetched_at_commit": "abc123",
                },
                "note": "Public reference inputs used by the real run.",
                "downloaded_files": {"rain.txt": {
                    "saved_to": "inputs/rain.txt", "bytes": 42,
                    "sha256": "f" * 64,
                }},
            }
            first = project / "inputs" / "reference" / "PROVENANCE.json"
            first.parent.mkdir(parents=True)
            first.write_text(json.dumps(provenance))
            duplicate = project / "outputs" / "Demo" / "provenance.json"
            duplicate.parent.mkdir(parents=True)
            duplicate.write_text(json.dumps(provenance))
            manifest = project / "runs" / "case" / "run_manifest.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                "source_prj": "/shared/KI/reference.prj",
                "source_obs": "/shared/KI/reference.obs",
            }))
            artifact = project / "artifacts" / "public_data_provenance.json"
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(json.dumps({
                "source_urls": {
                    "Public_weather": "https://example.test/viewer",
                    "Public_weather_API": "https://example.test/weather",
                },
                "transformations": ["rain kept as mm/day"],
                "input_checksums": {"inputs/weather.csv": "a" * 64},
            }))
            reproducibility = project / "runs" / "case" / "reproducibility_manifest.json"
            reproducibility.write_text(json.dumps({"official_sources": {
                "gauge": {
                    "source": "Official gauge archive",
                    "urls": {"daily_query_url": "https://example.test/gauge"},
                    "files": {"inputs/gauge.csv": {
                        "bytes": 21, "sha256": "b" * 64,
                    }},
                },
                "terrain": {
                    "source": "Public terrain tiles",
                    "source_index_url": "https://example.test/dem",
                    "tiles": [{"path": "inputs/dem.tif", "bytes": 99,
                               "sha256": "c" * 64}],
                },
            }}))

            records = sessions.provenance_records(root, session)

            self.assertEqual(len(records), 5)
            downloaded = next(r for r in records if r["version"])
            self.assertEqual(downloaded["version"], "abc123")
            self.assertEqual(downloaded["checksum_count"], 1)
            self.assertEqual(downloaded["files"][0]["name"], "rain.txt")
            weather = next(r for r in records if r["title"] == "Public weather API")
            self.assertEqual(weather["relative_path"],
                             "artifacts/public_data_provenance.json")
            self.assertEqual(weather["url"], "https://example.test/weather")
            self.assertEqual(weather["checksum_count"], 1)
            self.assertIn("mm/day", weather["note"])
            gauge = next(r for r in records if r["title"] == "Official gauge archive")
            self.assertEqual(gauge["checksum_count"], 1)
            terrain = next(r for r in records if r["title"] == "Public terrain tiles")
            self.assertEqual(terrain["files"][0]["name"], "dem.tif")
            copied = next(r for r in records if not r["url"])
            self.assertEqual(copied["title"], "Installed KI reference data")
            self.assertEqual(
                copied["method"], "Copied from the installed KI reference data")

    def test_user_supplied_papers_stay_in_this_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            saved = sessions.save_reference(root, session, "model paper.pdf", b"%PDF")
            project = sessions.project_path(root, session)
            self.assertEqual(saved, project / "references" / "papers" / "model_paper.pdf")
            self.assertEqual(sessions.reference_files(root, session)[0]["name"],
                             "model_paper.pdf")
            with self.assertRaisesRegex(ValueError, "PDF"):
                sessions.save_reference(root, session, "paper.txt", b"not a pdf")


class CalibrationIntegrationTests(unittest.TestCase):
    def test_one_shared_engine_and_one_editable_adapter_per_project(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            framework = root / "framework"
            for rel in (
                    "calibration_kit/__init__.py",
                    "calibration_kit/CALIBRATION_YAML_SCHEMA.md",
                    "calibration_kit/CALIBRATION_FRAMEWORK_DESIGN.md"):
                path = framework / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(rel)
            ki_root = root / "models" / "Demo"
            (ki_root / "tools").mkdir(parents=True)
            (ki_root / "calibration.yaml").write_text("model_id: Demo\n")
            (ki_root / "tools" / "calib_run.py").write_text("print('real model')\n")
            project = root / "project"

            with mock.patch.dict(
                    calibration.os.environ,
                    {"GEOFORGE_CALIBRATION_FRAMEWORK": str(framework)}):
                status = calibration.ensure_project(project, [KI("Demo", ki_root)])
                rules = calibration.prompt_block(project, [KI("Demo", ki_root)])
                env = calibration.with_framework_env({"PYTHONPATH": "/existing"})

            self.assertTrue(status["available"])
            self.assertEqual(status["adapters"][0]["status"], "ready")
            self.assertTrue((project / "calibration" / "kis" / "Demo" /
                             "calibration.yaml").is_file())
            self.assertTrue((project / "calibration" / "kis" / "Demo" /
                             "tools" / "calib_run.py").is_file())
            self.assertIn("Shared fixed engine", rules)
            self.assertIn("not an adaptive KI", rules)
            self.assertEqual(env["GEOFORGE_CALIBRATION_FRAMEWORK"],
                             str(framework.resolve()))
            self.assertIn(str(framework.resolve()),
                          env["PYTHONPATH"].split(os.pathsep))

    def test_missing_ki_adapter_is_reported_without_fake_calibration(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "models" / "Demo"
            ki_root.mkdir(parents=True)
            status = calibration.ensure_project(root / "project", [KI("Demo", ki_root)])
            self.assertEqual(status["adapters"][0]["status"], "authoring-needed")
            # The engine is app-level now; one KI missing an adapter must not
            # make the shared framework itself disappear.
            self.assertTrue(status["available"])

    def test_project_state_keeps_auto_ki_adapter_and_summarises_runs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "models" / "Demo"
            (ki_root / "tools").mkdir(parents=True)
            (ki_root / "calibration.yaml").write_text("model_id: Demo\n")
            (ki_root / "tools" / "calib_run.py").write_text("print('model')\n")
            project = root / "project"

            calibration.ensure_project(project, [KI("Demo", ki_root)])
            # Auto-KI prompt composition has no pinned KI on its next turn; it
            # must not erase the adapter learned from project progress.
            calibration.ensure_project(project)
            case = project / "calibration" / "cases" / "observed.csv"
            case.write_text("date,flow\n2000-01-01,1\n")
            run = project / "calibration" / "runs" / "run-1"
            run.mkdir(parents=True)
            (run / "engine.log").write_text("real model ran\n")
            (run / "report.json").write_text(json.dumps({
                "run_id": "run-1", "ki": "Demo", "algorithm": "dds",
                "budget": 20, "seed": 4,
                "report": {"status": "completed", "promotable": True,
                           "backend": "spotpy:dds", "best_loss": [0.2],
                           "best_params": {"x": 1.5},
                           "holdout": {"passed": True}},
            }))

            state = calibration.project_state(project)

            self.assertEqual(state["ready_adapter_count"], 1)
            self.assertEqual(state["case_count"], 1)
            self.assertEqual(state["run_count"], 1)
            self.assertEqual(state["latest_run"]["ki"], "Demo")
            self.assertTrue(state["latest_run"]["promotable"])
            self.assertEqual(state["latest_run"]["report_path"],
                             "calibration/runs/run-1/report.json")


class SkillLibraryTests(unittest.TestCase):
    def test_existing_agent_skill_homes_are_merged_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            agents = root / "agents"
            codex = root / "codex"
            for base, name, desc in (
                    (agents, "plotly", "Interactive scientific plots"),
                    (codex, "plotly", "Duplicate should lose"),
                    (codex, "geopandas", "Geospatial table analysis")):
                directory = base / name
                directory.mkdir(parents=True)
                (directory / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: {desc}\n---\n# {name}\n")
            with mock.patch.object(skilllib, "roots", return_value=[agents, codex]):
                found = skilllib.discover()
                block = skilllib.prompt_block(["geopandas"])
                read = skilllib.read("plotly")

            self.assertEqual([item["name"] for item in found], ["geopandas", "plotly"])
            self.assertEqual(found[1]["description"], "Interactive scientific plots")
            self.assertIn("geopandas/SKILL.md", block)
            self.assertIn("Interactive scientific plots", read)


class McpConnectionTests(unittest.TestCase):
    def test_discovery_reports_names_but_never_secrets(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / ".codex").mkdir()
            (home / ".codex" / "config.toml").write_text(
                '[mcp_servers.github]\ncommand="docker"\n'
                '[mcp_servers.github.env]\nTOKEN="do-not-return"\n')
            (home / ".claude.json").write_text(json.dumps({
                "mcpServers": {"files": {"command": "server", "env": {"KEY": "secret"}}},
            }))
            found = mcp.discover(home)

            encoded = json.dumps(found)
            self.assertEqual([item["name"] for item in found], ["files", "github"])
            self.assertNotIn("do-not-return", encoded)
            self.assertNotIn("secret", encoded)

    def test_github_setup_uses_official_server_without_storing_a_token(self):
        def which(name):
            return {"codex": "/bin/codex", "docker": "/bin/docker"}.get(name)

        with mock.patch.object(mcp, "status", return_value={
                "github": {"configured": False, "clients": []}}), \
             mock.patch.object(mcp.shutil, "which", side_effect=which), \
             mock.patch.object(mcp.subprocess, "run", return_value=SimpleNamespace(
                 returncode=0, stdout="", stderr="")) as run:
            result = mcp.configure_github_for_codex()

        argv = run.call_args.args[0]
        self.assertTrue(result["ok"])
        self.assertIn("ghcr.io/github/github-mcp-server", argv)
        self.assertIn("GITHUB_OAUTH_CALLBACK_PORT=8085", argv)
        self.assertFalse(any("TOKEN" in arg for arg in argv))


class FrontendRegressionTests(unittest.TestCase):
    def test_windows_tray_right_click_offers_open_and_real_exit(self):
        source = (Path(__file__).parents[1] / "kiss_cli" /
                  "windows_tray.py").read_text(encoding="utf-8")
        self.assertIn('"Open GeoForge"', source)
        self.assertIn('"Exit GeoForge"', source)
        self.assertIn("TrackPopupMenu", source)
        self.assertIn("Shell_NotifyIconW(NIM_DELETE", source)
        self.assertIn("os._exit(0)", source)

    def test_environment_selfcheck_proves_the_harness_before_providers(self):
        source = (Path(__file__).parents[1] / "kiss_cli" / "gui.py").read_text(encoding="utf-8")
        self.assertIn("[1/6] KI harness contract", source)
        self.assertIn("harness_runtime.status", source)

    def test_explicit_autonomous_chat_does_not_require_a_second_approval(self):
        self.assertIn("continue into the tools in this SAME", gui.SCOPE_FIRST_RULES)
        self.assertIn("Do not ask them to approve the work again", gui.SCOPE_FIRST_RULES)

    def test_cli_model_picker_has_native_default_and_starts_disabled(self):
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html").read_text(encoding="utf-8")
        self.assertIn("CLI default", page)
        self.assertIn("Auto KI", page)

    def test_chat_stream_hides_keepalives_and_explains_real_disconnects(self):
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html").read_text(encoding="utf-8")
        self.assertIn('replaceAll("\\u200b","")', page)
        self.assertIn("GEOFORGE_INTAKE", page)
        self.assertIn('(?:-->|$)/g,"")', page)
        self.assertIn("The live response connection was interrupted", page)
        self.assertNotIn("The request failed: ${e.message||e}", page)
        self.assertIn("Verified on this machine", page)
        self.assertIn('src="/logo.svg"', page)
        self.assertIn('id="newsess" disabled', page)
        self.assertIn("setControls(true)", page)
        self.assertIn('<script src="/clipboard.js"></script>', page)
        self.assertIn('<script src="/i18n.js"></script>', page)
        self.assertIn('data-language-toggle', page)
        self.assertIn('GeoForgeI18n.isChineseText(text)', page)
        bridge = (Path(__file__).parents[1] / "kiss_cli" / "web" / "clipboard.js").read_text(encoding="utf-8")
        self.assertIn("/api/clipboard", bridge)
        self.assertIn("contextmenu", bridge)
        self.assertIn("e.metaKey||e.ctrlKey", bridge)
        self.assertIn("navigator.clipboard", bridge)
        self.assertIn("Copy this message", page)
        self.assertIn("Recheck local CLIs", page)
        self.assertIn("/api/providers?refresh=1", page)
        self.assertIn('id="s-proxy-mode"', page)
        self.assertIn('id="s-proxy-url"', page)
        self.assertIn('id="s-obs-token"', page)
        self.assertIn('id="s-obs-mode"', page)
        self.assertIn("Direct through GeoForge Desktop (recommended)", page)
        self.assertIn('id="s-obs-test"', page)
        self.assertIn("Activation token", page)
        self.assertIn("Save &amp; test database", page)
        # settings window: sidebar pages, provider cards, catalogue browser
        for marker in ('class="setnav"', 'data-page="ai"', 'data-page="db"', 'data-page="net"', 'data-page="perm"',
                       'id="s-providers"', 'id="db-facets"', 'id="db-list"', "loadDatabaseBrowser", "KEY_ENV"):
            self.assertIn(marker, page)
        self.assertIn("/api/obs/test", page)
        self.assertIn("/api/obs/catalogue", page)
        self.assertIn("GeoForge Database", page)
        self.assertIn("applicable_domains", page)
        self.assertIn("spatial_coverage", page)
        self.assertIn("observation download tool", page)
        self.assertIn("renderPlanReview", page)
        self.assertIn('id="plan-data"', page)
        self.assertIn('id="request-done"', page)
        self.assertIn('id="action-plan"', page)
        self.assertIn("Test AI &amp; GitHub", page)
        self.assertIn("agent-run Git, pip, curl, and download commands", page)
        self.assertIn("/api/selfcheck?provider=", page)
        self.assertIn("refreshMachineStatus", page)
        self.assertIn('fetch("/api/status",{cache:"no-store"})', page)
        self.assertIn("refreshMachineStatus(true,true)", page)
        self.assertIn("A chat agent can finish or repair shared scientific software", page)
        self.assertIn("Local CLIs are installed but not ready", page)
        self.assertIn("sign-in needed", page)
        self.assertIn("update needed", page)
        self.assertIn("login checked on first use", page)
        self.assertIn('id="openproject" disabled', page)
        self.assertIn("/open`,{method:\"POST\"", page)
        self.assertIn("Archive this chat? Its local project files will be kept.", page)
        self.assertIn('id="skillpick"', page)
        self.assertIn('id="skills" class="composer-tool"', page)
        self.assertIn('id="attach" class="composer-tool"', page)
        self.assertIn('id="chatfiles" multiple', page)
        self.assertIn('id="dropzone"', page)
        self.assertIn("addChatFiles", page)
        self.assertIn("attachments:attachments.map", page)
        self.assertIn("const INFLIGHT=new Map()", page)
        self.assertIn('$("#newsess").disabled=false', page)
        self.assertIn('id="activitynote"', page)
        self.assertIn("has produced no tool or output event for", page)
        self.assertIn("No download, tool-call, or project-file evidence", page)
        self.assertIn("status.activity_detail", page)
        self.assertIn("Last observed action:", page)
        self.assertIn('id="activityevidence"', page)
        self.assertIn('id="activity-refresh"', page)
        self.assertIn("/agent-status", page)
        self.assertIn("event_silence_seconds", page)
        self.assertIn('id="activity-new"', page)
        self.assertIn("setInterval(updateActivityUI,1000)", page)
        self.assertIn('id="actionpick"', page)
        self.assertEqual(page.count('class="modal-x"'), 7)
        self.assertIn("MODAL_OVERLAY_IDS", page)
        self.assertIn('event.key!=="Escape"', page)
        self.assertIn("dismissModalOverlay(event.target)", page)
        self.assertIn("showActionPicker", page)
        self.assertIn("Continue with this choice", page)
        self.assertIn("Ask about these choices", page)
        self.assertIn("Calibrate with agent", page)
        self.assertIn("Add observations", page)
        self.assertIn("calibrationAgentPrompt", page)
        self.assertIn("latest_run", page)
        self.assertIn("request.options", page)
        self.assertIn("/request`", page)
        self.assertNotIn("MCPPICK=new Set(), busy=false", page)
        self.assertIn("/api/skills", page)
        self.assertIn("/skill-name", page)
        self.assertIn("create_project_plot", (Path(__file__).parents[1] / "kiss_cli" / "api.py").read_text(encoding="utf-8"))
        self.assertIn("chat-artifact", page)
        self.assertIn("/artifact?path=", page)
        self.assertIn("renderMarkdownTables", page)
        self.assertIn(".md-table", page)
        self.assertIn("Some providers double-escape Markdown", page)
        self.assertIn("AUTOMATIC SKILL USE AND INLINE RESULTS", gui.AUTOMATIC_SKILL_RULES)
        self.assertIn("SKILLS SELECTED BY THE USER", gui.SESSION_PROJECT_RULES + skilllib.prompt_block([]) + (Path(__file__).parents[1] / "kiss_cli" / "skilllib.py").read_text(encoding="utf-8"))
        self.assertIn('id="datapanel"', page)
        self.assertIn('id="viewpanel"', page)
        self.assertIn('id="openview" disabled', page)
        self.assertIn("refreshProjectView", page)
        self.assertIn("VIEW_RENDERED_KEY", page)
        self.assertIn("pauseProjectMedia", page)
        self.assertIn("patchProjectView", page)
        self.assertIn("/view-asset?path=", page)
        self.assertIn("Build or update with Agent", page)
        self.assertIn("/data`", page)
        self.assertIn("Upload other files", page)
        self.assertIn("Project status", page)
        self.assertIn("Continue in chat", page)
        self.assertIn("progressTitle", page)          # the progress card carries the run status line
        self.assertIn("Data for this run", page)
        self.assertIn("Data sources & download record", page)
        self.assertIn("refreshSessionList", page)
        self.assertIn("setInterval(refreshSessionList,5000)", page)
        self.assertIn("Only confirmed gaps", page)
        self.assertIn("Resolve group with agent", page)
        self.assertIn("Model data appears after the conversation chooses a KI.", page)
        self.assertIn("Built dynamically from", page)
        self.assertIn('data-open-path', page)
        self.assertIn("Open all inputs", page)
        self.assertIn("Open folder", page)
        self.assertIn("local_file_count", page)
        self.assertIn("dataAgentPrompt", page)
        self.assertIn("requirement-resolve", page)
        self.assertIn("data-requirement-card", page)
        self.assertIn("requirement-explain", page)
        self.assertIn("dataExplainPrompt", page)
        self.assertIn("Ask agent: what is this?", page)
        self.assertIn("category-level readiness", page)
        self.assertIn("KI-declared requirements in this group include", page)
        self.assertIn("See technical data details", page)
        self.assertIn("Checked data paths", page)
        self.assertIn("project_status", page)
        self.assertIn("technical.lanes", page)
        self.assertNotIn('const dataReached=', page)
        self.assertIn("datasetChecks", page)
        self.assertIn("extractWork", page)
        self.assertIn("Work details", page)
        self.assertIn("USER-FACING RESPONSE", gui.RESPONSE_PRESENTATION_RULES)
        self.assertIn("SIMPLIFIED CHINESE", gui.response_language_rules("请运行这个模型"))
        self.assertIn("latest message", gui.response_language_rules("Run this model"))
        locale = (Path(__file__).parents[1] / "kiss_cli" / "web" / "i18n.js").read_text(encoding="utf-8")
        self.assertIn('"New chat": "新建对话"', locale)
        self.assertIn('"Data for this run": "本次运行的数据"', locale)
        self.assertIn('"Resolve with agent": "让 Agent 解决"', locale)
        self.assertIn('"See technical data details": "查看技术数据明细"', locale)
        self.assertIn('.bubble,.log', locale)
        self.assertIn('navigator.language', locale)
        self.assertNotIn("The agent handles the setup", page)
        self.assertIn("See technical data details", page)
        self.assertIn("Optional model reading", page)
        self.assertIn("paper-upload", page)
        self.assertIn('id="connections"', page)
        self.assertIn("/api/mcp", page)
        self.assertIn("Configure for Codex", page)

    def test_library_is_for_browse_import_and_verification(self):
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" / "library.html").read_text(encoding="utf-8")
        self.assertIn("Browse, import, and verify KIs", page)
        self.assertIn("Check &amp; Import", page)
        self.assertIn("KI package check", page)
        self.assertEqual(page.count('class="modal-x"'), 3)
        self.assertIn("LIBRARY_MODAL_IDS", page)
        self.assertIn("dismissLibraryModal(event.target)", page)
        self.assertIn("Run data", page)
        self.assertIn("Explain my data", page)
        self.assertIn("/api/data-guide", page)
        self.assertIn("Set up with agent", page)
        self.assertIn('<script src="/i18n.js"></script>', page)
        self.assertIn('language:window.GeoForgeI18n', page)
        self.assertIn('location.href="/setup?model="', page)
        self.assertIn("primary_error", page)
        self.assertIn("pre.live-log", page)
        self.assertNotIn('id="send"', page)

    def test_observatory_projects_all_kis_without_executing_them(self):
        models = Path(__file__).parents[2] / "models"
        catalog = Catalog(models)
        atlas = observatory.atlas(
            catalog, lambda _ki: {"state": "setup", "can_run": False,
                                  "label": "Setup needed"})
        self.assertEqual(len(atlas["domains"]), 14)
        self.assertEqual(len(atlas["nodes"]), len(catalog))
        self.assertEqual(sum(row["count"] for row in atlas["domains"]), len(catalog))
        self.assertTrue(all(edge["evidence"] for edge in atlas["edges"]))
        self.assertTrue(all(edge["source"] != edge["target"]
                            for edge in atlas["domain_edges"]))
        self.assertTrue(all(edge["count"] >= 1 and edge["evidence"]
                            for edge in atlas["domain_edges"]))
        detail = observatory.model(
            catalog.get("VIC"), {"state": "verified", "can_run": True,
                                 "label": "Verified"})
        self.assertTrue(detail["safety"]["read_only"])
        self.assertFalse(detail["safety"]["executes_ki_code"])
        self.assertIn("verification", {node["kind"] for node in detail["graph"]["nodes"]})
        node_ids = {node["id"] for node in detail["graph"]["nodes"]}
        self.assertTrue(set(detail["overview"]["process_ids"]) <= node_ids)
        self.assertTrue(set(detail["overview"]["hidden_process_ids"]) <= node_ids)
        self.assertGreaterEqual(len(detail["story"]["phases"]), 4)
        self.assertEqual(detail["story"]["source"], "scientific_projection")
        self.assertTrue(all(phase["title"] and phase["title_zh"]
                            for phase in detail["story"]["phases"]))
        self.assertTrue(all(isinstance(phase["node_ids"], list)
                            for phase in detail["story"]["phases"]))
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" /
                "observatory.html").read_text(encoding="utf-8")
        self.assertIn("14 scientific domains", page)
        self.assertIn("/api/observatory", page)
        self.assertIn("Scientific coupling", page)
        self.assertIn('STATE={level:"domains"', page)
        self.assertIn('data-action="domain"', page)
        self.assertIn('data-action="ki"', page)
        self.assertIn('class="scienceflow"', page)
        self.assertIn('data-phase=', page)
        self.assertIn("Technical evidence", page)
        self.assertIn('relation:"off"', page)
        self.assertIn("Full technical DAG", page)
        self.assertIn("arXiv:2605.17856", page)
        self.assertIn('fetch("/api/sessions",{method:"POST"', page)
        self.assertIn('JSON.stringify({models:[model]})', page)
        self.assertIn('kiss.autosend.', page)
        self.assertNotIn('SESSIONS[0]?.id', page)

    def test_agent_setup_has_a_separate_human_handoff_page(self):
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" / "setup.html").read_text(encoding="utf-8")
        self.assertIn("The agent reads this KI and its KDT diagnostics", page)
        self.assertIn("/api/setup-agent", page)
        self.assertIn("/api/setup-resume", page)
        self.assertIn("/api/setup-upload", page)
        self.assertIn("Needs you", page)
        self.assertIn("Needs you now", page)
        self.assertIn("Continue repair", page)
        self.assertIn("copycommand", page)
        self.assertIn("I can't do this — help me", page)
        self.assertIn("chatForHelp", page)
        self.assertIn('<script src="/i18n.js"></script>', page)
        self.assertIn('我在设置', page)
        self.assertIn("presentSetupLog", page)
        self.assertIn("summarizeToolBlock", page)
        self.assertIn("Waiting for your permission", page)
        self.assertIn("setInterval(loadState,1500)", page)
        self.assertIn("managedWorkspacePermission", page)
        self.assertIn("View the full technical report", page)
        self.assertIn("Allow for this model — continue", page)
        self.assertIn('id="setupactivity"', page)
        self.assertIn('class="agent-orbit"', page)
        self.assertIn("lastSignalAt=Date.now()", page)
        self.assertIn("Agent process connected", page)
        self.assertIn("setInterval(drawRunState,1000)", page)
        self.assertIn("prefers-reduced-motion:reduce", page)
        self.assertIn('id="installpath"', page)
        self.assertIn("Model installation workspace", page)
        self.assertIn("chooseInstallLocation", page)
        self.assertIn("/api/setup-location", page)
        self.assertIn("GeoForge will create it and record the choice", page)
        self.assertIn("Use software already installed", page)
        self.assertIn('id="existingpath"', page)
        self.assertIn("Let Agent find and verify it", page)
        self.assertIn("discover_existing", page)
        self.assertIn("will not overwrite the existing software", page)
        self.assertNotIn('req.expected_path||["download","licence"]', page)
        chat = (Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html").read_text(encoding="utf-8")
        self.assertIn("kiss.draft.", chat)


class DataPlanTests(unittest.TestCase):
    def test_plan_combines_dag_declarations_with_local_file_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            forcing = root / "forcing"
            forcing.mkdir()
            (forcing / "weather.nc").write_text("present")
            ki = SimpleNamespace(name="Demo", dag_doc={
                "inputs": {
                    "forcing": [{"name": "rain", "unit": "mm/day"}],
                    "parameters": [{"name": "soil"}],
                },
                "outputs": [{"var": "runoff", "unit": "mm/day"}],
            })
            man = Manifest(model="Demo", data=[
                DataNeed(role="forcing", name="Weather", probe="weather.nc"),
                DataNeed(role="obs", name="Gauge observations", optional=True),
            ])
            cfg = SimpleNamespace(roles={"forcing": forcing, "obs": root / "obs"})
            plan = gui.build_data_plan(
                ki, man, cfg,
                {"state": "verified", "label": "Verified on this Mac", "can_run": True},
            )

        self.assertFalse(plan["generated_by_ai"])
        self.assertEqual(plan["run_readiness"]["state"], "ready")
        self.assertEqual(plan["input_count"], 2)
        self.assertEqual(plan["outputs"][0]["name"], "runoff")
        self.assertEqual(plan["dataset_contract"], {
            "declared": True, "required": 1, "ready": 1, "missing": 0, "optional": 1,
        })
        self.assertTrue(plan["datasets"][0]["present"])
        self.assertFalse(plan["datasets"][1]["present"])

    def test_empty_required_directory_is_not_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            empty = root / "static"
            empty.mkdir()
            ki = SimpleNamespace(name="Demo", dag_doc={})
            man = Manifest(model="Demo", data=[
                DataNeed(role="static", name="Model input directory"),
            ])
            cfg = SimpleNamespace(roles={"static": empty})

            missing = gui.build_data_plan(
                ki, man, cfg,
                {"state": "verified", "label": "Verified", "can_run": True},
            )
            self.assertEqual(missing["run_readiness"]["state"], "data_missing")
            self.assertFalse(missing["datasets"][0]["present"])

            (empty / "input.dat").write_text("real input")
            ready = gui.build_data_plan(
                ki, man, cfg,
                {"state": "verified", "label": "Verified", "can_run": True},
            )
            self.assertEqual(ready["run_readiness"]["state"], "ready")
            self.assertTrue(ready["datasets"][0]["present"])

    def test_nested_parameter_groups_are_not_hidden(self):
        ki = SimpleNamespace(name="DSSAT-like", dag_doc={
            "inputs": {"parameters": {
                "critical": [{"name": "cultivar_selection"}],
                "experiment_file": [{"name": "FileX"}],
            }}
        })
        man = Manifest(model="DSSAT-like")
        cfg = SimpleNamespace(roles={})
        plan = gui.build_data_plan(
            ki, man, cfg,
            {"state": "verified", "label": "Verified", "can_run": True},
        )
        items = plan["input_groups"][1]["items"]
        self.assertEqual([item["name"] for item in items], ["cultivar_selection", "FileX"])
        self.assertEqual(items[0]["subgroup"], "critical")


class ProjectPreparationTests(unittest.TestCase):
    def test_auto_ki_session_uses_the_model_selected_in_the_conversation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = sessions.create(root)
            project = sessions.project_path(root, session)
            ki_root = root / "models" / "Demo"
            (ki_root / "docs").mkdir(parents=True)
            (ki_root / "docs" / "format_spec.yaml").write_text("inputs: {}\n")
            ki = SimpleNamespace(
                name="Demo", root=ki_root,
                dag_doc={"inputs": {"forcing": [{"name": "rainfall"}]}},
            )
            projectrun.select_kis(project, ["Demo"])
            handler = object.__new__(gui.Handler)
            handler.workroot = root
            handler._ki = lambda name: ki if name == "Demo" else None
            handler._manifest = lambda _ki: SimpleNamespace(depends_on=[])
            handler._session_config = lambda _project, _ki: SimpleNamespace(roles={
                "data": project / "inputs",
                "forcing": project / "inputs" / "forcing",
                "obs": project / "inputs" / "observations",
                "static": project / "inputs" / "static",
                "data_ki": project / "inputs",
            })
            handler._status_for = lambda _ki: {"state": "verified", "can_run": True}
            plan = {"model": "Demo", "software": {"can_run": True},
                    "datasets": [], "outputs": []}
            with mock.patch.object(gui, "build_data_plan", return_value=plan), \
                 mock.patch.object(gui.calibration, "project_state", return_value={}):
                data = handler._session_data(session)

        self.assertFalse(data["auto_ki"])
        self.assertEqual([item["model"] for item in data["plans"]], ["Demo"])
        self.assertTrue(data["preparation"]["active"])
        self.assertEqual(data["preparation"]["models"][0]["name"], "Demo")
        source = next(lane for lane in data["preparation"]["lanes"]
                      if lane["id"] == "source_data")
        self.assertEqual(source["items"][0]["name"], "rainfall")

    def test_data_locations_are_real_project_folders_grouped_by_model_need(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            forcing = project / "inputs" / "forcing"
            static = project / "inputs" / "static"
            forcing.mkdir(parents=True)
            static.mkdir(parents=True)
            (forcing / "weather.csv").write_text("rain\n2\n")
            (static / "dem.tif").write_text("dem")
            ki_root = root / "Demo"
            (ki_root / "docs").mkdir(parents=True)
            (ki_root / "docs" / "format_spec.yaml").write_text("inputs: {}\n")
            ki = SimpleNamespace(name="Demo", root=ki_root, dag_doc={"inputs": {
                "forcing": [{"name": "weather"}],
                "parameters": [{"name": "elevation per grid cell"}],
            }})
            files = [
                {"name": "weather.csv", "relative_path": "inputs/forcing/weather.csv"},
                {"name": "dem.tif", "relative_path": "inputs/static/dem.tif"},
            ]
            result = preparation.build(
                [ki], [{"model": "Demo", "software": {"can_run": True},
                        "datasets": [], "outputs": []}], project, files,
                role_paths={"Demo": {
                    "data": project / "inputs", "forcing": forcing,
                    "static": static,
                }},
            )

        by_lane = {lane["id"]: lane for lane in result["lanes"]}
        self.assertEqual(by_lane["source_data"]["local_file_count"], 1)
        self.assertEqual(by_lane["spatial_parameters"]["local_file_count"], 1)
        self.assertIn("inputs/forcing", {
            row["relative_path"] for row in by_lane["source_data"]["locations"]})
        self.assertIn("inputs/static", {
            row["relative_path"] for row in by_lane["spatial_parameters"]["locations"]})
        self.assertEqual(by_lane["source_data"]["input_root"]["relative_path"], "inputs")

    def test_multiple_models_share_source_data_but_keep_format_variants(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            (project / "references" / "papers").mkdir(parents=True)
            kis = []
            for name, unit, file in (("One", "mm/day", "one.nc"),
                                     ("Two", "kg/m2/s", "two.txt")):
                ki_root = root / name
                (ki_root / "docs").mkdir(parents=True)
                (ki_root / "docs" / "format_spec.yaml").write_text(
                    f"inputs:\n  forcing:\n    - name: precipitation\n      unit: {unit}\n      file: {file}\n")
                (ki_root / "docs" / "papers.json").write_text(
                    json.dumps({"model": name, "papers": [{
                        "doi": "10.1/example", "title": f"{name} paper",
                        "role": "benchmark", "access": "open",
                        "serves": ["runoff"],
                    }]})
                )
                kis.append(SimpleNamespace(
                    name=name, root=ki_root,
                    dag_doc={"inputs": {"forcing": [{"name": "precipitation"}]}}
                ))
            plans = [{"model": name, "software": {"can_run": True},
                      "outputs": [{"name": "runoff"}]} for name in ("One", "Two")]

            result = preparation.build(kis, plans, project, [], auto_ki=False)

        source = next(lane for lane in result["lanes"] if lane["id"] == "source_data")
        rain = next(item for item in source["items"] if item["name"] == "precipitation")
        self.assertEqual(rain["models"], ["One", "Two"])
        self.assertEqual({v["unit"] for v in rain["variants"]}, {"mm/day", "kg/m2/s"})
        self.assertEqual(result["software_summary"]["ready"], 2)
        self.assertEqual(len(result["literature"]), 2)

    def test_grid_parameters_and_scientific_choices_are_separated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "VIC"
            (ki_root / "docs").mkdir(parents=True)
            (ki_root / "docs" / "format_spec.yaml").write_text("inputs: {}\n")
            ki = SimpleNamespace(name="VIC", root=ki_root, dag_doc={"inputs": {
                "parameters": [
                    {"name": "soil_depth", "notes": "one value per grid cell",
                     "source_kind": "dataset_lookup"},
                    {"name": "binfilt", "source_kind": "calibrated"},
                ]
            }})
            result = preparation.build(
                [ki], [{"model": "VIC", "software": {"can_run": True}, "outputs": []}],
                root / "project", [], auto_ki=False,
            )

        by_lane = {lane["id"]: lane for lane in result["lanes"]}
        self.assertEqual(by_lane["spatial_parameters"]["items"][0]["name"], "soil depth")
        self.assertEqual(by_lane["choices"]["items"][0]["action"], "needs_decision")


class InstallLocationTests(unittest.TestCase):
    def test_user_can_select_a_folder_that_does_not_exist_yet(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "external-disk" / "scientific-models" / "DSSAT"

            selected = install_locations.select(root / "geoforge", "DSSAT", target)

            self.assertEqual(selected, target.resolve())
            self.assertTrue(target.is_dir())
            self.assertEqual(
                install_locations.resolve(root / "geoforge", "dssat"),
                target.resolve(),
            )
            info = install_locations.info(root / "geoforge", "DSSAT")
            self.assertTrue(info["custom"])
            self.assertEqual(info["path"], str(target.resolve()))

    def test_install_path_is_recorded_beside_ki_without_mutating_its_source(self):
        with tempfile.TemporaryDirectory() as td:
            workroot = Path(td) / "geoforge"
            workspace = Path(td) / "chosen" / "VIC"
            install_locations.select(workroot, "VIC", workspace)
            live = workspace / "ki"
            live.mkdir(parents=True)
            (live / "SKILL.md").write_text("# VIC fixture\n")
            from kiss_cli import ki_guard
            ki_guard.enroll(live)
            cfg = paths.KissConfig.default(workspace)
            (workspace / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")

            value = install_locations.record(
                "VIC", workspace, cfg, ki_root=live, verified=True)

            outer = json.loads(
                (workspace / install_locations.RECORD_FILE).read_text(encoding="utf-8"))
            self.assertFalse((live / install_locations.RECORD_FILE).exists())
            self.assertEqual(outer["ki_root"], str(live.resolve()))
            self.assertEqual(outer["workspace"], str(workspace.resolve()))
            self.assertEqual(outer["binaries"], str(cfg.roles["binaries"]))
            self.assertTrue(value["verified"])
            self.assertTrue(install_locations.info(workroot, "VIC")["recorded"])
            ki_guard.require_intact(live)

    def test_existing_install_is_separate_from_the_writable_workspace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workroot = root / "geoforge"
            existing = root / "shared-software" / "bin" / "vic_classic"
            existing.parent.mkdir(parents=True)
            existing.write_text("binary")
            existing.chmod(0o555)

            install_locations.select_mode(
                workroot, "VIC", "existing", existing)
            info = install_locations.info(workroot, "VIC")

            self.assertEqual(info["installation_mode"], "existing")
            self.assertEqual(info["existing_path"], str(existing.resolve()))
            self.assertEqual(info["existing_kind"], "file")
            self.assertEqual(
                install_locations.resolve(workroot, "VIC"),
                install_locations.default_root(workroot, "VIC"),
            )

    def test_existing_install_binding_survives_verification_record_rewrite(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            workspace = root / "work"
            existing = root / "existing" / "model"
            existing.mkdir(parents=True)
            cfg = paths.KissConfig.default(workspace)
            install_locations.record(
                "Demo", workspace, cfg, installation_mode="existing",
                existing_path=existing)
            install_locations.record("Demo", workspace, cfg, verified=True)

            saved = json.loads(
                (workspace / install_locations.RECORD_FILE).read_text(encoding="utf-8"))
            self.assertEqual(saved["installation_mode"], "existing")
            self.assertEqual(saved["existing_path"], str(existing))
            self.assertTrue(saved["verified"])

    def test_gui_workdir_uses_the_saved_model_location(self):
        with tempfile.TemporaryDirectory() as td:
            workroot = Path(td) / "geoforge"
            target = Path(td) / "models-on-another-disk" / "CRHM"
            install_locations.select(workroot, "CRHM", target)
            handler = object.__new__(gui.Handler)
            handler.workroot = workroot

            self.assertEqual(
                gui.Handler._workdir(handler, SimpleNamespace(name="CRHM")),
                target.resolve(),
            )


class InstallStatusTests(unittest.TestCase):
    def test_python_env_uses_windows_venv_layout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = SimpleNamespace(
                roles={"python_env": root / "venv"},
                python="python",
            )

            def fake_run(argv, **_kwargs):
                if argv[1:3] == ["-m", "venv"]:
                    interpreter = root / "venv" / "Scripts" / "python.exe"
                    interpreter.parent.mkdir(parents=True)
                    interpreter.touch()
                return 0, "ok"

            with mock.patch.object(install.os, "name", "nt"), \
                 mock.patch.object(install, "_run", side_effect=fake_run):
                result = install.ensure_python_env(cfg, base_python="python")

            self.assertTrue(result.ok)
            self.assertEqual(cfg.python,
                             str(root / "venv" / "Scripts" / "python.exe"))

    def test_verified_preflight_is_injected_as_machine_evidence_for_chat(self):
        handler = object.__new__(gui.Handler)
        binary = "/shared/vic/binaries/cmf_v420_pkg/src/MAIN_cmf"
        handler._status_for = lambda _ki: {
            "can_run": True, "label": "Verified on this machine",
            "steps": [{"name": "preflight", "detail":
                       f"  OK    CaMa-Flood 4.20: {binary}\n"
                       "  Results: 2 passed, 0 failed"}],
        }
        cfg = SimpleNamespace(roles={"binaries": Path("/shared/vic/binaries")})

        block = handler._software_status_prompt(
            [SimpleNamespace(name="VIC")], cfg)

        self.assertIn("VERIFIED ON THIS MACHINE", block)
        self.assertIn(binary, block)
        self.assertIn("current machine evidence", block)

    def test_all_bundled_kis_have_an_agent_visibility_contract(self):
        models = Path(__file__).parents[2] / "models"
        manifests = Path(__file__).parents[1] / "manifests"
        with tempfile.TemporaryDirectory() as td:
            result = software_audit.audit(models, Path(td), manifests)

        self.assertEqual(result["catalogue_count"], 127)
        self.assertEqual(result["contract_checked"], 127)
        self.assertTrue(result["ok"], result["errors"])

    def test_verified_status_path_is_real_policy_and_cli_visible(self):
        models = Path(__file__).parents[2] / "models"
        manifests = Path(__file__).parents[1] / "manifests"
        with tempfile.TemporaryDirectory() as td:
            workroot = Path(td)
            workspace = workroot / "vic"
            binary = workspace / "binaries" / "cmf_v420_pkg" / "src" / "MAIN_cmf"
            binary.parent.mkdir(parents=True)
            binary.write_text("compiled model")
            cfg = paths.KissConfig.default(workspace)
            (workspace / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
            (workspace / "status.json").write_text(json.dumps({
                "model": "VIC", "ok": True,
                "steps": [{"name": "preflight", "ok": True,
                           "detail": f"  OK    CaMa-Flood 4.20: {binary}\n"}],
            }))

            result = software_audit.audit(models, workroot, manifests)

        self.assertTrue(result["ok"], result["errors"])
        vic = next(item for item in result["verified"] if item["model"] == "VIC")
        self.assertTrue(vic["paths"][0]["exists"])
        self.assertTrue(vic["paths"][0]["policy_visible"])
        self.assertTrue(vic["paths"][0]["cli_visible"])

    def test_preflight_path_parser_handles_colon_and_found_at_forms(self):
        status = {"steps": [{"name": "preflight", "detail":
                   "  OK    Maps: /tmp/model/maps (3 items)\n"
                   "[OK] binary found at /tmp/model/bin/run\n"
                   "  WARN  ignored: /tmp/missing"}]}
        self.assertEqual(
            software_audit.preflight_paths(status),
            [Path("/tmp/model/maps"), Path("/tmp/model/bin/run")],
        )

    def test_primary_cause_is_saved_and_preflight_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = root / "models" / "Demo"
            package.mkdir(parents=True)
            (package / "SKILL.md").write_text("# Demo installation fixture\n")
            (package / "preflight_check.py").write_text("print('PREFLIGHT_REPORT={}')\n")
            ki = KI("Demo", package)
            man = Manifest(
                model="Demo", acquire=Acquire(strategy="build", repo="https://invalid"),
            )
            emitted = []
            good = lambda name: install.Step(name, True, "ok")
            failed = install.Step("acquire[build]", False, "clone failed: no such tag")

            with mock.patch.object(gui.install, "ensure_python_env", return_value=good("python-env")), \
                 mock.patch.object(gui.install, "install_ki_tools_common", return_value=good("ki-tools-common")), \
                 mock.patch.object(gui.install, "check_system_deps", return_value=good("system-deps")), \
                 mock.patch.object(gui.install, "install_python_deps", return_value=good("python-deps")), \
                 mock.patch.object(gui.install, "acquire", return_value=(failed, None)), \
                 mock.patch.object(gui.install, "check_data", return_value=good("data")), \
                 mock.patch.object(gui.handoff, "write", return_value=[]):
                gui.run_install(ki, man, root / "work", emitted.append, root)

            status = json.loads((root / "work" / "status.json").read_text(encoding="utf-8"))
            self.assertEqual(status["primary_error"]["name"], "acquire[build]")
            self.assertIn("no such tag", status["primary_error"]["detail"])
            preflight = next(s for s in status["steps"] if s["name"] == "preflight")
            self.assertTrue(preflight["skipped"])
            self.assertIn("acquire[build]", preflight["detail"])


class AgentSetupTests(unittest.TestCase):
    def test_bundled_common_library_is_materialised_offline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "repo" / "ki_tools_common" / "ki_tools_common"
            source.mkdir(parents=True)
            (source / "__init__.py").write_text(
                "OUTPUTS = 'KISSPATH_OUTPUTS'\n")
            cfg = paths.KissConfig.default(root / "work")

            target = setup.prepare_common(cfg, root / "repo")

            installed = (target / "ki_tools_common" / "__init__.py").read_text(encoding="utf-8")
            # Replacements are embedded in Python source, so paths use forward
            # slashes even on Windows (native backslashes could become escapes).
            self.assertIn(cfg.roles["outputs"].as_posix(), installed)

    def test_agent_prepare_maps_legacy_ki_tools_before_first_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            package = root / "repo" / "models" / "Demo"
            (package / "tools").mkdir(parents=True)
            (package / "tools" / "prepare.py").write_text("print('ready')\n")
            (package / "preflight_check.py").write_text(
                'check_dir("KISSPATH_KI_ROOT/Demo/knowledge_infrastructure/tools", '
                '"KI tools directory")\n'
            )
            common = root / "repo" / "ki_tools_common" / "ki_tools_common"
            common.mkdir(parents=True)
            (common / "__init__.py").write_text("# bundled common tools\n")
            ki = KI("Demo", package)

            with mock.patch("kiss_cli.handoff.write_setup"):
                live, cfg = setup.prepare(
                    ki, SimpleNamespace(), root / "work", root / "repo",
                    root / "repo" / "models",
                )

            expected = (root / "work" / "models" / "Demo" /
                        "knowledge_infrastructure" / "tools")
            self.assertTrue(expected.is_symlink())
            self.assertEqual(expected.resolve(), (live.root / "tools").resolve())
            self.assertEqual(
                cfg.roles["ki_root"], (root / "work" / "models").resolve())

    def test_provider_network_failure_becomes_specific_user_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            made = setup.request_for_provider_connection(
                root, "kimi", "auth.kimi.com")
            shown = setup.request(root)

            self.assertEqual(made["kind"], "login")
            self.assertEqual(shown["title"], "Kimi Code cannot connect")
            self.assertIn("auth.kimi.com", shown["message"])
            self.assertIn("installation has not failed", shown["message"])
            self.assertIn("AI Settings", shown["message"])

    def test_shared_runner_is_noninteractive_and_kills_tree_on_timeout(self):
        process = mock.MagicMock(spec=subprocess.Popen)
        process.pid, process.returncode = 43210, None
        process.stdout = process.stderr = None
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["build"], 1),
            ("partial stdout", "partial stderr"),
        ]
        with mock.patch.object(execution.subprocess, "Popen", return_value=process) as popen,              mock.patch("kiss_cli.processes.terminate_process_tree") as terminate,              mock.patch.object(execution, "kill_tree") as posix_tree:
            run = execution.run_process(["build"], cwd=".", env={}, timeout=1)

        self.assertEqual(run.status, "timed_out")
        self.assertEqual(run.stdout, "partial stdout")
        if os.name == "nt":
            terminate.assert_called_once_with(process)
            self.assertIs(popen.call_args.kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(
                popen.call_args.kwargs["creationflags"],
                getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
        else:
            posix_tree.assert_called_once()
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

    @unittest.skipUnless(os.name == "nt", "Windows process trees")
    def test_windows_timeout_kills_the_pinned_snapshot_not_a_taskkill_walk(self):
        from kiss_cli import processes
        order = mock.Mock()
        process = SimpleNamespace(pid=54321, kill=order.kill)
        order.descendants.side_effect = [[(11, 1000)], [(12, 1001)]]
        with mock.patch.object(processes, "_windows_creation_time", return_value=777), \
             mock.patch.object(processes, "windows_descendants", order.descendants), \
             mock.patch.object(processes, "terminate_snapshot", order.terminate), \
             mock.patch.object(processes.subprocess, "run") as taskkill:
            processes.terminate_process_tree(process)

        # Snapshot, then our own handle, then whatever the root started meanwhile,
        # pinned to the root's creation time; taskkill never walks parent PIDs.
        self.assertEqual(order.mock_calls, [
            mock.call.descendants(54321, strict=True),
            mock.call.kill(),
            mock.call.descendants(54321, root_created=777),
            mock.call.terminate([(11, 1000), (12, 1001)]),
        ])
        taskkill.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows taskkill process trees")
    def test_windows_timeout_uses_taskkill_tree_force(self):
        # Only when no process snapshot can be taken at all.
        from kiss_cli import processes
        process = SimpleNamespace(pid=54321, kill=mock.Mock())
        completed = subprocess.CompletedProcess([], 0)
        with mock.patch.object(processes, "_windows_creation_time", return_value=None), \
             mock.patch.object(processes, "windows_descendants",
                               side_effect=OSError("no process table")), \
             mock.patch.object(
                processes.subprocess, "run", return_value=completed) as taskkill:
            processes.terminate_process_tree(process)

        command = taskkill.call_args.args[0]
        self.assertEqual(command[-4:], ["/PID", "54321", "/T", "/F"])
        self.assertIs(taskkill.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(taskkill.call_args.kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(taskkill.call_args.kwargs["stderr"], subprocess.DEVNULL)
        process.kill.assert_not_called()

    def test_api_setup_command_inherits_its_provider_proxy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = execution.ProcessRun(
                "succeeded", 0, stdout="git version test\n", stderr="")

            def routed(provider, env):
                self.assertEqual(provider, "api:deepseek")
                return {**env, "HTTPS_PROXY": "http://127.0.0.1:7897"}

            with mock.patch.object(
                    settings, "with_provider_proxy", side_effect=routed) as route, \
                 mock.patch.object(execution, "run_process", return_value=completed) as run:
                result = api.execute_tool(
                    "run_setup_command", {"argv": ["git", "--version"]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"provider_id": "api:deepseek"},
                )

            self.assertIn("git version test", result)
            self.assertEqual(route.call_count, 1)
            self.assertEqual(
                run.call_args.kwargs["env"]["HTTPS_PROXY"],
                "http://127.0.0.1:7897")

    def test_api_setup_can_inspect_a_user_selected_existing_install(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "work"
            ki_root = work / "ki"
            ki_root.mkdir(parents=True)
            existing = root / "external-install"
            existing.mkdir()
            binary = existing / "model"
            binary.write_text("binary")
            cfg = SimpleNamespace(
                root=work, python=sys.executable,
                roles={"binaries": work / "binaries"},
            )
            completed = execution.ProcessRun(
                "succeeded", 0, stdout="model: executable\n", stderr="")
            with mock.patch.object(execution, "run_process", return_value=completed):
                result = api.execute_tool(
                    "run_setup_command", {"argv": ["file", str(binary)]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"existing_roots": [str(existing)]},
                )
            self.assertIn("model: executable", result)

    def test_existing_install_task_forbids_reinstall_and_requires_real_preflight(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = setup.agent_task(
                SimpleNamespace(name="Demo"), SimpleNamespace(), root,
                installation_mode="existing",
                existing_paths=[str(root / "already-built")],
            )
            self.assertIn("Do not download, clone", task)
            self.assertIn("resolved_existing_path", task)
            self.assertIn("KI's real", task)

    def test_installation_only_task_forbids_scientific_runs(self):
        with tempfile.TemporaryDirectory() as td:
            task = setup.agent_task(
                SimpleNamespace(name="Demo"), SimpleNamespace(), Path(td),
                installation_only=True,
                manifest_hint="Use CPython 3.9 only; patch official source first.",
            )
            self.assertIn("installation-only stress test", task)
            self.assertIn("Do NOT run the KI preflight", task)
            self.assertIn("Do NOT download", task)
            self.assertIn("cheap startup probe", task)
            self.assertIn("Do not substitute a toy", task)
            self.assertIn("Never fabricate a compatibility distribution", task)
            self.assertIn("standard-library shadow module", task)
            self.assertIn("Do not create or overwrite GeoForge's", task)
            self.assertIn("installation-test.json", task)
            self.assertIn("workspace-local distribution", task)
            self.assertIn("Do not ask", task)
            self.assertIn("merely because a command is missing from PATH", task)
            self.assertIn("curl", task)
            self.assertIn("Python NuGet", task)
            self.assertIn("Do not bypass", task)
            self.assertIn("absence", task)
            self.assertIn("of a prebuilt Python wheel", task)
            self.assertIn("WinLibs", task)
            self.assertIn("7-Zip", task)
            self.assertIn("innoextract", task)
            self.assertIn("winflexbison", task)
            self.assertIn("netCDF-C", task)
            self.assertIn("not a permission question", task)
            self.assertIn("MANIFEST-SPECIFIC INSTALLATION ROUTE", task)
            self.assertIn("Use CPython 3.9 only", task)
            self.assertIn("Do not merely speculate", task)
            self.assertIn("compiler/linker failure", task)

    def test_installation_only_hides_and_blocks_scientific_tools(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            names = {
                tool["name"] for tool in api.tool_schemas(
                    SimpleNamespace(root=ki_root), setup_mode=True,
                    installation_only=True,
                )
            }
            self.assertNotIn("run_preflight", names)
            self.assertIn("run_builtin_setup", names)
            with self.assertRaisesRegex(api.ToolError, "installation-only setup"):
                api.execute_tool(
                    "run_preflight", {}, SimpleNamespace(root=ki_root), cfg,
                    setup_mode=True,
                    setup_context={"installation_only": True},
                )
    def test_installation_agent_receives_exact_final_import_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            preflight = root / "preflight_check.py"
            preflight.write_text(
                "def check_import(module, critical=True): pass\n"
                "check_import('simfire.sim.simulation')\n"
                "check_import('rasterio')\n",
                encoding="utf-8",
            )
            ki = SimpleNamespace(root=root, preflight=preflight)
            man = Manifest(
                model="SimFire", python_deps=["rasterio", "xarray"],
                acquire=Acquire(strategy="pip", package="simfire==2.0.1",
                                produces="simfire"),
            )
            contract = gui._installation_import_contract(ki, man)
            self.assertIn("simfire.sim.simulation", contract)
            self.assertIn("rasterio", contract)
            self.assertIn("xarray", contract)
            self.assertIn("one interpreter", contract)
            guidance = gui._installation_manifest_guidance(man)
            self.assertIn("strategy: pip", guidance)
            self.assertIn("simfire==2.0.1", guidance)
            self.assertIn("expected product: simfire", guidance)

    def test_topoflow_manifest_uses_pinned_official_source(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "TopoFlow.yaml")
        self.assertEqual(manifest.acquire.strategy, "pip")
        self.assertEqual(manifest.acquire.produces, "topoflow")
        self.assertIn("github.com/peckhams/topoflow36.git@", manifest.acquire.package)
        self.assertNotIn("@master", manifest.acquire.package)
        self.assertIn("cfunits", manifest.python_deps)

    def test_apex_manifest_does_not_require_wine_on_windows(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "APEX.yaml")
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertNotIn("wine", manifest.system_deps)
        self.assertEqual(manifest.reference_case, "APEX0806.exe")
        self.assertIn("Do not substitute", manifest.agent_hint)
        self.assertIn("APEX1501", manifest.agent_hint)
        self.assertIn("headless extraction", manifest.agent_hint)

    def test_alpine3d_manifest_deploys_official_windows_package(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "Alpine3D.yaml")
        self.assertEqual(manifest.acquire.strategy, "build")
        self.assertEqual(
            manifest.acquire.ref,
            "7188347dc69bcc7b99fad0e3f6523584b57b8414",
        )
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(
            manifest.acquire.produces,
            "source/repo/Source/alpine3d/bin/alpine3d.exe",
        )
        self.assertIn("300c211c79aee15", manifest.agent_hint)
        self.assertIn("NSIS installer", manifest.agent_hint)
        self.assertIn("7z2603-x64.exe", manifest.agent_hint)
        self.assertIn("binaries/Alpine3D/source/repo", manifest.agent_hint)
        self.assertIn("libmeteoio.dll", manifest.agent_hint)
        self.assertIn("must never be copied or renamed", manifest.agent_hint)

    def test_esmf_manifest_requires_native_core_and_esmpy(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "ESMF.yaml")
        self.assertEqual(manifest.acquire.strategy, "build")
        self.assertEqual(
            manifest.acquire.ref,
            "99356176e374c49273893bbb9564705915dba621",
        )
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(manifest.verified, "observed")
        self.assertEqual(
            manifest.acquire.produces,
            "env/Library/bin/ESMF_RegridWeightGen.exe",
        )
        self.assertIn("nompi_py311h597d70b_2", manifest.agent_hint)
        self.assertIn("nompi_h693c31f_5", manifest.agent_hint)
        self.assertIn("ESMFMKFILE", manifest.agent_hint)
        self.assertIn("esmpy.Manager", manifest.agent_hint)
        self.assertIn("never copy or rename Python", manifest.agent_hint)
        preflight = (Path(__file__).parents[2] / "models" / "ESMF" /
                     "preflight_check.py")
        ki = SimpleNamespace(preflight=preflight)
        self.assertEqual(
            runnable.declared_imports(ki),
            ["numpy", "netCDF4", "esmpy", "esmpy.api.esmpymanager"],
        )
        self.assertEqual(
            runnable.declared(ki),
            ["KISSPATH_BINARIES/ESMF/env/Library/bin/"
             "ESMF_RegridWeightGen.exe"],
        )
        contract = preflight.read_text(encoding="utf-8")
        self.assertIn("esmpy.Manager", contract)
        self.assertIn("esmpy.Grid", contract)
        self.assertIn("esmpy.Field", contract)

    def test_apex_execution_uses_native_binary_on_windows(self):
        path = (Path(__file__).parents[2] / "models" / "APEX" / "tools" /
                "s6_run_apex.py")
        spec = importlib.util.spec_from_file_location("apex_s6_runtime", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        binary = Path("C:/model/APEX0806.exe")
        self.assertEqual(module._runtime_command(binary, "nt"), [str(binary)])
        self.assertEqual(
            module._runtime_command(binary, "posix"),
            ["wine", "./APEX0806.exe"],
        )

    def test_ce_qual_w2_manifest_deploys_official_windows_binary(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "CE_QUAL_W2.yaml")
        self.assertEqual(manifest.acquire.strategy, "build")
        self.assertEqual(
            manifest.acquire.ref,
            "5544026e3f1a39c0c9e827bd3dc2bbc13a94636c",
        )
        self.assertEqual(manifest.acquire.produces, "bin/w2_v5")
        self.assertTrue(any(
            "executables/model/w2_v45_64.exe" in command
            for command in manifest.acquire.commands
        ))
        self.assertNotIn("gfortran", manifest.system_deps)

    def test_hype_manifest_downloads_observed_windows_release(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "HYPE.yaml")
        self.assertEqual(manifest.acquire.strategy, "download")
        self.assertEqual(manifest.verified, "observed")
        self.assertEqual(
            manifest.acquire.sha256,
            "f029ddd0ab9377eea1effb2ae1081c236b6c99950bba3b947f012fbd405a966b",
        )
        self.assertEqual(
            manifest.acquire.produces,
            "hype_5_35_0_exe/HYPE.exe",
        )
        self.assertIn("not a Git repository", manifest.agent_hint)

    def test_hexwatershed_manifest_stages_workspace_gdal(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "HexWatershed.yaml")
        self.assertEqual(
            manifest.acquire.ref,
            "e96ef94547b19d2a6d7949a6c735c7ed4750a6f2",
        )
        self.assertIn("micromamba", manifest.agent_hint)
        self.assertIn("mingw-w64-ucrt-x86_64-gdal", manifest.agent_hint)
        self.assertIn("mingw-w64-ucrt-x86_64-netcdf-cxx", manifest.agent_hint)
        self.assertIn("file(GET_RUNTIME_DEPENDENCIES)", manifest.agent_hint)
        self.assertIn("ABI-incompatible", manifest.agent_hint)
        self.assertIn("/share/apps/gdal/2.3.1", manifest.agent_hint)
        self.assertIn("changliao1025/hexwatershed", manifest.agent_hint)
        self.assertIn("pip check", manifest.agent_hint)
        self.assertIn("pyflowline", manifest.python_deps)

    def test_rhessys_manifest_pins_real_tag_and_windows_codegen(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "RHESSys.yaml")
        self.assertEqual(manifest.acquire.strategy, "build")
        self.assertEqual(
            manifest.acquire.ref,
            "91dccef178e5df33be2f8105f68e3cda819b7bb1",
        )
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(manifest.acquire.produces, "rhessys/rhessys7.4.exe")
        self.assertIn("winflexbison", manifest.agent_hint)
        self.assertIn("mingw32-make.exe", manifest.agent_hint)
        self.assertIn("start_line/line_count", manifest.agent_hint)
        self.assertIn("classic-only", manifest.agent_hint)
        self.assertIn("13.3.0", manifest.agent_hint)
        self.assertIn("dynamic_field_lookup.py", manifest.agent_hint)
        self.assertIn("typedef short bool", manifest.agent_hint)
        self.assertIn("gendef.exe", manifest.agent_hint)
        self.assertIn("dlltool.exe", manifest.agent_hint)
        self.assertIn("-o rhessys7.4.exe", manifest.agent_hint)

    def test_simfire_manifest_uses_pinned_official_source(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "SimFire.yaml")
        self.assertEqual(manifest.binary_type, "Python")
        self.assertEqual(manifest.acquire.strategy, "pip")
        self.assertIn(
            "github.com/mitrefireline/simfire.git@5d76a16de45e7058e5080f2cf4c5b5b2f9f1d0ae",
            manifest.acquire.package,
        )
        self.assertIn("CPython 3.9", manifest.agent_hint)
        self.assertIn("gcc.exe", manifest.agent_hint)
        self.assertIn("rasterio", manifest.python_deps)
        self.assertIn("xarray", manifest.python_deps)
        self.assertIn("do not rewrite or shim", manifest.agent_hint)
        self.assertIn("contextlib.nullcontext", manifest.agent_hint)

    def test_summa_manifest_pins_file_manager_v3_source(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "SUMMA.yaml")
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(
            manifest.acquire.ref,
            "2213bc57358e6709b48217cfce64f96a4b90b287",
        )
        self.assertEqual(manifest.acquire.produces, "bin/summa.exe")
        self.assertIn("netCDF-Fortran", manifest.agent_hint)
        self.assertIn("F_MASTER", manifest.agent_hint)
        self.assertIn("libnetcdf.dll.a", manifest.agent_hint)

    def test_rapid_manifest_pins_portable_msys2_petsc_route(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "RAPID.yaml")
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(
            manifest.acquire.ref,
            "83145101ac8b49b8269e330cfc1372876fce8d7d",
        )
        self.assertEqual(manifest.acquire.produces, "src/rapid.exe")
        self.assertIn("a2d047e8ee213c3c6a49a8de427eb1069df12207c0422ff1b3cbb5c905c34221",
                      manifest.agent_hint)
        self.assertIn("746207a3cb30cd796a872832cd0f2ba14a6b454b",
                      manifest.agent_hint)
        self.assertIn("petsc-3.13.6.tar.gz", manifest.agent_hint)
        self.assertIn("02ca534a14c800a96f139f54530ac048b1727eb6703975920953bcb502771b1c",
                      manifest.agent_hint)
        self.assertIn("Do not pass any `--with-petsc4py`", manifest.agent_hint)
        self.assertIn("`diffutils`", manifest.agent_hint)
        self.assertIn("--with-mpi=0", manifest.agent_hint)
        self.assertIn("`bash -c`", manifest.agent_hint)
        self.assertIn("never use the GUI installer", manifest.agent_hint)

    def test_lisflood_manifest_uses_bounded_micromamba_runtime(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "LISFLOOD.yaml")
        self.assertEqual(manifest.acquire.package, "lisflood-model==5.0.0")
        self.assertEqual(manifest.acquire.produces, "lisflood")
        self.assertIn("Python 3.11", manifest.agent_hint)
        self.assertIn("--root-prefix", manifest.agent_hint)
        self.assertIn("--prefix", manifest.agent_hint)
        self.assertIn("do not use `micromamba run`", manifest.agent_hint)

    def test_swap_manifest_uses_official_hashed_windows_release(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "SWAP.yaml")
        self.assertEqual(manifest.acquire.strategy, "download")
        self.assertEqual(manifest.acquire.produces, "swap.exe")
        self.assertEqual(
            manifest.acquire.sha256,
            "55a0de22beb0dfedf9d0bca64a7a6ac816ccef02237b2ce9f94c3e750127b257",
        )
        self.assertIn("v4.2.0", manifest.acquire.url)
        self.assertNotIn("gfortran", manifest.system_deps)

    def test_swat_plus_manifest_pins_observed_windows_build(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "SWAT_Plus.yaml")
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(
            manifest.acquire.ref,
            "cb442f7c05fc3bfc34349c446010f452d2737ca0",
        )
        self.assertEqual(manifest.acquire.produces, "swatplus.exe")
        self.assertTrue(any("swatplus-62.0.0" in command
                            for command in manifest.acquire.commands))
        self.assertIn("revision 59.3", manifest.notes)

    def test_direct_download_can_use_stable_manifest_filename(self):
        with tempfile.TemporaryDirectory() as td:
            prefix = Path(td)
            acquire = Acquire(
                strategy="download",
                url="https://example.invalid/model-v1.exe",
                produces="model.exe",
            )
            manifest = SimpleNamespace(acquire=acquire)
            opener = mock.Mock()
            opener.open.return_value = io.BytesIO(b"MZ-real-release")
            with mock.patch.object(
                    install.urllib.request, "build_opener", return_value=opener):
                step, binary = install._acq_download(
                    manifest, prefix, sys.executable)
            self.assertTrue(step.ok)
            self.assertEqual(binary, prefix / "model.exe")
            self.assertEqual(binary.read_bytes(), b"MZ-real-release")

    def test_julia_probe_uses_workspace_runtime_project_and_depot(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            binaries = root / "binaries"
            julia = binaries / "julia-1.10.7" / "bin" / "julia.exe"
            julia.parent.mkdir(parents=True)
            julia.write_bytes(b"MZ")
            (binaries / "julia_depot").mkdir()
            project = root / "ki" / "julia"
            project.mkdir(parents=True)
            (project / "Project.toml").write_text(
                '[deps]\nWflow = "d48b7d99-76e7-47ae-b1d5-ff0c1cf9a818"\n',
                encoding="utf-8",
            )
            cfg = SimpleNamespace(root=root, roles={"binaries": binaries})
            system_julia = root / "system-julia.exe"
            system_julia.write_bytes(b"MZ")
            completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
            with mock.patch.object(runnable.shutil, "which", return_value=str(system_julia)), \
                    mock.patch.object(runnable.subprocess, "run", return_value=completed) as run:
                ok, detail = runnable._probe_julia_project(
                    SimpleNamespace(root=root / "ki"), cfg, 25)
            self.assertTrue(ok)
            self.assertIn("Wflow", detail)
            argv = run.call_args.args[0]
            self.assertTrue(os.path.samefile(argv[0], julia))
            self.assertEqual(argv[1], f"--project={project}")
            self.assertEqual(argv[-1], "using Wflow")
            self.assertEqual(
                run.call_args.kwargs["env"]["JULIA_DEPOT_PATH"],
                str(binaries / "julia_depot"),
            )

    def test_julia_runtime_uses_path_only_without_a_managed_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            system_julia = root / "system-julia.exe"
            system_julia.write_bytes(b"MZ")
            cfg = SimpleNamespace(root=root, roles={"binaries": root / "missing-binaries"})
            for workspace in (cfg, None):
                with self.subTest(workspace=workspace), \
                        mock.patch.object(runnable.shutil, "which", return_value=str(system_julia)) as which:
                    selected = runnable._managed_julia(workspace)
                    self.assertTrue(os.path.samefile(selected, system_julia))
                    which.assert_called_once_with("julia")
                with self.subTest(workspace=workspace, system_missing=True), \
                        mock.patch.object(runnable.shutil, "which", return_value=None):
                    self.assertIsNone(runnable._managed_julia(workspace))

    def test_failed_managed_julia_probe_does_not_switch_to_system_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            binaries = root / "custom-runtimes"
            julia = binaries / "julia" / "bin" / "julia.exe"
            julia.parent.mkdir(parents=True)
            julia.write_bytes(b"MZ")
            project = root / "ki" / "julia"
            project.mkdir(parents=True)
            (project / "Project.toml").write_text("[deps]\n", encoding="utf-8")
            cfg = SimpleNamespace(root=root, roles={"binaries": binaries})
            failed = subprocess.CompletedProcess([], 1, stdout="", stderr="managed runtime dependency failure")
            with mock.patch.object(runnable.shutil, "which", return_value=str(root / "system-julia.exe")), \
                    mock.patch.object(runnable.subprocess, "run", return_value=failed) as run:
                ok, detail = runnable._probe_julia_project(SimpleNamespace(root=root / "ki"), cfg, 25)
            self.assertFalse(ok)
            self.assertIn("managed runtime dependency failure", detail)
            self.assertEqual(run.call_count, 1)
            self.assertTrue(os.path.samefile(run.call_args.args[0][0], julia))

    def test_numbered_workspace_venv_is_a_python_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            python = root / "venv39" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"MZ")
            cfg = SimpleNamespace(
                root=root,
                roles={"binaries": root / "binaries",
                       "python_env": root / "venv"},
            )
            candidates = runnable._python_candidates(cfg, sys.executable)
            self.assertTrue(any(os.path.samefile(item, python)
                                for item in candidates))

    def test_python_candidates_reload_agent_recorded_workspace_interpreter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            model_python = root / "private-python" / "python.exe"
            model_python.parent.mkdir()
            model_python.write_bytes(b"MZ")
            (root / "kiss.toml").write_text(
                "[kiss]\n"
                f"root = {json.dumps(str(root))}\n"
                "python = \"private-python/python.exe\"\n",
                encoding="utf-8",
            )
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries",
                       "python_env": root / "venv"},
            )
            candidates = runnable._python_candidates(cfg, sys.executable)
            self.assertTrue(os.path.samefile(candidates[0], model_python))

    def test_agent_final_preflight_becomes_the_saved_verification_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            live = root / "ki"
            live.mkdir()
            (live / "SKILL.md").write_text("# Demo setup fixture\n")
            ki = KI("Demo", live)
            from kiss_cli import ki_guard, ki_verification
            ki_guard.enroll(live)
            cfg = paths.KissConfig.default(root)
            cfg.python = sys.executable
            check = SimpleNamespace(
                ok=True, detail="1 passed, 0 failed", commands=["check Demo"])
            with mock.patch.object(install, "run_preflight", return_value=check), \
                 mock.patch.object(setup, "clear_request"):
                ok = gui.Handler._record_agent_preflight(
                    None, ki, ki, cfg,
                    root, lambda _piece: True,
                )
            status = json.loads((root / "status.json").read_text(encoding="utf-8"))
            self.assertTrue(ok)
            self.assertTrue(status["ok"])
            self.assertTrue(status["agent_setup"])
            self.assertIsNotNone(status["verified_at"])
            self.assertEqual(status["steps"][-1]["name"], "preflight")
            self.assertEqual(status["ki_content_digest"], ki_verification.content_digest(live))
            ki_guard.require_intact(live)

    def test_wrf_hydro_manifest_uses_real_release_and_separates_project_data(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "WRF_Hydro.yaml")
        self.assertEqual(manifest.acquire.ref, "v5.2.0")
        self.assertEqual(manifest.install_dir, "wrf_hydro/source")
        self.assertIn(
            "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            manifest.acquire.commands[0],
        )
        self.assertIn("mpif90", manifest.system_deps)
        self.assertIn("nf-config", manifest.system_deps)
        self.assertEqual(manifest.data, [])
        preflight = (Path(__file__).parents[2] / "models" / "WRF_Hydro" /
                    "preflight_check.py").read_text(encoding="utf-8")
        self.assertNotIn('check_dir("KISSPATH_FORCING"', preflight)

    def test_windows_release_manifests_do_not_require_source_toolchains(self):
        manifest_dir = Path(__file__).parents[1] / "manifests"
        cell2fire = Manifest.load(manifest_dir / "Cell2Fire.yaml")
        daisy = Manifest.load(manifest_dir / "Daisy.yaml")

        self.assertEqual(cell2fire.acquire.strategy, "download")
        self.assertEqual(cell2fire.system_deps, [])
        self.assertTrue(cell2fire.acquire.url.endswith(
            "Cell2FireW_v1.0.1-Windows-x86_64-binary.zip"))
        self.assertEqual(daisy.acquire.strategy, "download")
        self.assertEqual(daisy.system_deps, [])
        self.assertEqual(
            daisy.acquire.sha256,
            "d2bdf99b907cda45f118e9719e5aa7597bc42bfa9352db05fd0a3d0afbdf3473",
        )
        self.assertTrue(daisy.acquire.produces.endswith("daisy-bin.exe"))

    def test_caesar_windows_recipe_builds_the_declared_executable(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" /
            "CAESAR_Lisflood.yaml")

        self.assertEqual(manifest.acquire.strategy, "build")
        self.assertEqual(manifest.acquire.ref, "v1.0")
        self.assertEqual(manifest.acquire.produces, "bin/HAIL-CAESAR.exe")
        self.assertIn("g++", manifest.acquire.commands[0])
        self.assertIn("-DM_PI=", manifest.acquire.commands[0])
        self.assertNotIn("-fopenmp", manifest.acquire.commands[0])

    def test_missing_mac_build_libraries_become_a_human_request(self):
        software = {"steps": [{
            "name": "system-deps", "ok": False, "skipped": False,
            "detail": "not on PATH: mpif90, mpicc, nc-config, nf-config — install them",
        }]}
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(setup.sys, "platform", "darwin"), \
             mock.patch.object(setup.shutil, "which", return_value="/opt/homebrew/bin/brew"):
            req = setup.request_for_system_dependencies(Path(td), software)
            self.assertEqual(req["status"], "waiting")
            self.assertEqual(req["kind"], "permission")
            self.assertEqual(
                req["command"], "brew install mpich netcdf netcdf-fortran")

    def test_kimi_denied_folder_becomes_a_two_choice_popup_request(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            denied = Path.home() / "Documents" / "external-research-data"
            req = setup.request_for_kimi_permission(root, str(denied))
            self.assertIsNotNone(req)
            self.assertEqual(req["kind"], "permission")
            self.assertEqual(req["expected_path"], str(denied.resolve()))
            self.assertEqual(
                [item["id"] for item in req["options"]],
                ["allow-kimi-read-once", "allow-kimi-read-project"],
            )
            saved = setup.request(root)
            self.assertEqual(saved["title"], "Kimi needs access to one folder")
            self.assertFalse(saved["allow_note"])

    def test_kimi_shared_skill_folder_never_becomes_a_popup_request(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skills = Path.home() / ".agents" / "skills"
            self.assertIsNone(
                setup.request_for_kimi_permission(root, str(skills)))
            self.assertFalse((root / setup.REQUEST_FILE).exists())

    def test_old_kimi_shared_skill_popup_is_archived_on_read(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            skills = Path.home() / ".agents" / "skills"
            setup.request_user(root, {
                "kind": "permission",
                "title": "Kimi needs access to one folder",
                "expected_path": str(skills),
                "options": ["Allow once"],
            })

            self.assertIsNone(setup.request(root))
            self.assertFalse((root / setup.REQUEST_FILE).exists())
            self.assertEqual(len(list(root.glob("setup-request-*.json"))), 1)

    def test_kimi_permission_never_offers_the_entire_home_folder(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(
                setup.request_for_kimi_permission(Path(td), str(Path.home())))

    def test_failed_agent_turn_is_visible_even_without_structured_request(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / setup.LOG_FILE).write_text("agent output\nLoad failed\n")
            state = setup.setup_state(root, {
                "state": "failed", "can_run": False,
                "primary_error": {"name": "preflight", "detail": "binary missing"},
            })
            self.assertEqual(state["attention"]["title"], "Agent connection stopped")

    def test_dssat_manifest_pins_observed_windows_build(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "DSSAT.yaml")
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(
            manifest.acquire.ref,
            "40793f8d654ca033d027ec3a6cea53cf2f546602",
        )
        self.assertEqual(manifest.acquire.produces,
                         "build/bin/dscsm048.exe")
        self.assertEqual(manifest.acquire.commands[0],
                         "cmake -S . -B build -DCMAKE_BUILD_TYPE=RELEASE")
        self.assertNotIn("python3 -c", "\n".join(manifest.acquire.commands))
        self.assertIn("WinLibs", manifest.agent_hint)

    def test_trigrs_manifest_uses_current_public_usgs_archive(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "TRIGRS.yaml")
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(
            manifest.acquire.repo,
            "https://code.usgs.gov/usgs/landslides-trigrs.git",
        )
        self.assertEqual(
            manifest.acquire.ref,
            "969c409f7bc63e7616ebe34dfd5f6afd967f2d2d",
        )
        self.assertEqual(manifest.acquire.produces,
                         "src/TRIGRS/trg.exe")
        command = "\n".join(manifest.acquire.commands)
        self.assertIn("mingw32-make.exe", command)
        self.assertIn("MPIF90=gfortran", command)
        self.assertIn("CCFLAGS=-lm", command)
        self.assertIn("GIT_TERMINAL_PROMPT=0", manifest.agent_hint)
        self.assertIn("Do not use the obsolete", manifest.agent_hint)
        self.assertIn("WinLibs", manifest.agent_hint)
        self.assertIn("binaries/TRIGRS/src/TRIGRS/trg.exe",
                      manifest.agent_hint)
        self.assertIn("libgfortran-5.dll", manifest.agent_hint)

    def test_telemac_manifest_builds_real_serial_windows_core(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" /
            "TELEMAC_MASCARET.yaml")
        self.assertEqual(manifest.binary_type, "PE32")
        self.assertEqual(
            manifest.acquire.repo,
            "https://gitlab.pam-retd.fr/otm/telemac-mascaret.git",
        )
        self.assertEqual(
            manifest.acquire.ref,
            "a040e817390e787c5395be95663381ae85a4c0e3",
        )
        self.assertEqual(manifest.acquire.produces,
                         "b/bin/telemac2d.exe")
        self.assertNotIn("git-lfs", manifest.system_deps)
        self.assertNotIn("mpi", manifest.system_deps)
        self.assertNotIn("metis", manifest.system_deps)
        hint = manifest.agent_hint
        self.assertIn("GIT_LFS_SKIP_SMUDGE=1", hint)
        self.assertIn("homere_telemac2d", hint)
        self.assertIn("target_link_libraries(parallel PUBLIC special)", hint)
        self.assertIn("2D VERSION 9.1 FORTRAN 2003", hint)
        self.assertEqual(manifest.startup_marker,
                         "2D VERSION 9.1 FORTRAN 2003")
        self.assertIn("pip check", hint)
        self.assertIn("binaries/TELEMAC_MASCARET/b/bin/telemac2d.exe", hint)

    def test_human_request_can_receive_a_file_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            waiting = setup.request_user(root, {
                "kind": "download", "title": "Download the licensed model",
                "message": "Use the official portal.", "url": "https://example.com/model",
                "expected_path": "model.zip", "resume_hint": "unpack and retry",
                "options": [
                    {"id": "official", "label": "Use official download",
                     "description": "Requires my licence"},
                    "Provide an existing local file",
                    {"label": ""},
                ],
            })
            self.assertEqual(waiting["status"], "waiting")
            self.assertEqual(len(waiting["options"]), 2)
            self.assertEqual(waiting["options"][1]["id"], "option-2")
            self.assertTrue(waiting["id"])
            supplied = setup.save_upload(root, "model package.zip", b"payload")
            self.assertEqual(supplied.name, "model_package.zip")
            ready = setup.resume(root, "Downloaded under my account")
            self.assertEqual(ready["status"], "ready")
            state = setup.setup_state(root, {"state": "setup", "can_run": False})
            self.assertEqual(state["request"]["status"], "ready")
            self.assertEqual(state["uploads"][0]["name"], "model_package.zip")

    def test_api_setup_tools_are_only_exposed_in_setup_mode(self):
        normal = {t["name"] for t in api.tool_schemas(SimpleNamespace(), setup_mode=False)}
        guided = {t["name"] for t in api.tool_schemas(SimpleNamespace(), setup_mode=True)}
        project = {t["name"] for t in api.tool_schemas(
            SimpleNamespace(), setup_mode=False, project_mode=True)}
        combined_tools = api.tool_schemas(
            SimpleNamespace(), setup_mode=True, project_mode=True)
        combined = {t["name"] for t in combined_tools}
        self.assertNotIn("run_setup_command", normal)
        self.assertNotIn("run_ki_tool", normal)
        self.assertIn("run_setup_command", guided)
        self.assertIn("request_user_action", guided)
        self.assertIn("run_ki_tool", project)
        self.assertIn("create_project_plot", project)
        self.assertIn("publish_project_view", project)
        self.assertNotIn("create_project_plot", normal)
        self.assertNotIn("publish_project_view", normal)
        self.assertIn("write_project_file", project)
        self.assertIn("report_project_progress", guided)
        self.assertIn("report_project_progress", project)
        self.assertIn("run_setup_command", combined)
        self.assertIn("run_ki_tool", combined)
        self.assertIn("write_project_file", combined)
        self.assertIn("publish_setup_output", combined)
        self.assertEqual(
            [tool["name"] for tool in combined_tools].count("request_user_action"),
            1,
        )
        choice_tool = next(tool for tool in combined_tools
                           if tool["name"] == "request_user_action")
        self.assertIn("options", choice_tool["input_schema"]["properties"])
        run_tool = next(tool for tool in combined_tools if tool["name"] == "run_ki_tool")
        description = run_tool["input_schema"]["properties"]["tool_path"]["description"]
        self.assertIn("Python tool path relative to the KI root", description)
        self.assertIn("An absolute Python path stored in an approved plan is not the API", description)
        self.assertIn("Only a model binary declared by the KI may use an absolute path", description)
        self.assertIn("tools/", description)

    def test_api_install_turn_keeps_setup_and_project_roots_separate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup_root = root / "setup"
            project = root / "project"
            ki_root = setup_root / "ki"
            tools = ki_root / "tools"
            tools.mkdir(parents=True)
            project.mkdir()
            script = tools / "prepare.py"
            script.write_text(
                "from pathlib import Path\n"
                "Path('outputs/from-ki.txt').parent.mkdir(parents=True, exist_ok=True)\n"
                "Path('outputs/from-ki.txt').write_text('project-output')\n"
            )
            setup_probe = setup_root / "probe.py"
            setup_probe.write_text("print('setup-output')\n")
            cfg = SimpleNamespace(
                root=setup_root, python=sys.executable,
                roles={"binaries": setup_root / "binaries"},
            )
            ki = SimpleNamespace(root=ki_root)
            context = {"project_root": project}

            setup_output = api.execute_tool(
                "run_setup_command", {"argv": [sys.executable, "probe.py"]},
                ki, cfg, setup_mode=True, project_mode=True,
                setup_context=context,
            )
            project_output = api.execute_tool(
                "run_ki_tool", {"tool_path": "tools/prepare.py"},
                ki, cfg, setup_mode=True, project_mode=True,
                setup_context=context,
            )
            wrote = api.execute_tool(
                "write_project_file",
                {"path": "runs/state.json", "content": '{"ok":true}'},
                ki, cfg, setup_mode=True, project_mode=True,
                setup_context=context,
            )

            self.assertIn("setup-output", setup_output)
            self.assertIn("exit_code=0", project_output)
            self.assertIn("runs/state.json", wrote)
            self.assertEqual(
                (project / "outputs" / "from-ki.txt").read_text(),
                "project-output",
            )
            self.assertFalse((setup_root / "outputs" / "from-ki.txt").exists())

    def test_api_install_turn_can_publish_full_setup_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup_root = root / "setup"
            project = root / "project"
            source = setup_root / "outputs" / "case"
            source.mkdir(parents=True)
            project.mkdir()
            (source / "Summary.OUT").write_text("real summary")
            (source / "PlantGro.OUT").write_bytes(b"growth\x00output")
            ki_root = setup_root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=setup_root, python=sys.executable,
                roles={"binaries": setup_root / "binaries"},
            )
            result = api.execute_tool(
                "publish_setup_output",
                {"source": "outputs/case",
                 "destination": "outputs/case/verified-run"},
                SimpleNamespace(root=ki_root), cfg,
                setup_mode=True, project_mode=True,
                setup_context={"project_root": project},
            )
            self.assertIn("2 files", result)
            self.assertEqual(
                (project / "outputs" / "case" / "verified-run" /
                 "Summary.OUT").read_text(),
                "real summary",
            )
            self.assertEqual(
                (project / "outputs" / "case" / "verified-run" /
                 "PlantGro.OUT").read_bytes(),
                b"growth\x00output",
            )

    def test_api_publish_dereferences_only_internal_workspace_links(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            setup_root = root / "setup"
            project = root / "project"
            source = setup_root / "outputs" / "case"
            shared = setup_root / "model" / "Data"
            source.mkdir(parents=True)
            shared.mkdir(parents=True)
            project.mkdir()
            (shared / "MODEL.ERR").write_text("shared model table")
            try:
                (source / "MODEL.ERR").symlink_to(shared / "MODEL.ERR")
            except OSError as e:  # Windows may require Developer Mode.
                self.skipTest(f"symbolic links unavailable: {e}")
            ki_root = setup_root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=setup_root, python=sys.executable,
                roles={"binaries": setup_root / "binaries"},
            )
            context = {"project_root": project}
            result = api.execute_tool(
                "publish_setup_output",
                {"source": "outputs/case", "destination": "outputs/case"},
                SimpleNamespace(root=ki_root), cfg,
                setup_mode=True, project_mode=True, setup_context=context,
            )
            published = project / "outputs" / "case" / "MODEL.ERR"
            self.assertIn("1 internal links copied as files", result)
            self.assertEqual(published.read_text(), "shared model table")
            self.assertFalse(published.is_symlink())

            outside = root / "outside.txt"
            outside.write_text("not part of setup")
            escaping = setup_root / "outputs" / "escape"
            escaping.mkdir()
            (escaping / "outside.txt").symlink_to(outside)
            with self.assertRaisesRegex(api.ToolError, "escapes the setup workspace"):
                api.execute_tool(
                    "publish_setup_output",
                    {"source": "outputs/escape",
                     "destination": "outputs/escape"},
                    SimpleNamespace(root=ki_root), cfg,
                    setup_mode=True, project_mode=True, setup_context=context,
                )

    def test_api_project_agent_can_prepare_files_with_shipped_ki_tools(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            ki_root = project / "models" / "Demo" / "ki"
            tools = ki_root / "tools"
            tools.mkdir(parents=True)
            (project / "inputs").mkdir(parents=True)
            script = tools / "prepare.py"
            common = root / "common"
            binaries = root / "shared-binaries"
            binaries.mkdir()
            model_binary = binaries / "demo-model"
            model_binary.write_text("verified-shared-model")
            package = common / "ki_tools_common"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("SOURCE = 'bundled-common'\n")
            script.write_text(
                "import sys\n"
                "from pathlib import Path\n"
                "import ki_tools_common\n"
                "print('prepared-by-' + ki_tools_common.SOURCE)\n"
                "if len(sys.argv) > 1:\n"
                "    print('model=' + Path(sys.argv[1]).read_text())\n")
            cfg = paths.KissConfig.default(project)
            cfg.python = sys.executable
            cfg.roles.update(ki_tools_common=common, binaries=binaries)
            (ki_root.parent / paths.CONFIG_NAME).write_text(cfg.dumps(), encoding="utf-8")
            ki = SimpleNamespace(name="Demo", root=ki_root)

            wrote = api.execute_tool(
                "write_project_file",
                {"path": "runs/preparation.json", "content": '{"status":"started"}'},
                ki, cfg, project_mode=True,
            )
            calibration_case = api.execute_tool(
                "write_project_file",
                {"path": "calibration/cases/observed.csv",
                 "content": "date,value\n2000-01-01,1\n"},
                ki, cfg, project_mode=True,
            )
            output = api.execute_tool(
                "run_ki_tool", {
                    "tool_path": "tools/prepare.py",
                    "arguments": [str(model_binary)],
                },
                ki, cfg, project_mode=True,
            )
            plotted = api.execute_tool(
                "create_project_plot", {
                    "output_path": "artifacts/quick.svg", "kind": "bar",
                    "title": "Yield", "series": [{"name": "DSSAT", "y": [8338]}],
                }, ki, cfg, project_mode=True,
            )
            published = api.execute_tool(
                "publish_project_view", {
                    "title": "Demo results", "kis": ["Demo"],
                    "panels": [{"kind": "image", "title": "Yield",
                                "path": "artifacts/quick.svg"}],
                }, ki, cfg, project_mode=True,
            )
            progress = api.execute_tool(
                "report_project_progress",
                {"stage": "preparing", "status": "working",
                 "summary": "Preparing inputs", "selected_kis": ["Demo"]},
                ki, cfg, project_mode=True,
            )
            waiting = api.execute_tool(
                "request_user_action",
                {"kind": "choice", "title": "Choose crop",
                 "message": "Which crop should this scenario use?"},
                ki, cfg, project_mode=True,
            )

            self.assertIn("runs/preparation.json", wrote)
            self.assertIn("calibration/cases/observed.csv", calibration_case)
            self.assertIn("prepared-by-bundled-common", output)
            self.assertIn("model=verified-shared-model", output)
            self.assertIn("artifacts/quick.svg", plotted)
            self.assertIn("Project View published", published)
            self.assertTrue((project / "artifacts" / "quick.svg").is_file())
            self.assertTrue((project / "artifacts" / "project-view.json").is_file())
            self.assertIn("Preparing inputs", progress)
            self.assertIn("Choose crop", waiting)
            self.assertTrue((project / setup.REQUEST_FILE).is_file())
            with self.assertRaises(api.ToolError):
                api.execute_tool(
                    "write_project_file",
                    {"path": "session.json", "content": "tamper"},
                    ki, cfg, project_mode=True,
                )
            with self.assertRaises(api.ToolError):
                api.execute_tool(
                    "run_ki_tool", {"tool_path": "SKILL.md"},
                    ki, cfg, project_mode=True,
                )
            outside = root / "not-a-managed-binary.txt"
            outside.write_text("private")
            with self.assertRaisesRegex(api.ToolError, "path escapes"):
                api.execute_tool(
                    "run_ki_tool", {
                        "tool_path": "tools/prepare.py",
                        "arguments": [str(outside)],
                    },
                    ki, cfg, project_mode=True,
                )

    def test_api_setup_command_is_non_shell_and_workspace_scoped(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            ki = SimpleNamespace(root=ki_root)
            script = root / "probe.py"
            script.write_text("print('agent-ok')\n")
            output = api.execute_tool(
                "run_setup_command",
                {"argv": [sys.executable, "probe.py"]},
                ki, cfg, setup_mode=True,
            )
            self.assertIn("exit_code=0", output)
            self.assertIn("agent-ok", output)
            with self.assertRaises(api.ToolError):
                api.execute_tool(
                    "run_setup_command", {"argv": ["sh", "-c", "echo unsafe"]},
                    ki, cfg, setup_mode=True,
                )
            with self.assertRaises(api.ToolError):
                api.execute_tool(
                    "run_setup_command", {"argv": ["ls", "/private"]},
                    ki, cfg, setup_mode=True,
                )
            with self.assertRaises(api.ToolError):
                api.execute_tool(
                    "run_setup_command", {"argv": [sys.executable, "-c", "print(1)"]},
                    ki, cfg, setup_mode=True,
                )

    def test_setup_file_listing_survives_a_disappearing_directory(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def interrupted_walk(base, **kwargs):
                yield str(Path(base) / "nested"), [], ["kept.txt"]
                kwargs["onerror"](FileNotFoundError("build directory vanished"))

            with mock.patch.object(api.os, "walk", side_effect=interrupted_walk):
                files = api._safe_relative_file_listing(root, root, 800)
            self.assertEqual(files, ["nested/kept.txt"])

    def test_setup_text_reader_pages_large_build_files(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "makefile"
            path.write_text(
                "".join(f"line-{number}\n" for number in range(1, 1501)),
                encoding="utf-8",
            )
            self.assertEqual(
                api._read_text_page(path, start_line=1085, line_count=3),
                "line-1085\nline-1086\nline-1087\n",
            )
            with self.assertRaisesRegex(api.ToolError, "line_count"):
                api._read_text_page(path, start_line=1, line_count=2001)

    @unittest.skipUnless(os.name == "nt", "Windows path spelling")
    def test_setup_command_accepts_workspace_relative_windows_executable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            tool = root / "binaries" / "tools" / "python.exe"
            tool.parent.mkdir(parents=True)
            tool.write_bytes(b"MZ")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                [str(tool), "-m", "venv", "venv39"], 0,
                stdout="created", stderr="",
            )
            with mock.patch.object(execution, "run_process", return_value=_process_run(completed)) as run:
                output = api.execute_tool(
                    "run_setup_command", {
                        "argv": ["binaries\\tools\\python.exe", "-m", "venv", "venv39"],
                    },
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("exit_code=0", output)
            self.assertTrue(os.path.samefile(run.call_args.args[0][0], tool))

    def test_setup_command_allows_only_workspace_path_prefixes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            tool_bin = root / "binaries" / "toolchain" / "bin"
            ki_root.mkdir()
            tool_bin.mkdir(parents=True)
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                ["git", "--version"], 0, stdout="ok", stderr="")
            with mock.patch.object(execution, "run_process", return_value=_process_run(completed)) as run:
                output = api.execute_tool(
                    "run_setup_command", {
                        "argv": ["git", "--version"],
                        "env": {"PATH": str(tool_bin)},
                    },
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                )
            self.assertIn("exit_code=0", output)
            first = run.call_args.kwargs["env"]["PATH"].split(os.pathsep)[0]
            self.assertTrue(os.path.samefile(first, tool_bin))
            with self.assertRaisesRegex(api.ToolError, "PATH entry escapes"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": ["git", "--version"],
                        "env": {"PATH": str(root.parent)},
                    },
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                )

    def test_installation_only_tool_boundary_blocks_model_runs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            model = root / "binaries" / "DART" / "filter"
            model.parent.mkdir(parents=True)
            model.write_text("binary")
            model.chmod(0o755)
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            ki = SimpleNamespace(root=ki_root)
            context = {"installation_only": True}

            with self.assertRaisesRegex(api.ToolError, "model/example invocation"):
                api.execute_tool(
                    "run_setup_command", {"argv": [str(model)]},
                    ki, cfg, setup_mode=True, setup_context=context,
                )
            with mock.patch.object(
                    execution, "run_process",
                    return_value=execution.ProcessRun(
                        "succeeded", 0, stdout="DART 11.24.1", stderr="")):
                output = api.execute_tool(
                    "run_setup_command", {"argv": [str(model), "--version"]},
                    ki, cfg, setup_mode=True, setup_context=context,
                )
            self.assertIn("DART 11.24.1", output)

    def test_installation_only_agent_cannot_forge_verification_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            for filename in (
                    "status.json", "installation-test.json",
                    ".geoforge-install.json"):
                with self.subTest(filename=filename), self.assertRaisesRegex(
                        api.ToolError, "GeoForge-owned verification state"):
                    api.execute_tool(
                        "write_work_file",
                        {"path": filename, "content": '{"ok": true}'},
                        SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                        setup_context={"installation_only": True},
                    )

    def test_installation_only_tool_boundary_allows_build_not_reference_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            build = root / "binaries" / "DART" / "quickbuild.sh"
            build.parent.mkdir(parents=True)
            build.write_text("#!/bin/sh\nexit 0\n")
            build.chmod(0o755)
            reference = root / "run_reference_case.py"
            reference.write_text("print('scientific run')\n")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            ki = SimpleNamespace(root=ki_root)
            context = {"installation_only": True}

            with mock.patch.object(
                    execution, "run_process",
                    return_value=execution.ProcessRun(
                        "succeeded", 0, stdout="built", stderr="")):
                output = api.execute_tool(
                    "run_setup_command", {"argv": [str(build), "nompi"]},
                    ki, cfg, setup_mode=True, setup_context=context,
                )
            self.assertIn("built", output)
            with self.assertRaisesRegex(api.ToolError, "Python model/data command"):
                api.execute_tool(
                    "run_setup_command",
                    {"argv": [sys.executable, reference.name]},
                    ki, cfg, setup_mode=True, setup_context=context,
                )

    def test_installation_only_allows_workspace_source_generators(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            generator = root / "tools" / "win_bison.exe"
            grammar = root / "source" / "parser.y"
            generator.parent.mkdir()
            grammar.parent.mkdir()
            generator.write_bytes(b"MZ")
            grammar.write_text("%%\n")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                [str(generator), "-d", str(grammar)], 0,
                stdout="generated", stderr="",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command",
                    {"argv": [str(generator), "-d", str(grammar)]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("generated", output)

    def test_setup_allowlist_normalizes_bare_windows_executable_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                ["win_bison.exe", "--version"], 0,
                stdout="win_bison 2.5.25", stderr="",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command",
                    {"argv": ["win_bison.exe", "--version"]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("win_bison 2.5.25", output)

    def test_installation_only_allows_workspace_mingw_make(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            make = root / "toolchain" / "bin" / "mingw32-make.exe"
            make.parent.mkdir(parents=True)
            make.write_bytes(b"MZ")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                [str(make), "all"], 0, stdout="built", stderr="",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command",
                    {"argv": [str(make), "all"]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("built", output)

    def test_installation_only_allows_workspace_archive_extractor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            extractor = root / "tools" / "7zr.exe"
            installer = root / "downloads" / "setup.exe"
            extractor.parent.mkdir()
            installer.parent.mkdir()
            extractor.write_bytes(b"MZ")
            installer.write_bytes(b"MZ")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                [str(extractor), "x", str(installer)], 0,
                stdout="extracted", stderr="",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command",
                    {"argv": [str(extractor), "x", str(installer)]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("extracted", output)

    def test_installation_only_allows_bounded_workspace_micromamba(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            micromamba = root / "tools" / "micromamba.exe"
            micromamba.parent.mkdir()
            micromamba.write_bytes(b"MZ")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            argv = [str(micromamba), "create", "--root-prefix",
                    str(root / "mamba-root"), "--prefix", str(root / "env"),
                    "python=3.12", "pcraster", "gdal"]
            completed = subprocess.CompletedProcess(
                argv, 0, stdout="created", stderr="")
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command", {
                        "argv": argv,
                        "env": {"CONDA_PKGS_DIRS": str(root / "p")},
                    },
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("created", output)
            with self.assertRaisesRegex(
                    api.ToolError, "environment path escapes"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": argv,
                        "env": {"CONDA_PKGS_DIRS": str(root.parent)},
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            with self.assertRaisesRegex(api.ToolError, "requires both"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": [str(micromamba), "install", "pcraster"],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            with self.assertRaisesRegex(api.ToolError, "may not run"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": [str(micromamba), "run", "python", "--version"],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

    def test_installation_only_allows_only_bounded_portable_pacman(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            pacman = root / "msys64" / "usr" / "bin" / "pacman.exe"
            pacman.parent.mkdir(parents=True)
            pacman.write_bytes(b"MZ")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            argv = [
                str(pacman), "-S", "--needed", "--noconfirm",
                "make", "mingw-w64-x86_64-toolchain",
            ]
            completed = subprocess.CompletedProcess(
                argv, 0, stdout="installed", stderr="")
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command", {"argv": argv},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("installed", output)

            blocked_commands = (
                [str(pacman), "-S", "make"],
                [str(pacman), "-U", "--noconfirm", "local.pkg.tar.zst"],
                [str(pacman), "-S", "--noconfirm", "--root", str(root)],
                [str(pacman), "-S", "--noconfirm", "https://example/pkg"],
                [str(pacman), "-S", "--noconfirm", "--accept-license", "make"],
            )
            for blocked in blocked_commands:
                with self.subTest(argv=blocked):
                    with self.assertRaises(api.ToolError):
                        api.execute_tool(
                            "run_setup_command", {"argv": blocked},
                            SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                            setup_context={"installation_only": True},
                        )

    def test_installation_only_allows_workspace_portable_checksum(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            sha256sum = root / "msys64" / "usr" / "bin" / "sha256sum.exe"
            sha256sum.parent.mkdir(parents=True)
            sha256sum.write_bytes(b"MZ")
            archive = root / "msys2-base.tar.xz"
            archive.write_bytes(b"archive")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            argv = [str(sha256sum), str(archive)]
            completed = subprocess.CompletedProcess(
                argv, 0, stdout="digest  msys2-base.tar.xz", stderr="")
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command", {"argv": argv},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("digest", output)
            with self.assertRaisesRegex(api.ToolError, "workspace file"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": [str(sha256sum), str(root.parent / "outside")],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

    def test_installation_only_portable_shell_requires_one_safe_script(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            bash = root / "msys64" / "usr" / "bin" / "bash.exe"
            bash.parent.mkdir(parents=True)
            bash.write_bytes(b"MZ")
            script = root / "build-petsc.sh"
            script.write_text(
                "#!/usr/bin/env bash\n"
                "set -eu\n"
                "cd source/petsc\n"
                "/usr/bin/python ./configure --with-mpi=0\n"
                "make all\n",
                encoding="utf-8",
            )
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            argv = [str(bash), "--noprofile", "--norc", str(script)]
            completed = subprocess.CompletedProcess(
                argv, 0, stdout="built", stderr="")
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command", {"argv": argv},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("built", output)

            script.write_text(
                "cd /" + root.drive[:1].lower() +
                root.as_posix()[2:] + "/source/petsc\nmake all\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command", {"argv": [str(bash), str(script)]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("built", output)

            with self.assertRaisesRegex(api.ToolError, "command strings"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": [str(bash), "-lc", "make all"],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            script.write_text("sudo pacman -S make\n", encoding="utf-8")
            with self.assertRaisesRegex(api.ToolError, "host administration"):
                api.execute_tool(
                    "run_setup_command", {"argv": [str(bash), str(script)]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            script.write_text(
                "find . -type f -print0 | while read -r file; do\n"
                "  sed -i 's/x/y/' \"$file\"\n"
                "done\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(api.ToolError, "whole checkout"):
                api.execute_tool(
                    "run_setup_command", {"argv": [str(bash), str(script)]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

    def test_setup_workspace_path_env_covers_portable_msys_build_roots(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                ["git", "--version"], 0, stdout="git version", stderr="")
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command", {
                        "argv": ["git", "--version"],
                        "env": {
                            "MSYS2_ROOT": str(root / "msys64"),
                            "PETSC_DIR": str(root / "source" / "petsc"),
                            "TMP": str(root / "tmp"),
                        },
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("git version", output)
            with self.assertRaisesRegex(api.ToolError, "environment path escapes"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": ["git", "--version"],
                        "env": {"PETSC_DIR": str(root.parent)},
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

    def test_setup_exact_text_replacement_is_workspace_bounded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            source = root / "source.c"
            source.write_text("before\nold call\nafter\n", encoding="utf-8")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            output = api.execute_tool(
                "replace_work_text", {
                    "path": "source.c", "old": "old call", "new": "new call",
                }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                setup_context={"installation_only": True},
            )
            self.assertIn("replaced 1 exact match", output)
            self.assertEqual(
                source.read_text(encoding="utf-8"),
                "before\nnew call\nafter\n",
            )
            with self.assertRaisesRegex(api.ToolError, "found 0"):
                api.execute_tool(
                    "replace_work_text", {
                        "path": "source.c", "old": "missing", "new": "x",
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            outside = root.parent / "outside-source.c"
            outside.write_text("old call", encoding="utf-8")
            try:
                with self.assertRaisesRegex(api.ToolError, "absolute workspace"):
                    api.execute_tool(
                        "replace_work_text", {
                            "path": str(outside), "old": "old call", "new": "x",
                        }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                        setup_context={"installation_only": True},
                    )
            finally:
                outside.unlink(missing_ok=True)

    def test_setup_multiline_replacement_roundtrips_windows_written_and_read_text(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(root=root, python=sys.executable,
                                  roles={"binaries": root / "binaries"})

            def call(name, **args):
                return api.execute_tool(name, args, SimpleNamespace(root=ki_root), cfg,
                                        setup_mode=True, setup_context={"installation_only": True})

            content = "// café 中文\na = 1\nb = 2\nafter\n"
            # Windows write_work_file itself translates LF to CRLF. Supply
            # CRLF explicitly on other hosts to exercise the same disk bytes.
            native_content = content if os.name == "nt" else content.replace("\n", "\r\n")
            call("write_work_file", path="source.c", content=native_content)
            self.assertEqual((root / "source.c").read_bytes(), content.replace("\n", "\r\n").encode())
            read = call("read_work_file", path="source.c")
            self.assertEqual(read, content)
            old = "\n".join(read.splitlines()[1:3])
            call("replace_work_text", path="source.c", old=old, new="a = 3\nb = 4\nc = 5")
            expected = content.replace(old, "a = 3\nb = 4\nc = 5").replace("\n", "\r\n").encode()
            self.assertEqual((root / "source.c").read_bytes(), expected)

    def test_setup_multiline_replacement_preserves_mixed_untouched_bytes_and_local_endings(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            source = root / "source.c"
            prefix = "\ufeff// 中文\r\nleft\n".encode()
            source.write_bytes(prefix + b"old\r\ncall\r\nseparator\nold\ncall\ntail\r\n")
            cfg = SimpleNamespace(root=root, python=sys.executable,
                                  roles={"binaries": root / "binaries"})
            api.execute_tool("replace_work_text", {
                "path": "source.c", "old": "old\ncall", "new": "new\r\nvalue", "expected_count": 2,
            }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                setup_context={"installation_only": True})
            self.assertEqual(source.read_bytes(),
                             prefix + b"new\r\nvalue\r\nseparator\nnew\nvalue\ntail\r\n")

    def test_setup_replacement_counts_both_newline_styles_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            source = root / "source.c"
            original = b"old\r\ncall\r\nseparator\nold\ncall\n"
            source.write_bytes(original)
            cfg = SimpleNamespace(root=root, python=sys.executable,
                                  roles={"binaries": root / "binaries"})
            for old, count in (("old\ncall", 2), ("old\r\ncall", 2), ("old \ncall", 0)):
                with self.subTest(old=old), self.assertRaisesRegex(api.ToolError, f"found {count}"):
                    api.execute_tool("replace_work_text", {
                        "path": "source.c", "old": old, "new": "changed\ncall", "expected_count": 1,
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                        setup_context={"installation_only": True})
                self.assertEqual(source.read_bytes(), original)

    def test_setup_inline_replacement_uses_surrounding_lines_newline(self):
        self.assertEqual(api._replace_workspace_text("prefix\nold\r\ntail\n", "old", "new\nline", 1),
                         "prefix\nnew\r\nline\r\ntail\n")
        self.assertEqual(api._replace_workspace_text("prefix\r\nold", "old", "new\nline", 1),
                         "prefix\r\nnew\r\nline")

    def test_installation_agent_cannot_write_dependency_shims_to_site_packages(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            site = root / "venv" / "Lib" / "site-packages"
            site.mkdir(parents=True)
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            with self.assertRaisesRegex(api.ToolError, "may not write directly"):
                api.execute_tool(
                    "write_work_file", {
                        "path": "venv/Lib/site-packages/fcntl.py",
                        "content": "# fake compatibility module\n",
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            installed = site / "dependency.py"
            installed.write_text("old\n", encoding="utf-8")
            with self.assertRaisesRegex(api.ToolError, "may not patch"):
                api.execute_tool(
                    "replace_work_text", {
                        "path": "venv/Lib/site-packages/dependency.py",
                        "old": "old", "new": "new",
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

    def test_installation_agent_cannot_generate_dependency_shim_wheel(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            content = (
                "import zipfile\n"
                "zipfile.ZipFile('compat.whl', 'w').writestr('fcntl.py', "
                "'F_GETFL=3\\ndef fcntl(fd, cmd, arg=0): return 0\\n')\n"
            )
            with self.assertRaisesRegex(api.ToolError, "hand-assemble wheels"):
                api.execute_tool(
                    "write_work_file", {
                        "path": "build_compat_wheel.py", "content": content,
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

            with self.assertRaisesRegex(api.ToolError, "hand-assemble wheels"):
                api.execute_tool(
                    "write_work_file", {
                        "path": "make_noise_wheel.py",
                        "content": (
                            "import zipfile\n"
                            "zipfile.ZipFile('noise.whl', 'w').writestr("
                            "'noise-1.2.2.dist-info/METADATA', 'x')\n"
                        ),
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

            with self.assertRaisesRegex(api.ToolError, "replacement setup project"):
                api.execute_tool(
                    "write_work_file", {
                        "path": "noise-stage/setup.py",
                        "content": (
                            "from setuptools import setup\n"
                            "setup(name='noise', package_data={'noise': ['*.pyd']})\n"
                        ),
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

            with self.assertRaisesRegex(api.ToolError, "hand-assemble wheel archives"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": ["tar", "-cf", "noise.whl", "noise-stage"],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

            helper = root / "build_existing_wheel.py"
            helper.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(api.ToolError, "hand-assemble wheels"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": [sys.executable, helper.name],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

    def test_installation_agent_cannot_pip_install_local_dependency_shim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            wheel = root / "compat-1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr("fcntl.py", "F_GETFL = 3\n")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            with self.assertRaisesRegex(api.ToolError, "may not install"):
                api.execute_tool(
                    "run_setup_command", {
                        "argv": [sys.executable, "-m", "pip", "install", str(wheel)],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

    def test_installation_only_allows_workspace_windows_compiler_arguments(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            compiler = root / "toolchain" / "bin" / "gcc.exe"
            source = root / "source" / "extension.c"
            compiler.parent.mkdir(parents=True)
            source.parent.mkdir()
            compiler.write_bytes(b"MZ")
            source.write_text("int value = 1;\n")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                [str(compiler), "-Iinclude", "-c", str(source)], 0,
                stdout="compiled", stderr="",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command", {
                        "argv": [str(compiler), "-Iinclude", "-c", str(source)],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("compiled", output)

    def test_installation_only_allows_workspace_python_version_probe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            python = root / "venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"MZ")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                [str(python), "--version"], 0,
                stdout="Python 3.9.13", stderr="",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                output = api.execute_tool(
                    "run_setup_command",
                    {"argv": [str(python), "--version"]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("Python 3.9.13", output)

    def test_installation_only_allows_upstream_python_codegen(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            generator = root / "source" / "bin" / "dynamic_field_lookup.py"
            generator.parent.mkdir(parents=True)
            generator.write_text(
                "from pathlib import Path\n"
                "Path('generated.c').write_text('int generated;\\n')\n",
                encoding="utf-8",
            )
            output = root / "source" / "util" / "index_struct_fields.c"
            output.parent.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                [sys.executable, str(generator), "--output", str(output)],
                0, stdout="generated", stderr="",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)):
                result = api.execute_tool(
                    "run_setup_command", {
                        "argv": [sys.executable, str(generator),
                                 "--output", str(output)],
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("generated", result)

    def test_installation_only_caps_startup_probe_timeout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            binary = root / "binaries" / "model.exe"
            binary.parent.mkdir()
            binary.write_bytes(b"MZ")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                [str(binary), "--help"], 0, stdout="usage", stderr="",
            )
            with mock.patch.object(
                    execution, "run_process", return_value=_process_run(completed)) as run:
                output = api.execute_tool(
                    "run_setup_command", {
                        "argv": [str(binary), "--help"],
                        "timeout_seconds": 600,
                    }, SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )
            self.assertIn("usage", output)
            self.assertEqual(run.call_args.kwargs["timeout"], 20)

    @unittest.skipUnless(os.name == "nt", "Windows PE validation")
    def test_setup_rejects_archive_renamed_as_exe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            archive = root / "micromamba.exe"
            archive.write_bytes(b"BZh91AY&SY")
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            with self.assertRaisesRegex(api.ToolError, "not a Windows PE"):
                api.execute_tool(
                    "run_setup_command",
                    {"argv": [str(archive), "--version"]},
                    SimpleNamespace(root=ki_root), cfg, setup_mode=True,
                    setup_context={"installation_only": True},
                )

    def test_cli_written_handoff_cannot_inject_a_link(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / setup.REQUEST_FILE).write_text(json.dumps({
                "status": "waiting", "kind": "download", "title": "Continue",
                "message": "click", "url": "javascript:alert(1)",
            }))
            self.assertIsNone(setup.request(root)["url"])

    def test_claude_policy_maps_named_build_commands(self):
        pol = policy.Policy("Demo")
        pol.add("exec", "git", "setup")
        args, enforcement = policy.claude_args(pol)
        self.assertEqual(enforcement, policy.Enforcement.EXACT)
        self.assertIn("Bash(git:*)", args)

    def test_setup_policy_can_execute_a_model_scoped_downloaded_toolchain(self):
        with tempfile.TemporaryDirectory() as td:
            binaries = Path(td) / "binaries"
            cfg = SimpleNamespace(roles={"binaries": binaries})
            pol = policy.Policy("APSIM")
            gui._grant_setup_execution(pol, cfg)
            keys = {grant.key() for grant in pol.grants}
            self.assertEqual(pol.posture, policy.Posture.WORKSPACE_WRITE)
            self.assertIn(f"exec:{binaries}", keys)
            self.assertIn("exec:dotnet", keys)
            args, _ = policy.claude_args(pol)
            self.assertIn(f"Bash({binaries}/**)", args)
            self.assertIn("Bash(dotnet:*)", args)

    def test_policy_grants_configured_python_and_declared_model_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = paths.KissConfig.default(root / "work")
            cfg.python = "python3"
            pol = policy.Policy.derive(
                KI("Demo", ki_root),
                Manifest(model="Demo", system_deps=["wine"]),
                cfg,
            )
            keys = {grant.key() for grant in pol.grants}
            self.assertIn("exec:python3", keys)
            self.assertIn("exec:wine", keys)
            args, _ = policy.claude_args(pol)
            self.assertIn("Bash(python3:*)", args)
            self.assertIn("Bash(wine:*)", args)

    def test_policy_exposes_shared_binary_root_for_declared_coupling(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = paths.KissConfig.default(root / "vic")
            pol = policy.Policy.derive(
                KI("VIC", ki_root),
                Manifest(model="VIC", install_dir="VIC-5.1.0",
                         depends_on=["CaMa_Flood"]),
                cfg,
            )
            keys = {grant.key() for grant in pol.grants}
            self.assertIn(f"read:{cfg.roles['binaries']}", keys)
            self.assertIn(f"exec:{cfg.roles['binaries']}", keys)
            self.assertIn(
                f"exec:{cfg.roles['binaries'] / 'VIC-5.1.0'}", keys)


class ImportValidationTests(unittest.TestCase):
    def setUp(self):
        from .test_ki_verification_boundaries import isolated_engine
        self.gate_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.gate_temp.cleanup)
        self.gate_fixture = isolated_engine(Path(self.gate_temp.name))
        self.gate_fixture.__enter__()
        self.addCleanup(self.gate_fixture.__exit__, None, None, None)

    @staticmethod
    def _package(*, valid: bool = True) -> bytes:
        doc = io.BytesIO()
        with zipfile.ZipFile(doc, "w") as z:
            z.writestr("Demo/SKILL.md", "# Demo KI\n")
            if valid:
                z.writestr("Demo/preflight_check.py", "print('PREFLIGHT_REPORT={}')\n")
            z.writestr("Demo/docs/format_spec.yaml", "format: demo\n")
            z.writestr("Demo/dag.yaml", """
template_version: '3.5'
identity:
  model_id: Demo
  repo_url: https://example.com/demo
boundary: {}
inputs: {}
outputs: {}
states: {}
processes: {}
influence: {}
safety: {}
""")
        return doc.getvalue()

    @staticmethod
    def _handler(user_dir: Path, path: str):
        captured = {}
        handler = object.__new__(gui.Handler)
        handler.path = path
        handler.catalog = SimpleNamespace(
            packages={}, user_dir=user_dir, refresh=lambda: None,
        )
        handler._json = lambda obj, code=200: captured.update(obj=obj, code=code)
        return handler, captured

    def test_invalid_ki_is_rejected_before_it_is_copied(self):
        with tempfile.TemporaryDirectory() as td:
            handler, captured = self._handler(
                Path(td), "/api/import_ki?name=Demo.zip",
            )
            handler._import_ki_bytes(self._package(valid=False))
            self.assertEqual(captured["code"], 422)
            self.assertFalse(captured["obj"]["valid"])
            self.assertFalse((Path(td) / "Demo").exists())

    def test_valid_ki_can_be_checked_without_importing(self):
        with tempfile.TemporaryDirectory() as td:
            handler, captured = self._handler(
                Path(td), "/api/import_ki?validate=1&name=Demo.zip",
            )
            handler._import_ki_bytes(self._package())
            self.assertEqual(captured["code"], 200)
            self.assertTrue(captured["obj"]["ready_to_import"])
            self.assertFalse((Path(td) / "Demo").exists())


class PlatformParityTests(unittest.TestCase):
    """The same feature has to exist on all three platforms, not just macOS.

    Both gaps these cover shipped silently: Windows fell through the clipboard
    branches and returned "" for every read and False for every write, and the
    build-tools prompt only ever produced a real command for Homebrew.
    """

    def _capture(self, osname):
        """Run a clipboard round-trip on a pretended OS, returning the argv."""
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"], seen["kw"] = cmd, kw
            return SimpleNamespace(returncode=0, stdout="text")

        with mock.patch.object(clipboard.subprocess, "run", fake_run), \
             mock.patch.object(clipboard.platform, "system", lambda: osname), \
             mock.patch.object(clipboard.shutil, "which",
                               lambda name: f"/usr/bin/{name}"), \
             mock.patch.object(clipboard, "_mac_read", lambda: None), \
             mock.patch.object(clipboard, "_mac_write", lambda _t: None):
            read = clipboard.read_text()
            read_cmd, read_kw = seen["cmd"], seen["kw"]
            wrote = clipboard.write_text("hello")
        return read, read_cmd, read_kw, wrote, seen["cmd"]

    def test_windows_clipboard_is_wired_at_all(self):
        read, read_cmd, _kw, wrote, write_cmd = self._capture("Windows")
        self.assertEqual(read, "text")
        self.assertTrue(wrote)
        self.assertEqual(read_cmd[0], "powershell")
        self.assertEqual(write_cmd[0], "powershell")
        self.assertIn("Get-Clipboard", " ".join(read_cmd))
        self.assertIn("Set-Clipboard", " ".join(write_cmd))

    def test_clipboard_pins_utf8_on_every_platform(self):
        # Locale-codepage decoding is what turned prompts into mojibake on a
        # Chinese Windows install; the clipboard must not repeat it.
        for osname in ("Windows", "Linux", "Darwin"):
            with self.subTest(os=osname):
                _r, _c, kw, _w, _wc = self._capture(osname)
                self.assertEqual(kw.get("encoding"), "utf-8")

    def test_windows_clipboard_does_not_flash_a_console(self):
        # A windowed build owns no console, so a spawn without CREATE_NO_WINDOW
        # pops a black window — here that would be on every copy and paste.
        # _SPAWN is decided at import, so re-import under a pretended Windows.
        with mock.patch.object(os, "name", "nt"):
            windows = importlib.reload(clipboard)
            flags = dict(windows._SPAWN)
        importlib.reload(clipboard)          # restore for the rest of the suite
        self.assertEqual(flags.get("creationflags"),
                         getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        expected = ({"creationflags": getattr(
            subprocess, "CREATE_NO_WINDOW", 0x08000000)}
            if os.name == "nt" else {})
        self.assertEqual(clipboard._SPAWN, expected)

    def test_every_package_manager_names_the_same_tools(self):
        # A tool missing from one table means that platform silently drops it
        # from the install line and the user is told to find it themselves.
        tools = set(setup._PACKAGES["brew"])
        for manager, table in setup._PACKAGES.items():
            with self.subTest(manager=manager):
                self.assertEqual(set(table), tools)
                self.assertIn(manager, setup._INSTALLERS)

    def test_install_command_is_built_for_each_platform(self):
        missing = ["gfortran", "nc-config"]
        for manager, expected in (
            ("brew", "brew install gcc netcdf"),
            ("apt", "sudo apt install gfortran libnetcdf-dev"),
            ("dnf", "sudo dnf install gcc-gfortran netcdf-devel"),
            ("msys2", "pacman -S mingw-w64-x86_64-gcc-fortran mingw-w64-x86_64-netcdf"),
        ):
            with self.subTest(manager=manager), \
                 mock.patch.object(setup, "_package_manager", lambda m=manager: m):
                self.assertEqual(setup._install_command(missing), expected)

    def test_install_command_is_empty_when_no_manager_is_found(self):
        with mock.patch.object(setup, "_package_manager", lambda: None):
            self.assertEqual(setup._install_command(["gfortran"]), "")

    def test_prompt_does_not_call_them_mac_tools_on_other_platforms(self):
        source = Path(setup.__file__).read_text(encoding="utf-8")
        self.assertNotIn("Mac tools", source)
        self.assertIn("system tools", source)

    def _providers_on_windows(self):
        """The provider table as a Windows machine builds it."""
        with mock.patch.object(os, "name", "nt"):
            win = importlib.reload(providers)
            table = {n: (p.install, p.auth) for n, p in win.PROVIDERS.items()}
        importlib.reload(providers)      # restore for the rest of the suite
        return table

    def test_no_setup_hint_tells_windows_to_open_terminal(self):
        # "Terminal" is a macOS application; on Windows it sends the user
        # looking for something that is not there. This is the setup screen,
        # where no provider works yet and the hint is all they have.
        for name, (_install, auth) in self._providers_on_windows().items():
            with self.subTest(provider=name):
                self.assertNotIn("in Terminal", auth)

    def test_no_setup_hint_gives_windows_a_posix_only_command(self):
        # A curl|bash installer cannot run on a stock Windows box: no curl, no
        # bash, no sh. Naming a command that fails is worse than naming none.
        for name, (install, _auth) in self._providers_on_windows().items():
            with self.subTest(provider=name):
                self.assertNotIn("| bash", install)
                self.assertNotIn("curl -fsSL", install)

    def test_posix_hints_are_left_alone(self):
        # The Windows adaptation must not leak onto macOS or Linux.
        with mock.patch.object(os, "name", "posix"):
            posix = importlib.reload(providers)
            claude_auth = posix.PROVIDERS["claude"].auth
            kimi_install = posix.PROVIDERS["kimi"].install
        importlib.reload(providers)
        self.assertIn("in Terminal", claude_auth)
        self.assertIn("curl -fsSL", kimi_install)

    def test_windows_reveal_passes_select_and_path_as_one_argument(self):
        # explorer takes "/select,<path>" as a single token. Split in two it
        # drops the path and opens the default folder, so the file the user
        # asked to see is the one thing they do not get.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "project" / "results" / "run.csv"
            target.parent.mkdir(parents=True)
            target.write_text("x")
            seen = {}

            with mock.patch.object(sessions.platform, "system", lambda: "Windows"), \
                 mock.patch.object(sessions.subprocess, "Popen",
                                   lambda argv, **kw: seen.setdefault("argv", argv)), \
                 mock.patch.object(sessions, "project_path", lambda _w, _s: root / "project"):
                sessions.open_in_file_manager(root, {}, "results/run.csv")

        argv = seen["argv"]
        self.assertEqual(argv[0], "explorer")
        self.assertEqual(len(argv), 2, f"/select, must be one argument: {argv}")
        self.assertTrue(argv[1].startswith("/select,"))
        self.assertIn("run.csv", argv[1])


if __name__ == "__main__":
    unittest.main()



class ExternalPointerListingTests(unittest.TestCase):
    def test_listing_does_not_open_external_project_folders(self):
        with tempfile.TemporaryDirectory() as td:
            workroot = Path(td) / "kiss"
            (workroot / "sessions").mkdir(parents=True)
            external = Path(td) / "Documents" / "2026-09-02-Run-a-real-CRHM-case--0bb6986c2c3e"
            external.mkdir(parents=True)
            (workroot / "sessions" / "0bb6986c2c3e.json").write_text(json.dumps({
                "kind": "geoforge-project-pointer-v1", "id": "0bb6986c2c3e",
                "project_root": str(external)}))
            opened = []
            real_load = sessions.load

            def spy(root, sid):
                opened.append(sid)
                return real_load(root, sid)

            with mock.patch.object(sessions, "load", side_effect=spy):
                listed = sessions.list_all(workroot)
        self.assertEqual(opened, [])
        self.assertEqual(listed[0]["id"], "0bb6986c2c3e")
        self.assertTrue(listed[0]["external"])
        self.assertEqual(listed[0]["title"], "Run a real CRHM case")



class DownloadRequestTests(unittest.TestCase):
    def test_download_request_counts_as_placed_only_when_files_exist(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "inputs" / "raw" / "cmfd"
            req = {"kind": "download", "expected_path": str(target)}
            self.assertFalse(setup.download_placed(req))          # folder absent
            target.mkdir(parents=True)
            self.assertFalse(setup.download_placed(req))          # empty folder
            (target / ".DS_Store").write_bytes(b"x")
            self.assertFalse(setup.download_placed(req))          # junk only
            (target / "Prec" ).mkdir()
            (target / "Prec" / "prec_1989.nc").write_bytes(b"data")
            self.assertTrue(setup.download_placed(req))
            self.assertFalse(setup.download_placed({"kind": "download"}))

    def test_partial_hidden_and_symlink_payloads_do_not_resume_download(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "cmfd"
            target.mkdir()
            req = {"kind": "download", "expected_path": str(target)}
            for name in ("forcing.nc.part", "forcing.nc.crdownload", "forcing.nc.tmp"):
                (target / name).write_bytes(b"incomplete")
            hidden = target / ".cache"
            hidden.mkdir()
            (hidden / "data.nc").write_bytes(b"cache")
            outside = Path(td) / "other.nc"
            outside.write_bytes(b"unrelated")
            (target / "linked.nc").symlink_to(outside)
            self.assertFalse(setup.download_placed(req))
            self.assertFalse(setup.download_placed({"expected_path": str(target / "forcing.nc.part")}))
            (target / "forcing.nc").write_bytes(b"delivered")
            self.assertTrue(setup.download_placed(req))


class SetupSessionResumeTests(unittest.TestCase):
    """User report 2026-09-18: after a user action the setup agent restarted from scratch
    because every retry spawned a fresh CLI process. The workspace now remembers the CLI's
    own session id and the retry continues it with a short message."""

    def test_setup_workspace_remembers_and_returns_the_cli_session(self):
        from kiss_cli import setup as setup_flow
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertIsNone(setup_flow.cli_session(root, "claude"))
            setup_flow.remember_cli_session(root, "claude", "abc-123")
            setup_flow.remember_cli_session(root, "kimi", "k-9")
            self.assertEqual(setup_flow.cli_session(root, "claude"), "abc-123")
            self.assertEqual(setup_flow.cli_session(root, "kimi"), "k-9")
            (root / setup_flow.CLI_SESSION_FILE).write_text("not json")
            self.assertIsNone(setup_flow.cli_session(root, "claude"))

    def test_resume_message_continues_instead_of_restarting(self):
        from kiss_cli import setup as setup_flow
        with tempfile.TemporaryDirectory() as td:
            msg = setup_flow.resume_message({"user_note": "installed gfortran", "resume_hint": "rerun make"}, Path(td))
            self.assertIn("installed gfortran", msg)
            self.assertIn("rerun make", msg)
            self.assertIn("Do not re-read the KI", msg)
            self.assertNotIn("[TASK]", msg)
