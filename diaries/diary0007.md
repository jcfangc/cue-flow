# CueFlow Diary 0007：项目定位、当前实现与 Protobuf/gRPC 的关系

日期：2026-11-15

## 1. 为什么重新梳理

CueFlow 已经从最初的 CUE + FSM 原型，发展到具有 Rust/Python 后端、WebSocket 绑定和多种 Codec 的代码生成器。继续增加 CUE 语义、通信绑定和运行时之前，需要重新明确项目究竟解决什么问题，以及哪些事情不属于它。

本篇是截至当前实现的阶段性定位和路线总结，不覆盖此前日志中的历史决策。若未来实现与本文计划不同，应以新的决策日志明确更新。

## 2. 项目定位

CueFlow 是一个 **CUE-native Typed FSM Protocol Compiler**。

它把两个彼此正交的正确性维度放进同一份协议定义：

- **Value Correctness**：一条消息的数据结构是什么，字段值必须满足哪些约束。
- **Temporal Correctness**：在当前协议状态下，哪一方可以发送或接收哪种消息，发生后进入哪个状态。

因此，协议正确性可以概括为：

~~~text
Protocol Correctness
= Value Correctness
AND Temporal Correctness
~~~

CUE 负责描述消息值空间；CueFlow 的 FSM 负责描述消息出现的方向、顺序和状态转移。编译器把它们转换为目标语言中的消息模型、验证逻辑和状态化通信 API。

项目要解决的核心问题不是“如何再造一种网络协议”，而是：

> 把原本散落在业务代码、注释和运行时分支中的协议状态约束，提升为可编译、可验证、可生成的协议定义。

### 2.1 用户编写什么

用户在 CUE 中定义：

1. 消息 ID 到 CUE 值约束的显式映射。
2. 初始状态。
3. 每个状态允许的 server-side send 和 recv 转移，以及各自的目标状态。

send 和 recv 以服务端为主语：

- send：服务端向客户端发送。
- recv：服务端从客户端接收。

客户端 API 由生成器交换两个方向得到。用户不需要为 Client 和 Server 分别维护两份协议。

### 2.2 生成什么

同一份 CUE 协议可以生成不同语言的：

- 消息数据类型。
- 消息约束验证逻辑。
- Client / Server 状态 API。
- 可选的 Runtime + Communication Binding + Codec 适配器。

生成 API 应尽可能把当前状态允许的操作表达在目标语言类型中。Rust 通过状态类型表达 Typestate；Python 通过独立状态类、类型标注和运行时检查提供相应 API。不同语言不必拥有完全相同的静态保证等级，但必须遵守相同的协议语义。

## 3. 设计边界与非目标

CueFlow 应优先实现协议语义和代码生成，不重新实现成熟生态已经解决的问题。

核心原则：

~~~text
Compiler Smart, Runtime Boring
~~~

编译器负责 CUE 语义分析、FSM 检查、目标类型映射和代码生成；Runtime 尽量复用 Tokio、asyncio、成熟网络库和序列化库。

当前不以如下事项为项目目标：

- 自研 TCP、TLS、HTTP/2、QUIC 或 WebSocket 协议栈。
- 自研 JSON、CBOR 或 Protobuf 二进制编码算法。
- 通用 tracing、metadata、session ID 或 Envelope 规范。
- 服务发现、负载均衡、重试框架和分布式调度。
- 完整 Multiparty Session Type、全局死锁自由证明或活性证明。
- 自动推断业务请求与响应的关联关系。
- 不加区分地实现所有语言、Runtime、Binding 和 Codec 的完整笛卡尔积。

业务消息及其业务元信息由用户在 CUE 中定义。CueFlow 不额外强制 message_id、tracing_id、session_id 或 payload 包装层。具体传输已有的标准元数据机制应优先沿用。

## 4. 当前协议模型及其保证边界

当前核心模型是以服务端为主语的有限状态机，而不是完整的 Multiparty Session Type。

它描述：

- 当前状态。
- 服务端允许发送的消息及其后继状态。
- 服务端允许接收的消息及其后继状态。
- Client API 与 Server API 的方向对偶。
- 非终态状态隐式允许逻辑 Close；终态没有业务转移。

它保证的是协议安全性的一部分：生成 API 暴露当前状态允许的操作，收到或发送的消息仍须通过消息约束验证。

它不自动保证：

- 一条 Query 必然对应一条 Result。
- 请求和响应之间的 ID 关联。
- 消息计数、跨消息累积条件或依赖消息内容的 Guard。
- 双方不会死锁，或 Session 最终会结束。
- 任意并发交错、调度顺序和业务活性。
- 网络断线后自动重连、恢复或重放。

双方各自维护局部 FSM 状态。发送一条消息不等于对端已经处理该消息；消息交付、缓冲、背压、任务调度和连接生命周期由具体 Runtime / Binding 决定。

### 4.1 当前无通用 Envelope 的后果

WebSocket 线上帧直接承载 CUE 定义的业务消息对象，不额外增加 CueFlow 消息 ID 字段。接收端利用当前 FSM 状态确定预期消息类型。

因此，如果某一端在同一状态下需要从多个不同消息类型中进行接收分派，而线上消息本身没有可用的区分信息，当前生成器会拒绝有歧义的 Endpoint 组合。不能通过猜测消息形状或静默选择一种类型来绕过这个限制。

如确实需要分支标识，应由具体用户协议显式定义，或由未来某种 Binding 的既有机制提供；不因此引入全局 Envelope 规范。

### 4.2 Close

协议层 Close 表示逻辑 Session 结束。当前 WebSocket Binding 将它映射到 WebSocket Close，因此一个 CueFlow Session 对应一条 WebSocket 连接。这个映射是当前 Binding 的实现选择，不意味着所有未来 Binding 都必须以相同方式关闭底层连接。

Close 不代表对端已经处理完所有业务消息，也不提供请求确认、取消、重试或恢复语义。

## 5. 当前实现状态（截至 765f639）

### 5.1 生成轴

| 维度 | 当前刻度 | 说明 |
|---|---|---|
| Language | Rust、Python | CLI 的生成目标 |
| Runtime | Tokio、asyncio | 分别对应 Rust、Python；不支持交叉组合 |
| Endpoint | Client、Server、Both | 选择生成哪些端点 API |
| Communication Binding | WebSocket | CLI 参数目前仍命名为 --transport |
| Codec | JSON、CBOR | JSON 使用 WebSocket Text Frame；CBOR 使用 Binary Frame |

当前已支持的通信组合：

| Binding | JSON | CBOR |
|---|---|---|
| WebSocket | 已支持 | 已支持 |
| HTTP | 计划支持 | 暂不承诺 |

轴是独立职责，不代表所有值都可以任意组合。生成器只接受兼容性矩阵中明确支持的组合；其他组合应明确报错，不静默降级。

### 5.2 CUE 消息语义

当前 README 承诺的支持范围：

| 语义 | 当前状态 |
|---|---|
| String | 支持 |
| Boolean | 支持 |
| 有界 Integer（目标范围为 i64） | 支持 |
| 字符串非空约束 | 支持 |
| 字符串正则约束 | 支持 |
| 字符串最小 / 最大长度 | 支持 |
| 整数 inclusive 最小 / 最大值 | 支持 |
| 必填字段 | 支持 |
| Optional 字段 | 支持 |
| 递归嵌套的闭合对象 | 支持 |
| 数组 / List | 尚未支持 |
| 显式 Nullable / null | 尚未支持 |
| Literal / Enum / Disjunction | 尚未支持 |
| 动态键 / Open Object | 尚未支持 |
| Default | 尚未建立支持承诺 |

Optional 与 Nullable 必须区分：

- field?: string：字段可以缺失；存在时必须是字符串。当前支持缺失，但拒绝显式 null。
- field: string | null：字段必须存在，且允许字符串或 null。当前不支持。

不能把 Optional 当作 Nullable，也不能在生成代码时丢弃未支持的约束。

### 5.3 后端与通信实现

- Go 编译器通过 CUE 官方 Go API 加载并检查协议。
- 共享 Schema lowering 把支持的 CUE 消息约束转换为语言无关的字段模型。
- Rust 后端生成消息类型、验证逻辑和状态化 Client / Server API。
- Python 后端生成 Pydantic v2 消息模型、验证逻辑和状态化 Client / Server API。
- 不指定具体 Binding 时，生成 API 保留 Transport 抽象边界。
- WebSocket + JSON / CBOR 适配器复用目标语言生态中的成熟库。
- CLI 只生成源代码，不负责替用户项目安装依赖、建立连接、认证或重连。

### 5.4 当前验证缺口

现有跨语言 test_interop.py 使用测试专用的 JSON Lines over loopback TCP；该测试 framing 不是 CueFlow 的生产 Wire Format。

嵌套对象目前已经有 Rust / Python 类型生成和约束测试，但嵌套消息尚未完成通过生产 WebSocket JSON / CBOR Binding 的双向跨语言实连验证。

因此，当前不能把“嵌套消息经 WebSocket JSON / CBOR 跨语言互通”记作已验收。

## 6. 与 Protobuf 和 gRPC 的关系

必须区分 Protobuf 与 gRPC：它们通常一起使用，但属于不同层次。

### 6.1 Protobuf：消息 Schema 与 Wire Encoding

Protobuf 主要定义消息结构、字段类型、字段编号、Repeated、Map、Enum、Oneof 等，并规定成熟的二进制 Wire Format。

其重要优势包括：

- 稳定的字段编号。
- 成熟的二进制编码和解码生态。
- 明确的字段兼容性与 Schema Evolution 规则。
- 多语言代码生成和广泛工具支持。

CUE 与 Protobuf 的主要差别：

| 维度 | Protobuf | CUE |
|---|---|---|
| 主要用途 | 消息 Schema 与序列化 | 数据约束、配置和结构化值建模 |
| 结构类型 | Message | Struct / Definition |
| 重复字段 | Repeated | List |
| 动态键 | Map | Open Struct / Map 约束 |
| 有限值集合 | Enum | Literal / Disjunction |
| 数值范围约束 | 通常需要额外验证规则 | 原生约束 |
| 正则与长度约束 | 通常需要额外验证规则 | 原生约束 |
| 组合约束 | 以 Schema 类型系统为主 | Unification 与约束组合 |
| 线上格式 | Protobuf Wire Format | CUE 本身不规定 Wire Format |

CueFlow 当前使用 JSON 或 CBOR 作为消息编码，并没有 Protobuf 式稳定字段编号。因此：

- 当前 CBOR 不是 Protobuf Wire Format。
- CUE 定义不能自动视为 Protobuf Schema。
- 当前不能宣称具备 Protobuf 的二进制兼容性和演进保证。

未来如果需要稳定的长期二进制协议，需要专门设计字段身份、版本演进、删除字段和兼容性检查；不能仅靠把 JSON 换成 CBOR 解决。

Protobuf 也可以配合额外的验证扩展或验证器表达更丰富的值约束。比较时不应把“Protobuf 核心语法没有原生表达”误说成“Protobuf 生态完全做不到”。

### 6.2 gRPC：RPC 与 Streaming Runtime

gRPC 是 RPC 框架，通常使用 Protobuf 定义消息和服务，并以 HTTP/2 承载 RPC。它提供：

- Unary RPC。
- Client Streaming RPC。
- Server Streaming RPC。
- Bidirectional Streaming RPC。
- Client / Server Stub。
- Metadata、Status、Deadline、Cancellation。
- 流量控制、消息分帧和成熟的连接管理。

CueFlow 不应重新实现这些通用通信设施。

### 6.3 CueFlow 与 gRPC 的真正区别

gRPC 的四种 RPC cardinality 能够承载很多交互模式，但 gRPC 生成的 Stub 主要表达服务方法、消息类型和 Stream API；它不会自动把任意业务消息时序编译为状态专属 API。

例如，双向流可以承载：

~~~text
Client -> Context
Client -> Query
Server -> Result
Client -> Query
Server -> Result
...
~~~

但“Context 必须先出现一次”“Context 不能重复”“Query 只能在 Context 之后发送”等业务状态规则，通常仍由应用代码检查。

CueFlow 的目标是把这些 temporal invariants 写入 FSM，再生成状态化 API 和运行时验证逻辑。

| 问题 | Protobuf / gRPC | CueFlow |
|---|---|---|
| 消息结构 | Protobuf Schema | CUE |
| 复杂值约束 | 可借助扩展验证机制 | CUE 原生约束 |
| 二进制 Wire Format | Protobuf Wire Format | 当前 JSON / CBOR |
| RPC / Streaming | gRPC 提供成熟实现 | 当前 WebSocket Binding；HTTP 规划中 |
| 消息方向与顺序 | RPC 形状 + 应用逻辑 | FSM 显式定义 |
| 状态专属 API | 通常由应用自行组织 | 生成器生成 |
| 运行时成熟度 | 成熟、广泛部署 | 早期项目，能力有限 |

这不是说 gRPC 无法实现 FSM 协议。gRPC 完全可以承载 CueFlow 描述的协议；区别在于状态规则由谁定义、谁生成、谁验证。

### 6.4 两者可以共存

未来可以评估 gRPC Binding，而不是把它视为竞争对手：

~~~text
CUE
  |
  v
CueFlow Compiler
  |
  +---- Protobuf Schema / Message Types
  |
  +---- FSM-aware Client / Server API
              |
              v
          gRPC Runtime
              |
              v
            HTTP/2
~~~

在这种架构中：

- CUE 继续作为用户的协议约束来源。
- Protobuf 可以承担消息类型映射和稳定二进制 Wire Format。
- gRPC 负责 HTTP/2、RPC、Streaming、Metadata、Status 等通信设施。
- CueFlow 生成状态化 API，并补充 Protobuf / gRPC 本身不自动提供的 FSM 约束。

但这只是长期候选方向。要实现它，还需要设计 CUE 到 Protobuf 的语义映射、字段编号与演进策略、FSM 与 Stream 的映射、分支识别和错误语义。不能简单增加一个 --codec protobuf 就视为完成。

## 7. 后续路线

按当前目标，后续工作分为三个方向。

### 方向 A：完善 CUE 语义编译器

这是 CueFlow 的核心能力，优先于继续增加通信轴。

1. **数组 / List**：完成元素类型、递归嵌套和元素约束的 Rust / Python 纵向切片；明确区分同质列表、固定长度列表、异构 Tuple 等语义，尚未支持的形态明确拒绝。
2. **CUE Oracle 测试框架**：使用 CUE 自身作为参考判断，对同一组有效 / 无效输入比较 Rust 与 Python 的接受 / 拒绝结果，防止后端语义漂移。
3. **Nullable / Literal / Enum**：明确字段缺失、显式 null、有限值集合的区别。
4. **Map / Dynamic Keys**：支持动态键及其值约束。
5. **Union / Disjunction**：处理多分支类型、分支判别和重叠约束。
6. **Default**：在明确 CUE 默认值语义和生成行为后再承诺支持。

每个语义切片都必须满足：

- Rust 和 Python 都有对应类型或等价表示。
- 两端都有约束验证。
- 正例和反例覆盖边界值、缺失值、类型错误及约束冲突。
- CUE Oracle、Rust、Python 对同一输入给出一致的接受 / 拒绝结果。
- 不支持的语义必须明确报错，不允许静默丢失约束。

### 方向 B：验证并扩展通信绑定

1. 先完成嵌套消息经 WebSocket JSON / CBOR 的双向跨语言实连测试。
2. 保持 Runtime、Endpoint、Binding、Codec 的职责分离；只实现明确需要的兼容组合。
3. 按 Diary 0006 的决定实现 HTTP + JSON。
4. HTTP 首期支持 HTTP/1.1 和 HTTP/2，交由成熟 HTTP 库处理；HTTP Version 不单独成为 CLI 轴。
5. HTTP 首期只支持完整的一问一答 FSM：Client 发送一条请求消息，Server 接收并返回一条响应消息，双方到达终态。不符合该形状的 FSM 必须拒绝生成。
6. HTTP + CBOR、HTTP/3 根据实际需求重新评估，不纳入当前承诺。

### 方向 C：长期评估 Protobuf / gRPC 集成

在 CUE 语义映射、Wire Format 演进和 FSM 语义更成熟后，再决定是否实现：

- Protobuf Schema 生成。
- 稳定字段编号与兼容性检查。
- gRPC Client / Server Stub 适配。
- Streaming 与 FSM 状态 API 的组合。
- Metadata、Status、Deadline、Cancellation 的映射。

不在当前阶段启动完整 gRPC 兼容工作。

## 8. 阶段验收指标

CueFlow 不以支持的语言数量、Codec 数量或 Binding 数量作为唯一进度指标。核心验收维度是：

| 维度 | 验收问题 |
|---|---|
| Value Correctness | 生成的消息类型与验证逻辑是否保留 CUE 约束？ |
| Temporal Correctness | 当前状态下是否只暴露合法方向和消息操作？ |
| Static Safety | 目标语言类型系统能够提前发现哪些非法操作？ |
| Runtime Safety | 对端传入的非法值和非法时序是否会被拒绝？ |
| Interoperability | Rust 与 Python 的同一协议实现能否真实互通？ |
| Evolution | 协议变化是否有明确的兼容性规则？ |

## 9. 本阶段结论

CueFlow 与 Protobuf / gRPC 的关系不是替代关系：

- Protobuf 擅长成熟的消息 Schema 和稳定二进制编码。
- gRPC 擅长 RPC、Streaming 和底层通信设施。
- CUE 擅长表达丰富的数据约束。
- CueFlow 的差异化价值是把 CUE 值约束与 FSM 时序约束编译成多语言状态化 API。

近期应优先证明消息语义在 Rust、Python 和实际通信 Binding 之间保持一致，然后扩展数组等 CUE 语义。HTTP + JSON 是已规划的下一类通信绑定；Protobuf / gRPC 集成是长期候选，而不是当前必须完成的目标。

最终原则：

~~~text
CUE defines valid values.
FSM defines valid interactions.
CueFlow compiles both into usable APIs.
Mature runtimes carry the messages.
~~~
