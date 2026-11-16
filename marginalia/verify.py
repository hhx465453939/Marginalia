"""Marginalia · 完整性校验：把「防幻觉」变成可执行的断言。

`marginalia verify` 是这个项目最重要的命令——它回答一个问题：
**现在磁盘上这份数据，还能不能证明每个学员的记录只属于他自己？**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import audit, registry, render
from .notes import check_note, check_speaker, load_notes
from .store import Store, validate_slug, validate_uid
from .util import EXIT_INTEGRITY, MarginaliaError, read_text, sha256_text

ERROR = "ERROR"
WARN = "WARN"


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked: dict[str, int] = field(default_factory=dict)

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def bump(self, key: str, n: int = 1) -> None:
        self.checked[key] = self.checked.get(key, 0) + n

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked": self.checked,
        }


def verify_registry(store: Store, report: Report) -> dict | None:
    try:
        reg = registry.load(store)
    except MarginaliaError as exc:
        report.error(f"registry.json: {exc.message}")
        return None

    seen_uid: dict[str, str] = {}
    seen_open: dict[str, str] = {}
    owners = 0
    for user in reg["users"]:
        uid = str(user.get("uid", ""))
        try:
            validate_uid(uid)
        except MarginaliaError as exc:
            report.error(f"registry: {exc.message}")
            continue
        if uid in seen_uid:
            report.error(f"registry: uid 重复 {uid}")
        seen_uid[uid] = uid
        name = (user.get("name") or "").strip()
        if not name:
            report.error(f"registry: {uid} 缺少称呼")
        if user.get("role") == "owner":
            owners += 1
        for open_id in user.get("open_ids", []):
            if not open_id:
                report.error(f"registry: {uid} 存在空 open_id")
            if open_id in seen_open and seen_open[open_id] != uid:
                report.error(f"registry: open_id 重复 {open_id}（{seen_open[open_id]} 与 {uid}）")
            seen_open[open_id] = uid
        report.bump("users")
    if owners > 1:
        report.error(f"registry: owner 数量 {owners} > 1")
    return reg


def verify_user(store: Store, user: dict, report: Report, check_render: bool, strict: bool) -> None:
    uid = user["uid"]
    udir = store.user_dir(uid)
    if not udir.is_dir():
        report.error(f"{uid}: 书房目录缺失 {store.rel(udir)}")
        return

    # 符号链接逃逸检查
    try:
        resolved = udir.resolve()
        if resolved != udir and store.root not in resolved.parents and resolved != store.root:
            report.error(f"{uid}: 书房目录解析到数据根之外 {resolved}")
    except OSError:
        pass

    if not store.profile_path(uid).is_file():
        report.warn(f"{uid}: 缺少 profile.json（学员画像）")

    # 审计链
    try:
        problems = audit.verify_chain(store, uid)
    except MarginaliaError as exc:
        report.error(f"{uid}: 审计链不可读 — {exc.message}")
        problems = []
    for problem in problems:
        report.error(f"{uid}: {problem}")

    books_dir = store.books_dir(uid)
    if not books_dir.is_dir():
        report.warn(f"{uid}: 还没有 books/ 目录")
        return

    for child in sorted(books_dir.iterdir()):
        if child.is_dir() and child.name.startswith("_"):
            continue
        if not child.is_dir():
            continue
        repo = Report()
        slug = child.name
        try:
            validate_slug(slug)
        except MarginaliaError as exc:
            report.error(f"{uid}/{slug}: {exc.message}")
            continue
        _verify_book(store, uid, slug, report, check_render, strict)
        report.checked.update({k: report.checked.get(k, 0) + v for k, v in repo.checked.items()})


def _verify_book(
    store: Store, uid: str, slug: str, report: Report, check_render: bool, strict: bool
) -> None:
    where = f"{uid}/{slug}"
    paths = store.book_paths(uid, slug)

    if not paths["meta"].is_file():
        report.error(f"{where}: 缺少 meta.json")
        return
    try:
        meta = store.read_json(paths["meta"])
    except MarginaliaError as exc:
        report.error(f"{where}: meta.json 不可读 — {exc.message}")
        return

    # G3 归属闸
    if meta.get("uid") != uid:
        report.error(
            f"{where}: 归属冲突 — meta.uid={meta.get('uid')!r} 但位于 {uid!r} 的书房（跨学员串档）"
        )
    if meta.get("slug") != slug:
        report.error(f"{where}: meta.slug={meta.get('slug')!r} 与目录名不一致")

    # G6 原文闸
    if not paths["source"].is_file():
        report.warn(f"{where}: 缺少 source.md（无底本，无法定位批注）")
        source = ""
    else:
        try:
            source = read_text(paths["source"])
        except OSError as exc:
            report.error(f"{where}: source.md 不可读 — {exc}")
            source = ""
        else:
            expected = meta.get("source_sha256")
            if expected and sha256_text(source) != expected:
                report.error(f"{where}: 原文被改动（sha256 不匹配）—— 违反了「原文一字不改」铁律")
            elif not expected:
                report.warn(f"{where}: meta.source_sha256 缺失，原文未受哈希保护")
            report.bump("sources")

    # 批注层
    try:
        notes = load_notes(store, uid, slug)
    except MarginaliaError as exc:
        report.error(f"{where}: annotations.jsonl 损坏 — {exc.message}")
        notes = []
    seen_ids: set[str] = set()
    for note in notes:
        for problem in check_note(store, uid, note, source):
            report.error(f"{where}: {problem}")
        for problem in check_speaker(store, uid, note):
            report.error(f"{where}: {problem}")
        nid = str(note.get("id", ""))
        if nid in seen_ids:
            report.error(f"{where}: 批注 id 重复 {nid}")
        seen_ids.add(nid)
        report.bump("notes")

    # 渲染一致性
    if check_render:
        user = registry.resolve(store, uid)
        if not paths["rendered"].is_file():
            message = f"{where}: book.md 尚未渲染（运行 marginalia render）"
            (report.error if strict else report.warn)(message)
        elif not render.is_render_fresh(store, user, slug):
            message = f"{where}: book.md 与真源不一致（被手改过，或忘了 render）"
            (report.error if strict else report.warn)(message)
        else:
            report.bump("renders")

    # 未解析批注
    if paths["unresolved"].is_file():
        rows = store.read_jsonl(paths["unresolved"])
        if rows:
            report.warn(f"{where}: 有 {len(rows)} 条批注锚点未解析，待人工处理")


def verify_all(
    store: Store,
    check_render: bool = False,
    strict: bool = False,
    only_uid: str | None = None,
    only_slug: str | None = None,
) -> Report:
    report = Report()
    store.require_initialized()
    reg = verify_registry(store, report)
    if reg is None:
        return report

    users = reg["users"]
    if only_uid:
        user = registry.resolve(store, only_uid)
        users = [user]

    for user in users:
        if only_slug:
            _verify_book(store, user["uid"], only_slug, report, check_render, strict)
        else:
            verify_user(store, user, report, check_render, strict)

    # 孤儿书房：users/ 下有目录但注册表没有
    if not only_uid and store.users_dir.is_dir():
        known = {u["uid"] for u in reg["users"]}
        for child in sorted(store.users_dir.iterdir()):
            if child.is_dir() and child.name not in known and not child.name.startswith("_"):
                report.warn(f"users/{child.name}: 书房存在但注册表无此学员（孤儿目录）")

    return report


def assert_ok(report: Report) -> None:
    """strict 场景下直接抛错，交给 CLI 转成 exit 3。"""
    if not report.ok:
        raise MarginaliaError(
            f"完整性校验失败：{len(report.errors)} 项错误\n  - "
            + "\n  - ".join(report.errors[:20]),
            EXIT_INTEGRITY,
        )
