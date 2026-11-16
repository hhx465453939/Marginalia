# TRACEABILITY · CHG-002

需求 → 实现 → 证据。任一行为空即为未闭环。

## 1. 目标 → AC → 实现 → 证据

| 目标（SPEC §1.2） | AC | 实现位置 | 证据（测试/命令） |
|---|---|---|---|
| G-A 一条命令完成部署，幂等 | AC2 / AC3 | `setup.run_setup`、`cli.cmd_setup` | `test_setup.py::test_ready`、`test_idempotent`、`test_second_owner` |
| G-B `--check` 用退出码回答 | AC4 | `setup.check_setup` + `EXIT_BY_STATE` | `test_check_before`（1）、`test_check_after`（0） |
| G-C `deployment.json` 为唯一事实源 | AC7 | `setup._write_deployment` | `test_record`、`test_deploy_keeps_first_time` |
| G-D 副本漂移即 stale | AC8 | `check_setup` 的 `skill_integrity` / `skill_up_to_date` | `test_copy_drift`、`test_repo_drift` |
| G-E 找不到 skills 目录就失败 | AC6 | `resolve_skills_root` 显式化 | `test_need_skills_dir`（且断言不建数据根） |
| G-F 文档命令必须真实存在 | AC10 | `AGENT_DEPLOY.md` / `README*` / `SKILL.md` + 一致性测试 | `test_docs_consistency.py::test_commands_real` |

## 2. 断点 → 修复 → 证据

| 原断点（SPEC §1.1） | 修复 | 证据 |
|---|---|---|
| 入口断裂：命令没装时 SKILL.md 卡死 | SKILL.md §0 改为「先 `setup --check`」，并写明「命令不存在 → 走模式 B + 告知弱隔离」 | `test_docs_consistency.py::test_skill_points_to_protocol` |
| 无状态 | `<root>/deployment.json` | `test_record` |
| 无漂移检测 | sha256 比对（副本 vs 仓库） | `test_copy_drift`、`test_repo_drift` |
| 无冲突保护 | G10 部署闸 | `test_foreign`（exit 3）、`test_foreign_force` |
| 无顺序契约 | `AGENT_DEPLOY.md` 每步含「命令/期望/失败分支」，`check_setup` 预检先于写入 | `test_protocol_has_branches`、`test_need_skills_dir`、`test_owner_pair` |

## 3. 状态机 → 退出码 → 证据

| 状态 | 判据 | 退出码 | 证据 |
|---|---|---|---|
| `absent` | 数据根未初始化 | 1 | `test_check_before` |
| `partial` | 缺 `deployment.json` 或副本 | 1 | `test_need_skills_dir`、`test_owner_pair` |
| `stale` | 副本哈希不符 / 仓库已更新 | 3 | `test_copy_drift`、`test_repo_drift` |
| `broken` | `verify` 报完整性错误 | 3 | 复用 CHG-001 的 `test_bad_uid`、`test_source_tamper` |
| `ready` | 全部通过 | 0 | `test_ready`、`test_check_after` |

## 4. 文档链路（skill → script）覆盖

| 层 | 文件 | 与谁衔接 | 证据 |
|---|---|---|---|
| 协议 | `AGENT_DEPLOY.md` | agent 读它 → 调 CLI | `test_protocol_has_branches`、`test_files_exist` |
| 入口 | `README.md` / `README.en.md` 顶部 | 人/agent 读它 → 拿到四条命令 | `test_readmes_have_deploy` |
| 技能 | `SKILL.md` §0 | agent 每次会话先 `--check` | `test_skill_points_to_protocol` |
| 清单 | `skill.manifest.json` `deployment` 段 | 框架侧识别部署入口 | `test_manifest_has_deployment` |
| 脚本 | `scripts/deploy.{sh,cmd}` | 薄包装 → `marginalia setup` | `test_scripts_call_setup` |
| 实现 | `marginalia/setup.py` | 唯一逻辑实现 | 全部 `test_setup.py` |
| 细节 | `references/deployment.md` | 维护者向说明 | `test_files_exist` |

## 5. 开发中修掉的缺陷（当场修，未遗留）

| # | 缺陷 | 根因 | 修复 |
|---|---|---|---|
| 1 | 不带 `--skills-dir` 时仍会建数据根 | 校验滞后于写入 | 预检全部前置条件提前到任何写盘之前 |
| 2 | 探测到 `~/.claude/skills` 就自动往里装 | 把「候选」当「决定」，等于擅自改用户环境 | 改为必须显式 `--skills-dir`，候选只出现在报错建议里 |
| 3 | 检查项重复输出 | `run_setup` 与 `check_setup` 都产出同名项 | `_dedupe()` 同名保留最后一次 |
| 4 | `--no-skill` 被误判为 `partial` | `None` 同时表示「无期望值」与「期望无 skill」（哨兵歧义） | 引入 `_UNSET` 哨兵 |
| 5 | 文档一致性测试把 YAML frontmatter 当正文 | `name: marginalia` + 换行 `description:` 被匹配成命令 | 扫描前剥离 frontmatter（而非给测试加白名单） |
| 6 | `bin/marginalia` / `scripts/deploy.sh` 在本机直接失败 | 按「PATH 里有」选解释器：Windows 上 `python3` 是应用商店占位符，`command -v` 成功但执行报错 | 改为**实际执行一次并校验 ≥ 3.9**，回退链补 `py -3`；`deploy.cmd` 同步改成 `where` + 执行探测 |
| 7 | 文档主推命令 `marginalia setup --root ...` 直接报 `unrecognized arguments` | argparse 只接受子命令**之前**的全局选项，而文档写的是子命令之后 | CLI 新增 `_hoist_global_flags()`：两种位置都接受；只提取独立令牌，不误伤 `--text` 正文 |
| 8 | CI 的 py3.9 两个作业崩：`TypeError: write_text() got an unexpected keyword argument 'newline'` | `Path.write_text(newline=)` 是 **Python 3.10+** 才有的参数；本地开发在 3.13，测不出来 | 改用仓库已有的 `atomic_write`（内部 `os.fdopen(newline="\n")`，3.9 可用）；新增 `tests/test_compat.py` 用 AST 静态拦 3.10+ 专属参数 |
| 9 | 同一个 commit 本地 `ruff format --check` 绿、CI 红 | `ruff>=0.6` 未钉版本：本地 0.13.0、CI 拿到新版，formatter 默认值跳版本变了 | dev 依赖与 CI 均钉死 `ruff==0.13.0`；升版必须同步跑 `ruff format .` 并提交 |

> 第 8、9 条的共同点：**本地环境比 CI 新/不同**，本地全绿说明不了 CI 不会红。
> 对策是把「环境差异」变成可执行的断言（静态兼容守卫 + 工具版本钉死），而不是靠记性。

> 第 1、2 条是我自己在这一轮引入的——冒烟测试时真的往本机 `~/.claude/skills/marginalia` 装了副本，
> 已当场确认（manifest id 一致）后删除，并改成「必须显式指定」。
>
> 第 6、7 条是**实测脚本才发现的**：只写「脚本存在」的断言完全测不出来。
> 教训——AC11 的判据必须是「脚本真能跑」，不是「文件在不在」。

## 6. 未闭环项

| 项 | 原因 | 关闭条件 |
|---|---|---|
| B 模式无法被 `--check` 检测 | 无执行通道就没有检测器 | 架构性限制，已在 `AGENT_DEPLOY.md` §6 明写，不视为缺陷 |
| 真实 OpenClaw 上跑一次完整部署 | 部署不在本机 | 用户在目标机跑 `marginalia setup --check` 并回传输出 |
| 多台机器批量分发 | 不在本 CHG 范围（SPEC §1.3 非目标） | 需要时单独立 CHG |
| **一次不可复现的测试失败** | 开发中曾出现一次 `FAILED (failures=1)`，随后连跑 3 轮全量 + 并发用例 10 轮 + 部署用例 10 轮，**共 23 次全绿，无法复现** | 若 CI 重现，将它固定成一条回归用例；在此之前不凭猜测改测试或代码 |
