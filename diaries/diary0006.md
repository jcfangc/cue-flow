# CueFlow Diary 0006：生成轴刻度与兼容性矩阵

日期：2026-11-14

## 1. 目标

CueFlow 采用可组合的代码生成维度，不为每个组合增加专用 CLI 开关或独立生成方案。每个轴表达一个独立选择；兼容性矩阵明确哪些轴值可以组合。生成器只实现矩阵中明确支持的组合，对其他组合报错，不隐式降级，也不要求实现完整笛卡尔积。

当前 CLI 保留 `--transport` 参数名；它在本决策中承载 Communication Binding 选择。

## 2. 五个维度及刻度

| 维度 | 职责 | 刻度与约束 |
| --- | --- | --- |
| Language | 选择代码生成目标 | Rust、Python |
| Runtime | 选择目标生态的异步执行设施 | Tokio、`asyncio`；Rust 对应 Tokio，Python 对应 `asyncio`，不支持交叉组合 |
| Endpoint | 选择生成的端点 API | Client、Server、Both |
| Communication Binding | 定义消息收发方式及通信生命周期 | WebSocket、HTTP |
| Codec | 在 CUE 数据结构与线上字节间编码和解码 | JSON、CBOR |

Language 与 Runtime 是相关联的维度，不枚举无意义的组合。Endpoint 只决定生成哪些角色的状态机 API，不改变线上协议。不同语言后端独立生成和使用各自生态的依赖，不互相依赖。

## 3. Binding 与 Codec 兼容性矩阵

| Communication Binding | JSON | CBOR |
| --- | --- | --- |
| WebSocket | 已支持 | 已支持 |
| HTTP | 计划支持 | 暂不支持；之后按需求重新评估 |

矩阵约束适用于 Rust/Tokio 与 Python/`asyncio` 两个目标。增加某个 Codec 或 Binding 刻度，不会自动开放该刻度与其他所有值的组合。

不支持的组合必须给出明确错误。不能因为 Codec 或 Binding 暂不支持，就静默回退到其他线上表示。

## 4. Communication Binding 的语义

### WebSocket

- 表示持久连接上的双向通信和有状态会话。
- WebSocket 自身提供消息边界；CueFlow 不另加通用分帧机制。
- WebSocket + JSON 使用文本消息；WebSocket + CBOR 使用二进制消息。
- 当前 WebSocket Binding 按一个 CueFlow Session 对应一条 WebSocket 连接，并将协议 Close 映射到 WebSocket Close。

### HTTP

- 表示请求/响应和彼此独立的交换，不提供跨请求保存的 CueFlow FSM 会话状态。
- 第一版仅支持一次完整的请求/响应 FSM：Client 发出一条请求消息，Server 接收该消息并返回一条响应消息，双方到达终态。
- 不符合这一形状的协议必须拒绝生成；不通过隐式状态、Session ID 或持久化扩展其语义。
- HTTP Binding 负责把消息映射到 HTTP Method、Path、Status Code 和 Headers；这些内容不属于 Codec。
- HTTP/1.1 与 HTTP/2 是首期实现目标，由成熟 HTTP 库负责具体版本处理和连接管理。HTTP Version 不单独成为 CueFlow 轴，也不增加 CLI 参数。HTTP/3 留待后续验证。
- 实现时须区分 HTTP/Binding 失败与 CUE 消息验证失败；具体错误 API 在 HTTP 实现工作单元中定义。

## 5. 不单独设置的维度

以下概念不作为独立轴：

| 候选维度 | 决定 |
| --- | --- |
| Envelope | 不由 CueFlow 规定；用户通过自己的 CUE 消息表达元信息 |
| Framing | 由 WebSocket 或 HTTP Binding 处理 |
| TCP | 不直接提供底层字节流 Binding |
| Tracing | 使用现有标准及用户定义的消息元信息 |
| HTTP Version | 由 HTTP Binding 和成熟 HTTP 库处理；首期目标为 HTTP/1.1 与 HTTP/2 |
| Session | 由 Communication Binding 的语义决定：WebSocket 为有状态双向会话，HTTP 为单次请求/响应 |

## 6. 实施顺序

1. 本文冻结维度、刻度、Binding 与 Codec 兼容矩阵，以及 HTTP 首期语义；本阶段不修改通信实现。
2. 实现 WebSocket + CBOR，复用现有 WebSocket 适配器，使用二进制消息，并验证 Rust/Python 双向通信、Close 和异常路径。
3. 实现 HTTP + JSON，支持 Client、Server、Both；拒绝不符合单次请求/响应语义的 FSM，并验证 Rust/Python 双向通信。
4. HTTP + CBOR 不在当前承诺内，之后依据实际需求评估并更新兼容矩阵。

后续每新增刻度或组合，都应先更新职责与兼容性矩阵，再实现对应后端，并为不支持的组合保留明确拒绝行为。
