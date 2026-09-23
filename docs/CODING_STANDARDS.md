# 编码规范

## 类型标注与 Docstring

### 类型标注

所有函数、方法都必须有完整的类型标注（参数 + 返回值），包括 `-> None`。这不只是风格要求——
`pyproject.toml` 里 `mypy strict = true` 已经把这条强制生效了，没有类型标注的函数会直接导致
pre-commit 失败。

类型标注的意义：在代码运行之前就能发现"把 `str` 传给期望 `int` 的参数"这类错误，尤其是本项目
跨层传递数据多（OneBot 事件 → UnifiedMessage → Agent 状态 → 数据库记录），类型不匹配的 bug
很容易在层与层之间悄悄溜过去。

### Docstring：分两类对待，不是所有函数都要写

- **`agent/tools/` 下的工具函数必须写高质量 docstring。** 这是唯一一类"运行时真正生效"的
  docstring——LLM 靠它判断什么时候该调用这个工具、传什么参数。写得含糊，LLM 要么调错、要么
  压根不用。要求：清楚描述用途、适用场景，参数说明写在 Pydantic `Field(description=...)` 里
  （而不是重复写在 docstring 里）。

- **模块对外的公共 API 应该写**（比如 `onebot_adapter/client.py` 的 `connect` /
  `call_action`，`memory/user_profile.py` 的 `load` / `upsert`），哪怕只有一行，说明这个函数
  是给别的层调用的、做什么事、有什么副作用或者会抛什么异常。

- **内部私有函数（下划线开头）、脚本类代码（`scripts/` 下）不强制写 docstring**——命名清楚 +
  类型标注基本够用，逼自己每个 helper 都写三段式 docstring 只会拖慢开发速度，还容易在代码改动
  后没同步更新，变成一句谎言。

格式统一用 Google style（`Args:` / `Returns:` / `Raises:`），例：

```python
def make_thread_id(message_type: str, user_id: str, group_id: str | None) -> str:
    """生成 LangGraph 会话隔离用的 thread_id。

    Args:
        message_type: "group" 或 "private"。
        user_id: 发送者 QQ 号。
        group_id: 群号，私聊时为 None。

    Returns:
        群聊格式 "group:{group_id}:user:{user_id}"，私聊格式 "private:{user_id}"。
    """
```

## 异常处理

- **禁止裸 `except:`。** 裸 `except` 会连 `KeyboardInterrupt`、`SystemExit` 一起吞掉，程序会在
  你按 Ctrl+C 都退不出去，而且会掩盖真正意料之外的 bug，让排查变得极其困难。

- **`except Exception:` 只允许在明确设计为"隔离失败、不能让异常向上传播"的边界使用**，主要是
  两个场景：
  1. `agent/tools/` 里的工具函数——设计文档要求工具异常必须被捕获、转成友好文本返回给 LLM，
     而不是抛出去打断整个 Agent 循环。
  2. 后台异步任务（比如未来的记忆提取 `asyncio.create_task`）——后台任务失败绝不能
     影响主对话流程，但必须记录日志，不能默默吞掉。

  除了这两类场景，其他地方应该捕获具体的异常类型（如 `ValueError`、`TimeoutError`、
  `aiosqlite.Error`），让真正意外的异常正常抛出、暴露问题。

- 跨模块边界抛出的异常，优先用标准库异常类型或者自定义异常类（而不是到处用裸字符串判断错误
  原因）。自定义异常放在各自模块里，不搞一个全局 `exceptions.py` 大杂烩。

## 日志 vs print

- **`print` 只允许出现在 `scripts/` 下的一次性脚本里**（比如 `init_db.py` 这种手动运行、看
  一次输出就完事的场景）。

- **`onebot_adapter/`、`core/`、`agent/`、`memory/` 这些长期运行的服务代码一律用 `logging`**，
  不用 `print`。原因：`print` 没有级别、没有时间戳、生产环境里没法按级别过滤或者结构化收集。

- 日志级别的基本原则（接入持久化日志时再细化配置）：
  - `DEBUG`：排查问题时才需要的细节（原始收发的 JSON、中间状态）
  - `INFO`：正常的关键节点（连接建立、消息处理完成、记忆写入成功）
  - `WARNING`：不影响主流程但值得注意（重试、降级、跳过了某条消息）
  - `ERROR`：某个操作失败了，需要人关注（工具调用异常、数据库写入失败、LLM 调用超时）

- **用户消息原文默认不打进日志**（隐私考虑），确需记录用于排查时，只在 `DEBUG` 级别记录，且
  同时应考虑脱敏，避免意外记录隐私信息。

## 模块公共接口导出

- 每个包的 `__init__.py` 用 `__all__` 显式声明对外暴露的名字，不确定要不要公开的先不导出——
  加比减容易，先收紧后放开成本低，反过来（先公开后收紧）等于破坏性变更。

- 内部实现细节（不打算被包外代码 import 的函数/类）用下划线前缀 `_foo` 标记。

- **跨层调用有严格边界，这是本项目最重要的一条模块规范：**
  - `agent/` 禁止 import 任何 `onebot_adapter/` 的东西——agent 层完全不知道 OneBot 协议的
    存在。当前 MVP 由 `onebot_adapter/message.py` 提取文本，`core/` 只把纯文本交给 agent；
    将来确需处理多种消息段时，再考虑 `UnifiedMessage`。
  - `onebot_adapter/` 禁止 import 任何 `agent/` 或业务逻辑相关的东西——它只做协议翻译，不该
    知道"消息会被拿去问 LLM"这件事。
  - `core/` 是唯一允许同时依赖 `onebot_adapter/` 和 `agent/` 的层，它的职责就是把两边粘起来。

  违反这条边界（哪怕只是为了"图方便"）基本都意味着后面想换 QQ 实现或者换 LLM 框架时会牵一发
  动全身，这正是分层设计要防止的问题。
