//! Cross-language WebSocket smoke peer for one Query/Result exchange.

use cueflow_websocket_check::{
    ProtocolError, WebSocketJsonError, WebSocketJsonTransport, client, messages, server,
};
use std::error::Error;
use std::fmt::Debug;
use std::io;
use tokio::net::TcpListener;
use tokio_tungstenite::WebSocketStream;
use tokio_tungstenite::tungstenite::protocol::CloseFrame;
use tokio_tungstenite::tungstenite::protocol::frame::coding::CloseCode;

type PeerError = Box<dyn Error + Send + Sync>;

enum PeerRole {
    Server,
    Client,
    AbnormalServer,
    AbnormalClient,
}

fn protocol_failure(error: impl Debug) -> io::Error {
    io::Error::other(format!("{error:?}"))
}

fn parse_role(value: &str) -> Result<PeerRole, io::Error> {
    match value {
        "server" => Ok(PeerRole::Server),
        "client" => Ok(PeerRole::Client),
        "abnormal-server" => Ok(PeerRole::AbnormalServer),
        "abnormal-client" => Ok(PeerRole::AbnormalClient),
        _ => Err(io::Error::other("role must be server or client")),
    }
}

async fn run_server(port: u16) -> Result<(), PeerError> {
    let listener = TcpListener::bind(("127.0.0.1", port)).await?;
    let address = listener.local_addr()?;
    println!("READY {}", address.port());
    let (stream, _) = listener.accept().await?;
    let websocket = tokio_tungstenite::accept_async(stream).await?;
    serve_session(websocket).await
}

async fn serve_session<S>(websocket: WebSocketStream<S>) -> Result<(), PeerError>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send,
{
    let transport = WebSocketJsonTransport::new(websocket);
    let session = server::ServerSession::<_, server::Ready>::new(transport);
    let query = session.recv_query().await.map_err(protocol_failure)?;
    let cueflow_websocket_check::ReceiveOutcome::Message { message, session } = query else {
        return Err("server received Close before Query".into());
    };
    if message.id != "q1"
        || message.filter.sequence != "ACGT"
        || message.filter.range.top_k != 5
        || !message.filter.range.active
        || message
            .details
            .as_ref()
            .map(|details| details.label.as_str())
            != Some("nested")
    {
        return Err("server received an unexpected Query".into());
    }
    let waiting = session
        .send_result(messages::Result {
            id: message.id,
            payload: messages::ResultPayload {
                summary: "matched".to_owned(),
                matches: 3,
            },
        })
        .await
        .map_err(protocol_failure)?;
    waiting.recv_close().await.map_err(protocol_failure)?;
    println!("SERVER_OK");
    Ok(())
}

async fn run_client(port: u16) -> Result<(), PeerError> {
    let url = format!("ws://127.0.0.1:{port}");
    let (websocket, _) = tokio_tungstenite::connect_async(url).await?;
    let transport = WebSocketJsonTransport::new(websocket);
    let session = client::ClientSession::<_, client::Ready>::new(transport);
    let waiting = session
        .send_query(messages::Query {
            id: "q1".to_owned(),
            filter: messages::QueryFilter {
                sequence: "ACGT".to_owned(),
                range: messages::QueryFilterRange {
                    top_k: 5,
                    active: true,
                },
                note: None,
            },
            details: Some(messages::QueryDetails {
                label: "nested".to_owned(),
            }),
        })
        .await
        .map_err(protocol_failure)?;
    let result = waiting.recv_result().await.map_err(protocol_failure)?;
    let cueflow_websocket_check::ReceiveOutcome::Message { message, session } = result else {
        return Err("client received Close before Result".into());
    };
    if message.id != "q1" || message.payload.summary != "matched" || message.payload.matches != 3 {
        return Err("client received an unexpected Result".into());
    }
    session.close().await.map_err(protocol_failure)?;
    println!("CLIENT_OK");
    Ok(())
}

async fn run_abnormal_server(port: u16) -> Result<(), PeerError> {
    use futures_util::StreamExt;
    use tokio_tungstenite::tungstenite::Error as WebSocketError;
    use tokio_tungstenite::tungstenite::Message;

    let listener = TcpListener::bind(("127.0.0.1", port)).await?;
    let address = listener.local_addr()?;
    println!("READY {}", address.port());
    let (stream, _) = listener.accept().await?;
    let mut websocket = tokio_tungstenite::accept_async(stream).await?;
    match websocket.next().await {
        Some(Ok(Message::Text(_))) => {}
        Some(Ok(_)) => return Err("expected a Query text frame".into()),
        Some(Err(error)) => return Err(error.into()),
        None => return Err("client closed before sending Query".into()),
    }
    let close = CloseFrame {
        code: CloseCode::Error,
        reason: "test abnormal close".into(),
    };
    websocket.close(Some(close)).await?;
    while let Some(event) = websocket.next().await {
        match event {
            Ok(Message::Close(_)) => {}
            Ok(_) => return Err("received data after sending Close".into()),
            Err(WebSocketError::ConnectionClosed | WebSocketError::AlreadyClosed) => break,
            Err(error) => return Err(error.into()),
        }
    }
    println!("ABNORMAL_SERVER_OK");
    Ok(())
}

async fn run_abnormal_client(port: u16) -> Result<(), PeerError> {
    let url = format!("ws://127.0.0.1:{port}");
    let (websocket, _) = tokio_tungstenite::connect_async(url).await?;
    let transport = WebSocketJsonTransport::new(websocket);
    let session = client::ClientSession::<_, client::Ready>::new(transport);
    let waiting = session
        .send_query(messages::Query {
            id: "q1".to_owned(),
            filter: messages::QueryFilter {
                sequence: "ACGT".to_owned(),
                range: messages::QueryFilterRange {
                    top_k: 5,
                    active: true,
                },
                note: None,
            },
            details: Some(messages::QueryDetails {
                label: "nested".to_owned(),
            }),
        })
        .await
        .map_err(protocol_failure)?;
    match waiting.recv_result().await {
        Err(ProtocolError::Transport(WebSocketJsonError::AbnormalClose { code: Some(1011) })) => {
            println!("ABNORMAL_CLOSE_REJECTED");
            Ok(())
        }
        Err(error) => Err(protocol_failure(error).into()),
        Ok(_) => Err("abnormal WebSocket Close was accepted as protocol Close".into()),
    }
}

#[tokio::main]
async fn main() -> Result<(), PeerError> {
    let arguments = std::env::args().skip(1).collect::<Vec<String>>();
    if arguments.len() != 2 {
        return Err("usage: websocket_peer server|client <port>".into());
    }
    let role = parse_role(&arguments[0])?;
    let port = arguments[1].parse::<u16>()?;
    match role {
        PeerRole::Server => run_server(port).await?,
        PeerRole::Client => run_client(port).await?,
        PeerRole::AbnormalServer => run_abnormal_server(port).await?,
        PeerRole::AbnormalClient => run_abnormal_client(port).await?,
    }
    Ok(())
}
