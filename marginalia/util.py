"""Marginalia · 通用工具（时间、哈希、文本归一化、错误）。

设计原则：所有函数都是纯函数式或幂等的，不持有全局状态。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BJT = timezone(timedelta(hours=8))

# 退出码（与 SPEC §6 对齐）
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_IDENTITY = 2
EXIT_INTEGRITY = 3


class MarginaliaError(Exception):
    """带退出码的可预期错误。"""

    def __init__(self, message: str, code: int = EXIT_ERROR, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


def now_bj(fmt: str = "%Y-%m-%d %H:%M") -> str:
    return datetime.now(BJT).strftime(fmt)


def today_bj() -> str:
    return datetime.now(BJT).strftime("%Y-%m-%d")


def sha256_text(text: str) -> str:
    """文本哈希。CRLF 统一成 LF，避免 Windows/macOS 换行差异误报。"""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="strict")


def norm_text(text: str) -> str:
    """锚点匹配用的归一化：去掉全部空白（含全角空格）。

    只用于「定位」，不用于展示——原文永远不会被改写。
    """
    return re.sub(r"\s+", "", text.replace("\u3000", " "))


def atomic_write(path: Path, text: str) -> None:
    """原子写：先写同目录临时文件，再 os.replace。断电不产生半文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def canonical_json(obj: Any) -> str:
    """稳定序列化：审计链哈希必须与 key 顺序无关。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_obj(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def shorten(text: str, limit: int = 60) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr)
