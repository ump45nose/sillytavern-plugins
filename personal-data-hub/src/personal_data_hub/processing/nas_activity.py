"""NAS 日活动：观察点和已上报记录分别呈现，不估计观看或收听时长。"""
from collections import OrderedDict
from zoneinfo import ZoneInfo

from ..contracts import canonical, instant
from .reading import content, fields_block

PROCESSOR = 'nas-activity-v1'
PROFILE_VERSION = 1
KINDS = ('media_playback_snapshot', 'music_playback_event')


def accepts(row): return row['kind'] in KINDS

def scope(row):
    n = row['normalized']
    when = instant(n['observed_at']) if row['kind'] == 'media_playback_snapshot' else instant(row['occurred_at'])
    return canonical([n['service'], row['kind'], n['instance_id'], n['source_user_id'],
                      when.astimezone(ZoneInfo(row['timezone'])).date().isoformat()])


def header(row, scope_key=None):
    return 'activity', 'media_day' if row['kind'] == 'media_playback_snapshot' else 'music_day'


def process_scope(rows, scope_key):
    if not rows: return None
    media = rows[0]['kind'] == 'media_playback_snapshot'
    def timestamp(row): return instant(row['normalized']['observed_at']) if media else instant(row['occurred_at'])
    rows = sorted(rows, key=lambda r: (timestamp(r), r['normalized'].get('source_event_id', 0), r['id']))
    row = rows[0]; normal = row['normalized']; typ, variant = header(row)
    day = timestamp(row).astimezone(ZoneInfo(row['timezone'])).date().isoformat()
    blocks = []; groups = OrderedDict()
    for index,r in enumerate(rows):
        n = r['normalized']
        group_key = (n['item_id'], n.get('session_id')) if media else (n['item_id'],)
        group = groups.setdefault(group_key, dict(item_id=n['item_id'], title=n['title'], artist=n.get('artist'), album=n.get('album'),
            session_id=n.get('session_id'), player=n.get('player'), device=n.get('device'), link=n['link'], count=0,
            first_time=timestamp(r).isoformat(), last_time=timestamp(r).isoformat(), media_duration_seconds=n.get('media_duration_seconds')))
        group['count'] += 1; group['last_time'] = timestamp(r).isoformat()
        values = {k:n.get(k) for k in ('title','artist','album','series','season','episode','player','device','paused','position_seconds','playback_rate','media_duration_seconds','metadata_available','media_missing')}
        values.update(time=timestamp(r).isoformat(), item_id=n['item_id'], source_event_id=n.get('source_event_id'),
                      session_id=n.get('session_id'), time_basis=n['time_basis'], group_index=list(groups).index(group_key), role='observation' if media else 'scrobble_submission')
        block = fields_block(r, values, key=f'playback:{index}', field='normalized')
        blocks.append(block)
    for group in groups.values():
        group['count_label'] = '观察点' if media else '上报记录'
    metadata = dict(service=normal['service'], instance_id=normal['instance_id'], source_user_id=normal['source_user_id'],
                    business_date=day, timezone=row['timezone'], started_at=timestamp(rows[0]).isoformat(), ended_at=timestamp(rows[-1]).isoformat(),
                    time_basis=normal['time_basis'], capture=normal['capture'], record_count=len(rows), item_count=len(groups), items=list(groups.values()),
                    origin='deterministic_projection', duration_kind='observation_range' if media else 'submission_range',
                    watched_duration_seconds=None, listened_duration_seconds=None)
    warnings = ['sampling_may_miss_short_playback'] if media else ['client_submission_is_not_measured_listening_duration']
    if any(r['normalized'].get('metadata_available') is False for r in rows): warnings.append('item_metadata_missing')
    if media: metadata['sample_interval_seconds'] = normal['sample_interval_seconds']
    result = content(row, typ, variant, ('Emby 播放观察 · ' if media else 'Navidrome 收听上报 · ') + day, blocks, metadata,
                   warnings=warnings,
                   coverage={'body':'complete','playback':'sampled_current_state' if media else 'persisted_client_submissions','history':'since_source_capture' if media else 'retained_source_history'})

    result.preview = f'{len(groups)} 个条目，{len(rows)} ' + ('个播放观察点' if media else '条收听上报记录')
    return result
