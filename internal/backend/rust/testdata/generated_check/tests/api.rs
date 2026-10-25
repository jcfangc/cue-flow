//! Rust 生成 API 的运行期集成测试，使用 Mock Transport 检查状态转移、消息校验及 Close 行为。

use cueflow_generated_check::{
    client, messages, server, Inbound, ProtocolError, ReceiveOutcome, Transport,
};
use std::future::Future;
use std::task::{Context, Poll, Waker};

enum Incoming {
    Close,
    Message {
        message_id: String,
        payload: serde_json::Value,
    },
}

struct Mock {
    incoming: Option<Incoming>,
}

impl Mock {
    fn closed() -> Self {
        Self { incoming: None }
    }

    fn message(message_id: &str, payload: serde_json::Value) -> Self {
        Self {
            incoming: Some(Incoming::Message {
                message_id: message_id.into(),
                payload,
            }),
        }
    }
}

impl Transport for Mock {
    type Error = String;

    async fn send<M: serde::Serialize + Sync>(
        &mut self,
        _message_id: &'static str,
        _message: &M,
    ) -> Result<(), Self::Error> {
        Ok(())
    }

    async fn recv<M: serde::de::DeserializeOwned + Send>(
        &mut self,
        expected_message_id: &'static str,
    ) -> Result<Inbound<M>, Self::Error> {
        match self.incoming.take().unwrap_or(Incoming::Close) {
            Incoming::Close => Ok(Inbound::Close),
            Incoming::Message { message_id, payload } => {
                if message_id != expected_message_id {
                    return Err(format!(
                        "expected {expected_message_id}, received {message_id}"
                    ));
                }
                serde_json::from_value(payload)
                    .map(Inbound::Message)
                    .map_err(|error| error.to_string())
            }
        }
    }

    async fn send_close(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }

    async fn recv_close(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }
}

fn block_on<F: Future>(future: F) -> F::Output {
    let mut future = std::pin::pin!(future);
    let mut context = Context::from_waker(Waker::noop());
    loop {
        if let Poll::Ready(output) = future.as_mut().poll(&mut context) {
            return output;
        }
    }
}

async fn legal_client_flow() {
    let session = client::ClientSession::<Mock, client::Ready>::new(Mock::closed());
    let session = session
        .send_query(messages::Query {
            id: "q1".into(),
            sequence: "ACGT".into(),
            top_k: 5,
            note: None,
            cue_gen: None,
        })
        .await
        .unwrap();
    match session.recv_result().await.unwrap() {
        ReceiveOutcome::Closed => {}
        ReceiveOutcome::Message { message: _, session: _ } => {}
    }
}

fn query_payload(id: &str, sequence: &str, top_k: i64) -> serde_json::Value {
    serde_json::json!({"id": id, "sequence": sequence, "topK": top_k})
}

fn receive_query(
    payload: serde_json::Value,
    message_id: &str,
) -> Result<
    ReceiveOutcome<messages::Query, server::ServerSession<Mock, server::Waiting>>,
    ProtocolError<String>,
> {
    let session = server::ServerSession::<Mock, server::Ready>::new(Mock::message(message_id, payload));
    block_on(session.recv_query())
}

#[test]
fn optional_fields_distinguish_missing_from_null() {
    let missing = r#"{"id":"q1","sequence":"ACGT","topK":5}"#;
    assert!(serde_json::from_str::<messages::Query>(missing).is_ok());

    let explicit_null = r#"{"id":"q1","sequence":"ACGT","topK":5,"note":null}"#;
    assert!(serde_json::from_str::<messages::Query>(explicit_null).is_err());
}

async fn wait_for_peer_close_in_send_state() {
    client::ClientSession::<Mock, client::Ready>::new(Mock::closed())
        .recv_close()
        .await
        .unwrap();
}

#[test]
fn server_receives_valid_query_and_transitions() {
    match receive_query(query_payload("q1", "ACGT", 5), "Query").unwrap() {
        ReceiveOutcome::Message { message, session } => {
            assert_eq!(message.id, "q1");
            let _: server::ServerSession<Mock, server::Waiting> = session;
        }
        ReceiveOutcome::Closed => panic!("expected Query message"),
    }
}

#[test]
fn server_rejects_query_values_outside_cue_constraints() {
    for payload in [
        query_payload("q1", "ACGX", 5),
        query_payload("", "ACGT", 5),
        query_payload("q1", "ACGT", 0),
        query_payload("q1", "ACGT", 101),
    ] {
        match receive_query(payload, "Query") {
            Err(ProtocolError::Validation(_)) => {}
            _ => panic!("expected CUE constraint validation failure"),
        }
    }
}

#[test]
fn server_accepts_query_integer_boundaries() {
    for top_k in [1, 100] {
        match receive_query(query_payload("q1", "ACGT", top_k), "Query").unwrap() {
            ReceiveOutcome::Message { .. } => {}
            ReceiveOutcome::Closed => panic!("expected Query message"),
        }
    }
}

#[test]
fn unexpected_message_id_is_a_transport_error() {
    match receive_query(query_payload("q1", "ACGT", 5), "Unknown") {
        Err(ProtocolError::Transport(_)) => {}
        _ => panic!("unexpected message ID must not become a valid transition"),
    }
}

#[test]
fn legal_typestate_flow_observes_peer_close() {
    block_on(legal_client_flow());
}

#[test]
fn send_only_state_can_wait_for_peer_close() {
    block_on(wait_for_peer_close_in_send_state());
}
