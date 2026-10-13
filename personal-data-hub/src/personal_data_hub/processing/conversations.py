"""Wechat day conversations. Source text and attribution remain inspectable."""
from __future__ import annotations

from collections import Counter
from zoneinfo import ZoneInfo

from ..contracts import canonical, digest, instant
from .contracts import BLOCK_CHARS, ContentBlock, ProcessedContent

PROCESSOR = 'wechat-day-v1'
PROFILE_VERSION = 1
KINDS = ('interactions',)
DEPENDENCY_KINDS = ('people',)
BUSINESS_TIMEZONE = 'Asia/Taipei'
SEGMENT_GAP_SECONDS = 1800


def accepts(row):
    return row['kind'] == 'interactions' and row['raw'].get('channel') == 'wechat'


def identity(row):
    raw = row['raw']
    message = raw.get('message') if isinstance(raw.get('message'), dict) else {}
    person = str(raw.get('person_id') or '')
    account = str(message.get('account_namespace') or 'legacy')
    conversation = str(message.get('conversation_id') or '')
    when = instant(row['occurred_at'])
    day = when.astimezone(ZoneInfo(BUSINESS_TIMEZONE)).date().isoformat() if when else None
    # Missing person identity must not merge unrelated records into a shared bucket.
    return {'person_id': person, 'account_namespace': account, 'conversation_id': conversation,
            'business_date': day, 'isolation': '' if person else row['id']}


def scope(row):
    value = identity(row)
    return canonical([PROCESSOR, BUSINESS_TIMEZONE, value['account_namespace'], value['person_id'],
                      value['conversation_id'], value['business_date'], value['isolation']])


def clean(value, limit=None):
    value = str(value or '').replace('\x00', '\ufffd')
    return value[:limit] if limit else value


def message_value(row):
    raw = row['raw']
    message = raw.get('message') if isinstance(raw.get('message'), dict) else {}
    reader = message.get('record') if isinstance(message.get('record'), dict) else {}
    original = reader.get('content')
    field = 'raw.message.record.content'
    fidelity = 'original'
    if not isinstance(original, str):
        original = raw.get('summary')
        field = 'raw.summary'
        fidelity = 'legacy_description'
    if not isinstance(original, str):
        original = ''
        fidelity = 'missing'
    key = raw.get('source_message_key') or raw.get('source_event_key') or row['id']
    when = instant(row['occurred_at'])
    direction = raw.get('direction') if raw.get('direction') in ('inbound', 'outbound') else 'unknown'
    conversation = str(message.get('conversation_id') or '')
    chat_type = 'group' if conversation.endswith('@chatroom') else message.get('conversation_type', 'unknown')
    sender_id = clean(reader.get('sender_wxid'), 256) or None
    sender = clean(reader.get('sender'), 160) or ('我' if direction == 'outbound' else None)
    kind = reader.get('msg_type', raw.get('interaction_type'))
    metadata = {'message_key': clean(key, 256), 'occurred_at': when.isoformat() if when else None,
                'direction': direction, 'sender': sender, 'sender_id': sender_id,
                'message_type': clean(kind, 64), 'conversation_type': chat_type,
                'fidelity': fidelity, 'body_chars': len(original), 'empty': not original,
                'assets': row['assets'], 'media_state': media_state(kind, row['assets'])}
    fingerprint = digest([original, metadata['occurred_at'], direction, sender, sender_id, str(kind), fidelity])
    return {'row': row, 'text': original.replace('\x00', '\ufffd'), 'field': field,
            'metadata': metadata, 'identity': str(key), 'fingerprint': fingerprint,
            'refs': [dict(record_id=row['id'], input_hash=row['hash'], field=field)],
            'nul': '\x00' in original}


def media_state(kind, assets):
    if any(a.get('media_type') == 'application/vnd.wechat.encrypted-image' for a in assets):
        return 'encrypted'
    if assets:
        return 'archived_original'
    return 'not_archived' if str(kind) in ('3', '34', '43', '47', '49', '62') else 'none'


def process(rows):
    messages = [row for row in rows if accepts(row)]
    if not messages:
        return None
    if len({scope(row) for row in messages}) != 1:
        raise ValueError('conversation_scope_mismatch')
    context = identity(messages[0])
    people = {str(row['raw'].get('id')): row['raw'] for row in rows if row['kind'] == 'people'}
    person = people.get(context['person_id'], {})
    name = clean(person.get('display_name'), 120) or clean(context['conversation_id'], 120) or '历史微信会话'
    day = context['business_date']
    warnings = set()
    if not context['person_id']: warnings.add('conversation_identity_incomplete')
    if not day: warnings.add('conversation_time_unknown')
    values = sorted((message_value(row) for row in messages), key=lambda m:
                    (m['metadata']['occurred_at'] is None, m['metadata']['occurred_at'] or '',
                     m['identity'], m['row']['id']))
    unique, seen, identities = [], {}, set()
    for value in values:
        previous = seen.get((value['identity'], value['fingerprint']))
        if previous:
            previous['refs'].extend(value['refs'])
            assets = {asset['id']: asset for asset in previous['metadata']['assets']}
            assets.update({asset['id']: asset for asset in value['metadata']['assets']})
            previous['metadata']['assets'] = list(assets.values())
            continue
        if value['identity'] in identities:
            warnings.add('conflicting_message_identity')
        seen[(value['identity'], value['fingerprint'])] = value
        identities.add(value['identity'])
        unique.append(value)
    blocks, segment_count, previous_time, counts = [], 0, None, Counter()
    all_assets = {}
    for index, value in enumerate(unique):
        metadata = value['metadata']
        when = instant(metadata['occurred_at'])
        start_segment = index == 0 or when is None or previous_time is None or (when - previous_time).total_seconds() >= SEGMENT_GAP_SECONDS
        if start_segment: segment_count += 1
        segment_id = 'segment:' + digest([value['identity'], value['row']['id']])[:24] if start_segment else blocks[-1].metadata['segment_id']
        metadata |= {'segment_id': segment_id, 'segment_start': start_segment, 'message_index': index,
                     'part_count': max(1, (len(value['text']) + BLOCK_CHARS - 1) // BLOCK_CHARS)}
        counts[metadata['fidelity']] += 1
        if value['nul']: warnings.add('nul_replaced_in_reading_copy')
        if metadata['fidelity'] != 'original': warnings.add('historical_original_missing')
        if metadata['conversation_type'] == 'group' and not metadata['sender'] and not metadata['sender_id']:
            warnings.add('group_sender_unknown')
        for asset in metadata['assets']: all_assets[asset['id']] = asset
        for part, start in enumerate(range(0, max(1, len(value['text'])), BLOCK_CHARS)):
            end = min(len(value['text']), start + BLOCK_CHARS)
            key = 'message:' + digest([value['identity'], value['row']['id']])[:24] + ':' + str(part)
            refs = [ref | {'char_start': start, 'char_end': end} for ref in value['refs']]
            blocks.append(ContentBlock(key, 'message', value['text'][start:end], refs,
                metadata | {'part': part, 'continuation': part > 0, 'segment_start': start_segment and part == 0}))
        previous_time = when
    direction_counts = dict(Counter(m['metadata']['direction'] for m in unique))
    details = context | {'timezone': BUSINESS_TIMEZONE, 'name': name, 'message_count': len(unique),
                'body_chars': sum(len(value['text']) for value in unique),
                'input_message_records': len(messages), 'duplicate_records': len(messages) - len(unique),
                'fidelity_counts': dict(counts), 'directions': direction_counts,
                'segment_count': segment_count, 'segmentation': {'method': 'time_gap', 'gap_seconds': SEGMENT_GAP_SECONDS},
                'assets': list(all_assets.values()), 'origin': 'source',
                'extraction': {'state': 'separate_pipeline', 'method': None},
                'started_at': unique[0]['metadata']['occurred_at'], 'ended_at': unique[-1]['metadata']['occurred_at']}
    preview = next((m['text'][:500] for m in unique if m['text'].strip()), '无文本内容')
    return ProcessedContent('conversation', 'wechat_day', f'{name} · {day or "时间未知"}', preview,
                            blocks, details, warnings=sorted(warnings),
                            coverage={'body': 'original' if counts['original'] == len(unique) else 'partial',
                                      'original_messages': counts['original'], 'total_messages': len(unique),
                                      'history': 'archived_records_only'})
