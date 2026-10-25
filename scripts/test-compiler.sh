#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
tmp_dir=$(mktemp -d)
trap 'rm -rf "$tmp_dir"' EXIT
CARGO_TARGET_DIR=${CARGO_TARGET_DIR:-"$tmp_dir/cargo-target"}
export CARGO_TARGET_DIR
CARGO_PROFILE_DEV_DEBUG=${CARGO_PROFILE_DEV_DEBUG:-0}
export CARGO_PROFILE_DEV_DEBUG

go build -o "$tmp_dir/cueflow" "$repo_root/cmd/cueflow"
"$tmp_dir/cueflow" check --input "$repo_root/cue/examples"
"$tmp_dir/cueflow" generate rust --input "$repo_root/cue/examples" --output "$tmp_dir/rust-check/src/lib.rs"

mkdir -p "$tmp_dir/rust-check/src/bin" "$tmp_dir/rust-check/tests"
cat >"$tmp_dir/rust-check/Cargo.toml" <<'EOF'
[package]
name = "cueflow-generated-check"
version = "0.1.0"
edition = "2024"

[dependencies]
regex = "1"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
EOF

cat >"$tmp_dir/rust-check/tests/api.rs" <<'EOF'
use cueflow_generated_check::{
    client, messages, Inbound, ReceiveOutcome, Transport,
};
use std::future::Future;
use std::task::{Context, Poll, Waker};

struct Mock;

impl Transport for Mock {
    type Error = ();

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
        Ok(Inbound::Close)
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
    let session = client::ClientSession::<Mock, client::Ready>::new(Mock);
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

#[test]
fn optional_fields_distinguish_missing_from_null() {
    let missing = r#"{"id":"q1","sequence":"ACGT","topK":5}"#;
    assert!(serde_json::from_str::<messages::Query>(missing).is_ok());

    let explicit_null = r#"{"id":"q1","sequence":"ACGT","topK":5,"note":null}"#;
    assert!(serde_json::from_str::<messages::Query>(explicit_null).is_err());
}

async fn wait_for_peer_close_in_send_state() {
    client::ClientSession::<Mock, client::Ready>::new(Mock)
        .recv_close()
        .await
        .unwrap();
}

#[test]
fn legal_typestate_flow_observes_peer_close() {
    block_on(legal_client_flow());
}

#[test]
fn send_only_state_can_wait_for_peer_close() {
    block_on(wait_for_peer_close_in_send_state());
}
EOF

cargo test --offline --manifest-path "$tmp_dir/rust-check/Cargo.toml"

cat >"$tmp_dir/rust-check/src/bin/invalid.rs" <<'EOF'
use cueflow_generated_check::{client, messages, Inbound, Transport};

struct Mock;

impl Transport for Mock {
    type Error = ();

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
        loop {}
    }

    async fn send_close(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }

    async fn recv_close(&mut self) -> Result<(), Self::Error> {
        Ok(())
    }
}

async fn invalid_direction() {
    let session = client::ClientSession::<Mock, client::Ready>::new(Mock);
    let _ = session.send_result(messages::Result { id: "q1".into(), result: "matched".into() });
}

fn main() {}
EOF
if cargo check --offline --manifest-path "$tmp_dir/rust-check/Cargo.toml" --bin invalid >"$tmp_dir/invalid.log" 2>&1; then
	echo "expected invalid typestate call to fail compilation" >&2
	cat "$tmp_dir/invalid.log" >&2
	exit 1
fi
if ! grep -F 'no method named `send_result`' "$tmp_dir/invalid.log" >/dev/null; then
	echo "invalid typestate example failed for an unexpected reason" >&2
	cat "$tmp_dir/invalid.log" >&2
	exit 1
fi

"$tmp_dir/cueflow" check --input "$repo_root/cue/testdata/rust_backend/unsupported_constraint"
if "$tmp_dir/cueflow" generate rust --input "$repo_root/cue/testdata/rust_backend/unsupported_constraint" --output "$tmp_dir/unsupported.rs" >"$tmp_dir/unsupported.log" 2>&1; then
	echo "expected unsupported CUE constraint to be rejected" >&2
	cat "$tmp_dir/unsupported.log" >&2
	exit 1
fi

"$tmp_dir/cueflow" check --input "$repo_root/cue/testdata/rust_backend/name_collision"
if "$tmp_dir/cueflow" generate rust --input "$repo_root/cue/testdata/rust_backend/name_collision" --output "$tmp_dir/collision.rs" >"$tmp_dir/collision.log" 2>&1; then
	echo "expected Rust lowering name collision to be rejected" >&2
	cat "$tmp_dir/collision.log" >&2
	exit 1
fi
if ! grep -F 'duplicate Rust name "Ready"' "$tmp_dir/collision.log" >/dev/null; then
	echo "Rust lowering collision failed for an unexpected reason" >&2
	cat "$tmp_dir/collision.log" >&2
	exit 1
fi

echo "compiler and generated Rust checks passed"
