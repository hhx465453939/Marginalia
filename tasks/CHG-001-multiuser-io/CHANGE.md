# CHANGE · CHG-001

## 变更请求（原文）

> 这个项目目前所有的功能实现都是基于 Markdown 文档的 skill 约束，其实缺少一个标准化的规则 IO。
> 尤其对多用户的分类整理、批注记录、学习进度记录，每个用户异步的学习记录都需要一套比较硬的代码 IO。
> ……担心它会出现幻觉，把 A 用户的一些学习进度转移到 B 用户上。
>
> （后续）
> 你再好好核查一下，开发规范，有没有遗漏，commit push 不要让我来做，你来做，但是必须把整个开发任务闭环掉。

## 触发原因

纯 prompt 约束无法防串档：身份靠上下文记忆、路径靠模型拼接、说话人靠模型填写，三者全部无校验。

## 变更内容

把「谁 / 写到哪 / 说话人写谁」三个决策从模型转移到代码：

- 新增确定性 IO 层 `marginalia/`（零依赖 CLI）
- 新增九道硬闸（G1–G9）与退出码语义（0/1/2/3）
- 新增双模式（A strict / B portable），并如实标注强度差异
- 新增 `verify`（事前+事后断言）与 `lint`（纯 Markdown 事后取证）
- 新增存量迁移 `import`（默认 dry-run）
- 改写 `SKILL.md` v3、`references/io-contract.md`、`references/lesson-record-format.md`
- 新增工程规范配套：PRD / CHG / TRACEABILITY / CHANGELOG / CONTRIBUTING / SECURITY / CI / LICENSE

## 不做

- 不改动任何真实学员数据（`study/` 下）
- 不做 Web UI / 数据库 / LLM 调用
- 不重写历史提交

## 授权记录（关键）

| 动作 | 授权方 | 依据 | 时间 |
|---|---|---|---|
| SPEC 批准 | **user** | 本会话指令："必须把整个开发任务闭环掉" | 2026-11-16 |
| **commit** | **user** | 同上："commit push 不要让我来做，你来做" | 2026-11-16 |
| **push** | **user** | 同上 | 2026-11-16 |

> 说明：ai-spec 禁止 **agent 自我批准**。以上三项均为**用户显式授权**，记录在此以便审计；
> 不是 agent 自签。

## 关联

- 产品需求：`PRD.md`
- 工程契约：`tasks/CHG-001-multiuser-io/SPEC.md`
- 追溯矩阵：`tasks/CHG-001-multiuser-io/TRACEABILITY.md`
