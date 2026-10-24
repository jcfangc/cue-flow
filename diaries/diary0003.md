# CueFlow Diary 0003：最小协议 Schema 与 Close 语义

## 1. 本次决策

本次工作将 CueFlow 的 Typed FSM 方向落实为最小 CUE schema。目标是让 CUE 文件能直接承载协议图和消息约束，同时保持模型足够小；暂不开发编译器、Runtime、wire codec 或 Rust backend。

CUE 文件继续作为用户编写协议的规范来源；本阶段不另设一套用户维护的协议格式。此决定不取代 Diary 0002 规划的编译器架构：未来仍由 CUE frontend 将协议 lowering 到 compiler 内部的 Canonical Protocol IR，再进行语义检查和代码生成。该 IR 尚未实现，本次 schema 工作也不定义或改变它。

## 2. 协议 Schema

`protocol.cue` 定义了：

```text
#Protocol
  messages: MessageID → CUE value constraint
  initial: StateID
  states: StateID → State

#State
  send?: MessageID → next StateID
  recv?: MessageID → next StateID
  close?: true
```

状态图仍是协议的核心表示。`send` 和 `recv` 的键标识消息，值标识转移目标。一个状态可同时允许发送和接收；这表示两种通信行为均被协议允许，不表示调度顺序或活性保证。

## 3. 显式消息注册表

`#Protocol.messages` 是必填注册表，把协议中的 MessageID 映射到对应的 CUE 数据约束。例如：

```cue
messages: {
    Query:  #Query
    Result: #Result
}
```

MessageID 与 CUE 定义名可以相同，但二者概念不同：MessageID 是协议中的消息身份，`#Query`、`#Result` 是消息值约束。显式映射避免依赖隐式命名约定，并允许之后独立讨论 wire ID 和 CUE 类型的复用关系。

## 4. Close 语义

`close?: true` 表示该状态允许无载荷的逻辑 Close 事件。其约定为：

- 任一端都可以在允许 Close 的状态发送 Close，也可以在该状态接收对端的 Close。
- Close 在对偶下保持不变：`dual(Close) = Close`。
- 本端发送或接收 Close 后，session 立即进入隐式终态；终态不允许继续进行业务通信。
- Close 无需确认，不承诺对端已处理完此前的业务消息，也不表示异常断线。
- Close 终止逻辑 session，不决定底层连接或 stream 的释放和复用；这些由 Runtime 管理。

此处的 schema 字段本身只允许 `true`。上述双向、自对偶和终态行为是协议语义约定，未来应由 compiler 和 Runtime 按约定实现。

## 5. CUE Schema 与未来语义检查的边界

CUE schema 可以直接约束必填字段、状态结构、消息注册表值，以及 Close 字段只能为 `true`。示例也把 `#Query` 的字段约束注册到 `messages.Query` 并用请求样例验证该约束。

当前 schema 不保证跨字段引用完整性。未来 CueFlow compiler 在接受协议前必须检查：

- `initial` 指向已声明状态。
- 每条 `send` / `recv` 转移的目标状态都已声明。
- 每个 `send` / `recv` 的 MessageID 都在 `messages` 注册表中。
- FSM 是否满足后续确定的结构规则。

不能把这些性质描述成现有 CUE schema 已经保证的内容。

## 6. 安全性、活性与并发边界

CueFlow 第一阶段关注协议安全性：当前状态是否允许特定方向和类型的消息，以及状态如何转移。它不保证双方不会死锁、请求最终会得到响应或 session 最终会正常关闭；这些活性性质不能仅凭允许的转移图和应用代码的执行意愿推出。

因此，本阶段不为并发调度、超时、半关闭、Close 与在途消息的竞态或资源释放增加 schema 字段。这些问题可在 Runtime 设计阶段结合传输和执行模型讨论。

## 7. 验证与实现记录

仓库新增请求—响应协议示例，展示 `Query`、`Result` 注册、Send/Recv 转移和允许 Close 的状态。`test-schema.sh` 使用 CUE CLI 验证：

- 有效协议和消息样例通过。
- 非法 Close 值被拒绝。
- 不满足注册消息约束的 Query 值被拒绝。
- 缺少必填协议字段被拒绝。

非法状态引用和未知 MessageID 尚未作为 schema 负例测试，因为这些交叉引用检查留给未来 compiler。Schema 与验证用例由 reviewer 审查通过，并提交为 `eeb8b57`（`Add protocol message and close schema`）。

## 8. 当前结论

CueFlow 当前最小协议表示由三部分组成：

```text
CUE constraints  定义消息值
Typed FSM        定义消息方向与时序
messages map     把协议消息身份关联到 CUE 约束
```

下一步应启动 `cueflow check`：加载 CUE 协议，进入 Diary 0002 规划的 Canonical Protocol IR / semantic check 流程，并检查状态与消息交叉引用，再逐步补充明确的 FSM 结构规则。当前尚未实现 IR lowering、代码生成或 Runtime。
