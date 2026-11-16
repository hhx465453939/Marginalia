"""测试基类：在临时目录里跑真实的 CLI。"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from marginalia.cli import main

SOURCE = """# 鬼谷子

## 捭阖第一

粤若稽古，圣人之在天地间也，为众生之先。观阴阳之开阖以名命物。

变化无穷，各有所归。或阴或阳，或柔或刚。

## 反应第二

古之大化者，乃与无形俱生。反以观往，覆以验来。
"""

LEGACY = """# 《鬼谷子》·共读批注本（主人）

- 学员：主人（uid: owner）
- 底本：四部丛刊本
- 开课日期：2026-11-16
- 状态：进行中
- 更新时间：2026-11-16 00:35

## 全书地图

| 篇目 | 状态 |
|------|------|
| 捭阖第一 | 已讲 |
| 反应第二 | 未讲 |

## 当前进度

- 讲到：捭阖第一·第三段
- 锚点："变化无穷，各有所归。"

## 下次接续点

- 反应第二·第一段："古之大化者，乃与无形俱生。"

---

# 鬼谷子

## 捭阖第一

粤若稽古，圣人之在天地间也，为众生之先。观阴阳之开阖以名命物。

> 🦞 **【第1课·2026-11-16】** 这句是全书的门，先"稽古"再"观阴阳"。
>
> 👤 **主人**：为什么要先稽古？
>
> 💬 **讨论**：稽古是取得合法性的动作，不是考据癖。

变化无穷，各有所归。或阴或阳，或柔或刚。

> ✅ **进度**：本段完于 2026-11-16

## 反应第二

古之大化者，乃与无形俱生。反以观往，覆以验来。
"""


class BaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "study"
        self.source_file = self.tmp / "book.md"
        self.source_file.write_text(SOURCE, encoding="utf-8")
        code, out = self.cli("init", "--owner-open-id", "ou_owner", "--owner-name", "主人")
        self.assertEqual(code, 0, out)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---------- 工具 ----------

    def cli(self, *args: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            code = main(["--root", str(self.root), *args])
        return code, buf.getvalue()

    def cli_json(self, *args: str) -> tuple[int, dict]:
        code, out = self.cli(*args, "--json")
        payload: dict = {}
        # 取最后一段 JSON（前面可能混有提示行）
        start = out.find("{")
        if start >= 0:
            payload = json.loads(out[start:])
        return code, payload

    def add_student(self, name: str = "小林", open_id: str = "ou_lin") -> str:
        code, out = self.cli("user", "add", "--open-id", open_id, "--name", name)
        self.assertEqual(code, 0, out)
        code, payload = self.cli_json("user", "resolve", "--name", name)
        self.assertEqual(code, 0)
        return payload["uid"]

    def open_book(self, who: str = "主人", slug_expected: str = "鬼谷子") -> None:
        code, out = self.cli(
            "book", "create", "--as", who, "--title", "鬼谷子", "--source", str(self.source_file)
        )
        self.assertEqual(code, 0, out)
        self.assertTrue(self.book_dir(who, slug_expected).is_dir())

    def book_dir(self, who: str, slug: str = "鬼谷子") -> Path:
        code, payload = self.cli_json("user", "resolve", who)
        self.assertEqual(code, 0)
        return self.root / "users" / payload["uid"] / "books" / slug

    def note(self, who: str, kind: str, anchor: str, text: str = "笔记", book: str = "鬼谷子"):
        return self.cli(
            "note", "add", "--as", who, "--book", book, "--kind", kind,
            "--anchor", anchor, "--text", text,
        )

    def annotations(self, who: str, book: str = "鬼谷子") -> list[dict]:
        path = self.book_dir(who, book) / "annotations.jsonl"
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]

    def tree_snapshot(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*"))
