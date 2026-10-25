//! Rust peer for the N:1 case: three Queries are finalized into one aggregate Result.

mod interop_common;

use cueflow_generated_check::{client, messages, server};
use interop_common::{TcpTransport, block_on, expect_message, run_peer, serve_once};
use std::net::TcpStream;

const QUERY_COUNT: usize = 3;

fn serve_connection(stream: TcpStream) -> Result<(), String> {
    let transport = TcpTransport::new(stream)?;
    let session = server::ServerSession::<TcpTransport, server::Ready>::new(transport);
    let first = expect_message(block_on(session.recv_query()).map_err(as_error)?, "Query")?;
    validate_query_id(&first.message.id, 0)?;
    let second = expect_message(
        block_on(first.session.recv_query()).map_err(as_error)?,
        "Query",
    )?;
    validate_query_id(&second.message.id, 1)?;
    let third = expect_message(
        block_on(second.session.recv_query()).map_err(as_error)?,
        "Query",
    )?;
    validate_query_id(&third.message.id, 2)?;
    let finish = expect_message(
        block_on(third.session.recv_finish()).map_err(as_error)?,
        "Finish",
    )?;
    if finish.message.id != "batch" {
        return Err(format!("unexpected Finish ID: {}", finish.message.id));
    }
    let ready = block_on(finish.session.send_result(messages::Result {
        id: "aggregate".to_owned(),
        result: format!("received {QUERY_COUNT} queries"),
    }))
    .map_err(as_error)?;
    block_on(ready.recv_close()).map_err(as_error)
}

fn validate_query_id(actual: &str, index: usize) -> Result<(), String> {
    let expected = format!("query-{index}");
    if actual == expected {
        return Ok(());
    }
    Err(format!("expected Query ID {expected}, received {actual}"))
}

fn run_server(port: u16) -> Result<(), String> {
    serve_once(port, serve_connection)
}

fn run_client(port: u16) -> Result<(), String> {
    let transport = TcpTransport::connect(port)?;
    let session = client::ClientSession::<TcpTransport, client::Ready>::new(transport);
    let second = block_on(session.send_query(messages::Query {
        id: "query-0".to_owned(),
    }))
    .map_err(as_error)?;
    let third = block_on(second.send_query(messages::Query {
        id: "query-1".to_owned(),
    }))
    .map_err(as_error)?;
    let awaiting = block_on(third.send_query(messages::Query {
        id: "query-2".to_owned(),
    }))
    .map_err(as_error)?;
    let waiting = block_on(awaiting.send_finish(messages::Finish {
        id: "batch".to_owned(),
    }))
    .map_err(as_error)?;
    let result = expect_message(block_on(waiting.recv_result()).map_err(as_error)?, "Result")?;
    if result.message.id != "aggregate" || result.message.result != "received 3 queries" {
        return Err(format!("unexpected aggregate Result: {:?}", result.message));
    }
    block_on(result.session.close()).map_err(as_error)
}

fn as_error<E: std::fmt::Debug>(error: E) -> String {
    format!("{error:?}")
}

fn main() {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    if let Err(error) = run_peer(&arguments, run_server, run_client) {
        eprintln!("interop-peer failed: {error}");
        std::process::exit(1);
    }
}
