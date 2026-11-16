"""Marginalia · 命令行入口（Agent 唯一允许的数据写通道）。

设计信条：
  1. LLM 只能声明「我是谁」，不能声明「写到哪个文件」；
  2. 每条命令成功后，磁盘状态都自洽（渲染物同步刷新）；
  3. 任何拒绝都给出可执行的下一步指令。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from . import audit, books, importer, lint, notes as notes_mod, registry, render, verify
from .store import Store, default_slug
from .util import (
    EXIT_ERROR,
    EXIT_IDENTITY,
    EXIT_INTEGRITY,
    EXIT_OK,
    MarginaliaError,
    eprint,
    now_bj,
    shorten,
)

PROG = "marginalia"


# ---------------------------------------------------------------- 输出helper


def _force_utf8() -> None:
    """Windows 默认 GBK 控制台会把中文输出打成乱码/直接抛 UnicodeEncodeError。

    这是用户在 Windows 上第一条命令就会撞到的坑，所以在入口强制 UTF-8。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - 极老的 stdout 包装
            pass


def _out(msg: str = "") -> None:
    print(msg)


def _ok(msg: str) -> None:
    print(f"✓ {msg}")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], _display_width(cell))
    sep = "  "
    lines = [sep.join(_pad(h, widths[i]) for i, h in enumerate(headers))]
    lines.append(sep.join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append(sep.join(_pad(c, widths[i]) for i, c in enumerate(row)))
    return "\n".join(lines)


def _display_width(text: str) -> int:
    total = 0
    for ch in str(text):
        total += 2 if ord(ch) > 0x2E80 else 1
    return total


def _pad(text: str, width: int) -> str:
    return str(text) + " " * max(0, width - _display_width(text))


def _refresh(store: Store, user: dict, slug: str | None = None) -> None:
    if slug:
        render.render_book(store, user, slug, write=True)
    render.render_user_index(store, user, write=True)
    render.render_global_index(store, write=True)


# ---------------------------------------------------------------- 命令


def cmd_init(args: argparse.Namespace, store: Store) -> int:
    if store.is_initialized() and not args.force:
        _ok(f"数据根已存在，无需重复初始化: {store.root}")
        return EXIT_OK
    store.ensure()
    registry.save(store, registry.empty_registry())
    render.render_global_index(store, write=True)
    _ok(f"已初始化数据根: {store.root}")
    if args.owner_open_id and args.owner_name:
        user = registry.add_user(
            store,
            open_id=args.owner_open_id,
            name=args.owner_name,
            role="owner",
            goal="系统所有者",
        )
        audit.append(store, user["uid"], user["uid"], "user.add", "registry.json", {"role": "owner"})
        render.render_user_index(store, user, write=True)
        render.render_global_index(store, write=True)
        _ok(f"已建立 owner 书房: {user['name']}（uid: {user['uid']}）")
    else:
        _out("")
        _out("下一步：建档第一位学员")
        _out(f"  {PROG} user add --open-id <sender_id> --name <称呼> --role owner")
    return EXIT_OK


def cmd_user_add(args: argparse.Namespace, store: Store) -> int:
    store.require_initialized()
    aliases = [a.strip() for a in (args.alias or "").split(",") if a.strip()]
    with store.lock("registry"):
        user = registry.add_user(
            store,
            open_id=args.open_id,
            name=args.name,
            uid=args.uid,
            role=args.role,
            aliases=aliases,
            goal=args.goal or "",
            pace=args.pace or "",
        )
        audit.append(
            store, user["uid"], user["uid"], "user.add", "registry.json",
            {"role": user["role"], "name": user["name"]},
        )
    render.render_user_index(store, user, write=True)
    render.render_global_index(store, write=True)
    if args.json:
        print(json.dumps(user, ensure_ascii=False, indent=2))
    else:
        _ok(f"已建档：{user['name']}（uid: {user['uid']}, role: {user['role']}）")
        _out(f"  书房：{store.rel(store.user_dir(user['uid']))}")
        if user["role"] != "owner":
            _out(f"  下一步：{PROG} book create --as {user['uid']} --title 《某书》 --source <底本.md>")
    return EXIT_OK


def cmd_user_resolve(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.open_id or args.name or args.token)
    if args.json:
        print(json.dumps(user, ensure_ascii=False, indent=2))
    else:
        _ok(f"{user['name']} → uid: {user['uid']}（role: {user['role']}）")
    return EXIT_OK


def cmd_user_list(args: argparse.Namespace, store: Store) -> int:
    store.require_initialized()
    users = registry.list_users(store)
    if args.json:
        print(json.dumps(users, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not users:
        _out("（还没有学员）")
        return EXIT_OK
    rows = []
    for user in users:
        metas = books.list_books(store, user["uid"])
        note_count = sum(len(notes_mod.load_notes(store, user["uid"], m["slug"])) for m in metas)
        rows.append([
            user["name"],
            user["uid"],
            user.get("role", ""),
            str(len(metas)),
            str(note_count),
            ",".join(user.get("open_ids", []))[:28],
        ])
    _out(_table(["称呼", "uid", "角色", "课程", "批注", "open_id"], rows))
    return EXIT_OK


def cmd_book_create(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_)
    slug = args.slug or default_slug(args.title)
    with store.lock(f"book-{user['uid']}-{slug}"):
        meta = books.create_book(
            store,
            user,
            title=args.title,
            source_path=args.source,
            slug=slug,
            edition=args.edition or "",
        )
        _refresh(store, user, slug)
    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
    else:
        _ok(f"已开课：《{meta['title']}》 → {store.rel(store.book_paths(user['uid'], slug)['dir'])}")
        _out(f"  学员：{user['name']} ｜ slug：{slug} ｜ 篇目：{len(meta['chapters'])}")
        if not args.source:
            _out("  ⚠ 未提供底本；批注需要底本才能定位，请补 --source")
    return EXIT_OK


def cmd_book_list(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_)
    metas = books.list_books(store, user["uid"])
    if args.json:
        print(json.dumps(metas, ensure_ascii=False, indent=2))
        return EXIT_OK
    if not metas:
        _out(f"{user['name']} 还没有课程")
        return EXIT_OK
    rows = []
    for meta in metas:
        ns = notes_mod.load_notes(store, user["uid"], meta["slug"])
        chapters = meta.get("chapters", [])
        done = sum(1 for c in chapters if c.get("status") == "已讲")
        progress = meta.get("progress") or {}
        rows.append([
            meta.get("title", meta["slug"]),
            meta["slug"],
            meta.get("status", ""),
            f"{progress.get('chapter') or '—'}·{progress.get('segment') or '—'}",
            f"{done}/{len(chapters)}",
            str(len(ns)),
            meta.get("updated", ""),
        ])
    _out(_table(["课程", "slug", "状态", "进度", "已讲", "批注", "更新"], rows))
    return EXIT_OK


def cmd_chapter_mark(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_)
    with store.lock(f"book-{user['uid']}-{args.book}"):
        chapter = books.mark_chapter(store, user, args.book, args.chapter, args.status)
        _refresh(store, user, args.book)
    _ok(f"《{args.book}》{args.chapter} → {chapter['status']}")
    return EXIT_OK


def cmd_progress_set(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_)
    with store.lock(f"book-{user['uid']}-{args.book}"):
        meta = books.set_progress(
            store,
            user,
            args.book,
            chapter=args.chapter or "",
            segment=args.segment or "",
            anchor=args.anchor or "",
            next_anchor=args.next_anchor or "",
            next_segment=args.next_segment or "",
        )
        _refresh(store, user, args.book)
    progress = meta["progress"]
    _ok(f"进度已更新：{progress.get('chapter') or '—'}·{progress.get('segment') or '—'}")
    if progress.get("anchor"):
        _out(f"  锚点：\"{shorten(progress['anchor'], 50)}\"")
    if meta["next"].get("anchor"):
        _out(f"  下次接续：\"{shorten(meta['next']['anchor'], 50)}\"")
    return EXIT_OK


def cmd_note_add(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_)
    text = args.text
    if text == "-":
        text = sys.stdin.read()
    with store.lock(f"book-{user['uid']}-{args.book}"):
        note = notes_mod.add_note(
            store,
            user,
            slug=args.book,
            kind=args.kind,
            text=text,
            anchor=args.anchor or "",
            lesson=args.lesson,
            chapter=args.chapter or "",
            on_behalf=args.on_behalf,
        )
        target = registry.resolve(store, note["uid"])
        _refresh(store, target, args.book)
    if args.json:
        print(json.dumps(note, ensure_ascii=False, indent=2))
    else:
        _ok(
            f"批注已写入 {target['name']} 的书房 ｜ {notes_mod.KINDS[note['kind']][1]} ｜ id={note['id']}"
        )
        _out(f"  {shorten(note['text'], 60)}")
    return EXIT_OK


def cmd_render(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_) if args.as_ else None
    if args.indexes_only:
        counts = render.refresh_all(store) if not user else {
            "books": 0,
            "users": 1,
        }
        if user:
            render.render_user_index(store, user, write=True)
            render.render_global_index(store, write=True)
        _ok(f"索引已刷新（{counts['users']} 间书房）")
        return EXIT_OK

    if not args.book:
        raise MarginaliaError("请用 --book 指定课程（或 --indexes-only）")
    assert user is not None
    text = render.render_book(store, user, args.book, write=False)
    if args.output:
        out_path = Path(args.output).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        _ok(f"已渲染到 {out_path}")
    else:
        store.write_text(store.book_paths(user["uid"], args.book)["rendered"], text)
        _ok(f"已渲染：{store.rel(store.book_paths(user['uid'], args.book)['rendered'])}")
    render.render_user_index(store, user, write=True)
    render.render_global_index(store, write=True)
    return EXIT_OK


def cmd_export(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_)
    target = user
    if args.on_behalf:
        registry.require_owner(store, user, "代导出学员批注本")
        target = registry.resolve(store, args.on_behalf)
    meta = books.load_meta(store, target["uid"], args.book)
    text = render.render_book(store, target, args.book, write=False)
    out_dir = Path(args.out or ".").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"《{meta.get('title', args.book)}》·共读批注本.md"
    out_path = out_dir / filename
    out_path.write_text(text, encoding="utf-8")
    audit.append(
        store,
        target["uid"],
        actor=user["uid"],
        on_behalf=args.on_behalf,
        op="book.export",
        target=store.rel(store.book_paths(target["uid"], args.book)["dir"]),
        detail={"out": str(out_path)},
    )
    _ok(f"已导出：{out_path}")
    return EXIT_OK


def cmd_stats(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_)
    data = notes_mod.stats(store, user["uid"])
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return EXIT_OK
    _out(f"# {user['name']} 的学习统计")
    _out(f"批注总数：{data['notes_total']}")
    kinds = " ｜ ".join(
        f"{notes_mod.KINDS[k][1]} {v}" for k, v in data["by_kind"].items() if v
    )
    if kinds:
        _out(f"构成：{kinds}")
    if data["books"]:
        _out("")
        rows = [
            [b["title"], b["status"], f"{b['chapters_done']}/{b['chapters_total']}", str(b["notes"])]
            for b in data["books"]
        ]
        _out(_table(["课程", "状态", "已讲篇目", "批注"], rows))
    return EXIT_OK


def cmd_verify(args: argparse.Namespace, store: Store) -> int:
    report = verify.verify_all(
        store,
        check_render=args.check_render,
        strict=args.strict,
        only_uid=args.as_,
        only_slug=args.book,
    )
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        checked = " ｜ ".join(f"{k}={v}" for k, v in sorted(report.checked.items()))
        if report.errors:
            _out(f"✗ 完整性校验失败（{len(report.errors)} 项错误）")
            for item in report.errors:
                _out(f"  ✗ {item}")
        if report.warnings:
            _out(f"⚠ 警告（{len(report.warnings)} 项）")
            for item in report.warnings:
                _out(f"  ⚠ {item}")
        if report.ok:
            _ok(f"完整性校验通过（{checked or '无对象'}）")
    return EXIT_OK if report.ok else EXIT_INTEGRITY


def cmd_import(args: argparse.Namespace, store: Store) -> int:
    user = registry.resolve(store, args.as_)
    with store.lock(f"import-{user['uid']}"):
        summary = importer.import_book(
            store,
            user,
            source_file=args.from_,
            title=args.title,
            slug=args.slug,
            apply=args.apply,
            force_speaker=args.force_speaker,
        )
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return EXIT_OK
    mode = "已导入" if summary["applied"] else "试运行（未写盘）"
    _out(f"# 迁移 {mode}：《{summary['title']}》 → {summary['slug']}")
    _out(f"  学员：{summary['target']}（uid: {summary['uid']}）")
    _out(f"  原文：{summary['source_chars']} 字符 ｜ sha256 {summary['source_sha256'][:16]}…")
    _out(f"  课程卡：{'已剥离（代码重新生成）' if summary['header_stripped'] else '未检测到'}")
    _out(f"  篇目：{summary['chapters']} ｜ 批注：{summary['notes_total']}（已定位 {summary['notes_resolved']}）")
    if summary["notes_by_kind"]:
        _out("  构成：" + " ｜ ".join(f"{k}={v}" for k, v in summary["notes_by_kind"].items()))
    if summary["unresolved"]:
        _out(f"  ⚠ {len(summary['unresolved'])} 条锚点无法唯一定位，将写入 _unresolved.jsonl 待人工处理")
    if not summary["applied"]:
        _out("")
        _out("确认无误后加 --apply 真正写盘：")
        _out(f"  {PROG} import --as {summary['uid']} --from <文件> --apply")
    return EXIT_OK


def cmd_lint(args: argparse.Namespace, store: Store) -> int:
    """portable 模式的事后审计：纯 Markdown 批注本到底有没有串档。"""
    projection = lint.registry_projection(store)
    targets: list[Path] = []
    for raw in args.paths or []:
        path = Path(raw).expanduser()
        if path.is_dir():
            targets.extend(sorted(path.rglob("*.md")))
        else:
            targets.append(path)
    if not targets:
        targets = lint.discover_targets(store)
    if not targets:
        _out("（没有可审计的批注本）")
        return EXIT_OK

    reports = []
    for path in targets:
        try:
            reports.append(lint.lint_file(store, path, args.expect_uid, projection))
        except MarginaliaError as exc:
            eprint(f"✗ {exc.message}")
            return EXIT_ERROR

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], ensure_ascii=False, indent=2))
    else:
        _out(lint.summarize(reports))
    return EXIT_OK if not lint.has_errors(reports) else EXIT_INTEGRITY


def cmd_doctor(args: argparse.Namespace, store: Store) -> int:
    _out(f"# {PROG} doctor")
    _out(f"Python：{sys.version.split()[0]}")
    _out(f"数据根：{store.root}（{'存在' if store.root.is_dir() else '缺失'}）")
    if not store.is_initialized():
        _out("状态：未初始化")
        _out(f"修复：{PROG} init")
        return EXIT_ERROR
    users = registry.list_users(store)
    book_count = sum(len(books.list_books(store, u["uid"])) for u in users)
    _out(f"注册表：{len(users)} 位学员 ｜ 课程：{book_count} 门")
    locks = sorted(store.root.glob(".lock-*"))
    if locks:
        _out(f"⚠ 残留锁文件 {len(locks)} 个（陈旧锁会在 60s 后自动回收）")
        for lock in locks:
            _out(f"  {lock.name}")
    report = verify.verify_all(store, check_render=False)
    if report.errors:
        _out(f"✗ {len(report.errors)} 项完整性问题，运行 `{PROG} verify` 查看")
        return EXIT_INTEGRITY
    _ok("数据健康")
    _out("")
    _out("# 隔离能力边界（AC18）")
    _out("模式 A · strict：本进程可执行 → 路径/说话人由代码派生，越权即拒（写入前拦截）")
    _out("模式 B · portable：无执行通道的 Agent → 只能靠协议约束；事后用 `marginalia lint` 取证")
    linted = lint.discover_targets(store)
    if linted:
        bad = [r for r in (lint.lint_file(store, p) for p in linted) if not r.ok]
        _out(f"自检：已审计 {len(linted)} 份批注本，{'✗ ' + str(len(bad)) + ' 份存在串档迹象' if bad else '✓ 未发现串档迹象'}")
    return EXIT_OK


# ---------------------------------------------------------------- 参数


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Marginalia · 多用户共读批注本的确定性 IO 层",
        epilog="所有写操作都必须走这里——路径与说话人由代码派生，不接受手写。",
    )
    parser.add_argument("--root", help="数据根目录（默认 ./study 或 $MARGINALIA_HOME）")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument("--version", action="version", version=f"{PROG} 3.0.0")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="初始化数据根")
    p.add_argument("--owner-open-id", help="同时建立 owner 书房（sender_id）")
    p.add_argument("--owner-name", help="owner 称呼")
    p.add_argument("--force", action="store_true", help="覆盖已有 registry.json")
    p.set_defaults(func=cmd_init)

    user = sub.add_parser("user", help="学员注册表")
    user_sub = user.add_subparsers(dest="user_command", required=True)

    p = user_sub.add_parser("add", help="建档")
    p.add_argument("--open-id", required=True, help="真实消息的 sender_id")
    p.add_argument("--name", required=True, help="称呼（会写进批注标签）")
    p.add_argument("--uid", help="自定义 uid（默认由称呼派生）")
    p.add_argument("--role", default="student", choices=sorted(registry.ROLES))
    p.add_argument("--alias", help="别名，逗号分隔")
    p.add_argument("--goal", help="学习目标")
    p.add_argument("--pace", help="偏好节奏")
    p.set_defaults(func=cmd_user_add)

    p = user_sub.add_parser("resolve", help="解析身份")
    p.add_argument("token", nargs="?", help="uid / open_id / 称呼")
    p.add_argument("--open-id")
    p.add_argument("--name")
    p.set_defaults(func=cmd_user_resolve)

    p = user_sub.add_parser("list", help="列出学员")
    p.set_defaults(func=cmd_user_list)

    book = sub.add_parser("book", help="课程（一本书 = 一门课）")
    book_sub = book.add_subparsers(dest="book_command", required=True)

    p = book_sub.add_parser("create", help="开课（入库底本）")
    p.add_argument("--as", dest="as_", required=True, help="学员身份")
    p.add_argument("--title", required=True, help="书名")
    p.add_argument("--source", help="底本 Markdown 路径")
    p.add_argument("--slug", help="课程标识（默认由书名派生）")
    p.add_argument("--edition", help="版本说明")
    p.set_defaults(func=cmd_book_create)

    p = book_sub.add_parser("list", help="列出课程")
    p.add_argument("--as", dest="as_", required=True)
    p.set_defaults(func=cmd_book_list)

    p = sub.add_parser("chapter", help="篇目状态")
    chapter_sub = p.add_subparsers(dest="chapter_command", required=True)
    p = chapter_sub.add_parser("mark", help="标记篇目状态")
    p.add_argument("--as", dest="as_", required=True)
    p.add_argument("--book", required=True, help="课程 slug")
    p.add_argument("--chapter", required=True, help="篇名")
    p.add_argument("--status", required=True, choices=sorted(books.CHAPTER_STATUSES))
    p.set_defaults(func=cmd_chapter_mark)

    progress = sub.add_parser("progress", help="学习进度")
    progress_sub = progress.add_subparsers(dest="progress_command", required=True)
    p = progress_sub.add_parser("set", help="设置当前进度与接续点")
    p.add_argument("--as", dest="as_", required=True)
    p.add_argument("--book", required=True)
    p.add_argument("--chapter")
    p.add_argument("--segment", help="段（如「第三段」）")
    p.add_argument("--anchor", help="最后讲完的原句")
    p.add_argument("--next-anchor", help="下一段开头原句")
    p.add_argument("--next-segment")
    p.set_defaults(func=cmd_progress_set)

    note = sub.add_parser("note", help="批注")
    note_sub = note.add_subparsers(dest="note_command", required=True)
    p = note_sub.add_parser("add", help="追加一条批注")
    p.add_argument("--as", dest="as_", required=True)
    p.add_argument("--book", required=True)
    p.add_argument("--kind", required=True, choices=sorted(notes_mod.KINDS))
    p.add_argument("--text", required=True, help="批注正文；用 - 从 stdin 读")
    p.add_argument("-a", "--anchor", help="锚点：逐字摘自原文的一句")
    p.add_argument("-l", "--lesson", type=int, help="第几课")
    p.add_argument("--chapter", help="篇名（默认按锚点自动推断）")
    p.add_argument("--on-behalf", help="owner 代学员记录时指定学员 uid")
    p.set_defaults(func=cmd_note_add)

    p = sub.add_parser("render", help="渲染批注本 / 索引")
    p.add_argument("--as", dest="as_")
    p.add_argument("--book")
    p.add_argument("-o", "--output", help="输出路径（默认写回 book.md）")
    p.add_argument("--indexes-only", action="store_true")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("export", help="导出批注本（结课交付）")
    p.add_argument("--as", dest="as_", required=True)
    p.add_argument("--book", required=True)
    p.add_argument("--out", help="输出目录（默认当前目录）")
    p.add_argument("--on-behalf", help="owner 代导出时指定学员")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("verify", help="完整性校验（防串档断言）")
    p.add_argument("--as", dest="as_", help="只校验某位学员")
    p.add_argument("--book", help="只校验某门课")
    p.add_argument("--strict", action="store_true", help="警告升级为错误")
    p.add_argument("--check-render", action="store_true", help="校验 book.md 与真源一致")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("stats", help="学习统计")
    p.add_argument("--as", dest="as_", required=True)
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("import", help="迁移旧版单文件批注本")
    p.add_argument("--as", dest="as_", required=True)
    p.add_argument("--from", dest="from_", required=True, help="旧批注本 Markdown")
    p.add_argument("--title")
    p.add_argument("--slug")
    p.add_argument("--apply", action="store_true", help="真正写盘（默认试运行）")
    p.add_argument("--force-speaker", action="store_true", help="说话人不符时强制归一到当前学员")
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("lint", help="审计纯 Markdown 批注本（portable 模式取证）")
    p.add_argument("paths", nargs="*", help="文件或目录（默认审计整个 users/）")
    p.add_argument("--expect-uid", help="要求课程卡 uid 必须等于该值")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("doctor", help="环境自检 + 能力边界")
    p.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    raw = list(sys.argv[1:] if argv is None else argv)
    # 容错：--json 是全局开关，但用户/模型经常写在子命令后面
    if "--json" in raw:
        raw = [t for t in raw if t != "--json"]
        raw.insert(0, "--json")
    parser = build_parser()
    args = parser.parse_args(raw)
    store = Store(args.root)
    try:
        return int(args.func(args, store))
    except MarginaliaError as exc:
        eprint(f"✗ {exc.message}")
        if exc.hint:
            eprint(f"  → {exc.hint}")
        return exc.code
    except KeyboardInterrupt:
        eprint("已中断")
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
