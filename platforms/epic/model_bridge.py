"""Small OpenAI-compatible vision bridge for the optional hCaptcha SDK.

GPL adaptation of upstream extensions/llm_adapter.py. No network/model import at
module load; images and responses are bounded and never logged by this bridge.
"""
import base64
import json
from types import SimpleNamespace
from pathlib import Path


def install(settings):
    from google import genai
    from google.genai import types
    import httpx

    class Files:
        def __init__(self, storage): self.storage = storage

        async def upload(self, *, file, **kwargs):
            if hasattr(file, "read"):
                raw = file.read(4 * 1024 * 1024 + 1)
            else:
                with Path(file).open("rb") as stream:
                    raw = stream.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024: raise ValueError("challenge_image_limit")
            if len(self.storage) >= 16 or sum(map(len, self.storage.values())) + len(raw) > 16 * 1024 * 1024:
                raise ValueError("challenge_image_limit")
            name = "memory_" + str(len(self.storage))
            self.storage[name] = raw
            suffix = Path(str(getattr(file, "name", file))).suffix.lower()
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(suffix, "image/png")
            return types.File(name=name, uri=name, mime_type=mime)

    class Models:
        def __init__(self, storage): self.storage = storage

        async def generate_content(self, *, model, contents, config=None, **kwargs):
            messages = []
            instruction = getattr(config, "system_instruction", None)
            schema = getattr(config, "response_schema", None)
            if schema is not None and hasattr(schema, "model_json_schema"):
                instruction = str(instruction or "") + "\nReturn JSON matching: " + json.dumps(schema.model_json_schema())
            if instruction: messages.append({"role": "system", "content": str(instruction)})
            for content in contents if isinstance(contents, list) else [contents]:
                parts = []
                for part in getattr(content, "parts", []) or []:
                    if getattr(part, "text", None):
                        parts.append({"type": "text", "text": part.text})
                    data = getattr(part, "inline_data", None)
                    file = getattr(part, "file_data", None)
                    image = getattr(data, "data", None) if data else self.storage.get(getattr(file, "file_uri", ""))
                    if image:
                        mime = getattr(data if data else file, "mime_type", "image/png")
                        if mime not in {"image/png", "image/jpeg", "image/webp"}:
                            raise ValueError("challenge_image_type")
                        parts.append({"type": "image_url", "image_url": {"url":
                            "data:" + mime + ";base64," + base64.b64encode(image).decode()}})
                if parts: messages.append({"role": getattr(content, "role", None) or "user", "content": parts})
            payload = {"model": settings["name"], "messages": messages}
            if schema: payload["response_format"] = {"type": "json_object"}
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
                async with client.stream("POST", settings["base_url"].rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + settings["api_key"]}, json=payload) as response:
                    if response.status_code != 200: raise ValueError("challenge_provider_error")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 1024 * 1024: raise ValueError("challenge_provider_response_limit")
            text = json.loads(raw)["choices"][0]["message"]["content"].strip()
            if text.startswith("```"): text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = schema.model_validate_json(text) if schema and hasattr(schema, "model_validate_json") else None
            self.storage.clear()
            return SimpleNamespace(text=text, parsed=parsed,
                model_dump=lambda **_: {"text": text, "parsed": parsed.model_dump() if parsed else None})

    class Client:
        def __init__(self, *args, **kwargs):
            storage = {}
            self.aio = SimpleNamespace(files=Files(storage), models=Models(storage))

    genai.Client = Client
