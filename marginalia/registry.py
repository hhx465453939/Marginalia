"""Marginalia · 学员注册表：身份的唯一真源。

铁律：`speaker`（批注里的说话人）**只能**从这里派生，不接受外部输入。
"""

from __future__ import annotations

import re
from typing import Any

from .store import Store, validate_uid
from .util import EXIT_IDENTITY, EXIT_INTEGRITY, MarginaliaError, now_bj, today_bj

SCHEMA_VERSION = 1
ROLES = {"student", "owner"}
STATUSES = {"active", "paused", "archived"}


def empty_registry() -> dict:
    return {"schema": SCHEMA_VERSION, "users": []}


def load(store: Store) -> dict:
    store.require_initialized()
    reg = store.read_json(store.registry_path)
    if not isinstance(reg.get("users"), list):
        raise MarginaliaError("registry.json 结构损坏：缺少 users 数组", EXIT_INTEGRITY)
    return reg


def save(store: Store, reg: dict) -> None:
    reg["schema"] = SCHEMA_VERSION
    store.write_json(store.registry_path, reg)


def _norm_token(token: str) -> str:
    return token.strip().lower()


def find(reg: dict, token: str) -> dict | None:
    """按 uid / open_id / 称呼 / 别名解析，全部大小写不敏感。"""
    t = _norm_token(token)
    for user in reg["users"]:
        if _norm_token(user.get("uid", "")) == t:
            return user
        if t in {_norm_token(x) for x in user.get("open_ids", [])}:
            return user
        if _norm_token(user.get("name", "")) == t:
            return user
        if t in {_norm_token(x) for x in user.get("aliases", [])}:
            return user
    return None


def resolve(store: Store, token: str) -> dict:
    """解析身份；解析不到 → exit 2（G1 身份闸）。"""
    if not token or not token.strip():
        raise MarginaliaError(
            "缺少学员身份",
            EXIT_IDENTITY,
            hint="用 --as <uid|open_id|称呼> 指定；先 `marginalia user add` 建档",
        )
    user = find(load(store), token)
    if user is None:
        raise MarginaliaError(
            f"未知学员: {token!r} —— 该身份不在注册表中，拒绝任何读写",
            EXIT_IDENTITY,
            hint="新学员请先建档：marginalia user add --open-id <id> --name <称呼>",
        )
    if user.get("status") == "archived":
        raise MarginaliaError(f"学员已归档: {user['uid']}", EXIT_IDENTITY)
    return user


def is_owner(store: Store, user: dict) -> bool:
    return user.get("role") == "owner"


def require_owner(store: Store, user: dict, why: str) -> None:
    if not is_owner(store, user):
        raise MarginaliaError(
            f"权限不足：{why} 需要 owner 身份（当前 {user.get('uid')} / {user.get('name')}）",
            EXIT_IDENTITY,
        )


def speaker_of(store: Store, user: dict) -> str:
    """批注说话人：永远由注册表派生（G4 说话人闸）。"""
    name = (user.get("name") or "").strip()
    if not name:
        raise MarginaliaError(
            f"学员 {user.get('uid')} 缺少称呼，无法生成批注说话人", EXIT_INTEGRITY
        )
    return name


def add_user(
    store: Store,
    open_id: str,
    name: str,
    uid: str | None = None,
    role: str = "student",
    aliases: list[str] | None = None,
    goal: str = "",
    pace: str = "",
) -> dict:
    reg = load(store) if store.is_initialized() else empty_registry()

    name = (name or "").strip()
    if not name:
        raise MarginaliaError("称呼不能为空", EXIT_IDENTITY)
    if role not in ROLES:
        raise MarginaliaError(f"role 只能是 {sorted(ROLES)}", EXIT_IDENTITY)

    open_id = (open_id or "").strip()
    if not open_id:
        raise MarginaliaError(
            "open_id 不能为空（必须是真实消息里的 sender_id，不可猜测）", EXIT_IDENTITY
        )

    # open_id 唯一
    for u in reg["users"]:
        if open_id in u.get("open_ids", []):
            raise MarginaliaError(
                f"open_id 已被 {u['uid']}（{u.get('name')}）占用: {open_id}", EXIT_IDENTITY
            )

    if uid is None:
        uid = "owner" if role == "owner" else _derive_uid(name)
    validate_uid(uid)
    if find(reg, uid) is not None:
        raise MarginaliaError(f"uid 已存在: {uid}", EXIT_IDENTITY)

    # owner 只能有一个
    if role == "owner" and any(u.get("role") == "owner" for u in reg["users"]):
        raise MarginaliaError("owner 已存在，只能有一个系统所有者", EXIT_IDENTITY)

    user = {
        "uid": uid,
        "open_ids": [open_id],
        "name": name,
        "aliases": [a.strip() for a in (aliases or []) if a.strip()],
        "role": role,
        "status": "active",
        "joined": today_bj(),
        "profile": {"goal": goal, "pace": pace},
    }
    reg["users"].append(user)
    save(store, reg)

    # 建书房
    store.user_dir(uid).mkdir(parents=True, exist_ok=True)
    store.books_dir(uid).mkdir(parents=True, exist_ok=True)
    store.write_json(
        store.profile_path(uid),
        {
            "schema": SCHEMA_VERSION,
            "uid": uid,
            "name": name,
            "goal": goal,
            "pace": pace,
            "background": "",
            "style_notes": "",
            "notes": "",
            "updated": now_bj(),
        },
    )
    store.write_text(store.audit_path(uid), "")
    return user


def _derive_uid(name: str) -> str:
    """从称呼生成合法 uid：ASCII 走 slug 化，中文直接用称呼（目录名可读）。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]+", "", name.strip())
    if cleaned and re.search(r"[\u4e00-\u9fff]", cleaned):
        return cleaned[:40]
    ascii_part = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if ascii_part:
        return ascii_part[:40]
    import hashlib

    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"u-{digest}"


def list_users(store: Store) -> list[dict]:
    return load(store)["users"]


def get_profile(store: Store, uid: str) -> dict[str, Any]:
    return store.read_json(store.profile_path(uid), default={})
