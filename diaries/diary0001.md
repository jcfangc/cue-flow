# CueFlow Diary 0001：项目动机与核心模型

## 1. CueFlow 是什么

CueFlow 是一个以 CUE 作为主要协议描述前端的强类型 session protocol compiler。

它希望同时描述两件事情：

```text
一个消息什么样才合法

一个消息什么时候出现才合法
```

也就是：

```text
Value Correctness
+
Temporal Correctness
```

CueFlow 不以重新发明网络传输协议为主要目标。

它主要关注：

```text
data type

constraint

message direction

message ordering

branch ownership

session lifecycle

code generation
```

Wire encoding 应尽量简单、稳定、机械。

---

## 2. CueFlow 源于什么

CueFlow 的直接来源是 Protobuf + gRPC 的使用经验。

Protobuf 很适合描述：

```text
Message A
Message B
Message C
```

gRPC 很适合描述几类常见 RPC shape：

```text
Unary

Client Streaming

Server Streaming

Bidirectional Streaming
```

但当协议真正存在 session 语义时，这几个固定模型开始显得过于粗粒度。

例如：

```text
连接建立
↓
客户端必须先发送一次 Context
↓
Context 在整个 session 内有效
↓
之后客户端不断发送 Query
↕
服务器不断返回 Result
↓
Close
```

使用普通 gRPC bidi stream 往往只能表达成：

```text
ClientFrame =
    Context
  | Query
```

然后业务代码自己维护：

```text
context_seen

if first_frame ...

if context_received_twice ...

if query_before_context ...
```

也就是说：

> 数据 schema 知道 frame 是什么，却不知道 frame 应该什么时候出现。

CueFlow 想把这些 temporal invariants 提升到协议定义层。

---

## 3. CueFlow 想摆脱什么

CueFlow 不准备继续依赖以下模式：

```text
固定的 unary / streaming 四象限

用 oneof 模拟 session state

依靠注释描述 frame 顺序

业务代码手写 protocol FSM

client/server 分别维护隐含的状态机

把 Context 当普通 frame 特判

所有协议错误都等到 runtime 才发现

为了 schema 而接受过弱的数据约束能力
```

尤其不希望出现：

```text
“第一帧必须是 Context，具体请看注释。”
```

如果这是协议 invariant，它就应该存在于协议类型中。

---

## 4. 为什么选择 CUE

CueFlow 暂时不准备发明新的用户可见协议语言。

CUE 已经提供：

```text
struct

definition

required / optional

list

disjunction

constraint

range

regex

default

composition

unification

package/module
```

它已经能够很好地回答：

> 一个值属于什么合法值集合？

例如：

```cue
#Query: {
    id: string & != ""

    sequence: string & =~"^[ACGT]+$"

    topK: int & >=1 & <=100
}
```

这里描述的不只是序列化布局。

它描述的是：

```text
Query 合法值空间
```

CueFlow 没必要重新实现这一套。

CueFlow 真正增加的是 CUE 当前不负责的时间维度：

```text
这个值什么时候可以出现？
```

---

## 5. CUE 与 CueFlow 的职责边界

CUE 负责：

```text
Value Space
```

CueFlow Protocol Algebra 负责：

```text
Temporal Space
```

因此：

```text
CUE constraints
       │
       ▼
“这个值是否合法”

Protocol grammar
       │
       ▼
“这个消息现在是否合法”
```

最终：

```text
Protocol Correctness
=
Value Correctness
AND
Temporal Correctness
```

CueFlow 不修改 CUE 本身的语义。

Protocol 只是由 CUE 描述的一种 AST。

---

## 6. 当前核心 Protocol Algebra

第一阶段核心原语暂定为：

```text
Send<T>

Recv<T>

Seq<A, B>

Choose<A, B>

Offer<A, B>

Loop<A>

Close
```

保持数量尽可能少。

---

### Send<T>

当前一方向远端发送一个 `T`。

```text
Send<Query>
```

---

### Recv<T>

当前一方从远端接收一个 `T`。

```text
Recv<Result>
```

---

### Seq<A, B>

先执行 A，再执行 B。

```text
Seq(
    Send<Request>,
    Recv<Response>
)
```

顺序具有语义：

```text
A ; B != B ; A
```

---

### Choose<A, B>

当前一方选择一个 branch。

例如：

```text
Choose(
    Send<Query>,
    Send<Cancel>
)
```

表示 branch ownership 在当前端。

---

### Offer<A, B>

远端选择 branch，当前端负责接受。

```text
Offer(
    Recv<Query>,
    Recv<Cancel>
)
```

它与 Choose 构成对偶。

---

### Loop<A>

重复执行 A。

```text
Loop(
    Recv<Event>
)
```

第一版用 Loop 覆盖主要重复场景，不急于引入任意递归类型。

---

### Close

session 正常结束。

---

## 7. Dual

CueFlow 的核心性质之一是 protocol duality。

如果客户端定义：

```text
Send<A>
```

服务器自动得到：

```text
Recv<A>
```

如果客户端：

```text
Recv<B>
```

服务器得到：

```text
Send<B>
```

因此：

```text
dual(Send<T>) = Recv<T>

dual(Recv<T>) = Send<T>

dual(Choose<A,B>)
=
Offer<dual(A), dual(B)>

dual(Offer<A,B>)
=
Choose<dual(A), dual(B)>
```

用户原则上只定义一侧 protocol。

另一侧自动生成。

这样 client 与 server 不会维护两套独立 session schema。

---

## 8. Context 不作为特殊机制

CueFlow 不准备内置：

```text
ContextFrame
InitFrame
MetadataFrame
```

这种特殊概念。

如果某个协议要求第一步发送 Context：

```text
Seq(
    Send<Context>,
    ...
)
```

即可。

如果需要认证：

```text
Send<Auth>
;
Recv<AuthAccepted>
;
Send<Context>
;
...
```

如果未来出现其他初始化阶段，也只是正常 protocol sequence。

Framework 不需要提前知道用户会有哪些 session 初始化语义。

---

## 9. 示例：Context Session

当前主要 motivating example：

```text
Seq(
    Send<Context>,

    Loop(
        Choose(
            Send<Query>,
            Recv<Result>
        )
    ),

    Close
)
```

含义：

```text
首先发送一次 Context

之后 session 内可以持续：

发送 Query
或
接收 Result

最终关闭
```

Context 不需要：

```text
oneof
first_frame boolean
context_seen flag
```

它只是 protocol 的第一步。

---

## 10. Rust Typestate

Rust 是 CueFlow 最重要的第一目标语言。

希望生成的 API 不只是：

```rust
session.send(...)
session.recv(...)
```

然后 runtime 再判断是否合法。

而是尽量让：

```rust
Session<P>
```

中的 `P` 表示当前剩余 protocol。

例如当前：

```text
P = Send<Context> ; Rest
```

则只存在：

```rust
send(Context)
```

发送后得到：

```rust
Session<Rest>
```

如果当前协议要求：

```text
Recv<Result>
```

那么：

```rust
session.send(query)
```

最好直接无法编译。

因此 CueFlow 在支持能力足够的语言中，希望：

> 非法 session state 尽量不可表示。

---

## 11. 不同语言允许不同静态保证等级

CueFlow 不要求所有语言拥有完全相同的类型系统表现能力。

暂定可以区分：

```text
L1 Codec

L2 Runtime Protocol

L3 Static Session
```

### L1 Codec

保证：

```text
encode/decode
```

符合 canonical wire format。

### L2 Runtime Protocol

runtime FSM 检查 protocol 顺序。

### L3 Static Session

语言类型系统能够表达时，进一步把 session state 编译进类型。

例如 Rust 可以重点实现 L3。

Python 可以保持：

```text
L2 + typing hints
```

协议语义一致即可，不强求 API 表面完全一致。

---

## 12. Canonical Protocol IR

虽然 CUE 是官方首选描述语言，但 CueFlow 不希望 compiler 后半段依赖 CUE。

架构：

```text
CUE
 ↓
Frontend
 ↓
Canonical Protocol IR
 ↓
Semantic Check
 ↓
Codegen / Codec
```

IR 至少包含：

```text
Types

Constraints

Protocol FSM

Wire IDs

Evolution Metadata
```

一旦进入 IR：

```text
Rust backend
Go backend
TypeScript backend
...
```

都不需要理解 CUE。

未来如果需要，也可以增加：

```text
Rust DSL
TypeScript DSL
其他 frontend
```

共同生成相同 IR。

因此：

> CUE 是 canonical authoring frontend，而不是 runtime dependency。

---

## 13. Wire Format 原则

CueFlow 暂时不准备把创新重点放在二进制编码。

Wire format 应尽量机械：

```text
integer

float

bool

bytes

UTF-8 string

list

map

struct

tagged union

frame tag

payload length
```

优先保证：

```text
canonical

deterministic

easy to implement

easy to fuzz

easy to generate golden vectors

easy to port
```

而不是追求极端压缩率。

协议语义比少几个字节更重要。

---

## 14. Schema 与 Wire Type 不完全相同

CUE 表达能力远强于普通 wire schema。

例如：

```cue
#Port: int & >=1 & <=65535
```

Wire 上可以只是：

```text
u16
```

但生成 Rust 时可以得到：

```rust
struct Port(NonZeroU16);
```

因此 compiler 需要区分：

```text
semantic type

wire representation
```

约束不应该因为 lowering 到 wire format 而丢失。

---

## 15. 第一阶段目标

第一版只需要证明：

```text
CUE
 ↓
Protocol IR
 ↓
Rust data types
 ↓
Rust session types
 ↓
Rust client ↔ Rust server
```

只支持：

```text
Send
Recv
Seq
Choose
Offer
Loop
Close
```

并验证：

```text
schema constraint 不丢失

Context 只能在正确位置出现

非法 frame 顺序被拒绝

client/server protocol 自动对偶

encode/decode canonical

恶意远端不能绕过 runtime FSM
```

先只做好 Rust。

20 门语言属于后续机械扩展问题。

---

## 16. 当前非目标

第一阶段明确不做：

```text
HTTP/2 replacement

QUIC implementation

TLS implementation

service discovery

load balancing

retry framework

distributed tracing framework

schema registry

IDE plugin

完整 package ecosystem

20 种语言同时达到 L3

极端 zero-copy 优化
```

CueFlow 应该允许运行在已有 transport 上。

---

## 17. 与 Setpoint 的关系

CueFlow 和 Setpoint 是两个独立项目。

CueFlow 不以 Setpoint 为唯一使用场景。

Setpoint 也不能依赖 CueFlow 才能继续开发。

两者未来最自然的交汇点是：

```text
Setpoint Control Plane
        ↕
     CueFlow
        ↕
Setpoint Node Agent
```

这可以验证 CueFlow 是否真正适合长生命周期、有状态、双向的系统协议。

---

## 18. 当前原则

CueFlow 暂时遵循：

```text
协议状态是一等类型

消息顺序属于 schema，而不是注释

Context 只是普通协议阶段

Value Constraint 与 Session Constraint 正交

一侧协议定义，另一侧由 Dual 派生

少量原语优先于大量 RPC shape

CUE 负责值空间

Protocol Algebra 负责时间空间

IR 与 CUE frontend 解耦

Wire format 保持机械

能静态证明的，不留到 runtime

无法静态证明的，runtime 必须验证

先证明协议模型，再扩语言生态
```

CueFlow 不试图重新实现 gRPC。

它想回答的是：

> 如果协议不仅知道“消息是什么”，还知道“消息什么时候可以出现”，客户端和服务器 API 会变成什么样？
