"""Marginalia · 存储层：路径派生、原子读写、文件锁、slug 校验。

**本模块是整个项目防串档的地基**：
  任何人都不能通过传路径决定写到哪里——路径只能由 (uid, slug) 派生，
  而 uid 来自注册表、slug 经过白名单正则校验。
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .util import (
    EXIT_IDENTITY,
    MarginaliaError,
    atomic_write,
    canonical_json,
    read_text,
)

# slug 白名单：ASCII 字母数字 + 中文 + `_ - .`，但禁止以 `.` 开头、禁止 `..`
_SLUG_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff._-]{0,63}$")
_UID_RE = re.compile(r"^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_-]{0,63}$")
_RESERVED = {"_trash", "_unresolved", ".", "..", "con", "prn", "aux", "nul"}

LOCK_WAIT_SECONDS = 30.0
LOCK_STALE_SECONDS = 60.0


def validate_slug(slug: str, kind: str = "book") -> str:
    """校验 slug，拒绝路径穿越与保留字。返回规范化后的 slug。"""
    if not isinstance(slug, str) or not slug:
        raise MarginaliaError(f"{kind} 标识为空", EXIT_IDENTITY)
    if len(slug) > 64:
        raise MarginaliaError(f"{kind} 标识过长（≤64）: {slug!r}", EXIT_IDENTITY)
    if any(ch in slug for ch in ("/", "\\", "\x00")):
        raise MarginaliaError(f"{kind} 标识禁止包含路径分隔符: {slug!r}", EXIT_IDENTITY)
    if slug.startswith(".") or ".." in slug:
        raise MarginaliaError(f"{kind} 标识禁止以点开头或包含 '..': {slug!r}", EXIT_IDENTITY)
    if slug.lower() in _RESERVED:
        raise MarginaliaError(f"{kind} 标识为保留字: {slug!r}", EXIT_IDENTITY)
    if not _SLUG_RE.match(slug):
        raise MarginaliaError(
            f"{kind} 标识只允许 ASCII 字母数字、中文、下划线、连字符、点: {slug!r}",
            EXIT_IDENTITY,
        )
    return slug


def validate_uid(uid: str) -> str:
    if not isinstance(uid, str) or not _UID_RE.match(uid):
        raise MarginaliaError(
            f"uid 非法（字母数字或中文，1–64 位，可含 _ -，不得有空格/分隔符）: {uid!r}",
            EXIT_IDENTITY,
        )
    return uid


def default_slug(title: str) -> str:
    """从书名生成 slug：中文直接用，ASCII 转小写连字符。"""
    t = title.strip().strip("《》").strip()
    if re.search(r"[\u4e00-\u9fff]", t):
        slug = re.sub(r"[\s《》「」〈〉·・:：,，。.、!！?？'\"]+", "", t)
    else:
        slug = re.sub(r"[^A-Za-z0-9]+", "-", t).strip("-").lower()
    slug = slug[:64] or "book"
    if slug.startswith("."):
        slug = "b" + slug
    return slug


class Store:
    """数据根（默认 ./study，可用 MARGINALIA_HOME 覆盖）。"""

    def __init__(self, root: str | Path | None = None):
        env = os.environ.get("MARGINALIA_HOME")
        self.root = Path(root or env or "study").expanduser().resolve()
        self._held = threading.local()

    # ---------- 路径派生 ----------
    @property
    def registry_path(self) -> Path:
        return self.root / "registry.json"

    @property
    def users_dir(self) -> Path:
        return self.root / "users"

    @property
    def global_index(self) -> Path:
        return self.root / "INDEX.md"

    def user_dir(self, uid: str) -> Path:
        return self.users_dir / validate_uid(uid)

    def profile_path(self, uid: str) -> Path:
        return self.user_dir(uid) / "profile.json"

    def user_index(self, uid: str) -> Path:
        return self.user_dir(uid) / "INDEX.md"

    def audit_path(self, uid: str) -> Path:
        return self.user_dir(uid) / "audit.jsonl"

    def books_dir(self, uid: str) -> Path:
        return self.user_dir(uid) / "books"

    def book_dir(self, uid: str, slug: str) -> Path:
        d = self.books_dir(uid) / validate_slug(slug)
        # 双保险：解析后的真实路径必须仍在该学员书房内
        try:
            resolved = d.resolve(strict=False)
            allowed = self.books_dir(uid).resolve(strict=False)
        except OSError as exc:  # pragma: no cover - 极罕见
            raise MarginaliaError(f"路径解析失败: {exc}", EXIT_IDENTITY) from exc
        if resolved != allowed and allowed not in resolved.parents:
            raise MarginaliaError(f"路径越界: {d}", EXIT_IDENTITY)
        return d

    def book_paths(self, uid: str, slug: str) -> dict[str, Path]:
        d = self.book_dir(uid, slug)
        return {
            "dir": d,
            "meta": d / "meta.json",
            "source": d / "source.md",
            "annotations": d / "annotations.jsonl",
            "rendered": d / "book.md",
            "unresolved": d / "_unresolved.jsonl",
        }

    def rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path)

    # ---------- 初始化 ----------
    def is_initialized(self) -> bool:
        return self.registry_path.is_file()

    def ensure(self) -> None:
        self.users_dir.mkdir(parents=True, exist_ok=True)

    def require_initialized(self) -> None:
        if not self.is_initialized():
            raise MarginaliaError(
                f"数据根未初始化: {self.root}",
                hint="先运行 `marginalia init`",
            )

    # ---------- JSON ----------
    def read_json(self, path: Path, default: dict | None = None) -> dict:
        if not path.is_file():
            if default is not None:
                return default
            raise MarginaliaError(f"文件缺失: {self.rel(path)}")
        try:
            return json.loads(read_text(path))
        except json.JSONDecodeError as exc:
            raise MarginaliaError(f"JSON 解析失败 {self.rel(path)}: {exc}") from exc

    def write_json(self, path: Path, obj: Any) -> None:
        atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")

    def write_text(self, path: Path, text: str) -> None:
        atomic_write(path, text)

    # ---------- JSONL ----------
    def read_jsonl(self, path: Path) -> list[dict]:
        if not path.is_file():
            return []
        out: list[dict] = []
        for lineno, line in enumerate(read_text(path).split("\n"), 1):
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise MarginaliaError(f"JSONL 损坏 {self.rel(path)}:{lineno} — {exc}") from exc
        return out

    def append_jsonl(self, path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = canonical_json(obj) + "\n"
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())

    # ---------- 文件锁 ----------
    @contextmanager
    def lock(self, name: str, timeout: float = LOCK_WAIT_SECONDS) -> Iterator[None]:
        """跨进程排他锁（O_EXCL + 重试 + 陈旧锁回收），**同一线程可重入**。

        重入是必需的：库函数自带锁，CLI 也会对同一资源加锁。
        没有重入，库函数就会把自己锁死 30 秒。
        """
        key = re.sub(r"[^A-Za-z0-9_.\-\u4e00-\u9fff]", "_", name)[:80]
        held = getattr(self._held, "names", None)
        if held is None:
            held = set()
            self._held.names = held
        if key in held:
            yield
            return

        lock_path = self.root / f".lock-{key}"
        self.root.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        fd = -1
        while True:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.time()}".encode())
                break
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except OSError:
                    age = 0.0
                if age > LOCK_STALE_SECONDS:
                    try:
                        lock_path.unlink()
                    except OSError:
                        pass
                    continue
                if time.monotonic() > deadline:
                    raise MarginaliaError(
                        f"获取写锁超时（{timeout:.0f}s）: {lock_path.name}",
                        hint="是否有另一个 marginalia 进程卡住？确认后可删除该锁文件",
                    ) from None
                time.sleep(0.05)
        held.add(key)
        try:
            yield
        finally:
            held.discard(key)
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                lock_path.unlink()
            except OSError:
                pass
