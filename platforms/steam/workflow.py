"""Journal-first package claims. A pending attempt is reconciled, never replayed."""
from datetime import datetime, timezone
import json
from pathlib import Path
from common.model import atomic_json
from common.details import metric
from .candidates import validate_manifest, eligibility, verify_package, verify_app
from .ipc import SteamError

WINDOW_SECONDS = 5400
WINDOW_ATTEMPTS = 25
MIN_INTERVAL_SECONDS = 10
MAX_JOURNAL_ENTRIES = 200


class Journal:
    def __init__(self, path, steam_id):
        self.path = Path(path)
        self.steam_id = steam_id
        self.entries = {}
        self.blocked_until = 0
        if self.path.exists():
            try:
                if self.path.stat().st_size > 65536:
                    raise ValueError()
                data = json.loads(self.path.read_text())
                if data['schema_version'] != 1 or data['steam_id'] != steam_id or not isinstance(data['entries'], dict):
                    raise ValueError()
                for key, value in data['entries'].items():
                    if (not key.isdecimal() or not 0 < int(key) < 2**32 or not isinstance(value, dict)
                            or type(value.get('attempted_at')) not in (int, float)
                            or not 0 <= value['attempted_at'] < 1e12
                            or value.get('state') not in {'pending', 'confirmed'}):
                        raise ValueError()
                self.entries = data['entries']
                self.blocked_until = data.get('blocked_until', 0)
                if type(self.blocked_until) not in (int, float) or not 0 <= self.blocked_until < 1e12:
                    raise ValueError()
            except (OSError, ValueError, KeyError, TypeError):
                raise SteamError('journal_invalid') from None

    def save(self):
        atomic_json(self.path, {'schema_version': 1, 'steam_id': self.steam_id, 'entries': self.entries, 'blocked_until': self.blocked_until})
        # Persist the rename directory entry as well as the file before any POST.
        import os
        fd = os.open(self.path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def rate_reason(self, now):
        if now < self.blocked_until:
            return 'server_rate_limit_cooldown'
        times = [v['attempted_at'] for v in self.entries.values()]
        if any(t > now for t in times):
            return 'clock_moved_backwards'
        recent = [t for t in times if now - t < WINDOW_SECONDS]
        if len(recent) >= WINDOW_ATTEMPTS or (recent and now - max(recent) < MIN_INTERVAL_SECONDS):
            return 'local_rate_limited'
        if len(self.entries) >= MAX_JOURNAL_ENTRIES:
            return 'journal_capacity_requires_review'
        return None

    def intent(self, package_id, now):
        self.entries[str(package_id)] = {'attempted_at': now, 'state': 'pending'}
        self.save()

    def confirm(self, package_id):
        key = str(package_id)
        if key in self.entries:
            self.entries[key]['state'] = 'confirmed'
            self.save()


def classify_response(response):
    if not isinstance(response, dict):
        return 'claim_response_unverified'
    result, detail = response.get('Result'), response.get('PurchaseResultDetail')
    if type(result) is not int or type(detail) is not int:
        return 'claim_response_unverified'
    if result == 84 or detail == 53:
        return 'rate_limited'
    if result == 1 and detail == 0:
        return 'submission_accepted'
    if result == 30 or detail == 9:
        return 'already_owned_response'
    if detail in {13, 19, 23}:
        return 'region_rejected'
    if detail in {20, 21, 22, 44}:
        return 'account_restricted'
    if result in {3, 16, 20} or detail == 4:
        return 'claim_transport_uncertain'
    return 'claim_rejected'


def run_workflow(client, manifest, region, journal, claim=False, now=None, publish=None):
    clock = now or (lambda: datetime.now(timezone.utc))
    rows = validate_manifest(manifest, region, clock())
    present = {row['package_id'] for row, _ in rows}
    recovery = [int(pid) for pid, entry in journal.entries.items() if entry['state'] == 'pending' and int(pid) not in present]
    # Recover up to the result bound, including attempts whose promotions are
    # no longer discoverable. Entries beyond the batch remain durable for later.
    recovery_overflow = len(recovery) > 50
    rows += [({'package_id': pid, 'name': f'Steam package {pid}'}, 'journal_recovery_only') for pid in recovery[:50]]
    items = []
    acquired = 0
    stopped = None

    def output():
        statuses = {x['status'] for x in items}
        if len(items) < len(rows) or recovery_overflow:
            statuses.add('unknown')
        business = ('unknown' if 'unknown' in statuses else 'blocked' if 'blocked' in statuses
                    else 'incomplete' if 'incomplete' in statuses else 'complete' if items else 'not_applicable')
        return {'execution': 'ok', 'reason': 'claims_verified' if business == 'complete' else
                'no_candidates' if not items else 'steam_items_require_review',
                'business': {'claim': business},
                'details': {'metrics': {'claimed_packages': metric('count', current=acquired)}, 'items': list(items)}}

    def add(row, status, reason):
        items.append({'id': 'sub/' + str(row['package_id']), 'name': row['name'],
                      'status': status, 'reason': reason,
                      'url': 'https://store.steampowered.com/sub/' + str(row['package_id']) + '/'})
        if publish:
            publish(output())

    if not rows:
        return output()
    # An invalid/stale manifest cannot cause even an IPC read for its rejected rows.
    if not any(reason is None or str(row['package_id']) in journal.entries for row, reason in rows):
        for row, reason in rows:
            add(row, 'blocked', reason)
        return output()
    if publish:
        publish(output())
    client.session()
    owned = client.owned()
    for pid in recovery[50:]:
        if pid in owned:
            journal.confirm(pid)
    for row, reason in rows:
        pid = row['package_id']
        if str(pid) in journal.entries:
            if pid in owned:
                journal.confirm(pid)
                add(row, 'complete', 'previous_submission_owned_verified')
            else:
                add(row, 'unknown', 'previous_submission_unresolved')
            continue
        if reason:
            add(row, 'blocked', reason)
            continue
        if stopped:
            add(row, 'blocked', stopped)
            continue
        try:
            tree = client.package(pid)
            current = clock()
            reason = eligibility(row, region, current) or verify_package(tree, row, current, region)
            if reason:
                add(row, 'blocked', reason)
                continue
            for app_id in row['app_ids']:
                reason = verify_app(client.app(app_id), app_id, region)
                if reason:
                    break
            if reason:
                add(row, 'blocked', reason)
                continue
            if pid in owned:
                journal.confirm(pid)
                add(row, 'complete', 'owned_package_verified')
                continue
            if str(pid) in journal.entries:
                add(row, 'unknown', 'previous_submission_unresolved')
                continue
            if not claim:
                add(row, 'incomplete', 'dry_run_eligible')
                continue
            reason = journal.rate_reason(clock().timestamp())
            if reason:
                add(row, 'blocked', reason)
                continue
            # Revalidate the session, ownership, and promotion immediately before
            # the durable intent. No sleeps/queue may defer work past the window.
            client.session()
            owned = client.owned()
            if pid in owned:
                add(row, 'complete', 'owned_package_verified')
                continue
            current = clock()
            reason = eligibility(row, region, current) or verify_package(tree, row, current, region)
            if reason:
                add(row, 'blocked', reason)
                continue
            journal.intent(pid, clock().timestamp())
            try:
                reason = classify_response(client.claim(pid))
            except SteamError as error:
                reason = error.reason
            # A POST response alone never constitutes successful acquisition.
            # 401/403 and 429 stop all calls rather than retrying authentication.
            if reason in {'ipc_authentication_failed', 'rate_limited'}:
                stopped = reason
                if reason == 'rate_limited':
                    journal.blocked_until = clock().timestamp() + WINDOW_SECONDS
                    journal.save()
                add(row, 'unknown', reason)
                continue
            try:
                client.session()
                owned = client.owned()
            except SteamError as error:
                stopped = error.reason
                add(row, 'unknown', 'submission_readback_unavailable')
                continue
            if pid in owned:
                journal.confirm(pid)
                if reason in {'submission_accepted', 'ipc_transport_uncertain', 'claim_transport_uncertain'}:
                    acquired += 1
                    add(row, 'complete', 'claimed_package_verified')
                else:
                    add(row, 'complete', 'owned_package_verified')
            else:
                add(row, 'unknown', 'submission_unconfirmed_' + reason)
                # Even definite rejections retain intent and stop this invocation;
                # no subsequent item can conceal authentication/region trouble.
                stopped = 'previous_submission_unresolved'
        except SteamError as error:
            stopped = error.reason
            add(row, 'blocked', error.reason)
    return output()
