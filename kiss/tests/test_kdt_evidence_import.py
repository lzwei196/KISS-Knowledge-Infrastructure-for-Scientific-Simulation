"""Evidence copies preserve bytes and clean only the destination this attempt owns."""
from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from kiss_cli import kdtstudio,ki_guard


@pytest.fixture
def job(tmp_path,monkeypatch):
    engine=tmp_path/'engine'
    for name in kdtstudio.REQUIRED_ENGINE_FILES:
        path=engine/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('')
    source=tmp_path/'source';source.mkdir();(source/'README.md').write_text('source')
    parent=tmp_path/'workspaces';parent.mkdir()
    monkeypatch.setenv('GEOFORGE_KDT_HOME',str(tmp_path/'data'))
    monkeypatch.setenv('GEOFORGE_KDT_ENGINE',str(engine))
    monkeypatch.setenv('GEOFORGE_KI_VERIFICATION_HOME',str(tmp_path/'host-verification'))
    monkeypatch.setenv('GEOFORGE_FLOW_KEYS',str(tmp_path/'host-keys'))
    result=kdtstudio.create_job(model_name='Import Test',domain='crop',source_type='local',source=str(source),parent=str(parent))
    return SimpleNamespace(id=result['id'],root=Path(result['root']),base=tmp_path)


def _meta(job):
    return kdtstudio._meta(job.id)[1].copy()


def test_nested_git_pack_long_windows_destination_preserves_binary_bytes(job):
    source=job.base/('official-repository-'+('x'*55));source.mkdir()
    relative=Path('.git')/'objects'/'pack'/('pack-'+('a'*40)+'.pack')
    original=source/relative;ki_guard._io(original.parent).mkdir(parents=True)
    payload=b'PACK\x00\x02\r\n\n\xff'+bytes(range(256))*10
    ki_guard._io(original).write_bytes(payload)
    result=kdtstudio.add_evidence(job.id,kind='official_docs',source_type='local',value=str(source))
    rows=kdtstudio._user_evidence(job.root);assert len(rows)==1
    target=job.root/rows[0]['value']/relative
    assert len(str(target))>260
    assert ki_guard._io(target).read_bytes()==payload
    assert ki_guard._io(original).read_bytes()==payload
    assert rows[0]['bytes']==len(payload) and rows[0]['files']==1


def test_failed_directory_copy_removes_only_new_partial_destination(job,monkeypatch):
    source=job.base/'docs';source.mkdir();(source/'manual.txt').write_bytes(b'author supplied')
    before=_meta(job);evidence_dir=job.root/'evidence'/'official_docs'
    legacy=evidence_dir/'legacy-unregistered';legacy.mkdir(parents=True);(legacy/'keep').write_bytes(b'old')
    def failed(src,dst,**kwargs):
        (Path(dst)/'partial').write_bytes(b'partial')
        raise OSError('fixture copy failed')
    monkeypatch.setattr(kdtstudio.shutil,'copytree',failed)
    with pytest.raises(OSError,match='fixture copy failed'):
        kdtstudio.add_evidence(job.id,kind='official_docs',source_type='local',value=str(source))
    assert kdtstudio._user_evidence(job.root)==[] and _meta(job)==before
    assert list(evidence_dir.iterdir())==[legacy] and (legacy/'keep').read_bytes()==b'old'
    assert (source/'manual.txt').read_bytes()==b'author supplied'


def test_failed_single_file_copy_removes_partial_and_leaves_metadata(job,monkeypatch):
    source=job.base/'paper.bin';source.write_bytes(b'original\x00binary')
    before=_meta(job)
    def failed(src,dst,**kwargs):
        Path(dst).write_bytes(b'partial')
        raise OSError('copy failed')
    monkeypatch.setattr(kdtstudio.shutil,'copy2',failed)
    with pytest.raises(OSError,match='copy failed'):
        kdtstudio.add_evidence(job.id,kind='literature',source_type='local',value=str(source))
    assert list((job.root/'evidence'/'literature').iterdir())==[]
    assert kdtstudio._user_evidence(job.root)==[] and _meta(job)==before
    assert source.read_bytes()==b'original\x00binary'


@pytest.mark.parametrize('directory',[True,False])
def test_preexisting_destination_collision_never_copies_or_cleans(job,monkeypatch,directory):
    source=job.base/'collision'
    if directory:source.mkdir();(source/'manual').write_bytes(b'new')
    else:source.write_bytes(b'new')
    monkeypatch.setattr(kdtstudio.uuid,'uuid4',lambda:SimpleNamespace(hex='a'*32))
    target=job.root/'evidence'/'official_docs'/('a'*12+'-collision')
    target.parent.mkdir(parents=True)
    if directory:target.mkdir();(target/'old').write_bytes(b'keep')
    else:target.write_bytes(b'keep')
    before=_meta(job)
    with pytest.raises(FileExistsError):
        kdtstudio.add_evidence(job.id,kind='official_docs',source_type='local',value=str(source))
    assert kdtstudio._user_evidence(job.root)==[] and _meta(job)==before
    assert ((target/'old') if directory else target).read_bytes()==b'keep'


def test_failed_copy_does_not_recursively_clean_a_replaced_alias(job,monkeypatch):
    source=job.base/'docs';source.mkdir();(source/'manual').write_bytes(b'new')
    outside=job.base/'outside';outside.mkdir();(outside/'keep').write_bytes(b'outside')
    def changed(src,dst,**kwargs):
        destination=Path(dst);destination.rmdir()
        try:destination.symlink_to(ki_guard._io(outside),target_is_directory=True)
        except OSError:pytest.skip('symlink capability unavailable')
        raise OSError('fixture replaced destination')
    monkeypatch.setattr(kdtstudio.shutil,'copytree',changed)
    with pytest.raises(ValueError,match='refusing unsafe cleanup'):
        kdtstudio.add_evidence(job.id,kind='official_docs',source_type='local',value=str(source))
    assert (outside/'keep').read_bytes()==b'outside'
    assert kdtstudio._user_evidence(job.root)==[]
