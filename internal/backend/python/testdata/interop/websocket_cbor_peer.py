"""Cross-language WebSocket peer for the CBOR binding."""

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
    REJECT_DUPLICATE_KEYS = "reject-duplicate-keys"
    REJECT_TEXT_FRAME = "reject-text-frame"
    REJECT_MALFORMED_CBOR = "reject-malformed-cbor"


async def serve_session(websocket: Connection) -> None:
    session = api.ServerReady(api.WebSocketCBORTransport(websocket))
    query = await session.recv_query()
    if isinstance(query, api.Closed):
        raise RuntimeError("server received Close before Query")
    if query.message.id != "q1" or query.message.sequence != "ACGT":
        raise RuntimeError("server received an unexpected Query")
    if query.message.top_k != 5:
        raise RuntimeError("server received an unexpected topK value")
    result = api.Result.model_validate({"id": "q1", "result": "matched"})
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
    print(f"READY {sockets[0].getsockname()[1]}", flush=True)
    async with server:
        await asyncio.wait_for(completed.wait(), timeout=PROCESS_TIMEOUT_SECONDS)
    if failures:
        raise RuntimeError("; ".join(failures))
    print("SERVER_OK", flush=True)


async def run_client(port: int) -> None:
    async with connect(f"ws://{LOOPBACK}:{port}") as websocket:
        session = api.ClientReady(api.WebSocketCBORTransport(websocket))
        query = api.Query.model_validate(
            {"id": "q1", "sequence": "ACGT", "topK": 5}
        )
        waiting = await session.send_query(query)
        result = await waiting.recv_result()
        if isinstance(result, api.Closed):
            raise RuntimeError("client received Close before Result")
        if result.message.id != "q1" or result.message.result != "matched":
            raise RuntimeError("client received an unexpected Result")
        await result.session.close()
    print("CLIENT_OK", flush=True)


async def run_abnormal_server(port: int) -> None:
    completed = asyncio.Event()
    failures: list[str] = []

    async def handle_connection(websocket: Connection) -> None:
        try:
            message = await websocket.recv()
            if not isinstance(message, bytes):
                raise RuntimeError("expected a binary Query frame")
            await websocket.close(code=1011, reason="test abnormal close")
        except Exception as error:
            failures.append(str(error))
        finally:
            completed.set()

    server = await serve(handle_connection, LOOPBACK, port)
    sockets = server.sockets
    if sockets is None or not sockets:
        raise RuntimeError("WebSocket server did not bind a socket")
    print(f"READY {sockets[0].getsockname()[1]}", flush=True)
    async with server:
        await asyncio.wait_for(completed.wait(), timeout=PROCESS_TIMEOUT_SECONDS)
    if failures:
        raise RuntimeError("; ".join(failures))
    print("ABNORMAL_SERVER_OK", flush=True)


async def run_abnormal_client(port: int) -> None:
    async with connect(f"ws://{LOOPBACK}:{port}") as websocket:
        session = api.ClientReady(api.WebSocketCBORTransport(websocket))
        query = api.Query.model_validate(
            {"id": "q1", "sequence": "ACGT", "topK": 5}
        )
        waiting = await session.send_query(query)
        try:
            await waiting.recv_result()
        except api.TransportFailure:
            print("ABNORMAL_CLOSE_REJECTED", flush=True)
            return
        raise RuntimeError("abnormal WebSocket Close was accepted as protocol Close")


async def run_invalid_frame_server(port: int) -> None:
    completed = asyncio.Event()
    failures: list[str] = []

    async def handle_connection(websocket: Connection) -> None:
        try:
            session = api.ServerReady(api.WebSocketCBORTransport(websocket))
            await session.recv_query()
        except api.TransportFailure:
            print("INVALID_FRAME_REJECTED", flush=True)
        except Exception as error:
            failures.append(str(error))
        else:
            failures.append("invalid frame was accepted")
        finally:
            completed.set()

    server = await serve(handle_connection, LOOPBACK, port)
    sockets = server.sockets
    if sockets is None or not sockets:
        raise RuntimeError("WebSocket server did not bind a socket")
    print(f"READY {sockets[0].getsockname()[1]}", flush=True)
    async with server:
        await asyncio.wait_for(completed.wait(), timeout=PROCESS_TIMEOUT_SECONDS)
    if failures:
        raise RuntimeError("; ".join(failures))


async def run_peer(role: PeerRole, port: int) -> None:
    handlers: dict[PeerRole, Callable[[int], Awaitable[None]]] = {
        PeerRole.SERVER: run_server,
        PeerRole.CLIENT: run_client,
        PeerRole.ABNORMAL_SERVER: run_abnormal_server,
        PeerRole.ABNORMAL_CLIENT: run_abnormal_client,
        PeerRole.REJECT_DUPLICATE_KEYS: run_invalid_frame_server,
        PeerRole.REJECT_TEXT_FRAME: run_invalid_frame_server,
        PeerRole.REJECT_MALFORMED_CBOR: run_invalid_frame_server,
    }
    await handlers[role](port)


if __name__ == "__main__":
    asyncio.run(run_peer(PeerRole(sys.argv[1]), int(sys.argv[2])))
