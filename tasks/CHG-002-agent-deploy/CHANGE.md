# CHANGE · CHG-002

## 变更请求（原文）

> 这个项目最后都是要给 agent 部署的，你把 agent 部署引导，从 skill 到 script，都要形成一个可控的引导链路，
> readme 开头也要把部署语言指令写好，项目内部也把指引写好，然后 commit push 上去，
> 相关功能记得一定开发测试好，我睡觉了，明天见。

## 触发原因

项目已有硬隔离的 IO 层（CHG-001），但**「怎么把它装到一台机器 / 一个 agent 身上」全靠潜规则**：

- README 只写了 `pip install -e .` 和几条示例，没有「agent 照着做就能跑通」的顺序；
- SKILL.md §0 让 agent 先跑 `marginalia doctor`，但**命令本身没装的时候它什么也做不了**——这是个断点；
- skill 层（提示词）与 script 层（代码）之间没有任何「装没装、装的是不是最新版」的状态记录；
- 装错了、装旧了、装到别人的 skill 目录里，都没有任何检查。

结论：缺的不是文档，是**一条有状态、可验证、可重入的部署链路**。

## 变更内容

1. 新增 `marginalia setup`（`--dry-run` / `--check` / `--no-skill` / `--force`）：
   一次命令完成「建数据根 → 建 owner → 装 skill 副本 → 写 `deployment.json` → 自证」。
2. 新增部署状态机：`absent` → `partial` → `stale` → `ready`，`--check` 用退出码表达。
3. 新增**漂移检测**：安装的 `SKILL.md` 与仓库版本 sha256 不一致即 `stale`（exit 3），防止「代码升级了、skill 还是旧的」。
4. 新增**外来 skill 目录保护**（G10 部署闸）：目标目录已有别的技能（manifest id 不同）→ 拒绝覆盖，除非 `--force`。
5. 新增 `AGENT_DEPLOY.md`（agent 面协议，每步带命令/期望/失败分支）+ `references/deployment.md`（内部细节）。
6. README 开头新增「给 agent 的部署指令」区块（中/英双份）。
7. SKILL.md §0 增加部署门：命令不存在 → 转 `AGENT_DEPLOY.md`，不许硬猜。
8. 新增 `scripts/deploy.sh` / `scripts/deploy.cmd` 一键包装。
9. 新增文档-代码一致性测试：文档里出现的 `marginalia <子命令>` 必须真实存在。

## 不做

- 不做包管理器之外的自动下载（不联网装 Python）
- 不自动写用户没指定的 skill 目录（找不到就报错并给候选，绝不擅自写 `~/.claude`）
- 不改动 CHG-001 已定的九道闸语义

## 授权记录

| 动作 | 授权方 | 依据 | 时间 |
|---|---|---|---|
| SPEC 批准 | **user** | 本会话指令：「commit push 上去，相关功能记得一定开发测试好」 | 2026-11-16 |
| **commit** | **user** | 同上（原话：「然后 commit push 上去」） | 2026-11-16 |
| **push** | **user** | 同上 | 2026-11-16 |

> ai-spec 禁止 agent 自我批准。以上为用户显式授权，记录在此以便审计；不是 agent 自签。

## 关联

- 产品需求：`PRD.md`
- 前置契约：`tasks/CHG-001-multiuser-io/SPEC.md`
- 本契约：`tasks/CHG-002-agent-deploy/SPEC.md`
- 追溯矩阵：`tasks/CHG-002-agent-deploy/TRACEABILITY.md`
