"""AC15 / AC16：portable 模式事后审计器（lint）。

这是「不猜环境」的落点：即使 Agent 跑不了 CLI，也能事后证明有没有串档。
"""

from __future__ import annotations

import unittest

from tests.base import BaseTest

POISON = "> 👤 **小林**：这是我的批注，被写错了地方。"


class LintTest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.add_student()
        self.open_book("主人")
        self.open_book("小林")
        self.note("主人", "explain", "粤若稽古，圣人之在天地间也，为众生之先。", "主人专属讲解")
        self.note("主人", "ask", "变化无穷，各有所归。", "主人的问题")

    def owner_book(self):
        return self.book_dir("主人") / "book.md"

    def test_clean(self) -> None:
        code, out = self.cli("lint")
        self.assertEqual(code, 0, out)
        self.assertIn("通过审计", out)

    def test_poison(self) -> None:
        """AC16：把别人的批注塞进主人书房 → exit 3 且点名行号。"""
        path = self.owner_book()
        text = path.read_text(encoding="utf-8")
        poisoned = text + "\n" + POISON + "\n"
        path.write_text(poisoned, encoding="utf-8")

        code, out = self.cli("lint", str(path))
        self.assertEqual(code, 3, out)
        self.assertIn("L2", out)
        self.assertIn("小林", out)
        lines = poisoned.split("\n")
        expected = lines.index(POISON) + 1
        self.assertIn(f":{expected}:", out, f"应精确指向第 {expected} 行，实际输出：{out}")

    def test_no_card(self) -> None:
        path = self.owner_book()
        text = path.read_text(encoding="utf-8")
        stripped = "\n".join(
            line for line in text.split("\n") if not line.strip().startswith("- 学员：")
        )
        path.write_text(stripped, encoding="utf-8")
        code, out = self.cli("lint", str(path))
        self.assertEqual(code, 3, out)
        self.assertIn("L1", out)

    def test_uid_marker(self) -> None:
        path = self.owner_book()
        text = path.read_text(encoding="utf-8")
        path.write_text("<!-- marginalia:uid=小林 -->\n" + text, encoding="utf-8")
        code, out = self.cli("lint", str(path))
        self.assertEqual(code, 3, out)
        self.assertIn("L3", out)

    def test_expect_uid(self) -> None:
        code, out = self.cli("lint", str(self.owner_book()), "--expect-uid", "小林")
        self.assertEqual(code, 3, out)
        self.assertIn("L8", out)

    def test_two_books(self) -> None:
        """隔离良好的两本书各自通过——lint 验的是归属，不是挑刺。"""
        code, out = self.cli("lint")
        self.assertEqual(code, 0, out)
        owner = (self.book_dir("主人") / "book.md").read_text(encoding="utf-8")
        lin = (self.book_dir("小林") / "book.md").read_text(encoding="utf-8")
        self.assertIn("主人专属讲解", owner)
        self.assertNotIn("主人专属讲解", lin)

    def test_doctor_modes(self) -> None:
        """AC18：doctor 必须说明两种模式的能力边界。"""
        code, out = self.cli("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("模式 A · strict", out)
        self.assertIn("模式 B · portable", out)


if __name__ == "__main__":
    unittest.main()
