"""One-way import of old host settings and durable intents, with no side effects."""
from copy import deepcopy
from .runtime import AcquisitionSettings


def settings_from_legacy(current, legacy):
    keys = set(AcquisitionSettings.__dataclass_fields__) - {'enabled'}
    return {**{key: legacy[key] for key in keys if key in legacy}, **current}


def migrate_registry(registry, legacy_state, legacy_records):
    with registry.lock:
        state = registry.store.read()
        jobs, resources = state.setdefault('jobs', {}), state.setdefault('resources', {})
        for task_id, row in (legacy_state.get('jobs') or {}).items():
            jobs.setdefault(task_id, deepcopy(row))
        for key, task_id in (legacy_state.get('resources') or {}).items():
            if task_id in jobs:
                resources.setdefault(key, task_id)
        for film_id, record in legacy_records.items():
            if record.get('task_state') not in ('SUBMITTING', 'SUBMITTED') and not record.get('download_hash'):
                continue
            route = record.get('route') or 'pt'
            key = record.get('info_hash') or record.get('download_hash')
            if not key and route == '115_share' and record.get('candidate_id'):
                from .public_index import Mini4KIndexer
                key = 'share-candidate:' + Mini4KIndexer.comparable_candidate_id(record['candidate_id'])
            if not key:
                continue
            task_id = 'legacy-film-' + str(film_id)
            facts = {k: deepcopy(record[k]) for k in ('info_hash', 'download_hash', 'media_type',
                'target_path', 'candidate_id') if k in record}
            facts.update(route=route, task_id=task_id,
                         root_names=deepcopy(record.get('share_root_names') or []),
                         status='submitted' if record.get('task_state') == 'SUBMITTED'
                             or record.get('download_hash') else 'pending',
                         phase='submitted' if record.get('task_state') == 'SUBMITTED'
                             or record.get('download_hash') else 'submitting')
            jobs.setdefault(task_id, facts)
            resources.setdefault(key, task_id)
        registry.store.write(state)
