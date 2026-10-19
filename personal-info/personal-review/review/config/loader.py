"""加载严格分层的 ENV 与 YAML 配置。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
import yaml


class ConfigError(ValueError):
    """表示配置缺失、冲突或包含未知业务字段。"""


ENV_KEYS = {
    "REVIEW_TIMEZONE",
    "REVIEW_APP_ROOT",
    "REVIEW_SKYSIGHT_ARCHIVE_ROOT",
    "REVIEW_SKYSIGHT_READER",
    "REVIEW_MEMOS_BASE_URL",
    "REVIEW_MEMOS_TOKEN_FILE",
    "REVIEW_STATE_DB",
    "REVIEW_LOG_DIR",
    "REVIEW_JOBS_FILE",
    "REVIEW_HERMES_EXECUTIONS_DB",
    "REVIEW_HERMES_BIN",
    "REVIEW_HERMES_PROFILE",
    "REVIEW_DELIVERY_TARGET",
    "REVIEW_USER_MD",
    "REVIEW_COMPANION_USER_MD",
    "REVIEW_GIT_SUMMARY_DIR",
    "REVIEW_CRM_API_URL",
    "REVIEW_CRM_TOKEN_FILE",
    "REVIEW_EMAIL_BRIEF_DIR",
    "REVIEW_EMAIL_MCP_URL",
    "REVIEW_GOOGLE_CREDENTIAL_FILE",
    "REVIEW_HERMES_PROXY_ENV_FILE",
    "REVIEW_GOOGLE_BRIEF_DIR",
    "REVIEW_ATTACHMENT_SPOOL",
    "REVIEW_DAILY_TIME",
    "REVIEW_DAILY_ACK_TIME",
    "REVIEW_WEEKLY_TIME",
    "REVIEW_MEM0_TIME",
    "REVIEW_EMAIL_TIME",
    "REVIEW_GOOGLE_TIME",
    "REVIEW_GIT_TIME",
    "REVIEW_DAILY_DRY_RUN_TIME",
    "REVIEW_WEEKLY_DRY_RUN_TIME",
    "REVIEW_STAGE_TIME",
    "REVIEW_ATTACHMENT_WORKER_SCHEDULE",
    "REVIEW_ENABLE_DAILY",
    "REVIEW_ENABLE_WEEKLY",
    "REVIEW_ENABLE_STAGES",
    "REVIEW_ENABLE_USER_MD",
    "REVIEW_ENABLE_TASKS",
    "REVIEW_ENABLE_MEM0",
    "REVIEW_ENABLE_ATTACHMENTS",
}

REQUIRED_ENV_KEYS = ENV_KEYS - {
    "REVIEW_SKYSIGHT_READER",
    "REVIEW_ENABLE_DAILY",
    "REVIEW_ENABLE_WEEKLY",
    "REVIEW_ENABLE_STAGES",
    "REVIEW_ENABLE_USER_MD",
    "REVIEW_ENABLE_TASKS",
    "REVIEW_ENABLE_MEM0",
    "REVIEW_ENABLE_ATTACHMENTS",
}

TOP_LEVEL_YAML_KEYS = {
    "schema_version",
    "sources",
    "evidence",
    "daily",
    "weekly",
    "stages",
    "retention",
    "projections",
    "attachments",
    "memos",
    "health",
}


@dataclass(frozen=True)
class FeatureFlags:
    """保存各阶段是否允许产生外部副作用。"""

    daily: bool
    weekly: bool
    stages: bool
    user_md: bool
    tasks: bool
    mem0: bool
    attachments: bool


@dataclass(frozen=True)
class AppConfig:
    """应用启动后使用的不可变配置快照。"""

    env_file: Path
    policy_file: Path
    values: dict[str, str]
    policy: dict[str, Any]
    flags: FeatureFlags

    @property
    def timezone(self) -> ZoneInfo:
        """返回配置中的业务时区。"""

        return ZoneInfo(self.values["REVIEW_TIMEZONE"])

    def path(self, key: str) -> Path:
        """把指定 ENV 配置转换成绝对路径。"""

        return Path(self.values[key]).expanduser()


def _parse_env(path: Path) -> dict[str, str]:
    """读取简单 dotenv；不展开 shell，也不执行变量替换。"""

    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"{path}:{number} 不是 KEY=VALUE")
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("REVIEW_") and key not in ENV_KEYS:
            raise ConfigError(f"未知配置项：{key}")
        values[key] = value.strip().strip('"').strip("'")
    return values


def _as_bool(values: dict[str, str], key: str) -> bool:
    """严格解析布尔开关，避免拼写错误被当成开启。"""

    raw = values.get(key, "false").lower()
    if raw not in {"true", "false"}:
        raise ConfigError(f"{key} 只能是 true 或 false")
    return raw == "true"


def _validate_policy(policy: Any, schema_path: Path) -> dict[str, Any]:
    """校验业务配置的顶层结构和关键约束。"""

    if not isinstance(policy, dict):
        raise ConfigError("review.yaml 顶层必须是对象")
    unknown = set(policy) - TOP_LEVEL_YAML_KEYS
    missing = TOP_LEVEL_YAML_KEYS - set(policy)
    if unknown or missing:
        raise ConfigError(f"YAML 字段错误：unknown={sorted(unknown)}, missing={sorted(missing)}")
    if not schema_path.is_file():
        raise ConfigError(f"业务配置 schema 不存在：{schema_path}")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        Draft202012Validator(schema).validate(policy)
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise ConfigError(f"review.yaml 校验失败：{location}: {exc.message}") from exc
    if policy["schema_version"] != 1:
        raise ConfigError("仅支持 schema_version=1")
    if policy["stages"].get("max_active_goals") != 5:
        raise ConfigError("首版固定最多五个活跃阶段目标")
    if policy["stages"].get("cycle_days") != 42:
        raise ConfigError("首版阶段周期固定为 42 天")
    if policy["daily"].get("comment_max_chars", 0) > 300:
        raise ConfigError("Lingjun 评论不能超过 300 字")
    return policy


def load_config(env_file: str | Path, policy_file: str | Path) -> AppConfig:
    """加载、合并并严格校验应用配置。"""

    env_path = Path(env_file)
    policy_path = Path(policy_file)
    if not env_path.is_file() or not policy_path.is_file():
        raise ConfigError("ENV 或 YAML 配置文件不存在")

    values = _parse_env(env_path)
    missing = sorted(key for key in REQUIRED_ENV_KEYS if not values.get(key))
    if missing:
        raise ConfigError(f"缺少 ENV 配置：{', '.join(missing)}")
    for key in ("REVIEW_DAILY_TIME", "REVIEW_DAILY_ACK_TIME", "REVIEW_MEM0_TIME", "REVIEW_EMAIL_TIME", "REVIEW_GOOGLE_TIME", "REVIEW_GIT_TIME", "REVIEW_DAILY_DRY_RUN_TIME", "REVIEW_STAGE_TIME"):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", values[key]):
            raise ConfigError(f"{key} 必须是 HH:MM")
    for key in ("REVIEW_WEEKLY_TIME", "REVIEW_WEEKLY_DRY_RUN_TIME"):
        if not re.fullmatch(r"(?:MON|TUE|WED|THU|FRI|SAT|SUN) (?:[01]\d|2[0-3]):[0-5]\d", values[key]):
            raise ConfigError(f"{key} 必须是 DDD HH:MM")
    worker_parts = values["REVIEW_ATTACHMENT_WORKER_SCHEDULE"].split()
    if len(worker_parts) != 5 or not all(re.fullmatch(r"[0-9*/?,\-]+", part) for part in worker_parts):
        raise ConfigError("REVIEW_ATTACHMENT_WORKER_SCHEDULE 必须是五段 cron 表达式")
    try:
        ZoneInfo(values["REVIEW_TIMEZONE"])
    except ZoneInfoNotFoundError as exc:
        raise ConfigError("REVIEW_TIMEZONE 不是有效 IANA 时区") from exc
    for key in ("REVIEW_MEMOS_BASE_URL", "REVIEW_EMAIL_MCP_URL", "REVIEW_CRM_API_URL"):
        if not re.fullmatch(r"https?://[^\s]+", values[key]):
            raise ConfigError(f"{key} 必须是 http(s) URL")
    for key in REQUIRED_ENV_KEYS:
        if key.endswith(("_ROOT", "_FILE", "_DB", "_DIR", "_SPOOL", "_MD")) and not Path(values[key]).is_absolute():
            raise ConfigError(f"{key} 必须使用绝对路径")
    if not Path(values["REVIEW_HERMES_BIN"]).is_absolute():
        raise ConfigError("REVIEW_HERMES_BIN 必须使用绝对路径")

    schema_path = policy_path.parent.parent / "schemas/review.schema.json"
    policy = _validate_policy(yaml.safe_load(policy_path.read_text(encoding="utf-8")), schema_path)
    if policy["daily"]["cutoff"] != values["REVIEW_DAILY_TIME"]:
        raise ConfigError("REVIEW_DAILY_TIME 与 daily.cutoff 冲突")
    if policy["weekly"]["schedule"] != values["REVIEW_WEEKLY_TIME"]:
        raise ConfigError("REVIEW_WEEKLY_TIME 与 weekly.schedule 冲突")
    # 用户交互型和保留任务不允许在同一分钟重叠；附件 worker 是独立 no-agent，不参与此门禁。
    daily_slots = {
        "daily": values["REVIEW_DAILY_TIME"],
        "daily_ack": values["REVIEW_DAILY_ACK_TIME"],
        "mem0": values["REVIEW_MEM0_TIME"],
        "email": values["REVIEW_EMAIL_TIME"],
        "google": values["REVIEW_GOOGLE_TIME"],
        "git": values["REVIEW_GIT_TIME"],
        "daily_dry_run": values["REVIEW_DAILY_DRY_RUN_TIME"],
        "stage": values["REVIEW_STAGE_TIME"],
    }
    seen_daily: dict[str, str] = {}
    for name, scheduled_time in daily_slots.items():
        if previous := seen_daily.get(scheduled_time):
            raise ConfigError(f"调度时间冲突：{previous} 与 {name} 都是 {scheduled_time}")
        seen_daily[scheduled_time] = name
    for name, key in (("weekly", "REVIEW_WEEKLY_TIME"), ("weekly_dry_run", "REVIEW_WEEKLY_DRY_RUN_TIME")):
        weekday, scheduled_time = values[key].split()
        if previous := seen_daily.get(scheduled_time):
            raise ConfigError(f"调度时间冲突：{previous} 与 {name} 在 {weekday} {scheduled_time} 重叠")
    flags = FeatureFlags(
        daily=_as_bool(values, "REVIEW_ENABLE_DAILY"),
        weekly=_as_bool(values, "REVIEW_ENABLE_WEEKLY"),
        stages=_as_bool(values, "REVIEW_ENABLE_STAGES"),
        user_md=_as_bool(values, "REVIEW_ENABLE_USER_MD"),
        tasks=_as_bool(values, "REVIEW_ENABLE_TASKS"),
        mem0=_as_bool(values, "REVIEW_ENABLE_MEM0"),
        attachments=_as_bool(values, "REVIEW_ENABLE_ATTACHMENTS"),
    )
    return AppConfig(env_path, policy_path, values, policy, flags)
