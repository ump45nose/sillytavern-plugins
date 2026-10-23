import httpx
from fastapi import Depends, HTTPException, Query
from .proxy import stream_response


def register(app, settings, media, authenticated):
    @app.get("/api/v1/media/image", dependencies=[Depends(authenticated)])
    async def image(ref: str = Query(max_length=1024)):
        try:
            value = media.parse_ref(ref)
        except (ValueError, KeyError, TypeError):
            raise HTTPException(400) from None
        if value["s"] == "emby":
            if not settings.emby_token: raise HTTPException(503)
            request = media.client.build_request("GET", settings.emby_url.rstrip("/") + "/emby/Items/" + value["id"] + "/Images/Primary",
                params={"maxWidth": 600}, headers={"X-Emby-Token": settings.emby_token.get_secret_value()})
        else:
            if not settings.navidrome_password: raise HTTPException(503)
            request = media.client.build_request("POST", settings.navidrome_url.rstrip("/") + "/rest/getCoverArt.view",
                data={**media.nav_auth(), "id": value["id"], "size": 600})
        try:
            response = await media.client.send(request, stream=True)
        except httpx.RequestError:
            raise HTTPException(502) from None
        if response.status_code != 200 or not response.headers.get("content-type", "").startswith("image/"):
            code = 404 if response.status_code == 404 else 502
            await response.aclose()
            raise HTTPException(code)
        return stream_response(response, media_type=response.headers["content-type"],
                               headers={"Cache-Control": "private, max-age=300"})
