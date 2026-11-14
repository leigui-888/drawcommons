#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""验证「受方确认」的签名：这条 give，是不是真的由收方本人认过。

    verify.py          算出「链没断、锚值一致」——证明你拿到的字节与公示的一致
    verify-confirm.py  算出「这条确认是谁签的」——证明那句话确实出自那把私钥

两件事分开，因为它们的依赖不同：前者只标准库，后者必须调 `ssh-keygen`。
把它并进 `verify.py` 会让「零依赖」那句承诺变成半句真话，所以单开一个文件。

**为什么这件事非做不可。** 导出件里的 `confirmations` 只是一句话：「主体 X 认了条目 Y」。
如果不验签名，这句话的可信度就等于「运营方说它是真的」——而整个项目的前提是
「不必相信运营方」。第 04 步之所以把 `pubkey` 塞进每条确认、还带一个 `key_fp`，
就是为了让这一步在你机器上能做；只发出去不验，那两列就成了装饰。

**为什么敢信导出件里的 hash —— 不敢。** 规范 §4 的第一步写「从 items 里取 hash」，
但这里多做一步：**自己把链重算一遍**，用重算出来的 hash 去拼载荷。理由是这个链条
要接得上：

    条目内容 --(sha256)--> hash --(受方签名)--> 确认

只拿导出件自述的 hash 去验，接上的只是后半截：签名确实绑住了某个 hash，但那个 hash
是不是这条内容的，没人算过。中间断开的那一截，正好是「把条目换掉、hash 那列照抄」
这条路能走过去的地方。重算一遍，路就断了。

用法
----
    python3 verify-confirm.py                    # 验线上
    python3 verify-confirm.py --base https://…   # 验别的部署
    python3 verify-confirm.py --export e.json    # 验手里那份文件（可离线）
    python3 verify-confirm.py --quiet            # 只输出一行结论

退出码：0 每一条确认都验过（或本件没有确认）；1 有确认验不过或无法验；
        2 取不到数据、缺工具，或**拿到的东西不是账本**（没法开始验）。
        「无法验」与「验不过」都退 1：两者都不许写成「通过」。

依赖：Python 3.8+ 与 `ssh-keygen`（OpenSSH 8.0+）。**不自己实现 Ed25519**——
自己写曲线运算的失败方式是「大多情况下正确」，而那种错正常用例发现不了。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

# 与 verify.py 同源：哈希规则只允许有一份实现，两份就会有一天不一样。
from verify import body_of, canonical, entry_hash

GENESIS = "0" * 64
TAG = "drawcommons-confirm-v1"
NAMESPACE = "drawcommons-confirm"
# party_id 会被原样拼进 allowed_signers 的那一行（`<principal> <pubkey>`）。
# 协议侧的形状是 [A-Za-z0-9_-]{1,64}，这里照抄一遍并不多余：导出件是**别人给的
# 数据**，一个带空格或换行的 party_id 能往那个文件里塞第二行，等于让「验签」
# 去验另一把钥。不合法就不验，报「无法验」。
PARTY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


# ──────────────────────────────────────────────────────────────── 取数
def get_export(base: str) -> bytes:
    req = urllib.request.Request(base.rstrip("/") + "/api/ledger/export",
                                 headers={"User-Agent": "verify-confirm/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


# ──────────────────────────────────────────────────────── 五步里的第 2、3 步
def payload_for(entry_id: str, entry_hash: str) -> bytes:
    """被签的字节：三行，末行带换行，UTF-8。

    这三行不是随便定的：第一行划域（写入面的签名挪过来会被容器拒），第二行绑条目
    （把 A 的确认挪到 B 上，重建出的载荷不同），第三行绑字节（条目被换掉，hash 变，
    载荷就变）。少任何一行，都对应的有一种「挪过去照样验得过」的伪造。
    """
    return (TAG + "\n" + entry_id + "\n" + entry_hash + "\n").encode("utf-8")


def fingerprint(pubkey_line: str) -> str:
    """OpenSSH 口径：`SHA256:` + base64(sha256(公钥 blob))，去掉填充。

    自己算而不调 `ssh-keygen -lf`：口径在 OpenSSH 里是固定的，算出来可逐字符比对，
    而多调一次外部进程就多一个「它没装」的失败面。
    """
    parts = pubkey_line.strip().split()
    if len(parts) < 2:
        return ""
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except Exception:                                        # noqa: BLE001
        return ""
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def ssh_verify(pubkey_line: str, principal: str, sig_text: str, payload: bytes) -> tuple[bool, str]:
    """`ssh-keygen -Y verify`。allowed_signers 与 payload 都现写到临时目录。

    **payload 走 stdin 的二进制通道**（不设 text=True）。Windows 上文本模式会把 `\\n`
    写成 `\\r\\n`，差一个字节，签名就对不上——本机实测踩过，症状是「其余全绿，唯独
    正确导出件验签失败」。签什么就是什么，别让任何一层替你做换行转换。
    """
    with tempfile.TemporaryDirectory(prefix="dg-vc-") as td:
        allowed = os.path.join(td, "allowed_signers")
        sigf = os.path.join(td, "sig")
        with open(allowed, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{principal} {pubkey_line.strip()}\n")
        with open(sigf, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(sig_text)
        p = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", allowed, "-I", principal,
                            "-n", NAMESPACE, "-s", sigf],
                           input=payload, capture_output=True, timeout=20)
    msg = (p.stderr or p.stdout or b"").decode("utf-8", "replace").strip()
    return p.returncode == 0, msg


# ─────────────────────────────────────────────────────────────── 重算链
def rebuild(items: list[dict]) -> tuple[dict[str, str], int | None]:
    """按导出件的顺序重算一遍，返回 {entry_id: 重算 hash} 与首个不对的序号。

    重算不与「记录里的 hash」比过就退出去报到——那条链坏没坏是 `verify.py` 的事，
    这里只管一件事：确认签的那个 hash，是不是这条内容算出来的。
    """
    prev = GENESIS
    out: dict[str, str] = {}
    first_bad = None
    for i, e in enumerate(items):
        h = entry_hash(body_of(e), prev)
        if first_bad is None and (e.get("prev_hash") != prev or e.get("hash") != h):
            first_bad = i
        eid = str(e.get("entry_id") or "")
        if eid:
            out[eid] = h
        prev = h
    return out, first_bad


def main() -> int:
    ap = argparse.ArgumentParser(description="验证受方确认的签名")
    ap.add_argument("--base", default="https://drawcommons.org", help="站点根地址")
    ap.add_argument("--export", help="本地导出件（给了就不联网）")
    ap.add_argument("--quiet", action="store_true", help="只输出一行结论")
    a = ap.parse_args()

    if shutil.which("ssh-keygen") is None:
        print("缺 ssh-keygen：装 openssh-client 再跑（这一步没有纯 Python 的替代——"
              "不自己实现 Ed25519 是刻意的）", file=sys.stderr)
        return 2

    try:
        if a.export:
            with open(a.export, "rb") as fh:
                raw = fh.read()
        else:
            raw = get_export(a.base)
        doc = json.loads(raw.decode("utf-8"))
    except Exception as e:                                   # noqa: BLE001
        print(f"取数失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 2

    # 形态先验一遍。喂进来的可能是被截断的文件、代理的错误页、或者有人手改过的
    # 导出件——这些都不是「验不过」，是「没法开始验」。不先拦，"items" 是一串
    # 字符串时会在 rebuild 里抛 AttributeError，用户看到的是一段 traceback，
    # 而不是一个能照做的结论。
    if not isinstance(doc, dict):
        print(f"导出件顶层是 {type(doc).__name__}，不是对象——这不是账本导出格式，"
              f"无法验（退出码 2）", file=sys.stderr)
        return 2
    items = doc.get("items")
    if items is None:
        items = []
    elif not isinstance(items, list):
        print(f"导出件里的 items 是 {type(items).__name__}，不是数组——无法验（退出码 2）",
              file=sys.stderr)
        return 2
    confs = doc.get("confirmations")
    if confs is not None and not isinstance(confs, list):
        print(f"导出件里的 confirmations 是 {type(confs).__name__}，不是数组——无法验"
              f"（退出码 2）", file=sys.stderr)
        return 2
    if confs is None:
        # v1.4 之前的导出件没有这个键。**不是错误**：那时还没有确认层。
        if a.quiet:
            print("confirmations=0 confirmed=0 unverified=0 note=no_confirmations_key")
        else:
            print("本件的导出格式里没有 `confirmations` 键（v1.4 之前的导出件）。")
            print("确认层是第 04 步才有的，所以这份数据里没有可验的确认。")
        return 0

    recomputed, first_bad = rebuild(items)

    results = []
    for c in confs:
        eid = str(c.get("entry_id") or "")
        party = str(c.get("party_id") or "")
        pub = str(c.get("pubkey") or "")
        fp = str(c.get("key_fp") or "")
        sig = str(c.get("sig") or "")
        h = recomputed.get(eid)

        if h is None:
            results.append((eid, party, fp, "unverified", "条目不在 items 里：确认指不到东西"))
            continue
        if not pub:
            results.append((eid, party, fp, "unverified", "确认里没带 pubkey，无法自验"))
            continue
        if not sig:
            results.append((eid, party, fp, "unverified", "确认里没有签名"))
            continue
        if fingerprint(pub) != fp:
            # 指纹对不上意味着「这条确认自称是某人，但它带的公钥不是那个人」。
            # 这一条与签名无关，签名再对也不算数。
            results.append((eid, party, fp, "failed", "key_fp 与 pubkey 不符（有人在换钥）"))
            continue
        if not PARTY_RE.match(party):
            # 见 PARTY_RE 的注释：不合法就不往下走，别把外部数据拼进 allowed_signers。
            results.append((eid, party, fp, "unverified",
                            "party_id 形状不合法（应为 1–64 位 A-Za-z0-9_-），不验"))
            continue
        ok, msg = ssh_verify(pub, party, sig, payload_for(eid, h))
        if ok:
            results.append((eid, party, fp, "confirmed", ""))
        else:
            results.append((eid, party, fp, "failed", msg.splitlines()[-1] if msg else "验签失败"))

    confirmed = sum(1 for r in results if r[3] == "confirmed")
    failed = sum(1 for r in results if r[3] == "failed")
    unverified = sum(1 for r in results if r[3] == "unverified")

    if a.quiet:
        print(f"confirmations={len(confs)} confirmed={confirmed} "
              f"failed={failed} unverified={unverified}"
              + (f" chain_first_bad={first_bad}" if first_bad is not None else ""))
    else:
        print(f"条目数        {len(items)}")
        print(f"受方确认      {len(confs)} 条")
        if first_bad is not None:
            print(f"⚠ 链在第 {first_bad} 条（自 0 起）对不上——先跑 verify.py 看那一条；")
            print("  下面用的是重算出来的 hash，所以这一条的确认多半也会失败。")
        print()
        for eid, party, fp, state, why in results:
            mark = {"confirmed": "✅", "failed": "❌", "unverified": "⚠"}[state]
            label = {"confirmed": "已确认", "failed": "验不过", "unverified": "无法验"}[state]
            print(f"  {mark} {label}　{eid}　←　{party}　{fp[:19]}…"
                  + (f"\n     {why}" if why else ""))
        print()
        if not results:
            print("本件没有受方确认：链与锚值可以验（verify.py），确认层无内容可验。")
        elif failed == 0 and unverified == 0:
            print("结论：每一条确认都由它自称的那个主体签的，且签的是这条内容算出来的 hash。")
            print("      这不证明条目描述的事发生过——它证明的是「这个主体认过这条记录」。")
        elif unverified and failed == 0:
            print("结论：验过的都过了，但有确认**没法验**（见上面 ⚠ 那几行）。")
            print("      「没法验」不是「通过」——这两件事在记录里必须分开写。")
        else:
            print(f"结论：{failed} 条确认验不过。签名与条目对不上，说明这份导出件")
            print("      里的确认不是照着当前内容签的（换过条目、换过公钥，或被拼凑过）。")

    return 0 if (failed == 0 and unverified == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
