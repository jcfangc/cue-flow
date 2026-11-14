//! Cross-language WebSocket peer for the CBOR binding.

use cueflow_websocket_check::{
    ProtocolError, WebSocketCborError, WebSocketCborTransport, client, messages, server,
};
use futures_util::{SinkExt, StreamExt};
use std::error::Error;
use std::fmt::Debug;
use std::io;
use tokio::net::TcpListener;
use tokio_tungstenite::WebSocketStream;
use tokio_tungstenite::tungstenite::protocol::CloseFrame;
use tokio_tungstenite::tungstenite::protocol::frame::coding::CloseCode;
use tokio_tungstenite::tungstenite::{Error as WebSocketError, Message};

type PeerError = Box<dyn Error + Send + Sync>;

enum PeerRole {
    Server,
    Client,
    AbnormalServer,
    AbnormalClient,
    RejectDuplicateKeys,
    RejectTextFrame,
    RejectMalformedCbor,
}

#[derive(PartialEq, Eq)]
enum InvalidFrame {
    DuplicateKeys,
    Text,
    MalformedCbor,
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
        "reject-duplicate-keys" => Ok(PeerRole::RejectDuplicateKeys),
        "reject-text-frame" => Ok(PeerRole::RejectTextFrame),
        "reject-malformed-cbor" => Ok(PeerRole::RejectMalformedCbor),
        _ => Err(io::Error::other("role must be server or client")),
    }
}

async fn accept_connection(port: u16) -> Result<WebSocketStream<tokio::net::TcpStream>, PeerError> {
    let listener = TcpListener::bind(("127.0.0.1", port)).await?;
    println!("READY {}", listener.local_addr()?.port());
    let (stream, _) = listener.accept().await?;
    Ok(tokio_tungstenite::accept_async(stream).await?)
}

async fn run_server(port: u16) -> Result<(), PeerError> {
    serve_session(accept_connection(port).await?).await
}

async fn run_invalid_frame_server(port: u16, invalid_frame: InvalidFrame) -> Result<(), PeerError> {
    let transport = WebSocketCborTransport::new(accept_connection(port).await?);
    let session = server::ServerSession::<_, server::Ready>::new(transport);
    match session.recv_query().await {
        Err(ProtocolError::Transport(WebSocketCborError::TextFrameUnsupported))
            if invalid_frame == InvalidFrame::Text => {}
        Err(ProtocolError::Transport(WebSocketCborError::CborDeserialize(_)))
            if invalid_frame != InvalidFrame::Text => {}
        Err(error) => return Err(protocol_failure(error).into()),
        Ok(_) => return Err("invalid frame was accepted".into()),
    }
    println!("INVALID_FRAME_REJECTED");
    Ok(())
}

async fn serve_session<S>(websocket: WebSocketStream<S>) -> Result<(), PeerError>
where
    S: tokio::io::AsyncRead + tokio::io::AsyncWrite + Unpin + Send,
{
    let transport = WebSocketCborTransport::new(websocket);
    let session = server::ServerSession::<_, server::Ready>::new(transport);
    let query = session.recv_query().await.map_err(protocol_failure)?;
    let cueflow_websocket_check::ReceiveOutcome::Message { message, session } = query else {
        return Err("server received Close before Query".into());
    };
    if message.id != "q1" || message.sequence != "ACGT" || message.top_k != 5 {
        return Err("server received an unexpected Query".into());
    }
    let waiting = session
        .send_result(messages::Result {
            id: message.id,
            result: "matched".to_owned(),
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
    let transport = WebSocketCborTransport::new(websocket);
    let session = client::ClientSession::<_, client::Ready>::new(transport);
    let waiting = session
        .send_query(messages::Query {
            id: "q1".to_owned(),
            sequence: "ACGT".to_owned(),
            top_k: 5,
            note: None,
            cue_gen: None,
        })
        .await
        .map_err(protocol_failure)?;
    let result = waiting.recv_result().await.map_err(protocol_failure)?;
    let cueflow_websocket_check::ReceiveOutcome::Message { message, session } = result else {
        return Err("client received Close before Result".into());
    };
    if message.id != "q1" || message.result != "matched" {
        return Err("client received an unexpected Result".into());
    }
    session.close().await.map_err(protocol_failure)?;
    println!("CLIENT_OK");
    Ok(())
}

async fn run_abnormal_server(port: u16) -> Result<(), PeerError> {
    let mut websocket = accept_connection(port).await?;
    match websocket.next().await {
        Some(Ok(Message::Binary(_))) => {}
        Some(Ok(_)) => return Err("expected a binary Query frame".into()),
        Some(Err(error)) => return Err(error.into()),
        None => return Err("client closed before sending Query".into()),
    }
    let close = CloseFrame {
        code: CloseCode::Error,
        reason: "test abnormal close".into(),
    };
    websocket.send(Message::Close(Some(close))).await?;
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
    let transport = WebSocketCborTransport::new(websocket);
    let session = client::ClientSession::<_, client::Ready>::new(transport);
    let waiting = session
        .send_query(messages::Query {
            id: "q1".to_owned(),
            sequence: "ACGT".to_owned(),
            top_k: 5,
            note: None,
            cue_gen: None,
        })
        .await
        .map_err(protocol_failure)?;
    match waiting.recv_result().await {
        Err(ProtocolError::Transport(WebSocketCborError::AbnormalClose { code: Some(1011) })) => {
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
        return Err("usage: websocket_cbor_peer role <port>".into());
    }
    let role = parse_role(&arguments[0])?;
    let port = arguments[1].parse::<u16>()?;
    match role {
        PeerRole::Server => run_server(port).await,
        PeerRole::Client => run_client(port).await,
        PeerRole::AbnormalServer => run_abnormal_server(port).await,
        PeerRole::AbnormalClient => run_abnormal_client(port).await,
        PeerRole::RejectDuplicateKeys => {
            run_invalid_frame_server(port, InvalidFrame::DuplicateKeys).await
        }
        PeerRole::RejectTextFrame => run_invalid_frame_server(port, InvalidFrame::Text).await,
        PeerRole::RejectMalformedCbor => {
            run_invalid_frame_server(port, InvalidFrame::MalformedCbor).await
        }
    }
}
