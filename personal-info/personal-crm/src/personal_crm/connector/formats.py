"""将微信本机媒体转为普通文件；不保存密钥或加密副本。"""

import io
import re
import tempfile
import wave
from pathlib import Path


def image_bytes(path, account_dir, configured_uin=None):
    from chatlog_keeper.wechat_image import (
        _decrypt_v1v2,
        decrypt_wechat_dat,
        derive_v2_key_from_uin,
        wxgf_to_jpeg,
    )
    from PIL import Image

    from .media_reader import MediaUnavailable

    raw = Path(path).read_bytes()
    if raw.startswith(b"\x07\x08V2\x08\x07"):
        import hashlib

        account = Path(account_dir).name
        wxid, suffix = account.rsplit("_", 1)
        if configured_uin is not None:
            uin = configured_uin
        else:
            # 微信自己的账号统计文件名含 UIN；只读取账号标识，不扫描进程。
            app_data = Path(account_dir).parent.parent / "app_data"
            candidates = {
                int(m[1])
                for p in app_data.glob("**/key_*.statistic")
                if (m := re.match(r"key_(\d+)_", p.name))
            }
            uin = next(
                (u for u in candidates if hashlib.md5(str(u).encode()).hexdigest()[:4] == suffix),
                None,
            )
        if uin is None:
            raise MediaUnavailable("media_image_account_unavailable")
        data = _decrypt_v1v2(raw, derive_v2_key_from_uin(uin, wxid), uin & 255)
    else:
        data = decrypt_wechat_dat(Path(path))
    if data and data.startswith(b"wxgf"):
        data = wxgf_to_jpeg(data)
    if not data:
        raise MediaUnavailable("media_image_decode_unavailable")
    try:
        with Image.open(io.BytesIO(data)) as image:
            fmt = image.format
            image.verify()
        extension, mime = {
            "JPEG": ("jpg", "image/jpeg"),
            "PNG": ("png", "image/png"),
            "GIF": ("gif", "image/gif"),
            "WEBP": ("webp", "image/webp"),
        }[fmt]
    except (OSError, ValueError, KeyError):
        raise MediaUnavailable("media_image_invalid") from None
    return data, extension, mime


def voice_wav(data):
    import pilk

    from .media_reader import MediaUnavailable

    with tempfile.TemporaryDirectory(prefix="crm-voice-") as folder:
        source, output = Path(folder) / "voice.silk", Path(folder) / "voice.pcm"
        source.write_bytes(data)
        try:
            pilk.decode(str(source), str(output), 24000)
            pcm = output.read_bytes()
            if not pcm or len(pcm) % 2:
                raise ValueError()
        except (OSError, ValueError, RuntimeError):
            raise MediaUnavailable("media_voice_decode_unavailable") from None
    result = io.BytesIO()
    with wave.open(result, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    return result.getvalue()
