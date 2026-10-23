"""Shared deployment and result contract for benefits launchers and reports."""
import json
import os
from pathlib import Path

CONFIG = Path(os.environ.get("HERMES_HOME", "/home/hermes/.hermes/profiles/lingjun")) / "benefits-deployment.json"
MAX_JSON_BYTES = 65536


def bounded(path, limit=MAX_JSON_BYTES):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("deployment_input_limit")
    return json.loads(raw)


def load_deployment(path):
    config = bounded(path)
    if not isinstance(config, dict) or not isinstance(config.get("tasks"), dict):
        raise ValueError("invalid benefits deployment tasks")
    if not config.get("runtime_root") or not config.get("timezone"):
        raise ValueError("benefits runtime_root and timezone are required")
    return config


def identity_issue(platform, row, day, account=None):
    if account and row.get("account") != account:
        return "结果账号与配置不一致"
    if row.get("platform") != platform:
        return "结果平台标识与文件名不一致"
    if row.get("business_date") != day:
        return f"缺少当日结果（最新结果日期：{row.get('business_date') or '未知'}）"
    return None


REASONS = {
    "authentication_invalid": "登录失效",
    "authentication_unconfirmed": "登录状态无法确认",
    "cookiecloud_auth_pair_incomplete": "登录 Cookie 不完整，需重新登录并同步",
    "cart_preserved": "购物车状态无法确认，领取已停止",
    "full_requested_capabilities_partial": "已启用任务部分未完成",
    "full_task_cycle_changed": "平台任务已重置，需核查新一轮",
    "human_required": "需要人工验证",
    "launcher_failed": "启动失败",
    "network_error": "网络连接失败（重试后仍未恢复）",
    "deadline_exceeded": "执行超时",
    "configuration_or_io_error": "配置或结果保存失败",
    "lock_busy": "已有任务执行中",
    "native_configuration_or_browser_error": "配置或浏览器异常",
    "browser_timeout": "浏览器操作超时",
    "browser_cleanup_unverified": "上次浏览器任务回收未确认，已安全停止后续执行",
    "reward_not_confirmed": "当日奖励账目未确认",
    "login_not_confirmed": "登录未确认",
    "store_assets_access_denied": "商店资源被拒绝访问（403），领取已停止",
    "challenge_timeout": "验证码处理超时",
    "challenge_unconfirmed": "验证码未通过",
    "product_state_unconfirmed": "商品页状态未确认",
    "checkout_state_unconfirmed": "结算页状态未确认",
    "full_intervention_pending": "遇到验证或登录问题",
    "steam_login_required": "需要首次登录或恢复 Steam 会话",
    "steam_account_mismatch": "Steam 账号身份不匹配",
    "private_file_unreadable": "Steam 登录配置无法读取",
    "ipc_authentication_failed": "ASF IPC 认证失败",
    "ipc_transport_uncertain": "ASF IPC 连接未确认",
    "private_file_permissions_or_size": "Steam 私有配置权限不符合要求",
    "discovery_coverage_incomplete": "自动发现覆盖不完整",
    "discovery_candidates_require_review": "候选证据需要核对",
    "wechat_code_authentication_invalid": "微信取码服务认证失效",
    "wechat_code_account_unavailable": "微信账号需要检查或重新扫码",
    "wechat_code_service_unavailable": "微信取码服务或账号不可用",
    "wechat_code_connection_failed": "无法连接微信取码服务",
    "wechat_code_timeout": "微信取码服务超时",
    "activity_sent_reward_unconfirmed": "国际版活跃请求已发送，奖励未确认",
    "automated_checkin_rejected": "平台拒绝自动签到",
    "device_mismatch": "登录设备信息不匹配",
    "cloudflare_browser_signature_banned": "Cloudflare 拦截当前浏览器签名",
    "cloudflare_challenge": "Cloudflare 要求浏览器验证",
    "request_parameters_invalid": "需要有效的客户端请求参数",
    "not_logged_in": "登录失效，需重新扫码登录",
    "telegram_app_unavailable": "无法打开 Telegram 网页（代理或网络中断）",
    "telegram_snapshot_timeout": "Telegram 网页无响应，已停止本次执行",
    "selector_broken": "网页结构变化，需更新适配",
    "browser_or_network_error": "浏览器或网络异常",
    "dependency_unavailable_or_incompatible": "运行依赖缺失或版本不符",
    "configuration_missing": "缺少私有配置",
    "configuration_invalid": "私有配置格式无效",
    "account_not_configured": "私有配置中没有该账号",
    "private_file_invalid": "私有配置权限或大小不符合要求",
    "journal_invalid": "当日签到记录文件异常",
    "state_save_failed": "签到记录保存失败",
}
