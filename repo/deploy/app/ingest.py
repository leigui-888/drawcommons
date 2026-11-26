# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""写入面：五条受控 POST。挂在 `/api/v1/*`，与只读的公开页是两个进程。

**为什么是另一个进程，而不是给 app.py 加个 do_POST。**

公开页的卷是只读挂载，进程在物理上没有写库的能力——这一条写进了部署口径，也是
「公开页攻击面少一整类」的全部依据。同一个进程里加写入，就得把这个卷改成读写，
那条承诺当场变成一句注释。所以写入单独一个容器：卷只对它读写，对 app 仍只读。

**六条端点共用一条通路。**

`/api/v1/party`、`/api/v1/request`、`/api/v1/entry`、`/api/v1/confirm`、
`/api/v1/reject`、`/api/v1/remind` 都走
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
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ledger_store
import signing

DB_PATH = os.environ.get("LEDGER_DB", "data/ledger.db")
PORT = int(os.environ.get("PORT", "8001"))

# 请求体上限。六条端点里最大的是需求单（need_desc 2000 字），64 KiB 有二十倍余量；
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
    "DGB_ING_022": 400,   # 发布方认领自己的单
}

# 需求单里允许 API 直写的状态。`closed` 要等双方签名与两条账目都落库——而那两件事
# 一发生，`closed` 就是**可判定的事实**，由 `confirm` 顺手写（`close_after_confirm`），
# 不由谁去「宣布」；`expired` 由写入面按期限结算（`sweep_expired`），也不是人工动作。
# 这两条若开个口子，就等于允许一个人宣布一件系统还没挣到的事，也能宣布一件已经
# 挣到的事——接口上分不出这两种。
WRITABLE_STATES = ("open", "claimed", "delivered", "withdrawn")


def status_for(code: str) -> int:
    if code.startswith("DGB_LED_"):
        return ledger_store.LED_STATUS.get(code[-3:], 422)
    return STATUS.get(code, 400)


# 每个码配一句「下一步做什么」。给 agent 看的：它读得懂 HTTP 状态，但读不懂
# 「DGB_ING_009」该怎么办。没有这句，24 种情况下它只能猜，而猜错的下场是
# 往一个只追加的账本里写错东西。
# **写的是动作，不是解释**——「签名覆盖原始字节」是解释，「别重排 JSON 再签」是动作。
# 判据 `_ops/w0/error_codes_check.py` 保证：每个可达的码都有这一行，且不会出现
# 码表里有、代码里没有的孤儿。
CODE_HINTS = {
    # —— 传输与鉴权 ——
    "DGB_ING_001": "带齐 X-DG-Party / Issued / Nonce / Sig 四个头（见 /agent.md §4）",
    "DGB_ING_002": "用 ssh-keygen -Y sign -n drawcommons-ingest 签原始字节，别重排 JSON",
    "DGB_ING_003": "先 POST /api/v1/party 登记这把公钥，再签这一条",
    "DGB_ING_004": "把本机时钟对准 UTC；issued_at 须在服务端时间 ±15 分钟内",
    "DGB_ING_005": "每次请求换一个新 nonce（≥16 字节随机）；重试也要换",
    "DGB_ING_006": "Content-Type: application/json，且 body 是一个 JSON 对象而不是数组",
    "DGB_ING_007": "端点只有 party/request/entry/confirm/reject/remind 六个",
    "DGB_ING_008": "pubkey 传 authorized_keys 里的整行 ssh-ed25519 AAAA…，单行、不带注释",
    "DGB_ING_009": "按 detail 点名的字段补齐；请求体形状见 /agent.md §4 的示例",
    "DGB_ING_010": "本端点只接受 display_mode=pseudonymous",
    "DGB_ING_011": "这个 state 由服务端派生：delivered 生成两条账目，closed 由受方确认后自动追加",
    "DGB_ING_012": "这把公钥已属于另一个主体；换钥就是换人，用新的 party_id 重新登记",
    "DGB_ING_014": "同一 request_id 只能顺着状态机追加（每次带新的 state），不能重发一次 open",
    "DGB_ING_015": "每主体每分钟 30 次；按 Retry-After 等待后重试",
    "DGB_ING_016": "服务端兜底缺陷：把请求体与 detail 原文一并报给运营方，不要重试",
    "DGB_ING_017": "换一个 <kind>_id；账本只追加，条目 id 不能复用",
    "DGB_ING_018": "只发 schema 里的字段；signed_at / party_id / key_fp 都不接受客户端自带",
    "DGB_ING_019": "省略 rule_version（默认 v1），或显式写 v1",
    "DGB_ING_020": "请求体压到 64 KiB 以内；大文件放 evidence_uri 指过去",
    "DGB_ING_021": "用 curl -d 或显式带 Content-Length；分块传输不被接受",
    "DGB_ING_022": "发布方不能认领自己的单：换另一把钥匙的人来认领，或让发布方撤回后由别人重发",
    "DGB_LED_038": "同一张单 24 小时只能催一次；冷却过后再来",
    "DGB_LED_039": "只有当前认领方能催交付中的单；其他人不签",
    # —— 库约束（触发器）——
    "DGB_LED_012": "账本只追加：改状态要 POST 一行新的 seq，不要 UPDATE",
    "DGB_LED_013": "没有删除这条路径；写错了就再追加一行说明，别 DELETE",
    "DGB_LED_014": "archive_magnitude_v1 是只读归档表，只追加、不改写",
    "DGB_LED_015": "撤回同意是终态，撤回之后不能再改回去",
    "DGB_LED_016": "实名展示须显式绑定 real_name_ref；本端点不收实名",
    "DGB_LED_017": "pubkey 必须是单行、合法的 ssh-ed25519 authorized_keys 行",
    "DGB_LED_018": "已登记的公钥不可更换；换钥 = 换 party_id",
    "DGB_LED_019": "requested_by / claim_agent_id 里的主体必须先在 party 登记",
    "DGB_LED_020": "按 open → claimed → delivered → closed 走，不能跳级，也不能从终态再出发",
    "DGB_LED_021": "seq 由服务端算；同一 request_id 从 1 连续追加，不要自带 seq",
    "DGB_LED_023": "claimed 必须带 claim_agent_id",
    "DGB_LED_024": "delivered 必须带 occurred_at 与 evidence_uri（关闭行也要带）",
    "DGB_LED_025": "一单只有一个 requested_by；换发布方请重开一单",
    "DGB_LED_027": "mutual_id 必须是 m-rq_<request_id>，指向那张已交付的单子",
    "DGB_LED_028": "mutual_id 指向的需求单当前必须处于 delivered / closed",
    "DGB_LED_029": "凭据以第一次为准：改字段不是重试；要改就重开一单",
    "DGB_LED_030": "确认指向的条目不存在：先 GET /api/ledger/items 核对 entry_id 与 hash",
    "DGB_LED_031": "确认只能由受方签；给方自签不算双签",
    "DGB_LED_032": "一次互助只允许一条 give 与一条 receive；重复交付请用同一 request_id 重试",
    "DGB_LED_033": "give 的 from_agent_id 与 to_agent_id 不能是同一主体",
    "DGB_LED_034": "payload 三行：drawcommons-confirm-v1、entry_id、hash，末尾各带换行",
    "DGB_LED_035": "该条目已确认过；确认不可覆盖，要纠正只能追加说明",
    "DGB_LED_036": "拒收只能由发布方签；认领方与第三方不能拒别人的交付",
    "DGB_LED_037": "认领与交付只能推进状态，不能改条款；要改让发布方撤回后重发",
    # 签名存证（v1.8）。这三条对调用方只有一个动作：把 500 连同时间贴给运营方——
    # 它们全都意味着「服务端有一条写库路径少给了一样东西」，客户端改请求改不好。
    "DGB_LED_040": "服务端未声明该状态行的来源；这是服务端的错，请带着时间与端点报告",
    "DGB_LED_041": "服务端未随行存证（载荷/签名/指纹缺一）；这是服务端的错，请报告",
    "DGB_LED_042": "派生行被写入了签名（时钟与派生没有钥）；这是服务端的错，请报告",
}


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


# ── 六条端点的语义 ───────────────────────────────────────────────────────────
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
    with writer.tx(commit=not env.get("dry_run")) as con:
        writer.spend_nonce(con, env["nonce"], party)
        res = writer.register_party(con, pid, key_line, mode)
    res.update({"party_id": pid, "key_fp": signing.fingerprint(blob)})
    return res


# 邮箱形状：只挡「把一段话糊进邮箱栏」，不追求 RFC 5322 的完备。
# 判得越细越容易把合法地址挡在门外，而这里要防的从来不是罕见合法地址。
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _email(value, field: str) -> str | None:
    """规整一格邮箱：空串与 None 都算「没填」，其余必须过形状。"""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if len(s) > 254 or not EMAIL_RE.match(s):
        raise ledger_store.WriteError(
            "DGB_ING_009", f"{field} 不是一个邮箱地址（形状：xxx@yyy.zzz，最多 254 字符）")
    return s


def op_request(writer, party: str, data: dict, env: dict) -> dict:
    _no_extra(data, ("request_id", "state", "category", "need_desc", "window_expires_at",
                     "requested_by", "claim_agent_id", "evidence_uri", "occurred_at", "note",
                     "poster_email", "claimer_email"))
    _require(data, "request_id", "state", "category", "need_desc", "requested_by")
    # 两格联系方式先规整成 None / 合法串。空串存 NULL——`''` 与「没填」在页面上
    # 是同一件事，存两种值只会让读端多一个分支。
    data = dict(data,
                poster_email=_email(data.get("poster_email"), "poster_email"),
                claimer_email=_email(data.get("claimer_email"), "claimer_email"))
    if not REQUEST_RE.match(data["request_id"]):
        raise ledger_store.WriteError("DGB_ING_009", "request_id 形状：rq_ + 8–32 位小写字母数字")
    state = data["state"]
    if state not in WRITABLE_STATES:
        raise ledger_store.WriteError(
            "DGB_ING_011",
            f"{state} 不接受直写：" + ("closed 要等双方签名与两条账目（第 04/05 步）"
                                       if state == "closed" else "expired 由写入面按期限结算"))
    # 谁能推进哪一步。发布方管发布与撤回，认领方管认领、交付与放回——不是「有钥就能写」。
    # `open` 分两种，归属不同：第 1 行是「发布」，只能由 requested_by 发；非第 1 行是
    # 「回退」（v1.6），发布方与当前认领方都能提。后者要看库里当前行，所以判定挪进事务。
    if state == "withdrawn":
        if party != data["requested_by"]:
            raise ledger_store.WriteError(
                "DGB_ING_011", "withdrawn 只能由发布方（requested_by）提交")
    elif state in ("claimed", "delivered"):
        if not data.get("claim_agent_id"):
            raise ledger_store.WriteError("DGB_ING_009", f"{state} 必须带 claim_agent_id")
        if party != data["claim_agent_id"]:
            raise ledger_store.WriteError(
                "DGB_ING_011", f"{state} 只能由认领方（claim_agent_id）提交")
    # ── 签名存证（v1.8）─────────────────────────────────────────────────────
    # 这一段就是「签名证据在服务端」那句话的实物：`signed_payload` 是 `signing.verify`
    # 算出来并验过的那一段载荷（不是这里重拼的），`sig_text` 是客户端交上来的 SSHSIG
    # 原文，`key_fp` 是刚验过的那把钥。三样一起落库，事后任何人拿
    # `GET /api/v1/requests/<id>/evidence` 就能离线复验，不需要信本服务。
    #
    # 它证明的是「这一行来自这把钥的这一次请求」，**不是**「这一行的每个字段逐字等于
    # 请求体」——落库值经过规整（空串存 NULL、联系方式沿用上一行、seq 与 created_at
    # 由服务端盖）。这条边界写在 ddl_v1.8.sql 头部与 /requests 页面上，改之前先读。
    evidence = {"kind": "http",
                "payload": env["signed_payload"].decode("utf-8"),
                "sig": env["sig_text"],
                "key_fp": env["key_fp"]}
    with writer.tx(commit=not env.get("dry_run")) as con:
        writer.spend_nonce(con, env["nonce"], party)
        cur = writer.current_request(con, data["request_id"])

        # ── 发布方不能成为自己单子的认领方（2026-11-25）────────────────────
        # 库里其实有一条 `trg_ledger_give_not_self`（`DGB_LED_033`）在管「给方与受方
        # 不得同一」，但那要等到 **交付** 那一次才报，而且报出来的是库约束——提交的人
        # 只知道「服务端不让我写」，不知道自己踩的是哪条规矩。更要紧的是它拦晚了：
        # 自认领一旦成立，这张单就被发布方自己占住——别人再来认领是
        # open→claimed 而当前已是 claimed，只会拿到 `DGB_LED_020`「非法迁移」，
        # 于是这张单对所有人关闭，却不是 withdrawn、也不在任何人的待办里。
        # 所以在**认领那一刻**拦。判据用 `cur`（库里的真值）而不是请求体里的
        # `requested_by`：后者是客户端写的，改个值就能绕过去。
        if state == "claimed" and cur is not None and (cur["requested_by"] or "") == party:
            raise ledger_store.WriteError(
                "DGB_ING_022",
                "发布方不能认领自己发的单：一单的发布方与认领方必须是两个主体")

        # ── 联系方式两格：谁给、能不能改、怎么沿用（v1.7）──────────────────
        # 规则只有三条，都是「这版没有编辑功能」的直接推论：
        #   1) 带了就必须与上一行一字不差，否则 037——认领/交付/撤回/回退都不是
        #      改联系方式的暗门；
        #   2) 没带就沿用上一行，否则每推进一次状态就丢一次邮箱，而页面上的
        #      「双方认领后才可见」会在第二次状态变化后变成「看不见」；
        #   3) `claimer_email` 允许在 claimed / delivered 行**首次**填写（那时才
        #      第一次有认领方），填的人由上面的 claim_agent_id 校验保证是认领方本人。
        if cur is not None:
            v = data.get("poster_email")
            if v is not None and v != cur["poster_email"]:
                raise ledger_store.WriteError(
                    "DGB_LED_037", "不能改需求条款：poster_email（发单时的联系方式）")
            data["poster_email"] = v or cur["poster_email"]

            v = data.get("claimer_email")
            if v is not None and v != cur["claimer_email"]:
                if cur["claimer_email"] is not None:
                    raise ledger_store.WriteError(
                        "DGB_LED_037", "不能改需求条款：claimer_email（认领时的联系方式）")
                if state not in ("claimed", "delivered"):
                    raise ledger_store.WriteError(
                        "DGB_LED_037", "claimer_email 只能在认领或交付那一行第一次填写")
            data["claimer_email"] = v or cur["claimer_email"]

        if state == "open":
            if cur is None:
                # 第 1 行：发布。用自己的名字发别人的单不是本协议的动作。
                if party != data["requested_by"]:
                    raise ledger_store.WriteError(
                        "DGB_ING_011", "open 只能由发布方（requested_by）提交")
                if data.get("claimer_email"):
                    # 还没有人认领，就没有「认领方的联系方式」这回事。
                    # 不静默丢掉：丢掉会让客户端以为写进去了。
                    raise ledger_store.WriteError(
                        "DGB_ING_009", "第 1 行还没有认领方，不能带 claimer_email")
                # 接单窗口上限 90 天（v1.6）。页面上写着「上限 90 天」，服务端就得认同一个数，
                # 否则那句话只是前端的礼貌，脚本照样能挂十年。
                # 用 SQLite 自己的 `julianday()` 判，一次同时验两件事：格式能不能解析、
                # 是不是超过了上限。不在 Python 里另写一套日期解析——两套解析器迟早对不上。
                w = (data.get("window_expires_at") or "").strip()
                if w:
                    # 比较用**日期**而不是时刻：页面上写的是「上限 90 天」，人按天选，
                    # 而日期框给的是当地的一天、转成 UTC 后会落在这天的某个时刻。
                    # 拿时刻比，选「第 90 天」的人在 UTC+8 会被多出的 8 小时顶出去——
                    # 页面允许、服务端拒绝，这种错最难查。按天比，两边口径一致。
                    ok = con.execute(
                        "SELECT julianday(?) IS NOT NULL"
                        "   AND date(?) <= date('now', ?)",
                        (w, w, f"+{ledger_store.MAX_WINDOW_DAYS} days")).fetchone()[0]
                    if not ok:
                        raise ledger_store.WriteError(
                            "DGB_ING_009",
                            "window_expires_at 必须是可以解析的时间，且不晚于发布后 "
                            f"{ledger_store.MAX_WINDOW_DAYS} 天")
            else:
                # 非第 1 行：把已认领的单放回池子（v1.6）。这是认领人唯一的退路——
                # 他没有能力兑现时，以前只能永久占着这张单，连发布方都只能整张撤掉。
                if cur["state"] == "open":
                    # 已经是 open 了。「open → open」不是迁移，与 v1.4 那条
                    # `trg_request_open_only_first` 报同一个码，客户端不必为新旧行为
                    # 学两种错误码。
                    raise ledger_store.WriteError(
                        "DGB_LED_020", "这张单已经是 open；重复提交 open 不是一次迁移")
                if cur["state"] != "claimed":
                    raise ledger_store.WriteError(
                        "DGB_ING_011", f"只有 claimed 能回退到 open，当前是 {cur['state']}")
                allowed = {cur["requested_by"], cur["claim_agent_id"]} - {None, ""}
                if party not in allowed:
                    raise ledger_store.WriteError(
                        "DGB_ING_011", "回退到 open 只能由发布方或当前认领方提交")
                # **回退只改状态，不改条款。** 认领关系作废（认领方置空），而
                # category / need_desc / 截止时间一律沿用原行——否则「回退」就成了
                # 一个改需求的暗门，而这版没有编辑功能。
                # 认领方邮箱同时清掉（v1.7）：那个地址属于一个已经不在单上的人，
                # 留给下一任认领方看既没必要，也是在两次无关的认领之间传信息。
                data = dict(data, claim_agent_id=None, evidence_uri=None, occurred_at=None,
                            claimer_email=None,
                            category=cur["category"], need_desc=cur["need_desc"],
                            window_expires_at=cur["window_expires_at"], note=cur["note"])

        # 只在**前置状态本身合法**时才比条款：跳级（open → delivered）要报状态机那个
        # 更根本的错（`DGB_LED_020`），不该被一个次要校验抢先做成 037。判据顺序也是语义顺序。
        # v1.7 加了第四条：`delivered → delivered`（被拒收后再交一次）同样要走条款比对——
        # 它是真正的第二轮交付，不是重试；重试在下面走 `delivery_replay`。
        prev_ok = cur is not None and (
            (state == "claimed" and cur["state"] == "open")
            or (state == "delivered" and cur["state"] == "claimed")
            or (state == "delivered" and cur["state"] == "delivered"))
        if prev_ok:
            # **认领与交付都不能顺带改条款**（v1.6）。这版没有编辑功能，每一条推进状态的
            # 路径都必须关上这扇门，否则「认领」就成了一个改需求的暗门——发布方按 A 的
            # 条件挂出来，认领方交 B 的条件，账本里还两个都像真的。
            # 只比请求体里**带了**的键：脚本按最小字段提交（只带 request_id/state/…）时
            # 不该被「你没带 note」判成改了 note。带了就必须与上一行一字不差。
            def _norm(v):
                return "" if v is None else str(v)
            diff = [k for k in ledger_store.TERMS_FIELDS
                    if k in data and _norm(data[k]) != _norm(cur[k])]
            if diff:
                raise ledger_store.WriteError(
                    "DGB_LED_037",
                    "认领与交付不能改需求条款；要改只能由发布方撤回后重发"
                    f"（不一致：{', '.join(diff)}）")
            if state == "delivered" and cur["state"] in ("claimed", "delivered"):
                # 换个人来交付，等于绕过「先到先得」把单子转手了。第二次交付同样
                # 只能由当初那个人交——否则「拒收 → 换人重交」就是一条转手暗门。
                if _norm(data.get("claim_agent_id")) != _norm(cur["claim_agent_id"]):
                    raise ledger_store.WriteError(
                        "DGB_LED_037", "交付的认领方必须与认领时一致（先到先得）")

        if state == "withdrawn" and cur is not None:
            # 撤回行沿用上一行的交付字段。撤掉的可能是**已经被接过**的单，当前视图
            # 若看不到认领方，就等于抹掉了「撤掉的是谁接的单」——历史行仍在，但
            # 一单一行当前状态的口径残缺了。closed 由 close_after_confirm 整行复制，
            # 同一个道理，这里补齐。
            data = dict(data, claim_agent_id=cur["claim_agent_id"],
                        evidence_uri=cur["evidence_uri"],
                        occurred_at=cur["occurred_at"])

        if state == "delivered":
            # 交付这一次是**一个转换**，不是一行状态：它同时产出 give 与 receive 两条
            # 账目（第 05 步），并且与状态行在同一个事务里。分两步做就会留下「已交付但
            # 账上没东西」的中间态，而那个中间态没有任何人能修——delivered 不能重进。
            #
            # **三种情形，靠「当前行是否已被拒收」分开（v1.7）：**
            #   · 已结（closed）→ 重放分支：单子封了，任何提交都只能是重试；
            #   · 交付中、没被拒 → 重放分支：字段一致回 200，不一致 029（凭据以第一次为准）；
            #   · 交付中、**已被拒** → 这是一次新的交付，往下追加行与账目。
            # 第三支为什么必须有「已被拒」这个前提：没有它，任何一次带新凭据的
            # `delivered` 都能把上一次的凭据顶掉，而 append-only 的账上会留下两对
            # 一模一样的「交付」，没人分得清哪次算数。拒绝是重交的通行证。
            if cur is not None and (
                    cur["state"] == "closed"
                    or (cur["state"] == "delivered"
                        and not writer.rejected_seq(con, cur["request_id"], cur["seq"]))):
                return writer.delivery_replay(con, data, cur)
            res = writer.append_request(con, data, evidence)
            res.update(writer.convert_delivery(con, data["request_id"]))
        else:
            res = writer.append_request(con, data, evidence)
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
    with writer.tx(commit=not env.get("dry_run")) as con:
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

    with writer.tx(commit=not env.get("dry_run")) as con:
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


def op_reject(writer, party: str, data: dict, env: dict) -> dict:
    """受方拒收某一次交付。**不改需求单状态。**

    理由见 `ledger_store.insert_reject`：交付那一刻两条账目已经进链，append-only 撤不回来，
    把单子改成别的状态会让人以为「这次交付被取消了」。拒收能做的只有一件事——把
    「沉默」变成「有签名、有理由、可查询的拒绝」。

    内层签名载荷三行（`request_id` + `seq`），由服务端按库里那一行重算；客户端带的
    `payload` 只作核对，不采信——和 `op_confirm` 同一个道理。
    """
    _no_extra(data, ("request_id", "seq", "sig", "payload", "reason"))
    _require(data, "request_id", "seq", "sig")
    rid = str(data["request_id"])
    if not REQUEST_RE.match(rid):
        raise ledger_store.WriteError("DGB_ING_009", "request_id 形状：rq_ + 8–32 位小写字母数字")
    seq = data["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise ledger_store.WriteError(
            "DGB_ING_009", "seq 必须是正整数，指向被拒的那条 delivered 行")
    sig_text = data["sig"]
    if not isinstance(sig_text, str) or "BEGIN SSH SIGNATURE" not in sig_text:
        raise ledger_store.WriteError("DGB_ING_009", "sig 必须是 SSHSIG armor 全文")
    if len(sig_text) > 8192 or "\x00" in sig_text:
        raise ledger_store.WriteError("DGB_ING_009", "sig 超长或含 NUL")
    reason = data.get("reason")
    if reason is not None:
        reason = str(reason).strip() or None
    if reason is not None and len(reason) > 500:
        raise ledger_store.WriteError("DGB_ING_009", "reason 最多 500 字")

    with writer.tx(commit=not env.get("dry_run")) as con:
        writer.spend_nonce(con, env["nonce"], party)
        cur = writer.current_request(con, rid)
        if cur is None:
            # 没有这一单，就没有「那次交付」可否认。用 029 而不是 030：030 是
            # 「entry 不存在」（那是账本侧的指针），这里错的是需求单这一侧。
            raise ledger_store.WriteError("DGB_LED_029", f"需求单 {rid} 不存在")
        if cur["state"] != "delivered":
            # 拒收否认的是一次已经发生的交付。没有交付可否认时，「拒」没有对象。
            raise ledger_store.WriteError(
                "DGB_LED_036", f"只能拒收 delivered 的单，当前是 {cur['state']}")
        if seq != cur["seq"]:
            # 指错行 = 否认另一次交付。当前行是唯一还没被确认的那一次。
            raise ledger_store.WriteError(
                "DGB_ING_011", f"seq 必须指向当前 delivered 行（第 {cur['seq']} 行）")
        if party != cur["requested_by"]:
            raise ledger_store.WriteError(
                "DGB_LED_036", "拒收只能由发布方签（认领方与第三方不能拒别人的交付）")
        # 同一次交付只能被拒一次（v1.7 起一单可以有多条拒收，但一条交付只有一次拒绝）。
        # 重发同一份：理由一致就回已存在（幂等），不一致就是 029——拒收不可改，
        # 改理由不是重试。撞主键在 append-only 的表上没有第二种解释。
        prev = writer.current_reject(con, rid, seq)
        if prev is not None:
            if (prev["reason"] or None) != (reason or None):
                raise ledger_store.WriteError(
                    "DGB_LED_029", "这一次交付已经被拒收，理由以第一次为准；拒收不可改")
            return {"request_id": rid, "seq": seq, "party_id": party,
                    "key_fp": prev["key_fp"], "reason": prev["reason"],
                    "signed_at": prev["signed_at"], "already": True}
        payload = signing.reject_payload(rid, seq)
        sent = data.get("payload")
        if sent is not None and str(sent).encode("utf-8") != payload:
            raise ledger_store.WriteError(
                "DGB_LED_034", "payload 与服务端重算值不一致（签错单号或签错行号）")
        ok, out = signing.verify_detached(env["key_line"], party, sig_text, payload,
                                          signing.REJECT_NAMESPACE)
        if not ok:
            print(f"ingest: reject verify failed {party} {rid}#{seq}: {out[:200]}", flush=True)
            raise ledger_store.WriteError(
                "DGB_LED_034", "拒收签名验不过：载荷须为 request_id 与 seq 两行（带版本行）")
        res = writer.insert_reject(con, rid, seq, party, env["key_fp"],
                                   payload.decode("utf-8"), sig_text, reason)
    res.update({"payload": payload.decode("utf-8")})
    return res


def op_remind(writer, party: str, data: dict, env: dict) -> dict:
    """认领方对一次尚未确认的交付留一条「我催过」。**不改状态、不改条款。**

    拒收是「我不认这次交付」，催告是「请你看一眼」。两者都落在当前那条 delivered
    行上，但意思相反，所以各用一张表、各用一个签名域——合成一张表加 kind 列的话，
    每个查询都要带 `WHERE kind=...`，漏一处就把催告读成拒收，而那种错不会报。

    三条硬约束都在库里（`trg_request_reminder_is_claimer` / `_cooldown`），应用层
    再判一次只为把「这是谁的单」「还差几个小时」写成一句人话，而不是把触发器的
    RAISE 原文丢给调用方。判据里两条都要能弄红：拆掉触发器，应用层挡住；把应用层
    那两段删掉，触发器挡住。
    """
    _no_extra(data, ("request_id", "seq", "sig", "payload"))
    _require(data, "request_id", "seq", "sig")
    rid = str(data["request_id"])
    if not REQUEST_RE.match(rid):
        raise ledger_store.WriteError("DGB_ING_009", "request_id 形状：rq_ + 8–32 位小写字母数字")
    seq = data["seq"]
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise ledger_store.WriteError(
            "DGB_ING_009", "seq 必须是正整数，指向当前那条 delivered 行")
    sig_text = data["sig"]
    if not isinstance(sig_text, str) or "BEGIN SSH SIGNATURE" not in sig_text:
        raise ledger_store.WriteError("DGB_ING_009", "sig 必须是 SSHSIG armor 全文")
    if len(sig_text) > 8192 or "\x00" in sig_text:
        raise ledger_store.WriteError("DGB_ING_009", "sig 超长或含 NUL")

    with writer.tx(commit=not env.get("dry_run")) as con:
        writer.spend_nonce(con, env["nonce"], party)
        cur = writer.current_request(con, rid)
        if cur is None:
            raise ledger_store.WriteError("DGB_LED_029", f"需求单 {rid} 不存在")
        if cur["state"] != "delivered":
            raise ledger_store.WriteError(
                "DGB_LED_039", f"只有交付中的单能催，当前是 {cur['state']}")
        if seq != cur["seq"]:
            raise ledger_store.WriteError(
                "DGB_ING_011", f"seq 必须指向当前 delivered 行（第 {cur['seq']} 行）")
        if party != cur["claim_agent_id"]:
            raise ledger_store.WriteError(
                "DGB_LED_039", "催告只能由当前认领方签（发布方催自己不是催告）")

        # 冷却：24 小时内同一个人对同一张单只能催一次。这里先判一次是为了给
        # 「还差多久」；触发器那道照样在，防止绕过接口直写。
        last = writer.last_reminder_at(con, rid, party)
        if last:
            gap = con.execute(
                "SELECT julianday('now') - julianday(?)", (last,)).fetchone()[0]
            if gap is not None and gap < 1.0:
                hours = max(1, int(24 - gap * 24))
                raise ledger_store.WriteError(
                    "DGB_LED_038", f"24 小时内已经催过一次（最近 {last}）；约 {hours} 小时后再来")

        payload = signing.remind_payload(rid, seq)
        sent = data.get("payload")
        if sent is not None and str(sent).encode("utf-8") != payload:
            raise ledger_store.WriteError(
                "DGB_LED_034", "payload 与服务端重算值不一致（签错单号或签错行号）")
        ok, out = signing.verify_detached(env["key_line"], party, sig_text, payload,
                                          signing.REMIND_NAMESPACE)
        if not ok:
            print(f"ingest: remind verify failed {party} {rid}#{seq}: {out[:200]}", flush=True)
            raise ledger_store.WriteError(
                "DGB_LED_034", "催告签名验不过：载荷须为 request_id 与 seq 两行（带版本行）")
        res = writer.insert_reminder(con, rid, seq, party, env["key_fp"],
                                     payload.decode("utf-8"), sig_text)
    res.update({"payload": payload.decode("utf-8")})
    return res


ROUTES = {"/api/v1/party": op_party,
          "/api/v1/request": op_request,
          "/api/v1/entry": op_entry,
          "/api/v1/confirm": op_confirm,
          "/api/v1/reject": op_reject,
          "/api/v1/remind": op_remind}


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
    # 只查「表在不在」挡不住 2026-11-25 那次事故：库停在 v1.4、代码已到 v1.7，
    # 认领时 `cur["poster_email"]` 抛的是 **IndexError**，不是 sqlite3.Error——
    # 连 ledger_store 里那些 `except sqlite3.Error` 的兜底都接不住，直接 500。
    # 加列比加表危险得多：加表能被 try/except 变软成「这个功能没有」，加列会穿透。
    # 所以这里按列签名再核一遍，让「库落后于代码」在容器启动时就喊出来，
    # 而不是等第一个认领的人替我们撞上。
    #
    # 每一列对应「哪个文件补的」，报错才能指到具体一步：只说「先跑最新那份」，
    # 跳着一份不跑照样起不来，而错误信息看起来一模一样（2026-11-25 差点又踩）。
    need_cols = {"request": {
        "poster_email": "spec/ddl_v1.7.sql",
        "claimer_email": "spec/ddl_v1.7.sql",
        "sig_kind": "spec/ddl_v1.8.sql",
        "sig_payload": "spec/ddl_v1.8.sql",
        "sig": "spec/ddl_v1.8.sql",
        "sig_key_fp": "spec/ddl_v1.8.sql",
        "sig_ref": "spec/ddl_v1.8.sql",
    },
        # v1.10 的入链次序。缺了它不会 500（`append_entry` 会让路），但链会退回
        # 「按内容排序」——那正是 2026-11-26 让两条真实确认验不过的那条路。
        # 所以这里按硬要求报：**库跟不上，宁可起不来**。
        "ledger_give": {"ord": "spec/ddl_v1.10.sql"},
        "ledger_receive": {"ord": "spec/ddl_v1.10.sql"},
        "ledger_payback": {"ord": "spec/ddl_v1.10.sql"},
    }
    try:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        for t, cols in need_cols.items():
            present = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            lack = [c for c in cols if c not in present]
            if lack:
                files = sorted({cols[c] for c in lack})
                problems.append(f"库缺列 {t}.{','.join(lack)}"
                                f"——库落后于代码，先跑 {' 与 '.join(files)}")
        con.close()
    except sqlite3.Error as exc:
        problems.append(f"核列失败（{type(exc).__name__}: {exc}）")
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


def sweep_expired_quietly(where: str) -> None:
    """顺手把到期的 `open` 单结算成 `expired`。**失败只记日志，不改这一次请求的结果。**

    一次 sweep 炸掉（库锁、某行时间格式异常）不该让一次合法的写入变成 500：列表早就
    由视图 `v_public_request` 收走了，晚一步结算只是账本与站点暂时不一致，而一次
    500 会让调用方以为自己的写入失败了——那是个更坏的错误。

    它不读请求体、也没有调用方能指名哪一单，所以「`expired` 不是人工动作」这句
    仍然成立。它不是一个角色，是一个时钟。
    """
    try:
        with WRITER.tx() as con:
            done = WRITER.sweep_expired(con)
        if done:
            print(f"ingest: {where}结算 {len(done)} 张到期未认领的单："
                  + ", ".join(d["request_id"] for d in done), flush=True)
    except Exception:                      # noqa: BLE001
        print(f"ingest: sweep 失败（{where}）：\n{traceback.format_exc()}", flush=True)


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
        """错误体：码 + 人话 + **下一步**。`hint` 是给 agent 的那一格。

        它是附加字段，加在既有三个字段之后——老的调用方按名取值（`error` / `detail`），
        多一个键不会让它们解析失败。反过来若删字段或改码，才是破坏性的。
        """
        body = {"ok": False, "error": code, "detail": detail, "endpoint": endpoint}
        hint = CODE_HINTS.get(code)
        if hint:
            body["hint"] = hint
        self._send(status_for(code), body)

    def _client_ip(self) -> str:
        headers = getattr(self, "headers", None)
        xff = headers.get("X-Forwarded-For", "") if headers else ""
        return xff.split(",")[0].strip() if xff else self.client_address[0]

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/healthz":
            self._send(200, b"ok", "text/plain; charset=utf-8")
            return
        if path == "/api/v1/request/contact":
            self._contact()
            return
        self._send(404, {"ok": False, "error": "not_found"})

    def _contact(self) -> None:
        """取一单的联系方式。**读口，但要签名**——这是「双方认领后才可见」的实现。

        为什么放在写口进程而不是站点：站点是匿名的，`/r/<id>` 谁都能打开，
        CSP 又禁了脚本，浏览器里没有可验证的身份。把邮箱渲染上去，就是公开。
        这里用的是写口已有的那套信封签名：`X-DG-Party` + 四个头 + 空 body，
        验过之后才知道「问的人是谁」，再由 `contact_for` 判定他是不是这两方之一。

        载荷里的 method 是 `GET`，path 是 `/api/v1/request/contact`，body 摘要为空
        串的 sha256。查询串不参与签名（与 POST 的 dry_run 同一条规矩），所以
        `?id=` 不会让签名失效。
        """
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        rid = (qs.get("id") or [""])[0]
        try:
            if not REQUEST_RE.match(rid):
                raise ledger_store.WriteError("DGB_ING_009", "id 形状：rq_ + 8–32 位小写字母数字")
            party, key_fp, _env = signing.verify_read(
                self.headers, "/api/v1/request/contact", lookup_key)
            LIMITER.check(party)
            res = ledger_store.contact_for(DB_PATH, rid, party)
            if res is None:
                # 不存在、不是你的事、还没人认领——三种一律同一个回答，不区分。
                self._send(404, {"ok": False, "error": "not_found",
                                 "detail": "这一单不存在，或你不是它的当事人，或它还没有人认领。"})
                return
            res.update({"ok": True, "party": party, "key_fp": key_fp})
            self._send(200, res)
        except TooFast as exc:
            self._send(429, {"ok": False, "error": "DGB_ING_015",
                             "detail": "一分钟内读得太多，稍后再试"},
                       extra={"Retry-After": exc.retry_after})
        except signing.AuthError as exc:
            self._fail(exc.code, exc.detail, "contact")
        except ledger_store.WriteError as exc:
            self._fail(exc.code, exc.detail, "contact")
        except sqlite3.Error as exc:
            print("ingest sqlite error: " + traceback.format_exc(), flush=True)
            self._fail("DGB_ING_016", f"数据库拒绝：{type(exc).__name__}", "contact")

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
            # 演练开关（2026-11-15）：`?dry_run=1` 或 `X-DG-Dry-Run: 1`。
            # 两种都给，是因为有的客户端改不了 URL。**查询串不参与签名**——
            # `build_payload` 用的是去掉 `?` 之后的 path，所以加它不会让签名失效；
            # 这一点是刻意保留的：演练要是得重新签一次，就没人会去演练了。
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            env["dry_run"] = (
                qs.get("dry_run", ["0"])[0] in ("1", "true", "yes")
                or self.headers.get("X-DG-Dry-Run", "").strip() in ("1", "true", "yes"))
            if not env["dry_run"]:
                # 真写之前顺手结算一次。放在这里而不是定时任务里：写入面是唯一
                # 持 rw 的进程，也是唯一知道「现在」的地方；多一个调度器就多一个
                # 会单独坏掉、又没人看得见的部件。
                sweep_expired_quietly("写入前")
            res = op(WRITER, party, data, env)
            res.update({"ok": True, "endpoint": endpoint, "party": party, "key_fp": key_fp})
            if env["dry_run"]:
                # 必须显眼地说「没写」。否则调用方会以为已经落库，转头去查一条
                # 不存在的记录——而账本是 append-only，它会以为「查不到」是数据丢了。
                res["dry_run"] = True
                res["note"] = ("演练：校验全部跑过，事务已回滚，库与锚值未变，nonce 未消耗。"
                               "同一份请求去掉 dry_run 即为真写。")
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
    sweep_expired_quietly("启动时")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
