"""New setup prepares declared data before verification; existing discovery never fetches."""
import hashlib
import json

import pytest
from kiss_cli import gui, install, runtime_data
from .test_setup_projection_binding import case


@pytest.mark.parametrize('mode,engine_ok',[('new',True),('new',False),('existing',True)])
def test_gui_setup_data_acquisition_follows_engine_and_requires_explicit_existing_action(case,monkeypatch,mode,engine_ok):
    c=case;payload=b'! Native support table\n';events=[]
    c.man.runtime_data={'version':1,'source':{'repo':'https://example.invalid/official.git','commit':'a'*40},
      'target':{'role':'binaries','path':'Demo/Data'},'files':[{'source':'Data/TABLE.CDE','path':'TABLE.CDE','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]}
    def engine(*a,**kw):events.append('engine');return install.Step('acquire',engine_ok,'fixture engine'),None
    monkeypatch.setattr(install,'acquire',engine)
    def placement(*a,**kw):events.append('existing');return {'state':'placed','notes':[],'managed_binary':str(c.root/'binaries/Demo/bin/model')}
    monkeypatch.setattr(gui,'_place_selected_existing_install',placement)
    def prepare(man,cfg,*,allow_acquire,env=None):
        events.append(('data',allow_acquire))
        if allow_acquire:
            target=cfg.roles['binaries']/'Demo/Data/TABLE.CDE';target.parent.mkdir(parents=True);target.write_bytes(payload)
        return runtime_data.check(man,cfg)
    monkeypatch.setattr(runtime_data,'prepare',prepare)
    original=install.run_preflight
    def check(*a,**kw):events.append('preflight');return original(*a,**kw)
    monkeypatch.setattr(install,'run_preflight',check)
    gui.run_install(c.ki,c.man,c.root,lambda _:None,c.library,installation_mode=mode,existing_path='fixture')
    status=json.loads((c.root/'status.json').read_text())
    if not engine_ok:
        assert events==['engine'] and not status['ok']
    elif mode=='existing':
        assert events==['existing',('data',False)] and not status['ok']
    else:
        assert events==['engine',('data',True),'preflight'] and status['ok']
