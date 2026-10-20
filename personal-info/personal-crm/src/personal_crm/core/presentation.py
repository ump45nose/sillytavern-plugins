"""微信来源标签转换为可读姓名与单一附件引用。"""

import re


def label_names(value):
    value = str(value or "").strip()
    if value.startswith("备注/昵称："):
        return value.removeprefix("备注/昵称：").strip(), ""
    if value.startswith("备注："):
        remark, _, nickname = value.removeprefix("备注：").partition(" · 昵称：")
        return remark.strip(), nickname.strip()
    if value.startswith("昵称："):
        return "", value.removeprefix("昵称：").strip()
    return "", ""


def short_name(value):
    remark, nickname = label_names(value)
    return remark or nickname or str(value or "").strip()


def directory_name(item):
    remark, nickname = label_names(item.get("label"))
    return (
        str(item.get("remark") or "").strip()
        or remark
        or str(item.get("nickname") or "").strip()
        or nickname
        or short_name(item.get("label"))
        or item["conversation_id"]
    )


def attachment_content(content, name, attachment_id):
    # 仅替换整段通用占位；实际说明、时长和文件名不丢弃。
    if re.fullmatch(r"\[文件[:：].*\]", content.strip()) or content.strip() in {
        "[图片]",
        "[语音]",
        "[视频]",
        "[文件]",
        "[附件]",
        f"[{name}]",
    }:
        content = ""
    link = f"[{name}](attachment://{attachment_id})"
    return f"{content} {link}" if content else link


def clean_chat(content, replacements):
    """只改采集行的发言人标签与紧邻引用的重复占位，不重建正文。"""

    def speaker(match):
        name = match[2]
        return match[1] + replacements.get(name, short_name(name)) + "："

    content = re.sub(
        r"^((?:\d{4}-\d{2}-\d{2} )?\d{2}:\d{2} )"
        r"(备注：.*? · 昵称：[^：\n]*|备注/昵称：[^：\n]*|备注：[^：\n]*|昵称：[^：\n]*|[^：\n]+)：",
        speaker,
        content,
        flags=re.MULTILINE,
    )
    return re.sub(
        r"\[(图片|语音|视频|文件|附件)\] +(?=\[\1\]\(attachment://[\w-]+\))",
        "",
        content,
    )
