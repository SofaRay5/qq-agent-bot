# QQ 机器人工程化设计文档

**基于 LangChain (1.0) + OneBot v11 协议**

---

> 本文档基于对 [langchain-ai/langchain](https://github.com/langchain-ai/langchain) 和 [botuniverse/onebot](https://github.com/botuniverse/onebot) 现状的核实编写。核心结论：go-cqhttp 已停止维护，QQ 接入改用 NapCat；LangChain 已进入 1.0 正式版，Agent 编排统一使用 `create_agent()` + LangGraph 运行时。

---

# 01. 项目概览与技术选型

## 1.1 项目目标

构建一个**工程化、可维护、可扩展**的 QQ 智能机器人，核心诉求：

- 用 **OneBot 协议** 作为 QQ 接入的标准化接口层，不与具体 QQ 实现（NapCat/Lagrange/LLOneBot）耦合
- 用 **LangChain（1.0 + LangGraph 运行时）** 作为 Agent 编排层，获得工具调用、记忆持久化、可观测性
- 明确分层，各层单一职责，方便后续替换任意一层（换 QQ 实现、换 LLM 提供商、换存储）

## 1.2 技术选型说明（含现状核实）

### OneBot 协议

OneBot 是一套**聊天机器人应用接口标准**（不是某个具体项目），目前有 v11 / v12 两个版本共存：

| 版本 | 特点 | 适用场景 |
|---|---|---|
| **OneBot v11**（前身 CQHTTP） | 生态最成熟，消息用 CQ 码或数组表示，QQ 生态几乎都用这个 | **本项目采用** |
| OneBot v12 | 更规范的消息段格式、跨平台类型系统，是下一代标准 | 未来可迁移，暂不是QQ生态主流 |

**重要现状**：`go-cqhttp`（老牌 OneBot v11 QQ 实现）**已停止维护**，社区已迁移至基于无头 QQNT（QQ官方客户端内核）的新方案：

| 实现 | 说明 | 推荐度 |
|---|---|---|
| **NapCat** | 无头运行（无图形界面），适合 Linux 服务器部署，Docker 友好 | ⭐ **推荐，本项目采用** |
| LLOneBot | 需要图形界面 QQNT 客户端配合插件运行，适合 Windows 桌面 | 备选（桌面场景） |
| Lagrange.OneBot | 独立实现协议，非官方客户端内核 | 备选 |
| ~~go-cqhttp~~ | 已停止维护，QQ 风控后无法稳定登录 | ❌ 不建议新项目使用 |

本项目的 QQ 接入层**只对接 OneBot v11 协议本身**（HTTP / 正向WS / 反向WS），不关心底层具体是 NapCat 还是 Lagrange —— 这正是采用标准协议的意义：协议实现可以随时替换，机器人业务代码不需要改。

### LangChain

LangChain 1.0（2025年10月GA）的关键变化，直接影响本项目架构：

- **Agent 现在跑在 LangGraph 运行时之上**，`create_agent()` 是新的标准入口，取代旧的 `AgentExecutor`（后者进入维护模式，2026年12月停止支持）
- 内置**状态持久化（checkpointer）**，天然支持多轮对话记忆、断点续聊
- **中间件（middleware）机制**替代了旧版复杂的回调堆叠，用于做工具调用前后的拦截（比如敏感词过滤、限流）
- 生态上有 1000+ 模型/工具集成，模型提供商可自由切换（Claude / OpenAI / Gemini / 本地模型）

本项目用 LangChain 承担：**对话编排、工具调用（function calling）、短期记忆状态管理**；不用它做 QQ 消息收发（那是 OneBot 适配层的职责）。

## 1.3 架构总览

```
┌───────────────────────────────────────────────────────────┐
│                         QQ 客户端                            │
└───────────────────────────┬───────────────────────────────┘
                            │ QQNT 协议（私有）
┌───────────────────────────▼───────────────────────────────┐
│         NapCat（OneBot v11 协议实现端，无头QQNT）             │
│         暴露: HTTP API / 正向WS / 反向WS                     │
└───────────────────────────┬───────────────────────────────┘
                            │ OneBot v11 协议（标准化 JSON）
┌───────────────────────────▼───────────────────────────────┐
│                    本项目：机器人主体                          │
│  ┌─────────────────────────────────────────────────────┐  │
│  │  adapter 层 (onebot_adapter/)                        │  │
│  │  - OneBot v11 客户端：连接/心跳/断线重连               │  │
│  │  - 事件解析：message/notice/request/meta_event       │  │
│  │  - 消息段编解码：text/at/image/reply...               │  │
│  └───────────────────────┬─────────────────────────────┘  │
│                          │ 内部统一事件格式                    │
│  ┌───────────────────────▼─────────────────────────────┐  │
│  │  core 层 (core/)                                     │  │
│  │  - 事件路由 / 中间件管道（限流、权限、敏感词）           │  │
│  │  - 会话管理（按 user_id + group_id 建会话）             │  │
│  └───────────────────────┬─────────────────────────────┘  │
│                          │                                  │
│  ┌───────────────────────▼─────────────────────────────┐  │
│  │  agent 层 (agent/) —— LangChain / LangGraph          │  │
│  │  - create_agent() 主循环                              │  │
│  │  - 工具集：搜索/查询/自定义业务工具                     │  │
│  │  - Checkpointer：短期记忆持久化                        │  │
│  └───────────────────────┬─────────────────────────────┘  │
│                          │                                  │
│  ┌───────────────────────▼─────────────────────────────┐  │
│  │  memory 层 (memory/)                                 │  │
│  │  - 短期记忆：LangGraph checkpointer (Redis/SQLite)     │  │
│  │  - 长期记忆：用户画像 + 向量库（可选 RAG）              │  │
│  └───────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

## 1.4 技术栈清单

| 层 | 技术 | 用途 |
|---|---|---|
| QQ 实现端 | NapCat (Docker) | 登录 QQ、暴露 OneBot v11 接口 |
| 协议层 | OneBot v11（自实现轻量客户端） | 标准化消息收发 |
| Web 框架 | FastAPI | 接收反向WS/HTTP上报（可选，若用正向WS则不需要） |
| Agent 框架 | LangChain 1.0 + LangGraph | 对话编排、工具调用、状态机 |
| LLM | 可插拔（Claude/OpenAI/Gemini via LangChain 集成包） | 生成回复 |
| 短期记忆存储 | LangGraph Checkpointer（SQLite/Redis 后端） | 会话状态持久化 |
| 长期记忆存储 | SQLite/PostgreSQL | 用户画像、关键事件 |
| 向量库（可选） | Chroma/FAISS | 长期语义记忆检索（RAG） |
| 部署 | Docker Compose | NapCat + 机器人主体 + 数据库 一键起 |

下一节详细拆解各层的接口设计。
-e 

---


# 02. OneBot 适配层设计

## 2.1 连接方式选择

OneBot v11 支持三种通信方式，三选一（或多个并存）：

| 方式 | 谁发起连接 | 特点 | 本项目建议 |
|---|---|---|---|
| HTTP | 机器人主动轮询/NapCat 主动 POST 上报 | 简单，但实时性依赖 webhook | 可用于低频场景 |
| **正向 WebSocket** | 机器人主动连接 NapCat 的 WS 端口 | 机器人是客户端，NapCat 是服务端，**机器人重启不影响 NapCat** | ⭐ **推荐，本项目采用** |
| 反向 WebSocket | NapCat 主动连接机器人暴露的 WS 端口 | 机器人要先起服务，NapCat 后连；机器人重启会断线 | 备选 |

选正向 WS 的原因：机器人是消费方，天然应该是主动连接协议服务端的一方，重连逻辑也更容易控制（机器人自己管理重连策略）。

## 2.2 NapCat 侧配置（部署前提）

```yaml
# napcat 的 onebot11 配置片段（websocket 服务端模式）
network:
  websocketServers:
    - name: "ws-server"
      enable: true
      host: "0.0.0.0"
      port: 3001
      messagePostFormat: "array"   # 消息用数组格式而非CQ码字符串，方便解析
      reportSelfMessage: false
      token: "你的access_token"    # 鉴权，务必设置
      enableForcePushEvent: true
      debug: false
```

机器人连接地址：`ws://<napcat_host>:3001?access_token=你的access_token`

## 2.3 OneBot v11 核心数据结构

### 事件（上报，NapCat → 机器人）

四种基础事件类型，都有公共字段 `post_type`：

```json
{
  "post_type": "message",      // message | notice | request | meta_event
  "time": 1717600000,
  "self_id": 123456789
}
```

**消息事件（message）**是本项目主要处理对象：

```json
{
  "post_type": "message",
  "message_type": "group",      // group | private
  "sub_type": "normal",
  "message_id": 123,
  "group_id": 987654321,        // 仅群消息有
  "user_id": 111222333,
  "message": [                  // 数组格式（推荐，而非CQ码字符串）
    {"type": "at", "data": {"qq": "123456789"}},
    {"type": "text", "data": {"text": " 你好"}}
  ],
  "raw_message": "[CQ:at,qq=123456789] 你好",
  "sender": {
    "user_id": 111222333,
    "nickname": "小明",
    "card": "群名片"             // 群里的备注名，优先于nickname使用
  }
}
```

### 动作（请求，机器人 → NapCat）

调用格式统一：

```json
{
  "action": "send_group_msg",
  "params": {
    "group_id": 987654321,
    "message": [
      {"type": "text", "data": {"text": "回复内容"}}
    ]
  },
  "echo": "唯一请求ID"   // 用于WS模式下匹配请求和响应
}
```

常用 action 清单：

| action | 用途 |
|---|---|
| `send_group_msg` / `send_private_msg` | 发送消息 |
| `delete_msg` | 撤回消息 |
| `get_group_member_info` | 查群成员信息（用于画像补充） |
| `set_group_ban` | 禁言（管理功能） |
| `get_login_info` | 获取机器人自身QQ信息 |

## 2.4 适配层代码结构

```
onebot_adapter/
├── __init__.py
├── client.py          # WebSocket连接、心跳、断线重连
├── event.py            # 事件数据模型（Pydantic），对应上面的JSON结构
├── action.py            # 动作封装（send_group_msg等的Python方法）
├── message.py           # 消息段编解码：数组 ⇄ 内部统一格式
└── router.py             # 事件分发器：按post_type/message_type分发给core层
```

### client.py 核心逻辑（伪代码级设计，非最终实现）

```python
class OneBotClient:
    """
    职责单一：只管WS连接的生命周期和收发JSON，
    不掺杂任何业务逻辑（不解析业务含义、不调用LLM）
    """
    def __init__(self, ws_url: str, access_token: str):
        self.ws_url = ws_url
        self.access_token = access_token
        self._pending_echo: dict[str, asyncio.Future] = {}  # echo -> Future，用于匹配响应
        self._event_handlers: list[Callable] = []

    async def connect(self):
        # 建立WS连接，带指数退避的重连策略
        ...

    async def call_action(self, action: str, params: dict, timeout: float = 10) -> dict:
        # 生成echo，发送请求，await对应Future直到收到响应或超时
        ...

    def on_event(self, handler: Callable):
        # 注册事件回调（由router.py注册）
        self._event_handlers.append(handler)

    async def _listen_loop(self):
        # 持续接收WS消息：
        #   如果带echo字段 -> 是动作响应，resolve对应Future
        #   否则 -> 是事件上报，分发给_event_handlers
        ...
```

### message.py：消息段与业务层解耦

上报的消息是 OneBot 数组格式，但 agent 层（LangChain）需要的是**纯文本 + 结构化附件信息**，两者要做转换：

```python
@dataclass
class UnifiedMessage:
    """内部统一消息格式，屏蔽OneBot细节，供core/agent层使用"""
    text: str                      # 纯文本部分（供LLM）
    mentions: list[str]            # 被@的QQ号列表
    images: list[str]              # 图片URL列表
    reply_to: str | None           # 引用回复的消息ID
    raw_segments: list[dict]       # 保留原始段，供需要还原格式的场景使用

def onebot_to_unified(segments: list[dict]) -> UnifiedMessage:
    """OneBot消息段数组 -> 内部统一格式"""
    ...

def unified_to_onebot(text: str, at_list: list[str] = None) -> list[dict]:
    """内部格式 -> OneBot消息段数组（用于发送）"""
    ...
```

这一层转换的意义：**agent 层完全不知道 OneBot 协议的存在**，未来即使换成 Telegram/Discord 接入，只需要新写一个 `xxx_to_unified` 转换器，agent 层代码零改动。

## 2.5 长消息与限流处理

QQ 单条消息有长度限制（约 4500 字节，实际建议按 700-1000 汉字分段更保险），且频繁发送会触发风控：

```python
class MessageSender:
    MAX_LENGTH = 600          # 保守值，避免风控和截断
    MIN_INTERVAL = 1.2        # 秒，同一会话最小发送间隔

    async def send(self, target: SendTarget, text: str):
        chunks = self._split(text, self.MAX_LENGTH)
        for chunk in chunks:
            await self._rate_limited_send(target, chunk)
            await asyncio.sleep(self.MIN_INTERVAL)
```

## 2.6 断线重连与幂等性

- WS 断线后用**指数退避**重连（1s → 2s → 4s → ... 上限 30s）
- 重连后需要重新调用 `get_login_info` 确认账号状态
- `message_id` 去重：极端情况下 NapCat 可能重复上报同一事件，core 层用短期缓存（如最近500条 message_id 的 LRU）做幂等过滤
-e 

---


# 03. Agent 层设计（LangChain / LangGraph）

## 3.1 为什么用 `create_agent` 而不是手搓 Prompt 拼接

旧的做法（上一轮方案）：手动拼 system prompt + 消息列表 + 直接调 LLM API。这在功能少的时候没问题，但工程化项目要考虑：

- **工具调用**：机器人以后要查天气、查资料、执行业务逻辑，需要 function calling 的标准化管理
- **状态持久化**：多轮对话的中断恢复、跨进程重启的记忆保留
- **可观测性**：需要能追踪每一步 LLM 做了什么决策（尤其是多工具调用场景排错）
- **中间件拦截**：敏感词过滤、调用前限流，需要统一的插入点而不是散落在业务代码里

`create_agent()`（LangChain 1.0）把这些能力打包好了，底层跑在 LangGraph 状态机上，是目前官方推荐的标准写法（旧 `AgentExecutor` 已进入维护模式，2026年12月终止支持）。

## 3.2 Agent 层代码结构

```
agent/
├── __init__.py
├── builder.py          # create_agent() 的组装逻辑，注入模型/工具/中间件
├── tools/
│   ├── __init__.py
│   ├── search.py         # 示例工具：联网搜索
│   ├── profile_tool.py    # 示例工具：读写用户画像（对接memory层）
│   └── base.py             # 自定义工具的公共基类/装饰器封装
├── middleware/
│   ├── rate_limit.py       # 限流中间件
│   ├── content_filter.py    # 敏感词/越权拦截
│   └── logging.py            # 结构化日志中间件
├── checkpointer.py       # 短期记忆持久化后端配置（SQLite/Redis）
└── prompts.py            # 系统提示词模板（含用户画像占位符）
```

## 3.3 核心组装逻辑

```python
# agent/builder.py
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver

from .tools import search_tool, profile_tool
from .middleware import rate_limit_middleware, content_filter_middleware
from .prompts import build_system_prompt

def build_agent(model_name: str = "claude-sonnet-4-6"):
    checkpointer = SqliteSaver.from_conn_string("agent_state.db")

    agent = create_agent(
        model=model_name,                       # LangChain模型集成包自动路由到对应provider
        tools=[search_tool, profile_tool],
        middleware=[
            rate_limit_middleware,
            content_filter_middleware,
        ],
        checkpointer=checkpointer,               # 状态持久化，断点续聊
        system_prompt=build_system_prompt,       # 可以是callable，动态注入用户画像
    )
    return agent
```

## 3.4 会话标识设计（thread_id）

LangGraph 用 `thread_id` 区分不同会话的状态，本项目的映射规则：

```python
def make_thread_id(message_type: str, user_id: str, group_id: str | None) -> str:
    """
    群聊：按 群+用户 隔离上下文（同一个人在不同群，机器人对话互不影响）
    私聊：按 用户 隔离
    """
    if message_type == "group":
        return f"group:{group_id}:user:{user_id}"
    return f"private:{user_id}"
```

这个设计决定了记忆的隔离粒度——群聊场景下，同一用户在群A和群B里跟机器人聊的内容**不共享短期上下文**，但中期/长期的用户画像（memory层，见04文档）是跨群共享的。

## 3.5 工具（Tools）设计规范

每个工具必须：
1. 有清晰的 docstring（LLM 靠这个决定何时调用该工具）
2. 输入输出用 Pydantic 定义 schema，而不是裸字符串
3. 异常要被捕获并返回友好的错误描述给 LLM，而不是抛出去中断整个 Agent 循环

```python
# agent/tools/profile_tool.py
from langchain.tools import tool
from pydantic import BaseModel, Field
from memory.user_profile import UserProfileStore

class GetProfileInput(BaseModel):
    user_id: str = Field(description="要查询的QQ用户ID")

@tool("get_user_profile", args_schema=GetProfileInput)
async def profile_tool(user_id: str) -> str:
    """
    查询指定用户的已知画像信息（昵称、兴趣、性格、历史重要事件）。
    在需要个性化回复、或用户问"你还记得我说过XX吗"这类问题时调用。
    """
    try:
        store = UserProfileStore()
        profile = await store.load(user_id)
        return profile.to_prompt_snippet()
    except Exception as e:
        return f"（画像查询暂时不可用：{e}）"
```

## 3.6 系统提示词的动态构建

系统提示词不是静态字符串，需要在每次调用时注入当前用户的画像摘要（这一步与 memory 层对接，见 04）：

```python
# agent/prompts.py
BASE_PROMPT = """你是一个友好、有记忆的QQ聊天机器人。

当前对话对象信息：
{user_context}

行为准则：
1. 若用户信息中有相关背景，自然地体现你"记得"这些事，不要机械复述
2. 不确定的信息不要编造，可调用工具查询
3. 保持简洁，QQ对话不适合长篇大论
"""

def build_system_prompt(state: dict) -> str:
    user_context = state.get("user_context_snippet", "（暂无背景信息）")
    return BASE_PROMPT.format(user_context=user_context)
```

## 3.7 中间件示例：限流

```python
# agent/middleware/rate_limit.py
from collections import defaultdict
import time

class RateLimiter:
    def __init__(self, max_calls: int = 5, window_seconds: int = 60):
        self.max_calls = max_calls
        self.window = window_seconds
        self._records: dict[str, list[float]] = defaultdict(list)

    def check(self, thread_id: str) -> bool:
        now = time.time()
        records = self._records[thread_id]
        records[:] = [t for t in records if now - t < self.window]
        if len(records) >= self.max_calls:
            return False
        records.append(now)
        return True

rate_limiter = RateLimiter()

async def rate_limit_middleware(state, next_step):
    thread_id = state["thread_id"]
    if not rate_limiter.check(thread_id):
        return {"messages": [("assistant", "你发消息太快啦，稍等一下～")]}
    return await next_step(state)
```

## 3.8 可观测性

生产环境建议接入 LangSmith（或自建日志），至少要记录：

- 每次调用的 thread_id、耗时、token 消耗
- 工具调用的名称、入参、返回值（脱敏后）
- 异常堆栈（LLM 超时、工具失败）

最小实现（不依赖LangSmith，自己落库）：

```python
# agent/middleware/logging.py
import logging, time

logger = logging.getLogger("agent")

async def logging_middleware(state, next_step):
    start = time.time()
    thread_id = state["thread_id"]
    try:
        result = await next_step(state)
        logger.info(f"thread={thread_id} elapsed={time.time()-start:.2f}s status=ok")
        return result
    except Exception as e:
        logger.error(f"thread={thread_id} elapsed={time.time()-start:.2f}s status=error err={e}")
        raise
```
-e 

---


# 04. 记忆层设计

## 4.1 记忆分层与对应技术

延续三层记忆思路，但这次每一层都用对应的工程化组件承载，而不是全部手写：

| 层级 | 内容 | 承载技术 | 生命周期 |
|---|---|---|---|
| 短期记忆 | 当前会话消息轮次 | **LangGraph Checkpointer**（agent层自带，见03文档） | 按 thread_id，可配置过期 |
| 中期记忆 | 用户画像：昵称/性格/兴趣/亲密度 | SQLite/PostgreSQL 结构化表 | 用户级，永久（可清理） |
| 长期记忆 | 关键事件、可语义检索的历史 | SQLite（事件表）+ 可选向量库（RAG） | 永久归档 |

**关键设计决策**：短期记忆不再手写 `ShortTermMemory` 类，直接复用 LangGraph 的 checkpointer——这是 LangChain 1.0 的核心卖点之一，没必要重复造轮子。中期/长期记忆是业务特定的（用户画像、亲密度这些不是通用 LLM 框架的职责），继续自己维护。

## 4.2 短期记忆：LangGraph Checkpointer

```python
# agent/checkpointer.py
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

async def get_checkpointer():
    async with AsyncSqliteSaver.from_conn_string("data/agent_state.db") as saver:
        yield saver
```

生产环境建议换成 Redis 后端（`langgraph-checkpoint-redis`），原因：
- SQLite 单文件写锁在高并发多用户场景下会成为瓶颈
- Redis 原生支持 TTL，短期记忆自动过期不需要额外写清理任务

```python
from langgraph.checkpoint.redis import AsyncRedisSaver

checkpointer = AsyncRedisSaver.from_conn_string("redis://localhost:6379")
```

## 4.3 中期记忆：用户画像

### 数据库表设计

```sql
-- 用户基本画像
CREATE TABLE user_profiles (
    user_id         TEXT PRIMARY KEY,
    nickname        TEXT,
    personality     TEXT,              -- 性格描述，自然语言短句
    interests       TEXT,              -- JSON数组
    intimacy_score  REAL DEFAULT 0,
    first_seen_at   TEXT,
    updated_at      TEXT
);

-- 聊天风格学习结果
CREATE TABLE user_styles (
    user_id             TEXT PRIMARY KEY,
    tone                TEXT,          -- 正式/随意/温暖等
    speech_patterns     TEXT,          -- JSON: 常用语气词、表情习惯等
    sample_count        INTEGER DEFAULT 0,
    FOREIGN KEY(user_id) REFERENCES user_profiles(user_id)
);

-- 关键事件（长期记忆的主体）
CREATE TABLE key_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    event_type   TEXT,                 -- told / inferred / important
    content      TEXT,
    importance   INTEGER,              -- 1-10
    embedding_id TEXT,                 -- 若启用向量库，关联的embedding记录ID
    created_at   TEXT,
    FOREIGN KEY(user_id) REFERENCES user_profiles(user_id)
);

CREATE INDEX idx_events_user ON key_events(user_id, importance DESC);
```

### 存取接口

```python
# memory/user_profile.py
from dataclasses import dataclass
import aiosqlite, json, datetime

@dataclass
class UserProfile:
    user_id: str
    nickname: str | None
    personality: str | None
    interests: list[str]
    intimacy_score: float

    def to_prompt_snippet(self) -> str:
        """转成可以直接塞进system prompt的自然语言片段"""
        parts = []
        if self.nickname:
            parts.append(f"昵称：{self.nickname}")
        if self.personality:
            parts.append(f"性格：{self.personality}")
        if self.interests:
            parts.append(f"兴趣：{', '.join(self.interests)}")
        parts.append(f"亲密度：{self.intimacy_score:.1f}/10")
        return "；".join(parts)

class UserProfileStore:
    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = db_path

    async def load(self, user_id: str) -> UserProfile:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row is None:
                return UserProfile(user_id, None, None, [], 0.0)
            return UserProfile(
                user_id=row["user_id"],
                nickname=row["nickname"],
                personality=row["personality"],
                interests=json.loads(row["interests"] or "[]"),
                intimacy_score=row["intimacy_score"],
            )

    async def upsert(self, profile: UserProfile):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO user_profiles (user_id, nickname, personality, interests, intimacy_score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    nickname=excluded.nickname,
                    personality=excluded.personality,
                    interests=excluded.interests,
                    intimacy_score=excluded.intimacy_score,
                    updated_at=excluded.updated_at
            """, (
                profile.user_id, profile.nickname, profile.personality,
                json.dumps(profile.interests, ensure_ascii=False),
                profile.intimacy_score, datetime.datetime.now().isoformat()
            ))
            await db.commit()
```

## 4.4 记忆更新策略：谁来决定"记什么"

上一版方案用关键词硬编码（"工作"、"学校"…）判断是否记录事件，工程化项目应该**让 LLM 自己判断**，更准确也更容易扩展：

```python
# memory/extractor.py
"""
每轮对话后异步调用一次小模型（或复用同一个模型），
让它判断这轮对话是否包含值得记住的信息。
用结构化输出（Pydantic）保证格式稳定。
"""
from pydantic import BaseModel
from langchain_core.output_parsers import PydanticOutputParser

class ExtractedMemory(BaseModel):
    has_new_info: bool
    event_content: str | None = None
    importance: int = 0            # 1-10
    inferred_personality: str | None = None
    inferred_interest: str | None = None

async def extract_memory_from_turn(user_msg: str, bot_reply: str, llm) -> ExtractedMemory:
    parser = PydanticOutputParser(pydantic_object=ExtractedMemory)
    prompt = f"""分析以下对话轮次，判断是否有值得长期记住的用户信息。
用户: {user_msg}
机器人: {bot_reply}

{parser.get_format_instructions()}
"""
    raw = await llm.ainvoke(prompt)
    return parser.parse(raw.content)
```

**工程权衡**：这一步会增加一次额外的 LLM 调用（成本+延迟）。折中方案是**异步、非阻塞**执行——先把回复发给用户，记忆提取在后台任务里跑，不影响响应速度。

```python
# core层调用处
async def handle_message(...):
    reply = await agent.ainvoke(...)
    await sender.send(target, reply)                 # 先回复用户
    asyncio.create_task(update_memory(user_id, msg, reply))  # 后台异步更新记忆，不阻塞
```

## 4.5 长期记忆检索（可选：RAG）

当 `key_events` 积累到一定量后（比如单用户超过50条），线性拼接进 prompt 会让上下文过长。此时引入向量检索，只取语义相关的历史：

```python
# memory/vector_store.py
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

class LongTermMemoryIndex:
    def __init__(self, embedding_model, persist_dir="data/chroma"):
        self.store = Chroma(
            collection_name="user_events",
            embedding_function=embedding_model,
            persist_directory=persist_dir,
        )

    async def add_event(self, user_id: str, content: str, event_id: int):
        doc = Document(
            page_content=content,
            metadata={"user_id": user_id, "event_id": event_id},
        )
        await self.store.aadd_documents([doc])

    async def search_relevant(self, user_id: str, query: str, k: int = 3) -> list[str]:
        results = await self.store.asimilarity_search(
            query, k=k, filter={"user_id": user_id}
        )
        return [r.page_content for r in results]
```

**何时启用**：MVP 阶段（用户量少、单用户事件少）不需要，直接线性拼接最近N条事件即可。当事件表增长到影响 prompt 长度时再引入，避免过度工程化。

## 4.6 记忆写入的完整数据流

```
用户消息到达
   │
   ▼
Agent处理并生成回复（读取：checkpointer短期记忆 + user_profile中期记忆片段）
   │
   ▼
回复立即发送给用户 ← 不等待下面的步骤
   │
   ▼（后台异步任务）
extract_memory_from_turn() 用LLM判断本轮是否有新信息
   │
   ├─ 有 → 写入 key_events 表
   │        │
   │        └─ 若启用向量库 → 同步写入 LongTermMemoryIndex
   │
   └─ 更新 user_profiles.intimacy_score（简单规则：每轮+0.1，封顶10）
```
-e 

---


# 05. 项目结构、Core 层、部署与路线图

## 5.1 完整项目目录结构

```
qq-langchain-bot/
├── onebot_adapter/           # OneBot协议适配层（02文档）
│   ├── client.py
│   ├── event.py
│   ├── action.py
│   ├── message.py
│   └── router.py
│
├── core/                     # 业务编排层
│   ├── dispatcher.py          # 事件分发，串联 adapter → agent
│   ├── session.py              # thread_id生成、会话上下文组装
│   ├── middleware_pipeline.py   # 权限校验/黑白名单等（区别于agent层的LLM中间件）
│   └── sender.py                 # 长消息分段、限流发送（见02.5）
│
├── agent/                    # LangChain Agent层（03文档）
│   ├── builder.py
│   ├── tools/
│   ├── middleware/
│   ├── checkpointer.py
│   └── prompts.py
│
├── memory/                   # 记忆层（04文档）
│   ├── user_profile.py
│   ├── extractor.py
│   └── vector_store.py
│
├── config/
│   ├── settings.py            # Pydantic Settings，统一读取环境变量
│   └── logging_config.py
│
├── data/                      # 运行时数据（SQLite文件、Chroma持久化），.gitignore
│
├── tests/
│   ├── test_onebot_message_parse.py
│   ├── test_agent_tools.py
│   └── test_memory_store.py
│
├── scripts/
│   ├── init_db.py             # 建表脚本
│   └── backup_db.sh
│
├── docker-compose.yml         # NapCat + 机器人主体 + Redis
├── Dockerfile
├── pyproject.toml             # 用 uv/poetry 管理依赖
├── .env.example
└── main.py                    # 入口：启动adapter，注入router
```

## 5.2 Core 层：串联 adapter 与 agent

`core/dispatcher.py` 是真正把各层粘起来的地方：

```python
# core/dispatcher.py
from onebot_adapter.event import MessageEvent
from onebot_adapter.message import onebot_to_unified
from core.session import make_thread_id
from core.sender import MessageSender
from agent.builder import build_agent

class Dispatcher:
    def __init__(self):
        self.agent = build_agent()
        self.sender = MessageSender()

    async def handle_message_event(self, event: MessageEvent):
        # 1. 过滤：非文本/机器人自己发的消息 提前return
        if event.user_id == event.self_id:
            return

        # 2. 协议格式 -> 内部统一格式
        unified = onebot_to_unified(event.message)
        if not unified.text.strip():
            return

        # 3. 组装会话标识
        thread_id = make_thread_id(
            event.message_type, str(event.user_id),
            str(event.group_id) if event.group_id else None
        )

        # 4. 调用Agent（读取短期记忆 + 中期记忆片段，见04文档）
        result = await self.agent.ainvoke(
            {"messages": [("user", unified.text)]},
            config={"configurable": {"thread_id": thread_id}},
        )
        reply_text = result["messages"][-1].content

        # 5. 发送回复
        target = SendTarget.from_event(event)
        await self.sender.send(target, reply_text)

        # 6. 后台异步更新中/长期记忆（见04.4）
        asyncio.create_task(
            update_memory(str(event.user_id), unified.text, reply_text)
        )
```

## 5.3 配置管理

统一用 Pydantic Settings，避免散落的 `os.getenv`：

```python
# config/settings.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # OneBot
    onebot_ws_url: str = "ws://127.0.0.1:3001"
    onebot_access_token: str = ""

    # LLM
    llm_provider: str = "anthropic"        # anthropic / openai / google
    llm_model: str = "claude-sonnet-4-6"
    anthropic_api_key: str = ""

    # 存储
    sqlite_path: str = "data/memory.db"
    redis_url: str | None = None           # 为None时checkpointer退化用SQLite

    # 行为
    max_message_length: int = 600
    rate_limit_per_minute: int = 5

    class Config:
        env_file = ".env"

settings = Settings()
```

## 5.4 Docker Compose 部署

```yaml
# docker-compose.yml
version: "3.8"
services:
  napcat:
    image: mlikiowa/napcat-docker:latest
    container_name: napcat
    environment:
      - NAPCAT_UID=1000
      - NAPCAT_GID=1000
    ports:
      - "6099:6099"    # WebUI，首次登录扫码用
      - "3001:3001"    # OneBot v11 WebSocket
    volumes:
      - ./napcat_data:/app/napcat/config
    restart: always

  redis:
    image: redis:7-alpine
    restart: always
    volumes:
      - ./redis_data:/data

  bot:
    build: .
    depends_on:
      - napcat
      - redis
    environment:
      - ONEBOT_WS_URL=ws://napcat:3001
      - REDIS_URL=redis://redis:6379
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    restart: always
```

首次部署步骤：

```bash
# 1. 启动NapCat，浏览器打开 http://<host>:6099/webui 扫码登录QQ
docker compose up -d napcat

# 2. 确认NapCat已上线后，启动机器人主体
docker compose up -d bot redis

# 3. 查看日志确认WS连接成功
docker compose logs -f bot
```

## 5.5 开发路线图

### Phase 1：协议与骨架打通（第1周）

- [ ] `onebot_adapter`：WS连接、心跳、事件解析、消息段编解码
- [ ] 最小 `core/dispatcher`：收到消息原样回复"收到"，验证链路通畅
- [ ] Docker Compose 起 NapCat，本地跑通"发消息→机器人有响应"

### Phase 2：Agent 接入（第2周）

- [ ] `agent/builder`：`create_agent` 最小可用版本，不带工具
- [ ] system prompt 静态版本（暂不接用户画像）
- [ ] checkpointer 用 SQLite 打通多轮对话

### Phase 3：记忆系统（第2-3周）

- [ ] `memory/user_profile`：建表、存取接口
- [ ] `memory/extractor`：LLM 判断式记忆提取，异步写入
- [ ] system prompt 动态注入用户画像
- [ ] 亲密度递增逻辑

### Phase 4：工具与中间件（第3-4周，可选深化）

- [ ] 至少1个实用工具（如联网搜索或业务查询）
- [ ] 限流中间件、敏感词中间件
- [ ] 结构化日志/可观测性

### Phase 5：加固与可选扩展

- [ ] 向量库长期记忆检索（仅在数据量增长后需要）
- [ ] Redis 替换 SQLite checkpointer（并发场景）
- [ ] 管理端（查看用户画像、手动调整亲密度等）

## 5.6 测试策略

| 测试类型 | 覆盖内容 | 工具 |
|---|---|---|
| 单元测试 | 消息段编解码、thread_id生成规则、画像存取 | pytest |
| 集成测试 | Agent + Checkpointer 多轮对话状态是否正确保留 | pytest + 内存SQLite |
| 协议契约测试 | 构造标准OneBot事件JSON，断言adapter解析结果 | pytest，固定fixture数据 |
| 手动验收 | 真实QQ环境下多轮对话、群聊/私聊隔离验证 | 人工 |

## 5.7 关键风险点

| 风险 | 说明 | 缓解措施 |
|---|---|---|
| QQ 风控 | 无头协议方案本质是模拟客户端，存在被限制风险 | 控制发送频率、避免批量群发、账号常用小号而非主力号 |
| LangChain 版本迭代快 | 1.0 刚 GA 不久，API 可能还有调整 | 锁定版本号，升级前先在测试环境验证 |
| LLM 成本 | 记忆提取额外调用会翻倍token消耗 | 用便宜/快速模型做提取任务，主对话用更强模型 |
| 记忆误提取 | LLM判断"是否值得记住"可能出错 | importance阈值过滤，定期人工抽查key_events表 |
