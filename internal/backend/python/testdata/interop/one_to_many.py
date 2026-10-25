"""Python peer for the 1:N case: one Query receives three Result events."""

from __future__ import annotations

import sys

import generated as api
from common import StreamConnection, TcpTransport, listen_once, main as run_peer, run_client_flow


RESULT_COUNT = 3


async def serve_connection(connection: StreamConnection) -> None:
    transport = TcpTransport(connection)
    query = await api.ServerReady(transport).recv_query()
    if isinstance(query, api.Closed):
        raise RuntimeError("received Close while expecting Query")
    query_id = query.message.id
    streaming = query.session
    for index in range(1, RESULT_COUNT + 1):
        result = api.Result.model_validate(
            {"id": f"{query_id}-part-{index}", "result": f"part-{index}"}
        )
        streaming = await streaming.send_result(result)
    await streaming.close()


async def run_server(port: int) -> None:
    await listen_once(port, serve_connection)


async def run_client_session(connection: StreamConnection) -> None:
    session = api.ClientReady(TcpTransport(connection))
    query = api.Query.model_validate({"id": "query-0"})
    streaming = await session.send_query(query)
    for index in range(1, RESULT_COUNT + 1):
        result = await streaming.recv_result()
        if isinstance(result, api.Closed):
            raise RuntimeError("received Close before all Results arrived")
        expected_id = f"query-0-part-{index}"
        expected_result = f"part-{index}"
        if result.message.id != expected_id or result.message.result != expected_result:
            raise RuntimeError(f"unexpected stream Result: {result.message!r}")
        streaming = result.session
    final_event = await streaming.recv_result()
    if not isinstance(final_event, api.Closed):
        raise RuntimeError("server sent more than three Results")


async def run_client(port: int) -> None:
    await run_client_flow(port, run_client_session)


if __name__ == "__main__":
    raise SystemExit(run_peer(sys.argv[1:], run_server, run_client))
