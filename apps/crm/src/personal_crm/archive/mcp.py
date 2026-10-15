"""MCP 与 HTTP 共用 Archive，不保留旧 CRM 业务工具。"""

from .schemas import IdentityInput, InteractionCreate, InteractionPatch, PersonCreate, PersonPatch


def register_tools(server, archive, read_auth, write_auth):
    def tool(fn, write=False):
        server.tool(
            auth=write_auth if write else read_auth,
            annotations={
                "readOnlyHint": not write,
                "destructiveHint": fn.__name__.startswith(("delete_", "merge_")),
            },
        )(fn)

    def list_people(
        query: str = "", tag: str | None = None, limit: int = 50, cursor: str | None = None
    ):
        """按名称、别名、联系方式、备注及标签搜索人物，按最近交互排序。"""
        return archive.list_people(query=query, tag=tag, limit=limit, cursor=cursor)

    def get_person(person_id: str):
        """读取人物资料、来源身份及最近交互时间。"""
        return archive.get_person(person_id)

    def create_person(data: PersonCreate):
        """创建人物；不会按同名自动合并。"""
        return archive.create_person(data.model_dump())

    def update_person(person_id: str, changes: PersonPatch):
        """修改指定资料字段；省略的字段不变。"""
        return archive.update_person(person_id, changes.model_dump(exclude_unset=True))

    def delete_person(person_id: str):
        """删除人物及只属于此人的交互；多人交互只移除此人关联。"""
        return archive.delete_person(person_id)

    def merge_people(source_person_id: str, target_person_id: str):
        """将来源人物合入目标人物，保留交互和来源身份。"""
        return archive.merge_people(source_person_id, target_person_id)

    def bind_person_identity(person_id: str, identity: IdentityInput):
        """将来源账号身份绑定或改绑至人物，同时纠正该来源的交互关联。"""
        return archive.bind_person_identity(person_id, identity.model_dump())

    def list_interactions(
        person_id: str | None = None,
        start: str | None = None,
        end: str | None = None,
        type: str | None = None,
        channel: str | None = None,
        source: str | None = None,
        query: str = "",
        limit: int = 50,
        cursor: str | None = None,
    ):
        """按人物、日期范围、类型、渠道、来源或正文搜索交互，返回预览及续页游标。"""
        return archive.list_interactions(
            person_id=person_id,
            start=start,
            end=end,
            type=type,
            channel=channel,
            source=source,
            query=query,
            limit=limit,
            cursor=cursor,
        )

    def get_interaction(interaction_id: str, offset_chars: int = 0, limit_chars: int = 16000):
        """读取交互正文和附件 ID；长正文用 next_offset_chars 续读，不丢弃尾部。"""
        if offset_chars < 0 or not 1 <= limit_chars <= 64000:
            raise ValueError("invalid_content_page")
        row = archive.get_interaction(interaction_id)
        content = row["content"]
        row["content"] = content[offset_chars : offset_chars + limit_chars]
        following = offset_chars + len(row["content"])
        return {
            **row,
            "offset_chars": offset_chars,
            "total_chars": len(content),
            "next_offset_chars": following if following < len(content) else None,
        }

    def create_interaction(data: InteractionCreate):
        """记录与一个或多个人的交互，正文只保存一份。"""
        return archive.create_interaction(data.model_dump())

    def update_interaction(interaction_id: str, changes: InteractionPatch):
        """直接编辑交互正文或其他字段；微信后续只追加新增消息，不覆盖修改。"""
        return archive.update_interaction(interaction_id, changes.model_dump(exclude_unset=True))

    def delete_interaction(interaction_id: str):
        """删除交互及人物关联。"""
        return archive.delete_interaction(interaction_id)

    def upload_attachment(
        name: str,
        media_type: str,
        content_base64: str,
        attachment_id: str | None = None,
        offset_bytes: int = 0,
        final: bool = True,
    ):
        """上传 Base64 附件，每块最多 256KiB；后续块传返回 ID 和 next_offset，最后 final=true。"""
        return archive.upload_attachment_chunk(
            name,
            media_type,
            content_base64,
            attachment_id=attachment_id,
            offset_bytes=offset_bytes,
            final=final,
        )

    def read_attachment(attachment_id: str, offset_bytes: int = 0, limit_bytes: int = 65536):
        """读取附件元数据和 Base64 文件分页；available=false 表示文件尚未归档。"""
        return archive.read_attachment(attachment_id, offset_bytes, limit_bytes)

    for fn in (list_people, get_person, list_interactions, get_interaction, read_attachment):
        tool(fn)
    for fn in (
        create_person,
        update_person,
        delete_person,
        merge_people,
        bind_person_identity,
        create_interaction,
        update_interaction,
        delete_interaction,
        upload_attachment,
    ):
        tool(fn, write=True)
