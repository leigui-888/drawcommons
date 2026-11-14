#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""不信任任何人地验证账本：三件事，全部在你自己的机器上算完。

    1. 每条记录的 hash == sha256(prev_hash + "\\n" + canonical(entry))
    2. prev_hash 真的指向上一条的 hash（链没有断点）
    3. /api/ledger/export 的字节 sha256 == 页面上印的锚值

只有标准库，不需要账号、密钥、也不需要装任何东西。

用法
----
    python3 verify.py                       # 验线上
    python3 verify.py --base https://...    # 验别的部署
    python3 verify.py --tamper              # 故意改一条，看判据怎么报
    python3 verify.py --quiet               # 只输出一行结论（给 CI 用）

退出码：0 全通过；1 有一项不通过；2 取不到数据。

为什么要自己算
--------------
「我们校验过了，ok」是一句无法反驳也无法验证的话。这个脚本让它可以被反驳：
你自己拉数据、自己算哈希、自己比对页面上的锚值。三者只要有一处对不上，
就说明有东西被改过——而改在哪一条，脚本会告诉你序号。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request

GENESIS = "0" * 64          # 空链的前驱；与 spec 一致，不改


# ---------------------------------------------------------------- 规范化与哈希
# 这三行是全部规则，没有别的。跨语言实现时第 1 行是最容易出岔子的地方：
# Python 的 json.dumps(2.0) 是 "2.0"，JS 的 JSON.stringify(2.0) 是 "2"——
# 数字表示不一致，哈希就对不上。本脚本用 Python，与服务器同源，故不踩这个坑。
def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def entry_hash(body: dict, prev_hash: str) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + b"\n"
                          + canonical(body)).hexdigest()


def body_of(entry: dict) -> dict:
    """去掉 hash/prev_hash 之后的部分——被哈希的是它，不是整条记录。"""
    return {k: v for k, v in entry.items() if k not in ("hash", "prev_hash")}


# ---------------------------------------------------------------------- 取数
def get(url: str, binary: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": "verify-chain/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    return raw if binary else json.loads(raw.decode("utf-8"))


def page_anchor(base: str) -> str | None:
    """从 /ledger 页面里读人眼可见的锚值。

    刻意用正则而不是 HTML 解析器：这里要抓的是「页面上写着的那串字符」，
    用宽松的匹配反而更诚实——若页面结构变了抓不到，应当报错，而不是静默跳过。
    """
    html = get(base.rstrip("/") + "/ledger", binary=True).decode("utf-8", "replace")
    m = re.search(r'class="anchor".*?class="val">([0-9a-f]{64})<', html, re.S)
    return m.group(1) if m else None


# ---------------------------------------------------------------------- 三项检查
def check_chain(items: list[dict]) -> tuple[bool, int | None, str]:
    """逐条重算。返回 (是否通过, 首个失败序号, 说明)。"""
    prev = GENESIS
    for i, e in enumerate(items):
        if e.get("prev_hash") != prev:
            return False, i, f"prev_hash 不指向上一条（期望 {prev[:16]}…）"
        got = entry_hash(body_of(e), prev)
        if got != e.get("hash"):
            return False, i, f"hash 对不上（重算 {got[:16]}… / 记录里 {str(e.get('hash'))[:16]}…）"
        prev = e["hash"]
    tail = items[-1]["hash"] if items else GENESIS
    return True, None, f"链尾 {tail[:16]}…"


def check_anchor(base: str, raw: bytes) -> tuple[bool, str]:
    """页面印的锚值 vs 导出件字节算出来的。

    `raw` 由调用方传进来：同一份字节既算锚值又数确认条数，只取一次。
    早先这里自己再取一次，于是 items 与 export 是两次独立 GET——中间只要有
    一次写入，链检查与锚值检查比对的就不是同一版数据，两个结论拼不成一句话。
    """
    actual = hashlib.sha256(raw).hexdigest()
    printed = page_anchor(base)
    if printed is None:
        return False, "页面上找不到锚值（页面结构可能变了），无法比对"
    if printed != actual:
        return False, f"页面锚值 {printed[:16]}… ≠ 导出件实测 {actual[:16]}…"
    return True, f"锚值 {actual[:16]}…（页面印的与字节算的一致）"


def tamper(items: list[dict]) -> list[dict]:
    """演示用：改掉第 2 条的 unit，但不重算哈希。"""
    if len(items) < 2:
        return items
    out = [dict(x) for x in items]
    out[1]["unit"] = "day" if out[1].get("unit") != "day" else "hour"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="验证众汲之井账本：自己拉、自己算")
    ap.add_argument("--base", default="https://drawcommons.org", help="站点根地址")
    ap.add_argument("--tamper", action="store_true", help="演示：改一条再看判据")
    ap.add_argument("--quiet", action="store_true", help="只输出一行结论")
    a = ap.parse_args()
    base = a.base.rstrip("/")

    # 只取一次：导出件是**同一份字节**的来源——链、确认条数、锚值都由它算。
    # 早先 items 与 export 是两次独立 GET，中间只要有一次写入，两个结论就不是
    # 同一版数据；而这条脚本的全部价值在于「三个结论合起来能说明一件事」。
    try:
        raw_export = get(base + "/api/ledger/export", binary=True)
    except Exception as e:                                   # noqa: BLE001
        print(f"取数失败：{e}", file=sys.stderr)
        print("（这是「取不到数据」，不是「校验不通过」——退出码 2）", file=sys.stderr)
        return 2

    try:
        payload = json.loads(raw_export.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        print(f"导出件不是 JSON（{type(e).__name__}）：{e}", file=sys.stderr)
        print("（拿到了字节但不是账本——多半是代理错误页；退出码 1）", file=sys.stderr)
        return 1
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        print("导出件里没有 items 数组——不是账本导出格式，无法验（退出码 1）", file=sys.stderr)
        return 1

    items = payload["items"]
    if a.tamper:
        items = tamper(items)
        if not a.quiet:
            print("⚠ 已篡改第 2 条的 unit 字段（演示用）\n")

    ok_chain, bad_at, why = check_chain(items)

    # 确认层（v1.4 起导出件多出的顶层键）。**只报数，不假装验过**：验确认签名要调
    # ssh-keygen，而本脚本的承诺是「零依赖、只要标准库」。两件事分开说，比为了完整性
    # 把依赖悄悄加进来诚实。
    confs = payload.get("confirmations")
    n_conf = len(confs) if isinstance(confs, list) else 0

    if not a.quiet:
        print(f"条目数     {len(items)}")
        print(f"data_notice {payload.get('data_notice', '')}")
        if confs is not None:
            print(f"受方确认   {n_conf} 条（本脚本只报数，不验签名——"
                  f"要验跑 verify-confirm.py）")
        print()

    # 演示模式只跑链检查：改的是本地那份 items，线上锚值比的是**没改过**的字节，
    # 两者不可比。所以这里如实报 skipped——早先写的是 True，等于替一个没做的
    # 检查签字，而 quiet 下连「跳过」两个字都不会出现。
    if a.tamper:
        ok_anchor, anchor_why = "skipped", "（演示模式：改的是本地那份，与线上锚值不可比）"
    else:
        try:
            ok_anchor, anchor_why = check_anchor(base, raw_export)
        except Exception as e:                               # noqa: BLE001
            print(f"取数失败（/ledger）：{e}", file=sys.stderr)
            print("（页面拿不到 = 取不到数据，不是锚值对不上——退出码 2）", file=sys.stderr)
            return 2

    if a.quiet:
        print(f"chain_ok={ok_chain} anchor_ok={ok_anchor} items={len(items)}"
              + (f" confirmations={n_conf}" if confs is not None else "")
              + (f" first_bad={bad_at}" if not ok_chain else ""))
    else:
        print(f"  {'✅' if ok_chain else '❌'} 链完整　{why}")
        mark = "—" if ok_anchor == "skipped" else ("✅" if ok_anchor else "❌")
        print(f"  {mark} 锚值一致　{anchor_why}")
        print()
        if not ok_chain:
            print(f"结论：第 {bad_at} 条（自 0 起）对不上。")
            print("      这意味着该条记录在入链后被改过，或者链被整段替换过。")
            print("      注意：这不能证明是运营方改的，只能证明「你现在拿到的这份」")
            print("      与当初入链的那份不是同一份。")
        elif ok_anchor is True:
            print("结论：三项都对得上。这只证明「你拿到的数据与页面公示的一致」，")
            print("      不证明数据内容为真——账本记的是申报与确认，不是事实本身。")
        else:
            print("结论：只验了链（演示模式跳过了锚值比对）。")

    return 0 if (ok_chain and ok_anchor is True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
