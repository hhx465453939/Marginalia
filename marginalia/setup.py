"""Marginalia · 部署层：把「skill 提示」与「script 强制」装成一条可控链路。

为什么单独一层：CHG-001 保证「装好之后不会串档」，但从「什么都没装」到「能开口上课」
之间是断的——命令没装时 SKILL.md §0 无法自举，装了也没有任何状态记录，
仓库升级了副本还是旧的却无人发现。

本模块提供一条有状态、可验证、可重入的部署链：

    absent → partial → (stale | broken) → ready

状态与退出码：

    absent / partial   exit 1   需要部署（或缺部署记录）
    stale / broken     exit 3   已安装但不可信：副本过期或数据不完整
    ready              exit 0   可以开始上课

设计要点（与 SPEC §3 对齐）：
  * 部署状态落在**数据根**（`<root>/deployment.json`），项目目录可能只读；
  * 用 **sha256** 判断副本漂移，而不是版本号或 mtime；
  * 找不到 skills 目录就**失败并给候选**，绝不擅自写用户家目录；
  * 目标是别人的技能目录时**拒绝覆盖**（G10 部署闸），除非显式 --force。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__, registry, render, verify
from .store import Store
from .util import (
    EXIT_ERROR,
    EXIT_INTEGRITY,
    MarginaliaError,
    now_bj,
    read_text,
    sha256_text,
)

SCHEMA_VERSION = 1
DEPLOY_FILENAME = "deployment.json"

SKILL_ID = "marginalia"
SKILL_DIRNAME = "marginalia"
SKILL_FILE = "SKILL.md"
MANIFEST_FILE = "skill.manifest.json"
SKILL_REF_DIR = "references"

MIN_PYTHON = (3, 9)

# 哨兵：区分「没传期望值」与「期望值就是 None（--no-skill）」。
# 直接用 None 做两者会让 --no-skill 被误判为 partial。
_UNSET: Any = object()

STATE_ABSENT = "absent"
STATE_PARTIAL = "partial"
STATE_STALE = "stale"
STATE_BROKEN = "broken"
STATE_READY = "ready"

EXIT_BY_STATE = {
    STATE_READY: 0,
    STATE_ABSENT: EXIT_ERROR,
    STATE_PARTIAL: EXIT_ERROR,
    STATE_STALE: EXIT_INTEGRITY,
    STATE_BROKEN: EXIT_INTEGRITY,
}


@dataclass
class Check:
    """一项可判定的部署检查。"""

    name: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


@dataclass
class SetupResult:
    """setup 的完整结果，可直接落成 deployment.json。"""

    state: str = STATE_PARTIAL
    dry_run: bool = False
    root: str = ""
    python: str = ""
    mode: str = "strict"
    checks: list[Check] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    skill: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.state == STATE_READY

    @property
    def exit_code(self) -> int:
        return EXIT_BY_STATE.get(self.state, EXIT_ERROR)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "dry_run": self.dry_run,
            "root": self.root,
            "python": self.python,
            "mode": self.mode,
            "checks": [c.to_dict() for c in self.checks],
            "created": self.created,
            "skipped": self.skipped,
            "skill": self.skill,
            "notes": self.notes,
        }


# ---------------------------------------------------------------- 环境探测


def project_root() -> Path:
    """仓库根（本包的上一级）。用于取 SKILL.md 与 references 的权威副本。"""
    return Path(__file__).resolve().parent.parent


def python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def python_ok() -> tuple[bool, str]:
    current = (sys.version_info.major, sys.version_info.minor)
    return current >= MIN_PYTHON, python_version()


def candidate_skills_dirs() -> list[Path]:
    """常见的技能根目录（只作为**候选**，不会被擅自写入）。"""
    home = Path.home()
    return [
        home / ".agents" / "skills",
        home / ".claude" / "skills",
        Path.cwd() / ".agents" / "skills",
        Path.cwd() / ".claude" / "skills",
    ]


def existing_skills_dirs() -> list[Path]:
    return [p for p in candidate_skills_dirs() if p.is_dir()]


def resolve_skills_root(explicit: str | Path | None) -> Path:
    """确定 skill 安装根目录——**必须显式指定**。

    为什么不自动用探测到的目录：写进 `~/.claude/skills` 是**修改用户环境**。
    开发期实测过这个坑：本机恰好存在该目录，于是不带参数的一次 setup
    就往真实技能池里装了副本。所以改为：探测结果只作为**建议**出现在报错里，
    要不要写、写到哪里，由人（或 agent 明确传参）决定。
    """
    if explicit:
        return Path(explicit).expanduser().resolve()
    existing = existing_skills_dirs()
    if existing:
        hint = "；本机已存在：" + "、".join(str(p) for p in existing)
    else:
        hint = "；本机未发现常见技能目录：" + "、".join(str(p) for p in candidate_skills_dirs())
    raise MarginaliaError(
        "安装 skill 副本必须显式指定 --skills-dir",
        EXIT_ERROR,
        hint=f"加 --skills-dir <技能根目录>（会装到 <dir>/marginalia/）{hint}；或加 --no-skill 只建数据根",
    )


# ---------------------------------------------------------------- 部署记录


def deployment_path(store: Store) -> Path:
    return store.root / DEPLOY_FILENAME


def read_deployment(store: Store) -> dict[str, Any] | None:
    path = deployment_path(store)
    if not path.is_file():
        return None
    try:
        return store.read_json(path)
    except MarginaliaError:
        return None


def _skill_sources() -> list[tuple[Path, Path]]:
    """(仓库内源文件, 相对于技能目录的目标路径)。"""
    root = project_root()
    pairs: list[tuple[Path, Path]] = [
        (root / SKILL_FILE, Path(SKILL_FILE)),
        (root / MANIFEST_FILE, Path(MANIFEST_FILE)),
    ]
    ref_dir = root / SKILL_REF_DIR
    if ref_dir.is_dir():
        for src in sorted(ref_dir.glob("*.md")):
            pairs.append((src, Path(SKILL_REF_DIR) / src.name))
    return pairs


def _read_manifest_id(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(read_text(path))
    except (OSError, ValueError):
        return None
    value = data.get("id")
    return value if isinstance(value, str) else None


# ---------------------------------------------------------------- 安装


def install_skill(
    skills_root: Path,
    result: SetupResult,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """把 SKILL.md / manifest / references 复制到 <skills_root>/marginalia/。"""
    target = skills_root / SKILL_DIRNAME
    target_manifest = target / MANIFEST_FILE

    # ---- G10 部署闸：不覆盖别人的技能目录
    if target.is_dir():
        other_id = _read_manifest_id(target_manifest)
        if other_id and other_id != SKILL_ID and not force:
            raise MarginaliaError(
                f"目标目录已有其它技能（id={other_id!r}）: {target}",
                EXIT_INTEGRITY,
                hint="确认要覆盖请加 --force；否则换一个 --skills-dir",
            )
        if other_id is None and (target / SKILL_FILE).is_file() and not force:
            raise MarginaliaError(
                f"目标目录已有同名 SKILL.md 但无 manifest，无法判定归属: {target}",
                EXIT_INTEGRITY,
                hint="确认要覆盖请加 --force",
            )

    pairs = _skill_sources()
    if not (project_root() / SKILL_FILE).is_file():
        raise MarginaliaError(
            f"仓库缺少 {SKILL_FILE}，无法安装技能副本: {project_root()}",
            EXIT_ERROR,
            hint="请确认在完整仓库内运行（不是只装了 wheel 的环境）",
        )

    installed_sha = sha256_text(read_text(project_root() / SKILL_FILE))

    for src, rel in pairs:
        dest = target / rel
        if dry_run:
            result.created.append(str(dest))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 内容相同就不重写，避免无意义地改动 mtime
        try:
            same = dest.is_file() and read_text(dest) == read_text(src)
        except OSError:
            same = False
        if same:
            result.skipped.append(str(dest))
            continue
        dest.write_text(read_text(src), encoding="utf-8", newline="\n")
        result.created.append(str(dest))

    if not dry_run:
        result.checks.append(Check("skill_installed", True, str(target)))

    return {
        "dir": str(target),
        "file": str(target / SKILL_FILE),
        "installed_sha256": installed_sha,
        "source_sha256": installed_sha,
        "installed_at": now_bj(),
    }


# ---------------------------------------------------------------- 主流程


def run_setup(
    store: Store,
    *,
    skills_dir: str | Path | None = None,
    owner_open_id: str | None = None,
    owner_name: str | None = None,
    dry_run: bool = False,
    with_skill: bool = True,
    force: bool = False,
) -> SetupResult:
    """一次命令完成：探测 → 建根 → 建 owner → 装 skill → 记账 → 自证。"""
    result = SetupResult(dry_run=dry_run, root=str(store.root), python=python_version())

    # ---- 1. 环境探测（预检全部前置条件，校验先于任何写入）
    ok, version = python_ok()
    result.checks.append(
        Check("python_version", ok, f"{version}（需要 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}）")
    )
    if not ok:
        result.state = STATE_ABSENT
        raise MarginaliaError(
            f"Python 版本过低：{version}（需要 >= {MIN_PYTHON[0]}.{MIN_PYTHON[1]}）",
            EXIT_ERROR,
            hint="升级 Python 后重新运行 marginalia setup",
        )

    # 先解析 skill 目录：这是最容易失败的前置条件，
    # 放在这里可以保证失败时磁盘**零改动**（而不是建了数据根再报错）。
    skills_root: Path | None = None
    if with_skill:
        skills_root = resolve_skills_root(skills_dir)
    if (owner_open_id or owner_name) and not (owner_open_id and owner_name):
        raise MarginaliaError(
            "--owner-open-id 与 --owner-name 必须同时提供",
            EXIT_ERROR,
            hint="两者成对出现，否则建不出可用的 owner",
        )

    # ---- 2. 数据根
    if store.is_initialized():
        result.checks.append(Check("root_initialized", True, str(store.root)))
        result.skipped.append(f"数据根已存在：{store.root}")
    elif dry_run:
        result.checks.append(Check("root_initialized", False, "将创建（dry-run 未落盘）"))
        result.created.append(str(store.registry_path))
    else:
        store.ensure()
        registry.save(store, registry.empty_registry())
        render.render_global_index(store, write=True)
        result.checks.append(Check("root_initialized", True, f"已创建 {store.root}"))
        result.created.append(str(store.registry_path))

    # ---- 3. owner 账户
    if owner_open_id and owner_name:
        if dry_run:
            result.checks.append(Check("owner", False, "将创建（dry-run 未落盘）"))
        else:
            reg = registry.load(store)
            existing = registry.find(reg, owner_open_id)
            if existing is not None:
                result.checks.append(
                    Check("owner", True, f"已存在：{existing.get('name')}（{existing.get('uid')}）")
                )
                result.skipped.append("owner 已存在，未重复创建")
            elif any(u.get("role") == "owner" for u in reg["users"]):
                result.checks.append(Check("owner", False, "已有另一个 owner，未再创建"))
                result.notes.append(
                    "系统只允许一个 owner；如需换人请手动处理 registry.json 后再 setup"
                )
            else:
                user = registry.add_user(
                    store,
                    open_id=owner_open_id,
                    name=owner_name,
                    role="owner",
                    goal="系统所有者",
                )
                render.render_user_index(store, user, write=True)
                render.render_global_index(store, write=True)
                result.checks.append(
                    Check("owner", True, f"已创建 {user['name']}（uid: {user['uid']}）")
                )
                result.created.append(str(store.user_dir(user["uid"])))
    else:
        result.checks.append(Check("owner", True, "未指定（可稍后 user add）"))

    # ---- 4. skill 副本
    if with_skill and skills_root is not None:
        result.skill = install_skill(skills_root, result, dry_run=dry_run, force=force)
        if dry_run:
            result.checks.append(Check("skill_installed", False, f"将安装到 {result.skill['dir']}"))
        else:
            target = Path(result.skill["dir"]) / SKILL_FILE
            result.checks.append(
                Check("skill_installed", target.is_file(), str(result.skill["dir"]))
            )
    else:
        result.checks.append(Check("skill_installed", True, "已跳过（--no-skill）"))
        result.skipped.append("未安装 skill 副本（--no-skill）")

    # ---- 5. 记账 + 自证
    if not dry_run:
        state, checks, _ = check_setup(store, expected_skill=result.skill)
        result.state = state
        result.checks = _dedupe(result.checks + checks)
        _write_deployment(store, result)
    else:
        result.state = STATE_PARTIAL
        result.checks = _dedupe(result.checks)
        result.notes.append("dry-run：未写入 deployment.json")

    return result


def _dedupe(checks: list[Check]) -> list[Check]:
    """同名检查只保留最后一次结果，位置不变。

    run_setup 与 check_setup 都会产出 `root_initialized` 等项，
    直接拼接会让输出出现重复行，看起来像 bug。
    """
    index: dict[str, int] = {}
    out: list[Check] = []
    for check in checks:
        if check.name in index:
            out[index[check.name]] = check
        else:
            index[check.name] = len(out)
            out.append(check)
    return out


def _write_deployment(store: Store, result: SetupResult) -> None:
    """落 deployment.json；已存在则保留首次部署时间。"""
    previous = read_deployment(store) or {}
    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "project_version": __version__,
        "deployed_at": previous.get("deployed_at") or now_bj(),
        "updated_at": now_bj(),
        "python": result.python,
        "mode": result.mode,
        "root": str(store.root),
        "skill": result.skill,
        "checks": [c.to_dict() for c in result.checks],
    }
    if previous.get("skill") and result.skill:
        # 保留首次安装时间，只刷新哈希与时间戳
        payload["skill"]["installed_at"] = previous["skill"].get("installed_at") or now_bj()
    store.write_json(deployment_path(store), payload)


# ---------------------------------------------------------------- 校验


def check_setup(
    store: Store, *, expected_skill: Any = _UNSET
) -> tuple[str, list[Check], dict[str, Any] | None]:
    """只读校验：返回 (状态, 检查项, 部署记录)。

    `expected_skill` 供 run_setup 在写入前预判；`--check` 不传（用哨兵），
    一律以磁盘上的 deployment.json 为准。
    传 None 是合法值，表示「本次部署就是不装 skill」。
    """
    checks: list[Check] = []
    provided = expected_skill is not _UNSET

    if not store.is_initialized():
        return STATE_ABSENT, [Check("root_initialized", False, str(store.root))], None
    checks.append(Check("root_initialized", True, str(store.root)))

    record = read_deployment(store)
    if record is None and not provided:
        checks.append(
            Check("deployment_record", False, "缺少 deployment.json（运行 marginalia setup）")
        )
        return STATE_PARTIAL, checks, None
    checks.append(Check("deployment_record", True, str(deployment_path(store))))

    skill = expected_skill if provided else (record or {}).get("skill")
    stale = False
    broken = False

    if skill is None:
        checks.append(Check("skill", True, "未安装（--no-skill）"))
    else:
        skill_file = Path(str(skill.get("file", "")))
        exists = skill_file.is_file()
        checks.append(Check("skill_file", exists, str(skill_file)))
        if not exists:
            return STATE_PARTIAL, checks, record

        current = sha256_text(read_text(skill_file))
        recorded = skill.get("installed_sha256")
        if recorded and current != recorded:
            checks.append(Check("skill_integrity", False, "副本被改动过（sha256 不符）"))
            stale = True
        else:
            checks.append(Check("skill_integrity", True, recorded or ""))

        source = project_root() / SKILL_FILE
        if source.is_file():
            up_to_date = sha256_text(read_text(source)) == current
            checks.append(
                Check(
                    "skill_up_to_date",
                    up_to_date,
                    "与仓库一致" if up_to_date else "仓库 SKILL.md 已更新，需重新 setup --force",
                )
            )
            if not up_to_date:
                stale = True
        else:
            checks.append(Check("skill_up_to_date", True, "非仓库环境，跳过比对"))

    report = verify.verify_all(store, check_render=False)
    checks.append(
        Check(
            "data_integrity",
            report.ok,
            "通过" if report.ok else f"{len(report.errors)} 项错误（运行 marginalia verify）",
        )
    )
    if not report.ok:
        broken = True

    if stale:
        return STATE_STALE, checks, record
    if broken:
        return STATE_BROKEN, checks, record
    return STATE_READY, checks, record


def next_steps(result: SetupResult) -> list[str]:
    """给 agent / 人的编号下一步（可直接照做）。"""
    steps: list[str] = []
    if result.state in (STATE_ABSENT, STATE_PARTIAL):
        steps.append(
            "marginalia setup --root <数据根> --skills-dir <技能根> --owner-open-id <id> --owner-name <称呼>"
        )
    if result.state in (STATE_STALE, STATE_BROKEN):
        steps.append("marginalia setup --force   # 刷新 skill 副本与部署记录")
    if result.state == STATE_READY:
        steps.append("marginalia doctor          # 确认模式与能力边界")
        steps.append("marginalia user add --open-id <sender_id> --name <称呼>   # 给学员建档")
        steps.append("marginalia book create --as <uid> --title <书名> --source <底本.md>")
    return steps


def summarize(result: SetupResult, steps: list[str] | None = None) -> str:
    icon = {"ready": "✓", "absent": "✗", "partial": "✗", "stale": "⚠", "broken": "✗"}
    lines = [
        f"{icon.get(result.state, '?')} 部署状态：{result.state}"
        + ("（dry-run，未写盘）" if result.dry_run else ""),
        f"  数据根：{result.root}",
        f"  Python：{result.python} ｜ 模式：{result.mode}",
    ]
    if result.skill:
        lines.append(f"  skill：{result.skill.get('dir')}")
    lines.append("  检查：")
    for check in result.checks:
        mark = "✓" if check.ok else "✗"
        detail = f" — {check.detail}" if check.detail else ""
        lines.append(f"    {mark} {check.name}{detail}")
    if result.created:
        lines.append(f"  新建 {len(result.created)} 项")
    if result.skipped:
        lines.append(f"  跳过 {len(result.skipped)} 项")
    for note in result.notes:
        lines.append(f"  · {note}")
    if steps:
        lines.append("  下一步：")
        for idx, step in enumerate(steps, 1):
            lines.append(f"    {idx}. {step}")
    return "\n".join(lines)
