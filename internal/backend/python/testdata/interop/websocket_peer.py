"""Cross-language WebSocket smoke peer for one Query/Result exchange."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from enum import Enum

from websockets.asyncio.client import connect
from websockets.asyncio.connection import Connection
from websockets.asyncio.server import serve

import generated as api


LOOPBACK = "127.0.0.1"
PROCESS_TIMEOUT_SECONDS = 30


class PeerRole(Enum):
    SERVER = "server"
    CLIENT = "client"
    ABNORMAL_SERVER = "abnormal-server"
    ABNORMAL_CLIENT = "abnormal-client"


async def serve_session(websocket: Connection) -> None:
    session = api.ServerReady(api.WebSocketJSONTransport(websocket))
    query = await session.recv_query()
    if isinstance(query, api.Closed):
        raise RuntimeError("server received Close before Query")
    if (
        query.message.id != "q1"
        or query.message.filter.sequence != "ACGT"
        or query.message.filter.range.top_k != 5
        or not query.message.filter.range.active
        or query.message.details is None
        or query.message.details.label != "nested"
    ):
        raise RuntimeError("server received an unexpected Query")
    result = api.Result.model_validate(
        {"id": "q1", "payload": {"summary": "matched", "matches": 3}}
    )
    waiting = await query.session.send_result(result)
    await waiting.recv_close()


async def run_server(port: int) -> None:
    completed = asyncio.Event()
    failures: list[str] = []

    async def handle_connection(websocket: Connection) -> None:
        try:
            await serve_session(websocket)
        except Exception as error:
            failures.append(str(error))
        finally:
            completed.set()

    server = await serve(handle_connection, LOOPBACK, port)
    sockets = server.sockets
    if sockets is None or not sockets:
        raise RuntimeError("WebSocket server did not bind a socket")
    bound_port = int(sockets[0].getsockname()[1])
    print(f"READY {bound_port}", flush=True)
    async with server:
        await asyncio.wait_for(completed.wait(), timeout=PROCESS_TIMEOUT_SECONDS)
    if failures:
        raise RuntimeError("; ".join(failures))
    print("SERVER_OK", flush=True)


async def run_client(port: int) -> None:
    url = f"ws://{LOOPBACK}:{port}"
    async with connect(url) as websocket:
        session = api.ClientReady(api.WebSocketJSONTransport(websocket))
        query = api.Query.model_validate(
            {
                "id": "q1",
                "filter": {
                    "sequence": "ACGT",
                    "range": {"topK": 5, "active": True},
                },
                "details": {"label": "nested"},
            }
        )
        waiting = await session.send_query(query)
        result = await waiting.recv_result()
        if isinstance(result, api.Closed):
            raise RuntimeError("client received Close before Result")
        if (
            result.message.id != "q1"
            or result.message.payload.summary != "matched"
            or result.message.payload.matches != 3
        ):
            raise RuntimeError("client received an unexpected Result")
        await result.session.close()
    print("CLIENT_OK", flush=True)


async def run_abnormal_server(port: int) -> None:
    completed = asyncio.Event()

    async def handle_connection(websocket: Connection) -> None:
        await websocket.recv()
        await websocket.close(code=1011, reason="test abnormal close")
        completed.set()

    server = await serve(handle_connection, LOOPBACK, port)
    sockets = server.sockets
    if sockets is None or not sockets:
        raise RuntimeError("WebSocket server did not bind a socket")
    bound_port = int(sockets[0].getsockname()[1])
    print(f"READY {bound_port}", flush=True)
    async with server:
        await asyncio.wait_for(completed.wait(), timeout=PROCESS_TIMEOUT_SECONDS)
    print("ABNORMAL_SERVER_OK", flush=True)


async def run_abnormal_client(port: int) -> None:
    url = f"ws://{LOOPBACK}:{port}"
    async with connect(url) as websocket:
        session = api.ClientReady(api.WebSocketJSONTransport(websocket))
        query = api.Query.model_validate(
            {
                "id": "q1",
                "filter": {
                    "sequence": "ACGT",
                    "range": {"topK": 5, "active": True},
                },
                "details": {"label": "nested"},
            }
        )
        waiting = await session.send_query(query)
        try:
            await waiting.recv_result()
        except api.TransportFailure:
            print("ABNORMAL_CLOSE_REJECTED", flush=True)
            return
        raise RuntimeError("abnormal WebSocket Close was accepted as protocol Close")


async def run_peer(
    arguments: list[str],
    server: Callable[[int], Awaitable[None]],
    client: Callable[[int], Awaitable[None]],
) -> None:
    if len(arguments) != 2:
        raise RuntimeError("usage: websocket_peer.py server|client <port>")
    try:
        role = PeerRole(arguments[0])
    except ValueError as error:
        raise RuntimeError("usage: websocket_peer.py server|client <port>") from error
    port = int(arguments[1])
    if role is PeerRole.SERVER:
        await server(port)
        return
    if role is PeerRole.CLIENT:
        await client(port)
        return
    if role is PeerRole.ABNORMAL_SERVER:
        await run_abnormal_server(port)
        return
    await run_abnormal_client(port)


def main(arguments: list[str]) -> int:
    try:
        asyncio.run(run_peer(arguments, run_server, run_client))
    except Exception as error:
        print(f"websocket peer failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
