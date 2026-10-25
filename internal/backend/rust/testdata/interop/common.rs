//! Shared JSON Lines TCP transport and process entry points for cardinality peers.

use cueflow_generated_check::{Inbound, ReceiveOutcome, Transport};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::future::Future;
use std::io::{BufRead, BufReader, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::pin::pin;
use std::task::{Context, Poll, Waker};

const LOOPBACK: IpAddr = IpAddr::V4(Ipv4Addr::LOCALHOST);

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum WireFrame {
    Message { message_id: String, payload: Value },
    Close,
}

pub struct TcpTransport {
    reader: BufReader<TcpStream>,
    writer: TcpStream,
}

pub struct ReceivedMessage<M, S> {
    pub message: M,
    pub session: S,
}

impl TcpTransport {
    pub fn new(stream: TcpStream) -> Result<Self, String> {
        let reader = stream.try_clone().map_err(|error| error.to_string())?;
        Ok(Self {
            reader: BufReader::new(reader),
            writer: stream,
        })
    }

    pub fn connect(port: u16) -> Result<Self, String> {
        let address = SocketAddr::new(LOOPBACK, port);
        let stream = TcpStream::connect(address).map_err(|error| error.to_string())?;
        Self::new(stream)
    }

    fn send_frame(&mut self, frame: &WireFrame) -> Result<(), String> {
        let line = serde_json::to_string(frame).map_err(|error| error.to_string())?;
        writeln!(self.writer, "{line}").map_err(|error| error.to_string())?;
        self.writer.flush().map_err(|error| error.to_string())
    }

    fn receive_frame(&mut self) -> Result<WireFrame, String> {
        let mut line = String::new();
        let bytes_read = self
            .reader
            .read_line(&mut line)
            .map_err(|error| error.to_string())?;
        if bytes_read == 0 {
            return Err("peer closed the transport before sending a frame".to_owned());
        }
        serde_json::from_str(&line).map_err(|error| error.to_string())
    }
}

impl Transport for TcpTransport {
    type Error = String;

    async fn send<M: Serialize + Sync>(
        &mut self,
        message_id: &'static str,
        message: &M,
    ) -> Result<(), Self::Error> {
        let payload = serde_json::to_value(message).map_err(|error| error.to_string())?;
        self.send_frame(&WireFrame::Message {
            message_id: message_id.to_owned(),
            payload,
        })
    }

    async fn recv<M: serde::de::DeserializeOwned + Send>(
        &mut self,
        expected_message_id: &'static str,
    ) -> Result<Inbound<M>, Self::Error> {
        match self.receive_frame()? {
            WireFrame::Close => Ok(Inbound::Close),
            WireFrame::Message {
                message_id,
                payload,
            } => {
                if message_id != expected_message_id {
                    return Err(format!(
                        "expected message {expected_message_id}, received {message_id}"
                    ));
                }
                let message = serde_json::from_value(payload).map_err(|error| error.to_string())?;
                Ok(Inbound::Message(message))
            }
        }
    }

    async fn send_close(&mut self) -> Result<(), Self::Error> {
        self.send_frame(&WireFrame::Close)
    }

    async fn recv_close(&mut self) -> Result<(), Self::Error> {
        match self.receive_frame()? {
            WireFrame::Close => Ok(()),
            WireFrame::Message { message_id, .. } => {
                Err(format!("expected Close, received message {message_id}"))
            }
        }
    }
}

pub fn block_on<F: Future>(future: F) -> F::Output {
    let mut future = pin!(future);
    let mut context = Context::from_waker(Waker::noop());
    loop {
        if let Poll::Ready(output) = future.as_mut().poll(&mut context) {
            return output;
        }
    }
}

pub fn expect_message<M, S>(
    outcome: ReceiveOutcome<M, S>,
    description: &str,
) -> Result<ReceivedMessage<M, S>, String> {
    match outcome {
        ReceiveOutcome::Message { message, session } => Ok(ReceivedMessage { message, session }),
        ReceiveOutcome::Closed => Err(format!("received Close while expecting {description}")),
    }
}

pub fn serve_once(
    requested_port: u16,
    handler: fn(TcpStream) -> Result<(), String>,
) -> Result<(), String> {
    let address = SocketAddr::new(LOOPBACK, requested_port);
    let listener = TcpListener::bind(address).map_err(|error| error.to_string())?;
    let bound_port = listener
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();
    println!("READY {bound_port}");
    std::io::stdout()
        .flush()
        .map_err(|error| error.to_string())?;
    let incoming = listener
        .incoming()
        .next()
        .ok_or_else(|| "listener closed before accepting a client".to_owned())?;
    handler(incoming.map_err(|error| error.to_string())?)?;
    println!("SERVER_OK");
    Ok(())
}

pub fn run_peer(
    arguments: &[String],
    server: fn(u16) -> Result<(), String>,
    client: fn(u16) -> Result<(), String>,
) -> Result<(), String> {
    match arguments.first().map(String::as_str) {
        Some("server") if arguments.len() == 2 => server(parse_port(&arguments[1])?),
        Some("client") if arguments.len() == 2 => {
            client(parse_port(&arguments[1])?)?;
            println!("CLIENT_OK");
            Ok(())
        }
        _ => Err("usage: interop-peer server|client <port>".to_owned()),
    }
}

fn parse_port(value: &str) -> Result<u16, String> {
    value
        .parse::<u16>()
        .map_err(|error| format!("invalid port {value:?}: {error}"))
}
