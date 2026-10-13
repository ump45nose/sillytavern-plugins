"""Fail-closed, operator-reviewed promotion evidence. Not a discovery service."""
from datetime import datetime, timezone, timedelta
import re
from urllib.parse import urlsplit
from .ipc import SteamError

CATALOG_EVIDENCE_METHOD = 'official_store_catalog_free_to_keep'
AUTOMATIC_EVIDENCE_METHODS = frozenset({'official_store_free_to_keep', CATALOG_EVIDENCE_METHOD})


def timestamp(value):
    if not isinstance(value, str):
        raise SteamError('invalid_promotion_time')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise SteamError('invalid_promotion_time') from None


def validate_manifest(data, region, now):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('candidates'), list):
        raise SteamError('invalid_candidates')
    if len(data['candidates']) > 50:
        raise SteamError('too_many_candidates')
    # Duplicate packages are rejected, never two executions under different offers.
    seen = set()
    rows = []
    for row in data['candidates']:
        if not isinstance(row, dict):
            raise SteamError('invalid_candidate')
        pid = row.get('package_id')
        if type(pid) is not int or not 0 < pid < 2**32 or pid in seen:
            raise SteamError('invalid_or_duplicate_package')
        seen.add(pid)
        name = row.get('name')
        if not isinstance(name, str) or not 0 < len(name) <= 200 or any(ord(c) < 32 for c in name):
            raise SteamError('invalid_candidate_name')
        reason = eligibility(row, region, now)
        rows.append((row, reason))
    return rows


def eligibility(row, region, now):
    """All claims are explicit reviewed assertions, not inferred from a zero price."""
    if row.get('promotion_kind') != 'limited_time_free_to_keep' or row.get('permanent_license') is not True:
        return 'promotion_type_unverified'
    if any(row.get(k) is not False for k in ('free_to_play', 'free_weekend', 'demo', 'playtest')):
        return 'excluded_or_unknown_product_type'
    if row.get('product_type') != 'game':
        return 'unsupported_product_type'
    official = isinstance(row.get('evidence'), dict) and row['evidence'].get('method') == 'official_store_free_to_keep'
    if not official and (type(row.get('price_minor')) is not int or row['price_minor'] != 0
            or type(row.get('regular_price_minor')) is not int or row['regular_price_minor'] <= 0
            or not isinstance(row.get('currency'), str) or not re.fullmatch(r'[A-Z]{3}', row['currency'])):
        return 'price_evidence_unverified'
    if official and (type(row.get('price_minor')) is not int or row['price_minor'] != 0):
        return 'price_evidence_unverified'
    regions = row.get('allowed_regions')
    if not isinstance(regions, list) or not regions or any(not isinstance(r, str) or not re.fullmatch(r'[A-Z]{2}', r) for r in regions) or region not in regions:
        return 'region_not_verified'
    apps = row.get('app_ids')
    if not isinstance(apps, list) or not apps or any(type(a) is not int or not 0 < a < 2**32 for a in apps):
        return 'package_contents_unverified'
    evidence = row.get('evidence')
    if not isinstance(evidence, dict) or evidence.get('reviewed') is not True:
        return 'promotion_evidence_missing'
    # Distinct evidence categories force reviewers to attest the relevant facts.
    for key in ('promotion_url', 'package_url', 'region_url'):
        value = evidence.get(key)
        if not isinstance(value, str) or len(value) > 512:
            return 'promotion_evidence_missing'
        try:
            u = urlsplit(value)
            if (u.scheme != 'https' or u.hostname not in {'store.steampowered.com', 'steamcommunity.com', 'steamdb.info'}
                    or u.username or u.password or u.query or u.fragment or u.port not in (None, 443)):
                return 'invalid_evidence_url'
        except ValueError:
            return 'invalid_evidence_url'
    package_host = 'store.steampowered.com' if evidence.get('method') == CATALOG_EVIDENCE_METHOD else 'steamdb.info'
    if evidence['package_url'] != f"https://{package_host}/sub/{row['package_id']}/":
        return 'package_evidence_mismatch'
    try:
        start, end, checked = (timestamp(row['starts_at']), timestamp(row['ends_at']), timestamp(evidence['checked_at']))
    except (KeyError, SteamError):
        return 'promotion_time_unverified'
    if not start < end or now < start:
        return 'promotion_not_active'
    if now >= end:
        return 'promotion_expired'
    if checked > now or now - checked > timedelta(hours=1) or checked < start:
        return 'promotion_evidence_stale'
    return None


def child(node, name):
    children = node.get('Children') if isinstance(node, dict) else None
    if not isinstance(children, list):
        return None
    matches = [c for c in children if isinstance(c, dict) and c.get('Name') == name]
    return matches[0] if len(matches) == 1 else None


def leaf(node, name):
    value = child(node, name)
    return value.get('Value') if value else None


def verify_package(tree, row, now, region=None):
    # Require real typed fields, not default conversions of missing fields to zero.
    if tree.get('Name') != str(row['package_id']):
        return 'package_metadata_mismatch'
    if leaf(tree, 'billingtype') != '0' or leaf(tree, 'licensetype') != '1' or leaf(tree, 'status') != '0':
        return 'package_not_free_permanent_purchase'
    extended = child(tree, 'extended')
    if any(leaf(extended, key) not in (None, '0') for key in ('betatesterpackage', 'deactivated_demo')):
        return 'beta_or_demo_package_excluded'
    if any(leaf(extended, key) not in (None, '0') for key in ('mustownapptopurchase', 'dontgrantifappidowned')):
        return 'package_prerequisites_unverified'
    region_reason = (region_restriction(extended, 'restrictedcountries', 'onlyallowrestrictedcountries', region)
                     or region_restriction(extended, 'purchaserestrictedcountries', 'allowpurchasefromrestrictedcountries', region))
    if region_reason:
        return region_reason
    if leaf(extended, 'freeweekend') not in (None, '0'):
        return 'free_weekend_excluded'
    # Some packages omit the window; the reviewed manifest must still supply it.
    for field, lower in (('starttime', True), ('expirytime', False)):
        value = leaf(extended, field)
        if value is not None:
            try:
                boundary = int(value)
            except (ValueError, TypeError):
                return 'package_time_unverified'
            if boundary < 0 or (boundary and (now.timestamp() < boundary if lower else now.timestamp() >= boundary)):
                return 'package_not_currently_available'
    apps = child(tree, 'appids')
    if not isinstance(apps, dict) or not isinstance(apps.get('Children'), list):
        return 'package_contents_unverified'
    values = [c.get('Value') for c in apps['Children'] if isinstance(c, dict)]
    if not values or any(not isinstance(v, str) or not v.isdecimal() for v in values):
        return 'package_contents_unverified'
    if set(map(int, values)) != set(row['app_ids']):
        return 'package_contents_changed'
    return None


def region_restriction(node, list_key, flag_key, region, separator=' '):
    raw, flag = leaf(node, list_key), leaf(node, flag_key) if flag_key else None
    if flag not in (None, '0', '1'):
        return 'region_rules_unverified'
    if raw is None:
        return 'region_rules_unverified' if flag == '1' else None
    if not isinstance(raw, str):
        return 'region_rules_unverified'
    countries = [part.upper() for part in raw.split(separator) if part]
    if not countries or any(not re.fullmatch(r'[A-Z]{2}', part) for part in countries) or region is None:
        return 'region_rules_unverified'
    if (region.upper() in countries) != (flag == '1'):
        return 'region_restricted'
    return None


def verify_app(tree, app_id, region, allow_free_to_play=False):
    if tree.get('Name') != 'appinfo' or leaf(tree, 'appid') != str(app_id):
        return 'app_metadata_mismatch'
    common, extended = child(tree, 'common'), child(tree, 'extended')
    if (leaf(common, 'type') or '').lower() != 'game':
        return 'non_game_or_unknown_app_excluded'
    if not allow_free_to_play and leaf(extended, 'isfreeapp') not in (None, '0', 'false'):
        return 'free_to_play_or_unknown_app_excluded'
    if leaf(extended, 'playtest_type') is not None or leaf(extended, 'betaforappid') not in (None, '0'):
        return 'playtest_app_excluded'
    if leaf(extended, 'mustownapptopurchase') not in (None, '0'):
        return 'app_prerequisites_unverified'
    return (region_restriction(common, 'restricted_countries', None, region, ',')
            or region_restriction(extended, 'purchaserestrictedcountries', 'allowpurchasefromrestrictedcountries', region))
