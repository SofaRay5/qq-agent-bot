# 日常开发流程速查

> 忘了流程的时候翻这个文件，不用每次都来问。

## 每次写完一段代码，提交的标准流程

```bash
# 1. 看一眼改了什么，心里有数
git status
git diff

# 2. 把改动加入暂存区
git add -A
# 或者只加某几个文件（更安全，不会误提交不相关的东西）：
# git add path/to/file1 path/to/file2

# 3. 再看一眼确认要提交的内容对不对
git status

# 4. 提交（commit 前 pre-commit 会自动跑 ruff/mypy/pytest 四项检查）
git commit -m "类型: 简短描述"

# 5. 推到 GitHub
git push
```

第一次在新分支上 push 需要 `git push -u origin main`（`-u` 建立追踪关系），
之后同一个分支直接 `git push` 就够了，不用每次都写全。

## commit message 前缀怎么选

| 前缀 | 什么时候用 |
|---|---|
| `feat:` | 新增了一个功能 |
| `fix:` | 修了一个 bug |
| `chore:` | 工程杂项，不改变功能（配置文件、依赖版本、目录结构） |
| `docs:` | 只改了文档 |
| `test:` | 只加/改了测试 |
| `refactor:` | 重构，不改变外部行为 |

不确定选哪个就选最贴近改动本质的那个，别纠结太久。

## commit 被 pre-commit 拦下来了怎么办

```bash
git commit -m "..."
# 假设某个钩子报错，比如 ruff 说有未使用的 import
```

1. **ruff / ruff-format 报错**：大概率会自动帮你改好文件（`--fix` 已经开了），
   直接 `git add -A` 把改动加进来，再 commit 一次就行。
2. **mypy 报错**：需要你自己去看提示的文件+行号，补上类型标注或者修类型不匹配的地方。
3. **pytest 报错**：说明测试没通过，去看是测试写错了还是代码逻辑真的有 bug，改完再提交。

改完之后**不需要重新 `git commit`，只要 `git add` 改动的文件再 `git commit` 一次**
（上一次失败的 commit 根本没有真正发生，git 历史里不会留下失败记录）。

## 真的赶时间、想跳过检查（少用）

```bash
git commit -m "..." --no-verify
```

跳过所有 pre-commit 检查直接提交。只在你确认这是临时占位、后面一定会回来补的情况下用
（比如之前补占位测试之前的那次 milestone 0 首次提交）。日常写业务代码不建议用这个。

## 常用排查命令

```bash
# 看提交历史
git log --oneline

# 看本地有几个 commit 还没 push 到远程
git log origin/main..HEAD --oneline

# 手动跑一遍 pre-commit（不 commit，只是想看看会不会报错）
uv run pre-commit run --all-files

# 只跑某一个钩子
uv run pre-commit run ruff --all-files
uv run pre-commit run mypy --all-files
```

## 完整的一次循环，浓缩成一句话

**改代码 → `git status` 看一眼 → `git add -A` → `git commit -m "..."`
（自动跑检查，挂了就修完重新 add+commit）→ `git push`。**
