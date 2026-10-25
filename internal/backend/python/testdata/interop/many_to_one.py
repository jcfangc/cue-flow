"""Python peer for the N:1 case: three Queries produce one aggregate Result."""

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
    response = api.Result.model_validate(
        {"id": "aggregate", "result": f"received {QUERY_COUNT} queries"}
    )
    ready = await finish.session.send_result(response)
    await ready.recv_close()


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
    waiting = await awaiting.send_finish(api.Finish.model_validate({"id": "batch"}))
    result = await waiting.recv_result()
    if isinstance(result, api.Closed):
        raise RuntimeError("received Close while expecting aggregate Result")
    if result.message.id != "aggregate" or result.message.result != "received 3 queries":
        raise RuntimeError(f"unexpected aggregate Result: {result.message!r}")
    await result.session.close()


async def run_client(port: int) -> None:
    await run_client_flow(port, run_client_session)


if __name__ == "__main__":
    raise SystemExit(run_peer(sys.argv[1:], run_server, run_client))
