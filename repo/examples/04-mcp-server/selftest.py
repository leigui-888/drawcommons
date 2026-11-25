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
        check("五个 tool", names == ["ledger_items", "ledger_verify", "ledger_export",
                                     "requests_list", "entry_draft"],
              ", ".join(names))
        check("每个都有 object 型 inputSchema", all(
            (t.get("inputSchema") or {}).get("type") == "object" for t in tools))
        check("每个都标了 readOnlyHint（含 entry_draft：它只拼字节，不发）", all(
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

        print("\nledger_export 的 expect（比对交给读者）")
        r = c.call(c.send("tools/call", {"name": "ledger_export",
                                         "arguments": {"expect": anchors["export"]}}))
        sc = r.get("structuredContent") or {}
        check("expect 与现算一致 → match=true", sc.get("match") is True, str(sc.get("match")))
        r = c.call(c.send("tools/call", {"name": "ledger_export",
                                         "arguments": {"expect": "0" * 64}}))
        sc = r.get("structuredContent") or {}
        check("expect 不一致 → match=false，且两个值都印出来",
              sc.get("match") is False and sc.get("expect") == "0" * 64
              and sc.get("sha256") == anchors["export"], str(sc.get("match")))

        print("\nrequests_list（发现口，读的）")
        r = c.call(c.send("tools/call", {"name": "requests_list",
                                         "arguments": {"limit": 3}}))
        sc = r.get("structuredContent") or {}
        check("不是错误", r.get("isError") is False, str(sc.get("error"))[:60])
        check("返回条数不超过 limit", (sc.get("count") or 0) <= 3, f"count={sc.get('count')}")
        check("带 next_cursor 或空屏时为 null",
              isinstance(sc.get("next_cursor"), str) or
              (sc.get("count") == 0 and sc.get("next_cursor") is None),
              str(sc.get("next_cursor")))

        print("\nentry_draft（只拼字节，一个字节都不发）")
        body = {"request_id": "rq_selftest01", "state": "open", "category": "review",
                "need_desc": "自检用，不会发出去", "requested_by": "pt_selftest"}
        r = c.call(c.send("tools/call", {"name": "entry_draft", "arguments": {
            "endpoint": "request", "party": "pt_selftest", "body": body}}))
        sc = r.get("structuredContent") or {}
        rows = (sc.get("payload") or "").split("\n")
        check("起草成功（stage=envelope）", sc.get("stage") == "envelope",
              str(sc.get("error"))[:60])
        check("载荷七行 + 末行换行", len(rows) == 8 and rows[7] == "", f"{len(rows)} 段")
        check("第 2/3/4 行 = POST / 路径 / 主体",
              rows[1:4] == ["POST", "/api/v1/request", "pt_selftest"], str(rows[1:4]))
        check("第 7 行 = body_text 的 sha256",
              rows[6] == _sha256(sc.get("body_text") or ""))
        check("body_text 与原对象是同一份内容（只是紧凑了）",
              _same(body, sc.get("body_text") or ""))
        check("给了 dry_run 与 send 两段命令",
              set((sc.get("commands") or {})) == {"dry_run", "send"})
        check("两段都含 ssh-keygen 与 curl（签与发各在一段里，不用人拼起来）",
              all(("ssh-keygen -Y sign" in v and "curl " in v)
                  for v in (sc.get("commands") or {}).values()))
        check("命令里不绕解释器（纯 shell，不 python -c）",
              all("python" not in v for v in (sc.get("commands") or {}).values()))

        r = c.call(c.send("tools/call", {"name": "entry_draft", "arguments": {
            "endpoint": "confirm", "party": "pt_selftest",
            "body": {"entry_id": "g_doesnotexist"}}}))
        check("confirm 指一个不存在的条目 → 如实说没有，不编一个 hash 去签",
              r.get("isError") is True, str((r.get("structuredContent") or {})
                                            .get("error"))[:60])
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


def _sha256(text: str) -> str:
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _same(obj: dict, body_text: str) -> bool:
    """body_text 解回来必须还是那个对象。键序无关，值必须一致。"""
    try:
        return json.loads(body_text) == obj
    except Exception:                             # noqa: BLE001
        return False


if __name__ == "__main__":
    raise SystemExit(main())
