# Task 10 SQLite 长期记忆测试指南

Task 10 会在机器人成功回复后，从适合长期保留的对话中提炼少量事实、偏好或重要原话。近期聊天上下文仍只存在于当前进程；长期记忆保存在 **data/memory.db**，重启后仍可使用。该文件已被 Git 忽略。

## 1. 启动和配置

在仓库根目录执行：

~~~bash
uv sync
bash scripts/start_dashboard.sh
~~~

打开 <http://127.0.0.1:8765/> 并登录。在“模型与连接”页面：

1. 填写 NapCat 地址、Token、主模型地址、模型名和 API Key。
2. 记忆模型默认勾选“跟随主模型”，无需重复填写 API 配置。
3. 如需单独计费或使用其他模型，展开“记忆模型”，取消“跟随主模型”，再填写独立配置。
4. DeepSeek 留空的 API 地址和模型名会使用服务端默认值；API Key 留空会保留现有值。

在“行为设置”调整“每日记忆提炼调用”。默认每天 10 次；每次提炼还会占用“每日总调用”，任一额度用完都会静默跳过提炼，普通聊天继续运行。

## 2. 自动提炼和召回规则

- 只有机器人成功发送回复后，才会排队检查本轮用户消息。
- “我喜欢”“我住在”“记住”“之前说错”“我们群”“每周”等稳定信息才会进入提炼候选。过短闲聊、纯图片、固定错误提示和疑似密码、Token、验证码、证件、银行卡或精确住址不会调用记忆模型。
- 同一范围短时间内的候选会合并处理。后台写入失败或模型输出无效时，不影响已经发送的回复。
- 私聊记忆只属于该 QQ 用户；群内个人记忆同时绑定群号和 QQ 号；群共享记忆只绑定群号。私聊内容不会进入群聊，群 A 的内容不会进入群 B。
- 回复前最多召回 5 条相关当前记忆，总长度约 1500 字。来源摘录和旧版本不会发送给聊天模型。
- 纠正已有事实会建立新版本；旧版本可在后台查看，但不再参与回复。记忆不会自动过期。

自动提炼是异步操作。发出测试信息后先继续一轮有效对话，等待约 30 秒，再刷新后台“记忆”页面。

## 3. 浏览器后台管理

登录后台后打开“记忆”：

1. 可按范围、群号、QQ 号、类型和正文搜索；每页最多 50 条。
2. 展开“历史与来源”可查看所有版本和最多 300 字的来源摘录。
3. “手动添加记忆”支持 private、group_user、group_shared 三种范围。
4. 修改会创建新版本。复制会在目标范围建立一条独立记忆。
5. “永久删除”会删除该记忆及全部历史版本，无法恢复。
6. 按范围清空必须准确输入“确认清空”，只清除填写的精确范围。

页面不会显示 Token、API Key、数据库路径、完整聊天记录或模型原始输出。删除和清空前如需保留数据，先按下一节备份。

## 4. 只读检查 SQLite

先确认系统安装了 sqlite3，然后以只读模式打开：

~~~bash
sqlite3 -readonly data/memory.db
~~~

进入 SQLite 后执行：

~~~sql
.headers on
.mode box
SELECT i.id, i.scope, i.group_id, i.user_id, i.kind,
       v.version, v.importance, v.content, v.created_at
FROM memory_items AS i
JOIN memory_versions AS v ON v.item_id = i.id
WHERE v.is_current = 1
ORDER BY v.created_at DESC
LIMIT 50;

SELECT item_id, version, is_current, content, created_by, created_at
FROM memory_versions
WHERE item_id = 1
ORDER BY version DESC;

.quit
~~~

第二条查询中的 1 替换为要检查的记忆 ID。只读检查不要执行 DELETE、UPDATE 或修改表结构；写操作使用后台完成。

## 5. 停机备份与恢复

先在状态页停止机器人，再用终端 Ctrl+C 关闭后台。确认没有机器人或后台进程访问数据库后执行：

~~~bash
sqlite3 data/memory.db ".backup 'data/memory-backup.db'"
~~~

需要恢复时保持程序关闭，先保留当前文件，再复制备份：

~~~bash
cp data/memory.db data/memory-before-restore.db
cp data/memory-backup.db data/memory.db
~~~

重新启动后台后打开“记忆”页面检查数据。**data/** 已被 Git 忽略，不要把数据库或备份提交到仓库。

## 6. 自动化检查

Task 10 聚焦测试：

~~~bash
uv run pytest tests/test_memory_store.py tests/test_memory_extractor.py \
  tests/test_groupmate_reply.py tests/test_groupmate.py \
  tests/test_bot_runtime.py tests/test_bot.py \
  tests/test_dashboard_app.py tests/test_dashboard_memory.py -q
~~~

完整工程检查：

~~~bash
uv run pre-commit run --all-files
git diff --check
~~~

自动化测试使用假 NapCat 和假模型，不产生 API 费用。

## 7. 真实 NapCat、QQ 和模型验收

按顺序完成，并把结果反馈给开发代理：

1. 私聊告诉机器人一个稳定偏好，继续一轮有效对话，等待约 30 秒并刷新后台，确认出现对应私聊记忆。
2. 停止并重新启动机器人，再询问该偏好，确认回复仍能使用它。
3. 用同一 QQ 在群聊中触发机器人，确认私聊记忆没有泄漏。
4. 在群内分别表达个人信息和明确群约定，确认后台范围正确，且只在对应群和用户范围使用。
5. 明确纠正一条旧事实，确认回复只使用新版本，后台“历史与来源”仍能看到旧版本。
6. 永久删除该记忆，确认当前内容和全部历史消失，后续回复不再召回。
7. 将每日记忆额度临时调低并用完，确认不再新增记忆，但普通聊天仍正常。
8. 检查后台页面，确认没有完整密钥、完整聊天、图片 URL、本机私有路径或模型原始输出。

全部通过后，才能勾选 **docs/任务Checklist.md** 中 Task 10 的真实验收项。Task 7 识图和 Task 8 群聊真实验收仍需分别按各自指南执行。
