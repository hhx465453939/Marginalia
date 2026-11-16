"""Marginalia · portable 模式的**事后**审计器。

为什么需要它：很多 Agent 运行时没有 shell，跑不了 `marginalia` CLI。
那时隔离只能靠 SKILL 里的协议约束 —— 模型**可以违反**。

我们无法事前拦截，但可以事后取证：
    给定一份纯 Markdown 批注本，它到底有没有串档？

规则（L 系列，对应 SPEC AC15）：
    L1 课程卡缺「学员：<称呼>（uid: ...）」        ERROR
    L2 `👤 **X**` 的 X 与课程卡称呼不一致（串档）   ERROR
    L3 `<!-- marginalia:uid=... -->` 与课程卡不一致 ERROR
    L4 `👤` 标签里出现注册表中**其他**学员的称呼     ERROR
    L5 标题里的称呼与课程卡不一致                    WARN
    L6 同一文件出现两张不同归属的课程卡              ERROR
    L7 卡片 uid 无法在注册表解析                     WARN
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .store import Store
from .util import EXIT_INTEGRITY, MarginaliaError, read_text

ERROR = "ERROR"
WARN = "WARN"

_CARD_RE = re.compile(
    r"^-\s*学员[：:]\s*(?P<name>[^（(]+?)\s*[（(]\s*uid\s*[：:]\s*(?P<uid>[^）)]+?)\s*[）)]"
)
_TITLE_RE = re.compile(
    r"^#\s*《(?P<book>.+?)》\s*[·・]\s*共读批注本\s*[（(]?(?P<name>[^）)]*)[）)]?"
)
_UID_MARK_RE = re.compile(r"<!--\s*marginalia:uid\s*=\s*(?P<uid>[^\s]+)\s*-->")
_SPEAKER_RE = re.compile(r"^\s*>\s*👤\s*\*\*(?P<name>[^*]+?)\*\*")


@dataclass
class Issue:
    level: str
    line: int
    code: str
    message: str

    def render(self, path: str) -> str:
        return f"{path}:{self.line}: [{self.level}][{self.code}] {self.message}"


@dataclass
class LintReport:
    path: str
    issues: list[Issue] = field(default_factory=list)
    student: str = ""
    uid: str = ""

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == ERROR]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == WARN]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "ok": self.ok,
            "student": self.student,
            "uid": self.uid,
            "errors": [i.render(self.path) for i in self.errors],
            "warnings": [i.render(self.path) for i in self.warnings],
        }


def lint_text(
    text: str,
    path: str = "<memory>",
    known_users: dict[str, str] | None = None,
    expected_uid: str | None = None,
) -> LintReport:
    """known_users: 称呼 → uid（注册表投影，用于 L4 反查）。"""
    report = LintReport(path=path)
    known_users = known_users or {}

    card_name = ""
    card_uid = ""
    card_line = 0
    title_name = ""
    marker_uid = ""
    marker_line = 0
    issue_queue: list[tuple[int, str, str, str]] = []

    for lineno, line in enumerate(text.split("\n"), 1):
        title = _TITLE_RE.match(line)
        if title:
            title_name = (title.group("name") or "").strip()

        card = _CARD_RE.match(line.strip())
        if card:
            name = card.group("name").strip()
            uid = card.group("uid").strip()
            if card_name and (name != card_name or uid != card_uid):
                issue_queue.append(
                    (
                        lineno,
                        ERROR,
                        "L6",
                        f"出现第二张归属不同的课程卡：{name}（{uid}）≠ {card_name}（{card_uid}）",
                    )
                )
            else:
                card_name, card_uid, card_line = name, uid, lineno

        marker = _UID_MARK_RE.search(line)
        if marker and not marker_uid:
            marker_uid = marker.group("uid").strip()
            marker_line = lineno

        speaker_match = _SPEAKER_RE.match(line)
        if speaker_match:
            speaker = speaker_match.group("name").strip()
            if card_name and speaker != card_name:
                hint = ""
                if speaker in known_users and known_users[speaker] != card_uid:
                    hint = f"（「{speaker}」是另一位学员 {known_users[speaker]} 的称呼）"
                issue_queue.append(
                    (
                        lineno,
                        ERROR,
                        "L2",
                        f"批注说话人「{speaker}」≠ 本书房学员「{card_name}」{hint}",
                    )
                )

    # ---- L1 课程卡
    if not card_name:
        issue_queue.append(
            (1, ERROR, "L1", "课程卡缺少「学员：<称呼>（uid: ...）」——无归属声明，无法判定隔离")
        )

    # ---- L3 uid 标记
    if marker_uid and card_uid and marker_uid != card_uid:
        issue_queue.append(
            (marker_line, ERROR, "L3", f"uid 标记「{marker_uid}」≠ 课程卡 uid「{card_uid}」")
        )

    # ---- L7 注册表可解析性
    if card_uid and known_users and card_uid not in set(known_users.values()):
        issue_queue.append(
            (
                card_line,
                WARN,
                "L7",
                f"课程卡 uid「{card_uid}」不在注册表中（可能是外部文件或拼写错误）",
            )
        )

    # ---- L5 标题称呼
    if title_name and card_name and title_name != card_name:
        issue_queue.append((1, WARN, "L5", f"标题称呼「{title_name}」≠ 课程卡称呼「{card_name}」"))

    # ---- 外部期望
    if expected_uid and card_uid and card_uid != expected_uid:
        issue_queue.append(
            (card_line, ERROR, "L8", f"课程卡 uid「{card_uid}」≠ 期望「{expected_uid}」")
        )

    report.student = card_name
    report.uid = card_uid
    report.issues = [
        Issue(level, line, code, msg) for line, level, code, msg in sorted(issue_queue)
    ]
    return report


def registry_projection(store: Store) -> dict[str, str]:
    """称呼 → uid 投影；数据根未初始化时返回空。"""
    from . import registry

    if not store.is_initialized():
        return {}
    try:
        users = registry.load(store)["users"]
    except MarginaliaError:
        return {}
    out: dict[str, str] = {}
    for user in users:
        if user.get("name"):
            out[str(user["name"])] = str(user["uid"])
        for alias in user.get("aliases", []):
            out[str(alias)] = str(user["uid"])
    return out


def lint_file(
    store: Store,
    path: Path,
    expected_uid: str | None = None,
    known_users: dict[str, str] | None = None,
) -> LintReport:
    if not path.is_file():
        raise MarginaliaError(f"待审计文件不存在: {path}")
    text = read_text(path)
    projection = known_users if known_users is not None else registry_projection(store)
    return lint_text(text, path=str(path), known_users=projection, expected_uid=expected_uid)


def discover_targets(store: Store) -> list[Path]:
    """默认审计目标：只认**批注本**（books/<slug>/book.md）。

    source.md 是原文、INDEX.md 是索引，它们本来就没有课程卡——
    把它们也拉进来审，等于用错尺子量错东西。
    """
    if not store.users_dir.is_dir():
        return []
    return sorted(store.users_dir.glob("*/books/*/book.md"))


def summarize(reports: list[LintReport]) -> str:
    errors = sum(len(r.errors) for r in reports)
    warnings = sum(len(r.warnings) for r in reports)
    lines: list[str] = []
    for report in reports:
        for issue in report.errors:
            lines.append(issue.render(report.path))
        for issue in report.warnings:
            lines.append(issue.render(report.path))
    if not lines:
        return f"✓ {len(reports)} 份批注本通过审计（0 错误 0 警告）"
    head = f"{'✗' if errors else '✓'} 审计 {len(reports)} 份批注本：{errors} 错误 / {warnings} 警告"
    return head + "\n" + "\n".join(lines)


def has_errors(reports: list[LintReport]) -> bool:
    return any(r.errors for r in reports)


INTEGRITY_EXIT = EXIT_INTEGRITY
