# 贡献指南

先读这两份，再动代码：

- `PRD.md` —— 这个项目解决什么问题、不解决什么问题
- `tasks/CHG-001-multiuser-io/SPEC.md` —— 九道硬闸与退出码语义

## 环境

- Python 3.9+（仅标准库，零运行时依赖）
- Windows / macOS / Linux 均可

```bash
git clone https://github.com/hhx465453939/Marginalia.git
cd Marginalia
python -m pip install -e ".[dev]"     # 或 python -m pip install -e .
```

**Windows 注意**：本项目输出全中文，必须 `set PYTHONUTF8=1`（`bin\marginalia.cmd` 已代劳）。
否则控制台会按 GBK 编码，中文参数与符号会乱码甚至抛 `UnicodeEncodeError`。

## 命令

```bash
python -X utf8 -m unittest discover -s tests -t .   # 全部测试（46 项）
python -X utf8 -m ruff check .                      # 静态检查
python -X utf8 -m ruff format --check .             # 格式检查
python -X utf8 -m mypy                              # 类型检查（需 pip install mypy）
python -m build                                     # 构建 sdist + wheel
python -X utf8 -m marginalia doctor                 # 环境自检
```

提交前请保证这四条全绿（与 CI 一致）：`ruff check`、`ruff format --check`、`mypy`、`unittest`。

无 `pytest` 依赖是刻意的：测试只用标准库 `unittest`，克隆即可跑。
`ruff` / `mypy` / `build` 是**开发期可选依赖**：`python -m pip install -e ".[dev]"`。

## 代码规范

| 项 | 约定 |
|---|---|
| 行宽 | 100 |
| 引号 | 双引号 |
| 类型注解 | 所有公开函数必须标注；`from __future__ import annotations` |
| 注释 | 中文；解释**为什么**，不复述代码 |
| 错误 | 一律抛 `MarginaliaError(message, code, hint)`，`hint` 给出可执行的下一步 |

`ruff` 配置见 `pyproject.toml`。提交前必须 `ruff check .` 全绿。

## 三条不可违反的约定

1. **不许新增"由调用方记得加锁"的写入路径** —— 写库函数必须自带 `store.lock`。
2. **不许把路径作为参数暴露给上层** —— 路径只能由 `(uid, slug)` 派生。
3. **不许让说话人从外部传入** —— `speaker` 只能由 `registry.speaker_of` 派生。

违反任一条，等于把已经堵住的串档口子重新打开。评审会直接打回。

## 隐私红线

- **绝不提交 `study/` 目录**（已加入 `.gitignore`）。里面是真实学员的批注。
- 提交前跑一次隐私扫描：
  ```bash
  grep -rn "ou_[a-f0-9]\{20,\}" --include="*.md" --include="*.py" --include="*.json" .
  ```
- Issue / PR 中不要贴真实批注正文；用 `主人` / `小林` 之类的示例名。
- 发现泄漏，按 `SECURITY.md` 处理。

## 变更流程

本仓库用 CHG（change）契约管理改动，位置 `tasks/<CHG-id>/`：

```
tasks/CHG-000-template/
├── CHANGE.md        # 变更请求原文 + 授权记录
├── SPEC.md          # 工程契约（YAML 头 + 必需章节）
└── TRACEABILITY.md  # 需求 → 实现 → 证据
```

- 小修（错字、注释）：直接 PR。
- 触及硬闸、数据结构、CLI 契约：**必须先立 CHG**，在 SPEC 里写清"改完哪条 AC 变绿"。
- 不覆盖历史版本：改契约用追加章节（amendment），不改旧结论。

## 提交信息

Conventional Commits，中文正文可：

```
feat: 新增 lint 对 _unresolved.jsonl 的检查
fix: 锚点跨行时偏移计算错位
docs: 补充 B 模式的书房指针示例
test: 覆盖 20 线程并发追加
chore: 升级 CI 矩阵到 py3.13
```

## 测试要求

- 修 bug：先写一条能复现的失败测试，再修。
- 加闸门：必须同时有一条"绕过尝试被拒绝"的负向测试。
- 新增 CLI 命令：必须覆盖 `exit 2` / `exit 3` 场景。
