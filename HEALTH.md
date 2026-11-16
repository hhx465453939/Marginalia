# HEALTH · 项目健康基线

- 快照日期：2026-11-16
- 版本：3.0.0（commit `7ff55e2` 之后的本轮补全）
- 性质：**轻量基线**（非完整的 project-health-audit）。只记录可复现的客观状态，不替代审计。

---

## 1. 静态质量

| 项 | 工具 | 结果 |
|---|---|---|
| Lint | `ruff check .`（E/F/W/I/B，line-length 100） | **0 error / 0 warning** |
| 格式 | `ruff format --check .` | **20 files already formatted** |
| 类型 | `mypy`（13 source files，目标 py3.10） | **Success: no issues found** |

## 2. 测试

| 项 | 结果 |
|---|---|
| 命令 | `python -X utf8 -m unittest discover -s tests -t .` |
| 规模 | 46 项 |
| 结果 | **OK**（约 17 s，含大量真实文件 IO） |
| 覆盖 | AC1–AC11、AC15–AC16、AC18；含 20 线程并发、串档注入、路径穿越、审计断链 |
| 框架 | 标准库 `unittest`（刻意不依赖 pytest：克隆即可跑） |

## 3. 构建与打包

| 项 | 结果 |
|---|---|
| `python -m build` | 成功产出 sdist + wheel |
| 构建警告 | **0**（PEP 639 元数据已修正；此前 3 处废弃警告已清） |
| wheel 内容 | 含 `marginalia/py.typed`、`licenses/LICENSE`、`entry_points.txt` |
| sdist 内容 | 含 `SKILL.md`、`references/`、`assets/hero.svg`、`PRD.md`、`CHANGELOG.md`、`LICENSE` |
| 安装后命令 | `marginalia --version` → `3.0.0`（可在任意目录调用） |

## 4. 性能基线（本机实测，单线程）

| 操作 | 输入 | 实测 |
|---|---|---|
| `book create` | 1.09 MB 中文底本 | 184 ms |
| `note add`（含文件锁 + 锚点定位） | 0.28 MB 底本 | 中位 44.6 ms / 最大 46.6 ms |
| `render` | 0.28 MB / 0.28 MB× | 33 ms / 44 ms（1 MB） |
| `verify --check-render` | 1 本书 + 10 条批注 | 107 ms |

结论：在「一本书 + 数十条批注」的真实教学尺度下，全部操作都在人的感知阈值内（< 200 ms）。

## 5. 已知技术债

| # | 债务 | 影响 | 处理计划 |
|---|---|---|---|
| D1 | `importer` 只能解析文档记载的旧格式 | 真实旧文件可能有偏差 | 拿到真实样本后补测试用例 |
| D2 | 数据结构未带 schema 迁移器（当前 `schema: 1`） | 未来改字段需手工迁移 | 首个 schema 升级时补 `migrate` 命令 |
| D3 | 锚点唯一性过严 | 金句反复出现的书需长锚点 | 刻意取舍，不做放宽 |
| D4 | 无跨设备同步 | 单人单机 | 不在范围内 |

## 6. 未验证项（不影响可用性，但不得当作已验证）

1. 真实 OpenClaw 部署是否有执行通道 → `marginalia doctor` 可判定
2. 真实批注本 `import` 往返 → 试运行可判定
3. 长期多用户压力 → 需真实使用周期

## 7. 复现方式

```bash
python -X utf8 -m ruff check . && python -X utf8 -m ruff format --check .
python -X utf8 -m mypy
python -X utf8 -m unittest discover -s tests -t .
python -m build
```
