from .registry import PROFILES
from .repository import ProcessingRepository


def drain(store, limit=50, lane='reading', config=None):
    if not 1 <= limit <= 1000:
        raise ValueError('invalid_processing_limit')
    repository = ProcessingRepository(store)
    result = {'claimed': 0, 'published': 0, 'superseded': 0, 'failed': 0}
    for _ in range(limit):
        # The scheduled reading worker ends at 120s; its lease must outlive that
        # deadline so it cannot discard an otherwise valid publication at 120s.
        job = repository.claim(lease_seconds=900 if lane == 'model' else 180, lane=lane)
        if job is None:
            break
        result['claimed'] += 1
        try:
            rows = repository.snapshot(job)
            profile = PROFILES[job['processor']]
            if rows and hasattr(profile, 'process_with_config'):
                content = profile.process_with_config(rows, store, job, config)
            elif rows and hasattr(profile, 'process_scope'):
                content = profile.process_scope(rows, job['scope_key'])
            else:
                content = profile.process(rows) if rows else None
            if repository.publish(job, rows, content): result['published'] += 1
            else: result['superseded'] += 1
            if content is not None and lane == 'model': break  # At most one model scope per subprocess.
        except Exception as error:
            repository.fail(job, error)
            result['failed'] += 1
    return result
