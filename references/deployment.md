# 部署实现细节（维护者向）

`AGENT_DEPLOY.md` 是**执行协议**（给 agent 照着做）；
本文件是**实现说明**（给改代码的人看）。两者不一致时以代码为准，并回来改文档。

---

## 1. 分层：谁负责什么

| 层 | 位置 | 职责 | 不负责 |
|---|---|---|---|
| 协议 | `AGENT_DEPLOY.md` | 告诉 agent 按什么顺序做、失败怎么办 | 不实现任何逻辑 |
| 包装脚本 | `scripts/deploy.sh` / `deploy.cmd` | 找 Python、设 UTF-8、转调 CLI | 不做判断 |
| 编排 | `marginalia/setup.py` | 预检、建根、建 owner、装 skill、记账、自证 | 不管教学逻辑 |
| 底座 | `store / registry / verify / render` | 复用 CHG-001 的能力 | — |

**只有一处实现**：逻辑全在 `setup.py`，脚本是薄包装。这样 Windows 与 Unix 不会分叉。

---

## 2. `marginalia setup` 的执行顺序

顺序是刻意设计的：**所有前置校验都在第一次写盘之前完成**。

```
① python_ok()                     ← 版本不够，直接失败，磁盘零改动
② resolve_skills_root()           ← 没给 --skills-dir，直接失败，磁盘零改动
③ 参数成对校验（owner 两个参数）    ← 同上
④ 建数据根（registry.json / INDEX.md）
⑤ 建 owner（若指定）
⑥ 装 skill 副本（G10 检查在前）
⑦ check_setup() 自证 → 得到状态
⑧ 写 deployment.json
```

早期版本把 ⑥ 放在 ④ 之后，导致"没给 `--skills-dir` 却已经建了数据根"——
属于**校验滞后于写入**。已修（见 CHG-002 的测试 `test_no_skills_dir_writes_nothing`）。

---

## 3. 状态机

```python
STATE_ABSENT  = "absent"   # 数据根未初始化            → exit 1
STATE_PARTIAL = "partial"  # 根有了，但缺记录/缺副本   → exit 1
STATE_STALE   = "stale"    # 副本哈希不符 / 仓库已更新 → exit 3
STATE_BROKEN  = "broken"   # verify 报完整性错误      → exit 3
STATE_READY   = "ready"    # 全部通过                 → exit 0
```

判定顺序（`check_setup`）：

1. 根没初始化 → `absent`（**立即返回**，不看记录）
2. 没有 `deployment.json` → `partial`
3. skill 副本文件不存在 → `partial`
4. 副本哈希 ≠ 记录哈希 → 标记 stale（副本被改过）
5. 副本哈希 ≠ 仓库 `SKILL.md` 哈希 → 标记 stale（仓库更新了）
6. `verify` 有错误 → 标记 broken
7. 否则 `ready`

**stale 优先于 broken**：副本都不可信了，先刷新再谈数据完整性。

---

## 4. 为什么用 sha256 而不是版本号

| 方案 | 问题 |
|---|---|
| 比版本号 | 文档改动（最高频）不会改版本号 → 永远发现不了 |
| 比 mtime | 复制 / 检出 / 解压都会重置时间 → 假阳性 |
| **比内容哈希** | 改一个字符就报 stale，且与文件系统无关 ✅ |

代价：仓库里 `SKILL.md` 加一个空行，所有已部署实例都会 `stale`。
这是**刻意的**——提示词是行为契约，改一个字就该重新部署。

---

## 5. G10 部署闸（防覆盖别人的技能）

```python
target = <skills-dir>/marginalia
if target 存在:
    读 target/skill.manifest.json 的 id
    if id 存在 and id != "marginalia"  → 拒绝（exit 3），除非 --force
    if id 不存在 but SKILL.md 存在     → 拒绝（exit 3），除非 --force
```

「同 id 直接覆盖」是有意放行的：那是上次部署的同一技能，刷新即可。

---

## 6. `deployment.json` 字段

| 字段 | 含义 |
|---|---|
| `schema` | 记录格式版本（不是项目版本） |
| `project_version` | 部署时的 `marginalia.__version__` |
| `deployed_at` | **首次**部署时间（重复部署不会被覆盖） |
| `updated_at` | 最近一次写入时间 |
| `python` | 部署时的解释器版本 |
| `mode` | `strict`（本命令能跑即代表有执行通道） |
| `root` | 数据根绝对路径 |
| `skill` | `null` 表示 `--no-skill`；否则含 dir/file/哈希/安装时间 |
| `checks` | 最近一次自证的逐项结果 |

放在**数据根**而不是项目目录：项目目录可能只读（装进 site-packages），
且同一个项目可能部署到多个数据根。

---

## 7. 幂等性保证

| 对象 | 重复执行的后果 |
|---|---|
| 数据根 | 已存在则跳过，不重建 |
| owner | 按 `open_id` 查找；已存在则跳过并提示 |
| skill 副本 | 逐文件比较内容；相同则跳过，不刷 mtime |
| `deployment.json` | 覆盖写入，但保留首次 `deployed_at` |
| 学员数据 | **从不触碰** |

---

## 8. 加新检查项的正确姿势

1. 在 `check_setup()` 里追加一个 `Check(name=...)`；
2. 同名检查由 `_dedupe()` 自动去重（保留最后一次结果），不必手动防重；
3. 若该检查失败意味着"必须重新部署"，置 `stale`；
   若意味着"数据本身不可信"，置 `broken`；
4. 补一条测试到 `tests/test_setup.py`；
5. 若新增 CLI 命令，补 `tests/test_docs_consistency.py` 的文档一致性断言。

---

## 9. 脚本包装的边界

`scripts/deploy.sh` / `deploy.cmd` 只做三件事：

1. 定位 Python（`python3` → `python` → `py -3`）
2. 设 `PYTHONUTF8=1`（Windows 必需）
3. 把参数原样转给 `marginalia setup`

**不在这里加业务判断**。想加能力，改 `setup.py`。

---

## 10. 已知边界

- B 模式（无执行通道）无法被 `--check` 检测——没有执行通道就没有检测器。
- `--dry-run` 不做真实写入，因此它报的就是 `partial`（而不是"将要 ready"）。
- 目前不支持"一个 skills 目录装多份同名技能"。
- Windows 上如果 `python` 被 Microsoft Store 的假执行别名占位，脚本会回退到 `py -3`。
