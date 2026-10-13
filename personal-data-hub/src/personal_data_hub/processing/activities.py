"""活动阅读：上游摘要、既有背景和原始观察分别呈现。"""
import re

from ..contracts import digest
from .contracts import object_id
from .reading import content, fields_block, text_blocks

PROCESSOR = 'activity-v1'
PROFILE_VERSION = 2
KINDS = ('computer_summary', 'computer_segment')


def accepts(row): return row['kind'] in KINDS

def header(row, scope=None): return 'activity', 'activity_summary' if row['kind'] == 'computer_summary' else 'activity_observations'


def process(rows):
    if not rows: return None
    row = rows[0]; raw, n = row['raw'], row['normalized']
    if row['kind'] == 'computer_segment':
        blocks = []
        for index, event in enumerate(n['events']):
            app, window = event.get('app', {}), event.get('window', {})
            values = {'time': event.get('timestamp'), 'event_kind': event.get('kind'), 'application': app.get('name'),
                      'bundle_id': app.get('bundleIdentifier'), 'window': window.get('title'), 'url': window.get('url')}
            blocks.append(fields_block(row, values, key=f'event:{index}', field=f'normalized.events[{index}]'))
            for field, text in [('ax.text', event.get('ax', {}).get('text')), ('selection.selectedText', event.get('selection', {}).get('selectedText'))]:
                if isinstance(text, str):
                    blocks.extend(text_blocks(row, text, f'normalized.events[{index}].{field}', key=f'event:{index}:{field}', kind='text',
                        metadata={'event_index': index, 'time': event.get('timestamp'), 'application': app.get('name')}))
        return content(row, 'activity', 'activity_observations', '电脑活动观察', blocks,
            {'started_at': raw.get('startedAt'), 'ended_at': raw.get('endedAt'), 'event_count': len(n['events']),
             'suppressed_event_count': raw.get('suppressedEventCount'), 'duration_kind': 'observation_range', 'active_duration_seconds': None,
             'source_ref': n.get('source_ref')}, coverage={'body': 'complete', 'activity': 'observed_events_only'})
    body = n['content']; front = re.match(r'^---\s*\n(.*?)\n---[^\n]*\n?', body, re.S)
    # These upstream headers are plain single-line fields, not a strict YAML document.
    source_fields = dict(re.findall(r'(?m)^(title|description|applications):[ \t]*(.*)$', front[1])) if front else {}
    meta = {key:value.strip().strip('\"\'') for key,value in source_fields.items() if key != 'applications'}
    meta['applications'] = [value.strip().strip('\"\'') for value in source_fields.get('applications', '').strip().removeprefix('[').removesuffix(']').split(',') if value.strip()]

    offset = front.end() if front else 0
    headings = list(re.finditer(r'(?m)^#{1,2}\s+(.+)\n', body[offset:]))
    boundaries = [offset] + [offset + m.start() for m in headings if m.start()] + [len(body)]
    blocks = []
    for start, end in zip(boundaries, boundaries[1:]):
        section = body[start:end]; heading = re.match(r'^#{1,2}\s+(.+)', section)
        label = heading[1].strip() if heading else '正文'
        background = label in ('Relevant prior context', 'Important non-obvious context about the user')
        blocks.extend(text_blocks(row, section, 'normalized.content', key=f'section:{start}', offset=start,
            metadata={'section': label, 'role': 'background' if background else 'citations' if label == 'Citations' else 'activity'}))
    citation_section = re.search(r'(?ms)^##\s+Citations\s*\n(.*)', body)
    citations = []
    for line in citation_section[1].splitlines() if citation_section else []:
        path = line.strip().removeprefix('- ').strip()
        match = re.search(r'/segments/([^/]+)/events\.jsonl$', path)
        if match:
            rid = digest(['skysight-raw', match[1] + '/metadata.json'])
            citations.append({'path': path, 'record_id': rid, 'content_id': object_id(PROCESSOR, 'skysight-raw', rid), 'availability': 'resolve_on_open'})
        elif path: citations.append({'path': path, 'availability': 'source_reference'})
    return content(row, 'activity', 'activity_summary', meta.get('title') or '电脑活动摘要', blocks,
        {'description': meta.get('description'), 'applications': meta.get('applications', []), 'interval': n.get('interval'),
         'source_ref': n.get('source_ref'), 'source_citations': citations, 'format': 'markdown',
         'origin': 'upstream_model', 'body_chars': len(body) - offset, 'active_duration_seconds': None,
         'coverage_interval': None, 'count_as_duration': False},
        warnings=['summary_interval_is_not_active_duration'], coverage={'body': 'complete', 'activity': 'upstream_summary'})
