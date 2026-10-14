"""Shared bounded raw uploads for the independent import workflows."""

from fastapi import Request

from tabula_rasa.application.import_files import MAX_IMPORT_BYTES
from ..errors import TransportError


BINARY_UPLOAD = {"requestBody": {"required": True, "content": {
    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}}


async def read_import_upload(request: Request) -> bytes:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().casefold() != "application/octet-stream":
        raise TransportError("validation")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_IMPORT_BYTES:
            raise TransportError("validation")
        content.extend(chunk)
    return bytes(content)
