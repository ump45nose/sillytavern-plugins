"""SQLite 仓储：集中承载事务、幂等和数据完整性规则。"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import String, cast, create_engine, event, func, or_, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import (
    Base,
    Fact,
    FactStatus,
    Interaction,
    Person,
    Reminder,
    ReminderStatus,
    ensure_utc,
)


class CrmRepository:
    """提供四张核心表的稳定访问接口，业务模块不得直接持有 Engine。"""

    def __init__(self, url: str = "sqlite:///crm.db", *, create_schema: bool = True) -> None:
        engine_options: dict[str, Any] = {"future": True}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            # 内存库必须让所有 Session 复用同一个连接，否则测试会看到不同数据库。
            engine_options.update(
                {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
            )
        elif url.startswith("sqlite:"):
            engine_options["connect_args"] = {"check_same_thread": False}
        self.engine = create_engine(url, **engine_options)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        self._configure_sqlite(self.engine)
        if create_schema:
            Base.metadata.create_all(self.engine)

    @staticmethod
    def _configure_sqlite(engine: Engine) -> None:
        """为每个 SQLite 连接启用外键，并为文件库启用 WAL。"""

        if engine.dialect.name != "sqlite":
            return

        @event.listens_for(engine, "connect")
        def set_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
            """在连接建立时应用必须的 SQLite 约束。"""

            del connection_record
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            if engine.url.database not in {None, "", ":memory:"}:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    def session(self) -> Session:
        """创建由调用者负责关闭的 Session，供扩展模块执行组合查询。"""

        return self._sessions()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """提供统一的提交/回滚边界。"""

        with self._sessions() as session:
            with session.begin():
                yield session

    @staticmethod
    def _require_person(session: Session, person_id: str) -> Person:
        """取得人物；外部 ID 错误时立即阻止孤儿业务记录。"""

        person = session.get(Person, person_id)
        if person is None:
            raise ValueError("person not found")
        return person

    def create_person(self, **values: Any) -> Person:
        """创建人物。"""

        with self.transaction() as session:
            person = Person(**values)
            session.add(person)
            session.flush()
            return person

    def upsert_person(self, person_id: str | None = None, **values: Any) -> tuple[Person, dict]:
        """按 ID 创建或更新人物，并返回修改前的字段快照。"""

        with self.transaction() as session:
            person = session.get(Person, person_id) if person_id else None
            before = self.to_dict(person) if person else {}
            if person is None:
                person = Person(id=person_id, **values) if person_id else Person(**values)
                session.add(person)
            else:
                for name, value in values.items():
                    setattr(person, name, value)
            session.flush()
            return person, before

    def get_person(self, person_id: str) -> Person | None:
        """按 ID 读取人物。"""

        with self._sessions() as session:
            return session.get(Person, person_id)

    def search_people(self, query: str = "", limit: int = 50) -> list[Person]:
        """搜索姓名及 JSON 中的别名、联系方式和标签。"""

        with self._sessions() as session:
            statement = select(Person).order_by(Person.display_name).limit(limit)
            if query.strip():
                like = f"%{query.strip()}%"
                statement = statement.where(
                    or_(
                        Person.display_name.ilike(like),
                        cast(Person.aliases, String).ilike(like),
                        cast(Person.contact_methods, String).ilike(like),
                        cast(Person.tags, String).ilike(like),
                    )
                )
            return list(session.scalars(statement))

    def delete_person(self, person_id: str) -> bool:
        """删除人物及其级联业务记录。"""

        with self.transaction() as session:
            person = session.get(Person, person_id)
            if person is None:
                return False
            session.delete(person)
            return True

    def merge_people(self, source_person_id: str, target_person_id: str) -> tuple[Person, dict]:
        """事务化合并人物资料与全部业务记录，并删除来源人物。"""

        if source_person_id == target_person_id:
            raise ValueError("source and target person must differ")
        with self.transaction() as session:
            source = self._require_person(session, source_person_id)
            target = self._require_person(session, target_person_id)
            before = {"source": self.to_dict(source), "target": self.to_dict(target)}

            # 稳定字段以目标人物为准，目标缺失时才从来源补齐。
            target.aliases = sorted(
                set(target.aliases) | set(source.aliases) | {source.display_name}
            )
            merged_contacts = {key: list(values) for key, values in target.contact_methods.items()}
            for key, values in source.contact_methods.items():
                merged_contacts[key] = sorted(set(merged_contacts.get(key, [])) | set(values))
            target.contact_methods = merged_contacts
            organizations = {
                json.dumps(item, ensure_ascii=False, sort_keys=True): item
                for item in [*target.organizations, *source.organizations]
            }
            target.organizations = list(organizations.values())
            target.tags = sorted(set(target.tags) | set(source.tags))
            target.pronouns = target.pronouns or source.pronouns
            target.relationship_to_me = target.relationship_to_me or source.relationship_to_me
            target.contact_interval_days = (
                target.contact_interval_days or source.contact_interval_days
            )
            target.profile_notes = target.profile_notes or source.profile_notes
            if source.last_interaction_at and (
                target.last_interaction_at is None
                or source.last_interaction_at > target.last_interaction_at
            ):
                target.last_interaction_at = source.last_interaction_at

            # 先重绑互动和提醒；Fact 的复合唯一键需要逐条去重后再迁移。
            for interaction in session.scalars(
                select(Interaction).where(Interaction.person_id == source.id)
            ):
                interaction.person_id = target.id
            for reminder in session.scalars(
                select(Reminder).where(Reminder.person_id == source.id)
            ):
                reminder.person_id = target.id
            for fact in list(session.scalars(select(Fact).where(Fact.person_id == source.id))):
                duplicate = session.scalar(
                    select(Fact).where(
                        Fact.person_id == target.id,
                        Fact.fact_type == fact.fact_type,
                        Fact.content_hash == fact.content_hash,
                    )
                )
                if duplicate is not None:
                    session.delete(fact)
                else:
                    fact.person_id = target.id
            session.flush()
            session.delete(source)
            session.flush()
            return target, before

    @staticmethod
    def _complete_eligible_reminders(session: Session, interaction: Interaction) -> list[Reminder]:
        """用有效主动互动完成时间窗内的待办提醒。"""

        if interaction.direction not in {"outbound", "mutual"}:
            return []
        statement = select(Reminder).where(
            Reminder.person_id == interaction.person_id,
            Reminder.status.in_([ReminderStatus.PENDING.value, ReminderStatus.SNOOZED.value]),
            Reminder.created_at <= interaction.occurred_at,
        )
        # SQLite 的 datetime + timedelta 会退化为数值运算，因此时间窗在 Python 比较。
        completed = [
            reminder
            for reminder in session.scalars(statement)
            if interaction.occurred_at <= reminder.due_at + timedelta(days=7)
        ]
        for reminder in completed:
            reminder.status = ReminderStatus.COMPLETED.value
            reminder.completed_at = interaction.occurred_at
            reminder.completion_interaction_id = interaction.id
        return completed

    def record_interaction(self, **values: Any) -> tuple[Interaction, bool, int]:
        """幂等记录互动，并更新最后互动时间及自动完成提醒。"""

        with self.transaction() as session:
            self._require_person(session, values["person_id"])
            source_type = values["source_type"]
            source_event_key = values.get("source_event_key")
            if source_event_key:
                existing = session.scalar(
                    select(Interaction).where(
                        Interaction.source_type == source_type,
                        Interaction.source_event_key == source_event_key,
                    )
                )
                if existing:
                    return existing, False, 0
            interaction = Interaction(**values)
            session.add(interaction)
            session.flush()
            person = self._require_person(session, interaction.person_id)
            if (
                person.last_interaction_at is None
                or interaction.occurred_at > person.last_interaction_at
            ):
                # 较老的补录消息不能让 last_interaction_at 倒退。
                person.last_interaction_at = interaction.occurred_at
            completed = self._complete_eligible_reminders(session, interaction)
            session.flush()
            return interaction, True, len(completed)

    def list_interactions(
        self, person_id: str | None = None, limit: int = 100
    ) -> list[Interaction]:
        """按时间倒序列出互动。"""

        with self._sessions() as session:
            statement = select(Interaction).order_by(Interaction.occurred_at.desc()).limit(limit)
            if person_id:
                statement = statement.where(Interaction.person_id == person_id)
            return list(session.scalars(statement))

    def daily_summary(self, start: datetime, end: datetime) -> dict[str, Any]:
        """按半开时间窗汇总关系变化，不返回互动、事实或提醒正文。"""

        start_utc, end_utc = ensure_utc(start), ensure_utc(end)
        if start_utc >= end_utc:
            raise ValueError("daily summary start must be earlier than end")
        with self._sessions() as session:
            # 互动按实际发生时间归日；补录时间不会改变历史所属日期。
            interaction_rows = session.execute(
                select(Interaction, Person.display_name)
                .join(Person, Person.id == Interaction.person_id)
                .where(Interaction.occurred_at >= start_utc, Interaction.occurred_at < end_utc)
                .order_by(Interaction.occurred_at)
            ).all()
            # 事实按观察时间归日；只暴露类别和人物，不暴露内容。
            fact_rows = session.execute(
                select(Fact, Person.display_name)
                .join(Person, Person.id == Fact.person_id)
                .where(Fact.observed_at >= start_utc, Fact.observed_at < end_utc)
                .order_by(Fact.observed_at)
            ).all()
            # 提醒状态变化按更新时间归日，pending 不视为用户已完成的变化。
            reminder_rows = session.execute(
                select(Reminder, Person.display_name)
                .join(Person, Person.id == Reminder.person_id)
                .where(Reminder.updated_at >= start_utc, Reminder.updated_at < end_utc)
                .where(Reminder.status != ReminderStatus.PENDING.value)
                .order_by(Reminder.updated_at)
            ).all()

        def counts(values: list[str]) -> dict[str, int]:
            """生成键稳定的分类计数，便于下游确定性渲染。"""

            result: dict[str, int] = {}
            for value in values:
                result[value] = result.get(value, 0) + 1
            return dict(sorted(result.items()))

        people = sorted({name for _item, name in interaction_rows})
        fact_people = sorted({name for _item, name in fact_rows})
        reminder_people = sorted({name for _item, name in reminder_rows})
        return {
            "window_start": start_utc.isoformat(),
            "window_end": end_utc.isoformat(),
            "interactions": {
                "count": len(interaction_rows),
                "person_count": len(people),
                "people": people,
                "directions": counts([item.direction for item, _name in interaction_rows]),
                "channels": counts([item.channel for item, _name in interaction_rows]),
            },
            "facts": {
                "count": len(fact_rows),
                "people": fact_people,
                "types": counts([item.fact_type for item, _name in fact_rows]),
            },
            "reminder_changes": {
                "count": len(reminder_rows),
                "people": reminder_people,
                "statuses": counts([item.status for item, _name in reminder_rows]),
            },
        }

    @staticmethod
    def fact_hash(content: str) -> str:
        """以去首尾空白后的文本生成稳定事实哈希。"""

        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    def record_fact(
        self,
        *,
        person_id: str,
        fact_type: str,
        content: str,
        observed_at: datetime,
        confidence: float | None = None,
        source_interaction_id: str | None = None,
    ) -> tuple[Fact, bool]:
        """自动确认事实；同类别的新内容使旧 active 事实变为 superseded。"""

        digest = self.fact_hash(content)
        with self.transaction() as session:
            self._require_person(session, person_id)
            existing = session.scalar(
                select(Fact).where(
                    Fact.person_id == person_id,
                    Fact.fact_type == fact_type,
                    Fact.content_hash == digest,
                )
            )
            if existing:
                return existing, False
            for old in session.scalars(
                select(Fact).where(
                    Fact.person_id == person_id,
                    Fact.fact_type == fact_type,
                    Fact.status == FactStatus.ACTIVE.value,
                )
            ):
                old.status = FactStatus.SUPERSEDED.value
            fact = Fact(
                person_id=person_id,
                fact_type=fact_type,
                content=content.strip(),
                observed_at=ensure_utc(observed_at),
                confidence=confidence,
                source_interaction_id=source_interaction_id,
                content_hash=digest,
            )
            session.add(fact)
            session.flush()
            return fact, True

    def list_facts(self, person_id: str | None = None, limit: int = 100) -> list[Fact]:
        """按观察时间倒序列出事实。"""

        with self._sessions() as session:
            statement = select(Fact).order_by(Fact.observed_at.desc()).limit(limit)
            if person_id:
                statement = statement.where(Fact.person_id == person_id)
            return list(session.scalars(statement))

    def update_fact_status(self, fact_id: str, status: str) -> tuple[Fact, dict]:
        """更新事实生命周期并返回修改前快照。"""

        with self.transaction() as session:
            fact = session.get(Fact, fact_id)
            if fact is None:
                raise ValueError("fact not found")
            before = self.to_dict(fact)
            fact.status = status
            session.flush()
            return fact, before

    def create_reminder(self, **values: Any) -> Reminder:
        """创建提醒。"""

        with self.transaction() as session:
            self._require_person(session, values["person_id"])
            reminder = Reminder(**values)
            session.add(reminder)
            session.flush()
            return reminder

    def get_reminder(self, reminder_id: str) -> Reminder | None:
        """读取提醒。"""

        with self._sessions() as session:
            return session.get(Reminder, reminder_id)

    def update_reminder(self, reminder_id: str, **values: Any) -> tuple[Reminder, dict]:
        """更新提醒并返回修改前快照。"""

        with self.transaction() as session:
            reminder = session.get(Reminder, reminder_id)
            if reminder is None:
                raise ValueError("reminder not found")
            before = self.to_dict(reminder)
            for name, value in values.items():
                setattr(reminder, name, value)
            session.flush()
            return reminder, before

    def list_reminders(
        self, person_id: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[Reminder]:
        """按到期时间列出提醒。"""

        with self._sessions() as session:
            statement = select(Reminder).order_by(Reminder.due_at).limit(limit)
            if person_id:
                statement = statement.where(Reminder.person_id == person_id)
            if status:
                statement = statement.where(Reminder.status == status)
            return list(session.scalars(statement))

    def list_reminders_due_between(
        self, start: datetime, end: datetime, *, excluded_statuses: set[str] | None = None
    ) -> list[Reminder]:
        """返回时间窗内提醒，供指标模块通过公开仓储接口计算。"""

        with self._sessions() as session:
            statement = select(Reminder).where(
                Reminder.due_at >= ensure_utc(start),
                Reminder.due_at < ensure_utc(end),
            )
            if excluded_statuses:
                statement = statement.where(Reminder.status.not_in(excluded_statuses))
            return list(session.scalars(statement.order_by(Reminder.due_at)))

    def list_yearly_important_reminders(self) -> list[Reminder]:
        """列出年度生日和纪念日模板，供提醒策略生成新周期。"""

        with self._sessions() as session:
            return list(
                session.scalars(
                    select(Reminder).where(
                        Reminder.recurrence_rule == "yearly",
                        Reminder.reminder_type.in_(["birthday", "anniversary"]),
                    )
                )
            )

    def find_reminder_cycle(
        self, person_id: str, reminder_type: str, due_at: datetime
    ) -> Reminder | None:
        """查询人物在指定时间的同类提醒，避免年度周期重复物化。"""

        with self._sessions() as session:
            return session.scalar(
                select(Reminder).where(
                    Reminder.person_id == person_id,
                    Reminder.reminder_type == reminder_type,
                    Reminder.due_at == ensure_utc(due_at),
                )
            )

    def list_open_important_reminders(
        self, start: datetime, end: datetime, limit: int
    ) -> list[Reminder]:
        """按到期时间返回窗口内尚未处理的重要日期。"""

        with self._sessions() as session:
            return list(
                session.scalars(
                    select(Reminder)
                    .where(
                        Reminder.status.in_(["pending", "snoozed"]),
                        Reminder.reminder_type.in_(["birthday", "anniversary"]),
                        Reminder.due_at >= ensure_utc(start),
                        Reminder.due_at < ensure_utc(end),
                    )
                    .order_by(Reminder.due_at)
                    .limit(limit)
                )
            )

    def list_active_cadence_people(self) -> list[Person]:
        """返回配置联系节奏的活跃人物。"""

        with self._sessions() as session:
            return list(
                session.scalars(
                    select(Person).where(
                        Person.status == "active", Person.contact_interval_days.is_not(None)
                    )
                )
            )

    def has_open_follow_up(self, person_id: str) -> bool:
        """判断人物是否已有未完成的主动联系提醒。"""

        with self._sessions() as session:
            return (
                session.scalar(
                    select(Reminder.id).where(
                        Reminder.person_id == person_id,
                        Reminder.reminder_type == "follow_up",
                        Reminder.status.in_(["pending", "snoozed"]),
                    )
                )
                is not None
            )

    def count_follow_ups_created_between(self, start: datetime, end: datetime) -> int:
        """统计本周由提醒策略创建的主动联系项，维持跨进程调用预算。"""

        with self._sessions() as session:
            return int(
                session.scalar(
                    select(func.count(Reminder.id)).where(
                        Reminder.reminder_type == "follow_up",
                        Reminder.created_at >= ensure_utc(start),
                        Reminder.created_at < ensure_utc(end),
                    )
                )
                or 0
            )

    def import_wechat_batch(
        self, source: str, interactions: list[dict[str, Any]], facts: list[dict[str, Any]]
    ) -> tuple[int, int]:
        """在单一事务内导入微信摘要和事实；任一错误都会整批回滚。"""

        allowed_directions = {"inbound", "outbound", "mutual"}
        allowed_interaction_types = {"message", "call", "meeting", "manual_note", "other"}
        allowed_channels = {"wechat", "phone", "in_person", "email", "manual", "other"}
        allowed_fact_types = {
            "preference",
            "boundary",
            "life_event",
            "organization",
            "contact",
            "other",
        }
        for item in interactions:
            if item["direction"] not in allowed_directions:
                raise ValueError("invalid interaction direction")
            if item["interaction_type"] not in allowed_interaction_types:
                raise ValueError("invalid interaction type")
            if item["channel"] not in allowed_channels:
                raise ValueError("invalid interaction channel")
        for item in facts:
            if item["fact_type"] not in allowed_fact_types:
                raise ValueError("invalid fact type")

        accepted = 0
        duplicates = 0
        interaction_by_key: dict[str, Interaction] = {}
        with self.transaction() as session:
            for item in interactions:
                person = self._resolve_person(session, item["person_name"], item.get("wxid"))
                event_key = item["source_event_key"]
                existing = session.scalar(
                    select(Interaction).where(
                        Interaction.source_type == source,
                        Interaction.source_event_key == event_key,
                    )
                )
                if existing:
                    duplicates += 1
                    interaction_by_key[event_key] = existing
                    continue
                interaction = Interaction(
                    person_id=person.id,
                    occurred_at=ensure_utc(item["occurred_at"]),
                    interaction_type=item["interaction_type"],
                    channel=item["channel"],
                    direction=item["direction"],
                    summary=item["summary"].strip(),
                    source_type=source,
                    source_reference=item.get("source_reference"),
                    source_event_key=event_key,
                )
                session.add(interaction)
                session.flush()
                if (
                    person.last_interaction_at is None
                    or interaction.occurred_at > person.last_interaction_at
                ):
                    person.last_interaction_at = interaction.occurred_at
                self._complete_eligible_reminders(session, interaction)
                interaction_by_key[event_key] = interaction
                accepted += 1

            for item in facts:
                person = self._resolve_person(session, item["person_name"], item.get("wxid"))
                content = item["content"].strip()
                digest = self.fact_hash(content)
                existing = session.scalar(
                    select(Fact).where(
                        Fact.person_id == person.id,
                        Fact.fact_type == item["fact_type"],
                        Fact.content_hash == digest,
                    )
                )
                if existing:
                    duplicates += 1
                    continue
                for old in session.scalars(
                    select(Fact).where(
                        Fact.person_id == person.id,
                        Fact.fact_type == item["fact_type"],
                        Fact.status == FactStatus.ACTIVE.value,
                    )
                ):
                    old.status = FactStatus.SUPERSEDED.value
                source_interaction = interaction_by_key.get(item.get("source_event_key", ""))
                session.add(
                    Fact(
                        person_id=person.id,
                        fact_type=item["fact_type"],
                        content=content,
                        observed_at=ensure_utc(item["observed_at"]),
                        confidence=item.get("confidence"),
                        source_interaction_id=source_interaction.id if source_interaction else None,
                        content_hash=digest,
                    )
                )
                accepted += 1
        return accepted, duplicates

    @staticmethod
    def _resolve_person(session: Session, display_name: str, wxid: str | None) -> Person:
        """按 wxid 优先、姓名次之解析人物；不存在时创建最小人物。"""

        person = None
        if wxid:
            # 四表约束下联系方式保存在 JSON，SQLite json_each 用于精确匹配 wxid。
            person = session.scalar(
                select(Person)
                .where(
                    text(
                        "EXISTS (SELECT 1 FROM json_each(people.contact_methods, '$.wxid') "
                        "WHERE json_each.value = :wxid)"
                    )
                )
                .params(wxid=wxid)
            )
        if person is None:
            person = session.scalar(select(Person).where(Person.display_name == display_name))
        if person is None:
            contacts = {"wxid": [wxid]} if wxid else {}
            person = Person(display_name=display_name, contact_methods=contacts)
            session.add(person)
            session.flush()
        return person

    def backup(self, destination: str | Path) -> Path:
        """把文件型 SQLite 数据库复制到明确目标并返回路径。"""

        database = self.engine.url.database
        if not database or database == ":memory:":
            raise ValueError("in-memory database cannot be backed up")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.engine.connect() as connection:
            connection.execute(text("PRAGMA wal_checkpoint(FULL)"))
        shutil.copy2(database, target)
        return target

    def integrity_check(self) -> str:
        """运行 SQLite 完整性检查。"""

        with self.engine.connect() as connection:
            return str(connection.execute(text("PRAGMA integrity_check")).scalar_one())

    @staticmethod
    def to_dict(entity: Any | None) -> dict[str, Any] | None:
        """把 ORM 实体转换为 JSON 友好的稳定字典。"""

        if entity is None:
            return None
        result = {column.name: getattr(entity, column.name) for column in entity.__table__.columns}
        for name, value in result.items():
            if isinstance(value, datetime):
                result[name] = ensure_utc(value).isoformat()
        return result
