import time
from .registry import PROFILES
from .repository import ProcessingRepository


def drain(store, limit=50, lane='reading', config=None, max_seconds=None):
    if not 1 <= limit <= 1000:
        raise ValueError('invalid_processing_limit')
    deadline = time.monotonic() + max_seconds if max_seconds is not None else None
    repository = ProcessingRepository(store)
    result = {'claimed': 0, 'published': 0, 'superseded': 0, 'failed': 0}
    for _ in range(limit):
        if deadline is not None and time.monotonic() >= deadline:
            break
        # Each job has its own lease; the batch budget stops new claims. The
        # supervisor allows a final in-flight job to finish after that budget.
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
