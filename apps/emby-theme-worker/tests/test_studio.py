import json
from pathlib import Path
import pytest
from emby_theme_worker.config import Config
from emby_theme_worker.db import StateDB
from emby_theme_worker.models import Candidate, MediaItem
from emby_theme_worker.scoring import score_candidate
from emby_theme_worker.search_pipeline import queries
from emby_theme_worker.segments import select_window
from emby_theme_worker.studio import Studio, public_source
from emby_theme_worker.worker import Worker

def test_lock_independent_from_execution(tmp_path):
    db=StateDB(str(tmp_path/'worker.db')); db.initialize()
    item=MediaItem('1','Movie',None,2000,'Movie',str(tmp_path))
    db.record_item(item,'complete',provider='local_opening',output_sha256='old')
    assert not db.control('1')['locked']
    db.set_control('1',locked=True)
    db.record_item(item,'complete',provider='local_opening',output_sha256='old')
    assert db.control('1')['locked']
    assert not db.local_opening_items()
    worker=object.__new__(Worker); worker.db=db
    with pytest.raises(PermissionError):
        worker._commit(item,Path('unused'),'manual','local_media',100,{})

def test_search_and_music_selection():
    item=MediaItem('1','角斗士','Gladiator',2000,'Movie','/Media/movie')
    assert len(queries(item)) == 4
    c=Candidate('youtube','Gladiator Main Theme Instrumental','https://example.test',duration=90,metadata={'channel_verified':True})
    assert score_candidate(c,item)==90
    assert c.metadata['score_details']['penalty']==0
    selected=select_window([('noise',0,20),('speech',20,70),('music',70,130)],130)
    assert selected['start']>=70 and selected['quality']=='high'
    assert select_window([('speech',0,90)],90)['quality']=='low'

def test_search_uses_alias_and_avoids_arbitrary_album_track():
    item=MediaItem('1','咔嗒咔嗒','ガチアクタ',2025,'Series','/Media/series',aliases=['Gachiakuta'])
    result=queries(item,[{'title':'Title','artist':'Xitilon'}])
    assert len(result)==4
    assert any('ガチアクタ' in q for q in result) and any('咔嗒咔嗒' in q for q in result)
    assert any('Gachiakuta' in q for q in result)
    assert not any('Xitilon' in q for q in result)

def test_musicbrainz_rejects_undated_same_name_album(monkeypatch):
    import httpx
    from emby_theme_worker.search_pipeline import musicbrainz
    real_client=httpx.Client
    calls=[]
    def respond(request):
        calls.append(str(request.url.path))
        return httpx.Response(200,json={'releases':[{'id':'game','title':'Gladiator'}]})
    monkeypatch.setattr(httpx,'Client',lambda **kw:real_client(transport=httpx.MockTransport(respond),**kw))
    item=MediaItem('1','角斗士','Gladiator',2000,'Movie','/Media/movie')
    assert musicbrainz(item)==[]
    assert len(calls)==1

def test_candidate_survives_restart_without_repeating_search(tmp_path):
    from types import SimpleNamespace
    from hashlib import sha256
    config=Config(database_path=str(tmp_path/'worker.db'),staging_path=str(tmp_path/'staging'))
    db=StateDB(config.database_path);db.initialize()
    source='https://www.youtube.com/watch?v=12345678901'
    identity='a'*32
    item=MediaItem('1','Movie',None,2000,'Movie',str(tmp_path))
    candidate=Candidate('youtube','Movie main theme',source,duration=90)
    job=db.enqueue('search','1',{})
    db.finish_job(job,result={'candidates':[{'candidate_id':identity,'source_hash':sha256(source.encode()).hexdigest(),'source_ref':source,**candidate.public_dict()}]})
    studio=Studio(config,db)
    def no_search(_item):raise AssertionError('must not repeat a full search to play a saved public reference')
    restored=studio.candidate(SimpleNamespace(_search=no_search),item,identity)
    assert restored.source_url==source and restored.transport=='youtube'
    preview=db.enqueue('prepare','1',{'candidate_id':identity})
    assert next(j for j in db.jobs() if j['id']==preview)['candidate_id']==identity

def test_queue_restart_and_public_source(tmp_path):
    c=Config(database_path=str(tmp_path/'worker.db'),staging_path=str(tmp_path/'staging'))
    db=StateDB(c.database_path); db.initialize(); studio=Studio(c,db)
    automatic=db.enqueue('auto','1',{},10)
    manual=db.enqueue('search','2',{},0)
    assert db.claim_job()['id']==manual
    Studio(c,db)
    assert next(j for j in db.jobs() if j['id']==manual)['status']=='interrupted'
    assert db.claim_job(False) is None
    assert db.claim_job()['id']==automatic
    with pytest.raises(ValueError): public_source('http://127.0.0.1/admin')
    with pytest.raises(ValueError): public_source('https://youtube.com.evil.test/watch?v=12345678901')
    assert public_source('https://youtu.be/12345678901')[1]=='youtube'
    with pytest.raises(ValueError): studio.asset('../../secrets')

@pytest.mark.parametrize('registered',[True,False])
def test_manual_apply_lock_and_rollback(tmp_path,registered):
    from types import SimpleNamespace
    from emby_theme_worker.audio import AudioProcessor,sha256
    media=tmp_path/'media';media.mkdir();target=media/'theme.mp3';target.write_bytes(b'old audio')
    item=MediaItem('1','test',None,2000,'Series',str(media))
    c=Config(database_path=str(tmp_path/'worker.db'),staging_path=str(tmp_path/'staging'),replacement_backup_path=str(tmp_path/'backups'),allowed_path=str(tmp_path))
    db=StateDB(c.database_path);db.initialize();db.record_item(item,'complete',provider='local_opening',output_path=str(target),output_sha256=sha256(target))
    studio=Studio(c,db);identity='a'*32;directory=studio.asset(identity);directory.mkdir();prepared=directory/'prepared.mp3';prepared.write_bytes(b'new audio')
    (directory/'meta.json').write_text(json.dumps({'item_id':'1','expected_sha256':sha256(target)}))
    audio=AudioProcessor(45,'192k',30,{})
    audio.validate=lambda path,**kwargs:{'sha256':sha256(path),'duration':45}
    worker=SimpleNamespace(audio=audio,emby=SimpleNamespace(get_item=lambda _id:item,refresh_and_verify=lambda *args,**kwargs:registered))
    if registered:
        assert studio.execute(worker,'apply','1',{'asset_id':identity})['locked']
        assert db.control('1')['locked'] and db.item_state('1')['source_provider']=='manual'
        assert target.read_bytes()==b'new audio'
    else:
        with pytest.raises(RuntimeError):studio.execute(worker,'apply','1',{'asset_id':identity})
        assert target.read_bytes()==b'old audio' and not db.control('1')['locked']
        assert db.item_state('1')['source_provider']=='local_opening'

def test_exact_mapping_survives_search_duplicate():
    from emby_theme_worker.scoring import score_all
    item=MediaItem('1','Gladiator',None,2000,'Movie','/Media/movie')
    candidates=[Candidate('themerrdb','Gladiator','same',exact=True),Candidate('youtube','unrelated','same')]
    result=score_all(candidates,item)
    assert len(result)==1 and result[0].exact and result[0].provider=='themerrdb'

def test_registration_outage_preserves_ownership(tmp_path):
    from types import SimpleNamespace
    from emby_theme_worker.audio import AudioProcessor,sha256
    c=Config(database_path=str(tmp_path/'worker.db'),allowed_path=str(tmp_path))
    db=StateDB(c.database_path);db.initialize()
    directory=tmp_path/'movie';directory.mkdir()
    item=MediaItem('1','test',None,2000,'Series',str(directory))
    prepared=tmp_path/'prepared.mp3';prepared.write_bytes(b'audio')
    def unavailable(*args,**kwargs):raise ConnectionError('offline')
    worker=object.__new__(Worker);worker.config=c;worker.db=db;worker.audio=AudioProcessor(45,'192k',30,{})
    worker.emby=SimpleNamespace(theme_visible=lambda _id:False,refresh_and_verify=unavailable)
    result=worker._commit(item,prepared,'manual','local_media',100,{'duration':45})
    assert result['status']=='pending_refresh'
    db.record_item(item,'failed',error_class='network')
    assert db.item_state('1')['source_provider']=='manual' and db.item_state('1')['output_sha256']==sha256(directory/'theme.mp3')
    worker.emby=SimpleNamespace(trigger_library_scan=lambda:None,wait_library_scan=lambda *a:True,verify_theme_resource=lambda *a:True,get_item=lambda _id:item)
    db.record_item(item,'pending_refresh',provider='manual',output_path=str(directory/'theme.mp3'),output_sha256=sha256(directory/'theme.mp3'))
    assert worker._register_pending()==('complete',1)
    assert db.control('1')['locked']
