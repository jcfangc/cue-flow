//! Verify recursive generated types and nested CUE constraints.

use cueflow_nested_check::{
    Inbound, ProtocolError, ReceiveOutcome, Transport, client, messages, server,
};
use std::future::Future;
use std::task::{Context, Poll, Waker};

struct Mock {
    payload: Option<serde_json::Value>,
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
        _message_id: &'static str,
    ) -> Result<Inbound<M>, Self::Error> {
        let payload = self.payload.take().ok_or("missing test payload")?;
        serde_json::from_value(payload)
            .map(Inbound::Message)
            .map_err(|error| error.to_string())
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

fn query_payload(sequence: &str, top_k: i64) -> serde_json::Value {
    serde_json::json!({
        "id": "q1",
        "filter.sequence": "root-level",
        "filter": {
            "sequence": sequence,
            "range": {"topK": top_k, "active": true}
        }
    })
}

fn receive_query(
    payload: serde_json::Value,
) -> Result<
    ReceiveOutcome<messages::Query, server::ServerSession<Mock, server::Waiting>>,
    ProtocolError<String>,
> {
    let session = server::ServerSession::<Mock, server::Ready>::new(Mock {
        payload: Some(payload),
    });
    block_on(session.recv_query())
}

#[test]
fn nested_fields_lower_to_named_rust_types() {
    let query: messages::Query = serde_json::from_value(query_payload("ACGT", 5)).unwrap();
    query.validate().unwrap();
    assert_eq!(query.filter.range.top_k, 5);
}

#[test]
fn nested_constraints_reject_invalid_values() {
    for payload in [
        query_payload("ACGX", 5),
        query_payload("ACGT", 0),
        query_payload("ACGT", 101),
    ] {
        match receive_query(payload) {
            Err(ProtocolError::Validation(_)) => {}
            _ => panic!("expected nested CUE constraint validation failure"),
        }
    }
}

#[test]
fn nested_objects_reject_missing_and_extra_fields() {
    let missing = serde_json::json!({"id": "q1", "filter": {"sequence": "ACGT"}});
    let extra = serde_json::json!({
        "id": "q1",
        "filter.sequence": "root-level",
        "filter": {
            "sequence": "ACGT",
            "range": {"topK": 5, "active": true, "unexpected": true}
        }
    });
    let null_optional = serde_json::json!({
        "id": "q1",
        "filter.sequence": "root-level",
        "filter": {
            "sequence": "ACGT",
            "note": null,
            "range": {"topK": 5, "active": true}
        }
    });
    assert!(serde_json::from_value::<messages::Query>(missing).is_err());
    assert!(serde_json::from_value::<messages::Query>(extra).is_err());
    assert!(serde_json::from_value::<messages::Query>(null_optional).is_err());

    let null_nested_object = serde_json::json!({
        "id": "q1",
        "filter.sequence": "root-level",
        "filter": query_payload("ACGT", 5)["filter"].clone(),
        "details": null
    });
    assert!(serde_json::from_value::<messages::Query>(null_nested_object).is_err());
}

#[test]
fn optional_nested_object_accepts_absent_or_valid_value() {
    let absent: messages::Query = serde_json::from_value(query_payload("ACGT", 5)).unwrap();
    absent.validate().unwrap();
    assert!(absent.details.is_none());

    let mut present = query_payload("ACGT", 5);
    present["details"] = serde_json::json!({"label": "valid"});
    let present: messages::Query = serde_json::from_value(present).unwrap();
    present.validate().unwrap();
    assert_eq!(present.details.unwrap().label, "valid");

    let mut invalid = query_payload("ACGT", 5);
    invalid["details"] = serde_json::json!({"label": ""});
    let invalid: messages::Query = serde_json::from_value(invalid).unwrap();
    assert!(invalid.validate().is_err());
}

#[test]
fn invalid_nested_message_is_rejected_before_send() {
    let message = messages::Query {
        id: "q1".to_owned(),
        filter_sequence: "root-level".to_owned(),
        filter: messages::QueryFilter {
            sequence: "ACGX".to_owned(),
            note: None,
            range: messages::QueryFilterRange {
                top_k: 5,
                active: true,
            },
        },
        details: None,
    };
    let session = client::ClientSession::<Mock, client::Ready>::new(Mock { payload: None });
    match block_on(session.send_query(message)) {
        Err(ProtocolError::Validation(_)) => {}
        _ => panic!("invalid nested message must be rejected before send"),
    }
}
