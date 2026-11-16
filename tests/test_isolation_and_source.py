"""AC4 多用户隔离 / AC5 原文哈希锁 / AC6 锚点唯一性。"""

from __future__ import annotations

import json
import unittest

from tests.base import BaseTest

AMBIGUOUS_SOURCE = """# 歧义之书

## 第一篇

各有所归，各有所归。
"""


class IsolationTest(BaseTest):
    def test_two_users_same_book(self) -> None:
        """AC4：同一本书两人共读，批注、进度、书房三处全部隔离。"""
        self.add_student()
        self.open_book("主人")
        self.open_book("小林")

        self.note("主人", "explain", "粤若稽古，圣人之在天地间也，为众生之先。", "主人专属讲解")
        self.note("主人", "ask", "变化无穷，各有所归。", "主人的问题")
        code, _ = self.note("小林", "ask", "反以观往，覆以验来。", "小林的问题")
        self.assertEqual(code, 0)

        owner_notes = self.annotations("主人")
        lin_notes = self.annotations("小林")
        self.assertEqual(len(owner_notes), 2)
        self.assertEqual(len(lin_notes), 1)

        self.assertEqual({n["speaker"] for n in owner_notes}, {"主人"})
        self.assertEqual({n["speaker"] for n in lin_notes}, {"小林"})

        owner_text = (self.book_dir("主人") / "book.md").read_text(encoding="utf-8")
        lin_text = (self.book_dir("小林") / "book.md").read_text(encoding="utf-8")
        self.assertIn("主人专属讲解", owner_text)
        self.assertNotIn("主人专属讲解", lin_text)
        self.assertNotIn("小林的问题", owner_text)

        code, out = self.cli("verify", "--check-render", "--strict")
        self.assertEqual(code, 0, out)

    def test_progress_isolated(self) -> None:
        self.add_student()
        self.open_book("主人")
        self.open_book("小林")
        code, out = self.cli(
            "progress", "set", "--as", "主人", "--book", "鬼谷子",
            "--chapter", "捭阖第一", "--segment", "第一段",
            "--anchor", "粤若稽古，圣人之在天地间也，为众生之先。",
        )
        self.assertEqual(code, 0, out)

        owner_meta = json.loads((self.book_dir("主人") / "meta.json").read_text(encoding="utf-8"))
        lin_meta = json.loads((self.book_dir("小林") / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(owner_meta["progress"]["chapter"], "捭阖第一")
        self.assertEqual(lin_meta["progress"]["chapter"], "")
        self.assertEqual([c["status"] for c in lin_meta["chapters"]], ["未讲", "未讲"])


class SourceLockTest(BaseTest):
    def test_source_tamper(self) -> None:
        """AC5：原文被改一个字符 → verify exit 3，写入也被拒。"""
        self.open_book()
        self.note("主人", "ask", "变化无穷，各有所归。", "先写一条合法批注")

        source_path = self.book_dir("主人") / "source.md"
        original = source_path.read_text(encoding="utf-8")
        source_path.write_text(original.replace("众生之先", "众生之仙"), encoding="utf-8")

        code, out = self.cli("verify")
        self.assertEqual(code, 3, out)
        self.assertIn("原文被改动", out)

        code, out = self.note("主人", "ask", "变化无穷，各有所归。", "篡改后再写")
        self.assertEqual(code, 3, out)
        self.assertIn("原文被改动", out)

    def test_no_source_rewrite_cmd(self) -> None:
        """CLI 不提供任何改写原文的命令（--help 会 SystemExit，故直接查 parser）。"""
        from marginalia.cli import build_parser

        text = build_parser().format_help()
        self.assertNotIn("source-set", text)
        self.assertNotIn("source edit", text)


class AnchorGateTest(BaseTest):
    def test_missing_anchor(self) -> None:
        self.open_book()
        code, out = self.note("主人", "ask", "这句话原文里根本没有出现过", "x")
        self.assertEqual(code, 3, out)
        self.assertIn("不存在", out)

    def test_ambiguous_anchor(self) -> None:
        """AC6：锚点在原文出现多次 → exit 3，避免落错位置。"""
        ambiguous = self.tmp / "ambiguous.md"
        ambiguous.write_text(AMBIGUOUS_SOURCE, encoding="utf-8")
        code, out = self.cli(
            "book", "create", "--as", "主人", "--title", "歧义之书", "--source", str(ambiguous)
        )
        self.assertEqual(code, 0, out)
        code, out = self.cli(
            "note", "add", "--as", "主人", "--book", "歧义之书",
            "--kind", "ask", "--anchor", "各有所归", "--text", "会歧义",
        )
        self.assertEqual(code, 3, out)
        self.assertIn("不唯一", out)

    def test_span_anchor(self) -> None:
        self.open_book()
        code, out = self.note(
            "主人", "ask",
            "古之大化者，乃与无形俱生。反以观往，覆以验来。", "跨行锚点",
        )
        self.assertEqual(code, 0, out)

    def test_whitespace_anchor(self) -> None:
        self.open_book()
        code, out = self.note("主人", "ask", "粤若稽古， 圣人之在天地间也，\n为众生之先。", "空白不同也应命中")
        self.assertEqual(code, 0, out)

    def test_empty_anchor(self) -> None:
        self.open_book()
        code, out = self.cli(
            "note", "add", "--as", "主人", "--book", "鬼谷子",
            "--kind", "ask", "--text", "没有锚点",
        )
        self.assertEqual(code, 3, out)
        self.assertIn("锚点", out)


if __name__ == "__main__":
    unittest.main()
