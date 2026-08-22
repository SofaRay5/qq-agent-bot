"""OneBot v11 事件模型（消息事件 + 心跳元事件）。

参考: docs/reference/onebot-v11-events.md

message 字段格式：只支持数组格式（list[dict]），不兼容 CQ 码字符串格式。
理由：
- 设计文档里 NapCat 配置本来就建议 messagePostFormat="array"，数组格式是官方推荐的新写法，
  CQ 码字符串是历史遗留格式，两者携带的信息等价，没必要在适配层同时维护两套解析逻辑。
- 数组格式天然是结构化数据（每个消息段自带 type/data），Pydantic 处理起来更直接；CQ 码
  是一段需要额外用正则解析转义的字符串，多一层解析容易出 bug，且这层工作量对本项目没有
  实际收益。
- 如果以后真的需要接一个只支持 CQ 码格式的老实现，应该在 onebot_adapter 内部单独加一个
  "CQ 码字符串 -> 消息段数组"的转换函数，而不是让 event.py 的模型本身支持两种格式——
  保持模型定义单一、解析逻辑内聚。
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter


class Sender(BaseModel):
    """私聊消息的发送者信息。字段是"尽最大努力提供"，不保证都存在。"""

    user_id: int
    nickname: str | None = None
    sex: str | None = None
    age: int | None = None


class GroupSender(Sender):
    """群消息的发送者信息，比私聊多群相关字段（名片/地区/等级/角色/头衔）。"""

    card: str | None = None
    area: str | None = None
    level: str | None = None
    role: str | None = None
    title: str | None = None


class PrivateMessageEvent(BaseModel):
    time: int
    self_id: int
    post_type: Literal["message"]
    message_type: Literal["private"]
    sub_type: Literal["friend", "group", "other"]
    message_id: int
    user_id: int
    message: list[dict[str, Any]]
    raw_message: str
    font: int
    sender: Sender


class GroupMessageEvent(BaseModel):
    time: int
    self_id: int
    post_type: Literal["message"]
    message_type: Literal["group"]
    sub_type: Literal["normal", "anonymous", "notice"]
    message_id: int
    group_id: int
    user_id: int
    anonymous: dict[str, Any] | None = None
    message: list[dict[str, Any]]
    raw_message: str
    font: int
    sender: GroupSender


# 条件必填（group_id 只在群消息里出现）用两个独立类实现，而不是一个类 + model_validator：
# 私聊模型上根本不存在 group_id 字段，类型系统层面就不可能出现"私聊事件却带 group_id"
# 这种状态，比运行时校验更强的保证。
MessageEvent = Annotated[
    PrivateMessageEvent | GroupMessageEvent,
    Field(discriminator="message_type"),
]


class HeartbeatEvent(BaseModel):
    time: int
    self_id: int
    post_type: Literal["meta_event"]
    meta_event_type: Literal["heartbeat"]
    status: dict[str, Any]
    interval: int


AnyEvent = Annotated[
    MessageEvent | HeartbeatEvent,
    Field(discriminator="post_type"),
]

_KnownEvent = PrivateMessageEvent | GroupMessageEvent | HeartbeatEvent
_event_adapter: TypeAdapter[_KnownEvent] = TypeAdapter(AnyEvent)


class UnknownEvent(BaseModel):
    """post_type（或已知 post_type 下的子类型）不在当前支持范围时的兜底容器。

    未知事件不应该让整个程序崩溃——上游还会推送本项目暂不处理的 notice/request 事件，
    这里选择原样保留原始数据并返回，而不是抛异常。
    """

    raw: dict[str, Any]


def parse_event(
    data: dict[str, Any],
) -> PrivateMessageEvent | GroupMessageEvent | HeartbeatEvent | UnknownEvent:
    """把一个原始事件 dict 解析成对应的事件模型。

    已知类型（消息事件/心跳）字段不完整时会抛出 pydantic.ValidationError；
    未知的 post_type / message_type / meta_event_type 会返回 UnknownEvent，不抛异常。
    """
    post_type = data.get("post_type")
    if post_type == "message" and data.get("message_type") in ("private", "group"):
        return _event_adapter.validate_python(data)
    if post_type == "meta_event" and data.get("meta_event_type") == "heartbeat":
        return _event_adapter.validate_python(data)
    return UnknownEvent(raw=data)
