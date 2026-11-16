---
change_id: CHG-002
version: 1
status: approved
prd_ref: PRD.md
health_ref: HEALTH.md
supersedes: null
approved_by: user
approved_at: 2026-11-16
approval_evidence: |
  用户本会话原话：「commit push 上去，相关功能记得一定开发测试好，我睡觉了，明天见」。
  授权记录见 CHANGE.md。本文件不是 agent 自批。
---

# CHG-002 · agent 部署引导链路（skill → script）

## 1. 上下文与目标

### 1.1 问题（根因）

CHG-001 解决了「装好之后不会串档」。**没解决「怎么装」**，而这一层是断的：

| 断点 | 表现 |
|---|---|
| 入口断裂 | SKILL.md §0 要求先跑 `marginalia doctor`，但命令未安装时它跑不了，agent 卡死在这里 |
| 无状态 | 没有任何记录能回答「这台机器装好了吗、装的是哪版」 |
| 无漂移检测 | 仓库升级了 `SKILL.md`，agent 还在用三个月前的副本，行为与代码不一致且无人发现 |
| 无冲突保护 | 装到已有别的技能的目录里，静默覆盖 |
| 无顺序契约 | README 给的是命令清单，不是「按这个顺序、每步怎么验证」的流程 |

### 1.2 目标（可判定）

一句话：**任何 agent 从「什么都没装」到「可以开口上课」，全程只需读一份协议 + 跑一条命令，且每一步都有可验证的输出。**

具体：

- G-A：`marginalia setup` 一条命令完成「数据根 + owner + skill 副本 + 记账 + 自证」，幂等。
- G-B：`marginalia setup --check` 用退出码回答「装好没有」，可供 agent 在每次会话开头自愈。
- G-C：`deployment.json` 是唯一部署事实源，含版本、Python、模式、路径、每步校验结果。
- G-D：安装副本与仓库版本不一致 → `stale`，拒绝假装正常。
- G-E：找不到 skill 目录时**报错并给候选**，绝不擅自写用户家目录。
- G-F：文档里出现的每条命令都真实存在（用测试守住，而不是靠人眼）。

### 1.3 非目标

- 不联网下载 Python / 不代管包管理器
- 不做多机分发的编排（Ansible / Docker）
- 不改 CHG-001 的九道闸语义与退出码 0/1/2/3 的含义
- 不做无 shell 环境的自动部署（B 模式只能人工按文档做，见 §3.3）

### 1.4 约束

- 运行时零第三方依赖（只用标准库）
- Python ≥ 3.9
- Windows 必须能跑（UTF-8 + `.cmd` 包装）
- 所有写入要么在数据根内，要么在用户**显式指定**的 skill 目录内

### 1.5 假设

- agent 有执行通道时可运行 `marginalia`（否则走 B 分支）
- skill 目录符合「一个子目录 = 一个技能」的惯例（`<skills-dir>/<skill-name>/SKILL.md`）

### 1.6 未决问题

| # | 问题 | 本版处理 |
|---|---|---|
| Q1 | 是否要支持「一个 skills-dir 里装多份相同技能」 | 不支持；同名即视为同一技能，用 sha 判断是否过期 |
| Q2 | 是否要把 deployment.json 放进版本控制 | 不放（在 `study/` 内，已 gitignore） |
| Q3 | B 模式能否被 `--check` 检测 | 不能（无执行通道就无法运行检测）；文档明确说明 |

## 2. 现有架构与债务影响

复用 CHG-001 的分层，不新增层：

```
cli.py          ← 新增 setup 子命令（唯一入口）
setup.py（新）   ← 部署编排：探测/安装/记账/自证/漂移检测
store.py        ← 复用与扩展：deployment.json 读写、路径派生
registry.py     ← 复用：建 owner
verify.py       ← 复用：自证阶段跑完整性校验
render.py       ← 复用：建根后刷索引
```

债务影响：新增 1 个模块（`setup.py`），CLI 命令数 +1。CHG-001 的九道闸保持不变；新增第 10 道「部署闸」（G10）。

## 3. 选定设计与 ADR

### 3.1 链路（可控引导链）

```
[0] 探测        能执行命令？ ──否──> B 分支（人工，见 §3.3）
                    │是
[1] 装 CLI      pip install -e .  ｜ ./bin/marginalia ｜ 已安装
[2] marginalia setup            ← 一条命令做完 [2]~[5]
      2.1 建数据根（registry.json / INDEX.md）
      2.2 建 owner（若给了 --owner-open-id）
      2.3 装 skill 副本到 <skills-dir>/marginalia/
      2.4 写 <root>/deployment.json
      2.5 自证：verify + 五项检查
[3] marginalia setup --check    ← 退出码即结论（0 ready / 1 未装 / 3 漂移）
[4] marginalia doctor           ← 报模式与能力边界
[5] 交接口语：可以开始上课
```

### 3.2 ADR

**A1 · 部署状态放在数据根，不放在项目目录**
- 选定：`<root>/deployment.json`
- 被否：`<project>/.deployed` —— 项目目录可能只读（pip 安装到 site-packages 时），且同一项目可能部署到多个数据根
- 被否：环境变量 —— 进程外不可见，agent 读不到
- 可逆性：高（只是文件位置）
- 后果：数据根成为「部署 + 数据」的共同锚点，备份策略一并覆盖

**A2 · 用 sha256 判断漂移，而不是版本号**
- 选定：比较安装副本与仓库 `SKILL.md` 的 sha256
- 被否：比版本号 —— 版本号常用于整个包，单文件改了版本号不必变（文档改动正是高频场景）
- 被否：比 mtime —— 复制/检出会重置时间，不可靠
- 可逆性：高
- 后果：仓库改一个字，`--check` 就报 `stale`，需要重新 `setup --force`

**A3 · 部署编排写在 Python 里，脚本只做包装**
- 选定：`marginalia/setup.py` + `scripts/deploy.{sh,cmd}` 薄包装
- 被否：纯 shell 脚本 —— Windows 要写两套逻辑，且无法复用 registry/verify
- 被否：纯文档（让 agent 手敲 6 条命令）—— 无状态、无校验、失败无分支
- 可逆性：高
- 后果：脚本只负责定位 Python 与 UTF-8，逻辑只有一份

**A4 · 找不到 skills-dir 时失败，不猜**
- 选定：返回 exit 1 + 候选目录列表 + 明确 hint
- 被否：自动写第一个存在的目录 —— 可能写进别的 agent 的配置，属于擅自改用户环境
- 被否：自动创建 `~/.claude/skills` —— 在没装 Claude 的机器上凭空造目录
- 可逆性：高
- 后果：首次部署多一次交互；换来「绝不误写」

### 3.3 B 分支（无执行通道）

`setup` 跑不了，因此：

1. 按 `AGENT_DEPLOY.md` §B 手工建数据根与 `USERS.md`；
2. 每次落笔遵守「书房指针」协议（见 `references/lesson-record-format.md` §4）；
3. 事后若在别处能跑 CLI，用 `marginalia lint` 取证。

**B 模式无法被 `--check` 检测**，这一点在文档中明写，不许含糊。

## 4. 接口契约

### 4.1 CLI

```
marginalia setup [--skills-dir <dir>] [--owner-open-id <id>] [--owner-name <称呼>]
                 [--dry-run] [--check] [--force] [--no-skill] [--json]
```

| 参数 | 语义 |
|---|---|
| `--skills-dir` | skill 安装根目录（`<dir>/marginalia/`）。未给则探测候选；探测不到即失败 |
| `--dry-run` | 只打印将要做的事，**零写入** |
| `--check` | 只校验不改动；退出码即结论 |
| `--force` | 允许覆盖同名 skill 目录 / 刷新旧副本（G10 的显式解锁） |
| `--no-skill` | 只建数据根，不装 skill（用户自行管理提示词） |

### 4.2 退出码

| 场景 | 码 |
|---|---|
| 部署完成 / `--check` 为 `ready` | 0 |
| 参数或环境缺失（无 skills-dir、Python 版本过低） | 1 |
| 目标目录是别的技能（G10） | 3 |
| `--check` 为 `stale`（副本与仓库不一致） | 3 |

### 4.3 `deployment.json` schema

```json
{
  "schema": 1,
  "project_version": "3.0.0",
  "deployed_at": "2026-11-16 23:40",
  "updated_at": "2026-11-16 23:40",
  "python": "3.13.5",
  "mode": "strict",
  "root": "<abs>/study",
  "skill": {
    "dir": "<abs>/skills/marginalia",
    "file": "<abs>/skills/marginalia/SKILL.md",
    "installed_sha256": "<hex>",
    "source_sha256": "<hex>",
    "installed_at": "2026-11-16 23:40"
  },
  "checks": [{ "name": "root_initialized", "ok": true, "detail": "" }]
}
```

`skill` 为 `null` 表示 `--no-skill`。

### 4.4 状态机

| 状态 | 判据 | `--check` 退出码 |
|---|---|---|
| `absent` | 数据根未初始化 | 1 |
| `partial` | 根已建，但缺 `deployment.json` / skill 副本 | 1 |
| `stale` | 副本 sha ≠ 仓库 sha | 3 |
| `ready` | 全部检查通过 | 0 |

## 5. 安全

- **G10 部署闸**：目标 `<skills-dir>/marginalia/` 若已存在且其 `skill.manifest.json` 的 `id` ≠ `marginalia` → 拒绝（exit 3），除非 `--force`
- 不写 `~/.claude` / `~/.agents` 以外的任何位置；无 `--skills-dir` 且无候选 → 失败
- 部署日志不含学员数据（只记路径与哈希）

## 6. 兼容性与迁移

- CHG-001 用户：数据根已存在时 `setup` 只补 `deployment.json` 与 skill 副本，**不重建、不清空**
- `--no-skill` 用户不受影响
- 旧文档中的 `marginalia init` 仍可用（`setup` 是其超集）

## 7. 可观测性

- `setup` 输出：5 项检查逐条 ✓/✗ + 状态 + 编号的下一步
- `doctor` 增加「部署」段：版本、skill 路径、sha 是否一致、状态
- 全部失败都给 `hint`（可执行下一步）

## 8. 发布与回滚

- 向前：`setup` 幂等，可反复执行
- 回滚代码：`git checkout <上一 tag>`，`deployment.json` 保留（下次 `--check` 会报 `stale`，提示刷新）
- 回滚部署：删除 `<skills-dir>/marginalia/` 与 `<root>/deployment.json`
- 数据永不自动删除

## 9. 里程碑

| M | 内容 | 文件 | 验收 |
|---|---|---|---|
| M1 | 契约 | `tasks/CHG-002-agent-deploy/*` | 三份文件齐 |
| M2 | 部署编排 | `marginalia/setup.py` | AC1–AC7 |
| M3 | CLI 接入 | `marginalia/cli.py`（`setup` + `doctor` 增强） | AC2/AC8 |
| M4 | 脚本包装 | `scripts/deploy.{sh,cmd}` | AC11 |
| M5 | 文档链路 | `AGENT_DEPLOY.md`、`references/deployment.md`、README(中/英) 顶部、`SKILL.md` §0、manifest | AC9/AC10/AC12 |
| M6 | 测试 | `tests/test_setup.py`、`tests/test_docs_consistency.py` | AC1–AC12 全绿 |

## 10. 验收标准

| AC | 内容 |
|---|---|
| AC1 | `setup --dry-run` 零写入（磁盘快照不变） |
| AC2 | `setup` 建出数据根 + owner + skill 副本 + `deployment.json`，exit 0 |
| AC3 | 幂等：连续两次 `setup` 均 exit 0，owner 不重复、skill 不重复 |
| AC4 | `--check` 未部署 exit 1；部署后 exit 0 |
| AC5 | 目标目录是别的技能 → exit 3；加 `--force` 才覆盖 |
| AC6 | 无 `--skills-dir` 且无候选 → exit 1，输出含候选列表 |
| AC7 | `deployment.json` 字段完整（schema/version/python/mode/root/skill/checks） |
| AC8 | 仓库 `SKILL.md` 改动后 `--check` → `stale` exit 3 |
| AC9 | `doctor` 输出部署段（版本 / skill 路径 / sha 一致性 / 状态） |
| AC10 | 文档-代码一致性：`AGENT_DEPLOY.md`、`README.md`、`SKILL.md` 中出现的 `marginalia <子命令>` 全部真实存在 |
| AC11 | `scripts/deploy.sh` / `deploy.cmd` 存在，调用 `marginalia setup` |
| AC12 | 全量门禁绿：ruff / format / mypy / unittest / build 零警告；CI 绿 |

## 11. Definition of Ready

- [x] PRD 已批准（`PRD.md`）
- [x] 变更简报与授权记录（`CHANGE.md`）
- [x] 根因定位到「入口断裂 / 无状态 / 无漂移检测 / 无冲突保护 / 无顺序契约」
- [x] 至少两个被否方案（§3.2 共 8 个）
- [x] 每条 AC 可被一条命令或测试打绿/打红

## 12. Definition of Done

- [ ] AC1–AC12 全部有证据
- [ ] ruff / format / mypy / unittest / build 全绿
- [ ] `AGENT_DEPLOY.md` 的每一步都有「命令 / 期望输出 / 失败分支」
- [ ] README 开头能直接照做（中/英）
- [ ] SKILL.md §0 把 agent 指向部署协议，无断点
- [ ] 未验证项显式列出

## 13. 评审与交付门

| 门 | 判据 |
|---|---|
| R1 | 不违反 CHG-001 三条不可违反约定 |
| R2 | 新增命令有 exit 1 / 3 的负向测试 |
| R3 | 文档所述行为与代码一致（由 AC10 自动守住） |
| R4 | commit / push 有用户授权（`CHANGE.md`） |
