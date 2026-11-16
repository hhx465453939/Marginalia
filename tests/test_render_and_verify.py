"""AC7 渲染格式 / AC8 verify / AC9 审计链。"""

from __future__ import annotations

import json
import unittest

from tests.base import BaseTest


class RenderTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.open_book()
        self.note("主人", "explain", "粤若稽古，圣人之在天地间也，为众生之先。", "这句是全书的门。", )
        self.note("主人", "ask", "变化无穷，各有所归。", "为什么先说变化？")

    def text(self) -> str:
        return (self.book_dir("主人") / "book.md").read_text(encoding="utf-8")

    def test_card(self) -> None:
        body = self.text()
        self.assertIn("# 《鬼谷子》·共读批注本（主人）", body)
        self.assertIn("- 学员：主人（uid: owner）", body)
        self.assertIn("## 全书地图", body)
        self.assertIn("## 当前进度", body)
        self.assertIn("## 下次接续点", body)
        self.assertIn("| 捭阖第一 |", body)
        self.assertIn("| 反应第二 |", body)

    def test_tags(self) -> None:
        body = self.text()
        self.assertIn("🦞 **【", body)
        self.assertIn("👤 **主人**：", body)

    def test_quote_needs_blank_line(self) -> None:
        """引用块前必须有空行，否则 CommonMark 会当成段落续行。"""
        lines = self.text().split("\n")
        for i, line in enumerate(lines):
            if line.startswith("> 🦞") or line.startswith("> 👤"):
                self.assertTrue(
                    i > 0 and lines[i - 1].strip() == "",
                    f"第 {i+1} 行引用块前缺空行：{line[:30]}",
                )

    def test_source_verbatim(self) -> None:
        body = self.text()
        self.assertIn("粤若稽古，圣人之在天地间也，为众生之先。观阴阳之开阖以名命物。", body)
        self.assertIn("古之大化者，乃与无形俱生。反以观往，覆以验来。", body)

    def test_progress_card(self) -> None:
        code, out = self.cli(
            "progress", "set", "--as", "主人", "--book", "鬼谷子",
            "--chapter", "捭阖第一", "--segment", "第二段",
            "--anchor", "变化无穷，各有所归。",
        )
        self.assertEqual(code, 0, out)
        body = self.text()
        self.assertIn("捭阖第一·第二段", body)
        meta = json.loads((self.book_dir("主人") / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["progress"]["chapter"], "捭阖第一")
        self.assertEqual(meta["chapters"][0]["status"], "进行中")

    def test_chapter_mark(self) -> None:
        code, out = self.cli(
            "chapter", "mark", "--as", "主人", "--book", "鬼谷子",
            "--chapter", "反应第二", "--status", "已讲",
        )
        self.assertEqual(code, 0, out)
        self.assertIn("| 反应第二 | 已讲 |", self.text())


class VerifyTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.open_book()
        self.note("主人", "ask", "变化无穷，各有所归。", "一条干净批注")

    def test_clean(self) -> None:
        code, out = self.cli("verify", "--check-render", "--strict")
        self.assertEqual(code, 0, out)
        self.assertIn("通过", out)

    def test_bad_uid(self) -> None:
        """AC8：注入归属错误的批注 → verify exit 3。"""
        path = self.book_dir("主人") / "annotations.jsonl"
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]
        bad = dict(rows[0])
        bad["id"] = "n-bad-0001"
        bad["uid"] = "小林"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(bad, ensure_ascii=False) + "\n")

        code, out = self.cli("verify")
        self.assertEqual(code, 3, out)
        self.assertIn("uid 归属错误", out)

    def test_wrong_speaker(self) -> None:
        path = self.book_dir("主人") / "annotations.jsonl"
        rows = [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]
        bad = dict(rows[0])
        bad["id"] = "n-bad-0002"
        bad["speaker"] = "别人"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(bad, ensure_ascii=False) + "\n")

        code, out = self.cli("verify")
        self.assertEqual(code, 3, out)
        self.assertIn("说话人不属于本书房", out)

    def test_render_tamper(self) -> None:
        book = self.book_dir("主人") / "book.md"
        book.write_text(book.read_text(encoding="utf-8") + "\n手改一行\n", encoding="utf-8")
        code, out = self.cli("verify", "--check-render", "--strict")
        self.assertEqual(code, 3, out)
        self.assertIn("book.md", out)


class AuditTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.open_book()
        self.note("主人", "ask", "变化无穷，各有所归。", "a")
        self.note("主人", "ask", "古之大化者，乃与无形俱生。", "b")

    def audit(self):
        return self.root / "users" / "owner" / "audit.jsonl"

    def test_chain_ok(self) -> None:
        code, out = self.cli("verify")
        self.assertEqual(code, 0, out)
        rows = [json.loads(l) for l in self.audit().read_text(encoding="utf-8").split("\n") if l.strip()]
        self.assertGreaterEqual(len(rows), 4)
        self.assertEqual(rows[0]["prev_hash"], "0" * 64)

    def test_chain_break(self) -> None:
        """AC9：删掉中间一行 → 断链被查出。"""
        rows = [l for l in self.audit().read_text(encoding="utf-8").split("\n") if l.strip()]
        del rows[1]
        self.audit().write_text("\n".join(rows) + "\n", encoding="utf-8")
        code, out = self.cli("verify")
        self.assertEqual(code, 3, out)
        self.assertIn("链断裂", out)

    def test_chain_tamper(self) -> None:
        rows = [json.loads(l) for l in self.audit().read_text(encoding="utf-8").split("\n") if l.strip()]
        rows[1]["op"] = "note.delete"
        self.audit().write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )
        code, out = self.cli("verify")
        self.assertEqual(code, 3, out)
        self.assertIn("内容被篡改", out)


if __name__ == "__main__":
    unittest.main()
