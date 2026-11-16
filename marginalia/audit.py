"""Marginalia · 审计链：每次写操作留痕，链式哈希防篡改。

一条记录 = 谁（actor）在谁的授权下（on_behalf）对什么（target）做了什么（op）。
`prev_hash` 串联前一条的 `hash`，删改任意一行都会断链，`verify` 会报出来。
"""

from __future__ import annotations

from typing import Any

from .store import Store
from .util import now_bj, sha256_obj

GENESIS = "0" * 64


def _entry_hash(entry: dict) -> str:
    payload = {k: v for k, v in entry.items() if k != "hash"}
    return sha256_obj(payload)


def append(
    store: Store,
    uid: str,
    actor: str,
    op: str,
    target: str,
    detail: dict[str, Any] | None = None,
    on_behalf: str | None = None,
) -> dict:
    """追加一条审计记录（调用方必须已持有锁）。"""
    path = store.audit_path(uid)
    entries = store.read_jsonl(path)
    prev_hash = entries[-1]["hash"] if entries else GENESIS
    entry = {
        "seq": len(entries) + 1,
        "ts": now_bj("%Y-%m-%d %H:%M:%S"),
        "uid": uid,
        "actor": actor,
        "on_behalf": on_behalf,
        "op": op,
        "target": target,
        "detail": detail or {},
        "prev_hash": prev_hash,
    }
    entry["hash"] = _entry_hash(entry)
    store.append_jsonl(path, entry)
    return entry


def verify_chain(store: Store, uid: str) -> list[str]:
    """校验链完整性，返回问题列表（空 = 健康）。"""
    problems: list[str] = []
    entries = store.read_jsonl(store.audit_path(uid))
    prev = GENESIS
    for idx, entry in enumerate(entries, 1):
        where = f"audit.jsonl:{idx}"
        if entry.get("seq") != idx:
            problems.append(f"{where} seq 不连续：期望 {idx}，实际 {entry.get('seq')}")
        if entry.get("prev_hash") != prev:
            problems.append(f"{where} 链断裂：prev_hash 不匹配（记录被删改或插入）")
        if entry.get("uid") != uid:
            problems.append(f"{where} uid 归属错误：{entry.get('uid')} ≠ {uid}")
        recomputed = _entry_hash(entry)
        if entry.get("hash") != recomputed:
            problems.append(f"{where} 内容被篡改：hash 不匹配")
        prev = entry.get("hash", "")
    return problems
