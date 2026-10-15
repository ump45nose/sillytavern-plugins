"""CRM native changes and archive share one transaction; reconciliation is repair only."""
from sqlalchemy import event, select

from .contracts import Batch, Record, canonical, digest, instant

TABLES = ('people', 'interactions', 'facts', 'reminders', 'sync_clients')


def record_for(name, raw):
    import json
    raw = json.loads(canonical(dict(raw)))
    eid = 'client:' + digest([raw['source'], raw['client_id']]) if name == 'sync_clients' else name + ':' + raw['id']
    return Record(eid, name, raw, {'table': name},
                  instant(raw.get('occurred_at', raw.get('observed_at', raw.get('created_at')))),
                  instant(raw.get('updated_at')))


def install_mirror(repository):
    """Capture ORM flushes, including DB cascades, on this repository's sessions only."""
    from personal_crm.storage.models import Base, Fact, Interaction, Person, Reminder
    store = repository.hub_store

    @event.listens_for(repository._sessions, 'before_flush')
    def remember(session, context, instances):
        c = session.connection()
        if c.dialect.name == 'postgresql':
            # Acquire before native writes too: archive purges use this order.
            with store.writer_lock(c):
                pass
        changed = [e for e in session.new | session.dirty
                   if e.__tablename__ in TABLES and (e in session.new or session.is_modified(e, include_collections=False))]
        deleted = [e for e in session.deleted if e.__tablename__ in TABLES]
        removals, dependents = [], {'facts': set(), 'reminders': set()}
        for entity in deleted:
            raw = repository.to_dict(entity)
            removals.append(record_for(entity.__tablename__, raw).external_id)
            interactions = [raw] if isinstance(entity, Interaction) else []
            if isinstance(entity, Person):
                for name in ('interactions', 'facts', 'reminders'):
                    table = Base.metadata.tables[name]
                    for child in c.execute(select(table).where(table.c.person_id == entity.id)).mappings():
                        removals.append(record_for(name, child).external_id)
                        if name == 'interactions': interactions.append(child)
            for interaction in interactions:
                removals.extend(store.crm_event_aliases(interaction['source_type'], interaction['source_event_key'], interaction['source_message_key']))
                dependents['facts'].update(c.scalars(select(Fact.id).where(Fact.source_interaction_id == interaction['id'])))
                dependents['reminders'].update(c.scalars(select(Reminder.id).where(Reminder.completion_interaction_id == interaction['id'])))
        session.info['hub_flush'] = changed, removals, dependents

    @event.listens_for(repository._sessions, 'after_flush_postexec')
    def mirror(session, context):
        changed, removals, dependents = session.info.pop('hub_flush')
        c = session.connection()
        archive = [record_for(e.__tablename__, repository.to_dict(e)) for e in changed]
        # ON DELETE SET NULL is performed by the database, not the ORM.
        for name, identifiers in dependents.items():
            if identifiers:
                table = Base.metadata.tables[name]
                archive.extend(record_for(name, r) for r in c.execute(
                    select(table).where(table.c.id.in_(identifiers))).mappings())
        if archive or removals:
            result = store.ingest('crm', Batch(records=archive, deletions=removals), connection=c, refresh_unchanged=False)
            if result['tombstoned']:
                raise ValueError('crm_record_previously_deleted')


def reconcile(store, batch_size=100):
    """Repair current native rows in short transactions; never apply an old snapshot."""
    from sqlalchemy import tuple_
    from personal_crm.storage.models import Base
    from .storage import records
    totals = dict(changed=0, duplicates=0, tombstoned=0, deleted=0)

    def add(result):
        for key in totals: totals[key] += result[key]

    for name in TABLES:
        table = Base.metadata.tables[name]
        columns = list(table.primary_key.columns)
        after = None
        while True:
            with store.engine.begin() as c, store.writer_lock(c):
                statement = select(table).order_by(*columns).limit(batch_size)
                if after is not None:
                    statement = statement.where(tuple_(*columns) > tuple_(*after))
                rows = list(c.execute(statement).mappings())
                if rows:
                    add(store.ingest('crm', Batch(records=[record_for(name, row) for row in rows]),
                                     connection=c, refresh_unchanged=False))
                    after = tuple(rows[-1][col.name] for col in columns)
            if len(rows) < batch_size: break

        # Check each archived candidate against the native table in the SAME
        # short transaction. Concurrent mirrors cannot be mistaken for deletion.
        after_id = ''
        while True:
            with store.engine.begin() as c, store.writer_lock(c):
                rows = list(c.execute(select(records.c.id, records.c.external_id, records.c.raw).where(
                    records.c.source == 'crm', records.c.kind == name, records.c.id > after_id)
                    .order_by(records.c.id).limit(batch_size)).mappings())
                if rows:
                    keys = [tuple(row['raw'][col.name] for col in columns) for row in rows]
                    live = set(c.execute(select(*columns).where(tuple_(*columns).in_(keys))).all())
                    missing = [row['external_id'] for row, key in zip(rows, keys) if key not in live]
                    if missing:
                        add(store.ingest('crm', Batch(deletions=missing), connection=c, refresh_unchanged=False))
                    after_id = rows[-1]['id']
            if len(rows) < batch_size: break
    return totals
