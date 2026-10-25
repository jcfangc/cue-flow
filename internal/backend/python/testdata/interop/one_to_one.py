"""Python peer for the 1:1 case: one Query receives exactly one Result."""

from __future__ import annotations

import sys

import generated as api
from common import StreamConnection, TcpTransport, listen_once, main as run_peer, run_client_flow


async def serve_connection(connection: StreamConnection) -> None:
    transport = TcpTransport(connection)
    query = await api.ServerReady(transport).recv_query()
    if isinstance(query, api.Closed):
        raise RuntimeError("received Close while expecting Query")
    if query.message.id != "query-0":
        raise RuntimeError(f"unexpected Query ID: {query.message.id}")
    result = api.Result.model_validate({"id": query.message.id, "result": "matched"})
    ready = await query.session.send_result(result)
    await ready.recv_close()


async def run_server(port: int) -> None:
    await listen_once(port, serve_connection)


async def run_client_session(connection: StreamConnection) -> None:
    session = api.ClientReady(TcpTransport(connection))
    query = api.Query.model_validate({"id": "query-0"})
    waiting = await session.send_query(query)
    result = await waiting.recv_result()
    if isinstance(result, api.Closed):
        raise RuntimeError("received Close while expecting Result")
    if result.message.id != "query-0" or result.message.result != "matched":
        raise RuntimeError(f"unexpected Result: {result.message!r}")
    await result.session.close()


async def run_client(port: int) -> None:
    await run_client_flow(port, run_client_session)


if __name__ == "__main__":
    raise SystemExit(run_peer(sys.argv[1:], run_server, run_client))
