//! 编译失败夹具：客户端 Ready 状态不允许发送 Result，测试脚本应确认该调用被 Rust 类型系统拒绝。

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
    let _ = session.send_result(messages::Result {
        id: "q1".into(),
        result: "matched".into(),
    });
}

fn main() {}
