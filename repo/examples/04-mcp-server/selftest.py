#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""自检：把 server.py 当成真的 MCP server 连一遍。

    python3 selftest.py                    # 连线上
    python3 selftest.py --base http://127.0.0.1:8000

它做的事，就是一个客户端会做的事：握手、列工具、依次调用、读结果。多做的两件是
这个项目在乎的：

1. **stdout 纯净性**：每一条输出都必须是合法 JSON。stdio 传输里多一行日志，
   客户端就会把整个 server 判成坏的——而报错出现在别人的客户端里，不在我们这儿。
2. **判据能报错**：把线上条目改一个字符，`server.recompute()` 必须在那一格返回
   False。只会说"通过"的判据不算判据。

退出码：0 全通过；1 有失败；2 连不上（分得开，监控才不会把"网断了"记成"代码坏了"）。
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import server  # noqa: E402（同目录，先插路径）

PASS = []
FAIL = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"　{detail}" if detail else ""))
    return cond


class Client:
    """一个最小的 stdio 客户端：一行一条消息，按 id 配答案。"""

    def __init__(self, base: str):
        self.p = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "server.py"), "--base", base],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0)
        self.q: queue.Queue = queue.Queue()
        self.bad_lines: list[str] = []
        self.next_id = 0
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for raw in self.p.stdout:                    # 逐行读到进程结束
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            try:
                self.q.put(json.loads(line))
            except json.JSONDecodeError:
                # 这一行不是 JSON：记下来，自检会判红。绝不当成"无事发生"。
                self.bad_lines.append(line)

    def send(self, method: str, params: dict | None = None) -> int:
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self._raw(msg)
        return self.next_id

    def notify(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._raw(msg)

    def _raw(self, msg: dict) -> None:
        self.p.stdin.write(json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n")
        self.p.stdin.flush()

    def wait(self, mid: int, timeout: float = 40.0) -> dict:
        while True:
            try:
                msg = self.q.get(timeout=timeout)
            except queue.Empty:
                raise TimeoutError(f"等 id={mid} 的回应超时（{timeout}s）")
            if msg.get("id") == mid:
                return msg

    def call(self, mid: int) -> dict:
        msg = self.wait(mid)
        if "error" in msg:
            raise RuntimeError(f"JSON-RPC 错误：{msg['error']}")
        return msg["result"]

    def close(self) -> None:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()


def main() -> int:
    ap = argparse.ArgumentParser(description="MCP server 自检")
    ap.add_argument("--base", default=os.environ.get("LEDGER_BASE", server.DEFAULT_BASE))
    a = ap.parse_args()

    print(f"连 {a.base}\n")
    c = Client(a.base)
    anchors = {}
    try:
        print("握手")
        r = c.call(c.send("initialize", {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "selftest", "version": "1"}}))
        check("回协议版本", r.get("protocolVersion") in server.PROTOCOL_VERSIONS,
              r.get("protocolVersion"))
        check("声明 tools 能力", "tools" in (r.get("capabilities") or {}))
        check("给了 instructions（beta 前提要开场讲清）",
              bool((r.get("instructions") or "").strip()))
        c.notify("notifications/initialized")

        print("\n工具清单")
        r = c.call(c.send("tools/list"))
        tools = r.get("tools") or []
        names = [t.get("name") for t in tools]
        check("三个 tool", names == ["ledger_items", "ledger_verify", "ledger_export"],
              ", ".join(names))
        check("每个都有 object 型 inputSchema", all(
            (t.get("inputSchema") or {}).get("type") == "object" for t in tools))
        check("每个都标了 readOnlyHint", all(
            (t.get("annotations") or {}).get("readOnlyHint") is True for t in tools))

        print("\nledger_items")
        r = c.call(c.send("tools/call", {"name": "ledger_items",
                                         "arguments": {"limit": 2}}))
        sc = r.get("structuredContent") or {}
        check("不是错误", r.get("isError") is False)
        check("返回条数不超过 limit", sc.get("returned", 99) <= 2,
              f"returned={sc.get('returned')}")
        check("总数大于 0", (sc.get("total") or 0) > 0, f"total={sc.get('total')}")
        check("每条都带 hash", all(
            isinstance(e.get("hash"), str) and len(e["hash"]) == 64
            for e in (sc.get("items") or [])), "（字段没变）" if sc.get("items") else "（空）")

        print("\nledger_verify")
        r = c.call(c.send("tools/call", {"name": "ledger_verify", "arguments": {}}))
        sc = r.get("structuredContent") or {}
        check("verdict = agree", sc.get("verdict") == "agree", str(sc.get("verdict")))
        anchors["verify"] = (sc.get("anchor") or {}).get("sha256", "")
        check("锚值是 64 位十六进制", len(anchors["verify"]) == 64, anchors["verify"][:16] + "…")

        print("\nledger_export")
        r = c.call(c.send("tools/call", {"name": "ledger_export",
                                         "arguments": {"include_raw": True}}))
        sc = r.get("structuredContent") or {}
        anchors["export"] = sc.get("sha256", "")
        check("两处锚值一致（同一份字节）", anchors["verify"] == anchors["export"],
              anchors["export"][:16] + "…")
        check("原文可解析为 JSON", _is_json(sc.get("raw") or ""))

        print("\n判据会报错吗（本地改一个字符）")
        items = ((c.call(c.send("tools/call", {"name": "ledger_items",
                                               "arguments": {"limit": 200}}))
                  .get("structuredContent") or {}).get("items") or [])
        if len(items) >= 2:
            ok, bad, why = server.recompute(items)
            check("原样通过", ok, why)
            broken = [dict(x) for x in items]
            broken[1]["unit"] = "x" if broken[1].get("unit") != "x" else "y"
            ok2, bad2, _ = server.recompute(broken)
            check("改一条就报错，且指到那一条", not ok2 and bad2 == 1,
                  f"first_bad={bad2}")
        else:
            check("条目不足两条，跳过改一条的测试", True, f"items={len(items)}")

        check("stdout 全是 JSON（没有半行日志混进来）", not c.bad_lines,
              f"{len(c.bad_lines)} 行可疑" if c.bad_lines else "")
    except Exception as exc:                     # noqa: BLE001
        check(f"自检中断：{type(exc).__name__}: {exc}", False)
        c.close()
        return 2 if isinstance(exc, (TimeoutError, OSError)) else 1
    finally:
        c.close()

    print(f"\n{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项：" + "、".join(FAIL))
        return 1
    print("可以装进客户端了。")
    return 0


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except Exception:                             # noqa: BLE001
        return False


if __name__ == "__main__":
    raise SystemExit(main())
