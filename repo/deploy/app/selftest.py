#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""写入面自测。第 03 步的四条出口判据，一条一条跑给你看。

    python3 repo/deploy/app/selftest.py

判据（与 `_ops/排期 v2.7` 的 03 行一致）：

  1. 未签 → 4xx
  2. 改一字节 → 4xx
  3. 重放被拒
  4. 三处共用同一验签实现（不是三份拷贝）

第 04 步加了一节（§7 确认层），第 05 步又加了一节（§9 入账转换）：一次 `delivered`
恰好两条账目、重发幂等、换凭据被拒、确认之后单子关掉。§8 是闸门与上限，编号保留原位。

**客户端这一侧刻意不复用服务端的 `build_payload`。** 复用的话，这个测试只能证明
「同一个函数被调了两次」；载荷的字节形状是写在 `spec/ingest.md` 里的对外约定，
所以这里按那份文档的字面重新拼一遍，再与实现比一次。两边一起改错才会同时通过，
只改一边必然红。

依赖：`ssh-keygen`（OpenSSH 8.0+）、Python 3.10+、仓库内的 `evidence/build_ledger.py`
（用来造一个干净的库）。全部标准库，不装任何包。本文件不进镜像。
"""

from __future__ import annotations

import ast
import base64
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
# HERE = <root>/repo/deploy/app → ROOT = <root>（evidence/ 在那一层）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))

TAG = "drawcommons-ingest-v1"
NAMESPACE = "drawcommons-ingest"

# 结构性检查只看进镜像的那几个文件。selftest 自己也会调 `ssh-keygen -Y sign`，
# 把它算进来等于让「只有一处验签」这条判据永远数到 2。
RUNTIME_MODULES = ("signing.py", "ingest.py", "ledger_store.py", "app.py")


# ── 极简测试台 ───────────────────────────────────────────────────────────────
class Tally:
    def __init__(self):
        self.ok = 0
        self.bad = 0

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.ok += 1
            print(f"  ✅ {name}")
        else:
            self.bad += 1
            print(f"  ❌ {name}" + (f"   [{detail}]" if detail else ""))

    def section(self, title: str) -> None:
        print()
        print(title)
        print("-" * 60)


T = Tally()


# ── 按 spec 字面拼载荷（不复用服务端实现）──────────────────────────────────
def spec_payload(method: str, path: str, party: str, issued: str, nonce: str,
                 body: bytes) -> bytes:
    """`spec/ingest.md` §3 逐字拼出来的载荷。这是「文档即约定」的那一侧。"""
    return (TAG + "\n" + method + "\n" + path + "\n" + party + "\n" + issued + "\n"
            + nonce + "\n" + hashlib.sha256(body).hexdigest() + "\n").encode("utf-8")


def ssh_sign(payload: bytes, key_path: str, namespace: str = NAMESPACE) -> str:
    p = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", key_path, "-n", namespace, "-"],
                       input=payload, capture_output=True, timeout=20)
    if p.returncode != 0:
        raise RuntimeError("ssh-keygen -Y sign 失败：" + p.stderr.decode(errors="replace"))
    return p.stdout.decode("utf-8")


def now_iso(offset_seconds: int = 0) -> str:
    dt = (datetime.datetime.now(datetime.timezone.utc)
          + datetime.timedelta(seconds=offset_seconds))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def nonce() -> str:
    return base64.urlsafe_b64encode(uuid.uuid4().bytes).decode().rstrip("=")


def jbody(obj) -> bytes:
    """客户端自己的序列化：紧凑、键序按插入顺序。服务端不重排，所以它无所谓。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Client:
    """会签名的 HTTP 客户端。签名所需的私钥由临时目录里的 ssh-keygen 生成。"""

    def __init__(self, base: str, key_path: str, party: str):
        self.base = base
        self.key_path = key_path
        self.party = party

    def headers_for(self, path: str, body: bytes, *, party: str | None = None,
                    issued: str | None = None, nce: str | None = None,
                    sign_path: str | None = None, namespace: str = NAMESPACE) -> dict:
        party = party or self.party
        issued = issued or now_iso()
        nce = nce or nonce()
        payload = spec_payload("POST", sign_path or path, party, issued, nce, body)
        sig = ssh_sign(payload, self.key_path, namespace)
        return {"X-DG-Party": party, "X-DG-Issued": issued, "X-DG-Nonce": nce,
                "X-DG-Sig": base64.b64encode(sig.encode()).decode()}

    def send(self, path: str, body: bytes, *, tamper: bytes | None = None, **kw):
        hdrs = self.headers_for(path, body, **kw)
        hdrs["Content-Type"] = "application/json"
        return self.raw(path, body if tamper is None else tamper, hdrs)

    def raw(self, path: str, body: bytes, hdrs: dict):
        req = urllib.request.Request(self.base + path, data=body, method="POST", headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raw = e.read() or b"{}"
            try:
                return e.code, json.loads(raw)
            except json.JSONDecodeError:
                return e.code, {"raw": raw.decode("utf-8", "replace")}


# ── 环境准备 ─────────────────────────────────────────────────────────────────
def build_db(tmp: str) -> str:
    db = os.path.join(tmp, "ledger.db")
    script = os.path.join(ROOT, "evidence", "build_ledger.py")
    if not os.path.exists(script):
        raise SystemExit(f"找不到 {script}——自测需要一个由 DDL 造出来的干净库")
    p = subprocess.run([sys.executable, script, "--db", db],
                       capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise SystemExit("build_ledger 失败：\n" + p.stdout + p.stderr)
    return db


def make_key(tmp: str, name: str) -> tuple[str, str]:
    path = os.path.join(tmp, name)
    p = subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-C", f"selftest-{name}",
                        "-f", path, "-q"], capture_output=True, timeout=20)
    if p.returncode != 0:
        raise SystemExit("ssh-keygen 生成密钥失败：" + p.stderr.decode(errors="replace"))
    with open(path + ".pub", encoding="utf-8") as fh:
        return path, fh.read().strip()


# ── 结构性证明：验签实现只有一处 ────────────────────────────────────────────
def scan_sites() -> dict:
    """扫进镜像的那几个 .py。

    静态一侧要回答三个问题，每个都对应一种「多写一份」的方式：
      · `ssh-keygen -Y verify` 有几个调用点？（`_ssh_verify` 只能有一个）
      · 谁 import 了 subprocess？（只有 signing.py 该有）
      · `signing.verify` 在 ingest.py 里被调了几次？（所有端点只能共用一个出口）
    """
    verify_calls, subproc_imports, funnel, read_funnel = [], [], 0, 0
    for fn in RUNTIME_MODULES:
        path = os.path.join(HERE, fn)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name == "subprocess" for a in node.names):
                    subproc_imports.append(fn)
            elif isinstance(node, ast.ImportFrom):
                if node.module == "subprocess":
                    subproc_imports.append(fn)
            elif isinstance(node, ast.Call):
                f = node.func
                if (isinstance(f, ast.Attribute) and f.attr == "run"
                        and isinstance(f.value, ast.Name) and f.value.id == "subprocess"
                        and node.args and isinstance(node.args[0], ast.List)):
                    lits = [n.value for n in node.args[0].elts if isinstance(n, ast.Constant)]
                    if "-Y" in lits:
                        verify_calls.append(f"{fn}:{node.lineno}")
                if (isinstance(f, ast.Attribute) and f.attr == "verify"
                        and isinstance(f.value, ast.Name) and f.value.id == "signing"):
                    funnel += 1
                # 读口（v1.7）：只允许一个调用点，且它走 `verify_read` 这层固定参数
                # 转发——读口不能自己拼 method/body，否则就是绕过写口校验的旁路。
                if (isinstance(f, ast.Attribute) and f.attr == "verify_read"
                        and isinstance(f.value, ast.Name) and f.value.id == "signing"):
                    read_funnel += 1
    return {"verify_calls": verify_calls,
            "subproc_imports": sorted(set(subproc_imports)),
            "funnel": funnel, "read_funnel": read_funnel}


# ── 主流程 ───────────────────────────────────────────────────────────────────
def main() -> int:
    if shutil.which("ssh-keygen") is None:
        raise SystemExit("缺 ssh-keygen：装 openssh-client 再跑")

    tmp = tempfile.mkdtemp(prefix="dg-ingest-selftest-")
    srv = None
    try:
        db = build_db(tmp)
        os.environ["LEDGER_DB"] = db
        sys.path.insert(0, HERE)
        import ingest          # noqa: E402  （必须先设好 LEDGER_DB）
        import ledger_hash     # noqa: E402
        import ledger_store    # noqa: E402
        import signing         # noqa: E402

        from http.server import ThreadingHTTPServer
        srv = ThreadingHTTPServer(("127.0.0.1", 0), ingest.Handler)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        threading.Thread(target=srv.serve_forever, daemon=True).start()

        key_a, pub_a = make_key(tmp, "a")
        key_b, pub_b = make_key(tmp, "b")
        alice = Client(base, key_a, "pt_alice")
        mallory = Client(base, key_b, "pt_mallory")

        T.section("0. 载荷：文档字面 vs 实现")
        impl = signing.build_payload("POST", "/api/v1/party", "pt_x",
                                     "2026-11-14T00:00:00Z", "A" * 22, b'{"a":1}')
        want = spec_payload("POST", "/api/v1/party", "pt_x",
                            "2026-11-14T00:00:00Z", "A" * 22, b'{"a":1}')
        T.check("spec/ingest.md 的载荷 == signing.build_payload 的载荷", impl == want,
                f"{impl!r} != {want!r}")
        T.check("载荷含路径（换端点即失效）", b"/api/v1/party" in impl)
        T.check("载荷含请求体摘要（改一字节即失效）",
                hashlib.sha256(b'{"a":1}').hexdigest().encode() in impl)

        T.section("1. 未签 / 签名不完整 → 4xx")
        party_body = jbody({"party_id": "pt_alice", "pubkey": pub_a})
        st, r = alice.raw("/api/v1/party", party_body, {"Content-Type": "application/json"})
        T.check("完全没有签名头 → 401 DGB_ING_001",
                st == 401 and r.get("error") == "DGB_ING_001", f"{st} {r}")
        st, r = alice.send("/api/v1/party", party_body)
        T.check("（对照）完整签名 → 200", st == 200, f"{st} {r}")
        T.check("返回的指纹与 ssh-keygen -lf 一致",
                r.get("key_fp") == local_fp(pub_a), f"{r.get('key_fp')} vs {local_fp(pub_a)}")
        st, r = mallory.send("/api/v1/party", jbody({"party_id": "pt_mallory",
                                                     "pubkey": pub_b}))
        T.check("第二个主体登记 → 200", st == 200, f"{st} {r}")

        probe_body = jbody({"request_id": "rq_probe001", "state": "open",
                            "category": "compute", "need_desc": "探针",
                            "requested_by": "pt_alice"})
        for miss in ("X-DG-Party", "X-DG-Issued", "X-DG-Nonce", "X-DG-Sig"):
            hdrs = alice.headers_for("/api/v1/request", probe_body)
            hdrs["Content-Type"] = "application/json"
            del hdrs[miss]
            st, r = alice.raw("/api/v1/request", probe_body, hdrs)
            T.check(f"缺 {miss} → 401 DGB_ING_001",
                    st == 401 and r.get("error") == "DGB_ING_001", f"{st} {r}")

        T.section("2. 改一字节 → 4xx")
        need = {"request_id": "rq_selftest01", "state": "open", "category": "compute",
                "need_desc": "需要 2 小时 CPU 跑一次回归", "requested_by": "pt_alice"}
        good_body = jbody(need)
        st, r = alice.send("/api/v1/request", good_body)
        T.check("（对照）原样 → 200 且 seq=1", st == 200 and r.get("seq") == 1, f"{st} {r}")
        tampered = good_body.replace("2 小时".encode(), "3 小时".encode())
        T.check("改的是真的一个字符", tampered != good_body
                and len(tampered) == len(good_body))
        st, r = alice.send("/api/v1/request", good_body, tamper=tampered)
        T.check("改一字节 → 401 DGB_ING_002",
                st == 401 and r.get("error") == "DGB_ING_002", f"{st} {r}")
        st, r = alice.send("/api/v1/request", good_body, sign_path="/api/v1/entry")
        T.check("换端点（签名路径不符）→ 401 DGB_ING_002",
                st == 401 and r.get("error") == "DGB_ING_002", f"{st} {r}")
        st, r = mallory.send("/api/v1/request", good_body, party="pt_alice")
        T.check("别人的钥冒名 → 401 DGB_ING_002",
                st == 401 and r.get("error") == "DGB_ING_002", f"{st} {r}")
        st, r = alice.send("/api/v1/request", good_body, namespace="git")
        T.check("namespace=git 的签名被拒（域隔离由容器保证）",
                st == 401 and r.get("error") == "DGB_ING_002", f"{st} {r}")
        st, r = alice.send("/api/v1/request", good_body, issued=now_iso(-3600))
        T.check("一小时前的签名 → 401 DGB_ING_004",
                st == 401 and r.get("error") == "DGB_ING_004", f"{st} {r}")
        st, r = alice.send("/api/v1/request", good_body, party="pt_ghost")
        T.check("未登记公钥的主体 → 401 DGB_ING_003",
                st == 401 and r.get("error") == "DGB_ING_003", f"{st} {r}")

        T.section("3. 重放被拒")
        third = jbody({"request_id": "rq_selftest03", "state": "open", "category": "docs",
                       "need_desc": "重放用的单", "requested_by": "pt_alice"})
        once = nonce()
        st, r = alice.send("/api/v1/request", third, nce=once)
        T.check("（对照）新 nonce → 200", st == 200, f"{st} {r}")
        signed_once = alice.headers_for("/api/v1/request", third, nce=once)
        signed_once["Content-Type"] = "application/json"
        st, r = alice.raw("/api/v1/request", third, signed_once)
        T.check("同一份签名原样重放 → 409 DGB_ING_005",
                st == 409 and r.get("error") == "DGB_ING_005", f"{st} {r}")
        st, r = alice.send("/api/v1/request", third, nce=once)
        T.check("同一 nonce 重签再发 → 也是 409 DGB_ING_005",
                st == 409 and r.get("error") == "DGB_ING_005", f"{st} {r}")
        st, r = alice.send("/api/v1/request", jbody(dict(need, request_id="rq_selftest01")))
        T.check("同一 request_id 再发一次 open → 422 DGB_LED_020（open 只能是第 1 行）",
                st == 422 and r.get("error") == "DGB_LED_020", f"{st} {r}")

        T.section("4. 语义与状态机（写进去了才算通路打通）")
        st, r = alice.send("/api/v1/request", jbody({
            "request_id": "rq_selftest02", "state": "open", "category": "compute",
            "need_desc": "替别人发单", "requested_by": "pt_mallory"}))
        T.check("发布方不是签名者 → 403 DGB_ING_011",
                st == 403 and r.get("error") == "DGB_ING_011", f"{st} {r}")
        st, r = mallory.send("/api/v1/request", jbody({
            "request_id": "rq_selftest02", "state": "closed", "category": "compute",
            "need_desc": "直接宣布关闭", "requested_by": "pt_mallory"}))
        T.check("直接写 closed → 403 DGB_ING_011",
                st == 403 and r.get("error") == "DGB_ING_011", f"{st} {r}")
        st, r = mallory.send("/api/v1/request", jbody({
            "request_id": "rq_selftest02", "state": "claimed", "category": "compute",
            "need_desc": "认领但不写认领方", "requested_by": "pt_mallory"}))
        T.check("claimed 缺 claim_agent_id → 400 DGB_ING_009",
                st == 400 and r.get("error") == "DGB_ING_009", f"{st} {r}")
        st, r = mallory.send("/api/v1/request", jbody({
            "request_id": "rq_selftest04", "state": "open", "category": "compute",
            "need_desc": "带一个不存在的字段", "requested_by": "pt_mallory",
            "amount_fen": 1}))
        T.check("带未定义字段 → 400 DGB_ING_018",
                st == 400 and r.get("error") == "DGB_ING_018", f"{st} {r}")
        st, r = mallory.send("/api/v1/request", jbody({
            "request_id": "rq_selftest05", "state": "open", "category": "compute",
            "need_desc": "认领自己发单", "requested_by": "pt_mallory",
            "claim_agent_id": "pt_mallory"}))
        T.check("open 带 claim_agent_id（第 1 行只能是 open 本身）→ 200 或 422",
                st in (200, 422), f"{st} {r}")

        T.section("4b. 自认领：发布方不能成为自己单子的认领方")
        # 为什么要在**认领那一刻**拦，而不是等交付时让 `trg_ledger_give_not_self`
        # （DGB_LED_033）兜：兜出来的是「服务端缺陷」，对提交的人没有解释力；而当
        # 「自己发自己接」真的交付成功，账本里就多一条**没有真实互助**的撮合记录，
        # 账本只增不改，那条记录永久留着，污染的是它自己声称的信誉。
        # 清一次限流计数：本节连发四条，测的是归属，不是速率。
        with ingest.LIMITER.lock:
            ingest.LIMITER.hits.clear()

        def _cur(rid):
            con = sqlite3.connect(db)
            try:
                return con.execute("SELECT state, claim_agent_id FROM v_request_current"
                                   " WHERE request_id=?", (rid,)).fetchone()
            finally:
                con.close()

        own = {"request_id": "rq_selfclaim1", "state": "open", "category": "compute",
               "need_desc": "发布方想自己把这张单认下来", "requested_by": "pt_alice"}
        st, r = alice.send("/api/v1/request", jbody(own))
        T.check("（前置）发布方发布一张单 → 200", st == 200, f"{st} {r}")
        st, r = alice.send("/api/v1/request", jbody(dict(own, state="claimed",
                                                        claim_agent_id="pt_alice")))
        T.check("发布方认领自己的单 → 400 DGB_ING_022",
                st == 400 and r.get("error") == "DGB_ING_022", f"{st} {r}")
        now_row = _cur("rq_selfclaim1")
        T.check("被拒之后这张单仍是 open、认领方为空（没留下半个认领）",
                now_row is not None and now_row[0] == "open" and not now_row[1],
                str(now_row))
        st, r = mallory.send("/api/v1/request", jbody(dict(own, state="claimed",
                                                          claim_agent_id="pt_mallory")))
        after = _cur("rq_selfclaim1")
        T.check("（反证）换一把钥匙认领同一张单 → 200，认领方变成 pt_mallory"
                "（只拦自己，不拦别人）",
                st == 200 and after is not None and after[0] == "claimed"
                and after[1] == "pt_mallory", f"{st} {r} / {after}")

        T.section("5. 三处共用同一验签实现")
        scan = scan_sites()
        T.check("`ssh-keygen -Y verify` 调用点恰好 1 处", len(scan["verify_calls"]) == 1,
                str(scan["verify_calls"]))
        T.check("该调用点在 signing.py",
                len(scan["verify_calls"]) == 1
                and scan["verify_calls"][0].startswith("signing.py"),
                str(scan["verify_calls"]))
        T.check("只有 signing.py 导入 subprocess", scan["subproc_imports"] == ["signing.py"],
                str(scan["subproc_imports"]))
        T.check("ingest.py 里 `signing.verify(...)` 只有 1 个调用点（全部写端点共用）",
                scan["funnel"] == 1, f"funnel={scan['funnel']}")
        T.check("读口只经 `verify_read` 一个转发点（不能自带 method/body）",
                scan["read_funnel"] == 1, f"read_funnel={scan['read_funnel']}")
        T.check("路由表恰好 6 条，都指向同一条通路的语义函数",
                len(ingest.ROUTES) == 6 and set(ingest.ROUTES) == {
                    "/api/v1/party", "/api/v1/request", "/api/v1/entry",
                    "/api/v1/confirm", "/api/v1/reject", "/api/v1/remind"},
                str(list(ingest.ROUTES)))
        original = signing.verify

        def boom(*a, **k):
            raise signing.AuthError("DGB_ING_002", "被测试替换")

        signing.verify = boom
        try:
            probes = {
                "/api/v1/party": jbody({"party_id": "pt_alice", "pubkey": pub_a}),
                "/api/v1/request": third,
                "/api/v1/entry": jbody({"kind": "give", "give_id": "g_probe_1",
                                        "from_agent_id": "pt_alice", "to_agent_id": "pt_bob",
                                        "category": "compute", "occurred_at": now_iso()}),
                "/api/v1/confirm": jbody({"kind": "give", "entry_id": "g_probe_1",
                                          "sig": "-----BEGIN SSH SIGNATURE-----\n"}),
                "/api/v1/reject": jbody({"request_id": "rq_probe000001", "seq": 2,
                                         "sig": "-----BEGIN SSH SIGNATURE-----\n"}),
                "/api/v1/remind": jbody({"request_id": "rq_probe000001", "seq": 2,
                                         "sig": "-----BEGIN SSH SIGNATURE-----\n"}),
            }
            results = {p: alice.send(p, b)[:2] for p, b in probes.items()}
            allfail = all(st == 401 and r.get("error") == "DGB_ING_002"
                          for st, r in results.values())
            T.check("替换唯一实现后，六条端点全部 401 DGB_ING_002（6/6）", allfail,
                    str(results))
        finally:
            signing.verify = original

        T.section("6. 条目真的进链了")
        give = {"kind": "give", "give_id": "g_selftest_1", "mutual_id": None,
                "from_agent_id": "pt_alice", "to_agent_id": "pt_bob",
                "category": "compute", "quantity": 2, "unit": "hour",
                "occurred_at": now_iso(-60), "note": "自测条目"}
        st, r = alice.send("/api/v1/entry", jbody(give))
        T.check("give → 200 且返回 64 位 hash",
                st == 200 and len(str(r.get("hash"))) == 64, f"{st} {r}")
        returned = r.get("hash")
        entries = ledger_store.load_entries(db)
        chain = ledger_hash.build_chain(entries)
        ok_chain, bad_at = ledger_hash.verify_chain(chain)
        hit = [e for e in chain if e["type"] == "give" and e.get("entry_id") == "g_selftest_1"]
        T.check("链自洽（verify_chain 通过）", ok_chain, f"first_bad={bad_at}")
        T.check("接口返回的 hash == 独立重算的 hash",
                bool(hit) and hit[0]["hash"] == returned,
                f"{hit and hit[0]['hash']} vs {returned}")
        T.check("条目带 occurred_at（r6 起三类条目都有时间列）",
                bool(hit) and bool(hit[0].get("occurred_at")), str(hit and hit[0]))
        T.check("scope 由 mutual_id 推出（无 mutual_id → NULL + unresolved）",
                bool(hit) and hit[0].get("scope") is None
                and hit[0].get("scope_unresolved") == 1, str(hit and hit[0].get("scope")))
        st, r = alice.send("/api/v1/entry", jbody(dict(give, mutual_id="ghost")))
        T.check("mutual_id='ghost' → 422 DGB_LED_027（DDL 从接口这层也拦得住）",
                st == 422 and r.get("error") == "DGB_LED_027", f"{st} {r}")
        st, r = alice.send("/api/v1/entry", jbody(dict(give, kind="receive",
                                                       receive_id="r_x1",
                                                       occurred_at=now_iso())))
        T.check("receive 直写 → 403 DGB_ING_011（由 delivered 转换生成，第 05 步）",
                st == 403 and r.get("error") == "DGB_ING_011", f"{st} {r}")
        st, r = alice.send("/api/v1/entry", jbody(dict(give, give_id="g_selftest_2",
                                                       from_agent_id="pt_bob")))
        T.check("替别人记 give → 403 DGB_ING_011",
                st == 403 and r.get("error") == "DGB_ING_011", f"{st} {r}")
        st, r = alice.send("/api/v1/entry", jbody(dict(give, give_id="g_selftest_3",
                                                       to_agent_id="pt_alice")))
        T.check("给方=受方 → 422 DGB_LED_033",
                st == 422 and r.get("error") == "DGB_LED_033", f"{st} {r}")

        T.section("7. 确认层：受方对条目第二段签名（第 04 步）")
        # 前面几节已经用掉大半限额（默认 30 次/分钟/主体）。本节测的是确认层，不是限流，
        # 先清一次计数——否则「受方确认 → 200」会因为前面的用例而偶发 429，
        # 而那种失败看起来像「确认功能坏了」。
        with ingest.LIMITER.lock:
            ingest.LIMITER.hits.clear()
        # 客户端按 `spec/ingest.md` §6 的字面重新拼一遍，不复用 signing.confirm_payload：
        # 载荷形状是对外约定，两边一起改错才会同时通过，只改一边必然有一条红。
        def spec_confirm_payload(eid: str, h: str) -> bytes:
            return ("drawcommons-confirm-v1\n" + eid + "\n" + h + "\n").encode("utf-8")

        mk = {"kind": "give", "give_id": "g_confirm_1", "mutual_id": None,
              "from_agent_id": "pt_alice", "to_agent_id": "pt_mallory",
              "category": "compute", "quantity": 1, "unit": "hour",
              "occurred_at": now_iso(-120), "note": "确认层自测"}
        st, r = alice.send("/api/v1/entry", jbody(mk))
        h1 = r.get("hash")
        T.check("（准备）给方记一条 give 给受方 → 200", st == 200 and len(str(h1)) == 64,
                f"{st} {r}")
        # 基线必须在这一刻拍：**插入条目本身**会改变它之后那些条目的 prev_hash，
        # 因此「确认前后 hash 不变」只有在「条目已落库、确认未落库」这个窗口里才可判。
        # 在插入之前拍基线，测的是「插入没有改 hash」——而那件事本来就不成立。
        base_chain = ledger_hash.build_chain(ledger_store.load_entries(db))
        base_hashes = {e["entry_id"]: e["hash"] for e in base_chain}

        good_sig = ssh_sign(spec_confirm_payload("g_confirm_1", h1), key_b,
                            namespace="drawcommons-confirm")
        st, r = mallory.send("/api/v1/confirm",
                             jbody({"kind": "give", "entry_id": "g_confirm_1",
                                    "sig": good_sig, "payload": spec_confirm_payload(
                                        "g_confirm_1", h1).decode()}))
        T.check("受方确认 → 200 且返回的 entry_hash 与链上一致",
                st == 200 and r.get("entry_hash") == h1, f"{st} {r}")
        T.check("返回的 payload 就是三行规范载荷（服务端重算的那一份）",
                r.get("payload") == "drawcommons-confirm-v1\ng_confirm_1\n" + h1 + "\n",
                repr(r.get("payload"))[:120])

        after = ledger_hash.build_chain(ledger_store.load_entries(db))
        T.check("确认没有改动条目数", len(after) == len(base_chain),
                f"{len(base_chain)} → {len(after)}")
        T.check("确认没有改动任何既有条目的 hash（逐条比对）",
                all(e["hash"] == base_hashes[e["entry_id"]] for e in after),
                str([e["entry_id"] for e in after
                     if e["hash"] != base_hashes.get(e["entry_id"])]))
        T.check("链仍自洽（verify_chain 通过）", ledger_hash.verify_chain(after)[0],
                str(ledger_hash.verify_chain(after)[1]))
        hist = [e for e in after if e.get("entry_id") == "g_confirm_1"]
        T.check("条目本身的 verifiability 没被改写（仍是 self_reported）",
                bool(hist) and hist[0].get("verifiability") == "self_reported",
                str(hist and hist[0].get("verifiability")))

        confs = ledger_store.load_confirmations(db)
        row = [c for c in confs if c["entry_id"] == "g_confirm_1"]
        T.check("entry_confirm 落了一行", len(row) == 1, str(confs))
        T.check("确认里带 pubkey，且 key_fp 与它相符（第三方不必回头问运营方）",
                bool(row) and row[0]["pubkey"].startswith("ssh-ed25519 ")
                and row[0]["key_fp"] == local_fp(row[0]["pubkey"]),
                str(row and (row[0]["key_fp"], row[0]["pubkey"][:30])))
        T.check("key_fp 是受方那把钥，不是给方的",
                bool(row) and row[0]["key_fp"] == local_fp(pub_b), str(row and row[0]["key_fp"]))

        st, r = mallory.send("/api/v1/confirm",
                             jbody({"kind": "give", "entry_id": "g_confirm_1",
                                    "sig": good_sig}))
        T.check("同一条目再确认一次 → 409 DGB_LED_035（一条目一确认，不覆盖）",
                st == 409 and r.get("error") == "DGB_LED_035", f"{st} {r}")

        mk2 = dict(mk, give_id="g_confirm_2")
        st, r = alice.send("/api/v1/entry", jbody(mk2))
        h2 = r.get("hash")
        T.check("（准备）第二条 give → 200", st == 200, f"{st} {r}")
        self_sig = ssh_sign(spec_confirm_payload("g_confirm_2", h2), key_a,
                            namespace="drawcommons-confirm")
        st, r = alice.send("/api/v1/confirm",
                           jbody({"kind": "give", "entry_id": "g_confirm_2",
                                  "sig": self_sig}))
        T.check("给方自签 → 422 DGB_LED_031（自己说两遍不叫两个人各说一遍）",
                st == 422 and r.get("error") == "DGB_LED_031", f"{st} {r}")

        wrong = ssh_sign(spec_confirm_payload("g_confirm_2", "0" * 64), key_b,
                         namespace="drawcommons-confirm")
        st, r = mallory.send("/api/v1/confirm",
                             jbody({"kind": "give", "entry_id": "g_confirm_2", "sig": wrong}))
        T.check("签的是自造 hash → 400 DGB_LED_034（载荷以库里重算为准）",
                st == 400 and r.get("error") == "DGB_LED_034", f"{st} {r}")

        ingest_ns_sig = ssh_sign(spec_confirm_payload("g_confirm_2", h2), key_b,
                                 namespace="drawcommons-ingest")
        st, r = mallory.send("/api/v1/confirm",
                             jbody({"kind": "give", "entry_id": "g_confirm_2",
                                    "sig": ingest_ns_sig}))
        T.check("拿写入面域的签名当确认 → 400 DGB_LED_034（域隔离由容器保证）",
                st == 400 and r.get("error") == "DGB_LED_034", f"{st} {r}")

        ok_sig2 = ssh_sign(spec_confirm_payload("g_confirm_2", h2), key_b,
                           namespace="drawcommons-confirm")
        st, r = mallory.send("/api/v1/confirm",
                             jbody({"kind": "give", "entry_id": "g_confirm_2",
                                    "sig": ok_sig2,
                                    "payload": "drawcommons-confirm-v1\ng_confirm_2\n" + "0" * 64 + "\n"}))
        T.check("payload 与服务端重算不等 → 400 DGB_LED_034",
                st == 400 and r.get("error") == "DGB_LED_034", f"{st} {r}")

        st, r = mallory.send("/api/v1/confirm",
                             jbody({"kind": "give", "entry_id": "g_no_such", "sig": ok_sig2}))
        T.check("条目不存在 → 422 DGB_LED_030",
                st == 422 and r.get("error") == "DGB_LED_030", f"{st} {r}")
        st, r = mallory.send("/api/v1/confirm",
                             jbody({"kind": "receive", "entry_id": "r_whatever",
                                    "sig": ok_sig2}))
        T.check("kind=receive 的确认 → 403 DGB_ING_011（属第 05 步的转换）",
                st == 403 and r.get("error") == "DGB_ING_011", f"{st} {r}")
        st, r = mallory.send("/api/v1/confirm",
                             jbody({"kind": "give", "entry_id": "g_confirm_2",
                                    "sig": ok_sig2, "party_id": "pt_alice"}))
        T.check("自带 party_id → 400 DGB_ING_018（确认人只取签名主体）",
                st == 400 and r.get("error") == "DGB_ING_018", f"{st} {r}")

        # 导出件是第三方唯一拿到的东西，所以「确认有没有进导出件、进成什么形状」
        # 必须由判据看住，而不是靠读代码相信。
        import app as public_app      # noqa: E402  （LEDGER_DB 已在上面设好）
        ex = json.loads(public_app.LEDGER.export_bytes)
        T.check("导出件顶层四个键：confirmations 与 items 并列",
                sorted(ex) == ["confirmations", "data_notice", "genesis", "items"],
                str(sorted(ex)))
        want_keys = {"kind", "entry_id", "party_id", "key_fp", "pubkey", "sig", "signed_at"}
        T.check("确认条目的字段集固定（带 pubkey；不带 payload / entry_hash）",
                len(ex["confirmations"]) == 1
                and set(ex["confirmations"][0]) == want_keys,
                str(sorted(ex["confirmations"][0]) if ex["confirmations"] else []))
        T.check("确认不进条目：导出件的条目里没有 sig / payload 列",
                all("sig" not in e and "payload" not in e for e in ex["items"]))
        T.check("锚值只由导出字节决定：改一个字符就变",
                hashlib.sha256(public_app.LEDGER.export_bytes).hexdigest()
                == public_app.LEDGER.export_sha256)

        T.section("8. 闸门与上限")
        old_limiter = ingest.LIMITER
        ingest.LIMITER = ingest.RateLimiter(3)
        try:
            codes = []
            for i in range(4):
                st, r = alice.send("/api/v1/request", jbody({
                    "request_id": f"rq_rate{i:04d}", "state": "open", "category": "docs",
                    "need_desc": "刷频率", "requested_by": "pt_alice"}))
                codes.append((st, r.get("error")))
            T.check("一分钟内第 4 次 → 429 DGB_ING_015",
                    codes[-1] == (429, "DGB_ING_015"), str(codes))
        finally:
            ingest.LIMITER = old_limiter
        old_max = ingest.MAX_BODY
        ingest.MAX_BODY = 2048
        try:
            st, r = alice.send("/api/v1/entry", jbody({"big": "x" * 8192}))
            T.check("请求体超上限 → 413 DGB_ING_020",
                    st == 413 and r.get("error") == "DGB_ING_020", f"{st} {r}")
        finally:
            ingest.MAX_BODY = old_max
        T.check("正式上限是 64 KiB", old_max == 64 * 1024, str(old_max))
        req = urllib.request.Request(base + "/api/v1/nope", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                st = resp.status
        except urllib.error.HTTPError as e:
            st = e.code
        T.check("未知端点 → 404", st == 404, str(st))

        T.section("9. 入账转换：一次 delivered，两条账目（第 05 步）")
        # 同 §7：本节要发十来个请求，测的是转换，不是限流。先清计数，
        # 否则「交付 → 200」会因为前面的用例偶发 429，而那种失败看起来像转换坏了。
        with ingest.LIMITER.lock:
            ingest.LIMITER.hits.clear()

        def q1(sql: str, args=()):
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            try:
                return con.execute(sql, args).fetchone()
            finally:
                con.close()

        rid = "rq_deliver01"
        base_req = {"request_id": rid, "category": "compute",
                    "need_desc": "要 2 小时 CPU 跑一次回归", "requested_by": "pt_alice"}
        ev = "ipfs://bafyexample/handover.txt"
        occ = now_iso(-300)
        delivered = dict(base_req, state="delivered", claim_agent_id="pt_mallory",
                         evidence_uri=ev, occurred_at=occ)

        st, r = alice.send("/api/v1/request", jbody(dict(base_req, state="open")))
        T.check("（准备）发布 open → 200", st == 200, f"{st} {r}")
        st, r = mallory.send("/api/v1/request", jbody(dict(base_req, state="claimed",
                                                          claim_agent_id="pt_mallory")))
        T.check("（准备）认领 → 200", st == 200, f"{st} {r}")
        before = ledger_store.load_entries(db)

        st, r = mallory.send("/api/v1/request", jbody(delivered))
        T.check("交付 → 200，返回两条账目的位置与 hash",
                st == 200 and len(r.get("entries") or []) == 2
                and all(len(str(e.get("hash"))) == 64 for e in r["entries"]), f"{st} {r}")

        after = ledger_store.load_entries(db)
        T.check("一次交付恰好 +2 条（不多不少）", len(after) == len(before) + 2,
                f"{len(before)} → {len(after)}")
        pair = [e for e in after if e.get("mutual_id") == "m-" + rid]
        T.check("两条同 mutual_id = m-<request_id>", len(pair) == 2,
                str([e.get("entry_id") for e in pair]))
        T.check("id 是派生的：g-<request_id> / r-<request_id>（不由发号器发）",
                {e.get("entry_id") for e in pair} == {f"g-{rid}", f"r-{rid}"},
                str(sorted(e.get("entry_id") for e in pair)))
        g = [e for e in pair if e["type"] == "give"]
        rv_ = [e for e in pair if e["type"] == "receive"]
        T.check("give 的给方是认领方、受方是发布方（签名的那个人就是给方）",
                bool(g) and g[0]["from_agent_id"] == "pt_mallory"
                and g[0]["to_agent_id"] == "pt_alice", str(g[0] if g else None))
        T.check("两条都带 occurred_at，且等于这次交付的时间",
                all(e.get("occurred_at") == occ for e in pair),
                str([e.get("occurred_at") for e in pair]))
        T.check("交付凭据只在 receive 上（give 没有 evidence_uri 这一列）",
                bool(rv_) and rv_[0].get("evidence_uri") == ev and "evidence_uri" not in g[0],
                str(rv_[0] if rv_ else None))
        T.check("receive 的 state 记的是「已交付」，不随后续状态改写",
                bool(rv_) and rv_[0].get("state") == "delivered",
                str(rv_[0].get("state") if rv_ else None))

        chain5 = ledger_hash.build_chain(after)
        T.check("两条入链后链仍自洽", ledger_hash.verify_chain(chain5)[0],
                str(ledger_hash.verify_chain(chain5)[1]))
        chash = {e["entry_id"]: e["hash"] for e in chain5}
        T.check("接口返回的两个 hash == 独立重算的 hash",
                all(chash.get(e["entry_id"]) == e["hash"] for e in r["entries"]),
                str([(e["entry_id"], e["hash"][:8], chash.get(e["entry_id"], "")[:8])
                     for e in r["entries"]]))

        # 这两条账目不是「另一份记录」，而是那条已签的 delivered 行的函数。
        # 第三方手里有公开的需求单，就该能自己复算出同样的派生字段。
        pub = q1("SELECT * FROM v_public_request WHERE request_id=?", (rid,))
        T.check("第三方能从公开需求单复算出 give 的派生字段",
                bool(g) and pub is not None
                and g[0]["from_agent_id"] == pub["claim_agent_id"]
                and g[0]["to_agent_id"] == pub["requested_by"]
                and g[0]["category"] == pub["category"]
                and g[0]["occurred_at"] == pub["occurred_at"]
                and g[0]["entry_id"] == "g-" + pub["request_id"],
                str(pub["claim_agent_id"] if pub else None))

        st, r2 = mallory.send("/api/v1/request", jbody(delivered))
        T.check("原样再发一次 → 200 `already`（幂等，不是错误）",
                st == 200 and r2.get("already") is True, f"{st} {r2}")
        T.check("重发没有多出任何条目", len(ledger_store.load_entries(db)) == len(after),
                len(ledger_store.load_entries(db)))
        T.check("重发返回的是同一对 id 与同一个 hash",
                [e["entry_id"] for e in (r2.get("entries") or [])] == [e["entry_id"] for e in r["entries"]]
                and [e["hash"] for e in (r2.get("entries") or [])] == [e["hash"] for e in r["entries"]],
                str(r2.get("entries")))

        st, r3 = mallory.send("/api/v1/request", jbody(dict(delivered, evidence_uri=ev + ".bak")))
        T.check("换凭据再发 → 422 DGB_LED_029（改凭据不是重试）",
                st == 422 and r3.get("error") == "DGB_LED_029", f"{st} {r3}")
        T.check("被拒的那一次没写进任何地方（条目数与状态都没动）",
                len(ledger_store.load_entries(db)) == len(after)
                and q1("SELECT state FROM v_request_current WHERE request_id=?", (rid,))[0]
                == "delivered")

        st, r4 = alice.send("/api/v1/entry", jbody({
            "kind": "give", "give_id": "g_dup_of_delivery", "mutual_id": "m-" + rid,
            "from_agent_id": "pt_alice", "to_agent_id": "pt_mallory",
            "category": "compute", "occurred_at": now_iso()}))
        T.check("同一互助再手工记一条 give → 422 DGB_LED_032（一次互助只有一条）",
                st == 422 and r4.get("error") == "DGB_LED_032", f"{st} {r4}")

        st, r5 = mallory.send("/api/v1/request", jbody({
            "request_id": "rq_selftest01", "state": "delivered", "category": "compute",
            "need_desc": "还没人认领就宣布交付", "requested_by": "pt_alice",
            "claim_agent_id": "pt_mallory", "evidence_uri": ev, "occurred_at": occ}))
        T.check("open 直接跳 delivered → 422 DGB_LED_020（转换不绕过状态机）",
                st == 422 and r5.get("error") == "DGB_LED_020", f"{st} {r5}")
        st, r6 = alice.send("/api/v1/request", jbody(dict(delivered, request_id="rq_selftest01")))
        T.check("由发布方提交 delivered → 403 DGB_ING_011（交付只能由认领方提交）",
                st == 403 and r6.get("error") == "DGB_ING_011", f"{st} {r6}")

        rid2 = "rq_selfdel01"
        # 这一行必须**绕过写入面**造。§4b 之后，`claimed` 若由发布方自己提交，会在
        # 认领那一刻就 400 `DGB_ING_022`——正常路径已经造不出「自己发自己接」了。
        # 但 `DGB_LED_033` 仍然得在：它管的是**任何**路径落进库之后的「自己给自己」，
        # 包括直接写库、以及这条规则上线前就存在的行。所以这里直插一行，专门验库
        # 这道闸；绕过去是为了测兜底，不是为了绕过校验还假装没绕过。
        st, r = alice.send("/api/v1/request",
                           jbody(dict(base_req, request_id=rid2, state="open")))
        T.check("（准备）发布方发布一张单 → 200", st == 200, f"{st} {r}")
        con = sqlite3.connect(db)
        try:
            con.execute(
                "INSERT INTO request(request_id, seq, state, category, need_desc,"
                " window_expires_at, requested_by, claim_agent_id, created_at)"
                " VALUES(?,2,'claimed',?,?,'',?,?,?)",
                (rid2, base_req["category"], base_req["need_desc"],
                 "pt_alice", "pt_alice", now_iso()))
            con.commit()
        finally:
            con.close()
        T.check("（准备）直写一行自认领 → 库接受（这道闸在账目层，不在需求层）",
                q1("SELECT claim_agent_id FROM v_request_current WHERE request_id=?",
                   (rid2,))[0] == "pt_alice")
        st, r7 = alice.send("/api/v1/request", jbody(dict(delivered, request_id=rid2,
                                                          claim_agent_id="pt_alice")))
        T.check("自己给自己交付 → 422 DGB_LED_033（受方确认会变成自签）",
                st == 422 and r7.get("error") == "DGB_LED_033", f"{st} {r7}")
        T.check("被拒的那一次整体回滚：状态仍是 claimed、一条账目都没多",
                q1("SELECT state FROM v_request_current WHERE request_id=?", (rid2,))[0] == "claimed"
                and not [e for e in ledger_store.load_entries(db)
                         if e.get("mutual_id") == "m-" + rid2],
                str(q1("SELECT state FROM v_request_current WHERE request_id=?", (rid2,))))

        gh = chash[f"g-{rid}"]
        psig = ssh_sign(spec_confirm_payload(f"g-{rid}", gh), key_a,
                        namespace="drawcommons-confirm")
        st, r8 = alice.send("/api/v1/confirm",
                            jbody({"kind": "give", "entry_id": f"g-{rid}", "sig": psig}))
        T.check("发布方（受方）确认这条自动生成的 give → 200", st == 200, f"{st} {r8}")
        T.check("确认顺手把单子关掉（closed 是判定，不是第二个动作）",
                r8.get("closed_request") == rid, str(r8))
        T.check("库里的当前状态 = closed",
                q1("SELECT state FROM v_request_current WHERE request_id=?", (rid,))[0] == "closed")
        closed_row = q1("SELECT * FROM v_request_current WHERE request_id=?", (rid,))
        T.check("关闭行保留了交付时间与凭据（DGB_LED_024 要求，不能关单就丢证据）",
                closed_row["occurred_at"] == occ and closed_row["evidence_uri"] == ev,
                str(dict(closed_row)))
        st, r9 = mallory.send("/api/v1/request", jbody(delivered))
        T.check("关单之后再重发交付 → 仍是 200 already（幂等跨状态成立）",
                st == 200 and r9.get("already") is True and r9.get("state") == "closed",
                f"{st} {r9}")

        T.section("结果")
        print(f"  OK {T.ok} / FAIL {T.bad}")
        return 0 if T.bad == 0 else 1
    finally:
        if srv is not None:
            srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)


def local_fp(pubkey_line: str) -> str:
    """独立算一遍指纹（`ssh-keygen -lf` 的口径），用来核对接口返回的 key_fp。"""
    blob = base64.b64decode(pubkey_line.split()[1])
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


if __name__ == "__main__":
    raise SystemExit(main())
