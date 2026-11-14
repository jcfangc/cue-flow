use cueflow_websocket_check::{Transport, WebSocketJsonError, WebSocketJsonTransport};
use futures_util::StreamExt;
use tokio::io::DuplexStream;
use tokio_tungstenite::tungstenite::Message;
use tokio_tungstenite::{WebSocketStream, tungstenite::protocol::Role};

type RawWebSocket = WebSocketStream<DuplexStream>;

struct WebSocketPair {
    client: RawWebSocket,
    server: RawWebSocket,
}

async fn create_websocket_pair() -> WebSocketPair {
    let (client_stream, server_stream) = tokio::io::duplex(1024);
    let client = WebSocketStream::from_raw_socket(client_stream, Role::Client, None).await;
    let server = WebSocketStream::from_raw_socket(server_stream, Role::Server, None).await;
    WebSocketPair { client, server }
}

#[tokio::test(start_paused = true)]
async fn waiting_for_peer_close_times_out() {
    let pair = create_websocket_pair().await;
    let transport = WebSocketJsonTransport::new(pair.client);
    let receive_task = tokio::spawn(async move {
        let mut transport = transport;
        transport.recv_close().await
    });
    tokio::task::yield_now().await;
    tokio::time::advance(std::time::Duration::from_secs(11)).await;
    let result = receive_task.await.expect("receive task should complete");

    assert!(matches!(
        result,
        Err(WebSocketJsonError::CloseHandshakeTimedOut)
    ));
}

#[tokio::test(start_paused = true)]
async fn waiting_for_close_reply_times_out() {
    let pair = create_websocket_pair().await;
    let mut server = pair.server;
    let server_task = tokio::spawn(async move {
        let event = server.next().await;
        assert!(matches!(event, Some(Ok(Message::Close(_)))));
        std::future::pending::<()>().await;
    });

    let mut transport = WebSocketJsonTransport::new(pair.client);
    let result = transport.send_close().await;
    server_task.abort();

    assert!(matches!(
        result,
        Err(WebSocketJsonError::CloseHandshakeTimedOut)
    ));
}
