use cueflow_websocket_check::{client, messages, server, WebSocketJsonTransport};
use std::error::Error;
use std::io;
use tokio::net::TcpListener;
use tokio_tungstenite::WebSocketStream;

type PeerError = Box<dyn Error + Send + Sync>;

fn protocol_failure(error: impl std::fmt::Debug) -> io::Error {
    io::Error::other(format!("{error:?}"))
}

async fn serve(port: u16) -> Result<(), PeerError> {
    let listener = TcpListener::bind(("127.0.0.1", port)).await?;
    println!("READY {}", listener.local_addr()?.port());
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
    let terminal = session
        .send_finished(messages::Finished {
            status: "done".to_owned(),
        })
        .await
        .map_err(protocol_failure)?;
    terminal.recv_close().await.map_err(protocol_failure)?;
    println!("TERMINAL_SERVER_OK");
    Ok(())
}

async fn connect(port: u16) -> Result<(), PeerError> {
    let url = format!("ws://127.0.0.1:{port}");
    let (websocket, _) = tokio_tungstenite::connect_async(url).await?;
    let transport = WebSocketJsonTransport::new(websocket);
    let session = client::ClientSession::<_, client::Ready>::new(transport);
    let outcome = session.recv_finished().await.map_err(protocol_failure)?;
    let cueflow_websocket_check::ReceiveOutcome::Message { message, session } = outcome else {
        return Err("client received Close before Finished".into());
    };
    if message.status != "done" {
        return Err("client received an unexpected Finished".into());
    }
    session.close().await.map_err(protocol_failure)?;
    println!("TERMINAL_CLIENT_OK");
    Ok(())
}

#[tokio::main]
async fn main() -> Result<(), PeerError> {
    let arguments = std::env::args().skip(1).collect::<Vec<String>>();
    if arguments.len() != 2 {
        return Err("usage: terminal_websocket_peer server|client <port>".into());
    }
    let port = arguments[1].parse::<u16>()?;
    match arguments[0].as_str() {
        "server" => serve(port).await,
        "client" => connect(port).await,
        _ => Err("role must be server or client".into()),
    }
}
