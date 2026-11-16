# Changelog

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

（暂无）

## [3.0.0] - 2026-11-16

首个公开版本。技能 id 由 `tutor-progress` 更名为 `marginalia`（保留 legacy 别名）。

### Added

- 确定性 IO 层 `marginalia` CLI（零依赖，Python 3.9+）
  - `init` / `user add|resolve|list` / `book create|list`
  - `chapter mark` / `progress set` / `note add`
  - `render` / `export` / `stats` / `doctor`
- 九道硬闸：身份、路径、归属、说话人、锚点唯一、原文哈希、审计链、并发、渲染一致
- 退出码语义：`0` 成功 / `1` 一般错误 / `2` 身份或路径 / `3` 完整性违规
- 批注 append-only（`annotations.jsonl`）+ 由真源渲染的交付物（`book.md`）
- 审计链（`audit.jsonl`，链式哈希，删改一行即断链）
- `verify`：完整性断言，支持 `--strict` / `--check-render` / `--json`
- `lint`：**无执行通道时**的纯 Markdown 事后审计（规则 L1–L8，精确到行号）
- `import`：旧单文件批注本迁移（默认 dry-run，锚点无法唯一时落 `_unresolved.jsonl`）
- 双模式运行：A `strict`（硬隔离）/ B `portable`（协议级，**弱隔离**，如实标注）
- `doctor`：环境自检 + 能力边界输出

### Changed

- 技能 id：`tutor-progress` → `marginalia`（`skill.manifest.json` 记录 `legacy_ids`）
- 数据布局：单文件批注本 → `users/<uid>/books/<slug>/`（`meta.json` + `source.md` + `annotations.jsonl` + `book.md`）
- 说话人不再由模型填写，改由注册表派生
- 进度不再手写表格，改由 `meta.json` 派生并由 `render` 生成

### Fixed

- `ruff` 首轮报出 18 个真实问题：11 处未用导入、6 处歧义变量名（`l`）、1 处未用局部变量（保留其副作用调用）
- 构建期 3 处 PEP 621/639 元数据废弃警告（2027-02 将硬失败）→ 迁移到 SPDX 表达式后归零
- `Store.lock` 超时消息里的 `{.0 + timeout:.0f}` 怪表达式 → `{timeout:.0f}`，并按 B904 显式 `from None`
- Windows GBK 控制台导致中文/符号输出崩溃 → 入口强制 UTF-8，`bin/marginalia.cmd` 设 `PYTHONUTF8=1`
- CI：`ubuntu-latest` 已滚到 26.04，其中无 Python 3.9 构建（实测 `The version '3.9' ... was not found for Ubuntu 26.04`）→ 矩阵改为按版本钉 runner（3.9 → `ubuntu-22.04`，3.11/3.13 → `ubuntu-24.04`），并把 `checkout` / `setup-python` 升到真实存在的 v7（避开 Node 20 弃用）
- 引用块紧贴原文被 CommonMark 当作段落续行（批注不渲染）→ 渲染时强制空行分隔
- 篇目识别误把 `# 书名` 当作篇目 → 文档标题存在时篇目级别下探一层
- 迁移器把 `**讨论**` / `**进度**` 标签误当说话人、把 `**【第1课】**` 误当人名 → 仅 `👤` 承载"人"
- `lint` 误审 `source.md` / `INDEX.md` → 发现范围限定为 `books/*/book.md`
- 并发保护只长在 CLI、库函数裸奔 → `Store.lock` 支持同线程重入，写库函数自带锁

### Security

- 学员数据目录 `study/` 加入 `.gitignore`，禁止入库
- 移除文档与测试夹具中的真实 `open_id` 与真实人称

### Docs

- `README.md`（中文）、`README.en.md`（英文）、`MIGRATION.md`
- `SKILL.md` v3（双模式）、`references/io-contract.md`（规则 IO 契约）、`references/lesson-record-format.md`
- `PRD.md`、`tasks/CHG-001-multiuser-io/{CHANGE,SPEC,TRACEABILITY}.md`
- `CONTRIBUTING.md`、`SECURITY.md`、`LICENSE`(MIT)、CI（Ubuntu + Windows × py3.9/3.11/3.13）

### 工程规范

- 新增 `PRD.md`（产品需求）与 `HEALTH.md`（健康基线）
- 新增 `tasks/CHG-001-multiuser-io/{CHANGE,TRACEABILITY}.md`，`SPEC.md` 升 v2：补 YAML 契约头、ADR（四个被否方案）、性能预算、可观测性、发布回滚、运维归属、授权边界、DoR/DoD、评审门、AC19–AC24
- 新增 `CONTRIBUTING.md`、`SECURITY.md`、`.editorconfig`、`MANIFEST.in`、`README.en.md`
- 新增 `marginalia/py.typed`（PEP 561），声明 `Typing :: Typed`
- 新增 `[tool.ruff]` / `[tool.mypy]` 配置；CI 拆为 `test` / `lint` / `typecheck` / `package` 四个作业
- 元数据迁移到 PEP 639：`license = "MIT"` + `project.license-files`，`setuptools>=77`

### Tests

- 46 项自动化测试，覆盖 AC1–AC11、AC15–AC16、AC18，含 20 线程并发与串档注入

### Known limits

- 未在真实多用户生产环境长期运行
- 仅处理 Markdown 底本（EPUB/PDF 需先转文本）
- B 模式为协议级约束，模型可以违反；只能事后取证
