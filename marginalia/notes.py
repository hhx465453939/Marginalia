"""Marginalia · 批注层：append-only 真源 + 四道写入闸门。

写入顺序（任一步失败即整体不落盘）：
  1. G1 身份闸   —— 调用方已解析出 user
  2. G3 归属闸   —— book.meta.uid 必须等于目标书房 uid
  3. G4 说话人闸 —— speaker 由 registry 派生，与目标书房学员一致
  4. G5 唯一性闸 —— anchor 必须在原文中唯一出现
最后 append 一行 JSONL + 记审计。
"""

from __future__ import annotations

import secrets
from typing import Any

from . import audit, books, registry
from .store import Store
from .util import (
    EXIT_IDENTITY,
    EXIT_INTEGRITY,
    MarginaliaError,
    now_bj,
    shorten,
    today_bj,
)

# kind → (渲染前缀, 中文名)
KINDS: dict[str, tuple[str, str]] = {
    "explain": ("🦞", "讲解"),
    "ask": ("👤", "学员"),
    "dialog": ("💬", "讨论"),
    "progress": ("✅", "进度"),
    "variant": ("🔖", "异文"),
}


def _new_id() -> str:
    return f"n-{now_bj('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"


def add_note(
    store: Store,
    actor: dict,
    slug: str,
    kind: str,
    text: str,
    anchor: str = "",
    lesson: int | None = None,
    chapter: str = "",
    on_behalf: str | None = None,
) -> dict:
    """对外入口：**自动加锁**。

    并发安全由库保证，不要求调用方记得 `with store.lock(...)`。
    锁名由 (uid, slug) 派生——与路径派生同源，同样不接受外部指定。
    """
    target = actor
    if on_behalf:
        registry.require_owner(store, actor, "代笔/代记（--on-behalf）")
        target = registry.resolve(store, on_behalf)
    with store.lock(f"book-{target['uid']}-{slug}"):
        return _add_note(
            store, actor, slug, kind, text, anchor, lesson, chapter, on_behalf
        )


def _add_note(
    store: Store,
    actor: dict,
    slug: str,
    kind: str,
    text: str,
    anchor: str = "",
    lesson: int | None = None,
    chapter: str = "",
    on_behalf: str | None = None,
) -> dict:
    if kind not in KINDS:
        raise MarginaliaError(f"批注类型只能是 {sorted(KINDS)}")
    text = (text or "").strip()
    if not text:
        raise MarginaliaError("批注内容不能为空")

    # ---- 决定这篇批注记在谁的书房里（G3）
    target = actor
    if on_behalf:
        registry.require_owner(store, actor, "代笔/代记（--on-behalf）")
        target = registry.resolve(store, on_behalf)
        if target["uid"] == actor["uid"]:
            on_behalf = None
    uid = target["uid"]

    meta = books.load_meta(store, uid, slug)  # 内含 G3 归属闸
    source = books.read_source(store, uid, slug)  # 内含 G6 原文闸

    # ---- G4 说话人闸：speaker 只能来自注册表
    if kind == "explain" and on_behalf:
        speaker = registry.speaker_of(store, actor)  # 老师（owner）讲的话
    else:
        speaker = registry.speaker_of(store, target)

    # ---- G5 唯一性闸
    anchor_index = books.locate_anchor(source, anchor) if anchor else None
    if anchor_index is None:
        raise MarginaliaError(
            "缺少锚点：批注必须指向原文中的一句（-a/--anchor）",
            EXIT_INTEGRITY,
            hint="逐字复制相邻原文一句即可，代码会忽略空白差异",
        )
    if not chapter:
        chapter = books.chapter_at(source, anchor_index)

    note = {
        "id": _new_id(),
        "uid": uid,
        "speaker": speaker,
        "kind": kind,
        "lesson": lesson,
        "chapter": chapter,
        "anchor": anchor,
        "anchor_index": anchor_index,
        "text": text,
        "ts": now_bj(),
        "date": today_bj(),
        "actor": actor["uid"],
        "on_behalf": on_behalf,
    }

    _assert_note_ownership(uid, note)

    paths = store.book_paths(uid, slug)
    store.append_jsonl(paths["annotations"], note)

    audit.append(
        store,
        uid,
        actor=actor["uid"],
        on_behalf=on_behalf,
        op="note.add",
        target=store.rel(paths["dir"]),
        detail={
            "id": note["id"],
            "kind": kind,
            "speaker": speaker,
            "chapter": chapter,
            "anchor": shorten(anchor, 60),
        },
    )
    return note


def _assert_note_ownership(uid: str, note: dict) -> None:
    """G3 的落盘前二次断言：批注 uid 必须等于书房 uid。"""
    if note.get("uid") != uid:
        raise MarginaliaError(
            f"批注归属错误：note.uid={note.get('uid')!r} ≠ 书房 uid={uid!r} —— 已拦截",
            EXIT_INTEGRITY,
        )


def load_notes(store: Store, uid: str, slug: str) -> list[dict]:
    return store.read_jsonl(store.book_paths(uid, slug)["annotations"])


def check_note(store: Store, uid: str, note: dict, source: str) -> list[str]:
    """单条批注的完整性校验（verify 用），返回问题列表。"""
    problems: list[str] = []
    where = f"annotations.jsonl[{note.get('id')}]"
    if note.get("uid") != uid:
        problems.append(f"{where} uid 归属错误：{note.get('uid')} ≠ {uid}")
    kind = note.get("kind")
    if kind not in KINDS:
        problems.append(f"{where} 非法 kind：{kind}")
    if not str(note.get("text", "")).strip():
        problems.append(f"{where} 内容为空")
    anchor = note.get("anchor") or ""
    if not anchor:
        problems.append(f"{where} 缺少锚点")
    else:
        try:
            idx = books.locate_anchor(source, anchor)
        except MarginaliaError as exc:
            problems.append(f"{where} 锚点问题：{exc.message}")
        else:
            if note.get("anchor_index") != idx:
                problems.append(
                    f"{where} 锚点偏移漂移：记录 {note.get('anchor_index')} ≠ 实际 {idx}"
                )
    return problems


def check_speaker(store: Store, uid: str, note: dict) -> list[str]:
    """G4 复查：说话人必须是该书房学员，或 owner（讲解者）。"""
    problems: list[str] = []
    where = f"annotations.jsonl[{note.get('id')}]"
    try:
        target = registry.resolve(store, uid)
    except MarginaliaError as exc:
        return [f"{where} 书房 uid 不在注册表：{exc.message}"]
    expected = registry.speaker_of(store, target)
    speaker = note.get("speaker")
    if speaker == expected:
        return problems

    # 允许：owner 作为讲解者出现在学员书房（kind=explain）
    reg = registry.load(store)
    owners = [u for u in reg["users"] if u.get("role") == "owner"]
    owner_names = {u.get("name") for u in owners}
    if note.get("kind") == "explain" and speaker in owner_names:
        return problems

    problems.append(
        f"{where} 说话人不属于本书房：{speaker!r}（应为 {expected!r}）—— 疑似串档/幻觉"
    )
    return problems


def stats(store: Store, uid: str) -> dict[str, Any]:
    by_kind: dict[str, int] = {k: 0 for k in KINDS}
    rows = []
    total = 0
    for meta in books.list_books(store, uid):
        slug = meta["slug"]
        notes = load_notes(store, uid, slug)
        total += len(notes)
        for note in notes:
            by_kind[note.get("kind", "?")] = by_kind.get(note.get("kind", "?"), 0) + 1
        chapters = meta.get("chapters", [])
        done = sum(1 for c in chapters if c.get("status") == "已讲")
        rows.append(
            {
                "slug": slug,
                "title": meta.get("title", slug),
                "status": meta.get("status", ""),
                "notes": len(notes),
                "chapters_done": done,
                "chapters_total": len(chapters),
                "progress": meta.get("progress", {}),
            }
        )
    return {"uid": uid, "books": rows, "notes_total": total, "by_kind": by_kind}
