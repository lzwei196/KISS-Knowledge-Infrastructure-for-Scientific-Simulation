"""Same-source required data can strengthen a reviewed portable repair.

KDT seals in lifecycle fixtures are synthetic acceptance-boundary test doubles;
these tests neither perform scientific KDT review nor execute a model.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from kiss_cli import ki_adaptations as adapt,ki_copy,ki_guard,kdtstudio,paths,port,runtime_data
from kiss_cli import ki_verification,project_verification
from kiss_cli.catalog import KI
from kiss_cli.manifest import Manifest,document
from .test_ki_adaptations import prepare_helpers,accepted,fresh


def _recipe():
    return {'kiss_manifest_version':1,'model':'Demo','install_dir':'Demo','binary_type':'ELF',
      'acquire':{'strategy':'build','repo':'https://example.invalid/official.git','ref':'a'*40,
                 'commands':['build existing reviewed source'],'produces':'build/model'},
      'python_deps':['numpy'],'system_deps':['git']}


def _contract(recipe=None):
    recipe=recipe or _recipe();payload=b'Official support table\nA 1\n'
    return {'version':1,'source':{'repo':recipe['acquire']['repo'],'commit':recipe['acquire']['ref']},
      'target':{'role':'home','path':recipe['install_dir']+'/Data'},
      'files':[{'source':'Data/MODEL.ERR','path':'MODEL.ERR','bytes':len(payload),
                'sha256':hashlib.sha256(payload).hexdigest(),'text_newlines':'lf_or_crlf'}]}


def _write(root,value):
    root.mkdir(parents=True,exist_ok=True)
    (root/'kiss.yaml').write_text(yaml.safe_dump(value,sort_keys=False),encoding='utf-8')


def _compare(tmp_path,before,after):
    base,candidate=tmp_path/'before',tmp_path/'after';_write(base,before);_write(candidate,after)
    return adapt._same_recipe(base,candidate,'Demo')


def test_exact275_file_dssat_declaration_strengthens_same_pinned_recipe(tmp_path):
    path=Path(__file__).parents[1]/'manifests/DSSAT.yaml'
    base=yaml.safe_load(path.read_text(encoding='utf-8'))
    declared=json.loads((Path(__file__).parent/'fixtures/dssat-runtime-data-contract.json').read_text(encoding='utf-8'))
    assert len(declared['files'])==275
    assert declared['source']['repo']==base['acquire']['repo']
    assert declared['source']['commit']==base['acquire']['ref']=='40793f8d654ca033d027ec3a6cea53cf2f546602'
    before=tmp_path/'before';candidate=tmp_path/'after'
    _write(before,base);_write(candidate,dict(base,runtime_data=declared))
    assert adapt._same_recipe(before,candidate,'DSSAT') is None
    assert Manifest.load(before/'kiss.yaml').runtime_data is None


@pytest.mark.parametrize('role',['home','binaries'])
def test_same_source_relative_mapping_is_supported_in_declared_install_role(tmp_path,role):
    base=_recipe();after=deepcopy(base);after['runtime_data']=_contract();after['runtime_data']['target']['role']=role
    assert _compare(tmp_path,base,after) is None


@pytest.mark.parametrize('change',[
    'repo','commit','branch-ref','short-ref','strategy','install-dir','blank-install-dir',
    'binary','produces','commands','python','system','coupled','model','notes','existing-data',
    'target-outside','target-sibling-prefix','target-root','target-parent','target-role',
    'source-map','source-case','source-outside','destination-map','invalid-hash','invalid-size',
    'duplicate','unknown-contract','unbounded-install-dir','uppercase-ref','repo-alias',
    'absolute-install-dir','windows-install-dir','source-dot-alias',
])
def test_other_recipe_changes_or_inapplicable_contracts_require_separate_review(tmp_path,change):
    base=_recipe();after=deepcopy(base);after['runtime_data']=_contract()
    c=after['runtime_data']
    if change=='repo':c['source']['repo']='https://example.invalid/different.git'
    elif change=='commit':c['source']['commit']='b'*40
    elif change=='branch-ref':base['acquire']['ref']=after['acquire']['ref']='main'
    elif change=='short-ref':base['acquire']['ref']=after['acquire']['ref']='a'*7
    elif change=='uppercase-ref':base['acquire']['ref']=after['acquire']['ref']='A'*40
    elif change=='repo-alias':c['source']['repo']='https://EXAMPLE.invalid/official.git'
    elif change=='strategy':base['acquire']['strategy']=after['acquire']['strategy']='manual'
    elif change=='install-dir':after['install_dir']='Other'
    elif change=='blank-install-dir':base['install_dir']=after['install_dir']=''
    elif change=='unbounded-install-dir':base['install_dir']=after['install_dir']='../Demo'
    elif change=='absolute-install-dir':base['install_dir']=after['install_dir']='/Demo'
    elif change=='windows-install-dir':base['install_dir']=after['install_dir']='C:\\Demo'
    elif change=='binary':after['binary_type']='PE32'
    elif change=='produces':after['acquire']['produces']='other/model'
    elif change=='commands':after['acquire']['commands']=['other build']
    elif change=='python':after['python_deps'].append('other-package')
    elif change=='system':after['system_deps'].append('other-compiler')
    elif change=='coupled':after['depends_on']=['AnotherKI']
    elif change=='model':after['model']='Different'
    elif change=='notes':after['notes']='Different effective recipe'
    elif change=='existing-data':after['data']=[{'role':'forcing','name':'new-input'}]
    elif change=='target-outside':c['target']['path']='Other/Data'
    elif change=='target-sibling-prefix':c['target']['path']='Demo-other/Data'
    elif change=='target-root':c['target']['path']='Demo'
    elif change=='target-parent':c['target']['path']='Demo/../Data'
    elif change=='target-role':c['target']['role']='outputs'
    elif change=='source-map':c['files'][0]['source']='Different/MODEL.ERR'
    elif change=='source-dot-alias':c['files'][0]['source']='Data/./MODEL.ERR'
    elif change=='source-case':c['files'][0]['source']='data/MODEL.ERR'
    elif change=='source-outside':c['files'][0]['source']='../Data/MODEL.ERR'
    elif change=='destination-map':c['files'][0]['path']='elsewhere/MODEL.ERR'
    elif change=='invalid-hash':c['files'][0]['sha256']='bad'
    elif change=='invalid-size':c['files'][0]['bytes']=0
    elif change=='duplicate':c['files'].append(deepcopy(c['files'][0]))
    else:c['extra']=True
    with pytest.raises(ValueError):_compare(tmp_path,base,after)


@pytest.mark.parametrize('change',['remove','new-commit','new-file','changed-hash','new-role'])
def test_existing_runtime_contract_cannot_be_removed_or_replaced(tmp_path,change):
    base=dict(_recipe(),runtime_data=_contract());after=deepcopy(base)
    if change=='remove':after.pop('runtime_data')
    elif change=='new-commit':after['runtime_data']['source']['commit']='b'*40
    elif change=='new-file':after['runtime_data']['files'].append(dict(after['runtime_data']['files'][0],source='Data/OTHER',path='OTHER'))
    elif change=='changed-hash':after['runtime_data']['files'][0]['sha256']='b'*64
    else:after['runtime_data']['target']['role']='binaries'
    with pytest.raises(adapt.AdaptationError,match='effective installation recipe'):_compare(tmp_path,base,after)


@pytest.mark.parametrize('declared',[False,True])
def test_unchanged_recipes_still_pass(tmp_path,declared):
    base=_recipe()
    if declared:base['runtime_data']=_contract()
    assert _compare(tmp_path,base,deepcopy(base)) is None


@pytest.fixture
def lifecycle(tmp_path,monkeypatch):
    monkeypatch.setenv('GEOFORGE_KI_ADAPTATION_HOME',str(tmp_path/'adaptations'))
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS',str(tmp_path/'keys'))
    monkeypatch.delenv('GEOFORGE_KDT_ENGINE',raising=False)
    monkeypatch.setattr(kdtstudio,'engine_source_digest',lambda:'e'*64)
    library=tmp_path/'library';source=library/'models/Demo';_write(source,_recipe())
    (source/'SKILL.md').write_text('# Portable fixture\n')
    (source/'reader.py').write_text("output = 'KISSPATH_OUTPUTS/result.txt'\ndef read(): return 1\n")
    (source/'preflight_check.py').write_text("raise SystemExit('Model never executed by adaptation')\n")
    helpers=library/'ki_tools_common';helpers.mkdir();(helpers/'helper.py').write_text('VALUE = 1\n')
    prepared_helpers=tmp_path/'prepared-helpers';prepare_helpers(library,prepared_helpers)
    ki_guard.enroll(source)
    c=SimpleNamespace(base=tmp_path,source=source,library=library,manifest=Manifest.load(source/'kiss.yaml'),helpers=prepared_helpers)
    c.live,c.cfg=fresh(c,'project-a');origin=adapt.projection(c.live,c.cfg)
    portable=tmp_path/'portable';ki_copy.copytree(Path(origin['portable_root']),portable)
    _write(portable,dict(_recipe(),runtime_data=_contract()))
    runtime=tmp_path/'runtime';port.materialise(portable,runtime,c.cfg)
    c.portable,c.runtime,c.origin=portable,runtime,origin
    return c


def _prepare(c):
    return adapt.prepare_registration(c.live,c.cfg,c.portable,accepted(c.portable),c.runtime,accepted(c.runtime))


def _adopt(c):
    ticket=_prepare(c)
    ki_guard.activate(c.live,c.runtime,ticket['runtime_report'],quiescent=True)
    return adapt.register(ticket,c.live,c.cfg)


def test_register_and_same_source_reuse_keep_original_context_and_new_data_obligation(lifecycle):
    c=lifecycle;record=_adopt(c)
    assert record['context']==c.origin['context']
    assert record['context']['effective_manifest_digest']==adapt._hash(document(c.manifest))
    assert adapt._hash(document(Manifest.load(c.portable/'kiss.yaml')))!=record['context']['effective_manifest_digest']
    second,cfg=fresh(c,'project-b')
    projected=adapt.projection(second,cfg)
    assert projected['adaptation_id']==record['adaptation_id'] and not projected['reconciliation_needed']
    man=Manifest.load(second/'kiss.yaml');assert man.runtime_data==_contract()
    assert not runtime_data.check(man,cfg).ok
    assert not project_verification.status(cfg.root,KI('Demo',second))['can_run']
    assert Manifest.load(c.source/'kiss.yaml').runtime_data is None


@pytest.mark.parametrize('change',['upstream','recipe','helper'])
def test_changed_upstream_recipe_or_helper_does_not_replay_stronger_contract(lifecycle,change):
    c=lifecycle;record=_adopt(c)
    alt=c.base/'next-source';ki_copy.copytree(c.library,alt);manifest=c.manifest
    if change=='upstream':(alt/'models/Demo/new.txt').write_text('Updated upstream')
    elif change=='recipe':
        changed=_recipe();changed['acquire']['ref']='b'*40;_write(alt/'models/Demo',changed)
        manifest=Manifest.load(alt/'models/Demo/kiss.yaml')
    else:
        (alt/'ki_tools_common/helper.py').write_text('VALUE = 2\n');c.helpers=c.base/'new-helpers'
        prepare_helpers(alt,c.helpers)
    second,cfg=fresh(c,'project-b',source=alt/'models/Demo',library=alt,manifest=manifest)
    assert Manifest.load(second/'kiss.yaml').runtime_data is None
    p=adapt.projection(second,cfg);assert p['adaptation_id'] is None and p['reconciliation_needed']
    assert Manifest.load(c.live/'kiss.yaml').runtime_data==_contract()


@pytest.mark.parametrize('failure',['portable-gate','runtime-gate','projection','pre-adoption'])
def test_data_contract_does_not_bypass_kdt_projection_or_adoption(lifecycle,failure):
    c=lifecycle;portable=accepted(c.portable);runtime=accepted(c.runtime)
    if failure=='portable-gate':portable['ok']=False
    elif failure=='runtime-gate':runtime['ok']=False
    elif failure=='projection':(c.runtime/'extra.txt').write_text('Not a portable projection');runtime=accepted(c.runtime)
    if failure=='pre-adoption':
        ticket=_prepare(c)
        with pytest.raises(adapt.AdaptationError,match='not been adopted'):adapt.register(ticket,c.live,c.cfg)
    else:
        with pytest.raises(ValueError):adapt.prepare_registration(c.live,c.cfg,c.portable,portable,c.runtime,runtime)
    assert Manifest.load(c.live/'kiss.yaml').runtime_data is None
    assert not list((adapt._home()/'registry').glob('*.json'))
