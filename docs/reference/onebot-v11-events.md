# OneBot v11 事件参考（原文整理）

> 来源：[botuniverse/onebot-11](https://github.com/botuniverse/onebot-11) 官方文档（`event/` 目录），
> 抓取时间 2026-08-17。这是资料整理/离线查阅用；具体实现仍应核对当前 OneBot 协议与
> NapCat 的实际行为。

## 事件总览

所有事件都有公共字段：`time`（时间戳）、`self_id`（机器人 QQ 号）、`post_type`（事件类型）。

`post_type` 的四种取值：

| post_type | 含义 |
|---|---|
| `message` | 消息事件 |
| `notice` | 通知事件 |
| `request` | 请求事件 |
| `meta_event` | 元事件 |

`message` 字段的格式（字符串 / 消息段数组）由配置项 `event.message_format` 决定
（`string` 或 `array`）。

---

## 一、消息事件（`post_type = "message"`）

### 私聊消息（`message_type = "private"`）

| 字段 | 类型 | 可能的值 | 说明 |
|---|---|---|---|
| sub_type | string | `friend`、`group`、`other` | 好友消息是 `friend`，群临时会话是 `group` |
| message_id | number (int32) | - | 消息 ID |
| user_id | number (int64) | - | 发送者 QQ 号 |
| message | message | - | 消息内容 |
| raw_message | string | - | 原始消息内容 |
| font | number (int32) | - | 字体 |
| sender | object | - | 发送人信息（user_id/nickname/sex/age，尽最大努力提供，不保证都存在） |

快速操作：`reply`（回复内容）、`auto_escape`（是否作为纯文本发送）

### 群消息（`message_type = "group"`）

| 字段 | 类型 | 可能的值 | 说明 |
|---|---|---|---|
| sub_type | string | `normal`、`anonymous`、`notice` | 正常消息/匿名消息/系统提示（如"管理员已禁止匿名聊天"） |
| message_id | number (int32) | - | 消息 ID |
| group_id | number (int64) | - | 群号 |
| user_id | number (int64) | - | 发送者 QQ 号 |
| anonymous | object \| null | - | 匿名信息，非匿名消息为 null |
| message | message | - | 消息内容 |
| raw_message | string | - | 原始消息内容 |
| sender | object | - | 发送人信息（比私聊多 card/area/level/role/title） |

快速操作：`reply`、`auto_escape`、`at_sender`、`delete`（撤回）、`kick`（踢出）、
`ban`/`ban_duration`（禁言）

**关键观察（对应设计条件必填逻辑）**：`group_id` 只在 `message_type = "group"` 时出现，
私聊消息里没有这个字段。

---

## 二、通知事件（`post_type = "notice"`）

所有子类型都用 `notice_type` 区分（不是 `sub_type`），部分子类型下面还会再细分 `sub_type`：

| notice_type | sub_type（如有） | 说明 |
|---|---|---|
| `group_upload` | - | 群文件上传 |
| `group_admin` | `set`、`unset` | 群管理员变动 |
| `group_decrease` | `leave`、`kick`、`kick_me` | 群成员减少（主动退群/被踢/自己被踢） |
| `group_increase` | `approve`、`invite` | 群成员增加（管理员同意/邀请入群） |
| `group_ban` | `ban`、`lift_ban` | 群禁言/解除禁言 |
| `friend_add` | - | 好友添加 |
| `group_recall` | - | 群消息撤回 |
| `friend_recall` | - | 好友消息撤回 |
| `notify` | `poke` | 群内戳一戳 |
| `notify` | `lucky_king` | 群红包运气王 |
| `notify` | `honor` | 群成员荣誉变更（龙王/群聊之火/快乐源泉） |

**注意**：`notify` 这个 `notice_type` 下面挤了三种完全不同的事件（戳一戳/运气王/荣誉变更），
靠 `sub_type` 才能真正区分，容易漏判断。

---

## 三、请求事件（`post_type = "request"`）

用 `request_type` 区分：

| request_type | sub_type（如有） | 说明 |
|---|---|---|
| `friend` | - | 加好友请求 |
| `group` | `add`、`invite` | 加群请求 / 邀请入群 |

字段：`user_id`（发起者）、`comment`（验证信息）、`flag`（处理请求时要传回的凭证）、
`group_id`（仅 group 类型有）。

快速操作：`approve`（是否同意）、`remark`/`reason`（备注或拒绝理由）。

---

## 四、元事件（`post_type = "meta_event"`）

跟聊天软件无关，是 OneBot 自身运行状态相关的事件。用 `meta_event_type` 区分：

| meta_event_type | sub_type（如有） | 说明 |
|---|---|---|
| `lifecycle` | `enable`、`disable`、`connect` | OneBot 启用/停用/WS 连接成功 |
| `heartbeat` | - | 心跳，带 `status`（运行状态）和 `interval`（间隔毫秒数） |

`connect` 是本项目会实际用到的场景（正向 WebSocket 连接建立时）；`enable`/`disable`
只有 HTTP POST 模式才会收到，本项目用正向 WS，理论上不会遇到。

---

## 字段命名的规律（帮助记忆）

不同 `post_type` 下，"细分类型"字段的名字并不统一：

| post_type | 细分类型字段名 |
|---|---|
| `message` | `message_type`（private/group）+ `sub_type`（细分到 friend/normal 等） |
| `notice` | `notice_type` |
| `request` | `request_type` |
| `meta_event` | `meta_event_type` |

`sub_type` 这个字段名在四大类里都可能出现，但含义完全取决于它上一级的 `xxx_type` 是什么——
这也是为什么 checklist 要求"能脱稿讲清楚 `message_type` 和 `sub_type` 的区别"：
`message_type` 只在消息事件里出现，分 private/group 两大类；`sub_type` 是在 `message_type`
基础上更细一层的分类，且在其他三大类事件里也存在、但对应不同的父字段。
