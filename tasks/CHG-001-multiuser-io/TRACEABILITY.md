# TRACEABILITY · CHG-001

需求 → 实现 → 证据。任一行为空即为未闭环。

## 1. 产品需求 → 验收 → 实现

| 产品判据（PRD §5） | AC（SPEC §8） | 实现位置 | 证据（测试/命令） |
|---|---|---|---|
| P1 未注册身份无法写入 | AC1 | `registry.resolve` 抛 exit 2；`cli.py` 全部命令先解析身份 | `test_identity_and_paths.py::test_unknown_user`（含磁盘快照对比） |
| P2 同学异注互不出现 | AC4 | 路径由 `Store.book_dir(uid, slug)` 派生；批注落 `users/<uid>/books/<slug>/` | `test_two_users_same_book`、`test_progress_isolated`、端到端演练 |
| P3 改原文即被发现 | AC5 | `meta.source_sha256` + `books.read_source` 校验 | `test_source_tamper` |
| P4 进度可续到原句 | AC7 | `progress set` → `meta.progress/next` → `render` 课程卡 | `test_progress_card`、`test_card` |
| P5 结课产物离线可读 | AC7 | `render` 生成单文件 `book.md`；`export` 复制 | `test_quote_needs_blank_line`、`test_source_verbatim`、演练导出 |
| P6 无执行通道可事后判定 | AC15/16 | `lint.py` L1–L8 | `test_poison`、`test_no_card`、`test_uid_marker`、`test_expect_uid` |

## 2. 硬闸 → 实现 → 证据

| 闸 | 拦截点 | 退出码 | 证据 |
|---|---|---|---|
| G1 身份 | `registry.resolve` | 2 | `test_unknown_user` |
| G2 路径 | `store.validate_slug` / `book_dir` 真实路径包含 | 2 | `test_bad_slug`、`test_bad_slug_create`、`test_dot_slug` |
| G3 归属 | `books._assert_ownership`；`notes._assert_note_ownership` | 3 | `test_meta_tamper`、`test_bad_uid` |
| G4 说话人 | `registry.speaker_of`（无外部参数） | 3 | `test_wrong_speaker` |
| G5 锚点唯一 | `books.locate_anchor` | 3 | `test_missing_anchor`、`test_ambiguous_anchor` |
| G6 原文哈希 | `books.read_source` | 3 | `test_source_tamper` |
| G7 审计链 | `audit.verify_chain` | 3 | `test_chain_break`、`test_chain_tamper` |
| G8 并发 | `Store.lock`（可重入）+ 库函数自锁 | — | `test_parallel_notes`（20 线程，调用方不加锁） |
| G9 渲染一致 | `render.is_render_fresh` | 3 | `test_render_tamper` |

## 3. 退出码 → 处置（SKILL v3 §1.5）

| 码 | 语义 | 文档位置 |
|---|---|---|
| 0 | 成功 | `references/io-contract.md` §3 |
| 1 | 一般错误 | 同上 |
| 2 | 身份/权限/路径 | 同上 + `SKILL.md` §1.5 |
| 3 | 完整性违规 | 同上 + `SKILL.md` §1.5（明写"不许重试"） |

## 4. 里程碑 → 交付物

| 里程碑 | 交付物 | 状态 |
|---|---|---|
| M1 契约 | `PRD.md`、`CHANGE.md`、`SPEC.md` | ✅ |
| M2 存储与身份 | `util/store/registry/audit` | ✅ |
| M3 书与批注 | `books/notes/render` | ✅ |
| M4 自证 | `verify/lint` | ✅ |
| M5 迁移 | `importer` | ⚠️ 对文档格式已验证；真实文件未验证（不在本机） |
| M6 技能与文档 | `SKILL.md` v3、`io-contract`、`lesson-record-format`、`MIGRATION`、`README`(+en)、`CHANGELOG`、`CONTRIBUTING`、`SECURITY` | ✅ |
| M7 工程规范 | `.editorconfig`、`MANIFEST.in`、`py.typed`、ruff/mypy 配置、CI 矩阵 | ✅ |

## 5. 未闭环项（必须显式列出，不得隐藏）

| 项 | 原因 | 关闭条件 |
|---|---|---|
| 真实 OpenClaw 是否有 shell | 部署不在本机 | 运行 `marginalia doctor`，看是否打印"模式 A · strict" |
| 真实 `鬼谷子.md` 的 import 往返 | 文件不在本机 | `marginalia import ... `（dry-run）输出条数与旧文件一致 |
| 长期多用户压力 | 无生产数据 | 连续多周真实使用后 `verify --check-render` 持续为 0 |
