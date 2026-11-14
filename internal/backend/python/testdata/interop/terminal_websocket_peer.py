"""Cross-language peer for a protocol that enters its terminal state."""

from __future__ import annotations

import asyncio
import sys

from websockets.asyncio.client import connect
from websockets.asyncio.connection import Connection
from websockets.asyncio.server import serve

import generated_terminal as api


LOOPBACK = "127.0.0.1"


async def serve_session(websocket: Connection) -> None:
    session = api.ServerReady(api.WebSocketJSONTransport(websocket))
    terminal = await session.send_finished(api.Finished(status="done"))
    await terminal.recv_close()


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
        await asyncio.wait_for(completed.wait(), timeout=30)
    if failures:
        raise RuntimeError("; ".join(failures))
    print("TERMINAL_SERVER_OK", flush=True)


async def run_client(port: int) -> None:
    async with connect(f"ws://{LOOPBACK}:{port}") as websocket:
        session = api.ClientReady(api.WebSocketJSONTransport(websocket))
        outcome = await session.recv_finished()
        if isinstance(outcome, api.Closed):
            raise RuntimeError("client received Close before Finished")
        if outcome.message.status != "done":
            raise RuntimeError("client received an unexpected Finished")
        await outcome.session.close()
    print("TERMINAL_CLIENT_OK", flush=True)


async def main() -> None:
    role = sys.argv[1]
    port = int(sys.argv[2])
    if role == "server":
        await run_server(port)
        return
    if role == "client":
        await run_client(port)
        return
    raise RuntimeError("role must be server or client")


if __name__ == "__main__":
    asyncio.run(main())
