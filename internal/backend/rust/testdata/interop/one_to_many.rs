//! Rust peer for the 1:N case: one Query receives three Result events.

mod interop_common;

use cueflow_generated_check::{ReceiveOutcome, client, messages, server};
use interop_common::{TcpTransport, block_on, expect_message, run_peer, serve_once};
use std::net::TcpStream;

const RESULT_COUNT: usize = 3;

fn serve_connection(stream: TcpStream) -> Result<(), String> {
    let transport = TcpTransport::new(stream)?;
    let session = server::ServerSession::<TcpTransport, server::Ready>::new(transport);
    let query = expect_message(
        block_on(session.recv_query()).map_err(|error| format!("{error:?}"))?,
        "Query",
    )?;
    let query_id = query.message.id;
    let mut streaming = query.session;
    for index in 1..=RESULT_COUNT {
        streaming = block_on(streaming.send_result(messages::Result {
            id: format!("{query_id}-part-{index}"),
            result: format!("part-{index}"),
        }))
        .map_err(|error| format!("{error:?}"))?;
    }
    block_on(streaming.close()).map_err(|error| format!("{error:?}"))
}

fn run_server(port: u16) -> Result<(), String> {
    serve_once(port, serve_connection)
}

fn run_client(port: u16) -> Result<(), String> {
    let transport = TcpTransport::connect(port)?;
    let session = client::ClientSession::<TcpTransport, client::Ready>::new(transport);
    let mut streaming = block_on(session.send_query(messages::Query {
        id: "query-0".to_owned(),
    }))
    .map_err(|error| format!("{error:?}"))?;
    for index in 1..=RESULT_COUNT {
        let result = expect_message(
            block_on(streaming.recv_result()).map_err(|error| format!("{error:?}"))?,
            "Result",
        )?;
        let expected_id = format!("query-0-part-{index}");
        let expected_result = format!("part-{index}");
        if result.message.id != expected_id || result.message.result != expected_result {
            return Err(format!("unexpected stream Result: {:?}", result.message));
        }
        streaming = result.session;
    }
    match block_on(streaming.recv_result()).map_err(|error| format!("{error:?}"))? {
        ReceiveOutcome::Closed => Ok(()),
        ReceiveOutcome::Message { message, .. } => {
            Err(format!("received extra Result: {message:?}"))
        }
    }
}

fn main() {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if let Err(error) = run_peer(&arguments, run_server, run_client) {
        eprintln!("interop-peer failed: {error}");
        std::process::exit(1);
    }
}
