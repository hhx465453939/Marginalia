# Changelog

本文件格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added

- `marginalia setup`：一条命令完成部署——预检 → 建数据根 → 建 owner → 装 skill 副本 → 写 `deployment.json` → 自证；支持 `--dry-run` / `--check` / `--no-skill` / `--force`，幂等
- 部署状态机 `absent / partial / stale / broken / ready`，`--check` 用退出码表达（0 / 1 / 3）
- **漂移检测**：安装副本与仓库 `SKILL.md` 的 sha256 不一致即 `stale`，避免“代码升级了、skill 还是旧的”
- **G10 部署闸**：目标技能目录属于其它技能时拒绝覆盖，除非 `--force`
- `AGENT_DEPLOY.md`：agent 面部署协议，每步含命令 / 期望输出 / 失败分支；含 B 模式（无执行通道）手工路径
- `references/deployment.md`：实现细节（状态机、G10、幂等性、已知边界）
- `scripts/deploy.sh` / `scripts/deploy.cmd`：只负责找 Python + 设 UTF-8 + 转调 CLI 的薄包装
- `doctor` 新增「部署状态」段：版本 / skill 路径 / 失败检查项 / 修复命令
- README（中/英）开头新增「部署」区块：可直接转给 agent 的一句自然语言指令 + 四条命令 + 退出码含义
- `SKILL.md` §0 新增部署门：命令不存在时不再卡住，指向 `AGENT_DEPLOY.md`

### Changed

- 版本号收敛到单一真源 `marginalia.__version__`；`marginalia --version` 不再硬编码，
  并由测试断言与 `pyproject.toml` 一致
- `ruff` 从 `>=0.6` 改为钉死 `==0.13.0`（dev 依赖与 CI 同步）：
  formatter 默认值会跳版本变动，未钉时本地绿、CI 红

### Fixed

- 修正部署预检顺序：`--skills-dir` / 参数成对校验提到**任何写盘之前**（此前会先建数据根再报错）
- 取消“自动使用探测到的 skills 目录”：写入用户技能目录必须显式 `--skills-dir`，避免擅自修改用户环境
- 部署检查项去重（`root_initialized` 等此前会重复输出）
- 启动脚本 `bin/marginalia` / `scripts/deploy.sh` 按「PATH 里有」选解释器，在 Windows 上会选中
  Microsoft Store 占位符（`python3` 存在但不可执行）→ 改为**实际执行一次并校验 ≥ 3.9**，并在回退链里补上 `py -3`
- `--root` 作为全局选项此前只能写在子命令**之前**，而 README / `AGENT_DEPLOY.md` / `deploy.sh`
  用的是更自然的 `marginalia setup --root ...`——文档里的主推命令会报 `unrecognized arguments`。
  现改为两种位置都接受（只提取独立令牌，不误伤 `--text` 正文）
- **Python 3.9 崩溃**：`install_skill` 用了 `Path.write_text(..., newline="\n")`，而 `newline` 参数是
  3.10 才加的（CI 实证 `TypeError: write_text() got an unexpected keyword argument 'newline'`）
  → 改用仓库已有的 `atomic_write`（内部 `os.fdopen(newline="\n")`，3.9 可用）
- 新增 `tests/test_compat.py` 静态守卫：用 AST 扫源码，拦住 3.10+ 专属参数，
  避免「本地 3.13 绿、CI 3.9 红」的反馈环过长

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
