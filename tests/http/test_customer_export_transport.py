"""Private archive handles and concurrency slots survive transport disconnects."""

import asyncio
from io import BytesIO

import pytest
from starlette.requests import ClientDisconnect

from tabula_rasa.http.routes.customer_export import PrivateExportResponse, _slots


@pytest.mark.parametrize('disconnect', [False, True])
def test_stream_completion_or_disconnect_closes_file_and_releases_quota(disconnect):
    assert _slots.acquire(blocking=False)
    stream = BytesIO(b'x' * 100_000)
    response = PrivateExportResponse(stream)
    messages = []

    async def receive():
        return {'type': 'http.disconnect'}

    async def send(message):
        messages.append(message)
        if disconnect and message['type'] == 'http.response.body':
            raise OSError('synthetic disconnected client')

    async def deliver():
        await response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send)

    if disconnect:
        with pytest.raises(ClientDisconnect):
            asyncio.run(deliver())
    else:
        asyncio.run(deliver())
        assert sum(len(item.get('body', b'')) for item in messages) == 100_000
    assert stream.closed
    # Both slots are available again, even after a failed ASGI send.
    assert _slots.acquire(blocking=False)
    assert _slots.acquire(blocking=False)
    _slots.release()
    _slots.release()
