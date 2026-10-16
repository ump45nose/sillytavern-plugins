import os, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from personal_data_hub.server import create_app
from personal_data_hub.contracts import Batch, Record, Asset, instant
from personal_data_hub.storage import previews
from sqlalchemy import delete, select
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    for name,secret in [('writer','write-smoke'),('viewer','read-smoke'),('finance','finance-smoke')]: (root/name).write_text(secret)
    config={'database_url':'sqlite:///'+str(root/'archive.sqlite'),'asset_root':str(root/'assets'),'hub_api_token_file':str(root/'writer'),'hub_viewer_token_file':str(root/'viewer'),'sources':{'skysight-summaries':{'adapter':'skysight'}}}
    app=create_app(config,webhook_only=True); store=app.state.hub_store
    store.ingest('skysight-summaries',Batch(records=[Record(str(i),'computer_summary',{'title':'literal% title'}, {'content':'unique note '+str(i)},instant('2026-10-06T01:00:00Z'),assets=[Asset('note.txt',content=b'hello')]) for i in range(3)]))
    client=TestClient(app); read={'Authorization':'Bearer read-smoke'}
    assert client.get('/api/v1/browse').status_code==401
    p=client.get('/api/v1/browse?limit=2',headers=read).json(); assert len(p['records'])==2 and p['total']==3 and p['next_offset']==2
    assert not {'raw','normalized','assets'} & p['records'][0].keys()
    assert client.get('/api/v1/browse?offset=2&limit=2',headers=read).json()['next_offset'] is None
    assert client.get('/api/v1/browse?query=literal%25',headers=read).json()['total']==3
    assert client.get('/api/v1/browse?query=_',headers=read).json()['total']==0
    assert client.get('/api/v1/browse?start=2026-10-07T00:00:00Z',headers=read).json()['total']==0
    assert client.get('/api/v1/browse?start=2026-10-06',headers=read).status_code==422
    assert client.get('/api/v1/browse?offset=-1',headers=read).status_code==422
    for path in ['/api/v1/sources','/api/v1/kinds','/api/v1/records','/api/v1/records/'+p['records'][0]['id']]: assert client.get(path,headers=read).status_code==200
    full=store.get_record(p['records'][0]['id']); aid=full['assets'][0]['id']
    assert client.get('/api/v1/assets/'+aid,headers=read).content==b'hello'
    assert client.post('/api/v1/ingest',json={'batch_id':'test','source':'skysight-summaries'},headers=read).status_code==401
    assert client.put('/api/v1/assets/'+aid,content=b'hello',headers=read).status_code==401
    assert client.post('/autoaccounting/v1/bills',json={},headers=read).status_code==404
    with store.engine.begin() as c: c.execute(delete(previews).where(previews.c.record_id==full['id']))
    assert store.backfill_previews()==1
    store.ingest('skysight-summaries',Batch(records=[Record('nul','computer_summary',{'events':'AX\x00data'},{'content':'NUL\x00 preview'})]))
    assert client.get('/api/v1/browse?query=NUL',headers=read).json()['records'][0]['preview']=='NUL preview'
    store.ingest('skysight-summaries',Batch(deletions=['nul']))
    with store.engine.connect() as c: assert c.scalar(select(previews.c.record_id).where(previews.c.record_id==store.identity('skysight-summaries','nul'))) is None
    assert client.get('/api/v1/browse',headers={'Authorization':'Bearer write-smoke'}).status_code==200
    print('smoke_ok: viewer read-only boundary, bounded cards, literal search, time filters, paging, detail, attachment, NUL preview, backfill, deletion')
