# CueFlow Diary 0002：从协议代数回到状态机

## 1. 这次发生了什么

CueFlow 最初的设想，是在 CUE 的值约束能力之外，再补一套 session protocol algebra，用于描述消息之间的时间关系。

最早考虑的原语大致是：

```text
Send<T>
Recv<T>

Seq<A, B>

Choose<A, B>
Offer<A, B>

Loop<A>

Close
```

它们可以组合出常见 RPC：

```text
Unary

Server Streaming

Client Streaming

Bidirectional Streaming
```

也可以表达最初真正驱动 CueFlow 的场景：

```text
先发送一次 Context

之后：
    持续发送 Query
    持续接收 Result

最后关闭 Session
```

这套设计是成立的。

但继续讨论以后，一个更基本的问题逐渐显现：

> 这些 protocol algebra 原语究竟在描述什么？

答案最终都是：

> 状态和状态之间允许发生哪些 transition。

于是原本的设计：

```text
Protocol Algebra
      ↓
      FSM
```

开始显得多了一层。

既然最终语义本来就是有限状态机，那么没有必要先设计一套抽象语言，再把它编译回真正的语义模型。

CueFlow 因此做出第一次重要收缩：

> **回到状态机本身。**

---

## 2. 为什么放弃 Protocol Algebra 作为核心模型

问题最早暴露在：

```text
Choose
Offer
```

这一对原语上。

它们来自 session type 中常见的 branch semantics：

```text
Select
    当前端决定 branch

Branch
    对端决定 branch
```

这个语义本身没有问题。

但我们最初曾尝试用：

```text
Choose(
    Send<Query>,
    Recv<Result>,
)
```

表示一个双向 session：

```text
客户端可以发送 Query

服务器可以返回 Result
```

继续分析以后发现，这根本不是一个 branch。

因为：

```text
Send<Query>
```

和：

```text
Recv<Result>
```

并不是：

```text
A XOR B
```

它们只是同一个状态上允许发生的两种 transition。

例如：

```text
Ready
  --send Query----> Ready
  --recv Result---> Ready
```

既不需要：

```text
Choose
```

也不需要：

```text
Offer
```

更不需要再发明：

```text
Duplex
```

FSM 已经直接表达了事实本身。

类似地：

```text
Seq
Loop
Select
Branch
```

也都只是状态机拓扑的不同形状。

### Seq

```text
A --send X--> B --recv Y--> C
```

### Loop

```text
A --recv Event--> A
```

### Select

```text
A
├── send Foo --> B
└── send Bar --> C
```

### Branch

```text
A
├── recv Foo --> B
└── recv Bar --> C
```

因此它们可以作为未来的人类书写语法糖，但不应该成为 CueFlow 的 canonical semantic model。

---

## 3. 当前核心模型：Typed FSM

CueFlow 当前准备把协议直接定义为一个 typed finite-state machine。

核心只需要：

```text
Protocol

State

Transition

Initial State

Terminal State
```

Transition 只允许三种通信行为：

```text
Send<T>

Recv<T>

Close
```

概念上的 canonical IR 可以接近：

```text
Protocol {
    initial: StateId
    states: [...]
}

State {
    id: StateId
    transitions: [...]
}

Transition {
    event:
        Send<TypeId>
      | Recv<TypeId>
      | Close

    next: StateId
}
```

没有：

```text
if
guard
counter
variable
assignment
function
```

Protocol 描述的是一个有限的通信状态空间，而不是程序执行环境。

---

## 4. 原始 motivating example

最初促使我们考虑 CueFlow 的需求，是 gRPC bidi streaming 无法直接表达 Session 初始化阶段。

使用 gRPC/Proto 时，通常只能写成：

```text
ClientFrame =
    Context
  | Query
```

然后约定：

```text
第一帧必须是 Context

Context 只能出现一次

Context 在整个 Session 生命周期有效

Context 之后才能发送 Query
```

这些规则最终落入：

```text
oneof

注释

context_seen

if first_frame

runtime error
```

CueFlow 希望直接写出真正的状态机：

```text
Start
  --send Context--> Ready

Ready
  --send Query----> Ready
  --recv Result---> Ready
  --close---------> End
```

它已经完整表达：

```text
Context 必须先出现

Context 只能在 Start 状态出现

Query 只能在 Ready 状态出现

Result 只能在 Ready 状态出现

Ready 可以持续双向交互

Session 最终可以关闭
```

不需要任何额外隐含规则。

---

## 5. 为什么停在 FSM，而不是 EFSM

讨论过程中自然出现了另一个问题。

例如希望保证：

```text
每发送一个 Query
必须最终对应一个 Result
```

并允许：

```text
send Q1
send Q2
recv R1
recv R2
```

那么系统需要记住：

```text
pending_queries
```

进一步可能需要：

```text
pending += 1

pending -= 1

pending > 0
```

这会把 FSM 扩展成：

```text
Extended Finite State Machine
```

即：

```text
State
+
Variables
+
Guards
+
Updates
```

这个方向理论上当然可以继续。

但 CueFlow 当前明确不准备这么做。

原因不是 EFSM 不够强，而恰恰是它太强。

一旦协议语言拥有：

```text
mutable state

arithmetic

guards

collections

data-dependent transitions
```

就会自然继续出现：

```text
expression

function

branch

iteration

error handling
```

CueFlow 会逐渐从协议描述语言变成一门受限编程语言。

这不是当前目标。

---

## 6. 协议语言的边界

CueFlow 当前采用一个非常简单的判断原则：

> **如果一个规则只需要根据“当前 protocol state + 下一条消息的方向与类型”判断，它属于 CueFlow。**

例如：

```text
Context 只能作为第一条消息
```

属于 CueFlow。

```text
Success 和 Failure 导向不同状态
```

也属于 CueFlow，只要二者是不同的消息类型。

例如：

```text
Waiting
  --recv Success--> Ready
  --recv Failure--> Failed
```

---

如果一个规则必须读取：

```text
历史消息内容

无界计数

业务字段

数据库状态

时间

外部系统

动态集合
```

它就不属于 CueFlow 核心。

例如：

```text
Result.query_id
必须对应此前某个 Query.id
```

需要维护：

```text
outstanding_query_ids
```

这是 application semantics。

CueFlow 不负责证明它。

---

## 7. CUE、FSM、Application 的职责分离

当前最重要的设计边界是：

```text
CUE
    定义值是否合法

FSM
    定义消息何时合法

Application
    定义消息之间的业务关系是否合法
```

例如：

```cue
#Query: {
    id: string & != ""

    sequence: string & =~"^[ACGT]+$"

    topK: int & >=1 & <=100
}
```

CUE 保证的是：

```text
这一个 Query 本身合法
```

FSM：

```text
Ready --send Query--> Ready
```

保证的是：

```text
这个 Query 现在可以发送
```

Application 再负责：

```text
Result.id 是否对应某个 Query.id

Query 是否具有业务权限

Result 是否满足业务不变量
```

因此：

```text
CueFlow
=
CUE Value Constraints
+
Typed FSM
```

到这里停止。

---

## 8. Regular Protocol Only

从形式上说，CueFlow 当前刻意只描述 regular temporal language。

事件 alphabet 可以理解为：

```text
send<T>

recv<T>

close
```

协议定义：

```text
哪些有限事件序列是合法的
```

即：

```text
L(P) ⊆ Σ*
```

FSM 能完整表示这类 regular protocol。

CueFlow 当前不试图表达：

```text
任意深度嵌套

无界 counter

跨消息数据依赖

任意 guard

任意 computation
```

这种有限表达能力不是缺陷。

它是刻意保留的边界。

> **CueFlow intentionally describes regular communication protocols only.**

如果一个协议确实需要超出这个范围，那么相关逻辑应该进入应用代码，或者未来由一个明确独立的更高层系统处理，而不是不断扩大 CueFlow 核心。

---

## 9. Dual 也因此变得简单

在 Typed FSM 模型下，client/server dual 不再需要复杂的 algebra rewrite。

只需要：

```text
dual(send<T>) = recv<T>

dual(recv<T>) = send<T>
```

状态图本身保持不变。

例如客户端：

```text
Start
  --send Context--> Ready

Ready
  --send Query----> Ready
  --recv Result---> Ready
```

服务器自动得到：

```text
Start
  --recv Context--> Ready

Ready
  --recv Query----> Ready
  --send Result---> Ready
```

因此：

```text
Select ↔ Branch
```

也不再需要作为特殊规则存在。

如果某状态拥有：

```text
多个 send transition
```

自然意味着当前端选择。

如果拥有：

```text
多个 recv transition
```

自然意味着远端选择。

语义直接来自状态图。

---

## 10. Rust Typestate 仍然成立

放弃 protocol algebra 并不会损失 Rust typestate。

反而会更直接。

假设：

```text
Start
Ready
End
```

生成：

```rust
Session<Start>
Session<Ready>
Session<End>
```

如果：

```text
Start
  --send Context--> Ready
```

则生成的 Start API 只暴露：

```rust
send_context(...)
```

返回：

```rust
Session<Ready>
```

Ready 状态拥有：

```text
send Query

recv Result

close
```

那么：

```rust
Session<Ready>
```

只需要暴露对应操作。

生成 API 的依据不再是一套额外 protocol algebra。

它直接来自 FSM。

因此：

```text
Protocol FSM
      ↓
Typestate API
```

而不是：

```text
Protocol Algebra
      ↓
FSM
      ↓
Typestate API
```

少了一层无必要的抽象。

---

## 11. 对现有工作的重新认识

进一步检索后确认：

CueFlow 的核心理论并不新。

需要明确参考并学习已有的：

```text
Session Types

Communicating Finite State Machines

Behavioural Types

Typestate
```

以及相应工具与研究实现。

当前重点参考对象包括：

```text
Scribble

StMungo

Dialectic

Ferrite

Session Type Provider

Telltale

Rumpsteak / Rumpsteak Aura
```

这些项目已经分别探索过：

```text
global/local protocol

protocol projection

CFSM

duality

branch semantics

typestate generation

Rust session types

compile-time protocol checking

multiparty session types

refinement / value-dependent protocol
```

CueFlow 没有必要重新证明这些理论。

---

## 12. Scribble：重要的理论参考

Scribble 是当前最重要的参考对象之一。

它将 protocol 描述为角色之间的通信关系，并可以：

```text
Global Protocol
      ↓
Projection
      ↓
Local Protocol
      ↓
State Machine
```

进一步生成 endpoint API。

CueFlow 可以直接学习其中：

```text
protocol well-formedness

projection semantics

branch consistency

message sequencing

FSM construction
```

但 CueFlow 第一阶段不准备复制 Scribble 的完整目标。

尤其不准备一开始处理：

```text
Multiparty Session Types

Global Choreography

N-role Projection
```

CueFlow 当前仍然主要解决：

```text
Endpoint A ↔ Endpoint B
```

即一个更接近 RPC 的双端协议问题。

---

## 13. StMungo：Typestate 的直接参考

StMungo 已经实践了：

```text
Protocol
↓
State Machine
↓
State-specific API
```

这和 CueFlow 希望为 Rust 生成：

```rust
Session<State>
```

的思想高度一致。

因此 typestate codegen 不应被视为 CueFlow 的理论创新。

CueFlow 应直接吸收其中已经解决的问题，例如：

```text
状态 API 如何生成

branch 后类型如何变化

循环如何映射到类型

如何避免用户越过协议状态
```

---

## 14. Dialectic / Ferrite：Rust 实现参考

Dialectic 和 Ferrite 证明了 Rust 类型系统确实非常适合表达 session types。

它们对于：

```text
Send

Recv

Choice

Offer

Loop

linear usage

async transport
```

已经有大量工程实践。

CueFlow 与它们最大的不同，不应该是重新设计一套更聪明的 Rust session calculus。

CueFlow 更关注：

```text
CUE-first authoring

explicit FSM

language-neutral IR

multi-language codegen

wire codec

RPC replacement experience
```

因此 Rust backend 可以大量参考已有工作，而不应把项目重心变成新的 Rust 类型体操。

---

## 15. Multiparty Protocol 暂时不进入范围

检索过程中也重新认识了 MPST。

Multiparty Session Types 解决的是：

```text
A

B

C

D
```

多个 role 共同构成一个 global protocol 时，如何保证：

```text
局部协议能够一致投影

branch 信息能传播

多个 bilateral session 组合后不会产生错误的全局行为
```

例如：

```text
Buyer
Seller
Payment
```

或：

```text
Coordinator
Database A
Database B
```

这类系统确实存在真实价值。

但 CueFlow 最初的问题并不是这个。

CueFlow 最初只是希望：

> 一个 RPC stream 能不能准确描述自己的 Session FSM？

因此第一阶段明确保持：

```text
two-party local protocol
```

如果未来实际业务产生 multiparty requirement，再基于已有 MPST 理论扩展。

不为了理论完整性提前增加复杂度。

---

## 16. CueFlow 当前不主张理论原创

这次检索以后，一个重要认识是：

> CueFlow 不应该把 Session Type、CFSM、Duality 或 Typestate 当作自己的原创概念。

这些都有成熟理论和既有实现。

CueFlow 真正值得探索的是工程组合：

```text
CUE
  +
Typed FSM
  +
Canonical IR
  +
Generated Endpoint API
  +
Generated Codec
```

目标是做一个工程师愿意实际拿来替代 Proto/gRPC IDL 的工具。

因此 CueFlow 的定位从：

```text
新的 Session Protocol Type System
```

调整为：

> **CUE-native interface compiler for typed finite-state communication protocols.**

中文：

> **CueFlow 是一个以 CUE 描述数据约束、以有限状态机描述通信时序的接口编译器。**

---

## 17. CueFlow 真正想解决的仍然没有消失

现有工具已经很好地解决：

```text
Session Types

CFSM

Typestate

Protocol Projection
```

但目前没有发现一个成熟工具完整对应以下组合：

```text
CUE 作为主要数据 schema

显式 FSM 作为主要时序 schema

同一个 language-neutral IR

自动生成 client/server endpoint

自动生成 wire codec

面向多语言

把产品定位为 RPC/IDL 工具
```

因此 CueFlow 当前仍然有探索价值。

不是因为：

```text
没人知道状态机可以描述协议
```

而是因为：

```text
现有 RPC 工具没有把这些能力整理成我们想要的工程接口
```

---

## 18. 实现哲学

经过这次讨论，CueFlow 当前的实现哲学进一步收紧。

### 18.1 回到最直接的模型

如果状态机已经能完整表达，就直接写状态机。

不要为了抽象而增加：

```text
Seq

Loop

Choose

Offer

Duplex
```

如果以后发现这些语法糖确实改善可读性，可以在 frontend 层增加。

Canonical IR 永远保持 FSM。

---

### 18.2 不重新发明已经成熟的理论

对于：

```text
duality

branching

FSM determinism

protocol well-formedness

typestate generation

async session semantics
```

优先研究和复用已有工作。

目标是少踩坑，而不是重新证明一次。

---

### 18.3 不让 Protocol 变成 Programming Language

CueFlow 不拥有：

```text
变量

函数

任意 guard

业务表达式

副作用

外部状态
```

一旦某项需求需要这些能力，就默认它已经越过协议描述边界。

---

### 18.4 具有协议意义的差异必须类型化

不要写：

```text
recv Response

if response.status == "success" ...
```

如果：

```text
success

failure
```

会导致协议进入不同状态，那么它们应该成为不同的 message variant：

```text
recv Success -> Ready

recv Failure -> Failed
```

协议状态只根据：

```text
message type/tag
```

变化，不根据任意 payload predicate 变化。

---

### 18.5 CUE 负责值，不负责时间

不要试图利用 CUE unification 本身表达消息顺序。

CUE 擅长：

```text
这个值属于什么集合
```

FSM 擅长：

```text
这个事件在当前状态是否允许
```

二者保持正交。

---

### 18.6 Wire Format 保持无聊

CueFlow 的创新重点不在：

```text
比 Protobuf 少几个 bit
```

而在：

```text
协议表达

约束

状态

codegen
```

Wire codec 应优先：

```text
简单

canonical

deterministic

容易多语言实现

容易 fuzz

容易生成 golden vectors
```

---

### 18.7 Compiler 比 Runtime 更聪明

能在生成阶段完成的事情：

```text
FSM validation

duality

unreachable-state detection

ambiguous transition detection

schema validation

code generation
```

都不要拖到 runtime。

Runtime 应尽量只做：

```text
frame decode

current-state validation

transport

state transition
```

---

### 18.8 能静态保证就静态保证，不能就明确不保证

Rust 等语言可以生成：

```text
Session<State>
```

尽量做到 L3 static session safety。

Python 等语言可能只能做到：

```text
runtime FSM
+
type hints
```

不为了 API 表面统一而降低所有语言到最弱公共能力。

也不为了模拟 Rust 的静态能力，在动态语言里制造复杂且难用的 API。

---

### 18.9 两端协议只定义一次

用户定义一个 local protocol。

另一端通过：

```text
dual
```

自动生成。

禁止 client/server 分别维护两份人工 schema。

---

### 18.10 优先做 RPC，而不是做完整通信理论

CueFlow 当前不是：

```text
distributed choreography framework

formal verification platform

workflow language

actor language

general process calculus
```

CueFlow 首先是：

> **一个更好的 RPC 协议描述语言和接口编译器。**

如果未来真实使用过程中自然长出更大的需求，再扩展。

---

## 19. 当前最小模型

经过 Diary 0002 的收缩后，核心模型可以重新写成：

```text
CUE
│
├── Message Types
└── Value Constraints

        +

Typed FSM
│
├── State
├── Initial
└── Transition
      ├── Send<T>
      ├── Recv<T>
      └── Close

        ↓

Canonical IR

        ↓

┌─────────────┬─────────────┐
│             │             │
Rust          Go            TypeScript ...
│
Typestate where possible

        +

Canonical Wire Codec
```

相比 Diary 0001，这套模型更小。

但表达能力并没有因为删除 protocol algebra 而损失。

---

## 20. 当前原则

CueFlow 当前的原则可以压缩成：

```text
CUE 定义值

FSM 定义时序

代码定义业务

状态机是协议的 canonical form

只描述 regular protocol

不引入 protocol mutable state

不引入 arbitrary guard

不重新发明 Session Type 理论

从已有 CFSM / Typestate 工作中学习

双端优先

Multiparty 延后

Compiler 尽量聪明

Runtime 尽量无聊

Wire 尽量机械

Protocol 只定义一次

另一端通过 Dual 派生
```

最终可以再压缩成四句话：

> **CUE defines values.**
>
> **FSM defines order.**
>
> **Compiler generates endpoints.**
> **Runtime moves bytes.**

这是目前 CueFlow 最接近本质的一次定义。
