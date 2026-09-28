"""Replay CLI events through the real streaming loop, without a live agent."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest import mock

from kiss_cli import calibration, gui, providers, settings


def tool_call(call_id="query-1", name="Bash", command='geoforge-db "soil attribute table" --limit 10'):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": call_id, "name": name,
         "input": {"command": command}},
    ]}}


def tool_result(call_id="query-1", *, failed=False):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": call_id,
         "is_error": failed, "content": "fixture result"},
    ]}}


class CLIActivityLifecycleTests(unittest.TestCase):
    def replay(self, frames, *, output="stream-json"):
        events, snapshots, clock = {}, [], [100.0]

        class Stream:
            def __iter__(self):
                for at, event in frames:
                    clock[0] = at
                    yield (json.dumps(event) if isinstance(event, dict) else event) + "\n"
                    snapshots.append(copy.deepcopy(events["process"]))

            def close(self):
                pass

        provider = providers.Provider(
            name="claude", binary="claude", label="Claude Code",
            argv=["claude", "-p", "{prompt}"], output=output,
        )
        proc = mock.Mock(pid=1001, stdin=None, stdout=Stream())
        proc.wait.return_value = 0
        with mock.patch.object(provider, "health", return_value=providers.ProviderHealth(
                True, True, "fixture")), \
             mock.patch.object(provider, "path", return_value="/fixture/claude"), \
             mock.patch.object(settings, "with_provider_proxy", return_value={}), \
             mock.patch.object(calibration, "with_framework_env", return_value={}), \
             mock.patch.object(providers.subprocess, "Popen", return_value=proc), \
             mock.patch.object(providers.time, "time", side_effect=lambda: clock[0]):
            chunks = list(providers.run(
                provider, "fixture", Path("/tmp"), runtime_events=events))
        return snapshots, chunks

    def test_matching_result_stops_claiming_completed_query_is_active(self):
        states, _ = self.replay([(101, tool_call()), (104, tool_result())])
        self.assertEqual(states[0]["activity_state"], "tool_running")
        self.assertEqual(states[1]["activity_state"], "tool_finished")
        self.assertFalse(states[1].get("activity_detail"))
        self.assertNotEqual(states[1].get("activity"), "Bash")
        self.assertEqual(states[1]["last_activity_name"], "Bash")
        self.assertIn("soil attribute table", states[1]["last_activity_detail"])
        self.assertEqual(states[1]["last_work_at"], 104)

    def test_failed_result_is_completion_not_a_still_running_query(self):
        states, _ = self.replay([(101, tool_call()), (104, tool_result(failed=True))])
        self.assertEqual(states[-1]["activity_state"], "tool_finished")
        self.assertNotEqual(states[-1].get("activity"), "Bash")

    def test_unmatched_result_does_not_complete_active_tool_or_refresh_work(self):
        states, _ = self.replay([(101, tool_call()), (180, tool_result("different-id"))])
        self.assertEqual(states[-1]["activity_state"], "tool_running")
        self.assertEqual(states[-1]["activity"], "Bash")
        self.assertEqual(states[-1]["last_work_at"], 101)
        self.assertEqual(states[-1]["last_event_at"], 180)

    def test_ping_and_usage_do_not_refresh_meaningful_work_or_action_start(self):
        states, _ = self.replay([
            (101, tool_call()), (190, {"type": "ping"}),
            (200, {"type": "system", "subtype": "usage", "usage": {"input_tokens": 5}}),
        ])
        self.assertEqual(states[-1]["last_event_at"], 200)
        self.assertEqual(states[-1]["last_work_at"], 101)
        self.assertEqual(states[-1]["activity_started_at"], 101)

    def test_transport_text_and_echoed_user_text_do_not_refresh_work(self):
        states, _ = self.replay([
            (101, tool_call()), (190, {"type": "ping", "text": "still connected"}),
            (200, {"type": "user", "message": {"content": [
                {"type": "text", "text": "echoed input"}]}}),
        ])
        self.assertEqual(states[-1]["last_work_at"], 101)
        self.assertEqual(states[-1]["activity_state"], "tool_running")

    def test_unknown_provider_completion_shape_is_not_guessed(self):
        states, _ = self.replay([
            (101, {"role": "assistant", "tool_calls": [{"id": "kimi-call", "function": {
                "name": "Shell", "arguments": '{"command":"geoforge-db soil"}'}}]}),
            (104, {"role": "tool", "tool_call_id": "kimi-call", "content": "fixture"}),
            (106, {"role": "assistant", "content": "I can continue planning."}),
        ])
        self.assertEqual(states[0]["activity_state"], "unknown")
        self.assertEqual(states[1]["activity_state"], "unknown")
        self.assertEqual(states[1]["last_work_at"], 101)
        self.assertEqual(states[2]["activity_state"], "responding")

    def test_parallel_tool_completion_preserves_remaining_active_call(self):
        starts = tool_call("one", command="first-query")
        starts["message"]["content"] += tool_call("two", "Read", "second-query")["message"]["content"]
        states, _ = self.replay([
            (101, starts), (103, tool_result("two")), (104, tool_result("one")),
        ])
        self.assertEqual(states[0]["activity"], "Read")
        self.assertEqual(states[1]["activity"], "Bash")
        self.assertEqual(states[1]["activity_detail"], "first-query")
        self.assertEqual(states[1]["activity_started_at"], 101)
        self.assertEqual(states[2]["activity_state"], "tool_finished")

    def test_text_and_tool_in_one_frame_retains_active_tool(self):
        event = tool_call()
        event["message"]["content"].insert(0, {"type": "text", "text": "Looking up soil now."})
        states, chunks = self.replay([(101, event)])
        self.assertIn("Looking up soil now.", "".join(chunks))
        self.assertEqual(states[0]["activity_state"], "tool_running")
        self.assertEqual(states[0]["activity"], "Bash")

    def test_text_after_completion_marks_response_and_keeps_last_action(self):
        states, _ = self.replay([
            (101, tool_call()), (104, tool_result()),
            (110, {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "I found the soil table."}]}}),
        ])
        self.assertEqual(states[-1]["activity_state"], "responding")
        self.assertEqual(states[-1]["last_work_at"], 110)
        self.assertEqual(states[-1]["last_activity_name"], "Bash")

    def test_idless_tool_is_observation_without_invented_completion(self):
        event = tool_call()
        del event["message"]["content"][0]["id"]
        states, _ = self.replay([(101, event), (104, tool_result())])
        self.assertEqual(states[-1]["activity_state"], "unknown")
        self.assertEqual(states[-1]["activity"], "Bash")
        self.assertEqual(states[-1]["last_work_at"], 101)

    def test_duplicate_tool_start_does_not_restart_action_clock(self):
        states, _ = self.replay([(101, tool_call()), (190, tool_call())])
        self.assertEqual(states[-1]["activity_started_at"], 101)
        self.assertEqual(states[-1]["last_work_at"], 101)

    def test_preserved_action_details_use_existing_redaction(self):
        states, _ = self.replay([
            (101, tool_call(command="lookup --token fixture-secret password=fixture-password")),
            (104, tool_result()),
        ])
        summary = json.dumps(states[-1])
        self.assertNotIn("fixture-secret", summary)
        self.assertNotIn("fixture-password", summary)
        self.assertIn("[redacted]", summary)

    def test_text_only_provider_records_response_without_inventing_tools(self):
        states, _ = self.replay([(101, "Preparing a plan."), (105, "Data found.")], output="text")
        self.assertEqual(states[-1]["activity_state"], "responding")
        self.assertEqual(states[-1]["last_work_at"], 105)
        self.assertEqual(states[-1]["activity_started_at"], 101)


class AgentActivitySnapshotTests(unittest.TestCase):
    def test_startup_and_api_heartbeat_do_not_invent_a_first_work_event(self):
        session_id = "activity-first-event-fixture"
        for process in ({"state": "running", "started_at": 100, "last_event_at": 299}, None):
            with self.subTest(process=process), mock.patch.object(gui.time, "time", return_value=300):
                gui._register_agent_run(session_id, {"provider": "fixture"})
                with gui._LIVE_AGENT_RUNS_LOCK:
                    if process is not None:
                        gui._LIVE_AGENT_RUNS[session_id]["process"] = process
                try:
                    result = gui._agent_run_snapshot(session_id)
                finally:
                    with gui._LIVE_AGENT_RUNS_LOCK:
                        gui._LIVE_AGENT_RUNS.pop(session_id, None)
                self.assertFalse(result["work_observed"])

    def test_snapshot_separates_recent_ping_from_old_tool_work(self):
        session_id = "activity-lifecycle-fixture"
        with mock.patch.object(gui.time, "time", return_value=300):
            gui._register_agent_run(session_id, {"provider": "cli:claude"})
            with gui._LIVE_AGENT_RUNS_LOCK:
                gui._LIVE_AGENT_RUNS[session_id]["process"] = {
                    "state": "running", "started_at": 100,
                    "last_event_at": 299, "last_output_at": 110, "last_work_at": 110,
                    "activity": "Bash", "activity_detail": "geoforge-db soil",
                    "activity_state": "tool_running", "activity_started_at": 110,
                    "last_activity_name": "Bash", "last_activity_detail": "geoforge-db soil",
                }
            try:
                result = gui._agent_run_snapshot(session_id)
            finally:
                with gui._LIVE_AGENT_RUNS_LOCK:
                    gui._LIVE_AGENT_RUNS.pop(session_id, None)
        self.assertEqual(result["event_silence_seconds"], 1)
        self.assertEqual(result["work_silence_seconds"], 190)
        self.assertEqual(result["activity_elapsed_seconds"], 190)
        self.assertEqual(result["elapsed_seconds"], 200)
        self.assertEqual(result["activity_state"], "tool_running")
        self.assertEqual(result["last_activity_detail"], "geoforge-db soil")


if __name__ == "__main__":
    unittest.main()
