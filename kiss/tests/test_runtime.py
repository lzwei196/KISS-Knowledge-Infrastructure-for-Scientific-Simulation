from __future__ import annotations

import json
import io
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

from kiss_cli import api, app as desktop_app, calibration, clipboard, gui, harness_runtime, install, install_locations, kimi_security, mcp, paths, plotting, policy, port, preparation, projectrun, projectview, prompt, providers, sessions, settings, setup, shellenv, skilllib, software_audit, tls
from kiss_cli.catalog import KI
from kiss_cli.manifest import Acquire, DataNeed, Manifest


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
        with mock.patch.object(providers.shutil, "which", return_value="/bin/claude"), \
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
        }
        try:
            status = gui._agent_run_snapshot("status-test")
        finally:
            gui._LIVE_AGENT_RUNS.pop("status-test", None)
        self.assertTrue(status["process_alive"])
        self.assertEqual(status["activity"], "Bash")
        self.assertGreaterEqual(status["event_silence_seconds"], 94)
        self.assertEqual(status["pid"], 31415)

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
                    api.subprocess, "run",
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
        mac = (source / "GeoForgeDesktop.spec").read_text()
        generic = (source / "KISS.spec").read_text()
        for spec in (mac, generic):
            self.assertIn("ki_tools_common.harness.ki_harness", spec)
            self.assertIn("ki_tools_common.harness.ki_attention", spec)
            self.assertIn("ki_tools_common.harness.agent_spawn", spec)
            self.assertIn("ki_tools_common", spec)
        self.assertIn("str(KI_TOOLS_SOURCE)", mac)
        self.assertIn("'../ki_tools_common'", generic)

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
            result = subprocess.run(
                [sys.executable, str(live / "preflight_check.py")],
                capture_output=True, text=True,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SOFTWARE PREFLIGHT PASSED", result.stdout)
        self.assertIn("Project data not installed globally", result.stdout)

    def test_dssat_weather_fields_do_not_silently_drop_a_digit(self):
        script = (Path(__file__).parents[2] / "models" / "DSSAT" / "tools" /
                  "run_reference_case.py")
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
                f'check_file("{root}/Demo/build/bin/demo", "Demo", executable=True)\n'
            )
            ki = SimpleNamespace(preflight=preflight, root=root / "ki")
            cfg = SimpleNamespace(root=root)

            notes = install.place_where_the_ki_expects(ki, binary, cfg, prefix)

            self.assertTrue((root / "Demo").is_symlink())
            self.assertEqual((root / "Demo").resolve(), prefix.resolve())
            self.assertIn("linked install tree", notes[0])

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


class EnvironmentAndTlsTests(unittest.TestCase):
    def test_interactive_login_environment_is_nul_delimited(self):
        shellenv._done = False
        completed = SimpleNamespace(stdout=b"PATH=/custom/bin:/usr/bin\0TOKEN=a=b\nc\0")
        with mock.patch.dict(shellenv.os.environ,
                             {"HOME": "/tmp/geoforge-home", "SHELL": "/bin/zsh",
                              "PATH": "/usr/bin:/bin"}, clear=True), \
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

    def test_proxy_provider_selection_is_saved_and_defaults_to_claude_codex(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(settings, "_path", return_value=Path(td) / "settings.json"), \
             mock.patch.object(settings.urllib.request, "getproxies", return_value={
                 "https": "http://127.0.0.1:7897"}):
            self.assertEqual(
                set(settings.masked()["proxy_providers"]),
                {"cli:claude", "cli:codex"})
            settings.update({"proxy_providers": ["cli:kimi", "api:anthropic"]})
            self.assertEqual(
                set(settings.masked()["proxy_providers"]),
                {"cli:kimi", "api:anthropic"})
            self.assertEqual(
                settings.proxy_url_for("cli:kimi"), "http://127.0.0.1:7897")
            self.assertEqual(settings.proxy_url_for("api:deepseek"), "")

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
        deny = f'(deny file-read* (subpath "{home}"))'
        allow = f'(allow file-read* (subpath "{project}"))'
        self.assertIn(deny, text)
        self.assertIn(allow, text)
        self.assertIn(
            f'(allow file-read* (subpath "{home / ".agents" / "skills"}"))',
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
            f'(allow file-read-metadata (literal "{home / ".agents"}"))', text)
        self.assertIn(f'(allow file-read* (subpath "{skills}"))', text)
        self.assertNotIn(f'(allow file-read* (subpath "{home / ".agents"}"))', text)
        self.assertNotIn(f'(allow file-write* (subpath "{skills}"))', text)

    def test_scoped_kimi_uses_explicit_skills_instead_of_watching_home(self):
        with tempfile.TemporaryDirectory() as td:
            cwd = Path(td)
            project_skills = cwd / ".agents" / "skills"
            project_skills.mkdir(parents=True)
            dirs = kimi_security.explicit_skill_dirs(cwd)

            self.assertIn((Path.home() / ".agents" / "skills").resolve(), dirs)
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
            settings.update({"kimi_security_mode": "full"})
            self.assertEqual(settings.masked()["kimi_security_mode"], "full")
            with self.assertRaisesRegex(ValueError, "unknown Kimi security mode"):
                settings.update({"kimi_security_mode": "everything"})


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
        source = (Path(__file__).parents[1] / "kiss_cli" / "app.py").read_text()
        self.assertIn("webview.settings['SHOW_DEFAULT_MENUS'] = True", source)
        self.assertIn("webview.start()", source)
        self.assertNotIn("webview.start(_install_edit_menu)", source)

    def test_native_project_folder_picker_returns_one_selected_folder(self):
        native = SimpleNamespace(FOLDER_DIALOG="folder")
        bridge = desktop_app._DesktopApi(native)
        bridge.window = SimpleNamespace(
            create_file_dialog=mock.Mock(return_value=("/tmp/research",)))

        self.assertEqual(
            bridge.choose_project_parent("/tmp"), "/tmp/research")
        bridge.window.create_file_dialog.assert_called_once_with(
            "folder", directory="/tmp", allow_multiple=False)

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
                (root / "sessions" / f"{session['id']}.json").read_text())
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
            self.assertIn("<svg", output.read_text())
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
            svg = output.read_text()
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
            svg = (project / "artifacts" / "growth.svg").read_text()
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
            archived = (project / "memory" / "transcript.jsonl").read_text().splitlines()

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
            self.assertIn("old message", (project / "memory" / "transcript.jsonl").read_text())

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

            materialised = (run_ki.root / "SKILL.md").read_text()
            self.assertEqual(cfg.roles["binaries"], shared.roles["binaries"])
            self.assertEqual(cfg.roles["home"], shared.roles["home"])
            self.assertEqual(cfg.roles["forcing"], project / "inputs" / "forcing")
            self.assertEqual(cfg.roles["outputs"], project / "outputs" / "Demo")
            self.assertIn(str(project / "inputs" / "forcing"), materialised)
            self.assertIn(str(project / "outputs" / "Demo"), materialised)
            self.assertIn(str(shared.roles["home"] / "Demo" / "bin" / "model"),
                          materialised)

            # A validated legacy deck may need to keep inputs and generated
            # outputs together. A project-local binding survives refresh, but
            # it cannot override shared executable/runtime locations.
            deck = project / "outputs" / "Demo" / "case-one"
            deck.mkdir(parents=True)
            (deck / "INPUT.DAT").write_text("ready")
            saved = paths.KissConfig.load(project)
            saved.roles["static"] = deck
            saved.roles["binaries"] = project / "untrusted-binaries"
            (project / paths.CONFIG_NAME).write_text(saved.dumps())
            rebound = gui.Handler._session_config(fake_handler, project, ki)
            self.assertEqual(rebound.roles["static"], deck)
            self.assertEqual(rebound.roles["binaries"], shared.roles["binaries"])

            # Reusing the chat refreshes its generated KI copy, so corrected
            # shared paths and newly shipped tools reach existing projects.
            (run_ki.root / "SKILL.md").write_text("stale generated copy\n")
            refreshed, _ = gui.Handler._session_workspace(fake_handler, project, ki)
            self.assertNotIn("stale", (refreshed.root / "SKILL.md").read_text())

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
    def test_environment_selfcheck_proves_the_harness_before_providers(self):
        source = (Path(__file__).parents[1] / "kiss_cli" / "gui.py").read_text()
        self.assertIn("[1/5] KI harness contract", source)
        self.assertIn("harness_runtime.status", source)

    def test_explicit_autonomous_chat_does_not_require_a_second_approval(self):
        self.assertIn("continue into the tools in this SAME", gui.SCOPE_FIRST_RULES)
        self.assertIn("Do not ask them to approve the work again", gui.SCOPE_FIRST_RULES)

    def test_cli_model_picker_has_native_default_and_starts_disabled(self):
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html").read_text()
        self.assertIn("CLI default", page)
        self.assertIn("Auto KI", page)

    def test_chat_stream_hides_keepalives_and_explains_real_disconnects(self):
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html").read_text()
        self.assertIn('replaceAll("\\u200b","")', page)
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
        bridge = (Path(__file__).parents[1] / "kiss_cli" / "web" / "clipboard.js").read_text()
        self.assertIn("/api/clipboard", bridge)
        self.assertIn("contextmenu", bridge)
        self.assertIn("e.metaKey||e.ctrlKey", bridge)
        self.assertIn("navigator.clipboard", bridge)
        self.assertIn("Copy this message", page)
        self.assertIn("Recheck local CLIs", page)
        self.assertIn("/api/providers?refresh=1", page)
        self.assertIn('id="s-proxy-mode"', page)
        self.assertIn('id="s-proxy-url"', page)
        self.assertIn("Test AI & GitHub", page)
        self.assertIn("agent-run Git, pip, curl, and download commands", page)
        self.assertIn("/api/selfcheck?provider=", page)
        self.assertIn("refreshMachineStatus", page)
        self.assertIn('fetch("/api/status",{cache:"no-store"})', page)
        self.assertIn("refreshMachineStatus(true,true)", page)
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
        self.assertIn("process is alive but silent for", page)
        self.assertIn("can confirm that the process is alive, but not that it is computing", page)
        self.assertIn("/agent-status", page)
        self.assertIn("event_silence_seconds", page)
        self.assertIn("continue in the background", page)
        self.assertIn("setInterval(updateActivityUI,1000)", page)
        self.assertIn('id="actionpick"', page)
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
        self.assertIn("create_project_plot", (Path(__file__).parents[1] / "kiss_cli" / "api.py").read_text())
        self.assertIn("chat-artifact", page)
        self.assertIn("/artifact?path=", page)
        self.assertIn("renderMarkdownTables", page)
        self.assertIn(".md-table", page)
        self.assertIn("Some providers double-escape Markdown", page)
        self.assertIn("AUTOMATIC SKILL USE AND INLINE RESULTS", gui.AUTOMATIC_SKILL_RULES)
        self.assertIn("SKILLS SELECTED BY THE USER", gui.SESSION_PROJECT_RULES + skilllib.prompt_block([]) + (Path(__file__).parents[1] / "kiss_cli" / "skilllib.py").read_text())
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
        self.assertIn("Add source data", page)
        self.assertIn("Project status", page)
        self.assertIn("Continue in chat", page)
        self.assertIn("Project progress", page)
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
        self.assertIn("required data paths are ready", page)
        self.assertIn("datasetChecks", page)
        self.assertIn("extractWork", page)
        self.assertIn("Work details", page)
        self.assertIn("USER-FACING RESPONSE", gui.RESPONSE_PRESENTATION_RULES)
        self.assertIn("SIMPLIFIED CHINESE", gui.response_language_rules("请运行这个模型"))
        self.assertIn("latest message", gui.response_language_rules("Run this model"))
        locale = (Path(__file__).parents[1] / "kiss_cli" / "web" / "i18n.js").read_text()
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
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" / "library.html").read_text()
        self.assertIn("Browse, import, and verify KIs", page)
        self.assertIn("Check &amp; Import", page)
        self.assertIn("KI package check", page)
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

    def test_agent_setup_has_a_separate_human_handoff_page(self):
        page = (Path(__file__).parents[1] / "kiss_cli" / "web" / "setup.html").read_text()
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
        self.assertIn("Model installation folder", page)
        self.assertIn("chooseInstallLocation", page)
        self.assertIn("/api/setup-location", page)
        self.assertIn("GeoForge will create it and record the choice", page)
        self.assertNotIn('req.expected_path||["download","licence"]', page)
        chat = (Path(__file__).parents[1] / "kiss_cli" / "web" / "app.html").read_text()
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

    def test_install_path_is_recorded_beside_and_inside_local_ki(self):
        with tempfile.TemporaryDirectory() as td:
            workroot = Path(td) / "geoforge"
            workspace = Path(td) / "chosen" / "VIC"
            install_locations.select(workroot, "VIC", workspace)
            live = workspace / "ki"
            live.mkdir(parents=True)
            cfg = paths.KissConfig.default(workspace)
            (workspace / paths.CONFIG_NAME).write_text(cfg.dumps())

            value = install_locations.record(
                "VIC", workspace, cfg, ki_root=live, verified=True)

            outer = json.loads(
                (workspace / install_locations.RECORD_FILE).read_text())
            inner = json.loads(
                (live / install_locations.RECORD_FILE).read_text())
            self.assertEqual(outer, inner)
            self.assertEqual(outer["workspace"], str(workspace.resolve()))
            self.assertEqual(outer["binaries"], str(cfg.roles["binaries"]))
            self.assertTrue(value["verified"])
            self.assertTrue(install_locations.info(workroot, "VIC")["recorded"])

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
            (workspace / paths.CONFIG_NAME).write_text(cfg.dumps())
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
            ki = KI("Demo", package)
            man = Manifest(
                model="Demo", acquire=Acquire(strategy="build", repo="https://invalid"),
            )
            materialised = SimpleNamespace(
                unresolved=set(), corrupted=[], tokens_replaced=0, undeliverable_files=0,
            )
            emitted = []
            good = lambda name: install.Step(name, True, "ok")
            failed = install.Step("acquire[build]", False, "clone failed: no such tag")

            with mock.patch.object(gui.port, "materialise", return_value=materialised), \
                 mock.patch.object(gui.install, "ensure_python_env", return_value=good("python-env")), \
                 mock.patch.object(gui.install, "install_ki_tools_common", return_value=good("ki-tools-common")), \
                 mock.patch.object(gui.install, "check_system_deps", return_value=good("system-deps")), \
                 mock.patch.object(gui.install, "install_python_deps", return_value=good("python-deps")), \
                 mock.patch.object(gui.install, "acquire", return_value=(failed, None)), \
                 mock.patch.object(gui.install, "check_data", return_value=good("data")), \
                 mock.patch.object(gui.handoff, "write", return_value=[]):
                gui.run_install(ki, man, root / "work", emitted.append, root)

            status = json.loads((root / "work" / "status.json").read_text())
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

            installed = (target / "ki_tools_common" / "__init__.py").read_text()
            self.assertIn(str(cfg.roles["outputs"]), installed)

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

    def test_api_setup_command_inherits_its_provider_proxy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki_root = root / "ki"
            ki_root.mkdir()
            cfg = SimpleNamespace(
                root=root, python=sys.executable,
                roles={"binaries": root / "binaries"},
            )
            completed = subprocess.CompletedProcess(
                ["git", "--version"], 0, stdout="git version test\n", stderr="")

            def routed(provider, env):
                self.assertEqual(provider, "api:deepseek")
                return {**env, "HTTPS_PROXY": "http://127.0.0.1:7897"}

            with mock.patch.object(
                    settings, "with_provider_proxy", side_effect=routed) as route, \
                 mock.patch.object(api.subprocess, "run", return_value=completed) as run:
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

    def test_agent_final_preflight_becomes_the_saved_verification_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ki = SimpleNamespace(name="Demo", meta={"version": "1.0"})
            check = SimpleNamespace(
                ok=True, detail="1 passed, 0 failed", commands=["check Demo"])
            with mock.patch.object(install, "run_preflight", return_value=check), \
                 mock.patch.object(setup, "clear_request"):
                ok = gui.Handler._record_agent_preflight(
                    None, ki, ki, SimpleNamespace(python=sys.executable),
                    root, lambda _piece: True,
                )
            status = json.loads((root / "status.json").read_text())
            self.assertTrue(ok)
            self.assertTrue(status["ok"])
            self.assertTrue(status["agent_setup"])
            self.assertIsNotNone(status["verified_at"])
            self.assertEqual(status["steps"][-1]["name"], "preflight")

    def test_wrf_hydro_manifest_uses_real_release_and_separates_project_data(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "WRF_Hydro.yaml")
        self.assertEqual(manifest.acquire.ref, "v5.2.0")
        self.assertEqual(manifest.install_dir, "wrf_hydro/source")
        self.assertIn("mpif90", manifest.system_deps)
        self.assertIn("nf-config", manifest.system_deps)
        self.assertEqual(manifest.data, [])
        preflight = (Path(__file__).parents[2] / "models" / "WRF_Hydro" /
                     "preflight_check.py").read_text()
        self.assertNotIn('check_dir("KISSPATH_FORCING"', preflight)

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

    def test_dssat_runtime_source_fixes_are_idempotent(self):
        manifest = Manifest.load(
            Path(__file__).parents[1] / "manifests" / "DSSAT.yaml")
        patch_commands = manifest.acquire.commands[:2]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            nitrogen = root / "Soil" / "Inorganic_N" / "OPSOILNI.for"
            water = root / "Soil" / "SoilWater" / "OPSWBL.for"
            nitrogen.parent.mkdir(parents=True)
            water.parent.mkdir(parents=True)
            nitrogen.write_text(
                "'(T',SPACES,'X,\"Total Inorganic N @dep(ppm):\")'\n")
            water.write_text("FORMAT(X,I4,1X,I3.3,1X,I5,1X\n & 5(20(F8.4)))\n")

            for _ in range(2):
                for command in patch_commands:
                    subprocess.run(command, cwd=root, shell=True, check=True)

            self.assertIn(
                "',\"Total Inorganic N @dep(ppm):\")'", nitrogen.read_text())
            fixed_water = water.read_text()
            self.assertIn("I5,1X,\n", fixed_water)
            self.assertNotIn("I5,1X,,", fixed_water)

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
            ki_root = project / "models" / "Demo"
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
            cfg = SimpleNamespace(
                root=project, python=sys.executable,
                roles={"ki_tools_common": common, "binaries": binaries})
            ki = SimpleNamespace(root=ki_root)

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
    @staticmethod
    def _package(*, valid: bool = True) -> bytes:
        doc = io.BytesIO()
        with zipfile.ZipFile(doc, "w") as z:
            z.writestr("Demo/SKILL.md", "# Demo KI\n")
            if valid:
                z.writestr("Demo/preflight_check.py", "print('ok')\n")
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


if __name__ == "__main__":
    unittest.main()
