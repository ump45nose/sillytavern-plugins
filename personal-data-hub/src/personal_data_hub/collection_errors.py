"""Safe collection diagnostics for run records and isolated export processes."""

import json
import re

from .google_read import GoogleReadError


REASONS = {
    "collector_busy": "该来源正在采集或写入，稍后自动重试",
    "mcp_oauth_unavailable": "来源服务的授权不可用，需要重新授权",
    "upstream_mcp_error": "来源服务读取失败",
    "upstream_mcp_contract_changed": "来源服务返回的数据格式发生变化",
    "google_pagination_stalled": "Google 分页未推进，无法完成采集",
    "google_pagination_incomplete": "Google 分页未完成",
    "email_pagination_stalled": "邮件分页未推进，无法完成采集",
    "email_pagination_incomplete": "邮件分页未完成",
    "email_body_incomplete": "邮件正文未完整读取",
    "email_body_too_large": "邮件正文超过采集大小限制",
    "email_attachment_incomplete": "邮件附件未完整读取",
    "email_attachment_contract_changed": "邮件附件返回格式发生变化",
    "email_bridge_disconnected": "邮件读取服务连接中断",
    "mem0_list_tool_missing": "Mem0 服务缺少记忆列表接口",
    "mem0_schema_changed": "Mem0 返回的数据格式发生变化",
    "mem0_pagination_stalled": "Mem0 分页未推进，无法完成采集",
    "mem0_pagination_incomplete": "Mem0 分页未完成",
    "github_identity_missing": "无法读取 GitHub 账号身份",
    "github_search_incomplete": "GitHub 搜索结果不完整",
    "github_pagination_stalled": "GitHub 分页未推进，无法完成采集",
    "github_search_limit_requires_smaller_window": "GitHub 搜索超过结果上限，需要缩小采集窗口",
    "github_search_limit_requires_repository_scope": "GitHub 单秒结果仍超过上限或不完整，需要明确仓库范围",
    "github_pagination_incomplete": "GitHub 分页未完成",
    "memos_attachment_missing": "Memos 附件文件缺失",
    "memos_attachment_storage_unsupported": "Memos 附件存储方式不受支持",
    "token_schema_changed": "Token Monitor 返回的数据格式发生变化",
    "plaud_sync_failed": "Plaud 同步进程执行失败",
    "plaud_recording_missing": "Plaud 录音文件缺失",
    "isolated_source_assets_unsupported": "隔离采集返回了不支持的附件",
}
GOOGLE_MESSAGES = {
    "Google 凭据文件权限必须为 0600", "Google 凭据文件无法读取",
    "Google 凭据缺少 OAuth 刷新字段", "Google OAuth 凭据已失效，需要重新授权",
    "Google OAuth 刷新未返回 access token", "Google API 返回结构不是对象",
    "Hermes 代理 ENV 不得允许其他用户读取", "Hermes 代理 ENV 无法读取",
}


class IsolatedSourceError(RuntimeError):
    def __init__(self, detail):
        super().__init__("isolated_source_read_failed")
        self.detail = detail


def error_detail(exc):
    if isinstance(exc, IsolatedSourceError):
        return exc.detail
    kind = type(exc).__name__
    message = str(exc)
    reason = REASONS.get(message)
    if isinstance(exc, GoogleReadError):
        if message in GOOGLE_MESSAGES:
            reason = message
        elif re.fullmatch(r"Google (OAuth 刷新|API 读取)失败：HTTP [1-5][0-9]{2}", message):
            reason = message
        else:
            match = re.fullmatch(r"Google (OAuth 刷新|API 读取)失败：(URLError|TimeoutError|JSONDecodeError)", message)
            if match:
                category = {"URLError": "网络连接失败", "TimeoutError": "请求超时",
                            "JSONDecodeError": "返回的数据格式无法解析"}[match[2]]
                reason = f"Google {match[1]}失败：{category}"
    if not reason:
        if isinstance(exc, BaseExceptionGroup):
            details = [error_detail(child) for child in exc.exceptions[:5]]
            return {"type": kind, "reason": "；".join(dict.fromkeys(d['reason'] for d in details)),
                    "causes": details}
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if kind == "HTTPError":
            status = getattr(exc, "code", None)
        if isinstance(status, int) and 100 <= status <= 599:
            reason = f"来源接口请求失败（HTTP {status}）"
        elif isinstance(exc, PermissionError):
            reason = "读取来源数据的权限不足"
        elif isinstance(exc, FileNotFoundError):
            reason = "采集所需的文件或程序不存在"
        elif isinstance(exc, TimeoutError) or kind in ("TimeoutExpired", "ConnectTimeout", "ReadTimeout", "PoolTimeout"):
            reason = "采集请求超时"
        elif isinstance(exc, ConnectionError) or kind in ("URLError", "ConnectError", "ReadError", "RemoteProtocolError"):
            reason = "来源服务网络连接失败或中断"
        elif kind == "OperationalError":
            reason = "数据库连接或操作失败"
        else:
            reason = "采集器执行失败，未提供可识别的具体原因"
    return {"type": kind, "reason": reason}


def isolated_error(stderr):
    for line in reversed(stderr.splitlines()):
        try:
            value = json.loads(line).get("collection_error")
        except (ValueError, AttributeError):
            continue
        if (isinstance(value, dict) and isinstance(value.get("type"), str)
                and isinstance(value.get("reason"), str)):
            return IsolatedSourceError(value)
    return IsolatedSourceError({"type": "RuntimeError", "reason": "隔离采集进程执行失败，未返回错误原因"})
