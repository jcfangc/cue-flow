"""Shared JSON Lines TCP transport for generated Python cardinality peers."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Annotated, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter

import generated as api


LOOPBACK = "127.0.0.1"


class MessageFrame(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    kind: Literal["message"]
    message_id: StrictStr
    payload: object


class CloseFrame(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    kind: Literal["close"]


WireFrame = Annotated[MessageFrame | CloseFrame, Field(discriminator="kind")]
FRAME_ADAPTER = TypeAdapter(WireFrame)


@dataclass(frozen=True)
class StreamConnection:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter


ConnectionHandler = Callable[[StreamConnection], Awaitable[None]]
PeerHandler = Callable[[int], Awaitable[None]]


class TcpTransport:
    def __init__(self, connection: StreamConnection) -> None:
        self._reader = connection.reader
        self._writer = connection.writer

    async def send(self, message_id: str, message: BaseModel) -> None:
        payload: object = message.model_dump(mode="json", by_alias=True, exclude_unset=True)
        await self._send_frame(
            MessageFrame(kind="message", message_id=message_id, payload=payload)
        )

    async def recv(self, message_id: str) -> api.Inbound:
        frame = await self._receive_frame()
        if isinstance(frame, CloseFrame):
            return api.InboundClose()
        if frame.message_id != message_id:
            raise RuntimeError(
                f"expected message {message_id}, received {frame.message_id}"
            )
        return api.InboundMessage(frame.message_id, frame.payload)

    async def send_close(self) -> None:
        await self._send_frame(CloseFrame(kind="close"))

    async def recv_close(self) -> None:
        frame = await self._receive_frame()
        if not isinstance(frame, CloseFrame):
            raise RuntimeError(f"expected Close, received message {frame.message_id}")

    async def _send_frame(self, frame: WireFrame) -> None:
        self._writer.write((frame.model_dump_json() + "\n").encode("utf-8"))
        await self._writer.drain()

    async def _receive_frame(self) -> WireFrame:
        line = await self._reader.readline()
        if not line:
            raise ConnectionError("peer closed the transport before sending a frame")
        return FRAME_ADAPTER.validate_json(line)


async def open_connection(port: int) -> StreamConnection:
    # asyncio.open_connection returns its endpoints as a required pair; wrap it
    # in a named result type immediately at the standard-library boundary.
    endpoints = await asyncio.open_connection(LOOPBACK, port)
    return StreamConnection(reader=endpoints[0], writer=endpoints[1])


async def listen_once(port: int, handler: ConnectionHandler) -> None:
    completed = asyncio.Event()
    failures: list[str] = []

    async def handle_connection(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await handler(StreamConnection(reader, writer))
        except Exception as error:
            failures.append(str(error))
        finally:
            writer.close()
            await writer.wait_closed()
            completed.set()

    server = await asyncio.start_server(handle_connection, LOOPBACK, port)
    if not server.sockets:
        raise RuntimeError("server did not bind a socket")
    # The socket API reports its address as a host/port pair; only the port is
    # needed by the test orchestrator.
    bound_port = int(server.sockets[0].getsockname()[1])
    print(f"READY {bound_port}", flush=True)
    async with server:
        await asyncio.wait_for(completed.wait(), timeout=30)
    if failures:
        raise RuntimeError("; ".join(failures))
    print("SERVER_OK", flush=True)


async def run_peer(
    arguments: list[str], server: PeerHandler, client: PeerHandler
) -> None:
    if len(arguments) != 2 or arguments[0] not in {"server", "client"}:
        raise RuntimeError("usage: interop_peer.py server|client <port>")
    port = int(arguments[1])
    if arguments[0] == "server":
        await server(port)
        return
    await client(port)
    print("CLIENT_OK", flush=True)


async def run_client_flow(port: int, flow: ConnectionHandler) -> None:
    connection = await open_connection(port)
    try:
        await flow(connection)
    finally:
        connection.writer.close()
        await connection.writer.wait_closed()


def main(arguments: list[str], server: PeerHandler, client: PeerHandler) -> int:
    try:
        asyncio.run(run_peer(arguments, server, client))
    except Exception as error:
        print(f"interop-peer failed: {error}", file=sys.stderr)
        return 1
    return 0
