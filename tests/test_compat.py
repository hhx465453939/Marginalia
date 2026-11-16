"""Python 3.9 兼容性守卫（静态断言）。

为什么需要：本地开发在 3.13，CI 矩阵含 3.9。
用了 3.10+ 的 API 时，本地全绿、CI 才炸——反馈环太长。

已踩过的坑：`Path.write_text(newline="\\n")` 的 `newline` 参数是 3.10 才加的，
在 3.9 上直接 `TypeError: write_text() got an unexpected keyword argument 'newline'`。

这里用 AST 扫源码，把这类「本地测不出来」的不兼容变成可提前发现的失败。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 函数名 → 该函数上「3.10+ 才支持」的关键字参数
FORBIDDEN_KWARGS: dict[str, set[str]] = {
    "write_text": {"newline"},
    "write_bytes": {"newline"},
    "zip": {"strict"},
    "dataclass": {"slots"},
}


def sources() -> list[Path]:
    files = sorted((ROOT / "marginalia").glob("*.py"))
    files += sorted((ROOT / "tests").glob("*.py"))
    return files


class CompatTest(unittest.TestCase):
    def test_no_newer_api(self) -> None:
        offenders: list[str] = []
        for path in sources():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name: str | None = None
                if isinstance(func, ast.Attribute):
                    name = func.attr
                elif isinstance(func, ast.Name):
                    name = func.id
                if name is None or name not in FORBIDDEN_KWARGS:
                    continue
                used = {kw.arg for kw in node.keywords if kw.arg}
                bad = used & FORBIDDEN_KWARGS[name]
                if bad:
                    rel = path.relative_to(ROOT)
                    offenders.append(f"{rel}:{node.lineno} {name}({','.join(sorted(bad))}=...)")

        self.assertEqual(
            offenders,
            [],
            "检测到 Python 3.10+ 才支持的 API，3.9 上会 TypeError：" + " ｜ ".join(offenders),
        )

    def test_requires_python_covers_39(self) -> None:
        """pyproject 的 requires-python 必须仍然包含 3.9（否则 CI 矩阵与声明不一致）。"""
        text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('requires-python = ">=3.9"', text)

    def test_ci_matrix_keeps_39(self) -> None:
        """CI 必须继续覆盖 3.9，否则上面的静态守卫失去意义。"""
        text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('"3.9"', text)


if __name__ == "__main__":
    unittest.main()
