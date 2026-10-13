"""Exercise durable retries, interruption recovery and late-arrival discovery."""
import json
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch, AsyncMock

from plaud_daily import retries
from plaud_daily.core import State, atomic_bytes
from plaud_daily.daily_v3 import pending_dates
from plaud_daily import daily_v3 as daily
from plaud_daily.multiday_trial import sha256_file
from plaud_daily.fusion_v3 import write_once


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    published = root / 'source.json'
    staging = published.with_suffix('.json.part')
    staging.write_text('interrupted write')
    write_once(published,'complete source')
    write_once(published,'complete source')
    assert published.read_text() == 'complete source' and staging.read_text() == 'interrupted write'
    try: write_once(published,'different source')
    except RuntimeError: pass
    else: raise AssertionError('completed source must not be overwritten')
    cached_run = root/'runs/2026-10-05/cached'
    input_path = cached_run/'fusion-input-multiday-v3.md'
    atomic_bytes(input_path,b'verified three-source input')
    digest = sha256_file(input_path)
    atomic_bytes(cached_run/'review-manifest.json',json.dumps({'eligible_for_submission':True,'input_sha256':digest}).encode())
    atomic_bytes(cached_run/'run-inputs.json',json.dumps({'recordings':[{'id':'recording','duration_ms':30000}]}).encode())
    saved_answer = '## 录音 recording\n**00:00:02** 原话\n'
    atomic_bytes(cached_run/'response-unvalidated-1.md',saved_answer.encode())
    atomic_bytes(cached_run/'submission-attempt.json',json.dumps({'approved_sha256':digest,'model':'test-model','status':'failed','attempts':1}).encode())
    with patch.object(daily.trial,'configured_key',return_value='smoke-key'), \
         patch.object(daily.urllib.request,'urlopen',side_effect=AssertionError('saved fusion must not be requested again')):
        result = daily.submit_approved({'data_root':str(root),'fusion_model':'test-model','max_input_bytes':10000},cached_run,digest,automatic=True,day='2026-10-05')
    assert result['revalidated_saved_response'] and (cached_run/'response-unvalidated-1.md').read_text() == saved_answer
    assert 'Speaker ?: 原话' in (cached_run/'transcript-v3.md').read_text()
    attempt = root / 'attempt.json'
    identity = {'audio_sha256': 'same-input'}
    with patch.object(retries.time, 'time', return_value=1000):
        first = retries.begin(attempt, identity)
        assert first['attempts'] == 1
        retries.finish(attempt, first, False, error='temporary upstream failure')
        assert retries.begin(attempt, identity) is None
    with patch.object(retries.time, 'time', return_value=1031):
        second = retries.begin(attempt, identity)
        assert second['attempts'] == 2
        retries.finish(attempt, second, True)
        assert retries.begin(attempt, identity) is None
        recovered = retries.begin(attempt, identity, artifact_present=False)
        assert recovered['attempts'] == 3
    assert len(list((root / 'attempt.history').glob('*.json'))) == 2
    old = json.loads(attempt.read_text())
    old['status'] = 'attempted_once'
    atomic_bytes(attempt, json.dumps(old).encode())
    with patch.object(retries.time, 'time', return_value=attempt.stat().st_mtime + 1201):
        assert retries.begin(attempt, identity)['attempts'] == 4

    state = State(root)
    row = {'recording_id':'first','source_provider':'local','start_at':'2026-10-09T00:00:00Z',
           'local_date':'2026-10-09','duration_ms':1000,'remote_state':'downloaded','sha256':'first-hash'}
    state.upsert_recording(row)
    run = root / 'runs' / 'first'
    atomic_bytes(run / 'run-inputs.json', json.dumps({'recordings':[{'id':'first','audio':'first-hash','duration_ms':1000}]}).encode())
    atomic_bytes(root / 'status/2026-10-09.json', json.dumps({'status':'complete','run':str(run)}).encode())
    config, workflow = {'data_root':str(root)}, {'timezone':'Asia/Taipei'}
    assert pending_dates(config, workflow, date(2026,10,11)) == []
    state.upsert_recording({**row,'recording_id':'late','sha256':'late-hash'})
    assert pending_dates(config, workflow, date(2026,10,11)) == ['2026-10-09']
    state.upsert_recording({**row,'recording_id':'not-downloaded','remote_state':'pending'})
    assert pending_dates(config, workflow, date(2026,10,11)) == ['2026-10-09']
    state.upsert_recording({**row,'recording_id':'older-unfinished','local_date':'2026-09-01'})
    assert pending_dates(config, workflow, date(2026,10,11)) == ['2026-10-09']
    atomic_bytes(root/'status/2026-09-01.json',json.dumps({'date':'2026-09-01','status':'queued'}).encode())
    assert pending_dates(config, workflow, date(2026,10,11)) == ['2026-09-01','2026-10-09']
    state.close()
    archive = root / 'download-archive'
    old = State(archive)
    audio = archive / 'raw.mp3'
    audio.write_bytes(b'previously-downloaded-audio')
    old.upsert_recording({**row,'recording_id':'archive-only','local_date':(date.today()-timedelta(days=2)).isoformat(),
                          'local_path':str(audio),'sha256':sha256_file(audio)})
    old.close()
    config.update(archive_data_root=str(archive),sync_provider='plaud_mcp',plaud_mcp={'lookback_days':3})
    upstream = AsyncMock(return_value={'downloaded':0})
    with patch.object(daily,'sync_plaud',upstream), patch.object(daily,'run_date',return_value={'status':'source_retry_pending'}):
        result = daily.run_pending(workflow, config)
    assert upstream.call_args.args[0]['plaud_mcp']['lookback_days'] == 8
    state = State(root)
    assert state.get_recording('archive-only')['local_path'] == str(audio)
    state.close()
    (archive/'state/state.db').write_bytes(b'not readable as a database')
    with patch.object(daily,'sync_plaud',upstream), patch.object(daily,'run_date',return_value={'status':'source_retry_pending'}):
        result = daily.run_pending(workflow, config)
    assert result['archive_reuse'] == 'unavailable_use_upstream'
print('smoke OK: durable backoff, successful request reuse, missing artifact and interrupted request recovery, late audio reopens completed date; no network')
