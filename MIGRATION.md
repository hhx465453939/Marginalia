# 迁移指南：tutor-progress v2.0 → Marginalia v3

v2 的隔离靠 SKILL 里的自然语言规矩；v3 把「谁 / 写到哪 / 说话人写谁」交给代码。
**数据不需要重写**，但布局要挪一次，旧批注本要用 `import` 拆成真源。

---

## 0. 先备份（别跳过）

```bash
cp -r study study.backup-$(date +%Y%m%d)
```

Windows PowerShell：

```powershell
Copy-Item -Recurse study "study.backup-$(Get-Date -Format yyyyMMdd)"
```

---

## 1. 装上新版

```bash
git clone https://github.com/hhx465453939/Marginalia.git
cd Marginalia
python -m pip install -e .
```

技能目录改名（旧 id 仍是 `legacy_ids`，但目录名建议跟随新名）：

```bash
mv <skills-dir>/tutor-progress <skills-dir>/marginalia
```

---

## 2. 建数据根，并让 owner 的 uid 保持 `owner`

这一点很关键：v2 的布局是 `study/users/owner/`。`--role owner` 会自动把 uid 定为 `owner`，所以路径不变。

```bash
marginalia init --owner-open-id <你的 sender_id> --owner-name 主人
```

> `ou_...` 必须用**真实消息里的 sender_id**，不要凭空编。

---

## 3. 把旧批注本迁进来

v2 的形态：`study/users/owner/<课程名>.md`（单文件，原文 + 批注混在一起）。

**先试运行**（不写盘）：

```bash
marginalia import --as 主人 --from "study.backup-20261116/users/owner/鬼谷子.md" --title 鬼谷子
```

输出会告诉你：识别到几篇、几条批注、几条锚点无法唯一定位。

**确认无误再落盘**：

```bash
marginalia import --as 主人 --from "study.backup-20261116/users/owner/鬼谷子.md" --title 鬼谷子 --apply
```

迁移做了什么：

| 旧 | 新 |
|---|---|
| 单文件里的「课程卡」区 | 被剥离，改由 `meta.json` 承载，`render` 时重新生成 |
| 单文件里的原文 | → `source.md`，并记下 sha256（此后不可改） |
| 每个 `> 🦞 / 👤 / 💬 / ✅ / 🔖` 引用块 | → `annotations.jsonl` 的一行，带 `anchor` 与偏移 |
| 整个文件 | → `book.md`（`render` 重新生成，内容等价） |

锚点定位失败（金句重复、「这句话出现两次」）的批注会落到 `_unresolved.jsonl`，不会被丢掉，也不会被硬塞到错误位置。

---

## 4. 验证

```bash
marginalia verify --check-render --strict
marginalia lint
marginalia stats --as 主人
```

期望：`verify` 退出码 0；`lint` 无 ERROR；`stats` 的批注条数与旧文件里的引用块数量一致。

---

## 5. 逐条核对（用旧文件当基准）

```bash
# 旧：批注块数量
grep -c '^> 🦞\|^> 👤\|^> 💬\|^> ✅\|^> 🔖' "study.backup-*/users/owner/鬼谷子.md"

# 新：
wc -l study/users/owner/books/鬼谷子/annotations.jsonl
```

数字应当一致（除 `_unresolved.jsonl` 里待处理的那几条）。

---

## 6. 回滚

新版只写 `study/` 下的新布局，不动你的 `study.backup-*`。要回退：

```bash
rm -rf study && mv study.backup-20261116 study
```

---

## 7. 迁移后你可能想做的事

- **给其他学员建档**：`marginalia user add --open-id <对方 sender_id> --name <称呼>`
- **同一本书两人共读**：各自 `book create --as <uid> --source 同一份底本.md` —— 两间书房，两本批注本，互不可见
- **owner 代学员记录**：`note add --as owner --on-behalf <学员uid> ...`（会记审计）

---

## 已知差异

| 项 | v2 | v3 |
|---|---|---|
| 数据形态 | 纯 Markdown | Markdown + JSON + JSONL |
| 进度表 | 模型手写 | `meta.json` 派生，`render` 生成 |
| 说话人 | 模型自己填 | 注册表派生（G4） |
| 原文保护 | 约定 | sha256 断言（G6） |
| 串档发现 | 靠人看 | `exit 3` / `verify` / `lint` |
| 无 shell 环境 | 唯一形态 | 降级为 B 模式，**弱隔离**，只能事后审计 |
