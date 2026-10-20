"""邮件日报候选的保守白名单与敏感信息拦截。"""

from __future__ import annotations

from dataclasses import dataclass
import re

from enum import StrEnum

class EvidenceKind(StrEnum):
    BLOCKER = "blocker"
    EXTERNAL_FEEDBACK = "external_feedback"


@dataclass(frozen=True)
class EmailAssessment:
    """保存通过过滤后的安全主题和证据类型。"""

    subject: str
    kind: EvidenceKind

    @property
    def fact(self) -> str:
        """生成不含发件地址、正文和动作建议的候选事实。"""

        return f"邮件事项：{self.subject}"


class EmailCandidatePolicy:
    """只允许高价值外部变化进入日报，并硬拦截账号安全类内容。"""

    def __init__(self, policy: dict) -> None:
        """从 YAML 读取全部过滤词，禁止在脚本中散落业务白名单。"""

        values = policy["sources"]["email_filter"]
        self.useful = self._normalized(values["useful_patterns"])
        self.automated_allow = self._normalized(values["automated_allow_patterns"])
        self.automated_senders = self._normalized(values["automated_sender_patterns"])
        self.sensitive = self._normalized(values["sensitive_patterns"])
        self.noise = self._normalized(values["noise_patterns"])
        self.blockers = self._normalized(values["blocker_patterns"])

    def assess(self, subject: str, sender: str = "", context: str = "") -> EmailAssessment | None:
        """判断邮件是否具备日报价值；context 仅参与过滤，绝不写入候选。"""

        normalized_subject = self._compact(subject).lower()
        normalized_sender = self._compact(sender).lower()
        normalized_context = self._compact(context).lower()
        all_text = f"{normalized_subject} {normalized_sender} {normalized_context}"

        # 验证码、登录提醒和密码重置即使紧急，也属于安全通道而非个人复盘事实。
        if self._contains(all_text, self.sensitive):
            return None
        # 例行通知、社交站内信和营销摘要不因“回复/结果”等宽词误入。
        if self._contains(f"{normalized_subject} {normalized_sender}", self.noise):
            return None
        if not self._contains(normalized_subject, self.useful):
            return None
        automated = self._contains(f"{normalized_sender} {normalized_context}", self.automated_senders)
        if automated and not self._contains(normalized_subject, self.automated_allow):
            return None

        safe_subject = self._sanitize_subject(subject)
        if not safe_subject:
            return None
        kind = EvidenceKind.BLOCKER if self._contains(normalized_subject, self.blockers) else EvidenceKind.EXTERNAL_FEEDBACK
        return EmailAssessment(safe_subject, kind)

    @staticmethod
    def _normalized(values: list[str]) -> tuple[str, ...]:
        """统一大小写并移除空配置项。"""

        return tuple(value.strip().lower() for value in values if value.strip())

    @staticmethod
    def _contains(text: str, patterns: tuple[str, ...]) -> bool:
        """执行可读子串匹配，YAML 不承担正则转义负担。"""

        return any(pattern in text for pattern in patterns)

    @staticmethod
    def _compact(text: str) -> str:
        """压缩邮件元数据空白。"""

        return re.sub(r"\s+", " ", str(text or "")).strip()

    @classmethod
    def _sanitize_subject(cls, subject: str) -> str:
        """移除 URL、邮件地址和疑似口令，避免旧摘要把敏感元数据带回日报。"""

        text = cls._compact(subject)
        text = re.sub(r"https?://\S+", "[链接已省略]", text, flags=re.IGNORECASE)
        text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[地址已省略]", text)
        text = re.sub(r"(?<!\d)\d{5,}(?!\d)", "[编号已省略]", text)
        return text[:240].strip()
