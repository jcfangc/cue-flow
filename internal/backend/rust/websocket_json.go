// 文件职责：生成基于 Tokio 的 WebSocket + JSON Transport 实现。
// 每个 CueFlow Session 独占一条连接，Close 映射为 WebSocket Close。
package rust

import "bytes"

func writeWebSocketJSONTransport(output *bytes.Buffer) {
	output.WriteString(`
#[derive(Debug)]
pub enum WebSocketJsonError {
    WebSocket(tokio_tungstenite::tungstenite::Error),
    Json(serde_json::Error),
    ConnectionEnded,
    BinaryFrameUnsupported,
    MessageBeforeClose,
    AbnormalClose { code: Option<u16> },
    CloseHandshakeTimedOut,
}

const CLOSE_HANDSHAKE_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(10);

/// Tokio adapter for a WebSocket carrying direct CUE message JSON values.
/// This binding uses one WebSocket connection for one CueFlow session.
pub struct WebSocketJsonTransport<S> {
    socket: tokio_tungstenite::WebSocketStream<S>,
}

impl<S> WebSocketJsonTransport<S> {
    pub fn new(socket: tokio_tungstenite::WebSocketStream<S>) -> Self {
        Self { socket }
    }
}

impl<S> WebSocketJsonTransport<S>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send,
{
    async fn receive_text(&mut self) -> Result<Option<String>, WebSocketJsonError> {
        use futures_util::StreamExt;
        use tokio_tungstenite::tungstenite::Message;

        loop {
            let event = self.socket.next().await.ok_or(WebSocketJsonError::ConnectionEnded)?
                .map_err(WebSocketJsonError::WebSocket)?;
            match event {
                Message::Text(text) => return Ok(Some(text.to_string())),
                Message::Ping(_) | Message::Pong(_) => {}
                Message::Binary(_) => return Err(WebSocketJsonError::BinaryFrameUnsupported),
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
    ) -> Result<(), WebSocketJsonError> {
        tokio::time::timeout(CLOSE_HANDSHAKE_TIMEOUT, self.finish_close_inner(frame))
            .await
            .map_err(|_| WebSocketJsonError::CloseHandshakeTimedOut)?
    }

    async fn finish_close_inner(
        &mut self,
        frame: Option<tokio_tungstenite::tungstenite::protocol::CloseFrame>,
    ) -> Result<(), WebSocketJsonError> {
        use futures_util::StreamExt;
        use tokio_tungstenite::tungstenite::Error as TungsteniteError;
        use tokio_tungstenite::tungstenite::Message;

        let code = frame.as_ref().map(|close| u16::from(close.code));
        while let Some(event) = self.socket.next().await {
            match event {
                Ok(Message::Close(_)) => {}
                Ok(Message::Ping(_) | Message::Pong(_)) => {}
                Ok(_) => return Err(WebSocketJsonError::MessageBeforeClose),
                Err(TungsteniteError::ConnectionClosed | TungsteniteError::AlreadyClosed) => break,
                Err(error) => return Err(WebSocketJsonError::WebSocket(error)),
            }
        }
        if matches!(code, None | Some(1000 | 1001)) {
            return Ok(());
        }
        Err(WebSocketJsonError::AbnormalClose { code })
    }

    async fn wait_for_close_reply_inner(&mut self) -> Result<(), WebSocketJsonError> {
        use futures_util::StreamExt;
        use tokio_tungstenite::tungstenite::Message;

        loop {
            let event = self.socket.next().await.ok_or(WebSocketJsonError::ConnectionEnded)?
                .map_err(WebSocketJsonError::WebSocket)?;
            match event {
                Message::Close(frame) => return self.finish_close_inner(frame).await,
                Message::Ping(_) | Message::Pong(_) => {}
                _ => return Err(WebSocketJsonError::MessageBeforeClose),
            }
        }
    }

    async fn send_text(&mut self, text: String) -> Result<(), WebSocketJsonError> {
        use futures_util::SinkExt;
        use tokio_tungstenite::tungstenite::Message;

        self.socket.send(Message::Text(text.into())).await
            .map_err(WebSocketJsonError::WebSocket)
    }
}

#[allow(async_fn_in_trait)]
impl<S> Transport for WebSocketJsonTransport<S>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send,
{
    type Error = WebSocketJsonError;

    async fn send<M: serde::Serialize + Sync>(
        &mut self,
        message_id: &'static str,
        message: &M,
    ) -> Result<(), Self::Error> {
        let _ = message_id;
        let text = serde_json::to_string(message).map_err(WebSocketJsonError::Json)?;
        self.send_text(text).await
    }

    async fn recv<M: serde::de::DeserializeOwned + Send>(
        &mut self,
        message_id: &'static str,
    ) -> Result<Inbound<M>, Self::Error> {
        let _ = message_id;
        let Some(text) = self.receive_text().await? else {
            return Ok(Inbound::Close);
        };
        serde_json::from_str(&text).map(Inbound::Message).map_err(WebSocketJsonError::Json)
    }

    async fn send_close(&mut self) -> Result<(), Self::Error> {
        tokio::time::timeout(CLOSE_HANDSHAKE_TIMEOUT, async {
            self.socket.close(None).await.map_err(WebSocketJsonError::WebSocket)?;
            self.wait_for_close_reply_inner().await
        })
        .await
        .map_err(|_| WebSocketJsonError::CloseHandshakeTimedOut)?
    }

    async fn recv_close(&mut self) -> Result<(), Self::Error> {
        tokio::time::timeout(CLOSE_HANDSHAKE_TIMEOUT, async {
            match self.receive_text().await? {
                None => Ok(()),
                Some(_) => Err(WebSocketJsonError::MessageBeforeClose),
            }
        })
        .await
        .map_err(|_| WebSocketJsonError::CloseHandshakeTimedOut)?
    }
}
`)
}
