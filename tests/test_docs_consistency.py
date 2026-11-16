"""CHG-002 AC10/AC11：文档-代码一致性。

文档里的每条命令都必须真实存在——否则 agent 照着文档做会撞墙。
这个测试就是「引导链路可控」的机械保证。
"""

from __future__ import annotations

import argparse
import re
import unittest
from pathlib import Path

from marginalia.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent

# 面向 agent / 人的入口文档
DOCS = ["AGENT_DEPLOY.md", "README.md", "README.en.md", "SKILL.md"]

# 出现在散文里但不是子命令的词（显式白名单，新增需评审）
PROSE_WORDS = {"cli"}

CMD_RE = re.compile(r"marginalia\s+([a-z][a-z0-9-]*)")
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def body_of(path: Path) -> str:
    """取文档正文，**剔掉 YAML frontmatter**。

    frontmatter 里 `name: marginalia` 下面紧跟 `description:`，若整文件扫描，
    会被当成 `marginalia description` 这条不存在的命令。扫描应该只看正文。
    """
    text = path.read_text(encoding="utf-8")
    return FRONTMATTER_RE.sub("", text, count=1)


def top_commands() -> set[str]:
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    return set()


class DeployDocsTest(unittest.TestCase):
    def test_files_exist(self) -> None:
        """AC9/AC11：部署链路的四个入口都必须存在。"""
        for name in (
            "AGENT_DEPLOY.md",
            "references/deployment.md",
            "scripts/deploy.sh",
            "scripts/deploy.cmd",
        ):
            self.assertTrue((ROOT / name).is_file(), f"缺少 {name}")

    def test_commands_real(self) -> None:
        """AC10：文档里的 `marginalia <子命令>` 必须都在 parser 里注册过。"""
        known = top_commands()
        self.assertIn("setup", known, "setup 子命令必须存在")

        unknown: dict[str, set[str]] = {}
        for name in DOCS:
            text = body_of(ROOT / name)
            for token in CMD_RE.findall(text):
                if token in known or token in PROSE_WORDS:
                    continue
                unknown.setdefault(name, set()).add(token)
        self.assertEqual(unknown, {}, f"文档里出现未注册的子命令：{unknown}")

    def test_skill_points_to_protocol(self) -> None:
        """AC10：SKILL.md 必须有部署门，且指向协议文件。"""
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("AGENT_DEPLOY.md", text)
        self.assertIn("marginalia setup --check", text)
        self.assertIn("模式 B", text)

    def test_protocol_has_branches(self) -> None:
        """AC9：协议每一步都要有失败分支，否则 agent 会卡住。"""
        text = (ROOT / "AGENT_DEPLOY.md").read_text(encoding="utf-8")
        self.assertIn("失败分支", text)
        self.assertIn("期望", text)
        self.assertIn("模式 B", text)
        # 四个关键状态的退出码必须写明
        for code in ("`0`", "`1`", "`3`"):
            self.assertIn(code, text)

    def test_readmes_have_deploy(self) -> None:
        """AC9：中英文 README 开头都要能直接照着部署。"""
        for name in ("README.md", "README.en.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("marginalia setup", text, name)
            self.assertIn("--skills-dir", text, name)
            self.assertIn("setup --check", text, name)

    def test_scripts_call_setup(self) -> None:
        """AC11：包装脚本必须真的转调 setup。"""
        for name in ("scripts/deploy.sh", "scripts/deploy.cmd"):
            text = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("setup", text, name)
            self.assertIn("PYTHONUTF8", text, name)

    def test_version_single_source(self) -> None:
        """版本只能有一个真源：包内 `__version__`，且必须与 pyproject 一致。

        此前 `__init__.py` / `pyproject.toml` / `cli.py` 各自硬编码了一次，
        升版必然漂移。现在 cli 已改为读 `__version__`，此处锁住另一处。
        """
        import re as _re

        import marginalia

        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        found = _re.search(r'^version\s*=\s*"([^"]+)"', pyproject, _re.MULTILINE)
        self.assertIsNotNone(found, "pyproject.toml 缺少 version")
        assert found is not None
        self.assertEqual(
            marginalia.__version__,
            found.group(1),
            "marginalia.__version__ 与 pyproject.toml 版本不一致",
        )

    def test_manifest_has_deployment(self) -> None:
        """manifest 必须声明部署入口，否则框架侧无从得知。"""
        import json

        data = json.loads((ROOT / "skill.manifest.json").read_text(encoding="utf-8"))
        deploy = data.get("deployment")
        self.assertIsNotNone(deploy, "manifest 缺少 deployment 段")
        self.assertEqual(deploy["protocol"], "AGENT_DEPLOY.md")
        self.assertEqual(deploy["self_check"], "marginalia setup --check")
        self.assertTrue(deploy["requires_explicit_skills_dir"])
        self.assertIn("G10 deployment (不覆盖其它技能的目录)", data["quality_gates"])


if __name__ == "__main__":
    unittest.main()
