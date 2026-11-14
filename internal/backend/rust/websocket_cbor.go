// 文件职责：生成基于 Tokio 的 WebSocket + CBOR Transport 实现。
// 每个 CueFlow Session 独占一条连接，Close 映射为 WebSocket Close。
package rust

import "bytes"

func writeWebSocketCBORTransport(output *bytes.Buffer) {
	output.WriteString(`
#[derive(Debug)]
pub enum WebSocketCborError {
    WebSocket(tokio_tungstenite::tungstenite::Error),
    CborSerialize(String),
    CborDeserialize(String),
    ConnectionEnded,
    TextFrameUnsupported,
    MessageBeforeClose,
    AbnormalClose { code: Option<u16> },
    CloseHandshakeTimedOut,
}

const CLOSE_HANDSHAKE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(10);

/// Tokio adapter for a WebSocket carrying direct CUE message CBOR values.
/// This binding uses one WebSocket connection for one CueFlow session.
pub struct WebSocketCborTransport<S> {
    socket: tokio_tungstenite::WebSocketStream<S>,
}

impl<S> WebSocketCborTransport<S> {
    pub fn new(socket: tokio_tungstenite::WebSocketStream<S>) -> Self {
        Self { socket }
    }
}

impl<S> WebSocketCborTransport<S>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send,
{
    async fn receive_binary(&mut self) -> Result<Option<Vec<u8>>, WebSocketCborError> {
        use futures_util::StreamExt;
        use tokio_tungstenite::tungstenite::Message;

        loop {
            let event = self.socket.next().await.ok_or(WebSocketCborError::ConnectionEnded)?
                .map_err(WebSocketCborError::WebSocket)?;
            match event {
                Message::Binary(bytes) => return Ok(Some(bytes.to_vec())),
                Message::Ping(_) | Message::Pong(_) => {}
                Message::Text(_) => return Err(WebSocketCborError::TextFrameUnsupported),
                Message::Close(frame) => {
                    self.finish_close(frame).await?;
                    return Ok(None);
                }
                _ => {}
            }
        }
    }

    async fn finish_close(
        &mut self,
        frame: Option<tokio_tungstenite::tungstenite::protocol::CloseFrame>,
    ) -> Result<(), WebSocketCborError> {
        tokio::time::timeout(CLOSE_HANDSHAKE_TIMEOUT, self.finish_close_inner(frame))
            .await
            .map_err(|_| WebSocketCborError::CloseHandshakeTimedOut)?
    }

    async fn finish_close_inner(
        &mut self,
        frame: Option<tokio_tungstenite::tungstenite::protocol::CloseFrame>,
    ) -> Result<(), WebSocketCborError> {
        use futures_util::StreamExt;
        use tokio_tungstenite::tungstenite::Error as TungsteniteError;
        use tokio_tungstenite::tungstenite::Message;

        let code = frame.as_ref().map(|close| u16::from(close.code));
        while let Some(event) = self.socket.next().await {
            match event {
                Ok(Message::Close(_)) => {}
                Ok(Message::Ping(_) | Message::Pong(_)) => {}
                Ok(_) => return Err(WebSocketCborError::MessageBeforeClose),
                Err(TungsteniteError::ConnectionClosed | TungsteniteError::AlreadyClosed) => break,
                Err(error) => return Err(WebSocketCborError::WebSocket(error)),
            }
        }
        if matches!(code, None | Some(1000 | 1001)) {
            return Ok(());
        }
        Err(WebSocketCborError::AbnormalClose { code })
    }

    async fn wait_for_close_reply_inner(&mut self) -> Result<(), WebSocketCborError> {
        use futures_util::StreamExt;
        use tokio_tungstenite::tungstenite::Message;

        loop {
            let event = self.socket.next().await.ok_or(WebSocketCborError::ConnectionEnded)?
                .map_err(WebSocketCborError::WebSocket)?;
            match event {
                Message::Close(frame) => return self.finish_close_inner(frame).await,
                Message::Ping(_) | Message::Pong(_) => {}
                _ => return Err(WebSocketCborError::MessageBeforeClose),
            }
        }
    }

    async fn send_binary(&mut self, bytes: Vec<u8>) -> Result<(), WebSocketCborError> {
        use futures_util::SinkExt;
        use tokio_tungstenite::tungstenite::Message;

        self.socket.send(Message::Binary(bytes.into())).await
            .map_err(WebSocketCborError::WebSocket)
    }
}

#[allow(async_fn_in_trait)]
impl<S> Transport for WebSocketCborTransport<S>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send,
{
    type Error = WebSocketCborError;

    async fn send<M: serde::Serialize + Sync>(
        &mut self,
        message_id: &'static str,
        message: &M,
    ) -> Result<(), Self::Error> {
        let _ = message_id;
        let mut bytes = Vec::new();
        ciborium::ser::into_writer(message, &mut bytes)
            .map_err(|error| WebSocketCborError::CborSerialize(error.to_string()))?;
        self.send_binary(bytes).await
    }

    async fn recv<M: serde::de::DeserializeOwned + Send>(
        &mut self,
        message_id: &'static str,
    ) -> Result<Inbound<M>, Self::Error> {
        let _ = message_id;
        let Some(bytes) = self.receive_binary().await? else {
            return Ok(Inbound::Close);
        };
        ciborium::de::from_reader(bytes.as_slice())
            .map(Inbound::Message)
            .map_err(|error| WebSocketCborError::CborDeserialize(error.to_string()))
    }

    async fn send_close(&mut self) -> Result<(), Self::Error> {
        tokio::time::timeout(CLOSE_HANDSHAKE_TIMEOUT, async {
            self.socket.close(None).await.map_err(WebSocketCborError::WebSocket)?;
            self.wait_for_close_reply_inner().await
        })
        .await
        .map_err(|_| WebSocketCborError::CloseHandshakeTimedOut)?
    }

    async fn recv_close(&mut self) -> Result<(), Self::Error> {
        tokio::time::timeout(CLOSE_HANDSHAKE_TIMEOUT, async {
            match self.receive_binary().await? {
                None => Ok(()),
                Some(_) => Err(WebSocketCborError::MessageBeforeClose),
            }
        })
        .await
        .map_err(|_| WebSocketCborError::CloseHandshakeTimedOut)?
    }
}
`)
}
