//! Rust peer for the 1:1 case: one Query receives exactly one Result.

mod interop_common;

use cueflow_generated_check::{client, messages, server};
use interop_common::{TcpTransport, block_on, expect_message, run_peer, serve_once};
use std::net::TcpStream;

fn serve_connection(stream: TcpStream) -> Result<(), String> {
    let transport = TcpTransport::new(stream)?;
    let session = server::ServerSession::<TcpTransport, server::Ready>::new(transport);
    let query = expect_message(
        block_on(session.recv_query()).map_err(|error| format!("{error:?}"))?,
        "Query",
    )?;
    if query.message.id != "query-0" {
        return Err(format!("unexpected Query ID: {}", query.message.id));
    }
    let ready = block_on(query.session.send_result(messages::Result {
        id: query.message.id,
        result: "matched".to_owned(),
    }))
    .map_err(|error| format!("{error:?}"))?;
    block_on(ready.recv_close()).map_err(|error| format!("{error:?}"))
}

fn run_server(port: u16) -> Result<(), String> {
    serve_once(port, serve_connection)
}

fn run_client(port: u16) -> Result<(), String> {
    let transport = TcpTransport::connect(port)?;
    let session = client::ClientSession::<TcpTransport, client::Ready>::new(transport);
    let waiting = block_on(session.send_query(messages::Query {
        id: "query-0".to_owned(),
    }))
    .map_err(|error| format!("{error:?}"))?;
    let result = expect_message(
        block_on(waiting.recv_result()).map_err(|error| format!("{error:?}"))?,
        "Result",
    )?;
    if result.message.id != "query-0" || result.message.result != "matched" {
        return Err(format!("unexpected Result: {:?}", result.message));
    }
    block_on(result.session.close()).map_err(|error| format!("{error:?}"))
}

fn main() {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if let Err(error) = run_peer(&arguments, run_server, run_client) {
        eprintln!("interop-peer failed: {error}");
        std::process::exit(1);
    }
}
