"""Marginalia · 书籍层：底本入库、原文哈希锁、章节状态、进度、锚点定位。

锚点（anchor）是整套隔离机制里最容易被幻觉污染的东西，所以这里全部用
**归一化字符偏移** 处理：原文一字不改，批注靠偏移量精确落位。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import audit
from .store import Store, default_slug, validate_slug
from .util import (
    EXIT_ERROR,
    EXIT_INTEGRITY,
    MarginaliaError,
    norm_text,
    now_bj,
    read_text,
    sha256_text,
    shorten,
    today_bj,
)

SCHEMA_VERSION = 1
BOOK_STATUSES = {"进行中", "暂停", "已结课"}
CHAPTER_STATUSES = {"未讲", "进行中", "已讲"}
MIN_ANCHOR_CHARS = 2

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_BLOCK_SPLIT_RE = re.compile(r"\n[ \t]*\n+")


# ---------------------------------------------------------------- 文本地图


def split_blocks(source: str) -> list[dict[str, Any]]:
    """把原文切成段落块，并给出每块在「归一化原文」中的偏移区间。"""
    blocks: list[dict[str, Any]] = []
    offset = 0
    for raw in _BLOCK_SPLIT_RE.split(source):
        if not raw.strip():
            continue
        norm = norm_text(raw)
        if not norm:
            continue
        blocks.append({"text": raw, "start": offset, "end": offset + len(norm), "norm": norm})
        offset += len(norm)
    return blocks


def scan_headings(source: str) -> list[dict[str, Any]]:
    """扫描 Markdown 标题，返回篇目级标题（名称, 级别, 归一化偏移）。

    常见底本是 `# 书名` 后跟一串 `## 篇名`：此时文档标题不是篇目，
    篇目级别要下探一层。否则 `#` 就直接当篇目用。
    """
    all_headings: list[dict[str, Any]] = []
    offset = 0
    for line in source.split("\n"):
        norm_line = norm_text(line)
        match = _HEADING_RE.match(line)
        if match:
            all_headings.append(
                {
                    "name": match.group(2).strip(),
                    "level": len(match.group(1)),
                    "index": offset,
                }
            )
        offset += len(norm_line)

    if not all_headings:
        return []

    levels = [h["level"] for h in all_headings]
    top = min(levels)
    first = all_headings[0]
    lone_title = (
        first["level"] == top
        and len(all_headings) > 1
        and sum(1 for h in all_headings if h["level"] == top) == 1
    )
    chapter_level = min(h["level"] for h in all_headings[1:]) if lone_title else top
    return [h for h in all_headings if h["level"] == chapter_level]


def locate_anchor(source: str, anchor: str) -> int:
    """返回锚点在归一化原文中的唯一偏移；不唯一 / 不存在 → exit 3（G5 唯一性闸）。"""
    if not anchor or not anchor.strip():
        raise MarginaliaError("锚点为空：批注必须指向一句原文", EXIT_INTEGRITY)
    needle = norm_text(anchor)
    if len(needle) < MIN_ANCHOR_CHARS:
        raise MarginaliaError(
            f"锚点太短（<{MIN_ANCHOR_CHARS} 字），无法唯一定位: {anchor!r}", EXIT_INTEGRITY
        )
    haystack = norm_text(source)
    positions = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            break
        positions.append(idx)
        start = idx + 1
    if not positions:
        raise MarginaliaError(
            f"锚点在原文中不存在: {shorten(anchor)!r}",
            EXIT_INTEGRITY,
            hint="锚点必须逐字摘自 source.md（可跨行，代码会忽略空白差异）",
        )
    if len(positions) > 1:
        raise MarginaliaError(
            f"锚点在原文中出现 {len(positions)} 次，定位不唯一: {shorten(anchor)!r}",
            EXIT_INTEGRITY,
            hint="把锚点加长到能唯一覆盖（多带前后几个字，或整句）",
        )
    return positions[0]


def chapter_at(source: str, index: int) -> str:
    """给定偏移，返回其所属篇名。"""
    name = ""
    for heading in scan_headings(source):
        if heading["index"] <= index:
            name = heading["name"]
        else:
            break
    return name


# ---------------------------------------------------------------- 元数据


def load_meta(store: Store, uid: str, slug: str) -> dict:
    paths = store.book_paths(uid, slug)
    meta = store.read_json(paths["meta"])
    _assert_ownership(uid, meta)
    return meta


def save_meta(store: Store, uid: str, slug: str, meta: dict) -> None:
    _assert_ownership(uid, meta)
    meta["updated"] = now_bj()
    store.write_json(store.book_paths(uid, slug)["meta"], meta)


def _assert_ownership(uid: str, meta: dict) -> None:
    """G3 归属闸：书的 uid 必须与目标书房 uid 一致。"""
    owner = meta.get("uid")
    if owner != uid:
        raise MarginaliaError(
            f"归属冲突：这本批注本属于 {owner!r}，但你正在以 {uid!r} 的身份操作 —— 拒绝写入",
            EXIT_INTEGRITY,
            hint="这是跨学员串档的典型形态；请确认 --as 的身份是否正确",
        )


def read_source(store: Store, uid: str, slug: str) -> str:
    """读原文并校验哈希（G6 原文闸）。"""
    paths = store.book_paths(uid, slug)
    if not paths["source"].is_file():
        raise MarginaliaError(
            f"该课程还没有底本: {store.rel(paths['source'])}",
            EXIT_ERROR,
            hint="建课时用 --source 指定底本 Markdown",
        )
    text = read_text(paths["source"])
    expected = load_meta(store, uid, slug).get("source_sha256")
    if expected and sha256_text(text) != expected:
        raise MarginaliaError(
            f"原文被改动过（sha256 不匹配）: {store.rel(paths['source'])}",
            EXIT_INTEGRITY,
            hint="原文必须保持一字不改。若要换底本，请新建 slug 而不是改 source.md",
        )
    return text


def list_books(store: Store, uid: str) -> list[dict]:
    books_dir = store.books_dir(uid)
    if not books_dir.is_dir():
        return []
    out = []
    for child in sorted(books_dir.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        meta_path = child / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = store.read_json(meta_path)
        except MarginaliaError:
            continue
        out.append(meta)
    return out


def create_book(
    store: Store,
    user: dict,
    title: str,
    source_path: str | Path | None = None,
    slug: str | None = None,
    edition: str = "",
) -> dict:
    """对外入口：自动按学员加锁。"""
    with store.lock(f"user-{user['uid']}"):
        return _create_book(store, user, title, source_path, slug, edition)


def _create_book(
    store: Store,
    user: dict,
    title: str,
    source_path: str | Path | None = None,
    slug: str | None = None,
    edition: str = "",
) -> dict:
    uid = user["uid"]
    title = (title or "").strip().strip("《》")
    if not title:
        raise MarginaliaError("书名不能为空")

    slug = validate_slug(slug or default_slug(title))
    paths = store.book_paths(uid, slug)
    if paths["meta"].exists():
        raise MarginaliaError(
            f"课程已存在: {slug}",
            hint="同一本书请继续用 note add 追加批注；要重开请换 --slug",
        )

    source_text = ""
    if source_path:
        src = Path(source_path).expanduser()
        if not src.is_file():
            raise MarginaliaError(f"底本文件不存在: {src}")
        source_text = read_text(src)

    headings = scan_headings(source_text) if source_text else []
    chapters = [{"name": h["name"], "level": h["level"], "status": "未讲"} for h in headings]

    meta = {
        "schema": SCHEMA_VERSION,
        "slug": slug,
        "title": title,
        "uid": uid,
        "student": user.get("name", ""),
        "edition": edition,
        "status": "进行中",
        "created": today_bj(),
        "updated": now_bj(),
        "source_sha256": sha256_text(source_text) if source_text else None,
        "source_origin": str(Path(source_path).expanduser()) if source_path else None,
        "chapters": chapters,
        "progress": {"chapter": "", "segment": "", "anchor": "", "updated": None},
        "next": {"chapter": "", "segment": "", "anchor": ""},
    }

    paths["dir"].mkdir(parents=True, exist_ok=True)
    if source_text:
        store.write_text(paths["source"], source_text)
    store.write_text(paths["annotations"], "")
    store.write_json(paths["meta"], meta)
    audit.append(
        store,
        uid,
        actor=uid,
        op="book.create",
        target=store.rel(paths["dir"]),
        detail={
            "title": title,
            "slug": slug,
            "source_chars": len(source_text),
            "source_sha256": meta["source_sha256"],
            "chapters": len(chapters),
        },
    )
    return meta


# ---------------------------------------------------------------- 章节 / 进度


def mark_chapter(store: Store, user: dict, slug: str, chapter: str, status: str) -> dict:
    """对外入口：自动按书本加锁。"""
    with store.lock(f"book-{user['uid']}-{slug}"):
        return _mark_chapter(store, user, slug, chapter, status)


def _mark_chapter(store: Store, user: dict, slug: str, chapter: str, status: str) -> dict:
    if status not in CHAPTER_STATUSES:
        raise MarginaliaError(f"章节状态只能是 {sorted(CHAPTER_STATUSES)}")
    uid = user["uid"]
    meta = load_meta(store, uid, slug)
    target = None
    for item in meta.get("chapters", []):
        if item["name"] == chapter:
            target = item
            break
    if target is None:
        raise MarginaliaError(
            f"篇目不存在: {chapter!r}",
            hint="可用篇目：" + "、".join(c["name"] for c in meta.get("chapters", [])[:20]),
        )
    target["status"] = status
    save_meta(store, uid, slug, meta)
    audit.append(
        store,
        uid,
        actor=uid,
        op="chapter.mark",
        target=store.rel(store.book_paths(uid, slug)["dir"]),
        detail={"chapter": chapter, "status": status},
    )
    return target


def set_progress(
    store: Store,
    user: dict,
    slug: str,
    chapter: str,
    segment: str = "",
    anchor: str = "",
    next_anchor: str = "",
    next_segment: str = "",
) -> dict:
    """对外入口：自动按书本加锁。"""
    with store.lock(f"book-{user['uid']}-{slug}"):
        return _set_progress(store, user, slug, chapter, segment, anchor, next_anchor, next_segment)


def _set_progress(
    store: Store,
    user: dict,
    slug: str,
    chapter: str,
    segment: str = "",
    anchor: str = "",
    next_anchor: str = "",
    next_segment: str = "",
) -> dict:
    uid = user["uid"]
    meta = load_meta(store, uid, slug)
    source = read_source(store, uid, slug)

    anchor_index = locate_anchor(source, anchor) if anchor else None
    if anchor_index is not None and not chapter:
        chapter = chapter_at(source, anchor_index)

    if chapter and not meta.get("chapters"):
        meta["chapters"] = [
            {"name": h["name"], "level": h["level"], "status": "未讲"}
            for h in scan_headings(source)
        ]

    names = [c["name"] for c in meta.get("chapters", [])]
    if chapter and names and chapter not in names:
        raise MarginaliaError(
            f"篇目不在全书地图里: {chapter!r}", hint="可用篇目：" + "、".join(names[:20])
        )

    if next_anchor:
        locate_anchor(source, next_anchor)

    meta["progress"] = {
        "chapter": chapter,
        "segment": segment,
        "anchor": anchor,
        "anchor_index": anchor_index,
        "updated": now_bj(),
    }
    meta["next"] = {
        "chapter": chapter,
        "segment": next_segment,
        "anchor": next_anchor,
    }

    # 讲到哪，自动把该篇标成「进行中」（除非已标已讲）
    for item in meta.get("chapters", []):
        if item["name"] == chapter and item["status"] == "未讲":
            item["status"] = "进行中"

    save_meta(store, uid, slug, meta)
    audit.append(
        store,
        uid,
        actor=uid,
        op="progress.set",
        target=store.rel(store.book_paths(uid, slug)["dir"]),
        detail={
            "chapter": chapter,
            "segment": segment,
            "anchor": shorten(anchor, 80),
            "next_anchor": shorten(next_anchor, 80),
        },
    )
    return meta
