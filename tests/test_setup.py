"""CHG-002：部署链路（setup / --check / 漂移检测 / G10 部署闸）。

这些测试就是「可控」的定义：每条断言对应 SPEC §10 的一条 AC。
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from marginalia import setup as setup_mod
from marginalia.cli import main


class SetupTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "study"
        self.skills = self.tmp / "skills"
        self.skills.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # ---------- 工具 ----------

    def cli(self, *args: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(buf):
            code = main(["--root", str(self.root), *args])
        return code, buf.getvalue()

    def deploy(self, *extra: str) -> tuple[int, str]:
        return self.cli(
            "setup",
            "--skills-dir",
            str(self.skills),
            "--owner-open-id",
            "ou_owner",
            "--owner-name",
            "主人",
            *extra,
        )

    def depot(self) -> Path:
        return self.skills / "marginalia"

    def record(self) -> dict:
        return json.loads((self.root / "deployment.json").read_text(encoding="utf-8"))

    # ---------- AC1 预检先于写入 ----------

    def test_need_skills_dir(self) -> None:
        """AC6：不给 --skills-dir → exit 1，且不建数据根（预检先于写入）。"""
        code, out = self.cli("setup", "--owner-open-id", "ou_a", "--owner-name", "主人")
        self.assertEqual(code, 1, out)
        self.assertIn("--skills-dir", out)
        self.assertFalse(self.root.exists(), "预检失败时不得创建任何目录")

    def test_owner_pair(self) -> None:
        code, out = self.cli("setup", "--skills-dir", str(self.skills), "--owner-name", "主人")
        self.assertEqual(code, 1, out)
        self.assertFalse(self.root.exists())

    def test_dry_run(self) -> None:
        """AC1：dry-run 零写入。"""
        code, out = self.deploy("--dry-run")
        self.assertEqual(code, 1, out)
        self.assertIn("dry-run", out)
        self.assertFalse(self.root.exists())
        self.assertEqual(list(self.skills.iterdir()), [], "dry-run 不得写 skill 目录")

    # ---------- AC2 正常部署 ----------

    def test_ready(self) -> None:
        code, out = self.deploy()
        self.assertEqual(code, 0, out)
        self.assertIn("ready", out)
        self.assertTrue((self.root / "registry.json").is_file())
        self.assertTrue((self.root / "deployment.json").is_file())

    def test_files_copied(self) -> None:
        self.deploy()
        self.assertTrue((self.depot() / "SKILL.md").is_file())
        self.assertTrue((self.depot() / "skill.manifest.json").is_file())
        refs = self.depot() / "references"
        self.assertTrue(refs.is_dir())
        self.assertTrue(list(refs.glob("*.md")), "references 必须一起装")

    # ---------- AC3 幂等 ----------

    def test_idempotent(self) -> None:
        self.assertEqual(self.deploy()[0], 0)
        code, out = self.deploy()
        self.assertEqual(code, 0, out)
        reg = json.loads((self.root / "registry.json").read_text(encoding="utf-8"))
        owners = [u for u in reg["users"] if u.get("role") == "owner"]
        self.assertEqual(len(owners), 1, "owner 不得重复创建")

    def test_second_owner(self) -> None:
        self.deploy()
        code, out = self.cli(
            "setup",
            "--skills-dir",
            str(self.skills),
            "--owner-open-id",
            "ou_other",
            "--owner-name",
            "别人",
        )
        self.assertEqual(code, 0, out)
        self.assertIn("另一个 owner", out)
        reg = json.loads((self.root / "registry.json").read_text(encoding="utf-8"))
        self.assertEqual(len([u for u in reg["users"] if u.get("role") == "owner"]), 1)

    # ---------- AC4 --check ----------

    def test_check_before(self) -> None:
        code, out = self.cli("setup", "--check")
        self.assertEqual(code, 1, out)
        self.assertIn("absent", out)

    def test_check_after(self) -> None:
        self.deploy()
        code, out = self.cli("setup", "--check")
        self.assertEqual(code, 0, out)

    # ---------- AC8 漂移检测 ----------

    def test_copy_drift(self) -> None:
        """副本被手改 → stale + exit 3。"""
        self.deploy()
        target = self.depot() / "SKILL.md"
        target.write_text(target.read_text(encoding="utf-8") + "\n手改\n", encoding="utf-8")
        code, out = self.cli("setup", "--check")
        self.assertEqual(code, 3, out)
        self.assertIn("stale", out)
        self.assertIn("skill_integrity", out)

    def test_repo_drift(self) -> None:
        """仓库 SKILL.md 更新而副本未刷 → stale + exit 3。"""
        self.deploy()
        fake = self.tmp / "fake_repo"
        fake.mkdir()
        (fake / "SKILL.md").write_text("# 更新过的提示词\n", encoding="utf-8")
        with mock.patch.object(setup_mod, "project_root", lambda: fake):
            code, out = self.cli("setup", "--check")
        self.assertEqual(code, 3, out)
        self.assertIn("stale", out)
        self.assertIn("skill_up_to_date", out)

    # ---------- AC5 G10 部署闸 ----------

    def test_foreign(self) -> None:
        target = self.depot()
        target.mkdir(parents=True)
        (target / "skill.manifest.json").write_text(
            json.dumps({"id": "someone-else"}), encoding="utf-8"
        )
        (target / "SKILL.md").write_text("# 别人的技能\n", encoding="utf-8")
        code, out = self.deploy()
        self.assertEqual(code, 3, out)
        self.assertIn("其它技能", out)
        self.assertIn("别人的技能", (target / "SKILL.md").read_text(encoding="utf-8"))

    def test_foreign_force(self) -> None:
        target = self.depot()
        target.mkdir(parents=True)
        (target / "skill.manifest.json").write_text(
            json.dumps({"id": "someone-else"}), encoding="utf-8"
        )
        code, _ = self.deploy("--force")
        self.assertEqual(code, 0)
        manifest = (target / "skill.manifest.json").read_text(encoding="utf-8")
        self.assertIn('"marginalia"', manifest)

    # ---------- AC7 deployment.json ----------

    def test_record(self) -> None:
        self.deploy()
        rec = self.record()
        for key in (
            "schema",
            "project_version",
            "deployed_at",
            "updated_at",
            "python",
            "mode",
            "root",
            "skill",
            "checks",
        ):
            self.assertIn(key, rec)
        self.assertEqual(rec["schema"], 1)
        self.assertEqual(rec["mode"], "strict")
        self.assertTrue(Path(rec["root"]).is_absolute())
        self.assertTrue(rec["skill"]["file"].endswith("SKILL.md"))
        self.assertTrue(all(c["ok"] for c in rec["checks"]), rec["checks"])

    def test_no_skill(self) -> None:
        code, out = self.cli(
            "setup", "--owner-open-id", "ou_owner", "--owner-name", "主人", "--no-skill"
        )
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.record()["skill"])

    def test_deploy_keeps_first_time(self) -> None:
        self.deploy()
        first = self.record()["deployed_at"]
        self.deploy()
        self.assertEqual(self.record()["deployed_at"], first, "重复部署不得覆盖首次部署时间")

    # ---------- AC9 doctor ----------

    def test_root_after_subcommand(self) -> None:
        """AC11：文档里的写法 `marginalia setup --root ...` 必须真能跑。

        argparse 默认只认「子命令之前」的全局选项；README / AGENT_DEPLOY /
        deploy.sh 用的却是子命令之后的写法。两者都要能用。
        """
        code, out = self.cli(
            "setup",
            "--root",
            str(self.root),
            "--skills-dir",
            str(self.skills),
            "--owner-open-id",
            "ou_owner",
            "--owner-name",
            "主人",
        )
        self.assertEqual(code, 0, out)
        self.assertNotIn("unrecognized arguments", out)
        self.assertTrue((self.root / "deployment.json").is_file())

    def test_root_before_subcommand(self) -> None:
        """子命令之前的写法也必须继续可用（向后兼容）。"""
        code, out = self.cli("setup", "--skills-dir", str(self.skills), "--no-skill")
        self.assertEqual(code, 0, out)

    def test_doctor_block(self) -> None:
        self.deploy()
        code, out = self.cli("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("部署状态", out)
        self.assertIn("ready", out)

    def test_doctor_without_deploy(self) -> None:
        self.cli("init", "--owner-open-id", "ou_owner", "--owner-name", "主人")
        code, out = self.cli("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("未记录部署", out)


if __name__ == "__main__":
    unittest.main()
