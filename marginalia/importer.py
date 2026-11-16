"""Marginalia · 存量迁移：把旧的「单文件批注本」拆成 真源 + 渲染物。

旧世界：一本书一个 markdown，原文和批注混在一起，无法校验归属。
新世界：source.md（原文，哈希锁）+ annotations.jsonl（批注，append-only）。

本模块默认 **dry-run**，只报告将要做什么；加 `--apply` 才真正写盘。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from . import books, notes as notes_mod, registry
from .store import Store, default_slug
from .util import MarginaliaError, norm_text, now_bj, sha256_text, shorten, today_bj

MARKERS = {
    "🦞": "explain",
    "👤": "ask",
    "💬": "dialog",
    "✅": "progress",
    "🔖": "variant",
}

_TITLE_RE = re.compile(r"^#\s*《(?P<title>.+?)》")
_LESSON_RE = re.compile(r"【第(?P<lesson>\d+)课[·・]?(?P<date>[\d-]*?)】")
_SPEAKER_RE = re.compile(r"^\*\*(?P<speaker>[^*]+)\*\*\s*[：:]?\s*")
_BULLET_RE = re.compile(r"^-\s*(?P<key>[^：:]+)[：:]\s*(?P<value>.*)$")
_QUOTED_RE = re.compile(r"[\"“](?P<text>.+?)[\"”]")


@dataclass
class ParsedNote:
    kind: str
    text: str
    lesson: int | None = None
    date: str = ""
    speaker: str = ""
    anchor_candidates: list[str] = field(default_factory=list)
    anchor: str = ""
    anchor_index: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "lesson": self.lesson,
            "date": self.date,
            "speaker": self.speaker,
            "anchor": shorten(self.anchor, 80),
            "text": shorten(self.text, 80),
        }


@dataclass
class ParsedBook:
    title: str = ""
    edition: str = ""
    created: str = ""
    status: str = "进行中"
    student: str = ""
    chapters: list[dict] = field(default_factory=list)
    progress: dict = field(default_factory=dict)
    next: dict = field(default_factory=dict)
    source: str = ""
    notes: list[ParsedNote] = field(default_factory=list)
    unresolved: list[dict] = field(default_factory=list)
    header_stripped: bool = False


def parse_legacy(text: str) -> ParsedBook:
    book = ParsedBook()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    header_end = _find_header_end(lines)
    header_lines = lines[:header_end] if header_end else []
    body_lines = lines[header_end:] if header_end else lines
    book.header_stripped = bool(header_end)
    if header_lines:
        _parse_header(header_lines, book)

    src_lines: list[str] = []
    i = 0
    while i < len(body_lines):
        line = body_lines[i]
        if line.lstrip().startswith(">"):
            block: list[str] = []
            while i < len(body_lines) and body_lines[i].lstrip().startswith(">"):
                block.append(body_lines[i])
                i += 1
            marker = len(src_lines)
            for note in _parse_quote_block(block):
                note.anchor_candidates = _anchor_candidates(src_lines, marker)
                book.notes.append(note)
            continue
        src_lines.append(line)
        i += 1

    book.source = "\n".join(src_lines).strip("\n") + "\n"
    if not book.title:
        for line in src_lines:
            match = _TITLE_RE.match(line.strip())
            if match:
                book.title = match.group("title").strip()
                break
    if not book.chapters:
        book.chapters = [
            {"name": h["name"], "level": h["level"], "status": "未讲"}
            for h in books.scan_headings(book.source)
        ]

    for note in book.notes:
        _resolve_anchor(book, note)
    return book


def _find_header_end(lines: list[str]) -> int:
    """识别「代码生成的课程卡」区域，返回其结束行号。"""
    first = next((l for l in lines if l.strip()), "")
    if not first.startswith("# 《") or "共读批注本" not in first:
        return 0
    next_idx = None
    for idx, line in enumerate(lines):
        if line.strip().startswith("## 下次接续点"):
            next_idx = idx
            break
    if next_idx is None:
        return 0
    for idx in range(next_idx, len(lines)):
        if lines[idx].strip() in {"---", "***", "___"}:
            return idx + 1
    return 0


def _parse_header(lines: list[str], book: ParsedBook) -> None:
    section = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            section = stripped[3:].strip()
            continue
        if stripped.startswith("# "):
            match = _TITLE_RE.match(stripped)
            if match:
                book.title = match.group("title").strip()
            continue
        if stripped.startswith("|") and section == "全书地图":
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 2 and not set(cells[0]) <= {"-", ":", " "} and cells[0] != "篇目":
                book.chapters.append({"name": cells[0], "level": 2, "status": cells[1]})
            continue
        bullet = _BULLET_RE.match(stripped)
        if bullet:
            key, value = bullet.group("key").strip(), bullet.group("value").strip()
            if key == "底本":
                book.edition = value
            elif key == "开课日期":
                book.created = value
            elif key == "状态":
                book.status = value or "进行中"
            elif key == "学员":
                book.student = re.split(r"[（(]", value)[0].strip()
            elif key == "讲到":
                chapter, _, segment = value.partition("·")
                book.progress["chapter"] = chapter.strip()
                book.progress["segment"] = segment.strip()
            elif key == "锚点":
                quoted = _QUOTED_RE.search(value)
                book.progress["anchor"] = quoted.group("text") if quoted else value.strip('"“”')
            continue
        if section == "下次接续点" and stripped.startswith("- "):
            content = stripped[2:]
            quoted = _QUOTED_RE.search(content)
            book.next["anchor"] = quoted.group("text") if quoted else ""
            head = content.split("：")[0]
            chapter, _, segment = head.partition("·")
            book.next["chapter"] = chapter.strip()
            book.next["segment"] = segment.strip()


def _parse_quote_block(block: list[str]) -> list[ParsedNote]:
    groups: list[list[str]] = []
    current: list[str] = []
    for line in block:
        content = line.lstrip()[1:]
        if content.startswith(" "):
            content = content[1:]
        if not content.strip():
            if current:
                groups.append(current)
                current = []
            continue
        current.append(content.rstrip())
    if current:
        groups.append(current)

    out: list[ParsedNote] = []
    for group in groups:
        note = _parse_group(group)
        if note is None:
            if out:
                out[-1].text += "\n" + "\n".join(group)
            continue
        out.append(note)
    return out


def _parse_group(group: list[str]) -> ParsedNote | None:
    first = group[0]
    kind = None
    for marker, name in MARKERS.items():
        if marker in first[:6]:
            kind = name
            break
    if kind is None:
        return None

    lesson = None
    date = ""
    match = _LESSON_RE.search(first)
    if match:
        lesson = int(match.group("lesson"))
        date = match.group("date")

    body = first
    speaker = ""
    for marker in MARKERS:
        body = body.replace(marker, "", 1)
    body = body.strip()
    # 课次标记可能是 **【第N课·日期】** 或 【第N课·日期】
    body = re.sub(r"^\*\*【[^】]*】\*\*\s*", "", body)
    body = re.sub(r"^【[^】]*】\s*", "", body)

    # 只有 👤 承载「人」。💬/✅/🔖 后面的 **...** 是标签（讨论/进度/异文），
    # 把它们当说话人是语义错误，会制造「说话人不符」的假阳性。
    if kind == "ask":
        speaker_match = _SPEAKER_RE.match(body)
        if speaker_match:
            speaker = speaker_match.group("speaker").strip()
            body = body[speaker_match.end():].strip()
    else:
        body = re.sub(r"^\*\*[^*]+\*\*\s*[：:]?\s*", "", body)
    body = re.sub(r"^(讨论|进度|异文)\s*[：:]\s*", "", body).strip()

    text = "\n".join([body] + group[1:]).strip()
    if not text:
        return None
    return ParsedNote(kind=kind, text=text, lesson=lesson, date=date, speaker=speaker)


def _anchor_candidates(src_lines: list[str], marker: int) -> list[str]:
    j = marker - 1
    while j >= 0 and not src_lines[j].strip():
        j -= 1
    candidates: list[str] = []
    for width in range(1, 5):
        start = j - width + 1
        if start < 0:
            break
        chunk = "\n".join(src_lines[start : j + 1]).strip()
        if chunk:
            candidates.append(chunk)
    return candidates


def _resolve_anchor(book: ParsedBook, note: ParsedNote) -> None:
    for candidate in note.anchor_candidates:
        try:
            index = books.locate_anchor(book.source, candidate)
        except MarginaliaError:
            continue
        note.anchor = candidate
        note.anchor_index = index
        return
    book.unresolved.append(
        {
            "kind": note.kind,
            "speaker": note.speaker,
            "text": note.text,
            "reason": "锚点无法在原文中唯一定位",
            "candidates": [shorten(c, 60) for c in note.anchor_candidates[:2]],
        }
    )


def import_book(
    store: Store,
    user: dict,
    source_file: str,
    title: str | None = None,
    slug: str | None = None,
    apply: bool = False,
    force_speaker: bool = False,
) -> dict[str, Any]:
    from pathlib import Path

    path = Path(source_file).expanduser()
    if not path.is_file():
        raise MarginaliaError(f"待迁移文件不存在: {path}")
    parsed = parse_legacy(path.read_text(encoding="utf-8"))
    if title:
        parsed.title = title.strip().strip("《》")
    if not parsed.title:
        raise MarginaliaError("无法确定书名，请用 --title 指定")

    uid = user["uid"]
    resolved_slug = slug or default_slug(parsed.title)

    expected_speaker = registry.speaker_of(store, user)
    speaker_issues = []
    for note in parsed.notes:
        # 只有 👤 是归属声明；其余标签不参与比对
        if note.kind != "ask" or not note.speaker:
            continue
        if note.speaker == expected_speaker:
            continue
        speaker_issues.append(
            {"speaker": note.speaker, "kind": note.kind, "text": shorten(note.text, 50)}
        )

    summary = {
        "title": parsed.title,
        "slug": resolved_slug,
        "uid": uid,
        "target": expected_speaker,
        "header_stripped": parsed.header_stripped,
        "source_chars": len(parsed.source),
        "source_sha256": sha256_text(parsed.source),
        "chapters": len(parsed.chapters),
        "notes_total": len(parsed.notes),
        "notes_by_kind": _count_kinds(parsed.notes),
        "notes_resolved": sum(1 for n in parsed.notes if n.anchor_index is not None),
        "unresolved": parsed.unresolved,
        "speaker_issues": speaker_issues,
        "applied": False,
    }

    if speaker_issues and not force_speaker:
        raise MarginaliaError(
            f"发现 {len(speaker_issues)} 条批注的说话人与 {expected_speaker!r} 不符，疑似原文件混入了别人的记录",
            hint="核对后用 --force-speaker 强制按当前学员归一化，或先修正原文件",
        )

    if not apply:
        return summary

    user_dir = store.book_dir(uid, resolved_slug)
    if user_dir.exists():
        raise MarginaliaError(f"目标课程已存在: {resolved_slug}", hint="换 --slug 或先处理已存在的课程")

    meta = books.create_book(
        store,
        user,
        parsed.title,
        source_path=None,
        slug=resolved_slug,
        edition=parsed.edition,
    )
    paths = store.book_paths(uid, resolved_slug)
    store.write_text(paths["source"], parsed.source)

    meta["source_sha256"] = sha256_text(parsed.source)
    meta["created"] = parsed.created or today_bj()
    meta["status"] = parsed.status if parsed.status in books.BOOK_STATUSES else "进行中"
    if parsed.chapters:
        meta["chapters"] = [
            {
                "name": c["name"],
                "level": c.get("level", 2),
                "status": c.get("status", "未讲")
                if c.get("status") in books.CHAPTER_STATUSES
                else "未讲",
            }
            for c in parsed.chapters
        ]
    meta["progress"] = {
        "chapter": parsed.progress.get("chapter", ""),
        "segment": parsed.progress.get("segment", ""),
        "anchor": parsed.progress.get("anchor", ""),
        "anchor_index": None,
        "updated": now_bj(),
    }
    meta["next"] = {
        "chapter": parsed.next.get("chapter", ""),
        "segment": parsed.next.get("segment", ""),
        "anchor": parsed.next.get("anchor", ""),
    }
    meta["imported_from"] = str(path)
    books.save_meta(store, uid, resolved_slug, meta)

    reg = registry.load(store)
    owner_names = {u.get("name") for u in reg["users"] if u.get("role") == "owner"}
    imported = 0
    for note in parsed.notes:
        if note.anchor_index is None:
            continue
        if note.kind == "explain":
            speaker = note.speaker if note.speaker in owner_names else (next(iter(owner_names)) if owner_names else expected_speaker)
        else:
            speaker = expected_speaker
        record = {
            "id": notes_mod._new_id(),
            "uid": uid,
            "speaker": speaker,
            "kind": note.kind,
            "lesson": note.lesson,
            "chapter": books.chapter_at(parsed.source, note.anchor_index),
            "anchor": note.anchor,
            "anchor_index": note.anchor_index,
            "text": note.text,
            "ts": now_bj(),
            "date": note.date or today_bj(),
            "actor": uid,
            "on_behalf": None,
            "imported": True,
        }
        store.append_jsonl(paths["annotations"], record)
        imported += 1

    if parsed.unresolved:
        for row in parsed.unresolved:
            store.append_jsonl(paths["unresolved"], row)

    from . import audit, render

    audit.append(
        store,
        uid,
        actor=uid,
        op="book.import",
        target=store.rel(paths["dir"]),
        detail={
            "from": str(path),
            "notes_imported": imported,
            "unresolved": len(parsed.unresolved),
            "source_sha256": meta["source_sha256"],
        },
    )
    render.render_book(store, user, resolved_slug, write=True)
    render.render_user_index(store, user, write=True)
    render.render_global_index(store, write=True)

    summary["applied"] = True
    summary["notes_imported"] = imported
    return summary


def _count_kinds(notes: list[ParsedNote]) -> dict[str, int]:
    out: dict[str, int] = {}
    for note in notes:
        out[note.kind] = out.get(note.kind, 0) + 1
    return out


def _norm(text: str) -> str:  # pragma: no cover - 兼容旧调用
    return norm_text(text)
