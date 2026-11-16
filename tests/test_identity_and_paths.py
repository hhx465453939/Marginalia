"""AC1 身份闸 / AC2 路径闸 / AC3 归属闸。"""

from __future__ import annotations

import json
import unittest

from tests.base import BaseTest


class IdentityGateTest(BaseTest):
    def test_owner_uid(self) -> None:
        """owner 的 uid 固定为 owner —— 与旧版 users/owner/ 布局对齐。"""
        code, payload = self.cli_json("user", "resolve", "--open-id", "ou_owner")
        self.assertEqual(code, 0)
        self.assertEqual(payload["uid"], "owner")
        self.assertTrue((self.root / "users" / "owner").is_dir())

    def test_unknown_user(self) -> None:
        """AC1：未注册身份 → exit 2，且磁盘不产生任何新文件。"""
        self.open_book()
        before = self.tree_snapshot()
        code, out = self.cli(
            "note",
            "add",
            "--as",
            "陌生人",
            "--book",
            "鬼谷子",
            "--kind",
            "ask",
            "--anchor",
            "变化无穷，各有所归。",
            "--text",
            "偷偷写一条",
        )
        self.assertEqual(code, 2, out)
        self.assertEqual(before, self.tree_snapshot(), "被拒绝的命令不得写盘")

    def test_dup_openid(self) -> None:
        code, out = self.cli("user", "add", "--open-id", "ou_owner", "--name", "冒名者")
        self.assertEqual(code, 2, out)
        self.assertIn("open_id", out)

    def test_second_owner(self) -> None:
        code, out = self.cli(
            "user", "add", "--open-id", "ou_x", "--name", "另一个主人", "--role", "owner"
        )
        self.assertEqual(code, 2, out)

    def test_resolve_variants(self) -> None:
        uid = self.add_student()
        for token in ("小林", uid, "ou_lin"):
            code, payload = self.cli_json("user", "resolve", token)
            self.assertEqual(code, 0, token)
            self.assertEqual(payload["uid"], uid)


class PathGateTest(BaseTest):
    def test_bad_slug(self) -> None:
        """AC2：路径穿越在 slug 层就被拒。"""
        self.open_book()
        for slug in ("../../etc", "a/b", "..", "/abs/path", "C:\\windows"):
            code, out = self.cli(
                "note",
                "add",
                "--as",
                "主人",
                "--book",
                slug,
                "--kind",
                "ask",
                "--anchor",
                "变化无穷，各有所归。",
                "--text",
                "x",
            )
            self.assertEqual(code, 2, f"{slug} 应被拒绝，实际输出：{out}")

    def test_bad_slug_create(self) -> None:
        code, out = self.cli(
            "book",
            "create",
            "--as",
            "主人",
            "--title",
            "坏书",
            "--source",
            str(self.source_file),
            "--slug",
            "../../evil",
        )
        self.assertEqual(code, 2, out)
        self.assertFalse((self.tmp / "evil").exists())

    def test_dot_slug(self) -> None:
        code, _ = self.cli(
            "book",
            "create",
            "--as",
            "主人",
            "--title",
            "隐藏书",
            "--source",
            str(self.source_file),
            "--slug",
            ".hidden",
        )
        self.assertEqual(code, 2)

    def test_book_dir_scope(self) -> None:
        from marginalia.store import Store, validate_slug
        from marginalia.util import MarginaliaError

        store = Store(self.root)
        self.assertIn("books", str(store.book_dir("owner", "鬼谷子")))
        with self.assertRaises(MarginaliaError):
            validate_slug("../x")


class OwnershipGateTest(BaseTest):
    def test_meta_tamper(self) -> None:
        """AC3：把 meta.uid 改成别人 → 写入被拒（exit 3）。"""
        self.open_book()
        self.add_student()
        meta_path = self.book_dir("主人") / "meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["uid"] = "小林"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

        code, out = self.note("主人", "ask", "变化无穷，各有所归。", "试图越权写入")
        self.assertEqual(code, 3, out)
        self.assertIn("归属冲突", out)

    def test_note_uid(self) -> None:
        self.open_book()
        self.note("主人", "ask", "变化无穷，各有所归。", "我的问题")
        notes = self.annotations("主人")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["uid"], "owner")
        self.assertEqual(notes[0]["speaker"], "主人")


if __name__ == "__main__":
    unittest.main()
