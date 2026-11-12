#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""众汲之井 · MCP server（stdio）：三个只读接口变成三个 tool。

    ledger_items    取条目（分页、可按类型筛）
    ledger_verify   在本机重算哈希链与锚值，再把服务端自述摆在一起比对
    ledger_export   取导出件原文，算它的 sha256（就是锚值）

**零依赖**：Python 3.8+，标准库。不装 `mcp` SDK，也不装 httpx/pydantic。
理由不是"省事"，是三条：

1. **可审计。** 一个能读完全部行为的文件，比一个装进来的依赖树可信。这个项目
   的资产是"你不用信我"——那么连工具本身也应当能被一眼读完。全文只有 GET。
2. **供应链。** MCP SDK 拖着 pydantic 与 httpx，版本漂移会让"昨天能用今天不能用"，
   而报错出现在别人的客户端里，不在我们这儿。
3. **协议面很小。** stdio 传输就是「一行一个 JSON-RPC 消息」，需要的只有
   `initialize` / `tools/list` / `tools/call` / `ping` 四个方法。为这四个方法装
   十兆依赖，是把简单的事交给别人维护。

三条设计立场（都写在这里，而不是藏在代码里）：

1. **只读，且只连一个地址。** base URL 在启动时定死（`--base` 或 `LEDGER_BASE`），
   tool 参数不能改它。若允许调用方传 URL，这个 server 就成了一台开放代理——它跑在
   别人的机器上，能打到那台机器能打到的内网。三个 tool 都不可能写任何东西：
   协议里没有写方法，代码里没有第二个 HTTP 动词。
2. **不采信服务端自述。** `ledger_verify` 拿 `/api/ledger/verify` 的 `ok` 只当"一面之词"，
   真正判据是本机重算：逐条算 `sha256(prev_hash + "\\n" + canonical(entry))`、查
   `prev_hash` 是否接上一条、对导出件算 sha256 当锚值。服务端说 ok 而本机算出断链，
   这个 tool 报的是断链。
3. **"取不到数"不是"校验失败"。** 网络错误返回 `isError: true` 并说明取不到；
   链真的断了返回正常结果 + `verdict: "chain_broken"`。两者在监控里是两件事，
   混成一件就会把"网断了"记成"账本被改了"。

跑它：

    python3 server.py                          # 连 https://drawcommons.org
    python3 server.py --base http://127.0.0.1:8000   # 连本地起的服务

注意：**stdout 是协议通道**。这个文件里除了 `_write()`，任何地方都不许 print 到
stdout——多一行日志，客户端就会解析失败并把整个 server 标成坏掉。日志一律走 stderr。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

SERVER_NAME = "drawcommons-ledger"
SERVER_VERSION = "0.1.0-beta"
DEFAULT_BASE = "https://drawcommons.org"
TIMEOUT = 20                      # 秒。公网够用；卡住时不至于让客户端干等
UA = f"{SERVER_NAME}/{SERVER_VERSION} (+https://drawcommons.org)"
GENESIS = "0" * 64                # 空链的前驱；与 spec 一致，不改

# 支持的协议版本，从新到旧。客户端报哪个就回哪个（握手要谈拢，不能让对方
# 按新版的格式发、按旧版的理解答）；都不认识就回我们最新的一个。
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

BASE = DEFAULT_BASE               # main() 里定死；tool 无法改它


# ────────────────────────────────────────────────────────── 取数（只有 GET）
def http_get(path: str) -> bytes:
    """取一个绝对路径。失败一律抛，由调用方决定怎么说。"""
    url = BASE.rstrip("/") + path
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def get_json(path: str) -> dict:
    return json.loads(http_get(path).decode("utf-8"))


def describe(exc: Exception) -> str:
    """把取数异常翻成一句能照着排查的话。

    刻意区分「连不上」与「连上了但回的不对」：前者是网络/地址问题，后者是
    对方的问题。都写成「失败」的话，用户第一反应是怀疑数据，而数据可能是好的。
    """
    if isinstance(exc, urllib.error.HTTPError):
        # exc.url 已是完整地址（别再加 BASE，否则报出来是 dupe 的 URL，
        # 而排错时第一个要看的就是那个地址对不对）
        return f"接口返回 HTTP {exc.code}（{getattr(exc, 'url', '')}）"
    if isinstance(exc, urllib.error.URLError):
        return f"连不上 {BASE}：{exc.reason}"
    if isinstance(exc, json.JSONDecodeError):
        return f"返回的不是 JSON（{exc}）"
    return f"{type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────── 本机重算（判据在这里）
def canonical(obj) -> bytes:
    """与服务器同一套规范化：键排序、无空白、非 ASCII 不转义。

    跨语言重写时这是最容易出岔子的一行：Python 的 json.dumps(2.0) 是 "2.0"，
    JS 的 JSON.stringify(2.0) 是 "2"。数字表示不一致，哈希就对不上，于是
    你会得到一个假的「校验失败」，然后开始怀疑一份其实没问题的数据。
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def entry_hash(body: dict, prev_hash: str) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + b"\n"
                          + canonical(body)).hexdigest()


def body_of(entry: dict) -> dict:
    """被哈希的是「去掉 hash/prev_hash 之后的部分」，不是整条记录。"""
    return {k: v for k, v in entry.items() if k not in ("hash", "prev_hash")}


def recompute(items: list) -> tuple[bool, int | None, str]:
    """从 genesis 起逐条重算。返回 (是否通过, 首个失败序号, 说明)。"""
    prev = GENESIS
    for i, e in enumerate(items):
        if not isinstance(e, dict):
            return False, i, "这一条不是对象"
        if e.get("prev_hash") != prev:
            return False, i, (f"prev_hash 不指向上一条（该条写 {str(e.get('prev_hash'))[:16]}…，"
                              f"应为 {prev[:16]}…）")
        got = entry_hash(body_of(e), prev)
        if got != e.get("hash"):
            return False, i, (f"hash 对不上（重算 {got[:16]}… / 记录里 "
                              f"{str(e.get('hash'))[:16]}…）")
        prev = str(e["hash"])
    return True, None, f"链尾 {prev[:16]}…"


# ───────────────────────────────────────────────────────────────── 三个 tool
def tool_items(args: dict) -> dict:
    try:
        limit = int(args.get("limit", 20))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise RpcError(-32602, "limit / offset 必须是整数")
    limit = max(1, min(limit, 200))          # 上限写死：一条 tool 结果不该撑爆上下文
    offset = max(0, offset)
    typ = args.get("type")

    try:
        payload = get_json("/api/ledger/items")
    except Exception as exc:                  # noqa: BLE001（取数失败一律如实说）
        return _failure(f"取不到 /api/ledger/items：{describe(exc)}")

    items = payload.get("items") or []
    selected = [e for e in items if typ is None or e.get("type") == typ]
    page = selected[offset:offset + limit]

    head = (f"账本条目 {len(items)} 条"
            + (f"，按 type={typ} 筛后 {len(selected)} 条" if typ else "")
            + f"；本次返回第 {offset + 1}–{offset + len(page)} 条"
            f"（limit={limit}）")
    lines = [head, f"data_notice：{payload.get('data_notice', '')}"]
    if typ or offset or len(page) != len(selected):
        lines.append("注：筛过或截断的条目不是连续链段——prev_hash 仍指全链上的上一条，"
                     "所以这份切片不能拿来验链；要验链用 ledger_verify。")
    text = "\n".join(lines) + "\n\n" + json.dumps(page, ensure_ascii=False, indent=1)

    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {
            "total": len(items),
            "filtered": len(selected),
            "offset": offset,
            "limit": limit,
            "returned": len(page),
            "genesis": payload.get("genesis"),
            "data_notice": payload.get("data_notice"),
            "items": page,
        },
        "isError": False,
    }


def tool_verify(args: dict) -> dict:
    """服务端说 ok 是一句话；本机重算才是判据。两者都摆出来，不替谁圆场。"""
    try:
        claims = get_json("/api/ledger/verify")
        payload = get_json("/api/ledger/items")
        raw = http_get("/api/ledger/export")
    except Exception as exc:                  # noqa: BLE001
        return _failure(f"取不到数据，什么都没验：{describe(exc)}")

    items = payload.get("items") or []
    ok_local, bad_at, why = recompute(items)
    tail_local = items[-1].get("hash") if items else GENESIS
    anchor = hashlib.sha256(raw).hexdigest()

    claim_ok = claims.get("ok")
    claim_n = claims.get("items")
    claim_tail = claims.get("chain_tail")
    agree = (claim_ok == ok_local and claim_n == len(items)
             and (claim_tail in (None, tail_local)))

    if not ok_local:
        verdict = "chain_broken"
    elif not agree:
        verdict = "server_disagrees"
    else:
        verdict = "agree"

    def mark(b: bool) -> str:
        return "✅" if b else "❌"

    lines = [
        "链校验（本机重算，不采信服务端自述）",
        f"  条目数      {len(items)}（服务端说 {claim_n}）",
        f"  {mark(bool(claim_ok))} 服务端自称  ok={claim_ok}  chain_tail={str(claim_tail)[:16]}…",
        f"  {mark(ok_local)} 本机重算    ok={ok_local}  {why}",
        f"  {mark(agree)} 两处一致    {'是' if agree else '否'}",
        "",
        f"锚值（导出件 {len(raw):,} 字节的 sha256，本机算的）",
        f"  {anchor}",
        "",
    ]
    if verdict == "chain_broken":
        lines += [
            f"结论：第 {bad_at} 条（自 0 起）对不上——你拿到的这份与入链的那份不是同一份。",
            "      这不能证明是谁改的，只能证明改过。",
        ]
    elif verdict == "server_disagrees":
        lines += [
            "结论：本机算的链是通的，但服务端自述的 ok/条数/链尾与它自己给出的条目对不上。",
            "      这类不一致本身就是问题——要么它算错了，要么它给的条目不是它算的那份。",
        ]
    else:
        lines += [
            "结论：三项都对得上。这只证明「你拿到的字节与页面公示的一致、链没断」，",
            "      不证明条目描述的事真的发生过——账本记的是申报与确认，不是事实本身。",
        ]
    lines.append("")
    lines.append("Boundary: this verifies bytes, not facts. A complete hash chain also "
                 "results from a false entry that was recorded honestly.")

    return {
        "content": [{"type": "text", "text": "\n".join(lines)}],
        "structuredContent": {
            "verdict": verdict,
            "server": {"ok": claim_ok, "items": claim_n, "chain_tail": claim_tail,
                       "first_bad": claims.get("first_bad")},
            "local": {"ok": ok_local, "first_bad": bad_at, "items": len(items),
                      "chain_tail": tail_local, "detail": why},
            "anchor": {"sha256": anchor, "bytes": len(raw)},
            "agree": agree,
        },
        "isError": False,
    }


MAX_RAW = 200_000                 # 导出件原文字节上限：超了就明说截断，不静默截


def tool_export(args: dict) -> dict:
    include_raw = bool(args.get("include_raw", False))
    try:
        raw = http_get("/api/ledger/export")
        payload = get_json("/api/ledger/items")
    except Exception as exc:                  # noqa: BLE001
        return _failure(f"取不到 /api/ledger/export：{describe(exc)}")

    anchor = hashlib.sha256(raw).hexdigest()
    notice = payload.get("data_notice", "")
    text = (f"导出件 {len(raw):,} 字节，条目 {len(payload.get('items') or [])} 条\n"
            f"锚值（本机算的 sha256）：{anchor}\n"
            f"data_notice：{notice}\n\n"
            "拿这个值去 https://drawcommons.org/ledger 页面对一眼，或者下载 .txt 自己算——\n"
            "指纹一致只说明字节没变，不说明条目描述的事发生过。")

    structured = {"sha256": anchor, "bytes": len(raw),
                  "items": len(payload.get("items") or []), "data_notice": notice}
    truncated = False
    if include_raw:
        if len(raw) > MAX_RAW:
            # 静默截断是最坏的一种：拿到的 JSON 不完整，看起来却像完整
            text += (f"\n\n原文 {len(raw):,} 字节，超过本 tool 的 {MAX_RAW:,} 字节上限，"
                     f"只回前 {MAX_RAW:,} 字节——这份不是完整原文，不能拿去算哈希。")
            truncated = True
            body = raw[:MAX_RAW].decode("utf-8", "replace")
        else:
            body = raw.decode("utf-8")
        text += "\n\n" + body
        structured["raw"] = body
    structured["truncated"] = truncated

    return {"content": [{"type": "text", "text": text}],
            "structuredContent": structured, "isError": False}


def _failure(message: str) -> dict:
    """取不到数。**不是**校验失败——这两件事在监控里必须分得开。"""
    return {"content": [{"type": "text", "text": message}],
            "structuredContent": {"error": message},
            "isError": True}


# ──────────────────────────────────────────────────────────── tool 声明
TOOLS = [
    {
        "name": "ledger_items",
        "description": (
            "取众汲之井账本的条目（只读）。每条是一个 give/receive/payback 记录，"
            "带 prev_hash 与 hash。\n"
            "Read-only ledger entries, each with its hash. Beta: the ledger currently "
            "holds 4 structural samples with fake IDs, not real records."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200,
                          "default": 20, "description": "返回条数上限"},
                "offset": {"type": "integer", "minimum": 0, "default": 0,
                           "description": "跳过前 N 条"},
                "type": {"type": "string", "enum": ["give", "receive", "payback"],
                         "description": "只看某一类条目；筛选后不再是连续链段"},
            },
            "additionalProperties": False,
        },
        "annotations": {"title": "账本条目", "readOnlyHint": True,
                        "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": True},
    },
    {
        "name": "ledger_verify",
        "description": (
            "在本机重算哈希链与锚值，再与服务端自述比对（不采信服务端的 ok）。"
            "返回 verdict：agree / chain_broken / server_disagrees。\n"
            "Recomputes the hash chain and anchor locally and compares with the server's "
            "own claim. Proves bytes are unchanged, not that the events happened."),
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
        "annotations": {"title": "校验（本机重算）", "readOnlyHint": True,
                        "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": True},
    },
    {
        "name": "ledger_export",
        "description": (
            "取导出件原文并算它的 sha256——这个值就是账本锚值，可与 /ledger 页面上印的"
            "那串逐字符比对。include_raw=true 时一并回原文（超过 200 KB 会截断并说明）。\n"
            "Fetches the exported bytes and computes the anchor (sha256) locally."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_raw": {"type": "boolean", "default": False,
                                "description": "是否连原文一起返回"},
            },
            "additionalProperties": False,
        },
        "annotations": {"title": "导出件与锚值", "readOnlyHint": True,
                        "destructiveHint": False, "idempotentHint": True,
                        "openWorldHint": True},
    },
]

TOOL_IMPL = {
    "ledger_items": tool_items,
    "ledger_verify": tool_verify,
    "ledger_export": tool_export,
}

# 握手时给客户端读的一段话。工具描述会随每次调用进入上下文，但这一段只在
# 开场读一遍——适合放「别把这些数字当真实数据」这类前提。
INSTRUCTIONS = (
    "众汲之井账本（beta）。三个 tool 全是只读：取条目、本机重算校验、取导出件与锚值。"
    "账本里现有 4 条结构验证样例，用假 ID，不是真实账目；引用数字时请说明这一点。"
    "协议 v2.1-r5 处于公示期（2026-11-12 起算），尚未生效。"
    "链校验只证明字节未变，不证明条目描述的事发生过。"
)


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def initialize(params: dict) -> dict:
    want = params.get("protocolVersion")
    version = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION,
                       "title": "众汲之井账本"},
        "instructions": INSTRUCTIONS,
    }


def call_tool(params: dict) -> dict:
    name = params.get("name")
    if name not in TOOL_IMPL:
        raise RpcError(-32602, f"未知 tool：{name!r}（有 {', '.join(TOOL_IMPL)}）")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        raise RpcError(-32602, "arguments 必须是对象")
    try:
        return TOOL_IMPL[name](args)
    except RpcError:
        raise
    except Exception as exc:                  # noqa: BLE001（tool 内部错误也要成结果）
        return _failure(f"tool 执行出错：{type(exc).__name__}: {exc}")


def dispatch(method: str, params: dict):
    if method == "initialize":
        return initialize(params)
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        return call_tool(params)
    if method in ("ping", "logging/setLevel"):
        return {}
    raise RpcError(-32601, f"不支持的方法：{method}")


_MISSING = object()


def handle_one(msg):
    """处理一条消息。通知（无 id）返回 None——JSON-RPC 里通知不回应。"""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        mid = msg.get("id") if isinstance(msg, dict) else None
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32600, "message": "invalid request"}}
    mid = msg.get("id", _MISSING)
    method = msg.get("method")
    if not isinstance(method, str):
        if mid is _MISSING:
            return None
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32600, "message": "missing method"}}
    try:
        result = dispatch(method, msg.get("params") or {})
    except RpcError as exc:
        if mid is _MISSING:
            return None
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": exc.code, "message": exc.message}}
    except Exception as exc:                  # noqa: BLE001
        if mid is _MISSING:
            return None
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32603,
                          "message": f"{type(exc).__name__}: {exc}"}}
    if mid is _MISSING:
        return None
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def write(obj) -> None:
    """唯一的 stdout 出口。走 buffer：Windows 控制台默认 cp936，中文会变乱码键名。"""
    sys.stdout.buffer.write(json.dumps(obj, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main(argv=None) -> int:
    global BASE
    ap = argparse.ArgumentParser(description="众汲之井账本 MCP server（stdio，只读）")
    ap.add_argument("--base", default=os.environ.get("LEDGER_BASE", DEFAULT_BASE),
                    help=f"站点根地址，默认 {DEFAULT_BASE}（也可用环境变量 LEDGER_BASE）")
    a = ap.parse_args(argv)
    if not a.base.startswith(("http://", "https://")):
        print(f"--base 必须以 http:// 或 https:// 开头：{a.base}", file=sys.stderr)
        return 2
    BASE = a.base.rstrip("/")

    print(f"{SERVER_NAME} {SERVER_VERSION} · stdio · base={BASE} · 只读", file=sys.stderr)
    for raw in sys.stdin.buffer:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except Exception as exc:              # noqa: BLE001
            write({"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": f"parse error: {exc}"}})
            continue
        if isinstance(msg, list):
            # 批量请求：逐条处理，通知不产生回应；一条都没有回应时不发空数组
            resp = [r for r in (handle_one(m) for m in msg) if r is not None]
            if resp:
                write(resp)
            continue
        out = handle_one(msg)
        if out is not None:
            write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
