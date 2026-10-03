"""Run with the optional Epic venv; actual SDK types, fixture HTTP only."""
import asyncio
import json
import io
from pathlib import Path
import sys
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel
from platforms.epic.model_bridge import install

class Answer(BaseModel):
    selected: list[int]

async def smoke():
    sent = []
    def respond(request):
        body = json.loads(request.content)
        assert request.url == "https://fixture.invalid/v1/chat/completions"
        assert body["model"] == "configured-current-model"
        assert body["messages"][1]["content"][0]["image_url"]["url"].startswith("data:image/png;base64,")
        sent.append(body)
        return httpx.Response(200, json={"choices":[{"message":{"content":"{\"selected\":[1,3]}"}}]})
    original_client = httpx.AsyncClient
    original_genai = genai.Client
    try:
        install({"name":"configured-current-model", "api_key":"fixture", "base_url":"https://fixture.invalid/v1"})
        client = genai.Client(api_key="fixture")
        uploaded = await client.aio.files.upload(file=io.BytesIO(b"fixture-image"))
        part = types.Part.from_uri(file_uri=uploaded.uri, mime_type=uploaded.mime_type)
        with patch("httpx.AsyncClient", side_effect=lambda **kwargs: original_client(
                transport=httpx.MockTransport(respond), **kwargs)):
            result = await client.aio.models.generate_content(model="sdk-legacy-model",
                contents=[types.Content(role="user", parts=[part, types.Part.from_text(text="Select tiles")])],
                config=types.GenerateContentConfig(system_instruction="Return selections", response_schema=Answer))
        assert result.parsed.selected == [1, 3] and len(sent) == 1
        print("Epic model bridge smoke: passed (fixture HTTP, configured model, SDK schema)")
    finally:
        genai.Client = original_genai

if __name__ == "__main__":
    asyncio.run(smoke())
