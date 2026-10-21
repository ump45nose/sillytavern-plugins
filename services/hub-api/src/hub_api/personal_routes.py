import re
from datetime import date, datetime, timedelta
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import Depends, Header, HTTPException
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from starlette.background import BackgroundTask
from .sources.personal import local_time
from .recording_days import RecordingDays


class InteractionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    person_id: str | None = None
    person_name: str | None = None
    channel: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=100000)
    occurred_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def person(self):
        if not self.person_id and not self.person_name:
            raise ValueError("person required")
        return self


def register(app, settings, personal, authenticated, now, manager):
    recording_days = RecordingDays(personal)

    @app.get('/api/v1/recordings', dependencies=[Depends(authenticated)])
    async def list_recordings(source: Literal['plaud'] = 'plaud', before: date | None = None,
                              limit: int = 14):
        if not 1 <= limit <= 30:
            raise HTTPException(400)
        if not settings.plaud_token:
            raise HTTPException(503)
        try:
            return await recording_days.get(before or now().date()+timedelta(days=1), limit)
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            raise HTTPException(502) from None

    async def invoke(*args, **kwargs):
        try:
            return await personal.request(*args, **kwargs)
        except httpx.HTTPStatusError as exc:
            raise HTTPException(400 if exc.response.status_code in (400, 404, 409, 422) else 502) from None
        except (httpx.RequestError, ValueError, KeyError):
            raise HTTPException(502) from None

    @app.post("/api/v1/crm/interactions", status_code=201, dependencies=[Depends(authenticated)])
    async def create_interaction(body: InteractionInput):
        if not settings.crm_write_token:
            raise HTTPException(503)
        person_id = body.person_id
        if not person_id:
            people = await invoke("crm", "/api/v1/crm/people", {"query": body.person_name, "limit": 100})
            matches = [p for p in people["items"] if p["name"] == body.person_name]
            if len(matches) != 1 or people.get("next_cursor"):
                raise HTTPException(409)
            person_id = matches[0]["id"]
        time = body.occurred_at or now()
        value = await invoke("crm", "/api/v1/crm/interactions", method="POST", write=True,
            body={"person_ids": [person_id], "channel": body.channel, "content": body.summary,
                  "date": time.astimezone(now().tzinfo).date().isoformat(), "started_at": time.isoformat(), "type": "other", "source": "manual"})
        manager.states.pop("crm", None)
        return {"id": value["id"]}

    def recording(identifier):
        parts = identifier.split(":")
        if len(parts) == 3 and parts[0] == "plaud" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[1]) and re.fullmatch(r"[a-f0-9]{32}", parts[2]):
            return "plaud", "/api/v1/archives/" + parts[1], parts[2]
        if len(parts) == 2 and parts[0] == "crm" and re.fullmatch(r"[a-f0-9-]{32,36}", parts[1]):
            return "crm", "/api/v1/crm/attachments/" + parts[1], None
        raise HTTPException(404)

    async def upstream(source, path, range_header=None):
        token = getattr(settings, source + "_token")
        if not token:
            raise HTTPException(503)
        headers = {"Authorization": "Bearer " + token.get_secret_value()}
        if range_header:
            if not re.fullmatch(r"bytes=(?:\d+-\d*|-\d+)", range_header):
                raise HTTPException(400)
            headers["Range"] = range_header
        request = personal.client.build_request("GET", getattr(settings, source + "_url").rstrip("/") + path, headers=headers)
        try:
            response = await personal.client.send(request, stream=True)
        except httpx.RequestError:
            raise HTTPException(502) from None
        if response.status_code not in (200, 206):
            status = response.status_code
            await response.aclose()
            raise HTTPException(status if status in (404, 416) else 502)
        return response

    @app.get("/api/v1/recordings/{identifier}/audio", dependencies=[Depends(authenticated)])
    async def audio(identifier: str, range: str | None = Header(default=None)):
        source, base, audio_id = recording(identifier)
        response = await upstream(source, base + ("/audio/" + audio_id if source == "plaud" else "/content"), range)
        headers = {k: v for k, v in response.headers.items() if k.lower() in ("content-type", "content-length", "content-range", "accept-ranges")}
        async def chunks():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()
        return StreamingResponse(chunks(), status_code=response.status_code, headers=headers, background=BackgroundTask(response.aclose))

    @app.get("/api/v1/recordings/{identifier}/transcript", dependencies=[Depends(authenticated)])
    async def transcript(identifier: str):
        source, base, _ = recording(identifier)
        if source != "plaud":
            raise HTTPException(404)
        response = await upstream(source, base + "/transcript.md")
        try:
            text = (await response.aread()).decode("utf-8")
            for secret in settings.secrets():
                text = text.replace(secret, "[redacted]")
            return PlainTextResponse(text, media_type="text/markdown")
        finally:
            await response.aclose()
