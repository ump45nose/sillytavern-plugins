from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser


class UploadTooLarge(MultiPartException):
    pass


def too_large(limit_mb):
    return JSONResponse({'detail': f'文件超过 {limit_mb} MB'}, status_code=413)


async def read_upload(request, limit_mb):
    limit = limit_mb * 1024 * 1024
    # Keep the file in bounded memory: the container's /tmp is smaller than the
    # instance upload limit. Multipart framing has its own small allowance.
    body_limit = limit + 65536

    async def bounded_stream():
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > body_limit:
                raise UploadTooLarge('upload limit exceeded')
            yield chunk

    if request.headers.get('content-type', '').split(';', 1)[0].strip().lower() != 'multipart/form-data':
        raise HTTPException(400)
    parser = MultiPartParser(request.headers, bounded_stream(), max_files=1, max_fields=0)
    parser.spool_max_size = body_limit + 1
    try:
        form = await parser.parse()
    except UploadTooLarge:
        return too_large(limit_mb)
    except (MultiPartException, ValueError):
        raise HTTPException(400) from None
    try:
        items = form.multi_items()
        if len(items) != 1 or items[0][0] != 'file' or not isinstance(items[0][1], UploadFile):
            raise HTTPException(400)
        file = items[0][1]
        if not file.filename or invalid_filename(file.filename):
            raise HTTPException(400)
        content = await file.read(limit + 1)
        if len(content) > limit:
            return too_large(limit_mb)
        return file.filename, content
    finally:
        await form.close()


def invalid_filename(filename):
    return filename in ('.', '..') or any(c in filename for c in ('/', '\\', '\r', '\n', '\x00'))
