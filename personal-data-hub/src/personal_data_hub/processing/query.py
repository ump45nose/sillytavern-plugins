from __future__ import annotations

import base64
import json

from sqlalchemy import exists, func, or_, select, text

from ..contracts import canonical, instant
from .contracts import PAGE_BYTES
from .schema import blocks, inputs, objects


class ContentChanged(ValueError): pass
class ContentRemoved(ValueError): pass


def head(row, detail=False):
    identifier = row['id']
    result = {k: row[k] for k in ('id', 'type', 'variant', 'schema_version', 'revision', 'source', 'account',
                                  'scope_key', 'occurred_at', 'timezone', 'title', 'preview', 'summary', 'warnings', 'coverage')}
    result['processing'] = {'state': row['state'], 'published_at': row['published_at']}
    result['business_date'] = row['business_date']
    result['content'] = f'/api/v1/contents/{identifier}/blocks'
    result['evidence'] = f'/api/v1/contents/{identifier}/evidence'
    if detail:
        result['metadata'] = row['details']
        result['assets'] = row['details'].get('assets', [])
    return result


class ReadingQuery:
    def __init__(self, store): self.store = store

    def page(self, source=None, variant=None, query='', cursor=None, limit=50, start=None, end=None, content_type=None):
        if not 1 <= limit <= 50 or len(query) > 200 or (cursor and len(cursor) > 4096):
            raise ValueError('invalid_content_parameters')
        conditions = []
        filters = [source, variant, query, str(start), str(end)] + ([content_type] if content_type is not None else [])
        if content_type: conditions.append(objects.c.type == content_type)
        if variant != 'wechat_insights' and content_type != 'analysis': conditions.append(objects.c.type != 'analysis')
        if source: conditions.append(objects.c.source == source)
        if variant: conditions.append(objects.c.variant == variant)
        elif not source and content_type != 'status':
            conditions.extend((objects.c.variant.not_in(('execution_log', 'activity_observations')), objects.c.type != 'status'))
        if start: conditions.append(objects.c.occurred_at >= start)
        if end: conditions.append(objects.c.occurred_at < end)
        if query:
            conditions.append(objects.c.state == 'ready')
            # Find matching bodies once through the text index, rather than reading
            # every object's blocks in a separate correlated search.
            if len(query) < 3:
                # A one/two-character substring has no internal trigram. Search
                # the eligible objects' blocks, not the entire trigram index.
                if self.store.engine.dialect.name == 'postgresql':
                    object_body = select(blocks.c.object_id, blocks.c.search_text).where(
                        blocks.c.object_id == objects.c.id).offset(0).correlate(objects).lateral('object_body')
                    body_match = exists(select(object_body.c.object_id).where(
                        object_body.c.search_text.icontains(query, autoescape=True)))
                else:
                    body_match = exists(select(blocks.c.object_id).where(blocks.c.object_id == objects.c.id,
                        blocks.c.search_text.icontains(query, autoescape=True)))
            else:
                matching_bodies = select(blocks.c.object_id).join(objects, objects.c.id == blocks.c.object_id).where(
                    *conditions, blocks.c.search_text.icontains(query, autoescape=True)).distinct().cte(
                        'matching_bodies').prefix_with('MATERIALIZED', dialect='postgresql')
                body_match = objects.c.id.in_(select(matching_bodies.c.object_id))
            conditions.append(or_(objects.c.title.icontains(query, autoescape=True),
                                  objects.c.preview.icontains(query, autoescape=True), body_match))
        if cursor:
            try:
                parsed = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if set(parsed) != {'time', 'id', 'filters'} or parsed['filters'] != filters:
                    raise ValueError()
                when, key = instant(parsed['time']), parsed['id']
                if not isinstance(key, str) or len(key) != 64: raise ValueError()
                if when is None:
                    conditions.append(objects.c.occurred_at.is_(None) & (objects.c.id > key))
                else:
                    conditions.append(or_(objects.c.occurred_at < when, objects.c.occurred_at.is_(None),
                                          (objects.c.occurred_at == when) & (objects.c.id > key)))
            except (ValueError, TypeError, KeyError, UnicodeError):
                raise ValueError('invalid_content_cursor') from None
        # Exclude full metadata (attachments and relations) from list responses.
        columns = [col for col in objects.c if col.name != 'details']
        with self.store.engine.connect() as c:
            if c.dialect.name == 'postgresql':
                c = c.execution_options(isolation_level='REPEATABLE READ')
            with c.begin():
                if query and c.dialect.name == 'postgresql':
                    c.execute(text("SET LOCAL work_mem = '64MB'"))
                rows = list(c.execute(select(*columns).where(*conditions)
                    .order_by(objects.c.occurred_at.desc().nulls_last(), objects.c.id).limit(limit + 1)).mappings())
                page = [head(row) for row in rows[:limit]]
                if query and page:
                    # Fetch the first hit for the selected page together. Two scalar
                    # lookups per result repeatedly scanned the same trigram postings.
                    page_body = select(blocks.c.object_id, blocks.c.ordinal, blocks.c.search_text).where(
                        blocks.c.object_id.in_([item['id'] for item in page])).cte('page_body').prefix_with(
                            'MATERIALIZED', dialect='postgresql')
                    hits = select(page_body.c.object_id, page_body.c.ordinal, page_body.c.search_text,
                        func.row_number().over(partition_by=page_body.c.object_id,
                            order_by=page_body.c.ordinal).label('rank')).where(
                        page_body.c.search_text.icontains(query, autoescape=True)).subquery()
                    matches = {row.object_id: row for row in c.execute(select(hits).where(hits.c.rank == 1))}
                    for item in page:
                        if item['id'] in matches:
                            row = matches[item['id']]
                            offset = max(0, row.search_text.lower().find(query.lower()) - 100)
                            item['match'] = {'ordinal': row.ordinal, 'excerpt': row.search_text[offset:offset + 500]}
        next_cursor = None
        if len(rows) > limit:
            row = rows[limit-1]
            next_cursor = base64.urlsafe_b64encode(canonical({'time': instant(row['occurred_at']), 'id': row['id'],
                'filters': filters}).encode()).decode()
        return {'schema_version': 1, 'items': page, 'next_cursor': next_cursor, 'pagination': 'live_keyset'}

    def detail(self, identifier):
        with self.store.engine.connect() as c:
            row = c.execute(select(objects).where(objects.c.id == identifier)).mappings().first()
            return head(row, detail=True) if row else None

    def block_page(self, identifier, revision, after=-1, limit=50):
        if revision < 0 or after < -1 or not 1 <= limit <= 50:
            raise ValueError('invalid_block_parameters')
        # One SQL statement ties the body to the head revision/state. In PostgreSQL READ
        # COMMITTED, two separate SELECTs could straddle a concurrent delete/republication.
        joined = objects.outerjoin(blocks, (blocks.c.object_id == objects.c.id) & (blocks.c.ordinal > after))
        columns = [objects.c.revision.label('head_revision'), objects.c.state.label('head_state'),
                   blocks.c.ordinal, blocks.c.key, blocks.c.type, blocks.c.text, blocks.c.refs, blocks.c.details]
        with self.store.engine.connect() as c:
            rows = list(c.execute(select(*columns).select_from(joined).where(objects.c.id == identifier)
                                  .order_by(blocks.c.ordinal).limit(limit + 1)).mappings())
        if not rows: raise ContentRemoved('content_removed')
        if rows[0]['head_revision'] != revision or rows[0]['head_state'] == 'stale':
            raise ContentChanged('content_changed')
        result, budget = [], 1024
        has_more = False
        for row in rows:
            if row['ordinal'] is None: continue
            block = dict(key=row['key'], ordinal=row['ordinal'], type=row['type'], text=row['text'],
                         refs=row['refs'], metadata=row['details'])
            size = len(canonical(block).encode('utf-8')) + 1
            if len(result) == limit or budget + size > PAGE_BYTES:
                has_more = True; break
            result.append(block); budget += size
        if not result and has_more: raise ValueError('block_exceeds_page_budget')
        return {'id': identifier, 'revision': revision, 'blocks': result,
                'next_after': result[-1]['ordinal'] if has_more else None}

    def evidence(self, identifier, revision=None, after=None, limit=100):
        from ..storage import records
        if not 1 <= limit <= 100 or (after is not None and (len(after) != 64 or any(ch not in '0123456789abcdef' for ch in after))):
            raise ValueError('invalid_evidence_parameters')
        on = inputs.c.object_id == objects.c.id
        if after is not None: on &= inputs.c.record_id > after
        joined = objects.outerjoin(inputs, on).outerjoin(records, records.c.id == inputs.c.record_id)
        with self.store.engine.connect() as c:
            rows = list(c.execute(select(objects.c.revision, objects.c.state, inputs.c.record_id, inputs.c.input_hash,
                                         records.c.hash.label('current_hash')).select_from(joined)
                                  .where(objects.c.id == identifier).order_by(inputs.c.record_id).limit(limit + 1)).mappings())
        if not rows: return None
        if revision is not None and (rows[0]['revision'] != revision or rows[0]['state'] != 'ready'):
            raise ContentChanged('content_changed')
        return {'id': identifier, 'revision': rows[0]['revision'], 'inputs': [
            {'record_id': r['record_id'], 'input_hash': r['input_hash'], 'current_hash': r['current_hash'],
             'current_matches': r['input_hash'] == r['current_hash'], 'record': '/api/v1/records/' + r['record_id']}
            for r in rows[:limit] if r['record_id'] is not None],
            'next_after': rows[limit-1]['record_id'] if len(rows) > limit else None}

    def insights(self, identifier, revision, model=None):
        from .contracts import object_id
        from . import insights
        from .schema import jobs
        from ..contracts import digest
        with self.store.engine.connect() as connection:
            c = connection.execution_options(isolation_level='REPEATABLE READ') if connection.dialect.name == 'postgresql' else connection
            with c.begin():
                parent = c.execute(select(objects).where(objects.c.id == identifier)).mappings().first()
                if parent is None: raise ContentRemoved('content_removed')
                if parent['type'] != 'conversation': raise ValueError('not_a_conversation')
                if parent['revision'] != revision or parent['state'] != 'ready': raise ContentChanged('content_changed')
                key = object_id(insights.PROCESSOR, parent['source'], parent['scope_key'])
                job = c.execute(select(jobs).where(jobs.c.id == key)).mappings().first()
                result = {'id': identifier, 'revision': revision, 'state': job['state'] if job else 'pending',
                          'result': None, 'error_code': job['error_code'] if job else None}
                analysis = c.execute(select(objects).where(objects.c.id == key)).mappings().first()
                if result['state'] == 'ready':
                    if analysis is None:
                        result['state'] = 'not_needed'
                    else:
                        frozen = sorted(tuple(row) for row in c.execute(select(inputs.c.record_id, inputs.c.input_hash).where(inputs.c.object_id == identifier)))
                        if analysis['state'] != 'ready' or analysis['details']['input_fingerprint'] != digest(frozen):
                            result['state'] = 'stale'
                        elif model and analysis['details']['model'] != model:
                            result['state'] = 'model_changed'
                        else:
                            result['result'] = analysis['details'] | {'summary': analysis['summary'], 'warnings': analysis['warnings']}
                return result
