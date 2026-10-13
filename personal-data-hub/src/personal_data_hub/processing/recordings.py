"""复用既有 Plaud 产物，不重新转录、融合或生成摘要。"""
import math

from ..contracts import digest
from ..metric_rules import number
from .contracts import object_id
from .reading import content, fields_block, text_blocks

PROCESSOR = 'recording-v1'
PROFILE_VERSION = 1
KINDS = ('recording', 'recording_transcript', 'recording_daily_report', 'recording_summary')


def accepts(row): return row['kind'] in KINDS

def dependency_ids(rows):
    return [digest([row['source'], row['raw']['recording_id']]) for row in rows if row['kind'] == 'recording_transcript']


def header(row, scope=None):
    return ('recording', 'recording') if row['kind'] == 'recording' else ('document', row['kind'])


def link(source, external_id):
    rid = digest([source, external_id])
    return {'record_id': rid, 'content_id': object_id(PROCESSOR, source, rid)}


def transcript_blocks(row, normal, field, key, duration=None):
    text = normal.get('content', ''); segments = normal.get('segments', [])
    # Keep the archived full transcript verbatim, even when segment text differs.
    blocks = text_blocks(row, text, field + '.content', key=key, metadata={'role': 'transcript_verbatim' if segments else 'transcript', 'engine': normal.get('engine')})
    anchors = []
    for index, segment in enumerate(segments):
        start, end = segment.get('start_seconds'), segment.get('end_seconds')
        valid = isinstance(start, (int, float)) and not isinstance(start, bool) and math.isfinite(start) and start >= 0
        valid &= normal.get('status') != 'invalid_timestamps'
        if end is not None: valid &= isinstance(end, (int, float)) and not isinstance(end, bool) and math.isfinite(end) and end >= (start or 0)
        if duration is not None: valid &= start is not None and start < duration and (end is None or end <= duration)
        # One short segment block provides the audio anchor; full text remains above.
        segment_text = segment.get('text', '')
        pieces = text_blocks(row, segment_text, f'{field}.segments[{index}].text', key=f'{key}:segment:{index}', kind='text',
            metadata={'role': 'transcript_segment', 'segment_index': index, 'speaker': segment.get('speaker'),
                      'speaker_scope': 'source_block', 'seek_seconds': start if valid else None,
                      'end_seconds': end if valid else None, 'time_valid': bool(valid)})
        anchors.extend(pieces)
    return blocks + anchors


def process(rows):
    if not rows: return None
    row = rows[0]; raw, n = row['raw'], row['normalized']; kind = row['kind']
    if kind == 'recording':
        metadata = {k: n.get(k) for k in ('date', 'duration_ms', 'download_state', 'transcription_status', 'transcript_engine', 'transcript_is_draft', 'summary_status')}
        metadata.update(recording_id=raw['recording_id'], summary_scope=n.get('summary_scope'), transcription_scope='recording',
                        audio_assets=[a for a in row['assets'] if a.get('media_type', '').startswith('audio/')],
                        daily_report=link(row['source'], n['daily_report_external_id']) if n.get('daily_report_external_id') else None)
        blocks = text_blocks(row, n.get('transcript', ''), 'normalized.transcript', metadata={'role': 'transcript', 'draft': n.get('transcript_is_draft')})
        # Day summary is a linked day document, never a per-recording summary.
        metadata['daily_summary'] = link(row['source'], 'summary:' + n['date']) if n.get('summary') else None
        metadata['transcript_sources'] = [{k: source.get(k) for k in ('engine', 'status', 'draft', 'blocks', 'expected_blocks')}
                                          | link(row['source'], f"transcript:{raw['recording_id']}:{engine}")
                                          for engine, source in n.get('transcripts', {}).items()]
        return content(row, 'recording', 'recording', 'Plaud 录音 · ' + n['date'], blocks, metadata,
            coverage={'body': 'complete', 'transcript': n.get('transcription_status'), 'audio': n.get('download_state')})
    metadata = {k: n.get(k) for k in ('date', 'status', 'engine', 'draft', 'scope', 'blocks', 'expected_blocks')}
    if kind == 'recording_transcript':
        metadata.update(recording_id=raw['recording_id'], recording=link(row['source'], raw['recording_id']), scope=n.get('scope', 'recording'))
        parent = next((r for r in rows[1:] if r['kind'] == 'recording'), None)
        duration_ms = number(parent['normalized'].get('duration_ms')) if parent else None
        metadata['audio_assets'] = parent['assets'] if parent else []
        metadata['duration_ms'] = duration_ms
        metadata['audio_available'] = bool(parent and parent['assets'])
        blocks = transcript_blocks(row, n, 'normalized', 'transcript', duration_ms / 1000 if duration_ms is not None else None)
        if parent is None:
            for b in blocks:
                if b.metadata.get('role') == 'transcript_segment': b.metadata.update(seek_seconds=None, end_seconds=None, time_valid=False)
    else:
        metadata.update(scope='day', format='markdown', derived_from_recording_date=n.get('derived_from_recording_date'))
        blocks = text_blocks(row, n['content'], 'normalized.content')
    return content(row, 'document', kind, n['title'], blocks, metadata,
                   warnings=['upstream_draft'] if n.get('draft') else [],
                   coverage={'body': 'complete', 'transcript': n.get('status')} if kind == 'recording_transcript' else {'body': 'complete', 'scope': 'day'})
