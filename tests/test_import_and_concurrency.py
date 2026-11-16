"""AC10 存量迁移 / AC11 并发写入。"""

from __future__ import annotations

import json
import threading
import unittest

from tests.base import LEGACY, BaseTest


class ImportTest(BaseTest):
    def legacy(self):
        path = self.tmp / "legacy.md"
        path.write_text(LEGACY, encoding="utf-8")
        return path

    def test_dry_run(self) -> None:
        """AC10：默认试运行，绝不写盘。"""
        path = self.legacy()
        before = self.tree_snapshot()
        code, out = self.cli("import", "--as", "主人", "--from", str(path))
        self.assertEqual(code, 0, out)
        self.assertIn("试运行", out)
        self.assertEqual(before, self.tree_snapshot(), "试运行不得产生任何文件")
        self.assertNotIn("已导入", out)

    def test_apply(self) -> None:
        path = self.legacy()
        code, out = self.cli("import", "--as", "主人", "--from", str(path), "--apply")
        self.assertEqual(code, 0, out)
        self.assertIn("已导入", out)

        book = self.book_dir("主人")
        notes = [
            json.loads(line)
            for line in (book / "annotations.jsonl").read_text(encoding="utf-8").split("\n")
            if line.strip()
        ]
        self.assertEqual(len(notes), 4, [n["kind"] for n in notes])
        self.assertEqual(sorted(n["kind"] for n in notes), ["ask", "dialog", "explain", "progress"])

        meta = json.loads((book / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["title"], "鬼谷子")
        self.assertEqual(meta["edition"], "四部丛刊本")
        self.assertEqual(len(meta["chapters"]), 2)
        self.assertEqual(meta["status"], "进行中")

        # 原文头（代码生成的课程卡）必须被剥离，原文正文保留
        source = (book / "source.md").read_text(encoding="utf-8")
        self.assertTrue(source.lstrip().startswith("# 鬼谷子"), source[:60])
        self.assertNotIn("共读批注本", source)
        self.assertNotIn("🦞", source)

        rendered = (book / "book.md").read_text(encoding="utf-8")
        self.assertIn("🦞 **【第1课·2026-11-16】**", rendered)
        self.assertIn("👤 **主人**：为什么要先稽古？", rendered)
        self.assertIn("💬 **讨论**：稽古是取得合法性的动作", rendered)
        self.assertIn("✅ **进度**：本段完于 2026-11-16", rendered)

        code, out = self.cli("verify", "--check-render", "--strict")
        self.assertEqual(code, 0, out)

    def test_speaker_guard(self) -> None:
        """原文件里混着别人的批注 → 默认拒绝导入。"""
        path = self.tmp / "mixed.md"
        path.write_text(
            LEGACY.replace("👤 **主人**：为什么要先稽古？", "👤 **小林**：我要问"), encoding="utf-8"
        )
        code, out = self.cli("import", "--as", "主人", "--from", str(path), "--apply")
        self.assertEqual(code, 1, out)
        self.assertIn("说话人", out)

    def test_force_speaker(self) -> None:
        path = self.tmp / "mixed.md"
        path.write_text(
            LEGACY.replace("👤 **主人**：为什么要先稽古？", "👤 **小林**：我要问"), encoding="utf-8"
        )
        code, out = self.cli(
            "import", "--as", "主人", "--from", str(path), "--apply", "--force-speaker"
        )
        self.assertEqual(code, 0, out)
        book = self.book_dir("主人")
        notes = [
            json.loads(line)
            for line in (book / "annotations.jsonl").read_text(encoding="utf-8").split("\n")
            if line.strip()
        ]
        self.assertTrue(all(n["uid"] == "owner" for n in notes))

    def test_no_duplicate(self) -> None:
        path = self.legacy()
        self.cli("import", "--as", "主人", "--from", str(path), "--apply")
        code, out = self.cli("import", "--as", "主人", "--from", str(path), "--apply")
        self.assertEqual(code, 1, out)
        self.assertIn("已存在", out)


class ConcurrencyTest(BaseTest):
    def test_parallel_notes(self) -> None:
        """AC11：20 线程直调库函数（不靠调用方加锁）→ 全部落盘、id 唯一、审计链完整。"""
        self.open_book()
        from marginalia import notes as notes_mod
        from marginalia import registry
        from marginalia.store import Store

        store = Store(self.root)
        user = registry.resolve(store, "主人")
        total = 20
        errors: list[str] = []
        guard = threading.Lock()

        def worker(i: int) -> None:
            try:
                notes_mod.add_note(
                    store, user, "鬼谷子", "ask", f"并发批注 {i}", "变化无穷，各有所归。"
                )
            except Exception as exc:  # noqa: BLE001 - 测试需要看到任何异常
                with guard:
                    errors.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(total)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], "库自带锁失败，调用方无需加锁")
        rows = self.annotations("主人")
        self.assertEqual(len(rows), total)
        self.assertEqual(len({r["id"] for r in rows}), total, "id 必须唯一")

        self.cli("render", "--as", "主人", "--book", "鬼谷子")
        code, out = self.cli("verify", "--check-render", "--strict")
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
