"""Real provider-loop stop metadata without recording prompts or credentials."""
import json
import os
from types import SimpleNamespace

import pytest

from kiss_cli import api, provider_diagnostics as pd


def rows(project):
    return [json.loads(line) for line in (project / pd.LOG).read_text(encoding='utf-8').splitlines()]


def test_metadata_only_redaction_and_bounded_rotation(tmp_path, monkeypatch):
    monkeypatch.setattr(pd, 'MAX_BYTES', 8192)
    for i in range(60):
        pd.record(tmp_path, 'tool_result', step=i, error='ERROR: token=private-secret https://example.test/?key=secret',
                  arguments={'secret': 'DO_NOT_CAPTURE'}, prompt='PRIVATE_PROMPT', result='PRIVATE_RESULT')
    current = tmp_path / pd.LOG
    backup = current.with_suffix('.previous.jsonl')
    assert current.stat().st_size <= 8192 and backup.stat().st_size <= 8192
    combined = current.read_text() + backup.read_text()
    assert 'private-secret' not in combined and 'example.test' not in combined
    assert 'DO_NOT_CAPTURE' not in combined and 'PRIVATE_PROMPT' not in combined
    assert 'PRIVATE_RESULT' not in combined
    assert rows(tmp_path)[-1]['step'] == 59


def test_hardlinked_log_is_not_followed(tmp_path):
    target = tmp_path / 'unrelated.txt'; target.write_text('preserve')
    (tmp_path / pd.LOG.parent).mkdir()
    os.link(target, tmp_path / pd.LOG)
    pd.record(tmp_path, 'turn_end', reason='test')
    assert target.read_text() == 'preserve'


def test_logging_failure_does_not_change_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(pd.time, 'time', lambda: (_ for _ in ()).throw(OSError('disk error')))
    pd.record(tmp_path, 'turn_end', reason='test')
    assert not (tmp_path / pd.LOG).exists()


@pytest.mark.parametrize('wire,finish', [('openai', 'length'), ('anthropic', 'max_tokens')])
def test_output_limit_is_recorded_and_not_marked_normal_final(tmp_path, monkeypatch, wire, finish):
    monkeypatch.setenv('DIAG_TEST_KEY', 'not-for-log')
    prov = api.ApiProvider('diag', 'Diag', wire, 'https://invalid.example', 'DIAG_TEST_KEY', {'m': 'm'}, 'm')
    response = ({'choices': [{'message': {'role': 'assistant', 'content': 'partial answer'}, 'finish_reason': finish}]}
                if wire == 'openai' else {'content': [{'type': 'text', 'text': 'partial answer'}], 'stop_reason': finish})
    monkeypatch.setattr(api, '_post', lambda *a, **k: response)
    monkeypatch.setattr(api, 'tool_schemas', lambda *a, **k: [])
    flow = SimpleNamespace(project=tmp_path, state=SimpleNamespace(value='EXECUTING'), approval_id='approval1')
    result = ''.join(api.run(prov, SimpleNamespace(), SimpleNamespace(root=tmp_path), 'PRIVATE_SYSTEM',
        'PRIVATE_TASK', project_mode=True, flow=flow, setup_context={'_turn_id': 'turn1'}))
    assert flow.provider_succeeded is False and 'output limit' in result
    data = rows(tmp_path)
    assert data[-1]['reason'] == 'output_limit'
    assert data[-2]['finish_reason'] == finish
    assert all(row['turn_id'] == 'turn1' for row in data)
    assert 'PRIVATE' not in (tmp_path / pd.LOG).read_text()
    assert 'not-for-log' not in (tmp_path / pd.LOG).read_text()


def test_streamed_anthropic_stop_reason_is_preserved():
    data = api._assemble_anthropic(iter([
        {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': 'partial'}},
        {'type': 'message_delta', 'delta': {'stop_reason': 'max_tokens'}},
        {'type': 'message_stop'},
    ]))
    assert data['stop_reason'] == 'max_tokens'
    assert data['content'] == [{'type': 'text', 'text': 'partial'}]


@pytest.mark.parametrize('tool', ['read_project_file', 'run_ki_tool'])
def test_tool_failure_records_name_without_arguments(tmp_path, monkeypatch, tool):
    monkeypatch.setenv('DIAG_TEST_KEY', 'not-for-log')
    prov = api.ApiProvider('diag', 'Diag', 'openai', 'https://invalid.example', 'DIAG_TEST_KEY', {'m': 'm'}, 'm')
    responses = iter([
        {'choices': [{'message': {'role': 'assistant', 'content': '', 'tool_calls': [
            {'id': 'c1', 'function': {'name': tool, 'arguments': '{"path":"PRIVATE_PATH"}'}}]}, 'finish_reason': 'tool_calls'}]},
        {'choices': [{'message': {'role': 'assistant', 'content': 'ended'}, 'finish_reason': 'stop'}]},
    ])
    monkeypatch.setattr(api, '_post', lambda *a, **k: next(responses))
    monkeypatch.setattr(api, 'tool_schemas', lambda *a, **k: [])
    monkeypatch.setattr(api, 'execute_tool', lambda *a, **k: 'ERROR: file missing')
    flow = SimpleNamespace(project=tmp_path, state=SimpleNamespace(value='EXECUTING'), approval_id='approval1')
    ''.join(api.run(prov, SimpleNamespace(), SimpleNamespace(root=tmp_path), 'system', 'task', project_mode=True, flow=flow))
    data = rows(tmp_path)
    row = next(r for r in data if r['event'] == 'tool_result')
    assert row['tool'] == tool and row['error'] == 'ERROR: file missing'
    assert row['blocked'] is (tool == 'run_ki_tool')
    assert 'PRIVATE_PATH' not in (tmp_path / pd.LOG).read_text()
    assert data[-1]['reason'] == 'provider_final'
