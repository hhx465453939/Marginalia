"""Marginalia · 渲染层：把可读交付物从权威数据里「长」出来。

真源 = `meta.json` + `annotations.jsonl` + `source.md`
渲染物 = `book.md`（单文件批注本，可直接发给学员阅读/归档）

**book.md 永远不是真源**——它随时可以被重新渲染出来，所以手改它没有意义，
`verify --check-render` 会检出不一致。
"""

from __future__ import annotations

from typing import Any

from . import books, registry
from .notes import KINDS, load_notes
from .store import Store
from .util import now_bj, read_text, sha256_text

GENERATED_BANNER = (
    "> ⚙️ 本文件由 `marginalia render` 生成，**请勿手改**。\n"
    "> 真源：`meta.json`（进度）+ `annotations.jsonl`（批注）+ `source.md`（原文）。"
)

_KIND_TEMPLATE = {
    "explain": "🦞 **【{lesson_tag}】** {text}",
    "ask": "👤 **{speaker}**：{text}",
    "dialog": "💬 **讨论**：{text}",
    "progress": "✅ **进度**：{text}",
    "variant": "🔖 **异文**：{text}",
}


def _lesson_tag(note: dict) -> str:
    lesson = note.get("lesson")
    date = note.get("date") or ""
    if lesson:
        return f"第{lesson}课·{date}" if date else f"第{lesson}课"
    return date or "未编号"


def _quote_block(note: dict) -> str:
    kind = note.get("kind", "explain")
    template = _KIND_TEMPLATE.get(kind, "📝 {text}")
    body = template.format(
        lesson_tag=_lesson_tag(note),
        speaker=note.get("speaker", ""),
        text="",
    )
    # 正文可能多行：第一行接在前缀后面，其余行缩进对齐
    lines = str(note.get("text", "")).split("\n")
    first = body.replace("{text}", "") + lines[0].strip()
    rest = [f"> {line}" if line.strip() else ">" for line in lines[1:]]
    return "\n".join([f"> {first}"] + rest)


def _attach(notes: list[dict], blocks: list[dict]) -> dict[int, list[dict]]:
    """把每条批注挂到包含其锚点偏移的段落块上。"""
    attached: dict[int, list[dict]] = {}
    for note in notes:
        idx = note.get("anchor_index")
        placed = False
        if isinstance(idx, int):
            for i, block in enumerate(blocks):
                if block["start"] <= idx < block["end"]:
                    attached.setdefault(i, []).append(note)
                    placed = True
                    break
        if not placed:
            # 锚点失配的批注统一挂到文末，保证不丢内容（verify 会报问题）
            attached.setdefault(len(blocks), []).append(note)
    for bucket in attached.values():
        bucket.sort(key=lambda n: (n.get("ts") or "", n.get("id") or ""))
    return attached


def _card(meta: dict, notes: list[dict]) -> str:
    chapters = meta.get("chapters", [])
    done = sum(1 for c in chapters if c.get("status") == "已讲")
    progress = meta.get("progress") or {}
    nxt = meta.get("next") or {}
    student = meta.get("student") or meta.get("uid", "")

    lines = [
        f"# 《{meta.get('title', meta.get('slug'))}》·共读批注本（{student}）",
        "",
        GENERATED_BANNER,
        "",
        f"- 学员：{student}（uid: {meta.get('uid')}）",
        f"- 底本：{meta.get('edition') or '（未注明版本）'}",
        f"- 开课日期：{meta.get('created', '')}",
        f"- 状态：{meta.get('status', '进行中')}",
        f"- 更新时间：{meta.get('updated', '')}",
        f"- 批注条数：{len(notes)} ｜ 已讲篇目：{done}/{len(chapters)}",
        "",
        "## 全书地图",
        "",
    ]
    if chapters:
        lines.append("| 篇目 | 状态 |")
        lines.append("|------|------|")
        for chapter in chapters:
            lines.append(f"| {chapter['name']} | {chapter.get('status', '未讲')} |")
    else:
        lines.append("_（底本未识别到篇目标题）_")

    lines += [
        "",
        "## 当前进度",
        "",
        f"- 讲到：{(progress.get('chapter') or '—')}·{(progress.get('segment') or '—')}",
        f"- 锚点：\"{progress.get('anchor') or '—'}\"",
        "",
        "## 下次接续点",
        "",
        f"- {(nxt.get('chapter') or '—')}·{(nxt.get('segment') or '—')}："
        f"\"{nxt.get('anchor') or '（待定）'}\"",
        "",
        "---",
        "",
    ]
    return "\n".join(lines)


def render_book(store: Store, user: dict, slug: str, write: bool = True) -> str:
    uid = user["uid"]
    meta = books.load_meta(store, uid, slug)
    notes = load_notes(store, uid, slug)
    source = books.read_source(store, uid, slug)
    blocks = books.split_blocks(source)
    attached = _attach(notes, blocks)

    parts = [_card(meta, notes)]

    for i, block in enumerate(blocks):
        parts.append(block["text"].rstrip("\n"))
        bucket = attached.get(i)
        if bucket:
            # 空行是必需的：Markdown 里引用块紧贴段落会被当成段落续行
            parts.append("")
            parts.append("\n>\n".join(_quote_block(n) for n in bucket))
        parts.append("")

    trailing = attached.get(len(blocks))
    if trailing:
        parts.append("## 锚点失配的批注（需人工处理）")
        parts.append("")
        parts.append("\n>\n".join(_quote_block(n) for n in trailing))
        parts.append("")

    text = "\n".join(parts)
    text = text.rstrip() + "\n"

    if write:
        store.write_text(store.book_paths(uid, slug)["rendered"], text)
    return text


def render_user_index(store: Store, user: dict, write: bool = True) -> str:
    uid = user["uid"]
    rows = []
    for meta in books.list_books(store, uid):
        slug = meta["slug"]
        notes = load_notes(store, uid, slug)
        chapters = meta.get("chapters", [])
        done = sum(1 for c in chapters if c.get("status") == "已讲")
        progress = meta.get("progress") or {}
        loc = f"{progress.get('chapter') or '—'}·{progress.get('segment') or '—'}"
        rows.append(
            f"| 《{meta.get('title', slug)}》 | {meta.get('status', '')} | {loc} "
            f"| {done}/{len(chapters)} | {len(notes)} | {meta.get('updated', '')} |"
        )

    lines = [
        f"# {user.get('name', uid)} 的书房",
        "",
        GENERATED_BANNER,
        "",
        f"- uid：`{uid}`",
        f"- 身份：{user.get('role', 'student')}",
        f"- 开课数：{len(rows)}",
        "",
        "## 课程索引",
        "",
    ]
    if rows:
        lines += [
            "| 课程 | 状态 | 进度 | 已讲篇目 | 批注 | 更新时间 |",
            "|------|------|------|----------|------|----------|",
            *rows,
        ]
    else:
        lines.append("_还没有开课。对智能体说「我想学《某书》」即可开第一门课。_")

    exact = "\n".join(lines).rstrip() + "\n"
    if write:
        store.write_text(store.user_index(uid), exact)
    return exact


def render_global_index(store: Store, write: bool = True) -> str:
    reg = registry.load(store)
    rows = []
    for user in reg["users"]:
        uid = user["uid"]
        try:
            metas = books.list_books(store, uid)
        except Exception:  # pragma: no cover - 损坏的书房不应阻断总表
            metas = []
        if not metas:
            rows.append(
                f"| {user.get('name')} | `{uid}` | — | — | — | — | — | — |"
            )
            continue
        for meta in metas:
            slug = meta["slug"]
            notes = load_notes(store, uid, slug)
            chapters = meta.get("chapters", [])
            done = sum(1 for c in chapters if c.get("status") == "已讲")
            progress = meta.get("progress") or {}
            loc = f"{progress.get('chapter') or '—'}·{progress.get('segment') or '—'}"
            rows.append(
                f"| {user.get('name')} | `{uid}` | 《{meta.get('title', slug)}》 "
                f"| {meta.get('status', '')} | {loc} | {done}/{len(chapters)} "
                f"| {len(notes)} | {meta.get('updated', '')} |"
            )

    lines = [
        "# Marginalia · 全局课程总表",
        "",
        GENERATED_BANNER,
        "",
        f"- 学员数：{len(reg['users'])} ｜ 生成时间：{now_bj()}",
        "- 每位学员一间独立书房：`users/<uid>/books/<slug>/`。总表只列**进度元数据**，不含批注正文。",
        "",
        "| 学员 | uid | 课程 | 状态 | 进度 | 已讲篇目 | 批注 | 更新时间 |",
        "|------|-----|------|------|------|----------|------|----------|",
        *rows,
    ]
    exact = "\n".join(lines).rstrip() + "\n"
    if write:
        store.write_text(store.global_index, exact)
    return exact


def refresh_all(store: Store) -> dict[str, int]:
    """重渲染所有索引 + 所有批注本。"""
    counts = {"books": 0, "users": 0}
    reg = registry.load(store)
    for user in reg["users"]:
        for meta in books.list_books(store, user["uid"]):
            render_book(store, user, meta["slug"], write=True)
            counts["books"] += 1
        render_user_index(store, user, write=True)
        counts["users"] += 1
    render_global_index(store, write=True)
    return counts


def is_render_fresh(store: Store, user: dict, slug: str) -> bool:
    """book.md 是否与当前真源一致。"""
    paths = store.book_paths(user["uid"], slug)
    if not paths["rendered"].is_file():
        return False
    try:
        existing = read_text(paths["rendered"])
    except OSError:
        return False
    return sha256_text(existing) == sha256_text(render_book(store, user, slug, write=False))
