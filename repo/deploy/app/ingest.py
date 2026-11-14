# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""写入面：四条受控 POST。挂在 `/api/v1/*`，与只读的公开页是两个进程。

**为什么是另一个进程，而不是给 app.py 加个 do_POST。**

公开页的卷是只读挂载，进程在物理上没有写库的能力——这一条写进了部署口径，也是
「公开页攻击面少一整类」的全部依据。同一个进程里加写入，就得把这个卷改成读写，
那条承诺当场变成一句注释。所以写入单独一个容器：卷只对它读写，对 app 仍只读。

**四条端点共用一条通路。**

`/api/v1/party`、`/api/v1/request`、`/api/v1/entry`、`/api/v1/confirm` 都走
`signing.verify`，没有「这条简单点，少验一样」的分支。验签之后才解析语义；语义错了回 422，
签名错了回 401，两者不混——把「签名不对」报成「字段不对」，等于教攻击者怎么绕过。

`confirm` 多一道**内层签名**：外层证明「请求是这把钥发的」，内层证明「这个人认可这条已经
发生的事」。内层签的载荷由服务端从库里重算（`entry_id` + 该条目当前 `hash`），客户端交上
来的只能用来核对——否则签名保护的就是客户端自己写的那句话。

**`request` 的 `delivered` 不是一行状态，是一个转换。** 它同时产出 `give` 与 `receive`
两条账目，与状态行同事务（`ledger_store.convert_delivery`）。这仍然是「一条端点」，因为
两条账目不是客户端提交的内容：它们是那条已签的 delivered 行的**函数**——任何人事后都能
用公开的需求单复算出同样的字节。反过来，让客户端分两次提交「状态」和「账目」，就会出现
「已交付但账上没东西」的中间态，而那个中间态没有任何人能修（delivered 不能重进）。

**这一层不做的事**（写进 spec/ingest.md §7）：不建会话、不发 token、不存 cookie、
不做账号体系。请求体自签，主体就是那把钥；服务端不记得「你是谁」，每次重新验。
状态全部靠 append-only 表推进，没有一行是可改的。
"""

from __future__ import annotations

import collections
import json
import os
import re
import shutil
import sqlite3
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ledger_store
import signing

DB_PATH = os.environ.get("LEDGER_DB", "data/ledger.db")
PORT = int(os.environ.get("PORT", "8001"))

# 请求体上限。四条端点里最大的是需求单（need_desc 2000 字），64 KiB 有二十倍余量；
# 再大就不是本协议的形状了，早拒早省内存。
MAX_BODY = 64 * 1024

# 单主体写入频率。**这不是安全边界**，只是一道刹车：没有它，一个脚本可以用一把
# 合法的钥把需求表刷成一片噪声，而清理噪声要人工。放在进程内存里，重启即清空——
# 故意不落库：一个能被自己刷满的计数器，落库只会变成第二种攻击面。
RATE_PER_MINUTE = 30

PARTY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
REQUEST_RE = re.compile(r"^rq_[0-9a-z]{8,32}$")
ENTRY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# DGB_ING_0xx → HTTP 状态。全服务只有这一张表；`signing` 与 `ledger_store` 只带码，
# 不带状态。同一个码在两条路径上回不同的状态，是这一层最容易犯的错，所以不给它机会。
STATUS = {
    "DGB_ING_001": 401,   # 缺签名材料 / 形状不对
    "DGB_ING_002": 401,   # 验签失败
    "DGB_ING_003": 401,   # 主体未登记公钥
    "DGB_ING_004": 401,   # 时间窗外
    "DGB_ING_005": 409,   # nonce 重放
    "DGB_ING_006": 400,   # 请求体不是 JSON 对象
    "DGB_ING_007": 404,   # 未知端点
    "DGB_ING_008": 400,   # 公钥形状非法
    "DGB_ING_009": 400,   # 字段缺失 / 形状不对
    "DGB_ING_010": 400,   # 不支持的 display_mode
    "DGB_ING_011": 403,   # 该状态或该类型不接受直写
    "DGB_ING_012": 409,   # 公钥已属另一主体
    "DGB_ING_014": 409,   # request_id 已存在
    "DGB_ING_015": 429,   # 太快了
    "DGB_ING_016": 422,   # 约束兜底
    "DGB_ING_017": 409,   # ID 冲突
    "DGB_ING_018": 400,   # 未知字段
    "DGB_ING_019": 400,   # 未知 rule_version
    "DGB_ING_020": 413,   # 请求体过大
    "DGB_ING_021": 411,   # 缺 Content-Length
}

# 需求单里允许 API 直写的状态。`closed` 要等双方签名与两条账目都落库——而那两件事
# 一发生，`closed` 就是**可判定的事实**，由 `confirm` 顺手写（`close_after_confirm`），
# 不由谁去「宣布」；`expired` 由窗口到期触发、也不是人工动作。这两条若开个口子，就等于
# 允许一个人宣布一件系统还没挣到的事，也能宣布一件已经挣到的事——接口上分不出这两种。
WRITABLE_STATES = ("open", "claimed", "delivered", "withdrawn")


def status_for(code: str) -> int:
    if code.startswith("DGB_LED_"):
        return ledger_store.LED_STATUS.get(code[-3:], 422)
    return STATUS.get(code, 400)


class TooFast(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


class RateLimiter:
    """每主体一分钟 N 次。滑动窗口，内存里，重启即清空。"""

    def __init__(self, limit: int = RATE_PER_MINUTE):
        self.limit = limit
        self.hits: dict[str, collections.deque] = {}
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits.setdefault(key, collections.deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.limit:
                raise TooFast(int(60 - (now - q[0])) + 1)
            q.append(now)
            if len(self.hits) > 4096:          # 防内存随主体数无限增长
                for k in [k for k, v in self.hits.items() if not v][:1024]:
                    self.hits.pop(k, None)


LIMITER = RateLimiter()


# ── 四条端点的语义 ───────────────────────────────────────────────────────────
def _require(data: dict, *keys: str) -> None:
    missing = [k for k in keys if data.get(k) in (None, "")]
    if missing:
        raise ledger_store.WriteError("DGB_ING_009", f"缺少字段：{', '.join(missing)}")


def _no_extra(data: dict, allowed) -> None:
    extra = sorted(set(data) - set(allowed))
    if extra:
        raise ledger_store.WriteError("DGB_ING_018", f"不认识的字段：{', '.join(extra)}")


def op_party(writer, party: str, data: dict, env: dict) -> dict:
    """登记公钥。签名已用请求体里自带的那把钥验过——这本身就是「持有私钥」的证明。"""
    _no_extra(data, ("party_id", "pubkey", "display_mode"))
    _require(data, "party_id", "pubkey")
    pid = data["party_id"]
    if not PARTY_RE.match(pid):
        raise ledger_store.WriteError("DGB_ING_009", "party_id 形状：1–64 位 [A-Za-z0-9_.:-]")
    if pid != party:
        # 用 A 的签名去登记 B 的公钥，会让「主体」与「持有者」脱钩。这一条必须自己挡，
        # 不靠调用方记得。
        raise ledger_store.WriteError("DGB_ING_009", "签名主体与 party_id 不一致")
    mode = data.get("display_mode", "pseudonymous")
    if mode != "pseudonymous":
        # 实名展示不是这个端点的事：它要 real_name_ref（脱敏串或外部指针），
        # 而那个值从公网接口走进来就会留痕。留在运维侧写库。
        raise ledger_store.WriteError("DGB_ING_010", "本端点只接受 pseudonymous")
    key_line, blob = signing.parse_pubkey(data["pubkey"])
    with writer.tx() as con:
        writer.spend_nonce(con, env["nonce"], party)
        res = writer.register_party(con, pid, key_line, mode)
    res.update({"party_id": pid, "key_fp": signing.fingerprint(blob)})
    return res


def op_request(writer, party: str, data: dict, env: dict) -> dict:
    _no_extra(data, ("request_id", "state", "category", "need_desc", "window_expires_at",
                     "requested_by", "claim_agent_id", "evidence_uri", "occurred_at", "note"))
    _require(data, "request_id", "state", "category", "need_desc", "requested_by")
    if not REQUEST_RE.match(data["request_id"]):
        raise ledger_store.WriteError("DGB_ING_009", "request_id 形状：rq_ + 8–32 位小写字母数字")
    state = data["state"]
    if state not in WRITABLE_STATES:
        raise ledger_store.WriteError(
            "DGB_ING_011",
            f"{state} 不接受直写：" + ("closed 要等双方签名与两条账目（第 04/05 步）"
                                       if state == "closed" else "expired 由窗口到期触发"))
    # 谁能推进哪一步。发布方管发布与撤回，认领方管认领与交付——不是「有钥就能写」。
    if state in ("open", "withdrawn"):
        if party != data["requested_by"]:
            raise ledger_store.WriteError("DGB_ING_011", f"{state} 只能由发布方（requested_by）提交")
    else:
        if not data.get("claim_agent_id"):
            raise ledger_store.WriteError("DGB_ING_009", f"{state} 必须带 claim_agent_id")
        if party != data["claim_agent_id"]:
            raise ledger_store.WriteError("DGB_ING_011", f"{state} 只能由认领方（claim_agent_id）提交")
    with writer.tx() as con:
        writer.spend_nonce(con, env["nonce"], party)
        if state == "delivered":
            # 交付这一次是**一个转换**，不是一行状态：它同时产出 give 与 receive 两条
            # 账目（第 05 步），并且与状态行在同一个事务里。分两步做就会留下「已交付但
            # 账上没东西」的中间态，而那个中间态没有任何人能修——delivered 不能重进。
            cur = writer.current_request(con, data["request_id"])
            if cur is not None and cur["state"] in ("delivered", "closed"):
                return writer.delivery_replay(con, data, cur)
            res = writer.append_request(con, data)
            res.update(writer.convert_delivery(con, data["request_id"]))
        else:
            res = writer.append_request(con, data)
    return res


def op_entry(writer, party: str, data: dict, env: dict) -> dict:
    kind = data.get("kind")
    if kind not in ("give", "receive", "payback"):
        raise ledger_store.WriteError("DGB_ING_009", "kind 必须是 give / receive / payback")
    if kind != "give":
        # receive 与 payback 没有主体列，只能通过 mutual_id 追到需求单上的认领方；
        # 而在 r6 里它们本来就该由 delivered 那一次转换当场生成。
        # 现在开直写，等于先给一条「没有主体也能进账」的路，之后再关掉就是改协议。
        raise ledger_store.WriteError(
            "DGB_ING_011", f"{kind} 由 delivered 那一次自动生成，不接受直写")
    _no_extra(data, ("kind", "rule_version") + ledger_store.GIVE_FIELDS)
    eid = data.get("give_id")
    if not eid or not ENTRY_ID_RE.match(str(eid)):
        raise ledger_store.WriteError("DGB_ING_009", "give_id 形状：1–64 位 [A-Za-z0-9_-]")
    if data.get("from_agent_id") != party:
        # 替别人记「他给过东西」不是本协议的动作：give 的给方就是签名者本人。
        raise ledger_store.WriteError("DGB_ING_011", "give 的 from_agent_id 必须就是签名主体")
    _require(data, "to_agent_id", "category", "occurred_at")
    with writer.tx() as con:
        writer.spend_nonce(con, env["nonce"], party)
        res = writer.append_entry(con, "give", data)
    return res


def op_confirm(writer, party: str, data: dict, env: dict) -> dict:
    """受方确认一条 give。**两个签名，两件事。**

    外层（信封）证明「这个请求是这主体发的」，已经被 `signing.verify` 验过；
    内层（`sig` 字段）证明「这个主体认可这条已经发生的事」。两者不能互相顶替：
    外层签的是请求体摘要，内层签的是从库里重算出来的 `entry_id + hash`。

    所以内层的载荷**绝不能用客户端交上来的值**——那样签名保护的是客户端自己写的那句话，
    而攻击者只要签一句「我认可 g_xxx + 我自己编的 hash」就能造出一条确认。
    """
    _no_extra(data, ("kind", "entry_id", "sig", "payload"))
    _require(data, "kind", "entry_id", "sig")
    kind = data["kind"]
    if kind != "give":
        # 这一条现在有确定的理由，不再是「等第 05 步」：一次交付的两条账目里，
        # give 由受方再签一次（本端点），receive 由认领方提交 delivered 时的那次
        # 外层签名推出来——两个主体各签过一次，两件事就都有人认了。
        # 给 receive 再开一次确认，签的还是同一句话，多出来的只是一个可以撒谎的重复。
        raise ledger_store.WriteError(
            "DGB_ING_011", f"{kind} 没有第二次确认这一档：它由 delivered 那一次推出来，"
                           f"而那次提交本身已经由认领方签过")
    eid = str(data["entry_id"])
    if not ENTRY_ID_RE.match(eid):
        raise ledger_store.WriteError("DGB_ING_009", "entry_id 形状：1–64 位 [A-Za-z0-9_-]")
    sig_text = data["sig"]
    if not isinstance(sig_text, str) or "BEGIN SSH SIGNATURE" not in sig_text:
        raise ledger_store.WriteError("DGB_ING_009", "sig 必须是 SSHSIG armor 全文")
    if len(sig_text) > 8192 or "\x00" in sig_text:
        raise ledger_store.WriteError("DGB_ING_009", "sig 超长或含 NUL")

    with writer.tx() as con:
        writer.spend_nonce(con, env["nonce"], party)
        entry_hash = writer.chain_hash_of(con, kind, eid)
        if entry_hash is None:
            raise ledger_store.WriteError("DGB_LED_030", f"条目 {kind}/{eid} 不存在")
        payload = signing.confirm_payload(eid, entry_hash)
        # 客户端可以带 payload 自检（它签的时候手里那段），但只能是「核对」，不是「采信」：
        # 与重算值差一个字节就拒，且库里存的是重算值。
        sent = data.get("payload")
        if sent is not None and str(sent).encode("utf-8") != payload:
            raise ledger_store.WriteError(
                "DGB_LED_034", "payload 与服务端按条目重算的值不一致（签错条目或签错 hash）")
        ok, out = signing.verify_detached(env["key_line"], party, sig_text, payload,
                                          signing.CONFIRM_NAMESPACE)
        if not ok:
            print(f"ingest: confirm verify failed {party} {kind}/{eid}: {out[:200]}", flush=True)
            raise ledger_store.WriteError(
                "DGB_LED_034", "确认签名验不过：载荷须为 entry_id 与该条目当前 hash")
        res = writer.insert_confirm(con, kind, eid, party, env["key_fp"],
                                    payload.decode("utf-8"), sig_text)
        # 确认落下之后，这张需求单就满足了 `closed`（双签齐、两条账目在链上）。
        # 关单不是第二个动作，是这一次确认的副产品——见 ledger_store.close_after_confirm。
        closed = writer.close_after_confirm(con, kind, eid)
    res.update({"entry_hash": entry_hash, "payload": payload.decode("utf-8")})
    if closed:
        res.update({"closed_request": closed})
    return res


ROUTES = {"/api/v1/party": op_party,
          "/api/v1/request": op_request,
          "/api/v1/entry": op_entry,
          "/api/v1/confirm": op_confirm}


def parse_body(body: bytes) -> dict:
    """请求体 → dict。**只在语义层用，不在验签前用。**

    2026-11-14 修：原先 do_POST 一进来就 `json.loads`，解析失败落进兜底的
    `except Exception`，回 500 internal_error。后果是「网络截断一个字节」
    看起来像「服务端坏了」——而正确的说法是「签名与请求体不符」（401 002）。
    签名保护的就是原始字节，字节不对第一件事是验签失败，不是 JSON 不合法。

    唯一的例外是 `/api/v1/party`：库里还没有这把钥，只能拿请求体里那把验，
    所以那一端必须先解析（见 do_POST）。
    """
    if not body:
        raise ledger_store.WriteError("DGB_ING_006", "请求体必须是 JSON 对象")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ledger_store.WriteError("DGB_ING_006", "请求体不是合法 JSON") from None
    if not isinstance(data, dict):
        raise ledger_store.WriteError("DGB_ING_006", "请求体必须是 JSON 对象")
    return data


def lookup_key(party_id: str):
    return ledger_store.pubkey_of(DB_PATH, party_id)


def preflight() -> list[str]:
    """启动前能查的都查一遍，缺什么一次说清。缺 ssh-keygen 时不要「启动成功但什么都写不进」。"""
    problems = []
    if shutil.which("ssh-keygen") is None:
        problems.append("找不到 ssh-keygen（验签依赖 openssh-client；镜像里必须装）")
    if not os.path.exists(DB_PATH):
        problems.append(f"账本库不存在：{DB_PATH}")
        return problems
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        have = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
    except sqlite3.Error as exc:
        problems.append(f"账本库打不开（{type(exc).__name__}: {exc}）")
        return problems
    for t in ("party", "request", "ledger_give", "ledger_receive", "ledger_payback",
              "entry_confirm", "ingest_nonce"):
        if t not in have:
            problems.append(f"库缺表 {t}——先跑 spec/ddl_w4.sql 与 spec/ddl_v1.4.sql")
    # 写得进去才算数。只查表存在的话，卷以只读挂入或宿主 uid 不对时，启动会「成功」，
    # 然后每一条写入都 500——而日志里只有一堆 traceback，看不出是权限。
    # `BEGIN IMMEDIATE` 拿一次写锁再回滚：不改一个字节，但确实证明了能写。
    try:
        con = sqlite3.connect(DB_PATH, timeout=5, isolation_level=None)
        con.execute("PRAGMA busy_timeout=5000")
        con.execute("BEGIN IMMEDIATE")
        con.execute("ROLLBACK")
        con.close()
    except sqlite3.Error as exc:
        problems.append(f"账本库不可写（{type(exc).__name__}: {exc}）"
                        "——卷是否以 rw 挂入？宿主目录是否 chown 999:999？")
    return problems


WRITER = ledger_store.Writer(DB_PATH)


class Handler(BaseHTTPRequestHandler):
    server_version = "drawcommons-ingest"

    timeout = 15

    # 写入面不回 HTML，所以 CSP 直接关到底：这个端口只吐 JSON。
    CSP = "default-src 'none'; frame-ancestors 'none'"

    def _send(self, code: int, payload: dict | bytes, ctype: str = "application/json; charset=utf-8",
              extra: dict | None = None) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(
            payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", self.CSP)
        for k, v in (extra or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, code: str, detail: str, endpoint: str) -> None:
        self._send(status_for(code), {"ok": False, "error": code,
                                      "detail": detail, "endpoint": endpoint})

    def _client_ip(self) -> str:
        headers = getattr(self, "headers", None)
        xff = headers.get("X-Forwarded-For", "") if headers else ""
        return xff.split(",")[0].strip() if xff else self.client_address[0]

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0].rstrip("/") == "/healthz":
            self._send(200, b"ok", "text/plain; charset=utf-8")
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        endpoint = path.rsplit("/", 1)[-1]
        op = ROUTES.get(path)
        if op is None:
            self._fail("DGB_ING_007", f"未知端点 {path}", endpoint)
            self.close_connection = True
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except (TypeError, ValueError):
            self._fail("DGB_ING_021", "必须带 Content-Length", endpoint)
            return
        if length > MAX_BODY:
            # 不读也不留连接：读掉一个 10MB 的体只是为了扔掉它，等于替攻击者做带宽。
            self._fail("DGB_ING_020", f"请求体上限 {MAX_BODY} 字节", endpoint)
            self.close_connection = True
            return
        body = self.rfile.read(length) if length else b""

        try:
            # 顺序：先验签，再解析语义。唯一的例外是登记主体——那一端库里还没有
            # 这把钥，只能拿请求体里自带的那把验，所以必须先解析（且只解析一次）。
            if op is op_party:
                data = parse_body(body)
                # 缺 pubkey 要先报「字段缺失」而不是「主体未登记」——后者会让人以为
                # 是授权问题，其实是请求写漏了一行。
                if not data.get("pubkey"):
                    raise ledger_store.WriteError("DGB_ING_009", "缺少字段：pubkey")
                hint = data["pubkey"]
            else:
                data = None
                hint = None
            party, key_fp, env = signing.verify(
                self.headers, "POST", path, body, lookup_key, hint_pubkey=hint)
            if data is None:
                data = parse_body(body)
            LIMITER.check(party)
            res = op(WRITER, party, data, env)
            res.update({"ok": True, "endpoint": endpoint, "party": party, "key_fp": key_fp})
            self._send(200, res)
            print(f"ingest ok {endpoint} party={party} {self._client_ip()}", flush=True)
        except TooFast as exc:
            self._send(429, {"ok": False, "error": "DGB_ING_015",
                             "detail": "一分钟内写得太多，稍后再试", "endpoint": endpoint},
                       extra={"Retry-After": exc.retry_after})
        except signing.AuthError as exc:
            self._fail(exc.code, exc.detail, endpoint)
        except ledger_store.WriteError as exc:
            self._fail(exc.code, exc.detail, endpoint)
        except sqlite3.Error as exc:
            # 库层的意外不把 SQL 原文回给调用方：里面有表名与列名。
            print("ingest sqlite error: " + traceback.format_exc(), flush=True)
            self._fail("DGB_ING_016", f"数据库拒绝：{type(exc).__name__}", endpoint)
        except Exception:                      # noqa: BLE001
            print("ingest internal error: " + traceback.format_exc(), flush=True)
            self._send(500, {"ok": False, "error": "internal_error", "endpoint": endpoint})

    def do_HEAD(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0].rstrip("/") == "/healthz":
            self._send(200, b"", "text/plain; charset=utf-8")
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def do_PUT(self) -> None:  # noqa: N802
        self._send(405, {"ok": False, "error": "method_not_allowed"})

    do_PATCH = do_PUT
    do_DELETE = do_PUT

    def log_message(self, fmt, *args):
        # 默认实现把整行请求写进 stderr，含路径与状态；这里安静一点，
        # 成功与失败各在上面显式打一行（含主体，方便追「谁在写」）。
        if "/healthz" in (fmt % args):
            return
        super().log_message(fmt, *args)


def main() -> int:
    problems = preflight()
    if problems:
        print("ingest 拒绝启动：", flush=True)
        for p in problems:
            print("  · " + p, flush=True)
        return 2
    print(f"ingest: db={DB_PATH}  endpoints={' '.join(sorted(ROUTES))}  "
          f"namespace={signing.NAMESPACE}", flush=True)
    print(f"ingest: ssh-keygen={shutil.which('ssh-keygen')}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
