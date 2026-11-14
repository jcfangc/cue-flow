// 文件职责：生成 asyncio WebSocket 与 CBOR 二进制帧适配器。
// 线上帧直接承载 CUE 消息对象；WebSocket 正常关闭表示 Session Close。
package python

import "bytes"

func writeWebSocketCBORTransport(output *bytes.Buffer) {
	output.WriteString(`
from websockets.exceptions import ConnectionClosedOK

_CLOSE_HANDSHAKE_TIMEOUT_SECONDS = 10


class WebSocketCBORTransport:
    """asyncio adapter for binary CBOR frames on one CueFlow session."""

    def __init__(self, websocket: Connection) -> None:
        self._websocket = websocket

    async def send(self, message_id: str, message: BaseModel) -> None:
        del message_id
        await self._websocket.send(
            cbor2.dumps(message.model_dump(by_alias=True, exclude_unset=True))
        )

    async def recv(self, message_id: str) -> Inbound:
        try:
            raw = await self._websocket.recv()
        except ConnectionClosedOK:
            return InboundClose()
        payload = self._decode_payload(raw)
        return InboundMessage(message_id, payload)

    async def send_close(self) -> None:
        await asyncio.wait_for(
            self._websocket.close(), timeout=_CLOSE_HANDSHAKE_TIMEOUT_SECONDS
        )
        self._ensure_normal_close(self._websocket.close_code)

    async def recv_close(self) -> None:
        try:
            raw = await asyncio.wait_for(
                self._websocket.recv(), timeout=_CLOSE_HANDSHAKE_TIMEOUT_SECONDS
            )
        except ConnectionClosedOK:
            return
        except TimeoutError as error:
            raise ProtocolError("timed out waiting for WebSocket Close") from error
        self._decode_payload(raw)
        raise ProtocolError(
            "received a business message while waiting for WebSocket Close"
        )

    @staticmethod
    def _decode_payload(raw: str | bytes) -> object:
        if not isinstance(raw, bytes):
            raise ProtocolError("WebSocket CBOR binding requires binary frames")
        return cbor2.loads(raw)

    @staticmethod
    def _ensure_normal_close(code: int | None) -> None:
        if code not in {None, 1000, 1001, 1005}:
            raise ProtocolError("WebSocket closed with abnormal code " + str(code))
`)
}
