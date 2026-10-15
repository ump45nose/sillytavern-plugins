from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from sqlalchemy import delete, func, insert, or_, select, text, union_all, update

from ..contracts import instant, utcnow
from ..storage import active_sources
from .contracts import SCHEMA_VERSION, object_id
from .registry import PROFILES, COLLECTION_PROFILES, routes, scopes, header
from .schema import blocks, inputs, jobs, members, model_results, objects


class ProcessingRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def eligible(now):
        return or_((jobs.c.state == 'pending') & (jobs.c.retry_at.is_(None) | (jobs.c.retry_at <= now)),
                   (jobs.c.state == 'failed') & (jobs.c.attempts < 5) & (jobs.c.retry_at <= now),
                   (jobs.c.state == 'running') & (jobs.c.lease_until <= now))

    def has_pending(self, lane='reading'):
        processors = [name for name, profile in PROFILES.items() if getattr(profile, 'LANE', 'reading') == lane]
        with self.store.engine.connect() as c:
            return c.scalar(select(jobs.c.id).where(self.eligible(utcnow()), jobs.c.processor.in_(processors), jobs.c.source.in_(active_sources())).limit(1)) is not None

    def affected(self, c, record_id):
        result = {(r.processor, r.source, r.scope_key) for r in c.execute(
            select(jobs.c.processor, jobs.c.source, jobs.c.scope_key).join(inputs, inputs.c.object_id == jobs.c.id)
            .where(inputs.c.record_id == record_id, jobs.c.processor.in_(PROFILES), jobs.c.source.in_(active_sources())))}
        result.update((r.processor, r.source, r.scope_key) for r in c.execute(
            select(jobs.c.processor, jobs.c.source, jobs.c.scope_key).join(members, members.c.job_id == jobs.c.id)
            .where(members.c.record_id == record_id, jobs.c.processor.in_(PROFILES), jobs.c.source.in_(active_sources()))))
        return result

    def enqueue(self, c, processor, source, scope_key):
        identifier = object_id(processor, source, scope_key)
        profile = PROFILES[processor]
        old = c.execute(select(jobs).where(jobs.c.id == identifier).with_for_update()).mappings().first()
        now = utcnow()
        c.execute(delete(model_results).where(model_results.c.job_id == identifier))
        if old:
            c.execute(update(jobs).where(jobs.c.id == identifier).values(
                desired_generation=old['desired_generation'] + 1, profile_version=profile.PROFILE_VERSION,
                state='running' if old['lease_token'] else 'pending', attempts=0, retry_at=None,
                error_code=None, updated_at=now))
            c.execute(update(objects).where(objects.c.id == identifier).values(state='stale'))
        else:
            c.execute(insert(jobs).values(id=identifier, processor=processor, source=source, scope_key=scope_key,
                desired_generation=1, published_generation=0, profile_version=profile.PROFILE_VERSION,
                state='pending', attempts=0, updated_at=now))
        return identifier

    def changed(self, c, row, processors=None):
        # Full dependency lookup also covers future aggregate profiles and kind changes.
        affected = self.affected(c, row['id'])
        new_routes = set(routes(row))
        affected.update((processor, row['source'], scope) for processor, scope in new_routes)
        if processors is not None:
            affected = {route for route in affected if route[0] in processors}
            new_routes = {route for route in new_routes if route[0] in processors}
        affected_ids = [object_id(processor, source, scope) for processor, source, scope in affected]
        c.execute(delete(members).where(members.c.record_id == row['id'], members.c.job_id.in_(affected_ids)))
        for processor, source, scope in sorted(affected):
            identifier = self.enqueue(c, processor, source, scope)
            if (processor, scope) in new_routes:
                c.execute(insert(members).values(job_id=identifier, record_id=row['id']))
            if (processor, scope) in new_routes and getattr(PROFILES[processor], 'LANE', 'reading') == 'reading':
                if c.scalar(select(objects.c.id).where(objects.c.id == identifier)) is None:
                    from ..storage import sources
                    account = c.scalar(select(sources.c.account).where(sources.c.id == source)) or 'unregistered'
                    typ, variant = header(PROFILES[processor], row, scope)
                    c.execute(insert(objects).values(id=identifier, processor=processor, source=source, account=account,
                        scope_key=scope, type=typ, variant=variant, schema_version=SCHEMA_VERSION,
                        revision=0, generation=0, occurred_at=row['occurred_at'], timezone=row['timezone'],
                        title=row['kind'], preview='', state='pending', details={}, warnings=[], coverage={}))

    def removed(self, c, record_id):
        affected = self.affected(c, record_id)
        c.execute(delete(members).where(members.c.record_id == record_id))
        for processor, source, scope in sorted(affected):
            identifier = self.enqueue(c, processor, source, scope)
            # Withdraw all derived content before source/dependency deletion, including search.
            c.execute(delete(blocks).where(blocks.c.object_id == identifier))
            c.execute(delete(inputs).where(inputs.c.object_id == identifier))
            c.execute(delete(objects).where(objects.c.id == identifier))

    def claim(self, lease_seconds=120, lane='reading'):
        now = utcnow()
        eligible = self.eligible(now)
        guard = self.store.writer_lock() if self.store.engine.dialect.name == 'sqlite' else nullcontext()
        with guard, self.store.engine.begin() as c:
            processors = [name for name, profile in PROFILES.items() if getattr(profile, 'LANE', 'reading') == lane]
            statement = select(jobs).where(eligible, jobs.c.processor.in_(processors), jobs.c.source.in_(active_sources())).order_by(jobs.c.updated_at, jobs.c.id).limit(1).with_for_update(skip_locked=True)
            job = c.execute(statement).mappings().first()
            if not job:
                return None
            job = dict(job)
            token = str(uuid4())
            c.execute(update(jobs).where(jobs.c.id == job['id']).values(state='running', lease_token=token,
                lease_until=now + timedelta(seconds=lease_seconds), attempts=job['attempts'] + 1))
            c.execute(update(objects).where(objects.c.id == job['id'], objects.c.revision == 0).values(state='running'))
            return job | {'lease_token': token, 'attempts': job['attempts'] + 1}

    def snapshot(self, job):
        from ..storage import records
        profile = PROFILES[job['processor']]
        with self.store.engine.connect() as connection:
            c = connection.execution_options(isolation_level='REPEATABLE READ') if connection.dialect.name == 'postgresql' else connection
            with c.begin():
                rows = [dict(row) for row in c.execute(select(records).join(members, members.c.record_id == records.c.id)
                    .where(members.c.job_id == job['id'], records.c.source == job['source'])).mappings()]
                rows = [row for row in rows if profile.accepts(row) and job['scope_key'] in scopes(profile, row)]
                if 'people' in getattr(profile, 'DEPENDENCY_KINDS', ()):
                    people_ids = [self.store.identity(job['source'], 'people:' + str(row['raw']['person_id']))
                                  for row in rows if row['raw'].get('person_id')]
                    rows.extend(dict(row) for row in c.execute(select(records).where(records.c.id.in_(people_ids))).mappings())
                if hasattr(profile, 'dependency_ids'):
                    ids = set(profile.dependency_ids(rows)) - {row['id'] for row in rows}
                    rows.extend(dict(row) for row in c.execute(select(records).where(records.c.id.in_(ids))).mappings())
                return rows

    def publish(self, job, rows, content):
        try:
            return self._publish(job, rows, content)
        except OperationalError as exc:
            if getattr(exc.orig, 'sqlstate', None) != '55P03':
                raise
            # An input is being edited. NOWAIT avoids a job/input lock cycle;
            # give the job back without consuming the failure retry budget.
            with self.store.engine.begin() as c:
                c.execute(update(jobs).where(jobs.c.id == job['id'], jobs.c.lease_token == job['lease_token']).values(
                    state='pending', lease_token=None, lease_until=None, attempts=jobs.c.attempts - 1,
                    retry_at=utcnow() + timedelta(seconds=5), updated_at=utcnow()))
            return False

    def _publish(self, job, rows, content):
        from ..storage import records, sources
        # Ingest and deletion enqueue while holding this same job row. The
        # generation check therefore serializes publication with invalidation;
        # Input locks use NOWAIT so a concurrent edit cannot create a lock cycle.
        # Publishing unrelated content does not take the archive/asset lock.
        guard = self.store.writer_lock() if self.store.engine.dialect.name == 'sqlite' else nullcontext()
        with guard, self.store.engine.begin() as c:
            if c.dialect.name == 'postgresql':
                c.execute(text("SET LOCAL statement_timeout = '60s'"))
            current = c.execute(select(jobs).where(jobs.c.id == job['id']).with_for_update()).mappings().one()
            if current['lease_token'] != job['lease_token']:
                return False
            expected = {r['id']: r['hash'] for r in rows}
            present = dict(c.execute(select(records.c.id, records.c.hash).where(records.c.id.in_(expected))
                .order_by(records.c.id).with_for_update(read=True, nowait=True)).all()) if expected else {}
            current_members = set(c.scalars(select(members.c.record_id).where(members.c.job_id == job['id'])))
            frozen_members = {r['id'] for r in rows if PROFILES[job['processor']].accepts(r) and job['scope_key'] in scopes(PROFILES[job['processor']], r)}
            profile = PROFILES[job['processor']]
            valid = (current['desired_generation'] == job['desired_generation']
                     and current['profile_version'] == job['profile_version'] == profile.PROFILE_VERSION
                     and instant(current['lease_until']) > utcnow() and present == expected
                     and current_members == frozen_members)
            if not valid:
                c.execute(update(jobs).where(jobs.c.id == job['id']).values(state='pending', lease_token=None, lease_until=None))
                return False
            identifier = job['id']
            if content is None:
                c.execute(delete(blocks).where(blocks.c.object_id == identifier))
                c.execute(delete(inputs).where(inputs.c.object_id == identifier))
                c.execute(delete(objects).where(objects.c.id == identifier))
            else:
                row = rows[0]
                account = c.scalar(select(sources.c.account).where(sources.c.id == job['source'])) or 'unregistered'
                values = dict(id=identifier, processor=job['processor'], scope_key=job['scope_key'], source=job['source'],
                    account=account, type=content.type, variant=content.variant, schema_version=SCHEMA_VERSION,
                    revision=job['desired_generation'], generation=job['desired_generation'], occurred_at=instant(content.metadata.get('started_at')) if 'started_at' in content.metadata else row['occurred_at'],
                    timezone=content.metadata.get('timezone', row['timezone']), title=content.title, preview=content.preview, summary=content.summary,
                    business_date=content.metadata.get('business_date'),
                    state='ready', details=content.metadata, warnings=content.warnings, coverage=content.coverage, published_at=utcnow())
                if c.scalar(select(objects.c.id).where(objects.c.id == identifier)):
                    c.execute(update(objects).where(objects.c.id == identifier).values(**values))
                else:
                    c.execute(insert(objects).values(**values))
                # Unchanged blocks and input links do not churn the text index.
                old_blocks = {r['ordinal']: dict(r) for r in c.execute(select(blocks).where(blocks.c.object_id == identifier)).mappings()}
                replacements = []
                for i, b in enumerate(content.blocks):
                    value = dict(object_id=identifier, ordinal=i, key=b.key, type=b.type,
                        text=b.text, refs=b.refs, details=b.metadata,
                        search_text=(content.blocks[i-1].text[-200:] if i and (b.type != 'message' or b.metadata.get('continuation')) else '') + b.text)
                    old = old_blocks.get(i)
                    if old is None or any(old[k] != v for k, v in value.items()):
                        replacements.append(dict(value, revision=values['revision']))
                removed = set(old_blocks) - set(range(len(content.blocks)))
                replaced = {b['ordinal'] for b in replacements} & old_blocks.keys()
                if removed or replaced:
                    c.execute(delete(blocks).where(blocks.c.object_id == identifier, blocks.c.ordinal.in_(removed | replaced)))
                if replacements:
                    c.execute(insert(blocks), replacements)
                old_inputs = dict(c.execute(select(inputs.c.record_id, inputs.c.input_hash).where(inputs.c.object_id == identifier)).all())
                obsolete = {key for key, value in old_inputs.items() if expected.get(key) != value}
                if obsolete:
                    c.execute(delete(inputs).where(inputs.c.object_id == identifier, inputs.c.record_id.in_(obsolete)))
                new_inputs = [dict(object_id=identifier, record_id=key, input_hash=value)
                              for key, value in expected.items() if old_inputs.get(key) != value]
                if new_inputs:
                    c.execute(insert(inputs), new_inputs)
            c.execute(update(jobs).where(jobs.c.id == identifier).values(published_generation=job['desired_generation'],
                state='ready', lease_token=None, lease_until=None, retry_at=None, error_code=None, updated_at=utcnow()))
            return True

    def fail(self, job, error):
        # Exception text may include private body text. Expose only stable, known error codes.
        allowed = {'conversation_scope_mismatch',
                   'model_not_configured', 'model_response_invalid', 'model_citation_invalid', 'model_response_too_large',
                   'model_budget_exceeded', 'model_credential_missing', 'model_incomplete_response', 'model_input_too_large'}
        import re
        code = str(error) if str(error) in allowed or re.fullmatch(r'model_http_[1-5][0-9]{2}', str(error)) else type(error).__name__
        with self.store.engine.begin() as c:
            current = c.execute(select(jobs).where(jobs.c.id == job['id']).with_for_update()).mappings().one()
            if current['lease_token'] != job['lease_token']:
                return
            superseded = current['desired_generation'] != job['desired_generation']
            c.execute(update(jobs).where(jobs.c.id == job['id']).values(state='pending' if superseded else 'failed',
                lease_token=None, lease_until=None, error_code=None if superseded else code,
                attempts=max(0, current['attempts'] - 1) if code == 'model_budget_exceeded' else current['attempts'],
                retry_at=(utcnow().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)) if code == 'model_budget_exceeded'
                         else utcnow() + timedelta(seconds=min(3600, 30 * 2 ** min(job['attempts'], 7)))))
            if not superseded:
                c.execute(update(objects).where(objects.c.id == job['id'], objects.c.revision == 0).values(state='failed'))

    def rebuild(self, source=None, force=False, after=None, limit=250, processor=None, background_page=False):
        """Stable-ID backfill, bounded transaction; enable ingest hooks before scanning."""
        from ..storage import checkpoints, records
        if not 1 <= limit <= 1000:
            raise ValueError('invalid_pagination')
        if processor is not None and processor not in PROFILES: raise ValueError('unknown_processor')
        selected = {processor} if processor else set(COLLECTION_PROFILES)
        kinds = {kind for name, profile in PROFILES.items() if name in selected for kind in profile.KINDS}
        with self.store.writer_lock(), self.store.engine.begin() as c:
            scan_all = True
            if background_page:
                profile_versions = {name: profile.PROFILE_VERSION for name, profile in COLLECTION_PROFILES.items()}
                progress = c.scalar(select(checkpoints.c.value).where(checkpoints.c.source == 'processing:reading-backfill')) or {}
                scan_all = progress.get('scan_all', progress.get('profiles') != profile_versions)
                if progress.get('profiles') != profile_versions:
                    progress = {}
                    scan_all = True
                if progress.get('complete'):
                    return {'enqueued': 0, 'scanned': 0, 'next_after': None, 'complete': True}
                after = progress.get('after')
            branches = []
            for kind in sorted(kinds):
                branch = select(records.c.id).where(records.c.kind == kind, records.c.source.in_(active_sources())).order_by(records.c.id).limit(limit + 1)
                if source: branch = branch.where(records.c.source == source)
                if after: branch = branch.where(records.c.id > after)
                branch = branch.subquery()
                branches.append(select(branch.c.id))
            identifiers = union_all(*branches).subquery()
            keys = list(c.scalars(select(identifiers.c.id).order_by(identifiers.c.id).limit(limit + 1)))
            body_keys = keys[:limit]
            if background_page and not scan_all and not force and body_keys:
                # Ingest saves routing links transactionally. With the same rule
                # versions, existing links do not need the original JSON again.
                metadata_rows = list(c.execute(select(records.c.id, records.c.kind).where(records.c.id.in_(body_keys))))
                kinds_by_id = {row.id: row.kind for row in metadata_rows}
                linked = list(c.execute(select(members.c.record_id, jobs.c.processor, jobs.c.profile_version)
                    .join(jobs, jobs.c.id == members.c.job_id).where(members.c.record_id.in_(body_keys), jobs.c.processor.in_(selected))))
                covered, outdated = set(), set()
                for link in linked:
                    profile = PROFILES[link.processor]
                    if link.profile_version != profile.PROFILE_VERSION:
                        outdated.add(link.record_id)
                    elif kinds_by_id[link.record_id] in profile.KINDS:
                        covered.add(link.record_id)
                body_keys = [key for key in body_keys if key not in covered or key in outdated]
            rows = list(c.execute(select(records).where(records.c.id.in_(body_keys)).order_by(records.c.id)).mappings()) if body_keys else []
            batch = rows[:limit]
            wanted, record_routes = {}, {}
            for row in batch:
                for name, scope_key in routes(row):
                    if name not in selected: continue
                    key = object_id(name, row['source'], scope_key)
                    wanted[key] = (name, row['source'], scope_key, row)
                    record_routes.setdefault(row['id'], set()).add(key)
            existing_jobs = {r.id: r.profile_version for r in c.execute(select(jobs.c.id, jobs.c.profile_version).where(jobs.c.id.in_(wanted)))} if wanted else {}
            links = list(c.execute(select(members.c.record_id, members.c.job_id, jobs.c.processor, jobs.c.source, jobs.c.scope_key)
                .join(jobs, jobs.c.id == members.c.job_id).where(members.c.record_id.in_(record_routes), jobs.c.processor.in_(selected)))) if record_routes else []
            existing_links = {(r.record_id, r.job_id) for r in links}
            repair = {rid for rid, keys in record_routes.items() if force or any(
                (rid, key) not in existing_links or existing_jobs.get(key) != PROFILES[wanted[key][0]].PROFILE_VERSION for key in keys)}
            affected = {key: wanted[key][:3] for rid in repair for key in record_routes[rid]}
            affected.update({r.job_id: (r.processor, r.source, r.scope_key) for r in links if r.record_id in repair})
            if affected:
                c.execute(delete(members).where(members.c.record_id.in_(repair), members.c.job_id.in_(affected)))
                from ..storage import sources
                accounts = dict(c.execute(select(sources.c.id, sources.c.account).where(sources.c.id.in_({source_id for _, source_id, _ in affected.values()}))).all())
                existing_objects = set(c.scalars(select(objects.c.id).where(objects.c.id.in_(affected))))
                for key, (name, source_id, scope_key) in sorted(affected.items()):
                    self.enqueue(c, name, source_id, scope_key)
                    if key not in wanted or key in existing_objects or getattr(PROFILES[name], 'LANE', 'reading') != 'reading': continue
                    row = wanted[key][3]
                    typ, variant = header(PROFILES[name], row, scope_key)
                    c.execute(insert(objects).values(id=key, processor=name, source=source_id,
                        account=accounts.get(source_id, 'unregistered'), scope_key=scope_key,
                        type=typ, variant=variant,
                        schema_version=SCHEMA_VERSION, revision=0, generation=0, occurred_at=row['occurred_at'],
                        timezone=row['timezone'], title=row['kind'], preview='', state='pending', details={}, warnings=[], coverage={}))
                new_links = [dict(job_id=key, record_id=rid) for rid in repair for key in record_routes[rid]]
                if new_links: c.execute(insert(members), new_links)
            result = {'enqueued': len(affected), 'scanned': min(len(keys), limit),
                      'next_after': keys[limit-1] if len(keys) > limit else None}
            if background_page:
                result['complete'] = result['next_after'] is None
                value = {'profiles': profile_versions, 'after': result['next_after'], 'complete': result['complete'], 'scan_all': scan_all}
                values = dict(source='processing:reading-backfill', value=value, updated_at=utcnow())
                updated = c.execute(update(checkpoints).where(checkpoints.c.source == values['source']).values(**values))
                if not updated.rowcount: c.execute(insert(checkpoints).values(**values))
            return result

    def status(self):
        from ..storage import records
        with self.store.engine.connect() as c:
            counts = {r.state: r.count for r in c.execute(select(jobs.c.state, func.count().label('count')).where(jobs.c.processor.in_(COLLECTION_PROFILES), jobs.c.source.in_(active_sources())).group_by(jobs.c.state))}
            obj_counts = {r.state: r.count for r in c.execute(select(objects.c.state, func.count().label('count')).where(objects.c.processor.in_(COLLECTION_PROFILES), objects.c.source.in_(active_sources())).group_by(objects.c.state))}
            coverage = []
            for row in c.execute(select(records.c.source, records.c.kind, func.count().label('count')).where(records.c.source.in_(active_sources())).group_by(records.c.source, records.c.kind)):
                supported = any(row.kind in p.KINDS for p in COLLECTION_PROFILES.values())
                coverage.append(dict(source=row.source, kind=row.kind, records=row.count, supported=supported,
                    processors=[p.PROCESSOR for p in COLLECTION_PROFILES.values() if row.kind in p.KINDS],
                    reading_policy='unsupported' if not supported else 'auxiliary' if row.kind in ('recording_artifact','collector_meta','collector_gaps','sync_clients','computer_segment_invalid','recording_processing_status') else 'business' if supported else 'unsupported'))
            errors = [dict(r) for r in c.execute(select(jobs.c.id, jobs.c.source, jobs.c.state, jobs.c.error_code,
                jobs.c.attempts, jobs.c.retry_at).where(jobs.c.state == 'failed', jobs.c.processor.in_(COLLECTION_PROFILES), jobs.c.source.in_(active_sources())).order_by(jobs.c.updated_at).limit(50)).mappings()]
            lanes = {}
            for row in c.execute(select(jobs.c.processor, jobs.c.state, func.count().label('count')).where(jobs.c.processor.in_(COLLECTION_PROFILES), jobs.c.source.in_(active_sources())).group_by(jobs.c.processor, jobs.c.state)):
                lane = getattr(PROFILES.get(row.processor), 'LANE', 'reading')
                counts_for_lane = lanes.setdefault(lane, {})
                counts_for_lane[row.state] = counts_for_lane.get(row.state, 0) + row.count
        return {'schema_version': SCHEMA_VERSION, 'jobs': counts, 'objects': obj_counts,
                'profiles': {k: p.PROFILE_VERSION for k, p in COLLECTION_PROFILES.items()}, 'source_coverage': coverage, 'errors': errors,
                'lanes': lanes, 'deferred_processors': ['wechat-insights-v1']}
