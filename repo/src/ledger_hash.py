# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 数字丐帮 2.0 贡献者
"""账本条目的规范化序列化与哈希链。

存在的理由只有一个：让"某条记录没有被改写"成为一件任何人可自行验证的事，
而不是一件需要相信运营方的事。

设计约束（与 W4 的账本计量载体一致）：
  1. 规范化序列化必须与语言、字典顺序、空白无关 —— 否则同一份数据在两台机器上算出两个哈希；
  2. 哈希链只追加，不改写；校验失败必须给出**第一个**失败的序号，而不是"校验失败"四个字；
  3. 不依赖任何第三方库：一个只用标准库的校验脚本，才可能被外部审计者直接跑起来。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

GENESIS = "0" * 64


def canonical(obj: Any) -> bytes:
    """规范化序列化：键排序、无多余空白、UTF-8、不转义非 ASCII。"""
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def entry_hash(entry: dict, prev_hash: str) -> str:
    """单条记录哈希 = sha256(prev_hash + "\\n" + canonical(entry))。

    把 prev_hash 放进被哈希的输入，而不是只存在字段里：
    否则可以整段替换中段记录并重算该段，链退化为"每条各自独立"。
    """
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(b"\n")
    h.update(canonical(entry))
    return h.hexdigest()


def build_chain(entries: Iterable[dict], genesis: str = GENESIS) -> list[dict]:
    """为一组记录追加 hash / prev_hash 字段，返回新列表（不改动入参）。"""
    out: list[dict] = []
    prev = genesis
    for e in entries:
        body = {k: v for k, v in e.items() if k not in ("hash", "prev_hash")}
        h = entry_hash(body, prev)
        out.append({**body, "prev_hash": prev, "hash": h})
        prev = h
    return out


def verify_chain(chain: list[dict], genesis: str = GENESIS) -> tuple[bool, int | None]:
    """逐条校验，返回 (是否通过, 第一个失败的序号)。序号从 0 起；通过时返回 None。"""
    prev = genesis
    for i, e in enumerate(chain):
        body = {k: v for k, v in e.items() if k not in ("hash", "prev_hash")}
        if e.get("prev_hash") != prev:
            return False, i
        if entry_hash(body, prev) != e.get("hash"):
            return False, i
        prev = e["hash"]
    return True, None


if __name__ == "__main__":
    demo = [
        {"entry_id": "e-001", "kind": "donation", "amount_fen": 4_500_000},
        {"entry_id": "e-002", "kind": "expense", "amount_fen": 120_000},
        {"entry_id": "e-003", "kind": "matching", "amount_fen": 0},
    ]
    chained = build_chain(demo)
    ok, idx = verify_chain(chained)
    print(f"三条记录建链：ok={ok} fail_at={idx} last={chained[-1]['hash'][:16]}")

    # 篡改中段：改金额但不重算
    tampered = [dict(x) for x in chained]
    tampered[1]["amount_fen"] = 1
    ok, idx = verify_chain(tampered)
    print(f"篡改第 2 条金额：ok={ok} fail_at={idx}  ← 应定位到 1")

    # 整段替换并重算该段：prev_hash 会暴露它
    forged = tampered[:]
    forged[1]["hash"] = entry_hash({k: v for k, v in forged[1].items() if k not in ("hash", "prev_hash")}, forged[0]["hash"])
    ok, idx = verify_chain(forged)
    print(f"改写第 2 条并重算自身哈希：ok={ok} fail_at={idx}  ← 应定位到 2")
