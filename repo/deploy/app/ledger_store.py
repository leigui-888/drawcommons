# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""账本库的落点：读（三表 → 统一条目 → 建链）与写（party / request / entry / nonce）。

**为什么读面与写面合成一个文件，而不是各写一份。**

「三张表 → 统一条目 → 建链」这一段必须只有一份实现。读面用它算锚值，写面用它算
新条目的 hash，第三方复现也用它。两份实现一旦分叉，出现的不是崩溃，而是
「写进去的 hash 与读出来的链对不上」——这种错在运营方自己的机器上永远看不见，
只有在别人拿 `examples/01-verify-chain` 重算时才暴露。所以宁可让只读服务多 import
一个文件，也不要让这条算法有第二个版本。

**写面的连接与事务。**

写入用 `BEGIN IMMEDIATE` 起手：先在库里拿到写锁，再算 `seq`、再插行。SQLite 的
`MAX(seq)+1` 不是原子操作，两个并发请求若都读到 3，第二个会被 `PRIMARY KEY` 或
触发器挡下——能挡住，但报的是「主键冲突」而不是「状态不对」，错误码因此不确定。
先拿写锁，这个竞态就不存在。

**错误码只在数据库里定义一次。** 触发器里 `RAISE(ABORT, 'DGB_LED_0xx: ...')` 抛出的
串被 `WriteError.from_sqlite` 原样解析出来，接口层再按码映射 HTTP 状态。应用层不
另写一套「什么时候该拒绝」的判断——那样就会出现两套规则，且迟早不一致。
"""

from __future__ import annotations

import datetime
import re
import sqlite3
from contextlib import contextmanager

from ledger_hash import build_chain, canonical

# 三表 → 条目类型的映射。顺序固定，`verify` 与写面都按这个顺序读。
TABLES = (("give", "ledger_give"),
          ("receive", "ledger_receive"),
          ("payback", "ledger_payback"))

# 写入面允许客户端填的列（白名单）。不在表里的键一律拒绝，理由不是「怕注入」——
# SQL 全部是参数化的——而是「列集决定条目哈希」：放过一个未定义的键，条目里就会
# 多出一个没人审过的字段，而它照样进哈希、照样进锚值。
GIVE_FIELDS = ("give_id", "mutual_id", "from_agent_id", "to_agent_id", "category",
               "quantity", "unit", "occurred_at", "note", "magnitude",
               "duration_hours", "window_expires_at")
RECEIVE_FIELDS = ("receive_id", "mutual_id", "state", "occurred_at", "evidence_uri",
                  "magnitude", "duration_hours", "window_expires_at")
PAYBACK_FIELDS = ("payback_id", "mutual_id", "occurred_at",
                  "magnitude", "duration_hours", "window_expires_at")

ENTRY_FIELDS = {"give": GIVE_FIELDS,
                "receive": RECEIVE_FIELDS,
                "payback": PAYBACK_FIELDS}

# 入账转换（第 05 步）派生出来的两个 id。**必须是纯函数**：`delivered` 那一次调用
# 与事后任何一次重放、任何一个第三方复算，都要得到同一个 id。带随机尾缀的话，
# 「这条账目是从哪张需求单来的」就只能靠库里的对应关系回答，而库在运营方手里。
DELIVERY_ID = {"give": "g-", "receive": "r-"}

# 重放时要比对的字段：都在客户端那次提交里、也都落在 delivered 行上。
# `request_id` 与 `state` 不比——它们相同才会走到那条分支。
DELIVERY_SAME_FIELDS = ("category", "need_desc", "window_expires_at", "requested_by",
                        "claim_agent_id", "evidence_uri", "occurred_at", "note")

# r6 起草时协议规则版本仍只有一个取值。第 07/08 步换版本串时**只改这一行**，
# 不在各处分散写 "pr_v1.1.0"——版本号散落是「同一事实写在两处」的典型形态。
ALLOWED_RULE_VERSIONS = ("pr_v1.1.0",)

# DGB_LED_0xx → HTTP 状态。语义错的（状态机、字段完备）是 422：
# 「语法我读懂了，但这件事按规矩不能这么写」。冲突类（换了已登记的公钥）是 409。
LED_STATUS = {"012": 403, "013": 403,          # append-only：UPDATE / DELETE 一律拒
              "014": 422, "015": 422, "016": 422,   # archive 只读 / 撤回是终态 / 实名绑定
              "017": 422, "018": 409, "019": 422, "020": 422, "021": 422,
              "023": 422, "024": 422, "025": 422, "027": 422, "028": 422,
              "030": 422, "031": 422, "032": 422, "033": 422,
              # 确认层：034 是「你给的东西自己不自洽」（payload 与重算不等、签名验不过），
              # 属请求有问题 → 400；035 是「这条已经确认过了」→ 冲突 → 409。
              "034": 400, "035": 409,
              # 拒收层：036 是「这不是你能拒的那次交付」——只有发布方能拒（v1.6）。
              # 属权限问题 → 403，不是请求格式错。
              "036": 403,
              # 条款保护：037 是「认领/交付想顺带改需求」——这版没有编辑功能，
              # 拦在状态机之前 → 422（读懂了，但按规矩不能这么写）。
              "037": 422,
              # 催告层（v1.7）：038 是「24 小时内已经催过」——不是格式错，是节奏错，
              # 客户端隔一天再来即可 → 409（冲突，不是永久拒绝）。
              # 039 是「这不是你能催的单」——只有当前认领方能催 delivered 的单 → 403。
              "038": 409, "039": 403,
              # 签名存证（v1.8）：040–042 全是**服务端自己写错了**，不是调用方填错。
              # 「这一行没声明谁写的」「http 行缺证据」「派生行带了签名」三种状态，
              # 客户端做什么都改不了它，只有改代码。所以 500 而不是 422——
              # 422 会让调用方去改自己的请求，而他改一百遍也不会好。
              "040": 500, "041": 500, "042": 500,
              # 入账转换：029 是「这一单的交付已经定局，你这次提交的字段与它不一致」。
              # 不是冲突（409 会让人以为重试一下就好了），是规矩不让——凭据以第一次为准。
              "029": 422}
# 注：`022` 已删（2026-11-15）。它一度被写成「终态不得有后继行」的码，但库里那条规则
# 由 `trg_request_transition` 统一抛 `020`，`022` 从来没被抛出过一次——文档里却有。
# 留一个永不出现的码，比没有更坏：查日志的人会去找它，而它不会出现。



def utcnow() -> str:
    """服务端时间戳：UTC、秒级、带 Z。全库同一个形状，才能被 `julianday()` 解析。"""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class WriteError(Exception):
    """写入被拒。`code` 是接口对外的那一个（DGB_LED_* 或 DGB_ING_*）。

    HTTP 状态**不在这里定**：状态码只有一处映射（`ingest.status_for`），
    否则「同一个码在两条路径上回不同的状态」迟早出现。
    """

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    @classmethod
    def from_sqlite(cls, exc: Exception) -> "WriteError":
        """把库里的拒绝翻译成确定的错误码。

        触发器抛的串自带 `DGB_LED_0xx`，直接取用；唯一/主键冲突没有码，这里补：
        `party.pubkey` 撞车说明这把公钥已属于别人（012），`request` 主键撞车说明
        这单已经存在（014），条目主键撞车说明这个 id 用过了（017）。
        """
        msg = str(exc)
        m = re.search(r"DGB_LED_(\d{3})", msg)
        if m:
            return cls(f"DGB_LED_{m.group(1)}", msg)
        if "UNIQUE constraint failed: party.pubkey" in msg:
            return cls("DGB_ING_012", "该公钥已登记在另一个主体名下")
        if "UNIQUE constraint failed: request.request_id" in msg:
            return cls("DGB_ING_014", "该 request_id 已存在；新状态请带 state 追加一行")
        if "UNIQUE constraint failed: entry_confirm" in msg:
            # 复合主键 (kind, entry_id)：一条目只允许一条确认。这里必须排在通用
            # 「UNIQUE constraint failed」之前，否则会落到兜底的 017（「ID 已被使用」），
            # 而那句话完全说不到点子上——对方会以为是 give_id 撞了。
            return cls("DGB_LED_035", "该条目已有确认；确认不可覆盖、不可重复")
        if "UNIQUE constraint failed: ingest_nonce.nonce" in msg:
            return cls("DGB_ING_005", "nonce 已被使用（重放）")
        if "UNIQUE constraint failed" in msg or "PRIMARY KEY" in msg:
            return cls("DGB_ING_017", "主键冲突：该 ID 已被使用")
        if "CHECK constraint failed" in msg:
            return cls("DGB_ING_016", f"字段取值不合约束：{msg}")
        if "NOT NULL constraint failed" in msg:
            return cls("DGB_ING_016", f"缺必填字段：{msg}")
        return cls("DGB_ING_016", msg)


# ── 签名存证（v1.8）：把「这一行是谁写的」折成五列 ───────────────────────────
EVIDENCE_TAG = "drawcommons-ingest-v1"


def _evidence_columns(evidence: dict) -> tuple:
    """`append_request(evidence=...)` 的入参校验，返回五个列值。

    库里有三条触发器守着同一件事（`040/041/042`），这里再判一遍只为把错误信息说得
    像人话——两处都判不是冗余：触发器防绕过（任何写库路径都躲不开），这里防
    「报一串 SQL 给调用方看」。

    三种输入都必须给出结论，**没有「不填」这个选项**：这一行是谁写的，是这条记录的
    一半，不是附加信息。v1.8 之前的老行留 NULL 是历史，不是模板。
    """
    if not isinstance(evidence, dict):
        raise WriteError("DGB_LED_040",
                         "append_request 必须带 evidence：{'kind': 'http'|'derived', ...}")
    kind = evidence.get("kind")
    if kind == "http":
        payload = evidence.get("payload") or ""
        sig = evidence.get("sig") or ""
        fp = evidence.get("key_fp") or ""
        if not payload or not sig or not fp:
            raise WriteError("DGB_LED_041",
                             "http 行必须同时带 payload / sig / key_fp（缺一样就不是证据）")
        if not payload.startswith(EVIDENCE_TAG + "\n"):
            # 同一把钥、另一个域（确认层 / 拒收层 / 催告层）的载荷。这种错在库里
            # 是一段格式正确的签名，只有拿它去验才会失败，而失败点离出错的地方很远。
            raise WriteError("DGB_LED_041",
                             f"载荷第一行必须是 {EVIDENCE_TAG}：这像是另一个域的签名")
        return ("http", payload, sig, fp, None)
    if kind == "derived":
        if evidence.get("sig") or evidence.get("payload"):
            raise WriteError("DGB_LED_042",
                             "派生行不能带签名：时钟与派生没有钥，签了就是伪造")
        ref = (evidence.get("ref") or "").strip() or None
        return ("derived", None, None, None, ref)
    raise WriteError("DGB_LED_040", f"未知 evidence.kind={kind!r}（只能是 http / derived）")


# ── 读：三表 → 统一条目 ──────────────────────────────────────────────────────
def entries_from(con: sqlite3.Connection) -> list[dict]:
    """把三张 append-only 表读成统一条目列表（已按**入链次序**排序）。

    `scope_unresolved=1` 时 `scope` 置 null：库里的 NULL 是「不可判定」，不是「互助」。
    排序口径与读面、写面、第三方复现三处必须一致，所以放在这里，不放在调用方。

    ── 为什么按 `ord` 排，而不是按条目内容（2026-11-26，v1.10）────────────────
    原先这里是 `entries.sort(key=canonical)`，而 `build_chain` 按这个顺序逐条算
    prev_hash/hash。两者合起来的后果是：**hash 不是写入时钉死的，是每次导出按当前
    排序重算的**。于是新条目只要在内容上排在旧条目之前，就会插进链中间，把后面每一条
    的 hash 全部重算——「只追加」就被悄悄改写成了「可重排」。

    实测后果：链路自测单 `rq_linktest01` 的两条落到了 `g-rq_reviewprivacy1` 之前，
    两条真实互助的确认（签的是旧 hash）当场验不过，第三方按我们自己的脚本会读到
    「2 条确认验不过」。

    `ord` 是不参与哈希的入链序号（见 `spec/ddl_v1.10.sql`）：排序只看它，位置就不再
    由内容推出。旧库没有这一列时全部退化成旧行为（NULL 排最后、按 canonical 兜底），
    所以「代码先上、库后迁」的窗口期只是排序退步，不会 500。
    """
    rows: list[tuple[int | None, dict]] = []
    for kind, table in TABLES:
        for row in con.execute(f"SELECT * FROM {table}"):
            d = {"type": kind}
            pk = f"{kind}_id"
            ordv = None
            for k in row.keys():
                if k == pk:
                    d["entry_id"] = row[k]
                elif k == "ord":
                    # **不进条目内容**：进了就进 canonical、就进 hash，
                    # 等于让条目自述自己在链上的位置——那不是事实，是申明。
                    ordv = row[k]
                else:
                    d[k] = row[k]
            if d.get("scope_unresolved"):
                d["scope"] = None
            rows.append((ordv, d))
    # NULL 的排最后（清单外的历史行），同 ord 不可能出现（有唯一索引），
    # 最后一档 canonical 只为让输出在异常库上也确定。
    rows.sort(key=lambda p: (p[0] is None, p[0] if p[0] is not None else 0, canonical(p[1])))
    return [d for _, d in rows]


def load_entries(db_path: str) -> list[dict]:
    """只读连接上取条目。根镜像里公开页就是这么读的（`mode=ro`）。

    `busy_timeout` 是 r6 加的：现在库里多了一个写入进程，读到一半碰上提交的窗口
    会直接 `database is locked`。等 5 秒比报 500 好，而 5 秒足够一次提交走完。
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=5000")
        return entries_from(con)
    finally:
        con.close()


def load_confirmations(db_path: str) -> list[dict]:
    """确认层：受方对 `give.hash` 的二次声明。

    **为什么不进条目表**：条目 `hash` 覆盖全部字段，而签名覆盖 `hash`。两者同表就是
    循环——加签名列会改 `hash`，`hash` 一变签名失效，签名一写 `hash` 又变。实测：插入
    确认后既有 7 条条目的 hash 一个字符没动。

    **为什么带 `pubkey`**：第三方拿到的只有导出件，没有库、没有 party 表。确认条目里
    不带公钥，验证者就必须回来问运营方「这个 party_id 的公钥是什么」——那一步一旦存在，
    「自行验证」就退回到「相信运营方」。所以公钥随确认走，`key_fp` 用于交叉核对
    （`key_fp` 必须等于 `pubkey` 的指纹，不等就是有人在换钥）。

    排序固定 `(kind, entry_id)`：导出件要能被任何语言逐字节重建，顺序不能取决于
    SQLite 的返回次序。
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=5000")
        try:
            rows = con.execute(
                "SELECT c.kind, c.entry_id, c.party_id, c.key_fp, c.sig, c.signed_at, p.pubkey "
                "FROM entry_confirm c LEFT JOIN party p ON p.party_id = c.party_id "
                "ORDER BY c.kind, c.entry_id").fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: entry_confirm" not in str(exc):
                raise
            # v1.4 之前的库没有这张表。**读在这里返回空**，是为了让「先部署代码、后跑迁移」
            # 这个错误的顺序，后果只是「锚值与页面印的不一致」，而不是「整站 502」——
            # 后者会让人以为是代码坏了，而真正的原因是一个没跑完的迁移。
            #
            # 这不等于放行写入：`ingest` 的 preflight 在缺表时直接拒绝启动，
            # 而且写入面本来就走不到这条读路径。**能读、不能写**是这里想要的方向。
            return []
    finally:
        con.close()
    out: list[dict] = []
    for r in rows:
        out.append({
            "kind": r["kind"],
            "entry_id": r["entry_id"],
            "party_id": r["party_id"],
            "key_fp": r["key_fp"],
            "pubkey": (r["pubkey"] or "").strip(),
            "sig": r["sig"],
            "signed_at": r["signed_at"],
        })
    return out


def pubkey_of(db_path: str, party_id: str) -> str | None:
    """取主体的公钥行。验签方唯一的授权来源——不在别处缓存一份。

    每次验签都读库，看起来浪费；换来的是「库里的 pubkey 改了，下一个请求立刻按新钥
    验」——而 pubkey 有 `DGB_LED_018` 兜着，其实只会从「无」变成「有」一次。
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    try:
        con.execute("PRAGMA busy_timeout=5000")
        row = con.execute("SELECT pubkey FROM party WHERE party_id=?", (party_id,)).fetchone()
    finally:
        con.close()
    return row[0] if row and row[0] else None


# ── 读：需求单（发现口，/requests 与 agent 心跳的唯一数据源） ────────────────
#
# 读的是 `v_public_request` 而不是 `request` 表。两张表的差别不是性能，是口径：
# 前者一 request_id 只留当前状态一行，且按 90 天常量把终态收窄。公开页、/requests、
# 本接口三处必须同一条口径——绕过去就等于悄悄换了一版「什么算公开」。
REQUEST_STATES = ("open", "claimed", "delivered", "closed", "withdrawn", "expired")

# 没填 `window_expires_at` 时按「发布后多少天」到期（v1.6，2026-11-16）。
# 与终态留存的 90 天数值相同但彼此独立：一个是「还能放多久」，一个是「过期后还留多久」。
# 常量不是条款——改它不换版；改「要不要默认期限」才换版。
UNCLAIMED_DEFAULT_DAYS = 90

# 接单窗口的最长天数。与上面那个是**同一个数**的两个用法，所以由它派生而不是另写一个 90：
#   不填截止 → 从发布起算 90 天到期；
#   填了截止 → 不得晚于发布 + 90 天（写口 `op_request` 拦，页面也拦同一个数）。
# 分成两个独立常量的话，某天只改一个就会出现「不填能挂 90 天、填了能挂 365 天」这种矛盾。
MAX_WINDOW_DAYS = UNCLAIMED_DEFAULT_DAYS

# 认领与交付时**不允许改**的条款字段。这版没有编辑功能，任何一条推进状态的路径
# 都不该成为改需求的暗门（`claimed → open` 的回退同理，见 ingest.op_request）。
# 不包含 `claim_agent_id`：那一列在 `claimed` 行是**新填**的，比对它必然不等。
# 不包含 `evidence_uri` / `occurred_at`：那是交付这一次的新值。
TERMS_FIELDS = ("category", "need_desc", "window_expires_at", "note")

# 游标带版本前缀。将来若要换键（比如加 seq），旧客户端手里的 `c1.` 会被明确拒绝，
# 而不是被当成新格式解析出一个「看起来对、其实错位」的位置。
CURSOR_PREFIX = "c1."
CURSOR_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def encode_cursor(created_at: str, request_id: str) -> str:
    """游标 = `(created_at, request_id)`。

    不用 `seq`：视图里一个 request_id 只有一行，二元组已经唯一。也不用 offset——
    offset 在 append-only 表上遇到并发插入会漏行，而漏掉的需求单不会报错，
    只会「谁都没看见」，这比报错难查得多。
    """
    return f"{CURSOR_PREFIX}{created_at}~{request_id}"


def decode_cursor(raw: str) -> tuple[str, str]:
    """坏游标抛 `ValueError`，调用方回 400。

    **绝不宽容解析成「从头开始」**：那会让客户端以为拿到了增量，其实每次都在
    重放全量，而它永远不会知道——这种静默降级是游标接口最常见的坏法。
    """
    if not raw.startswith(CURSOR_PREFIX):
        raise ValueError(f"游标版本前缀应为 {CURSOR_PREFIX}")
    at, sep, rid = raw[len(CURSOR_PREFIX):].partition("~")
    if not sep or not rid:
        raise ValueError("游标应为 <created_at>~<request_id>")
    if not CURSOR_TIME_RE.match(at):
        raise ValueError("游标里的时间不是 YYYY-MM-DDTHH:MM:SSZ")
    if not rid.startswith("rq_") or not 11 <= len(rid) <= 35:
        raise ValueError("游标里的 request_id 形状不对")
    return at, rid


def load_request_page(db_path: str, *, since: tuple[str, str] | None = None,
                      state: str | None = None, limit: int = 20) -> dict:
    """一页需求单。

    两种调用方式，语义不同，不要混：

    - **不带 `since`**：给「最近这些」，按时间倒序取 limit 条后翻正。新来的 agent
      第一次就该是这样——它要的是「现在有什么可接的」，不是三年前的第一条。
    - **带 `since`**：给「游标之后追加的」，正序。心跳场景。

    一单从 `open` 变 `claimed` 时，当前行的 `created_at` 会变新，因此它会**再出现
    一次**——这是通知，不是重复：调用方按 `request_id` 折叠即可。反过来，靠
    「记住见过的 request_id」去重会漏掉状态变化，那才是真正的漏。
    """
    if limit < 1 or limit > 200:
        raise ValueError("limit 必须在 1..200")

    where: list[str] = []
    params: list = []
    if since is not None:
        where.append("(created_at, request_id) > (?, ?)")
        params.extend(since)
    if state is not None:
        if state not in REQUEST_STATES:
            raise ValueError(f"未知 state={state}")
        where.append("state = ?")
        params.append(state)

    sql = "SELECT * FROM v_public_request"
    if where:
        sql += " WHERE " + " AND ".join(where)

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=5000")
        # 多取一行判「还有没有」：比 count(*) 便宜，也不会因为并发插入给出一个
        # 与本次结果不一致的数字。
        if since is not None:
            rows = con.execute(sql + " ORDER BY created_at, request_id LIMIT ?",
                               params + [limit + 1]).fetchall()
        else:
            rows = con.execute(sql + " ORDER BY created_at DESC, request_id DESC LIMIT ?",
                               params + [limit + 1]).fetchall()
            rows = list(reversed(rows))   # 翻正后，多出来的那一条在最前面
    finally:
        con.close()

    has_more = len(rows) > limit
    if has_more:
        rows = rows[1:] if since is None else rows[:limit]

    if rows:
        next_cursor = encode_cursor(rows[-1]["created_at"], rows[-1]["request_id"])
    else:
        # 没有新行时把游标原样退回：调用方下次拿同一个游标来，不会跳过一个空窗。
        next_cursor = encode_cursor(*since) if since is not None else None

    return {
        "items": [dict(r) for r in rows],
        "count": len(rows),
        "has_more": has_more,
        "next_cursor": next_cursor,
    }


# ── 读：一单的全部（/r/<id> 的唯一数据源）─────────────────────────────────────
def load_request_detail(db_path: str, request_id: str) -> dict | None:
    """一单的当前状态、全部状态行、以及它那一对账目（若有）。

    读的是 `request` 全表而不是 `v_public_request`：`/r/<id>` 的承诺是**永久可访问**，
    而公开视图会把终态 90 天后的行从列表里收窄掉。这两件事不矛盾——列表收窄是为了
    不把 `needs` 堆成坟场，单据本身仍然一直都在。

    账目的 hash 从 `build_chain` 重算，不读表（表里没有这一列）。这一页因此与
    `/api/ledger/items`、第三方复现是同一个 hash 口径，三处不会各说各话。
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=5000")
        hist = con.execute("SELECT * FROM request WHERE request_id=? ORDER BY seq",
                           (request_id,)).fetchall()
        if not hist:
            return None
        mutual = "m-" + request_id
        pair = [e for e in build_chain(entries_from(con))
                if e.get("mutual_id") == mutual]
        confs: dict[tuple, dict] = {}
        try:
            for row in con.execute("SELECT kind, entry_id, party_id, signed_at, key_fp"
                                   " FROM entry_confirm ORDER BY kind, entry_id"):
                confs[(row["kind"], row["entry_id"])] = dict(row)
        except sqlite3.OperationalError as exc:
            if "no such table: entry_confirm" not in str(exc):
                raise
        for e in pair:
            e["confirmed"] = confs.get((e["type"], e["entry_id"]))

        # 拒收层（v1.6 / 多轮 v1.7）。表可能不存在——与上面 `entry_confirm`
        # 同样的容错：旧库升到一半时，单页不该整页 500，只是「没有拒收记录」。
        # 单页要按**轮次**列：一张被拒过两次的单，只显示最后一条会让人以为
        # 中间那次交付没被拒过。
        rejects: list[dict] = []
        try:
            rows = con.execute(
                "SELECT seq, party_id, key_fp, reason, signed_at FROM request_reject"
                " WHERE request_id=? ORDER BY seq", (request_id,)).fetchall()
            rejects = [dict(r) for r in rows]
        except sqlite3.OperationalError as exc:
            if "no such table: request_reject" not in str(exc):
                raise
        reject = rejects[-1] if rejects else None

        # 催告层（v1.7）：同样容错，旧库没有这张表时单页照常。
        reminders: list[dict] = []
        try:
            rows = con.execute(
                "SELECT seq, party_id, key_fp, signed_at FROM request_reminder"
                " WHERE request_id=? ORDER BY signed_at", (request_id,)).fetchall()
            reminders = [dict(r) for r in rows]
        except sqlite3.OperationalError as exc:
            if "no such table: request_reminder" not in str(exc):
                raise

        # 交付之后等了几天还没被确认。口径与 `v_public_request.unconfirmed_days`
        # 一致（都从本行 `created_at` 起算、CAST 取整而不是四舍五入），否则
        # 列表与单页会对同一张单给出相差一天的数字。非 delivered 一律 None：
        # 那时候问「几天没确认」没有意义。
        cur = hist[-1]
        unconfirmed = None
        if cur["state"] == "delivered":
            unconfirmed = con.execute(
                "SELECT CAST(COALESCE(julianday('now') - julianday(?), 0) AS INTEGER)",
                (cur["created_at"],)).fetchone()[0]

        # 联系方式（v1.7）在这里**剥掉**，不进单页数据。
        # `/r/<id>` 是匿名可读的（没有登录，站点也禁脚本），任何进到这个结构里的
        # 邮箱都会被渲染成公开页面上的一行。要联系方式的人走 `contact_for()`
        # ——那条路要签名，且只给这条单的两方。
        hist_out = []
        for r in hist:
            d = dict(r)
            d.pop("poster_email", None)
            d.pop("claimer_email", None)
            hist_out.append(d)
        cur_out = dict(cur)
        cur_out.pop("poster_email", None)
        cur_out.pop("claimer_email", None)

        return {"request_id": request_id,
                "current": cur_out,
                "history": hist_out,
                "entries": pair,
                "reject": reject,
                "rejects": rejects,
                "reminders": reminders,
                "unconfirmed_days": unconfirmed}
    finally:
        con.close()


# ── 签名存证（v1.8）：读 ────────────────────────────────────────────────────
def split_signed_payload(payload: str) -> dict:
    """把逐字载荷拆成七行。**只为好读**，验签必须用原串（`payload` 整段）。

    拆出来的东西不能反过来拼回载荷——拼回去只要差分一个换行，验签就永远失败，
    而那看起来像「证据坏了」。所以返回体里既给拆开的字段，也给原文。
    """
    lines = (payload or "").split("\n")
    if len(lines) < 7:
        return {}
    return {"tag": lines[0], "method": lines[1], "path": lines[2], "signer": lines[3],
            "issued": lines[4], "nonce": lines[5], "body_sha256": lines[6]}


def load_request_evidence(db_path: str, request_id: str) -> dict | None:
    """一单的全部状态行 + 每一行的签名存证 + 签名者的公钥。没有这张单返回 None。

    **返回的是能离线复验的原料**，不是本站的判断：逐字载荷、SSHSIG 原文、公钥行。
    `serve` 那一侧再附一句「照这条命令跑」，本站说「验过了」不算数——这正是
    存证与「我们相信我们的代码」之间的差别。

    旧库（v1.7 及之前）没有这五列：`sqlite3.OperationalError` 原样抛给调用方，
    由它决定回 503 还是别的。这里**不吞**——吞掉会变成「一单没有存证」，
    而那是另一个意思（v1.8 之前的行确实没有，但那是逐行的，不是整站读不出）。
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=5000")
        rows = con.execute(
            "SELECT seq, state, created_at, requested_by, claim_agent_id,"
            " sig_kind, sig_payload, sig, sig_key_fp, sig_ref"
            " FROM request WHERE request_id=? ORDER BY seq", (request_id,)).fetchall()
        if not rows:
            return None
        out = []
        signers: set[str] = set()
        for r in rows:
            d = dict(r)
            kind = d.pop("sig_kind")
            raw = d.pop("sig_payload")
            sig = d.pop("sig")
            d["key_fp"] = d.pop("sig_key_fp")
            d["ref"] = d.pop("sig_ref")
            d["evidence"] = kind or "none"
            # `none` 只可能是 v1.8 之前写下的行：那时不存，现在补不出来（旧行禁改）。
            d["payload"] = raw
            d["sig"] = sig
            d["signed"] = split_signed_payload(raw) if raw else {}
            if kind == "http" and d["signed"].get("signer"):
                signers.add(d["signed"]["signer"])
            out.append(d)
        keys = {}
        for pid in sorted(signers):
            row = con.execute("SELECT pubkey FROM party WHERE party_id=?",
                              (pid,)).fetchone()
            keys[pid] = (row["pubkey"] if row else None)
        return {"request_id": request_id, "rows": out, "pubkeys": keys}
    finally:
        con.close()


def contact_for(db_path: str, request_id: str, party_id: str) -> dict | None:
    """取一单的联系方式，**只给这条单的两方**，且只在认领成立之后。

    这是「双方认领后才可见」这句话唯一的实现。页面上做不了：`/r/<id>` 匿名可读、
    站点 `script-src 'none'`，浏览器里没有可验证的身份，把邮箱渲染上去就是公开。
    所以它走写口那套签名——谁在问，由 `X-DG-Party` 与信封签名决定，而不是由
    一个查询参数决定。

    返回 None 的三种情况（对外一律同一个回答，不区分）：
      · 单子不存在；
      · 问的人既不是发布方也不是当前认领方；
      · 还没人认领（`open` / `withdrawn` / `expired`）。

    区分它们就等于给了一个探测接口：「这个 id 存在吗」「谁接过这单」。
    两方拿到的是同一个结构，各自那一格也在里面——没有「只能看对方」的遮蔽，
    因为本人本来就知道自己的地址，遮掉只会让客户端多一个特判。
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA busy_timeout=5000")
        cur = con.execute("SELECT * FROM v_request_current WHERE request_id=?",
                          (request_id,)).fetchone()
        if cur is None:
            return None
        if cur["state"] not in ("claimed", "delivered", "closed"):
            return None
        if party_id not in (cur["requested_by"], cur["claim_agent_id"]):
            return None
        return {"request_id": request_id,
                "state": cur["state"],
                "requested_by": cur["requested_by"],
                "claim_agent_id": cur["claim_agent_id"],
                "poster_email": cur["poster_email"],
                "claimer_email": cur["claimer_email"]}
    finally:
        con.close()


# ── 写：事务 ─────────────────────────────────────────────────────────────────
class Writer:
    """写入面的库句柄。一次请求一个事务，`BEGIN IMMEDIATE` 起手。"""

    def __init__(self, db_path: str):
        self.db_path = db_path

    @contextmanager
    def tx(self, commit: bool = True):
        """一次请求一个事务。`commit=False` 是演练：跑完全部校验与写入，然后回滚。

        **为什么不是「先校验、不写」**：那等于把校验逻辑复制一份到事务之外，两份迟早
        不一致，而演练的价值恰恰是「和真写走同一条路」。ROLLBACK 让同一段代码既验证
        约束、又保证一个字节都不落下。

        连带的语义：nonce 也会被回滚，所以**演练不消耗 nonce**——同一个 nonce 可以
        演练多次再真写。这不是漏洞：nonce 防的是重放已提交的请求，而演练没提交任何东西。
        """
        con = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=8000")
        con.execute("BEGIN IMMEDIATE")
        try:
            yield con
        except sqlite3.IntegrityError as exc:
            # 库自己的拒绝在**这一层**翻成确定的错误码。放到接口层翻会让每条 SQL
            # 都得记着包一层 try；漏一处就是「触发器拦住了，但对外报的是兜底码」。
            con.execute("ROLLBACK")
            con.close()
            raise WriteError.from_sqlite(exc) from None
        except BaseException:
            con.execute("ROLLBACK")
            con.close()
            raise
        con.execute("COMMIT" if commit else "ROLLBACK")
        con.close()

    # ── 主体公钥 ────────────────────────────────────────────────────────────
    def register_party(self, con, party_id: str, pubkey: str, display_mode: str = "pseudonymous") -> dict:
        """登记主体公钥。三种情形分开返回，因为它们的后果不同：

        · 新主体 → 建行；
        · 老主体还没登记过公钥 → 挂上去（此后不可换，`DGB_LED_018`）；
        · 老主体已登记同一把钥 → 幂等成功，不改任何字节（写时间戳也算改字节）。

        幂等这一条不是顺手加的：客户端重试一次不该把 `updated_at` 推着走，
        否则「主体何时更新过」这条信息会被重试噪声填满。
        """
        now = utcnow()
        row = con.execute("SELECT pubkey FROM party WHERE party_id=?", (party_id,)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO party(party_id, display_mode, updated_at, pubkey, pubkey_added_at)"
                " VALUES(?,?,?,?,?)", (party_id, display_mode, now, pubkey, now))
            return {"created": True, "attached": True}
        old = row["pubkey"]
        if old is None or not str(old).strip():
            con.execute(
                "UPDATE party SET pubkey=?, pubkey_added_at=?, updated_at=? WHERE party_id=?",
                (pubkey, now, now, party_id))
            return {"created": False, "attached": True}
        if str(old).strip() != pubkey.strip():
            raise WriteError("DGB_LED_018", "该主体已登记另一把公钥；换钥 = 换 party_id")
        return {"created": False, "attached": False}

    # ── 需求单 ──────────────────────────────────────────────────────────────
    def append_request(self, con, body: dict, evidence: dict) -> dict:
        """追加一行需求状态。`seq` 与 `created_at` 由服务端算，不接受客户端自带。

        `created_at` 记的是**本行落库时间**，不是首行时间。公开视图的 90 天规则
        作用在终态行上，因此「终态之后 90 天从列表隐藏」才成立；若沿用首行时间，
        一张挂了两年的单子刚关闭就会立刻消失。

        `poster_email` / `claimer_email`（v1.7）跟着行一起写：这两列是「本行这一方
        留下的联系方式」，不是 `party` 的属性。追加行时由调用方决定填什么——
        沿用上一行、置空、或者新填（认领那一刻才第一次有认领方邮箱）。

        `evidence`（v1.8，**必填**）说明这一行是谁写的：

            {"kind": "http", "payload": str, "sig": str, "key_fp": str}
                客户端签名请求直接写的行。载荷逐字来自那次请求（`signing.verify`
                算出来的那一段），签名与指纹同源。
            {"kind": "derived", "ref": "clock" | "confirm:<entry_id>"}
                服务端派生的行：时钟结算的 `expired`、确认派生的 `closed`。
                这两类没有自己的签名，**不许**带签名（库里 `DGB_LED_042` 拦）。

        为什么必填而不是可选：可选等于「以后会有人忘」，而忘了之后库里多出来的那一行
        与别的行长得一模一样，只有专门去查才发现。库里 `trg_request_sig_required`
        与这里各判一次——库里的那条是底线，这里的这条只为把错误信息说得更像人话。
        """
        rid = body["request_id"]
        sig_cols = _evidence_columns(evidence)
        seq = con.execute(
            "SELECT COALESCE(MAX(seq),0)+1 FROM request WHERE request_id=?", (rid,)
        ).fetchone()[0]
        now = utcnow()
        con.execute(
            "INSERT INTO request(request_id, seq, state, category, need_desc, window_expires_at,"
            " requested_by, claim_agent_id, evidence_uri, occurred_at, created_at, note,"
            " poster_email, claimer_email, sig_kind, sig_payload, sig, sig_key_fp, sig_ref)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, seq, body["state"], body["category"], body["need_desc"],
             body.get("window_expires_at") or "", body["requested_by"],
             body.get("claim_agent_id"), body.get("evidence_uri"),
             body.get("occurred_at"), now, body.get("note"),
             body.get("poster_email") or None, body.get("claimer_email") or None,
             *sig_cols))
        return {"request_id": rid, "seq": seq, "created_at": now,
                "evidence": evidence.get("kind")}

    # ── 账目条目 ────────────────────────────────────────────────────────────
    def append_entry(self, con, kind: str, body: dict) -> dict:
        """追加一条账目，并返回它在链上的位置与哈希。

        哈希必须在**同一事务内**算：`hash` 依赖 `prev_hash`，而 `prev_hash` 依赖排序后
        的前一条。提交之后再算，中间插进来的一条会让返回的哈希作废，而客户端拿它去
        签名（第 04 步的双签）就会签在一个已经不存在的链位置上。
        """
        cols = ENTRY_FIELDS[kind]
        unknown = sorted(set(body) - set(cols) - {"kind", "rule_version"})
        if unknown:
            raise WriteError("DGB_ING_018", f"不认识的字段：{', '.join(unknown)}")
        values = {k: body[k] for k in cols if k in body}
        if kind == "give" and "occurred_at" not in values:
            raise WriteError("DGB_ING_009", "give 必须带 occurred_at")
        if kind in ("receive", "payback") and "occurred_at" not in values:
            raise WriteError("DGB_ING_009", f"{kind} 必须带 occurred_at")
        rv = body.get("rule_version", ALLOWED_RULE_VERSIONS[0])
        if rv not in ALLOWED_RULE_VERSIONS:
            raise WriteError("DGB_ING_019", f"未知 rule_version={rv}")
        if "rule_version" not in cols:
            values["rule_version"] = rv
        # scope 不接受客户端指定：它由 mutual_id 是否可判定推出，与 ddl_w4.sql v1.2 的
        # 一次性回填同一条规则。写成「客户端说了算」就等于允许一条没有 mutual_id 的
        # 条目自称 mutual——那正是 scope 这个列当初要解决的问题。
        mutual = values.get("mutual_id")
        if mutual and str(mutual).strip():
            values["scope"], values["scope_unresolved"] = "mutual", 0
        else:
            values["scope"], values["scope_unresolved"] = None, 1
        # ── 入链次序（v1.10）───────────────────────────────────────────────
        # 三表共享一个序列：取三表现有最大 ord 加一。由服务端分配，客户端指定不了
        # ——`ord` 不在 ENTRY_FIELDS 白名单里，带了会被上面的 DGB_ING_018 拒掉。
        # 库还没跑 v1.10 时退回旧行为（不写这一列）：窗口期只是排序退步，不会 500。
        # 这也正是 2026-11-25 那次事故的教训——加列要么在 preflight 里喊，要么在代码里让路，
        # 不能假定「库一定跟上了」。
        have_cols = {r[1] for r in con.execute(f"PRAGMA table_info(ledger_{kind})")}
        if "ord" in have_cols:
            values["ord"] = con.execute(
                "SELECT COALESCE(MAX(ord), 0) + 1 FROM ("
                " SELECT ord FROM ledger_give UNION ALL"
                " SELECT ord FROM ledger_receive UNION ALL"
                " SELECT ord FROM ledger_payback)").fetchone()[0]
        names = ",".join(values)
        marks = ",".join("?" * len(values))
        con.execute(f"INSERT INTO ledger_{kind}({names}) VALUES({marks})", tuple(values.values()))

        chain = build_chain(entries_from(con))
        eid = values.get(f"{kind}_id")
        hit = [i for i, e in enumerate(chain)
               if e["type"] == kind and e.get("entry_id") == eid]
        if not hit:
            raise WriteError("DGB_ING_016", "条目已写入但没能在链上定位（不应发生）")
        i = hit[0]
        return {"entry_id": eid, "index": i, "chain_length": len(chain),
                "hash": chain[i]["hash"], "prev_hash": chain[i]["prev_hash"]}

    # ── 确认层 ──────────────────────────────────────────────────────────────
    def chain_hash_of(self, con, kind: str, entry_id: str) -> str | None:
        """取某条目在**当前链上**的 hash；不存在返回 None。

        不直接读表里的「hash」列——条目表里没有这一列。hash 是 `build_chain` 按排序位置
        算出来的，读端也是这么算的，所以这里必须重算一遍；缓存或另存一份，就会出现
        「确认时用的 hash」与「验证者重算的 hash」两个来源，而它们迟早不一致。

        代价是每次确认重建一次整条链。这在本项目的量级上是毫秒级，且**正确性优先**：
        一条确认签错了 hash，事后无法补救（确认不可覆盖、不可撤销）。
        """
        for e in build_chain(entries_from(con)):
            if e["type"] == kind and e.get("entry_id") == entry_id:
                return e["hash"]
        return None

    def insert_confirm(self, con, kind: str, entry_id: str, party_id: str,
                       key_fp: str, payload: str, sig: str) -> dict:
        """落一条确认。`signed_at` 由服务端盖章。

        客户端自带的 `signed_at` 一律不采信：确认的时点是「服务端收到并验过的那一刻」，
        让客户端填就等于允许把一条今天的确认写成去年的。库里的 `payload` 存**服务端
        重算的值**（调用方保证它来自 `chain_hash_of`），不是客户端交上来的那段。

        `payload` 仍存全文：它是审计时唯一能回答「当时签的到底是哪三个东西」的字段，
        而它不进导出件（导出件的确认里没有 payload，验证者按规则自己重建）。
        """
        con.execute(
            "INSERT INTO entry_confirm(kind, entry_id, party_id, key_fp, payload, sig, signed_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (kind, entry_id, party_id, key_fp, payload, sig, utcnow()))
        return {"kind": kind, "entry_id": entry_id, "party_id": party_id, "key_fp": key_fp}

    # ── 拒收层（v1.6 / 多轮 v1.7）：受方对一次交付说「不认」─────────────────
    def current_reject(self, con, request_id: str, seq: int | None = None):
        """某一轮的那条拒收记录；`seq` 省略时取最新一轮。没有则 None。

        v1.6 一单只有一条，`WHERE request_id` 就够；v1.7 允许多轮交付，同一张单
        可能有多条拒收记录，于是「当前」必须由 seq 指明——只用 request_id 取
        `fetchone()` 会拿到任意一条（SQLite 通常给第一条），而调用方会把它当成
        「这次交付被拒了」的证据，指错轮次。
        """
        if seq is None:
            return con.execute(
                "SELECT * FROM request_reject WHERE request_id=? ORDER BY seq DESC LIMIT 1",
                (request_id,)).fetchone()
        return con.execute(
            "SELECT * FROM request_reject WHERE request_id=? AND seq=?",
            (request_id, seq)).fetchone()

    def rejects_of(self, con, request_id: str) -> list[dict]:
        """这张单的全部拒收记录，按轮次升序。单页要把每一轮都列出来。"""
        try:
            rows = con.execute(
                "SELECT seq, party_id, key_fp, reason, signed_at FROM request_reject"
                " WHERE request_id=? ORDER BY seq", (request_id,)).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: request_reject" not in str(exc):
                raise
            return []
        return [dict(r) for r in rows]

    def insert_reject(self, con, request_id: str, seq: int, party_id: str,
                      key_fp: str, payload: str, sig: str, reason: str | None) -> dict:
        """落一条拒收。`signed_at` 服务端盖章，`payload` 存服务端重算值。

        **它不改需求单的状态。** 交付那一刻 give 与 receive 已经入链，账本 append-only
        撤不回来；把单子改成别的状态会让人以为「这次交付被取消了」。拒收能做的只有
        一件事：把「沉默」变成「有签名、有理由、可查询的拒绝」。状态仍停在 delivered，
        `/r/<id>` 上多一行「受方已拒收」。

        签名签的是 `request_id + seq`（被拒的那条 delivered 行），不是这条记录自己——
        签自己等于签一句自述，签那一行才指着一项事实。载荷由服务端按库里那一行重算。
        """
        con.execute(
            "INSERT INTO request_reject(request_id, seq, party_id, key_fp, payload, sig,"
            " reason, signed_at) VALUES(?,?,?,?,?,?,?,?)",
            (request_id, seq, party_id, key_fp, payload, sig, reason, utcnow()))
        return {"request_id": request_id, "seq": seq, "party_id": party_id,
                "key_fp": key_fp, "reason": reason}

    # ── 催告层（v1.7）：认领方说一句「请你看一眼」───────────────────────────
    def last_reminder_at(self, con, request_id: str, party_id: str) -> str | None:
        """同一个人对同一张单最近一次催告的时刻；没有则 None。

        应用层用它给出「还差几个小时」的人话；真正的门槛在触发
        `trg_request_reminder_cooldown` 里——这里只是让错误信息的版本更好读。
        两处都判不是冗余：触发器防绕过，这里防「报一个触发器原文给用户」。
        """
        try:
            row = con.execute(
                "SELECT MAX(signed_at) FROM request_reminder"
                " WHERE request_id=? AND party_id=?", (request_id, party_id)).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table: request_reminder" not in str(exc):
                raise
            return None
        return row[0] if row and row[0] else None

    def insert_reminder(self, con, request_id: str, seq: int, party_id: str,
                        key_fp: str, payload: str, sig: str) -> dict:
        """落一条催告。`signed_at` 服务端盖章，`payload` 存服务端重算值。

        **它不改需求单的状态，也不改条款。** 催告是「这次交付还没被确认」这件事的
        一条签名断言：它让发布方那一侧的「等确认」有一个可查的次数与时刻，而不是
        只剩沉默。单子仍在 delivered，下一步仍只有发布方能走（确认或拒收）。
        """
        now = utcnow()
        con.execute(
            "INSERT INTO request_reminder(request_id, seq, party_id, key_fp, payload,"
            " sig, signed_at) VALUES(?,?,?,?,?,?,?)",
            (request_id, seq, party_id, key_fp, payload, sig, now))
        return {"request_id": request_id, "seq": seq, "party_id": party_id,
                "key_fp": key_fp, "signed_at": now}

    def reminders_of(self, con, request_id: str) -> list[dict]:
        """这张单收到过的全部催告，按时间升序。单页与两侧管理页都用它。"""
        try:
            rows = con.execute(
                "SELECT seq, party_id, key_fp, signed_at FROM request_reminder"
                " WHERE request_id=? ORDER BY signed_at", (request_id,)).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table: request_reminder" not in str(exc):
                raise
            return []
        return [dict(r) for r in rows]

    # ── 入账转换（第 05 步）：一次 delivered，两条账目 ────────────────────────
    def current_request(self, con, request_id: str):
        """当前状态行（视图口径，与公开页、读口同一份）。没有则 None。"""
        return con.execute("SELECT * FROM v_request_current WHERE request_id=?",
                           (request_id,)).fetchone()

    def sweep_expired(self, con) -> list[dict]:
        """把「到期仍未结」的单写成 `expired`，返回写了哪几单。

        这是 `→ expired` 唯一的写入者。它不是一个角色，是一个时钟：没有调用方
        能指名「让哪一单过期」，也没有请求体能带这个意图进来（`expired` 在写口仍是
        `DGB_ING_011`）。候选只由库里那几列决定，同一次调用跑两遍，第二遍查不到候选。

        **候选两支（v1.6 起）与两种状态（v1.7 起）：**

        a) 填了 `window_expires_at`：过了那个时刻即到期——v1.5 起就是这样；
        b) 没填（空串）：按 `created_at + UNCLAIMED_DEFAULT_DAYS` 到期。

        v1.6 只扫 `open`，`claimed` 那一支刻意不碰：当时的理由是「已经有人接了，
        时钟不该替他撤销约定」。那句话在页面上留下了一个死角——认领方接了单一直不交，
        单子永远停在「已认领」，发布方等到截止也等不到任何下一步，而 `sweep` 每跑一次
        都从它身上跨过去。v1.7 把 `claimed` 纳入：到期同样写 `expired`。

        **为什么写 `expired` 而不是 `withdrawn`。** 两者在页面上都读作「不能接了」，
        但在账上是两件事：`withdrawn` 是发布方签名的意思表示，`expired` 是期限到了。
        时钟没有签名，替发布方写一条「他撤回了」就是伪造一条他没说过的意思表示。
        作废是时钟唯一有资格做的事。

        **claimed 的到期时刻怎么算。** 口径与 `open` 一字不差：填了截止就是那个时刻，
        空串就是「本行 `created_at` + 90 天」。claimed 行的 `created_at` 是认领时刻
        （`v_request_current` 取当前行整行），所以空串在这里读作「认领后 90 天」——
        不是「发布后 90 天」。这两者不必统一：`open` 的空串是「没人接，挂牌多久」，
        `claimed` 的空串是「有人接了，给他多久」。同一个常数，两段不同的时间。

        **只认能解析的时间。** `julianday()` 解析不了返回 NULL，比较得 NULL，WHERE 视作
        不成立——格式坏的单会被跳过，不会被误判成「已到期」。方向必须是「宁可留着」，
        因为 `expired` 是终态，写错了没有回头路（append-only）。
        """
        now = utcnow()
        rows = con.execute(
            "SELECT * FROM v_request_current"
            " WHERE state IN ('open','claimed')"
            " AND ("
            "   (TRIM(COALESCE(window_expires_at, '')) <> ''"
            "    AND julianday(window_expires_at) IS NOT NULL"
            "    AND julianday('now') > julianday(window_expires_at))"
            "   OR"
            "   (TRIM(COALESCE(window_expires_at, '')) = ''"
            "    AND julianday(created_at) IS NOT NULL"
            "    AND julianday('now') - julianday(created_at) > ?)"
            " )"
            " ORDER BY request_id",
            (UNCLAIMED_DEFAULT_DAYS,)).fetchall()
        out = []
        for r in rows:
            seq = r["seq"] + 1
            con.execute(
                "INSERT INTO request(request_id, seq, state, category, need_desc,"
                " window_expires_at, requested_by, claim_agent_id, evidence_uri,"
                " occurred_at, created_at, note, poster_email, claimer_email,"
                " sig_kind, sig_ref)"
                " VALUES(?,?,'expired',?,?,?,?,?,?,?,?,?,?,?,'derived','clock')",
                (r["request_id"], seq, r["category"], r["need_desc"], r["window_expires_at"],
                 r["requested_by"], r["claim_agent_id"], r["evidence_uri"],
                 r["occurred_at"], now, r["note"], r["poster_email"], r["claimer_email"]))
            out.append({"request_id": r["request_id"], "seq": seq,
                        "from_state": r["state"]})
        return out

    def mutual_entries(self, con, mutual_id: str) -> dict:
        """一次互助应有的两条，按类型取原始行。缺哪条就是哪条为 None。"""
        return {kind: con.execute(f"SELECT * FROM ledger_{kind} WHERE mutual_id=?",
                                  (mutual_id,)).fetchone()
                for kind in ("give", "receive")}

    def convert_delivery(self, con, request_id: str) -> dict:
        """把一条已落库的 `delivered` 行转成 `give` + `receive` 两条账目。

        **输入只取库里那一行，不取请求体。** 请求体在 `append_request` 之后就不再是
        权威了（服务端盖了 `created_at`、算了 `seq`），而转换的产物是要进哈希链的。
        拿请求体去派生，等于让两条记录有两个来源——重放一次、换个客户端重发一次，
        就可能派生出不一样的字节，而链上已经有一条了。

        **为什么是两条，不是一条。** `give` 记「谁给了谁什么」，`receive` 记「这次交付
        有凭据」。凭据列 `evidence_uri` 只存在于 `receive`：放进 `give` 会让「给了什么」
        与「凭什么说给了」混在同一行，而这两件事的举证方不同——前者是给方自述，
        后者要受方认（第 04 步的确认签的正是这条 `give` 的 hash）。

        **两条同 `mutual_id`，所以同一次互助在账本里是一对。** `m-<request_id>` 是派生的，
        不是发号器发的：从任一账目都能反查那张需求单，且不必多一张映射表。

        **计量列留空而不是填 0。** 需求单只有 `need_desc` 没有数量字段，所以
        `quantity`/`unit` 是 NULL（`magnitude` 落到列默认值 0，那是 `ddl_w4.sql` 的既有
        形状：0 表示未计量）。把不知道的数写成 0，事后没人能把它与「真的是零」分开。
        """
        row = self.current_request(con, request_id)
        if row is None:
            raise WriteError("DGB_LED_029", f"需求单 {request_id} 不存在，无法转换")
        if row["state"] not in ("delivered", "closed"):
            # 只有交付过的单子才有账目可生成。状态机允许的路径里不会走到这里；
            # 走到了说明有人绕过接口直接改了库。
            raise WriteError("DGB_LED_029",
                             f"需求单当前是 {row['state']}，只有 delivered / closed 才有账目")
        claimer = row["claim_agent_id"]
        if not claimer or not str(claimer).strip():
            raise WriteError("DGB_LED_029", "delivered 行没有 claim_agent_id，无法判定给方")

        mutual = "m-" + request_id
        # 第几次交付（v1.7）。第一次沿用历史 id（`g-rq_...` / `r-rq_...`），
        # 第二次起带 `-d<n>` 后缀。为什么不给所有交付都加后缀：库里已有的条目
        # 就叫 `g-rq_...`，改格式等于让历史条目换 id，而链上的 id 是不可改的。
        # 两种格式并存不是妥协，是「旧的那一次已经发生过」的必然形状。
        give_id, receive_id, round_no = self.delivery_ids(con, request_id, row["seq"])
        if round_no < 1:
            raise WriteError("DGB_LED_029", "交付行不存在，无法生成账目")

        # give：认领方（提交 delivered 的那一方，也就是签名主体）给发布方。
        # 这一条与 `/api/v1/entry` 的「give 的给方必须就是签名者本人」是同一个规则，
        # 不是例外——转换用的就是那张单子的签名。
        self.append_entry(con, "give", {
            "give_id": give_id,
            "mutual_id": mutual,
            "from_agent_id": claimer,
            "to_agent_id": row["requested_by"],
            "category": row["category"],
            "quantity": None,
            "unit": None,
            "occurred_at": row["occurred_at"],
            "note": None,
        })
        # receive：交付这件事本身的凭据侧。state 固定 'delivered'——它记的是「已交付」，
        # 不随后续状态变化改写（append-only，且 `receive` 没有确认这一档）。
        self.append_entry(con, "receive", {
            "receive_id": receive_id,
            "mutual_id": mutual,
            "state": "delivered",
            "occurred_at": row["occurred_at"],
            "evidence_uri": row["evidence_uri"],
        })

        # hash 在两条都落库之后再取一次。`append_entry` 返回的是「插入那一刻」的位置，
        # 而第二条的插入可能改变第一条的 `prev_hash`（排序取决于 canonical 字节，
        # 不由插入顺序决定）。对外返回一个下一刻就作废的 hash，等于让客户端拿它去
        # 签名（第 04 步）时签在一段已经不存在的链位置上。
        chain = build_chain(entries_from(con))
        out: dict[str, dict] = {}
        for i, e in enumerate(chain):
            if e.get("entry_id") in (give_id, receive_id):
                out[e["type"]] = {"entry_id": e["entry_id"], "index": i,
                                  "hash": e["hash"], "prev_hash": e["prev_hash"]}
        if set(out) != {"give", "receive"}:
            raise WriteError("DGB_ING_016", "两条账目已写入但没能在链上定位（不应发生）")
        return {"mutual_id": mutual, "entries": [out["give"], out["receive"]]}

    def delivery_ids(self, con, request_id: str, seq: int) -> tuple[str, str, int]:
        """某一条 delivered 行对应的两条账目 id，以及它是第几轮交付。

        v1.7 起一单可以有多轮交付（被拒收后再交一次）。第一轮沿用历史 id
        （`g-rq_...` / `r-rq_...`），第二轮起带 `-d<n>`。`seq` 指明是哪一行：
        同一个函数既给写入面用（刚追加的那一行），也给重放与关单用（当前行）。
        """
        round_no = con.execute(
            "SELECT COUNT(*) FROM request WHERE request_id=? AND state='delivered' AND seq <= ?",
            (request_id, seq)).fetchone()[0]
        suffix = "" if round_no == 1 else f"-d{round_no}"
        return (DELIVERY_ID["give"] + request_id + suffix,
                DELIVERY_ID["receive"] + request_id + suffix, round_no)

    def rejected_seq(self, con, request_id: str, seq: int) -> bool:
        """这一条交付是否被拒收过。没有 `request_reject` 表（旧库）时按「没有」处理。"""
        try:
            return con.execute(
                "SELECT 1 FROM request_reject WHERE request_id=? AND seq=?",
                (request_id, seq)).fetchone() is not None
        except sqlite3.OperationalError as exc:
            if "no such table: request_reject" not in str(exc):
                raise
            return False

    def delivery_replay(self, con, data: dict, row) -> dict:
        """已经交付过的那一单，再来一次。

        两种情形分开处理，因为它们的后果不同：

        · **两条账目都在** → 这是重试。字段逐个比对：全一致就回 200 并把上次那两条
          的位置原样告诉他（`already: true`）；有一处不一致就是 `DGB_LED_029`——
          凭据以第一次为准，改凭据不是重试，而 append-only 也不给改的机会。
        · **缺账目** → 不变量破了（转换与状态行同事务，正常走不到）。这里不报错也不
          装作没看见：用那条已签的 delivered 行补生成一次，`repaired: true` 说清是补的。
          让单据卡在「已交付但账上没东西」才是更坏的结果——它永远无法再前进。

        **多轮交付（v1.7）。** 这条分支只管「当前这一轮」。第二轮交付时，`row` 是
        第二条 delivered 行，`delivery_ids` 按它的 seq 算出 `-d2` 那一对。上一轮
        那对账目仍在链上、仍指向同一次互助，拒收记录也仍指着旧 seq——三者互不覆盖。
        """
        request_id = row["request_id"]
        mutual = "m-" + request_id
        diff = [k for k in DELIVERY_SAME_FIELDS
                if k in data and ("" if data[k] is None else str(data[k]))
                != ("" if row[k] is None else str(row[k]))]
        if diff:
            raise WriteError(
                "DGB_LED_029",
                "这一单的交付已经入账，凭据以第一次为准；改凭据不是重试（不一致："
                + ", ".join(diff) + "）")

        give_id, receive_id, _round = self.delivery_ids(con, request_id, row["seq"])
        have = {kind: con.execute(
            f"SELECT * FROM ledger_{kind} WHERE {kind}_id=?", (eid,)).fetchone()
            for kind, eid in (("give", give_id), ("receive", receive_id))}
        if have["give"] is not None and have["receive"] is not None:
            chain = build_chain(entries_from(con))
            entries = []
            for kind, eid in (("give", give_id), ("receive", receive_id)):
                hit = [(i, e) for i, e in enumerate(chain)
                       if e["type"] == kind and e.get("entry_id") == eid]
                if not hit:
                    raise WriteError("DGB_ING_016", f"{kind}/{eid} 在表里但不在链上（不应发生）")
                entries.append({"entry_id": eid, "index": hit[0][0],
                                "hash": hit[0][1]["hash"],
                                "prev_hash": hit[0][1]["prev_hash"]})
            return {"request_id": request_id, "state": row["state"], "seq": row["seq"],
                    "mutual_id": mutual, "entries": entries, "already": True}

        converted = self.convert_delivery(con, request_id)
        converted.update({"request_id": request_id, "state": row["state"], "seq": row["seq"],
                          "repaired": True})
        return converted

    # ── 闭环：确认之后把单子关掉（第 05 步的另一半）──────────────────────────
    def close_after_confirm(self, con, kind: str, entry_id: str) -> str | None:
        """受方确认一条由 `delivered` 生成的 give 之后，那张单子就满足了 `closed`。

        **为什么由这一步来关，而不是等人再点一次。** `closed` 的定义是「双签完成、
        两条账目已入链」（`spec/request.md` §2）——那是**可判定的事实**，不是谁的意愿。
        再开一个「关闭」接口，就等于让某人有权宣布一件系统已经挣到的事，也能宣布一件
        还没挣到的事，而这两件事在接口上长得一模一样。所以关单不是一个动作，是确认的
        副产品：最后缺的那一块（受方签名）一落下，条件就齐了。

        只对 `m-rq_*` 生效。手工记的 `give`（`mutual_id` 为空）与需求单无关，不闭嘴。
        返回被关掉的需求单 id；没关任何东西返回 None。

        **只认最新一轮（v1.7）。** 一单被拒收后可以再交，于是同一个 `mutual_id` 下
        可能有多条 give。确认一条**旧的** give 当然也算确认（它是真的发生过），但它
        不能把单子关掉——那张单当前等的是新一轮的确认。拿 give 的 id 与当前 delivered
        行应得的那一条比对：不相等就返回 None，确认照样落库，单子不动。
        """
        if kind != "give":
            return None
        g = con.execute("SELECT mutual_id FROM ledger_give WHERE give_id=?",
                        (entry_id,)).fetchone()
        mutual = (g["mutual_id"] or "") if g else ""
        if not mutual.startswith("m-rq_"):
            return None
        request_id = mutual[2:]
        row = self.current_request(con, request_id)
        if row is None or row["state"] != "delivered":
            return None
        latest_give, _latest_recv, _round = self.delivery_ids(con, request_id, row["seq"])
        if entry_id != latest_give:
            return None
        # 关闭行是上一行的完整复制，只换 state：DGB_LED_024 要求 closed 也带
        # occurred_at 与 evidence_uri，漏一个就退化成「关闭时交付凭据消失了」。
        # 邮箱两列同理——关单之后双方还要联系，凭据行缺了邮箱等于把联系方式
        # 从当前行抹掉（历史行仍在，但「一单一行当前状态」的口径残缺了）。
        # 证据（v1.8）不复制：这一行不是谁签的，是那条确认的副产品。`sig_ref` 指向
        # 真正被签的那条确认，读的人顺着它就能走到 `entry_confirm` 的签名上去。
        self.append_request(con, {
            "request_id": request_id,
            "state": "closed",
            "category": row["category"],
            "need_desc": row["need_desc"],
            "window_expires_at": row["window_expires_at"],
            "requested_by": row["requested_by"],
            "claim_agent_id": row["claim_agent_id"],
            "evidence_uri": row["evidence_uri"],
            "occurred_at": row["occurred_at"],
            "note": row["note"],
            "poster_email": row["poster_email"],
            "claimer_email": row["claimer_email"],
        }, {"kind": "derived", "ref": f"confirm:{entry_id}"})
        return request_id

    # ── 重放闸门 ────────────────────────────────────────────────────────────
    def spend_nonce(self, con, nonce: str, party_id: str) -> None:
        """把 nonce 记成已用。撞主键即重放，交给 `from_sqlite` 翻成 005。

        顺手清掉 1 小时前的行：时间窗是 15 分钟，留 4 倍余量足够吸收时钟漂移，
        再久就没有判别意义，只会让表逐年长大。
        """
        now = utcnow()
        cutoff = (datetime.datetime.now(datetime.timezone.utc)
                  - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        con.execute("DELETE FROM ingest_nonce WHERE seen_at < ?", (cutoff,))
        con.execute("INSERT INTO ingest_nonce(nonce, party_id, seen_at) VALUES(?,?,?)",
                    (nonce, party_id, now))
