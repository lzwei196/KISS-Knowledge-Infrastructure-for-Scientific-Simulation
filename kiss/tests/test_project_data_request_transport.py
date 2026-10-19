"""Many precise inputs keep the same read authority without argv-size limits."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from kiss_cli import execution, project_data_tools
from .test_project_data_tools import case, approve, run


def test_many_precise_inputs_launch_and_are_receipted(tmp_path, monkeypatch):
    source = '''import json
from pathlib import Path
files = sorted(Path('inputs/daily').glob('*.txt'))
total = sum(int(p.read_text()) for p in files)
out = Path('outputs/inspection.json')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({'file_count':len(files),'total':total}))
'''
    c = case(tmp_path, source)
    raw = c[1] / 'inputs/daily'
    raw.mkdir()
    for index in range(220):
        (raw / (('meteorological_input_' + str(index).zfill(4) + '_') + 'x'*50 + '.txt')).write_text(str(index))
    c[4]['items'][0]['local_paths'] = ['inputs/daily']
    c[3]['steps'][0]['project_data_tool']['arguments'] = []
    request = project_data_tools.worker_request(c[1], Path(c[5]['tool']), c[3]['steps'][0], c[4], [])
    assert len(project_data_tools.encode_worker_request(request)) > 20000
    original = execution.run_process
    captures = []
    def observe(command, **kwargs):
        payload = kwargs['stdin'].read()
        kwargs['stdin'].seek(0)
        assert command[-2] == '--request-stdin-v1'
        assert command[-1] == hashlib.sha256(payload).hexdigest()
        assert len(' '.join(command)) < 4000
        captures.append(json.loads(payload))
        return original(command, **kwargs)
    monkeypatch.setattr(execution, 'run_process', observe)
    approve(c)
    result = run(c)
    assert result.startswith('exit_code=0'), result
    assert len(captures) == 1 and len(captures[0]['input_files']) == 220
    assert json.loads((c[1]/'outputs/inspection.json').read_text()) == {'file_count':220,'total':sum(range(220))}
    receipts = list((c[1]/'.geoforge/receipts/model-runs').glob('*.json'))
    assert len(receipts) == 1
    assert len(json.loads(receipts[0].read_text())['inputs']) >= 220


@pytest.mark.parametrize('fault', ['digest', 'oversize', 'bad_json', 'not_object'])
def test_bad_transport_rejected_before_source_runs(tmp_path, fault):
    worker = Path(execution.__file__).with_name('_project_data_worker.py')
    source = tmp_path/'must_not_run.py'
    marker = tmp_path/'executed'
    source.write_text("from pathlib import Path\nPath('executed').write_text('bad')\n")
    payload = b'{}'
    if fault == 'oversize':
        payload = b' '*(project_data_tools.MAX_WORKER_REQUEST_BYTES + 1)
    elif fault == 'bad_json':
        payload = b'{'
    elif fault == 'not_object':
        payload = b'[]'
    digest = '0'*64 if fault == 'digest' else hashlib.sha256(payload).hexdigest()
    result = subprocess.run([sys.executable,'-I','-S',str(worker),str(source),'--request-stdin-v1',digest],
                            input=payload,cwd=tmp_path,capture_output=True,timeout=15)
    assert result.returncode != 0
    assert not marker.exists()


def test_host_transport_limit_counts_utf8_bytes():
    with pytest.raises(ValueError, match='8 MiB'):
        project_data_tools.encode_worker_request({'grant': '测'*(project_data_tools.MAX_WORKER_REQUEST_BYTES//3)})


def test_transport_does_not_expand_input_read_grants(tmp_path):
    c = case(tmp_path, "from pathlib import Path\nPath('inputs/undeclared.txt').read_text()\n")
    (c[1]/'inputs/undeclared.txt').write_text('not approved')
    approve(c)
    result = run(c)
    assert 'exit_code=1' in result and 'outside approved inputs' in result
