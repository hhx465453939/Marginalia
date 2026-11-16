# CHG-001 · Marginalia 多用户确定性 IO 层（立项契约）

- 状态：进行中
- 立项日期：2026-11-16
- 项目：Marginalia（原技能 id `tutor-progress`，新 id `marginalia`，保留 legacy 别名）
- 依赖：Python 3.9+（仅标准库）

---

## 1. 问题陈述（根因，不是补丁）

现状：多用户隔离**只靠 SKILL.md 的自然语言约束**（`study/users/<uid>/` + 标签带称呼）。

根因：Agent 在纯 Markdown 世界里执行的是「自由文本编辑 + 路径拼接」，三个环节全部无校验：

| 环节 | 失败模式 | 后果 |
|---|---|---|
| 身份 | 靠上下文记忆"我现在是谁" | 串档：把 A 进度写进 B 书房 |
| 路径 | LLM 自己拼 `study/users/B/鬼谷子.md` | 写错人、写到 `../`、覆盖他人 |
| 内容 | 自由改标题/进度表/说话人标签 | 幻觉：A 的观点变成 B 的批注 |

**结论**：没有 schema 校验、没有归属断言、没有审计，幻觉不可防。必须引入确定性代码层。

## 2. 目标（可验证）

把「谁 / 写到哪 / 写了什么 / 能不能改」四个决策从 LLM 手里收回到代码里：

1. **LLM 只能说"我是谁"，不能决定"写到哪个文件"** —— 路径由 `uid` 派生，`--as` 是唯一身份入参。
2. **说话人由注册表派生**，不接受外部传入 → 幻觉出 `👤 别人` 无法落盘。
3. **原文只读且哈希锁定** → "原文一字不改"从口号变成断言。
4. **批注 append-only（JSONL）** → 交付物 `book.md` 由代码渲染，不可手改。
5. **一切写操作进审计链** → 事后可取证。

## 3. 非目标

- 不做 Web UI / 不做数据库（Markdown + JSON + JSONL 是交付物本身）
- 不做向量检索 / 不做 LLM 调用（纯 IO 层）
- 不删除任何存量学员数据（只在 `_trash/` 归档）

## 4. 架构

```
study/                              ← 数据根，由代码独占写入
├── registry.json                   ← 唯一身份真源（uid ↔ open_id ↔ 称呼 ↔ 角色）
├── INDEX.md                        ← 全局总表（代码渲染）
└── users/<uid>/
    ├── profile.json                ← 学员画像
    ├── INDEX.md                    ← 该学员课程索引（代码渲染）
    ├── audit.jsonl                 ← 审计链（append-only，链式哈希）
    └── books/<slug>/
        ├── meta.json               ← 底本/版本/进度/接续点/章节状态 + source 哈希
        ├── source.md               ← 原文，不可变
        ├── annotations.jsonl       ← 批注，append-only，权威真源
        └── book.md                 ← 渲染物（交付/阅读，勿手改）
```

写入通道只有一条：`marginalia` CLI。

## 5. 四件套（独占清单）

| 类别 | 路径 | 可改 |
|---|---|---|
| 契约 | `tasks/CHG-001-multiuser-io/SPEC.md` | 本文件 |
| 代码（新建） | `marginalia/*.py`、`bin/`、`pyproject.toml` | 全新建 |
| 测试（新建） | `tests/*.py` | 全新建 |
| 文档（改写） | `SKILL.md`、`README.md`、`skill.manifest.json`、`references/*.md`、`assets/*.svg` | 改写 |

**独占声明**：本 CHG 不改动 `study/` 下任何**真实学员数据**（各学员已有的批注本）。存量迁移由 `marginalia import` 在授权后单独执行。

## 6. CLI 契约

```
marginalia init
marginalia user add --open-id <id> --name <称呼> [--role student|owner] [--alias a,b]
marginalia user resolve (--open-id <id> | --name <称呼>)
marginalia user list
marginalia book create --as <身份> --title <书名> [--source <file>] [--slug <slug>] [--edition <版本>]
marginalia book list --as <身份>
marginalia chapter mark --as <身份> --book <slug> --chapter <篇名> --status 未讲|进行中|已讲
marginalia progress set --as <身份> --book <slug> --chapter <篇名> --segment <段> --anchor <原文句> [--next-anchor <原文句>]
marginalia note add --as <身份> --book <slug> --kind explain|ask|dialog|progress|variant --text <内容> --anchor <原文句> [--lesson N]
marginalia render --as <身份> --book <slug> [-o <path>]
marginalia export --as <身份> --book <slug> [--out <dir>]
marginalia verify [--as <身份>] [--book <slug>] [--strict] [--check-render] [--json]
marginalia stats --as <身份>
marginalia import --as <身份> --from <legacy.md> [--title <书名>] [--slug <slug>]
marginalia doctor
```

**退出码**：`0` 成功 ｜ `1` 一般错误 ｜ `2` 身份/权限/路径越界 ｜ `3` 完整性违规。

## 7. 硬闸（不可绕过）

| # | 闸门 | 行为 |
|---|---|---|
| G1 | 身份闸 | `--as` 无法解析到注册表 → exit 2，提示先 `user add` |
| G2 | 路径闸 | `slug` 必须 `^[a-z0-9][a-z0-9_-]{0,63}$`；拒绝 `..`、`/`、`\`、绝对路径、盘符、符号链接逃逸 → exit 2 |
| G3 | 归属闸 | 批注写入前校验 `book.meta.uid == 目标书房 uid` → 不符 exit 3 |
| G4 | 说话人闸 | `speaker` 一律由 registry 派生；外部传入与注册表不符 → exit 3（无 `--speaker` 参数） |
| G5 | 唯一性闸 | `anchor` 必须在 `source.md` 中**唯一**出现；0 次或多次 → exit 3 |
| G6 | 原文闸 | `source.md` sha256 与 `meta.json` 记录不符 → exit 3（禁止手改原文） |
| G7 | 审计闸 | 每次写操作追加 audit 行，`prev_hash` 链式串联，断链 → verify 报错 |
| G8 | 并发闸 | 写操作持文件锁（`O_EXCL` + 重试 + 30s 陈旧锁回收） |
| G9 | 渲染闸 | `book.md` 只能由 `render` 生成；`verify --check-render` 比对 |

## 8. 验收标准（AC）

- **AC1** 未注册身份执行任意命令 → exit 2，且不创建任何文件
- **AC2** `--book ../../etc` / `--slug a/b` / 绝对路径 → exit 2，无文件写入
- **AC3** 向 A 书房的书写入时 `meta.uid` 被篡改为 B → exit 3
- **AC4** 同一本书两个学员 → 两个独立 `annotations.jsonl`，A 的 20 条批注不出现在 B 文件；`verify` 通过
- **AC5** 手改 `source.md` 一个字符 → `verify` exit 3，报 source hash 不匹配
- **AC6** `anchor` 在原文出现 0 次 / 2 次 → `note add` exit 3
- **AC7** `render` 产出的单文件批注本符合 `references/lesson-record-format.md`（课程卡 + 原文 + 引用块批注）
- **AC8** `verify --strict` 在干净库 exit 0；注入任一违规 exit 非 0
- **AC9** audit.jsonl 链式哈希可验证；删除中间一行 → verify 报断链
- **AC10** `import` 存量单文件批注本 → source + annotations 可重建，`render` 与原文件批注条数与锚点一致
- **AC11** 20 线程并发 `note add` → 全部落盘，JSONL 行数 = 20，无损坏行
- **AC12** README（taste 基因：cg-03 留白 + md-04 庄重）含 hero SVG、故事、对比表、架构图、5 分钟上手
- **AC13** `python -m unittest discover -s tests` 全绿
- **AC14** SKILL.md v3 强制"所有状态变更必须走 CLI"，禁止手写路径/进度表

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 无 shell 的智能体无法跑 CLI | **见 §11 修订：这不是待缓解风险，是决定架构的未验证前提。已定义 portable 模式 + 事后审计器 `marginalia lint`，不再靠口头降级** |
| 用户手动改 `book.md` 后丢失 | `book.md` 头加"此文件由代码生成，请勿手改"；`verify` 检出 |
| 存量数据迁移出错 | `import` 先 dry-run 输出统计，`--apply` 才落盘；原件备份到 `_trash/` |
| 中文锚点匹配歧义 | 归一化（去空白/全半角）后匹配，仍要求唯一；不唯一时提示加长锚点 |

## 11. 修订记录（2026-11-16 · 立项 30 分钟后自查）

### 11.1 承认的错误

立项时把 **R1「Agent 可能没有执行通道」** 当作"风险项"写进 §9，然后用一句"保留 portable 模式"就算缓解，接着照自己的 SPEC 开工。这是**自签施工许可**：契约最关键的未验证前提被降级成待办，而它决定了整套设计是否成立。

已执行的事实侦察（本机）：

- `rg "共读批注本" /e` → 0 命中
- `tutor-progress` 仅在回收站保留**空目录**
- 无任何真实 `study/users/<uid>/` 数据

结论：**真实部署不在这台机器上，我无法用真实数据验证 importer，也无法直接观测 OpenClaw 是否有 shell。** 因此本 SPEC 的验收必须以「不依赖该未知量」的方式重构。

### 11.2 不可回避的技术判断

> **纯 Markdown 无法提供硬隔离。** 没有执行通道时，写入位置与说话人归属只能靠模型自觉——这正是当前串档的根因。

所以本项目交付**双模式**，且必须诚实标注各自的能力边界：

| 模式 | 前提 | 隔离强度 | 可验证性 |
|---|---|---|---|
| **A · strict（CLI）** | Agent 能执行命令（shell/python） | **硬**：路径/说话人由代码派生，越权即 exit 2/3 | 写入前拦截 + `verify` 事后断言 |
| **B · portable（纯 Markdown）** | 任意 Agent | **弱**：靠协议约束，模型可违反 | 只能**事后**审计（`lint`），不能事前拦截 |

不得在任何文档里把 B 描述成「同样安全」。B 的定位是：**可用、可审计、但不设防**。

### 11.3 修订后的新增验收（可证伪，不依赖未知量）

- **AC15** 新增 `marginalia lint <path>`：对**纯 Markdown 批注本**做事后审计，检出并 exit 3：
  - L1 课程卡缺 `学员：<称呼>（uid: ...）`
  - L2 出现 `👤 **<X>**` 且 X ≠ 课程卡称呼（跨学员污染）
  - L3 存在 `<!-- marginalia:uid=... -->` 但与课程卡 uid 不一致
  - L4 注册表已知的其他学员称呼出现在 `👤` 标签里
- **AC16** `lint` 对合法批注本 exit 0；对注入了他人批注的样本 exit 3，且错误信息点名到具体行号
- **AC17** SKILL.md v3 必须**分 A/B 双模式**，且对 B 模式显式标注「弱隔离·可被模型违反」；禁止只写 A 然后把无 shell 情形留空
- **AC18** 端点自检：`marginalia doctor` 输出当前可用模式判定，并给出该模式下的能力边界

### 11.4 由此确定的原则

1. **不猜环境**：可验证的部分现在做完（lint 审计器、双模式契约）；只有你（部署者）能确认的事实，才作为待确认项列出。
2. **不把「弱」说成「强」**：B 模式不假装有硬隔离，只在文档里写它能做什么。
3. **自签契约无效**：本 CHG 后续每次改代码，都必须先答「改完哪条 AC 变绿」。

## 10. 交付物清单（原始，已由 §11 增补）

1. `marginalia/`（10 模块）+ `bin/marginalia` + `pyproject.toml`
2. `tests/`（覆盘 AC1–AC11、AC15–AC16）
3. `references/io-contract.md`（A 模式规则 IO：Agent 唯一允许的数据操作方式）
4. `SKILL.md` v3（A/B 双模式，禁止单模式冒充全场景）
5. `README.md`（taste 设计门面）+ `assets/hero.svg`
6. `skill.manifest.json` v2
7. `references/lesson-record-format.md`（含 B 模式「书房指针」规范）
8. `MIGRATION.md`（存量单文件 → 新布局）

---

## 12. 验收结果（2026-11-16 · 收尾自查）

| AC | 结论 | 证据 |
|---|---|---|
| AC1 身份闸 | ✅ | `test_identity_and_paths.py::test_unknown_user`（exit 2 + 磁盘快照不变） |
| AC2 路径闸 | ✅ | `test_bad_slug`（`../../etc`、`a/b`、`..`、绝对路径、`C:\` 全 exit 2） |
| AC3 归属闸 | ✅ | `test_meta_tamper`（篡改 `meta.uid` → exit 3「归属冲突」） |
| AC4 多用户隔离 | ✅ | `test_two_users_same_book` + `test_progress_isolated`；端到端演练：owner 2 条 / 小林 1 条，互不出现 |
| AC5 原文哈希 | ✅ | `test_source_tamper`（改 1 字 → verify exit 3，写入也拒） |
| AC6 锚点唯一 | ✅ | `test_missing_anchor` / `test_ambiguous_anchor`（0 次与 2 次均 exit 3） |
| AC7 渲染格式 | ✅ | `test_card` / `test_tags` / `test_quote_needs_blank_line` / `test_source_verbatim` |
| AC8 verify | ✅ | `test_clean` / `test_bad_uid` / `test_wrong_speaker` / `test_render_tamper` |
| AC9 审计链 | ✅ | `test_chain_break`（删中间行）/ `test_chain_tamper`（改 op）均报错 |
| AC10 存量迁移 | ⚠️ 部分 | 对**文档记载的旧格式**验过（dry-run / apply / speaker 闸 / 幂等）；**未对他的真实 鬼谷子.md 验证**（文件不在本机） |
| AC11 并发 | ✅ | `test_parallel_notes`：20 线程直调库函数、调用方不加锁 → 20/20、id 唯一、审计链完整 |
| AC12 README | ✅ | hero SVG（cg-03 留白 + md-04 庄重，绢色/墨/朱砂一枚印）+ 词源故事 + 对比表 + mermaid 架构 + 5 分钟上手 + 已知边界 |
| AC13 测试 | ✅ | `Ran 46 tests ... OK` |
| AC14 SKILL 强制 CLI | ✅ | SKILL v3 §1.6 禁止清单 + §1.5 错误码处置 |
| AC15 lint | ✅ | `lint.py` L1–L8；`test_poison` 精确到行号 |
| AC16 lint 判据 | ✅ | `test_clean` / `test_no_card` / `test_uid_marker` / `test_expect_uid` |
| AC17 双模式 | ✅ | SKILL v3 §0 模式判定 + §2「弱隔离，模型可以违反」 |
| AC18 doctor 边界 | ✅ | `test_doctor_modes`，实测输出含 A/B 边界与自检结论 |

**未验证项（不装已完成）**：

1. 真实 OpenClaw 部署是否有 shell —— 本机无该部署，无法观测；SKILL v3 §0 已改为「先跑 doctor 判定，判不出就问用户，不许猜」。
2. 真实 `鬼谷子.md` 的 import 往返 —— 文件不在本机；`import` 的解析与锚点策略按 `references/lesson-record-format.md` 实现，并用等价样例覆盖。
3. 长期多用户压力 —— 当前证据为 46 项自动化测试 + 一次端到端演练。

**新增缺陷修复记录**（开发中当场修，未遗留）：

- Windows GBK 控制台导致中文/符号崩溃 → 入口强制 UTF-8 + `bin/marginalia.cmd` 设 `PYTHONUTF8=1`
- 引用块紧贴原文被 CommonMark 当段落续行 → `render` 强制空行分隔
- 篇目识别把 `# 书名` 当篇目 → `scan_headings` 下探一层
- `importer` 把 `**讨论**`/`**进度**` 标签当说话人、把 `**【第1课】**` 当人名 → 仅 `👤` 承载「人」
- `lint` 误审 `source.md`/`INDEX.md` → 发现范围限定为 `books/*/book.md`
- 并发保护只长在 CLI、库函数裸奔 → `Store.lock` 支持同线程重入，写库函数自带锁
- 测试夹具用全局 `redirect_stdout` 做多线程捕获 → 改为直调库函数（假失败的根因）
