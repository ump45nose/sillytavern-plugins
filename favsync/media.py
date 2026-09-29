"""Bounded media signature validation shared by download adapters."""

def valid_media(path):
    try:
        with path.open("rb") as stream:
            head = stream.read(16)
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return head.startswith(b"\xff\xd8\xff")
    if suffix == ".png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".webp":
        return head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    if suffix == ".gif":
        return head.startswith((b"GIF87a", b"GIF89a"))
    if suffix in (".mp4", ".mov", ".heic"):
        return len(head) >= 12 and head[4:8] == b"ftyp"
    return False

