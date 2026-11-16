# AGENT_DEPLOY · 给 agent 的部署协议

> 这份文件是**给 agent 读的**，不是给人读的散文。
> 每一步三件事：**做什么 → 期望看到什么 → 失败怎么办**。
> 按顺序执行。任一步「期望」不成立，就跳到该步的「失败分支」，不要往下走。

---

## 0. 先判断：你有执行通道吗

| 现象 | 结论 | 去哪 |
|---|---|---|
| 你能运行命令并拿到输出 | **模式 A（strict）** | 继续读 §1 |
| 你没有 shell / 无法执行任何命令 | **模式 B（portable）** | 跳到 §6 |

**不要猜。** 判不出来就问用户："我这个环境能执行命令吗？"

---

## 1. 装 CLI（三选一，按当前环境挑一个）

| 情况 | 命令 |
|---|---|
| 已有仓库目录 | `python -m pip install -e .` |
| 不想装进环境 | `./bin/marginalia --version`（Windows：`bin\marginalia.cmd --version`） |
| 已经装过 | `marginalia --version` |

**期望**：输出 `marginalia 3.1.0`（或更高）。

**失败分支**

| 错误 | 处置 |
|---|---|
| `python: command not found` | 让用户先装 Python ≥ 3.9，然后把 `python` 换成 `python3` 或 `py -3` 重试 |
| `No module named marginalia` | 确认当前目录是仓库根（有 `pyproject.toml`），再跑 `pip install -e .` |
| 中文输出乱码 / `UnicodeEncodeError` | Windows 设 `PYTHONUTF8=1`，或改用 `bin\marginalia.cmd` |
| 版本 < 3.1.0 | 仓库太旧，先 `git pull` |

> **记录**：把你实际用来调用 CLI 的前缀记下来（`marginalia` 或 `./bin/marginalia` 或 `python -m marginalia`）。
> 后面所有命令都用它，不要中途换。本文档统一写作 `marginalia`。

---

## 2. 一条命令完成部署

```bash
marginalia setup \
  --root ./study \
  --skills-dir <技能根目录> \
  --owner-open-id <用户的真实 sender_id> \
  --owner-name <owner 称呼>
```

参数说明：

| 参数 | 必须 | 说明 |
|---|---|---|
| `--root` | 建议 | 数据根，默认 `./study` |
| `--skills-dir` | **必须**（除非 `--no-skill`） | 会装到 `<skills-dir>/marginalia/` |
| `--owner-open-id` | 首次必须 | 用户在聊天平台上的真实 ID（飞书是 `ou_...`）。**不可编造** |
| `--owner-name` | 首次必须 | 会出现在批注标签里，如 `主人` |

**期望**：

```
✓ 部署状态：ready
  检查：
    ✓ python_version / root_initialized / owner / skill_installed
    ✓ deployment_record / skill_file / skill_integrity / skill_up_to_date / data_integrity
  下一步：
    1. marginalia doctor ...
```

**失败分支**

| 报错 | 含义 | 处置 |
|---|---|---|
| `安装 skill 副本必须显式指定 --skills-dir` | 你没给装 skill 的位置 | 问用户技能根目录（常见 `~/.claude/skills`、`~/.agents/skills`），或加 `--no-skill` 只建数据根 |
| `目标目录已有其它技能（id=...）` | 那个目录属于别的技能 | **停下**，向用户确认；确认覆盖才加 `--force` |
| `Python 版本过低` | 环境不满足 | 让用户升级 Python |
| `--owner-open-id 与 --owner-name 必须同时提供` | 参数不成对 | 补齐两项 |

> `setup` 是**幂等**的：重复执行安全，不会重建或清空已有数据。
> 想先看它要做什么：加 `--dry-run`（零写入）。

---

## 3. 自证（每次会话都可以跑）

```bash
marginalia setup --check
```

**这是整条链路的健康探针**，退出码就是结论：

| 退出码 | 状态 | 含义与处置 |
|---|---|---|
| `0` | `ready` | 可以开始上课 |
| `1` | `absent` / `partial` | 还没装好 → 回 §2 |
| `3` | `stale` | 已装但**副本过期** → `marginalia setup --force` |
| `3` | `broken` | 数据完整性有问题 → `marginalia verify` 看详情，**不要继续写入** |

**建议**：每次会话开头先跑一次 `--check`。非 0 就按上表处理，别带着过期副本讲课。

---

## 4. 确认能力边界

```bash
marginalia doctor
```

**期望**：看到两个区块

- `# 部署状态（CHG-002）` → `状态：ready`、版本、skill 路径
- `# 隔离能力边界（AC18）` → 模式 A/B 说明 + 批注本自检结论

**失败分支**：doctor 报“未记录部署” → 回 §2。

---

## 5. 交接口语

部署完成后，对用户说这一句（把尖括号换成实际值）：

> 已经装好了。你现在可以直接说「我想学《某书》」，我会开始第一课。
> 你的书房在 `<数据根>/users/<uid>/`。

之后进入正常教学流程，见 `SKILL.md` §1。

---

## 6. 模式 B：没有执行通道时（手工部署）

你跑不了任何命令，所以**不能**用 `setup`。按下面四条做：

1. **建数据根**：创建 `study/` 目录。
2. **建注册表**：创建 `study/USERS.md`，每位学员一行：
   ```
   uid: <uid> | 称呼: <称呼> | 书房: study/users/<uid>/
   ```
3. **写书房指针**：每次会话开始，把当前学员那一行**原样抄**进上下文。
4. **遵守写作协议**：见 `references/lesson-record-format.md` §4 —— 课程卡必须有
   `- 学员：<称呼>（uid: ...）`，`👤` 标签只能写这个称呼，路径只能以指针里的
   `书房:` 开头。

**必须向用户说清楚**（不得省略）：

> 我这个环境不能执行命令，所以用的是**弱隔离**模式：靠规则约束，不是代码强制。
> 如果有别的环境能跑命令，用 `marginalia lint` 可以事后检查有没有串档。

**B 模式无法被 `--check` 检测**——没有执行通道就没有检测器。这是事实，不要假装。

---

## 7. 排障速查

| 现象 | 先跑 | 再决定 |
|---|---|---|
| 不确定装好没有 | `marginalia setup --check` | 非 0 按 §3 表处理 |
| 怀疑数据被串档 | `marginalia verify --check-render --strict` | 有错就停下，把报错给用户看 |
| 怀疑纯 Markdown 批注本串档 | `marginalia lint` | 报 L1–L8，精确到行号 |
| 忘记部署到哪了 | `marginalia doctor` | 看 `skill：` 那一行 |
| 想重装技能副本 | `marginalia setup --skills-dir <同一目录> --force` | 会刷新，不动学员数据 |
| 锁超时 | `marginalia doctor` 看残留 `.lock-*` | 确认无进程在跑后删除该锁文件 |

---

## 8. 绝对禁止（部署期同样适用）

- ❌ 未经用户确认，往任何 skills 目录里装东西（`--skills-dir` 必须是用户给的或用户确认的）
- ❌ 编造 `--owner-open-id`（必须来自真实消息的 `sender_id`）
- ❌ 用 `--force` 覆盖别人的技能目录
- ❌ 把 `--check` 的 exit 3 当成"重试一下就好"
- ❌ 在 B 模式下声称"有硬隔离"
- ❌ 提交或上传 `study/` 里的学员数据
