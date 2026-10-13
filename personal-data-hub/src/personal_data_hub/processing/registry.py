"""已声明阅读方式的来源加工规则。"""
from . import activities, conversations, documents, emails, git_pull_requests, insights, metrics, nas_activity, recordings, statuses, structured

PROFILES = {profile.PROCESSOR: profile for profile in
            (documents, conversations, insights, emails, git_pull_requests, activities, nas_activity, recordings, metrics, structured, statuses)}


# 保留旧 profile 用于既有结果的失效/删除维护；采集阶段不再为提炼创建新 scope。
COLLECTION_PROFILES = {name: profile for name, profile in PROFILES.items() if name != insights.PROCESSOR}


def scopes(profile, record):
    if hasattr(profile, 'scopes'): return profile.scopes(record)
    return [profile.scope(record) if hasattr(profile, 'scope') else record['id']]


def routes(record):
    return [(name, key) for name, profile in COLLECTION_PROFILES.items() if profile.accepts(record) for key in scopes(profile, record)]


def header(profile, record, scope_key):
    if hasattr(profile, 'header'): return profile.header(record, scope_key)
    if hasattr(profile, 'scope'): return 'conversation', 'wechat_day'
    return 'document', 'execution_log' if record['kind'] == 'hermes_execution_report' else 'memory' if record['kind'] == 'memory' else 'legacy_review' if record['kind'] == 'legacy_review_report' else 'note'
