from contextlib import asynccontextmanager

from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask


@asynccontextmanager
async def mutation(manager, *sources, enabled=True):
    """Once a write is attempted its outcome may be uncertain; never retain old data."""
    try:
        yield
    finally:
        if enabled:
            await manager.invalidate(*sources)


def stream_response(upstream, *, headers=None, media_type=None):
    async def chunks():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
    return StreamingResponse(chunks(), status_code=upstream.status_code,
        headers=headers, media_type=media_type, background=BackgroundTask(upstream.aclose))
