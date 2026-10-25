"""Python peer for the N:N case: three correlated Queries receive three Results."""

from __future__ import annotations

import sys

import generated as api
from common import StreamConnection, TcpTransport, listen_once, main as run_peer, run_client_flow


QUERY_COUNT = 3


async def serve_connection(connection: StreamConnection) -> None:
    transport = TcpTransport(connection)
    first = await api.ServerReady(transport).recv_query()
    if isinstance(first, api.Closed):
        raise RuntimeError("received Close before first Query")
    validate_query_id(first.message.id, 0)
    second = await first.session.recv_query()
    if isinstance(second, api.Closed):
        raise RuntimeError("received Close before second Query")
    validate_query_id(second.message.id, 1)
    third = await second.session.recv_query()
    if isinstance(third, api.Closed):
        raise RuntimeError("received Close before third Query")
    validate_query_id(third.message.id, 2)
    finish = await third.session.recv_finish()
    if isinstance(finish, api.Closed):
        raise RuntimeError("received Close before Finish")
    if finish.message.id != "batch":
        raise RuntimeError(f"unexpected Finish ID: {finish.message.id}")
    query_ids = [first.message.id, second.message.id, third.message.id]
    streaming = finish.session
    for query_id in query_ids:
        result = api.Result.model_validate(
            {"id": query_id, "result": f"matched:{query_id}"}
        )
        streaming = await streaming.send_result(result)
    await streaming.close()


def validate_query_id(actual: str, index: int) -> None:
    expected = f"query-{index}"
    if actual != expected:
        raise RuntimeError(f"expected Query ID {expected}, received {actual}")


async def run_server(port: int) -> None:
    await listen_once(port, serve_connection)


async def run_client_session(connection: StreamConnection) -> None:
    session = api.ClientReady(TcpTransport(connection))
    second = await session.send_query(api.Query.model_validate({"id": "query-0"}))
    third = await second.send_query(api.Query.model_validate({"id": "query-1"}))
    awaiting = await third.send_query(api.Query.model_validate({"id": "query-2"}))
    streaming = await awaiting.send_finish(api.Finish.model_validate({"id": "batch"}))
    for index in range(QUERY_COUNT):
        result = await streaming.recv_result()
        if isinstance(result, api.Closed):
            raise RuntimeError("received Close before all Results arrived")
        expected_id = f"query-{index}"
        if result.message.id != expected_id or result.message.result != f"matched:{expected_id}":
            raise RuntimeError(f"unexpected correlated Result: {result.message!r}")
        streaming = result.session
    final_event = await streaming.recv_result()
    if not isinstance(final_event, api.Closed):
        raise RuntimeError("server sent more than three Results")


async def run_client(port: int) -> None:
    await run_client_flow(port, run_client_session)


if __name__ == "__main__":
    raise SystemExit(run_peer(sys.argv[1:], run_server, run_client))
