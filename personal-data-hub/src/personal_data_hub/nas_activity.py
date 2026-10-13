"""Emby 当前播放观察和 Navidrome 已保存的 scrobble 历史。"""
from pathlib import Path
from urllib.parse import quote

import httpx

from .collectors import snapshot, chunks
from .contracts import Batch, Record, digest, instant, utcnow


class EmbyCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None):
        s = self.settings
        user_id = s['user_id']
        observed = utcnow()
        slot = int(observed.timestamp()) // s.get('interval_seconds', 60)
        with httpx.Client(headers={'X-Emby-Token': Path(s['api_key_file']).read_text().strip()}, timeout=20, trust_env=False) as client:
            response = client.get(s['url'].rstrip('/') + '/emby/Sessions')
            response.raise_for_status()
            sessions = response.json()
        rows = []
        for session in sessions:
            if session.get('UserId') != user_id or not session.get('NowPlayingItem'): continue
            item, state = session['NowPlayingItem'], session.get('PlayState', {})
            raw = {key: session.get(key) for key in ('Id', 'ServerId', 'UserId', 'DeviceId', 'DeviceName', 'Client', 'LastActivityDate')}
            # Archive the playback business projection; media URLs and OpenToken are excluded.
            raw['NowPlayingItem'] = {key: item.get(key) for key in ('Id', 'Name', 'Type', 'SeriesName', 'SeasonName', 'IndexNumber', 'ParentIndexNumber', 'RunTimeTicks', 'ProductionYear', 'ProviderIds')}
            raw['PlayState'] = {key: state.get(key) for key in ('PositionTicks', 'IsPaused', 'PlaybackRate', 'CanSeek', 'PlayMethod')}
            normal = dict(service='emby', instance_id=s['instance_id'], source_user_id=user_id, item_id=item['Id'], title=item['Name'],
                          item_type=item.get('Type'), series=item.get('SeriesName'), season=item.get('ParentIndexNumber'), episode=item.get('IndexNumber'),
                          session_id=session['Id'], device_id=session.get('DeviceId'), device=session.get('DeviceName'), player=session.get('Client'),
                          paused=state.get('IsPaused'), position_seconds=state['PositionTicks'] / 10_000_000 if state.get('PositionTicks') is not None else None,
                          media_duration_seconds=item['RunTimeTicks'] / 10_000_000 if item.get('RunTimeTicks') is not None else None,
                          playback_rate=state.get('PlaybackRate'), observed_at=observed.isoformat(), source_activity_at=session.get('LastActivityDate'),
                          time_basis='observation_time', capture='sampled_current_state', sample_interval_seconds=s.get('interval_seconds', 60),
                          link=s['web_url'].rstrip('/') + '/web/index.html#!/item?id=' + quote(str(item['Id'])),
                          listened_duration_seconds=None, watched_duration_seconds=None)
            eid = 'snapshot:' + digest([s['instance_id'], user_id, session['Id'], item['Id'], slot])
            rows.append(Record(eid, 'media_playback_snapshot', raw, normal, timezone=s.get('timezone', 'Asia/Shanghai')))
        yield from chunks(rows)
        yield Batch(next_cursor={'checked_at': observed.isoformat(), 'coverage': 'current_sessions_only', 'observed_playing_sessions': len(rows)})


class NavidromeCollector:
    def __init__(self, settings): self.settings = settings

    def collect(self, cursor, since=None):
        s = self.settings; last_id = cursor.get('last_scrobble_id', 0)
        observed = utcnow()
        with snapshot(s['path']) as c:
            statement = '''SELECT s.id, s.media_file_id, s.user_id, s.submission_time,
                                  m.title, m.artist, m.album, m.duration, m.missing
                           FROM scrobbles s LEFT JOIN media_file m ON m.id = s.media_file_id
                           WHERE s.user_id = ? AND s.id > ?'''
            params = [s['user_id'], last_id]
            if since:
                statement += ' AND s.submission_time >= ?'; params.append(int(instant(since).timestamp()))
            statement += ' ORDER BY s.id'
            def records():
                nonlocal last_id
                for row in c.execute(statement, params):
                    raw = dict(row); last_id = row['id']
                    normal = dict(service='navidrome', instance_id=s['instance_id'], source_user_id=s['user_id'],
                                  item_id=row['media_file_id'], source_event_id=row['id'], title=row['title'] or '歌曲信息已不在库中',
                                  artist=row['artist'], album=row['album'], media_duration_seconds=row['duration'],
                                  metadata_available=row['title'] is not None, item_metadata_basis='library_at_collection', media_missing=bool(row['missing']) if row['missing'] is not None else None,
                                  time_basis='source_submission_time', capture='persisted_scrobble', event_type='scrobble_submission',
                                  link=s['web_url'], listened_duration_seconds=None)
                    # Native row ID retains repeated submissions of the same song, including same-second plays.
                    yield Record('scrobble:' + str(row['id']), 'music_playback_event', raw, normal,
                                 instant(row['submission_time']), timezone=s.get('timezone', 'Asia/Shanghai'))
            yield from chunks(records())
        yield Batch(next_cursor={'last_scrobble_id': last_id, 'checked_at': observed.isoformat(),
                                 'coverage': 'persisted_client_submissions', 'history_since': instant(since).isoformat() if since else cursor.get('history_since')})
