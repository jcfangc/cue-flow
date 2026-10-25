"""Valid client and server state transitions for mypy."""

from typing import assert_type
from generated import (
    ClientReady,
    ClientWaiting,
    Query,
    Received,
    ServerReady,
    ServerWaiting,
)

async def client_flow(session: ClientReady) -> ClientWaiting:
    message = Query.model_validate({"id": "q1", "sequence": "ACGT", "topK": 5})
    return await session.send_query(message)

async def server_flow(session: ServerReady) -> None:
    event = await session.recv_query()
    if isinstance(event, Received):
        assert_type(event.message, Query)
        assert_type(event.session, ServerWaiting)
