# 规则 IO 契约（Agent 与数据之间的唯一接口）

> 这份文件不是建议，是**接口定义**。
> 任何绕过这里的写入，都等于放弃隔离保证。

---

## 1. 为什么需要契约

纯 Markdown 约束下，Agent 干三件事时无人校验：**记住我是谁**、**拼出文件路径**、**决定说话人写谁**。
契约的作用是把这三件事从"模型的自觉"变成"接口的强制"：

| 决策 | 谁做 | 输入 | 校验 |
|---|---|---|---|
| 我是谁 | `--as` 令牌 → 注册表 | 用户消息 sender_id | 不在注册表 → exit 2 |
| 写到哪 | 由 `uid + slug` 派生 | 无（不可指定路径） | slug 白名单 + 真实路径包含检查 |
| 说话人写谁 | 注册表 `name` | 无（无此参数） | 落盘前断言 `note.uid == 书房 uid` |

**核心原则：Agent 不传路径，只传身份。**

---

## 2. 唯一写通道

```bash
marginalia <command>
```

| 操作 | 命令 |
|---|---|
| 建数据根 | `init --owner-open-id <id> --owner-name <称呼>` |
| 建档 | `user add --open-id <id> --name <称呼> [--goal] [--pace] [--role]` |
| 解析身份 | `user resolve --open-id <id>` / `--name <称呼>` / `<token>` |
| 开课 | `book create --as <身份> --title <书名> --source <底本.md> [--slug] [--edition]` |
| 篇目状态 | `chapter mark --as <身份> --book <slug> --chapter <篇名> --status 未讲\|进行中\|已讲` |
| 进度 | `progress set --as <身份> --book <slug> --chapter <篇名> --segment <段> --anchor <原句> [--next-anchor <原句>]` |
| 批注 | `note add --as <身份> --book <slug> --kind <kind> --anchor <原句> --text <正文> [-l N] [--on-behalf <uid>]` |
| 渲染 | `render --as <身份> --book <slug> [-o <path>]` / `render --indexes-only` |
| 导出 | `export --as <身份> --book <slug> [--out <dir>] [--on-behalf <uid>]` |
| 校验 | `verify [--as] [--book] [--strict] [--check-render] [--json]` |
| 审计纯 Markdown | `lint [paths...] [--expect-uid <uid>]` |
| 迁移旧文件 | `import --as <身份> --from <旧.md> [--apply] [--force-speaker]` |
| 自检 | `doctor` |

`--as` 接受 uid / open_id / 称呼 / 别名，大小写不敏感。

---

## 3. 退出码语义（必须按此处置）

| 码 | 名称 | 含义 | Agent 应做 |
|---|---|---|---|
| 0 | OK | 成功 | 继续 |
| 1 | ERROR | 一般错误（文件缺失、参数错） | 读 hint 修正后重试一次 |
| 2 | IDENTITY | 身份 / 权限 / 路径越界 | **停下**，向用户确认；未建档则 `user add` |
| 3 | INTEGRITY | 完整性违规 | **立即停止写入**，把原文报错交给用户判断 |

`3` 的具体来源：归属冲突（G3）、说话人不匹配（G4）、锚点不唯一（G5）、原文被改（G6）、审计断链（G7）、渲染不一致（G9）。

---

## 4. 数据结构（schema）

### 4.1 `study/registry.json` — 身份唯一真源

```json
{
  "schema": 1,
  "users": [
    {
      "uid": "owner",
      "open_ids": ["ou_xxx"],
      "name": "主人",
      "aliases": [],
      "role": "owner",
      "status": "active",
      "joined": "2026-11-16",
      "profile": { "goal": "", "pace": "" }
    }
  ]
}
```

约束：`uid` 唯一且匹配 `^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_-]{0,63}$`；`open_ids` 全局唯一；`role ∈ {owner, student}`；**owner 至多一个**（`role=owner` 时 uid 固定为 `owner`）。

### 4.2 `users/<uid>/books/<slug>/meta.json` — 课程元数据

```json
{
  "schema": 1,
  "slug": "鬼谷子",
  "title": "鬼谷子",
  "uid": "owner",
  "student": "主人",
  "edition": "四部丛刊本",
  "status": "进行中",
  "created": "2026-11-16",
  "updated": "2026-11-16 22:12",
  "source_sha256": "<hex>",
  "source_origin": "/path/to/底本.md",
  "chapters": [{ "name": "捭阖第一", "level": 2, "status": "进行中" }],
  "progress": { "chapter": "捭阖第一", "segment": "第三段", "anchor": "变化无穷，各有所归。", "anchor_index": 120, "updated": "..." },
  "next": { "chapter": "捭阖第一", "segment": "第四段", "anchor": "..." }
}
```

约束：`uid` 必须等于所在书房的 uid（否则 G3 拒绝）；`source_sha256` 必须等于 `source.md` 的实际哈希（否则 G6）。

### 4.3 `annotations.jsonl` — 批注（append-only，真源）

一行一条：

```json
{"id":"n-20261116-2211-ab12cd","uid":"owner","speaker":"主人","kind":"ask","lesson":1,
 "chapter":"捭阖第一","anchor":"变化无穷，各有所归。","anchor_index":120,
 "text":"为什么先说变化再分类？","ts":"2026-11-16 22:11","date":"2026-11-16",
 "actor":"owner","on_behalf":null}
```

- `kind ∈ {explain, ask, dialog, progress, variant}`
- `speaker` **只能**等于注册表中 `uid` 的 `name`（例外：`kind=explain` 时允许为 owner 的 name）
- `anchor` 必须在 `source.md` 归一化文本中**唯一**出现；`anchor_index` 是该处的字符偏移
- 不提供"修改/删除批注"的命令：要更正，追加一条新批注说明

### 4.4 `audit.jsonl` — 审计链

```json
{"seq":1,"ts":"2026-11-16 22:11:50","uid":"owner","actor":"owner","on_behalf":null,
 "op":"note.add","target":"users/owner/books/鬼谷子","detail":{"id":"n-...","kind":"ask"},
 "prev_hash":"0000…0000","hash":"<hex>"}
```

`prev_hash` 串联上一条的 `hash`；首条为 64 个 `0`。删改插入任意一行都会断链。

---

## 5. 绝对禁止

1. 自行拼接 `study/users/...` 路径写入（必须走 CLI）
2. 手改 `source.md` / `meta.json` / `annotations.jsonl` / `book.md`
3. 用 `--as` 操作他人书房（owner 代操作必须显式 `--on-behalf`）
4. 在 `--text` 中替学员编造"他说过的话"
5. 把 `exit 3` 当作"重试"信号
6. 为了"让校验通过"而修改数据

---

## 6. 最小调用序列（开一课，讲一段）

```bash
marginalia user resolve --open-id ou_xxx                 # → uid
marginalia book create --as <uid> --title 鬼谷子 --source ./鬼谷子.md
marginalia note add --as <uid> --book 鬼谷子 --kind explain -l 1 \
  --anchor "粤若稽古，圣人之在天地间也，为众生之先。" --text "…"
marginalia note add --as <uid> --book 鬼谷子 --kind ask -l 1 \
  --anchor "粤若稽古，圣人之在天地间也，为众生之先。" --text "<学员原话>"
marginalia progress set --as <uid> --book 鬼谷子 \
  --chapter 捭阖第一 --segment 第一段 \
  --anchor "粤若稽古，圣人之在天地间也，为众生之先。" \
  --next-anchor "变化无穷，各有所归。"
marginalia verify --check-render --strict
```

---

## 7. portable 模式的审计规则（`lint`）

无执行通道时，只能事后取证。规则按 `文件:行号` 报出：

| 码 | 级别 | 内容 |
|---|---|---|
| L1 | ERROR | 课程卡缺 `学员：<称呼>（uid: ...）` |
| L2 | ERROR | `👤 **X**` 的 X 与课程卡称呼不一致（串档） |
| L3 | ERROR | `<!-- marginalia:uid=... -->` 与课程卡 uid 不一致 |
| L4 | ERROR | `👤` 标签出现注册表中**其他**学员的称呼（信息更具体，与 L2 同源） |
| L5 | WARN | 标题里的称呼与课程卡不一致 |
| L6 | ERROR | 同一文件出现两张归属不同的课程卡 |
| L7 | WARN | 课程卡 uid 不在注册表中 |
| L8 | ERROR | 指定 `--expect-uid` 时，课程卡 uid 不匹配 |

无 shell 时，把 L1–L8 当人工检查单逐条过。

---

## 8. 兼容性

- 旧技能 id `tutor-progress` 与旧布局 `study/<课程名>.md` 由 `marginalia import` 迁移，详见 `MIGRATION.md`。
- `annotations.jsonl` 的 `id` 形如 `n-YYYYMMDD-HHMMSS-xxxxxx`；带 `imported: true` 的记录来自迁移。
