# HEALTH · 项目健康基线

- 快照日期：2026-11-16
- 版本：3.1.0（CHG-002 部署链路）
- 性质：**轻量基线**（非完整的 project-health-audit）。只记录可复现的客观状态，不替代审计。

---

## 1. 静态质量

| 项 | 工具 | 结果 |
|---|---|---|
| Lint | `ruff check .`（E/F/W/I/B，line-length 100） | **0 error / 0 warning** |
| 格式 | `ruff format --check .` | **全部已格式化** |
| 类型 | `mypy`（14 source files，目标 py3.10） | **Success: no issues found** |

## 2. 测试

| 项 | 结果 |
|---|---|
| 命令 | `python -X utf8 -m unittest discover -s tests -t .` |
| 规模 | 77 项（含 CHG-002 部署链路与兼容守卫的 31 项） |
| 结果 | **OK**（约 20 s，含大量真实文件 IO） |
| 覆盖 | CHG-001：AC1–AC11、AC15–AC16、AC18；CHG-002：AC1–AC12。含 20 线程并发、串档注入、路径穿越、审计断链、部署漂移、G10 部署闸、文档-代码一致性 |
| 框架 | 标准库 `unittest`（刻意不依赖 pytest：克隆即可跑） |

## 3. 构建与打包

| 项 | 结果 |
|---|---|
| `python -m build` | 成功产出 sdist + wheel |
| 构建警告 | **0**（PEP 639 元数据已修正；此前 3 处废弃警告已清） |
| wheel 内容 | 含 `marginalia/py.typed`、`licenses/LICENSE`、`entry_points.txt` |
| sdist 内容 | 含 `SKILL.md`、`references/`、`assets/hero.svg`、`PRD.md`、`CHANGELOG.md`、`LICENSE` |
| 安装后命令 | `marginalia --version` → `3.1.0`（可在任意目录调用） |

## 4. 部署链路（CHG-002）

| 项 | 结果 |
|---|---|
| `marginalia setup` 一条命令 | 建数据根 + 建 owner + 装 skill 副本 + 写 `deployment.json` + 自证 |
| 幂等 | 连续两次 exit 0；owner 不重复；副本内容相同不重写 |
| 预检先于写入 | 缺 `--skills-dir` / owner 参数不成对 → exit 1 且磁盘**零改动**（已测） |
| 漂移检测 | 副本被改 / 仓库 `SKILL.md` 更新 → `stale` + exit 3 |
| G10 部署闸 | 目标目录属于其它技能 → exit 3；`--force` 才覆盖 |
| 状态机 | `absent`/`partial` → 1；`stale`/`broken` → 3；`ready` → 0 |
| 文档-代码一致性 | 文档里出现的 `marginalia <子命令>` 全部真实存在（自动断言） |
| 全局开关位置 | `--root` 写在子命令前或后两种写法都可用（文档主推写法已实测） |
| 启动脚本探测 | 按「真能跑且 ≥3.9」选解释器，可避开 Windows 应用商店占位符 |
| Python 3.9 兼容 | 静态守卫：源码不得使用 3.10+ 专属参数（`write_text(newline=)` / `zip(strict=)` 等） |
| 工具确定性 | `ruff` 钉死 0.13.0（本地与 CI 同一版本，避免 format 结果漂移） |

## 5. 性能基线（本机实测，单线程）

| 操作 | 输入 | 实测 |
|---|---|---|
| `book create` | 1.09 MB 中文底本 | 184 ms |
| `note add`（含文件锁 + 锚点定位） | 0.28 MB 底本 | 中位 44.6 ms / 最大 46.6 ms |
| `render` | 0.28 MB / 0.28 MB× | 33 ms / 44 ms（1 MB） |
| `verify --check-render` | 1 本书 + 10 条批注 | 107 ms |

结论：在「一本书 + 数十条批注」的真实教学尺度下，全部操作都在人的感知阈值内（< 200 ms）。

## 6. 已知技术债

| # | 债务 | 影响 | 处理计划 |
|---|---|---|---|
| D1 | `importer` 只能解析文档记载的旧格式 | 真实旧文件可能有偏差 | 拿到真实样本后补测试用例 |
| D2 | 数据结构未带 schema 迁移器（当前 `schema: 1`） | 未来改字段需手工迁移 | 首个 schema 升级时补 `migrate` 命令 |
| D3 | 锚点唯一性过严 | 金句反复出现的书需长锚点 | 刻意取舍，不做放宽 |
| D4 | 无跨设备同步 | 单人单机 | 不在范围内 |

## 7. 未验证项（不影响可用性，但不得当作已验证）

1. 真实 OpenClaw 部署是否有执行通道 → `marginalia doctor` 可判定
2. 真实批注本 `import` 往返 → 试运行可判定
3. 长期多用户压力 → 需真实使用周期

## 8. 复现方式

```bash
python -X utf8 -m ruff check . && python -X utf8 -m ruff format --check .
python -X utf8 -m mypy
python -X utf8 -m unittest discover -s tests -t .
python -m build
```
