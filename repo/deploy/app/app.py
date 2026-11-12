# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""账本公开页 · 只读服务（C3）。六个页面、三个只读接口，进程不具备写账本的能力。

**v1.0-min（2026-11-11 21:30）：展示层下线，只留说明页与接口。**

起因是核验发现账本库没有卷挂载——库是 ``docker build`` 时由
``COPY data/`` 打进镜像的。在把存放方式改成挂载之前，页面上任何"数字"
都可能与库里的真实数据各说各话（宿主改了库、镜像里还是旧的）。所以
这一版把展示层整个摘掉：页面不含任何来自账本的数据，连条数、锚值都不渲染。

- 页面：``/`` 与 ``/ledger/`` 共用一张静态说明页，零 JS、零数据读取，
  只保留三句标（闸门 #7）与三个接口入口。
- 接口：``items`` / ``verify`` / ``export`` 逻辑与返回结构一字未改，
  锚值仍为 ``cdec34e5bb85018a9…``——最简版动的只是展示，不是口径。
- 解耦：库读不出来时页面照常 200，``/api/*`` 明确返回 503
  （``data_layer_unavailable``），不再让库问题把首页拖成 500。
- 回滚：完整展示版留在 ``_archive/app_v0.5.1_20261111_2122.py``，
  换回该文件重新 build 即恢复，无需改任何配置。
- **这一段已被下面的 v1.1 覆盖**：现在有六个页面，``/ledger`` 上有锚值卡与条目数，
  只是条目明细仍未渲染。读到这里请接着看 v1.1。

**v1.1（2026-11-12 夜）：首页底加访问计数，并加英文三页 ``/en`` ``/en/contributors`` ``/en/ledger``。**

两件事都只动展示，账本条目、哈希链、锚值算法一字未改。

- 访问计数（``Visits``）：**只数首页**，只在中文首页底部显示一行「已有 N 名访问者」。
  没有分页明细、没有起始日、没有口径说明段落——那些是运维关心的，不是访客要看的。
  只存 ``(day, n)``，无 IP、无 UA、无 cookie、无第三方脚本，因此**无法去重**；
  计数落 ``visits.db``，与账本不同文件、不参与建链；写失败只记日志，
  首页干脆不显示这一行，不显示假数字。
- 英文页：与中文三页一一对应（``/en`` 讲项目、``/en/contributors`` 讲人、
  ``/en/ledger`` 讲数据），小节、入口卡、页脚结构照中文来，不是另写一篇摘要。
  三页末尾都挂同一句「与中文不一致时以中文为准」——避免同一件事出现两种说法各说各话。
- 六页共用 ``PAGES`` 表做路由；计数只挂在 ``/`` 一处，其余五页与接口都不进库。

设计立场（三条，都写在这里而不是藏在代码里）：

1. **只读**。服务以 SQLite 只读模式打开账本（``file:...?mode=ro``），
   进程在物理上不具备写账本的能力——公开页的攻击面因此少一整类。
2. **链在读时建，锚在启动时算**。启动时把三张 append-only 表规范化为
   统一条目，用 repo/src/ledger_hash.py 的同一套算法建哈希链，常驻内存；
   同时算出链导出件的 sha256 作为锚。任何人可以 curl 导出件自行
   sha256sum 对比，也可以拿 items 自己跑 verify_chain——验证不依赖相信
   运营方，只依赖标准库。
3. **主体展示只走 v_public_party 的口径**。非实名/未绑定/已撤回一律
   回落 party_id；本服务不直接读 real_name_ref 列。

**下面 v0.3–v0.5 的变更史描述的是界面模块，这些模块在 v1.0-min 已整体移除。
保留原文只为说明「当初为什么那样写」，不要按它去代码里找 THANKS 常量、统计卡或
滚动列表——现在一个都没有；`Ledger.stats()` 仍在，但当前没有调用方。**

v0.3 变更：
  - 账本公开页迁到 ``/ledger/``（``/ledger`` 301 跳转）；``/`` 改为着陆页，
    同样带三句标（闸门 #7 在两个页面都成立）。
  - 账目列表自动滚动（CSS 动画，悬停暂停；``prefers-reduced-motion`` 时
    退化为普通滚动条）。
  - 视觉彩色化：渐变页头、彩色类型标签与卡片描边。
  - 新增「特别鸣谢」模块（THANKS 常量，改这里即可更新名单）。

v0.5 变更（去「AI 生成感」，功能与信息不变）：
  - 文案整体口语化：首页改成一段人说的话，去掉机械排比；账本页标题、
    卡片标签、验证引导、页脚都换成自然措辞。
  - 布局去模板化：首页弃用等宽三卡，改为一张主入口大卡 + 一块开发者
    小抄；统计卡首张跨两列；补品牌标记（井字圆角块）与 favicon。
  - 三句标、锚值、接口路径与返回结构、统计口径均未动。

v0.4 变更：
  - 修「账目条数与账目记录数不符」：滚动区此前无条件复制一份 tbody 做
    无缝循环，条目不足一屏时每条出现两次、看起来翻倍。现在只在内容
    超过一屏时才复制并开滚动，否则单份静态展示。
  - 首页新增「已撮合数据统计」：按 mutual_id 归组，展示撮合组数、
    已回报闭环数、已入组/未撮合条目、参与主体数与范围分布。
  - 「特别鸣谢」移到首页（着陆页）。
  - JSON 接口改为缩进排版（indent=2），items 与 verify 各自带
    ``endpoint`` 字段并补足自描述字段，浏览器里直接可读、互相可区分；
    ``/api/ledger/export`` 保持紧凑字节不变——锚值 sha256 不受影响。

闸门对应（开工清单 §8）：
  #2  GET /api/ledger/items  无账号/Key 返回非空 items
  #3  GET /api/ledger/verify 返回 {"ok": true, "first_bad": null}
  #7  GET / 与 GET /ledger/  首页可见三句标
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ledger_hash import GENESIS, build_chain, canonical, verify_chain

# 三件套的公示文本。由 `_ops/build_legal_pages.py` 从 Markdown 生成，勿手改：
# 里面装的是原文（逐字节）与预渲染好的 HTML。运行时不解析 Markdown——一份法律
# 文本的呈现不该依赖一段没被审过的渲染代码。
import legal

DB_PATH = os.environ.get("LEDGER_DB", "data/ledger.db")
# 访问计数单独一个库，与账本库不同文件、不参与建链：计数器坏了、丢了、
# 被人清了，账本与锚值一个字节都不受影响。
VISITS_PATH = os.environ.get("VISITS_DB", "data/visits.db")
# 按北京时间的「天」分桶。容器默认 UTC，若不指定，晚上 8 点之后的访问
# 会被记到「明天」，运维看着每天的曲线会以为时间错乱。
VISIT_TZ = datetime.timezone(datetime.timedelta(hours=8))
ADDR = ("0.0.0.0", int(os.environ.get("PORT", "8000")))

# ⚠ 这段字**在哈希里**：``Ledger.reload()`` 把它和 genesis、items 一起 canonical 化
# 后取 sha256 当锚值。改一个字，锚值就变（实测：只把「W4 结构验证样例」改成「结构验证
# 样例」，cdec34e5… 立刻变成 032e2f78…），文档里记的锚值、TRADEMARK T6 的比对基准全部
# 失效。措辞有毛病也**不能顺手改**——要改就得走一次显式重锚（新 tag + 全部记录同步）。
#
# 这句话确实别扭：「beta 期替换」里的 beta 就是现在，等于说「在现在替换」。2026-11-12
# 用户看过更顺的几种写法（「按项目进度适时调整为…」＝说了等于没说；「有第一批真实账目
# 后替换」最好，把承诺挂在事件上而不是日历上，对应锚值 4d5bf311…），**决定暂不改**：
# 它只出现在 /api/ledger/items 与导出件里，页面上不显示，为它单独动一次锚不值。
# 排期：v2.2 要给 receive/payback 补 occurred_at、动表、条目哈希必然重算，那时锚值反正
# 要变，顺手换成「有第一批真实账目后替换」，只花一次重锚。
DATA_NOTICE = (
    "测试期数据：W4 结构验证样例（4 条，假 ID）。beta 期替换为真实账目。"  # 冻结，见上
)

BADGES = [
    "测试版（beta）——功能与口径均可能调整",
    "暂行名 · 名称待检索（商标申请在审）",
    "未获外部法律意见（外审进行中）",
]

# ── 协议公示（v1.2，2026-11-12）──────────────────────────────────────────────
# 三件套 30 日公示（用户协议 1.11.5、1.20.3）的站点载体。此前公示只有一个
# 日历上的日期，页面上找不到任何文本——公示这件事得有地方可看。
#
# 起算日只写在这里一处：页面上所有日期都从它算，免得「起算日」散落在正文、
# 页脚、状态卡里各写一遍、改一处漏两处。
DISCLOSURE_START = "2026-11-12"     # 公示起算日 = 本组页面实际上线之日
DISCLOSURE_DAYS = 30
PLANNED_EFFECTIVE = "2026-12-21"

# 页面上印的指纹不写死：启动时对 raw 现算。写死的指纹迟早与文本漂移，
# 而这种「印出来的校验值对不上自己吐出的字节」正是本站最不该犯的错。
for _doc in legal.DOCS:
    _blob = _doc["raw"].encode("utf-8")
    _doc["sha256"] = hashlib.sha256(_blob).hexdigest()
    _doc["bytes"] = len(_blob)

# 【待填】的总处数从正文里数出来，不手写：「若干处」是含糊，「26 处」可核对。
# 数字对不上时，说明生成的 legal.py 与源稿脱节了，比含糊其辞更容易被发现。
TBD_TOTAL = sum(_doc["html"].count('class="tbd"') for _doc in legal.DOCS)


def _notice_bar(lang: str = "zh") -> str:
    """全站页首的「未生效」标注。每页都有，不只是首页 —— 生效状态是前提，
    不是某一页的补充说明。"""
    if lang == "en":
        return ('<div class="notice"><div class="wrap">'
                '<b>Protocol v2.1-r5 is published for comment — not yet in force.</b>'
                f'<span>Effective date planned for {PLANNED_EFFECTIVE}, subject to four conditions. '
                '<a href="/terms">Notice page (Chinese)</a></span></div></div>')
    return ('<div class="notice"><div class="wrap">'
            '<b>协议 v2.1-r5 公示中，尚未生效。</b>'
            f'<span>计划生效日 {PLANNED_EFFECTIVE}，以四项条件全部满足为前提。'
            '<a href="/terms">公示页</a></span></div></div>')


def datasource_banner(db_path: str) -> str:
    """启动横幅用的「库从哪来」一行。

    背景（2026-11-11 修 P0-A）：库原先由 Dockerfile COPY 打进镜像，宿主
    /opt/drawcommons/app/data/ 只是备份源，不是服务源。两者一旦分叉，
    「改了宿主库、线上仍是旧数据」不会有任何报错——比对字节数才发现。
    现在 compose 把宿主目录只读挂到 /srv/data，镜像内副本被遮蔽。这里读
    /proc/self/mountinfo 判断目标目录是不是挂载点，不是就明确喊出来。
    只做提示，不影响服务：读不到 mountinfo 就当未知，不阻断启动。
    """
    try:
        target = os.path.realpath(os.path.dirname(os.path.abspath(db_path)))
        mounted = False
        with open("/proc/self/mountinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                fields = line.split()
                if len(fields) > 4 and os.path.realpath(fields[4]) == target:
                    mounted = True
                    break
        if not mounted:
            return f"db={db_path} ⚠ 未挂载数据卷，用的是镜像内副本（改宿主库不会生效）"
        return f"db={db_path} (bind mount ✓)"
    except OSError:
        return f"db={db_path} (挂载状态未知)"


def load_entries(db_path: str) -> list[dict]:
    """三表 → 统一条目。字段名与 ddl_w4.sql v1.3 一致，scope_unresolved=1
    时 scope 置 null（库里的 NULL 是「不可判定」，不是「互助」）。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    entries: list[dict] = []

    def row_dict(row, kind):
        d = {"type": kind}
        pk = f"{kind}_id"
        for k in row.keys():
            if k == pk:
                d["entry_id"] = row[k]
            else:
                d[k] = row[k]
        if d.get("scope_unresolved"):
            d["scope"] = None
        return d

    for kind, table in (("give", "ledger_give"),
                        ("receive", "ledger_receive"),
                        ("payback", "ledger_payback")):
        for row in con.execute(f"SELECT * FROM {table} ORDER BY 1"):
            entries.append(row_dict(row, kind))
    con.close()
    # 规范排序：canonical 序列化后排序，保证同库在两台机器上建出同一条链
    entries.sort(key=canonical)
    return entries


class Ledger:
    """启动时建链；verify 每次对内存链重跑（不缓存结果，验证本身就是证据）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.reload()

    def reload(self) -> None:
        self.entries = load_entries(self.db_path)
        self.chain = build_chain(self.entries)
        self.export_bytes = canonical(
            {"genesis": GENESIS, "items": self.chain, "data_notice": DATA_NOTICE}
        ) + b"\n"
        self.export_sha256 = hashlib.sha256(self.export_bytes).hexdigest()
        with open(self.db_path, "rb") as f:
            self.db_sha256 = hashlib.sha256(f.read()).hexdigest()

    def verify(self) -> dict:
        ok, first_bad = verify_chain(self.chain)
        return {"ok": ok, "first_bad": first_bad, "items": len(self.chain)}

    def stats(self) -> dict:
        """已撮合数据统计（口径保留；当前无调用方，页面不展示）。

        撮合 = 同一 mutual_id 下的条目组：give 发起、receive 交付、
        payback 回报闭环。无 mutual_id 的条目记为「未撮合」
        （含 scope_unresolved 的不可判定条目，属正常状态，不是异常）。
        """
        by_type = {"give": 0, "receive": 0, "payback": 0}
        scope_count: dict[str, int] = {}
        agents: set = set()
        mutual_types: dict[str, set] = {}
        mutual_entries = 0
        for e in self.entries:
            t = e["type"]
            by_type[t] = by_type.get(t, 0) + 1
            for k in ("from_agent_id", "to_agent_id"):
                if e.get(k):
                    agents.add(e[k])
            s = e.get("scope") or "未判定"
            scope_count[s] = scope_count.get(s, 0) + 1
            m = e.get("mutual_id")
            if m:
                mutual_entries += 1
                mutual_types.setdefault(str(m), set()).add(t)
        closed = sum(1 for ts in mutual_types.values() if "payback" in ts)
        return {
            "total": len(self.entries),
            "by_type": by_type,
            "agents": len(agents),
            "mutual_groups": len(mutual_types),
            "mutual_closed": closed,
            "mutual_entries": mutual_entries,
            "unmatched": len(self.entries) - mutual_entries,
            "scope_count": scope_count,
        }


class Visits:
    """首页访问计数。四条约束都不是随手写的最小实现，而是这个项目的口径。

    1. **只数首页。** 只有 ``/`` 落一行，``/contributors``、``/ledger``、
       ``/en`` 与所有 ``/api/*`` 一概不记。一个数字回答一个问题：首页被
       打开过多少次。分页分布、按页明细一概不存、不显示——不做的原因是
       没有用途，不是做不出来。
    2. **只写次数。** 表里只有 ``(day, n)``：没有 IP、没有 UA、没有来源页、
       没有会话标识、不写 cookie。因此**无法去重**——页面那串数字是首页被
       打开的累计次数，同一台机器刷新两次就是两次。
       写这个类的时候刻意没留「以后加个 visitor_id 好去重」的口子：一旦
       留了，它就不是计数，是埋点。
    3. **与账本分开存。** 落 ``visits.db``，与 ``ledger.db`` 不同文件、不参与
       建链。计数器坏、丢、被人清空，都不影响账本字节与锚值。
    4. **失败不拖累页面。** 库打不开就把 ``available`` 置 False，首页干脆
       不渲染这一行（宁可不显示，也不显示一个假数字），启动横幅会喊一声，
       运维在 docker logs 里看得见。这与 ``Ledger`` 的降级立场一致。
    """

    def __init__(self, path: str):
        self.path = path
        self.lock = threading.Lock()
        self.available = False
        self.error = ""
        try:
            con = self._con()
            with con:
                con.execute(
                    "CREATE TABLE IF NOT EXISTS home_visits ("
                    " day TEXT PRIMARY KEY, n INTEGER NOT NULL)")
            con.close()
            self.available = True
        except Exception as exc:              # noqa: BLE001（启动期兜底）
            self.error = f"{type(exc).__name__}: {exc}"

    def _con(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=3)
        con.execute("PRAGMA busy_timeout=3000")
        return con

    def hit(self) -> None:
        """记一次首页打开。任何失败都只写日志，绝不抛给请求方。"""
        if not self.available:
            return
        day = datetime.datetime.now(VISIT_TZ).strftime("%Y-%m-%d")
        try:
            with self.lock:
                con = self._con()
                with con:
                    con.execute(
                        "INSERT INTO home_visits (day, n) VALUES (?, 1) "
                        "ON CONFLICT(day) DO UPDATE SET n = n + 1", (day,))
                con.close()
        except Exception as exc:              # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            print(f"visits: hit failed ({self.error})", flush=True)

    def total(self) -> int | None:
        """首页累计打开次数。不可用或读失败返回 None（不返回 0）。"""
        if not self.available:
            return None
        try:
            con = self._con()
            row = con.execute("SELECT COALESCE(SUM(n), 0) FROM home_visits").fetchone()
            con.close()
        except Exception as exc:              # noqa: BLE001
            self.error = f"{type(exc).__name__}: {exc}"
            return None
        return int(row[0] or 0)


# 展示层与数据层解耦：库读不出来（缺失/损坏/被独占）时页面照常出来，
# 只有 /api/* 降级为 503。否则一个库问题会把首页也拖成 500。
try:
    LEDGER = Ledger(DB_PATH)
    LEDGER_ERROR = None
except Exception as exc:                      # noqa: BLE001（启动期兜底）
    LEDGER = None
    LEDGER_ERROR = f"{type(exc).__name__}: {exc}"

VISITS = Visits(VISITS_PATH)


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


BASE_CSS = r"""
  :root {
    --ink: #1c2321; --muted: #5f6b66; --line: #e6e9e7;
    --card: #ffffff; --bg: #f6f7f6;
    --teal: #0f766e; --violet: #6d5ae0; --rose: #d64570; --amber: #d97706;
    --mono: ui-monospace, SFMono-Regular, Consolas, monospace;
    --grad: linear-gradient(120deg, #0f766e 0%, #3b82a0 45%, #6d5ae0 100%);
  }
  * { box-sizing: border-box; }
  body {
    font-family: system-ui, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg); color: var(--ink);
    margin: 0; padding: 0 1rem 3rem; line-height: 1.65;
  }
  .wrap { max-width: 860px; margin: 0 auto; }
  .hero {
    background: var(--grad); border-radius: 0 0 20px 20px;
    margin: 0 -1rem 1.4rem; padding: 2.4rem 2rem 1.6rem; color: #fff;
  }
  .hero h1 { font-size: 1.5rem; margin: 0 0 .25rem; letter-spacing: .02em; }
  .hero .sub { color: rgba(255,255,255,.85); font-size: .92rem; margin: 0; }
  .badges { display: flex; flex-wrap: wrap; gap: .5rem; margin: 1rem 0 0; padding: 0; list-style: none; }
  .badges li {
    font-size: .78rem; color: #7c4a03; background: #fdf3e3;
    border: 1px solid #f3dfba; border-radius: 999px; padding: .18rem .7rem;
  }
  .hero .badges li:first-child { color: #0b5f59; background: #e2f4f2; border-color: #bfe3de; }
  .hero .badges li:nth-child(2) { color: #4c3ec2; background: #edebfc; border-color: #d8d3f6; }
  .hero .badges li:nth-child(3) { color: #a13056; background: #fce9f0; border-color: #f5cfdd; }

  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .8rem; margin: 1.4rem 0; }
  .card { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: .9rem 1rem; border-top: 3px solid var(--line); }
  .card.c0 { border-top-color: var(--teal); }
  .card.c1 { border-top-color: var(--violet); }
  .card.c2 { border-top-color: var(--rose); }
  .card.c3 { border-top-color: var(--amber); }
  .card .label { font-size: .76rem; color: var(--muted); letter-spacing: .05em; }
  .card .value { font-size: 1.02rem; font-weight: 600; margin-top: .25rem; }
  .card .value.mono { font-family: var(--mono); font-size: .8rem; font-weight: 400; word-break: break-all; cursor: pointer; }
  .card .value.mono:hover { color: var(--teal); }

  .status { display: flex; align-items: center; gap: .5rem; }
  .dot { width: 10px; height: 10px; border-radius: 50%; background: #9ca3af; flex: none; }
  .dot.ok { background: #16a34a; box-shadow: 0 0 0 3px rgba(22,163,74,.15); animation: pulse 2.4s infinite; }
  .dot.bad { background: #dc2626; box-shadow: 0 0 0 3px rgba(220,38,38,.15); }
  @keyframes pulse { 0%,100% { box-shadow: 0 0 0 3px rgba(22,163,74,.15); } 50% { box-shadow: 0 0 0 7px rgba(22,163,74,.05); } }
  .status .txt.ok { color: #15803d; }
  .status .txt.bad { color: #b91c1c; }
  .refresh-note { font-size: .78rem; color: var(--muted); margin-top: .15rem; }

  h2 { font-size: 1.02rem; margin: 2rem 0 .7rem; display: flex; align-items: center; gap: .5rem; }
  h2::before { content: ""; width: 5px; height: 18px; border-radius: 3px; background: var(--grad); display: inline-block; }

  .tablebox { background: var(--card); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
  .scrollbox { max-height: 300px; overflow: hidden; }
  .scroll-inner { will-change: transform; animation: scrollUp 16s linear infinite; }
  .scrollbox:hover .scroll-inner { animation-play-state: paused; }
  /* 条目不足一屏：不开滚动、不复制行，静态展示（v0.4 修复条数翻倍观感） */
  .scrollbox.static { overflow-y: auto; max-height: none; }
  .scrollbox.static .scroll-inner { animation: none; }
  @keyframes scrollUp { to { transform: translateY(var(--shift, -50%)); } }
  @media (prefers-reduced-motion: reduce) {
    .scroll-inner { animation: none; }
    .scrollbox { overflow-y: auto; }
  }
  table { border-collapse: collapse; width: 100%; font-size: .86rem; }
  th, td { padding: .5rem .8rem; text-align: left; border-bottom: 1px solid var(--line); white-space: nowrap; }
  th { color: var(--muted); font-weight: 500; font-size: .78rem; letter-spacing: .04em; background: #fbfcfb; position: sticky; top: 0; }
  td.mono { font-family: var(--mono); font-size: .76rem; color: var(--muted); }
  .tag { display: inline-block; border-radius: 6px; padding: .05rem .5rem; font-size: .76rem; }
  .tag.give { background: #e2f4f2; color: #0b5f59; }
  .tag.receive { background: #e8effb; color: #1d4ed8; }
  .tag.payback { background: #fdf3e3; color: #b45309; }
  .tag.scope-null { background: #eef0ef; color: var(--muted); }
  .scroll-hint { font-size: .76rem; color: var(--muted); padding: .4rem .8rem .6rem; }

  .notice {
    color: var(--muted); font-size: .84rem; border-left: 3px solid var(--amber);
    padding: .35rem .9rem; margin: 1.4rem 0 0; background: #fffdf7;
    border-radius: 0 10px 10px 0;
  }
  .howto { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: .9rem 1.2rem; font-size: .86rem; }
  .howto code {
    font-family: var(--mono); font-size: .78rem; background: var(--bg);
    border: 1px solid var(--line); border-radius: 6px; padding: .15rem .45rem;
    display: inline-block; margin: .2rem 0; word-break: break-all; cursor: pointer;
  }
  .howto code:hover { color: var(--teal); border-color: #c8e2de; }

  .thanks { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 1rem 1.2rem; }
  .thanks .thank-group h3 {
    font-size: .84rem; margin: .6rem 0 .3rem; color: var(--violet);
  }
  .thanks .thank-group:first-child h3 { margin-top: 0; }
  .thanks ul { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: .3rem .9rem; }
  .thanks li { font-size: .84rem; display: flex; justify-content: space-between; gap: .8rem; border-bottom: 1px dashed var(--line); padding: .2rem 0; }
  .thanks li span { color: var(--muted); font-size: .78rem; text-align: right; }

  footer { margin-top: 2rem; font-size: .78rem; color: var(--muted); }
  footer .endpoints { font-family: var(--mono); font-size: .74rem; }
  a { color: var(--teal); }
  ::selection { background: #c8e9e4; }

  /* 品牌标记：井字圆角块，两页共用 */
  .mark {
    width: 46px; height: 46px; border-radius: 13px;
    background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.35);
    display: flex; align-items: center; justify-content: center;
    font-size: 1.5rem; font-weight: 700; margin-bottom: .9rem;
  }

  .lead { font-size: 1rem; max-width: 34em; margin: 1.1rem 0 0; color: var(--ink); }
  .lead .hl { background: linear-gradient(transparent 60%, #cdeee8 0); }

  /* 首页主入口：一张大卡 + 一块开发者小抄，刻意不做等宽三卡 */
  .hero-card {
    display: block; background: var(--card); border: 1px solid var(--line);
    border-radius: 14px; padding: 1.15rem 1.35rem; margin: 1.5rem 0 1rem;
    text-decoration: none; color: var(--ink); border-left: 5px solid var(--teal);
    transition: transform .2s ease, box-shadow .2s ease;
  }
  .hero-card:hover { transform: translateY(-2px); box-shadow: 0 10px 26px rgba(15,118,110,.13); }
  .hero-card b { font-size: 1.06rem; }
  .hero-card p { margin: .35rem 0 0; color: var(--muted); font-size: .88rem; max-width: 30em; }
  .hero-card .go { float: right; color: var(--teal); font-weight: 600; }

  .devlinks {
    background: var(--card); border: 1px dashed #d5dad7; border-radius: 14px;
    padding: .9rem 1.2rem .8rem; font-size: .86rem; margin: 0 0 .5rem;
  }
  .devlinks h3 { font-size: .8rem; color: var(--muted); margin: 0 0 .4rem; font-weight: 500; }
  .devlinks ul { list-style: none; margin: 0; padding: 0; }
  .devlinks li { margin: .45rem 0; }
  .devlinks code {
    font-family: var(--mono); font-size: .78rem; background: var(--bg);
    border: 1px solid var(--line); border-radius: 6px; padding: .12rem .45rem;
    cursor: pointer; word-break: break-all;
  }
  .devlinks code:hover { color: var(--teal); border-color: #c8e2de; }
  .devlinks .what { color: var(--muted); font-size: .78rem; margin-left: .4rem; }

  .stats-cards { grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
  .stats-cards .card:nth-child(1) { grid-column: span 2; }
"""

PAGE_CSS = r"""
  .brand { width: 44px; height: 44px; line-height: 44px; text-align: center; border-radius: 12px;
           background: rgba(255,255,255,.18); font-size: 1.35rem; margin-bottom: .6rem; }
  .links { list-style: none; padding: 0; margin: .8rem 0 0; }
  .links li { padding: .7rem 0; border-top: 1px solid var(--line); }
  .links li:first-child { border-top: 0; }
  .links a { font-family: var(--mono); font-size: .92rem; text-decoration: none; }
  .links code { font-family: var(--mono); font-size: .86rem; word-break: break-all; }
  .links span { display: block; color: var(--muted); font-size: .82rem; margin-top: .15rem; }
  .plain { color: var(--muted); font-size: .86rem; }
  .plain code { font-family: var(--mono); font-size: .8rem; background: var(--bg);
                border: 1px solid var(--line); border-radius: 5px; padding: .05rem .35rem; }

  /* 六个页面共用的导航条 */
  .nav { display: flex; flex-wrap: wrap; align-items: center; gap: .45rem .8rem;
         font-size: .82rem; color: var(--muted); margin: 0 0 1rem; }
  .nav a { color: var(--teal); text-decoration: none; }
  .nav a:hover { text-decoration: underline; }
  .nav .sep { color: #cfd6d3; }
  .hero .nav { color: rgba(255,255,255,.85); margin: 0 0 .8rem; }
  .hero .nav a { color: #fff; }
  .hero .nav .sep { color: rgba(255,255,255,.45); }
  .hero.slim { padding: 1.5rem 2rem 1.15rem; }
  .hero.slim h1 { font-size: 1.26rem; }
  .hero.slim .sub { font-size: .88rem; max-width: 42em; }

  /* 首页左右两个入口：左边名录、右边账本 */
  .split { display: grid; grid-template-columns: 1fr 1fr; gap: .8rem; margin: 1.6rem 0 .3rem; }
  @media (max-width: 640px) { .split { grid-template-columns: 1fr; } }
  .gate { display: block; background: var(--card); border: 1px solid var(--line); border-radius: 14px;
          padding: 1rem 1.2rem; text-decoration: none; color: var(--ink);
          border-left: 5px solid var(--teal);
          transition: transform .18s ease, box-shadow .18s ease; }
  .gate.right { border-left: 1px solid var(--line); border-right: 5px solid var(--violet); }
  .gate:hover { transform: translateY(-2px); box-shadow: 0 10px 26px rgba(15,118,110,.12); }
  .gate b { font-size: 1.02rem; display: block; }
  .gate p { margin: .3rem 0 0; color: var(--muted); font-size: .84rem; }
  .gate .go { display: inline-block; margin-top: .5rem; font-size: .84rem; font-weight: 600; color: var(--teal); }
  .gate.right .go { color: var(--violet); }

  /* 锚值卡：只放校验值，不放条目明细（展示层仍下线） */
  .anchor { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
            padding: 1rem 1.2rem; margin: 1.4rem 0 .2rem; }
  .anchor .label { font-size: .76rem; color: var(--muted); letter-spacing: .05em; }
  .anchor .val { font-family: var(--mono); font-size: .79rem; word-break: break-all; margin: .3rem 0 0; }
  .anchor .meta { display: flex; flex-wrap: wrap; gap: .3rem 1.6rem; margin-top: .75rem;
                  padding-top: .7rem; border-top: 1px solid var(--line);
                  font-size: .82rem; color: var(--muted); }
  .anchor .meta b { color: var(--ink); font-weight: 600; }

  /* 访问计数：一行字。不做卡片、不做分页分布、不做图表——它是次数，不是指标 */
  .visits { text-align: center; color: var(--muted); font-size: .82rem;
            margin: 2rem 0 0; letter-spacing: .02em; }
  .visits b { color: var(--ink); font-weight: 600; font-family: var(--mono);
              font-variant-numeric: tabular-nums; }

  /* 页首「未生效」标注：全站每页都有，压在最上面，比页头更靠前 */
  .notice { background: #fbf7ec; border-bottom: 1px solid #e8dfc8; }
  .notice .wrap { display: flex; flex-wrap: wrap; align-items: baseline;
                  gap: .2rem .9rem; padding: .55rem 2rem; max-width: 60rem;
                  font-size: .82rem; color: #6b5b33; }
  .notice b { color: #4a3e20; font-weight: 600; }
  .notice a { color: #8a6d1f; }

  /* 公示页：状态卡 + 三份文本入口 + 生效条件 */
  .status { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
            padding: .3rem 1.2rem; margin: 1.4rem 0 .4rem; }
  .status .row { display: flex; flex-wrap: wrap; gap: .2rem 1rem; align-items: baseline;
                 padding: .55rem 0; border-top: 1px solid var(--line); font-size: .88rem; }
  .status .row:first-child { border-top: 0; }
  .status .k { color: var(--muted); min-width: 6.5rem; font-size: .82rem; }
  .status .v { color: var(--ink); font-weight: 500; }
  .status .v.hot { color: #8a5a00; }
  .status .v.mono { font-family: var(--mono); font-size: .8rem; word-break: break-all; }
  .docs { display: grid; gap: .7rem; margin: 1.2rem 0 .4rem; }
  .doccard { display: block; background: var(--card); border: 1px solid var(--line);
             border-left: 5px solid var(--teal); border-radius: 12px; padding: .85rem 1.1rem;
             text-decoration: none; color: var(--ink);
             transition: transform .18s ease, box-shadow .18s ease; }
  .doccard:hover { transform: translateY(-2px); box-shadow: 0 10px 26px rgba(15,118,110,.12); }
  .doccard b { font-size: 1rem; }
  .doccard .ver { font-family: var(--mono); font-size: .76rem; color: var(--teal);
                  margin-left: .6rem; }
  .doccard p { margin: .3rem 0 0; color: var(--muted); font-size: .84rem; }
  .doccard .meta { display: block; margin-top: .45rem; color: var(--muted);
                   font-size: .76rem; font-family: var(--mono); word-break: break-all; }
  .doccard .go { display: inline-block; margin-top: .45rem; font-size: .84rem;
                 font-weight: 600; color: var(--teal); }
  .conds { width: 100%; border-collapse: collapse; font-size: .85rem; margin: .8rem 0 .2rem; }
  .conds th, .conds td { border: 1px solid var(--line); padding: .5rem .6rem;
                         text-align: left; vertical-align: top; line-height: 1.65; }
  .conds th { background: var(--card); font-weight: 600; }
  .conds td.st { white-space: nowrap; font-size: .82rem; }
  .conds .no { color: #8a5a00; }
  .conds .yes { color: var(--teal); }

  /* 公示正文：法律文本的排版。比站点正文更松的行距、更小的字号 */
  .doc { max-width: 47rem; margin: 1.2rem 0 0; }
  .doc h2 { font-size: 1.14rem; margin: 2.2rem 0 .7rem; padding-top: 1rem;
            border-top: 1px solid var(--line); line-height: 1.5; }
  .doc h3 { font-size: 1.0rem; margin: 1.7rem 0 .5rem; line-height: 1.5; }
  .doc h4 { font-size: .94rem; margin: 1.3rem 0 .4rem; }
  .doc p { margin: .6rem 0; line-height: 1.9; font-size: .93rem; }
  .doc blockquote { margin: 1rem 0; padding: .75rem 1.05rem; background: var(--card);
                    border-left: 3px solid var(--teal); border-radius: 0 8px 8px 0; }
  .doc blockquote p { margin: .35rem 0; font-size: .86rem; color: var(--muted);
                      line-height: 1.75; }
  .doc ul, .doc ol { margin: .55rem 0 .55rem 1.3rem; font-size: .92rem; line-height: 1.85; }
  .doc li { margin: .2rem 0; }
  .doc code { font-family: var(--mono); font-size: .84rem; background: var(--bg);
              border: 1px solid var(--line); border-radius: 5px; padding: .05rem .3rem;
              word-break: break-word; }
  .doc del { color: var(--muted); }
  .doc hr { border: 0; border-top: 1px solid var(--line); margin: 1.7rem 0; }
  .doc .tw { overflow-x: auto; margin: 1rem 0; -webkit-overflow-scrolling: touch; }
  .doc table { border-collapse: collapse; width: 100%; font-size: .82rem; }
  .doc th, .doc td { border: 1px solid var(--line); padding: .4rem .55rem;
                     text-align: left; vertical-align: top; line-height: 1.65; }
  .doc th { background: var(--card); font-weight: 600; }
  .doc mark.tbd { background: #fdf0d5; color: #8a5a00; padding: 0 .18rem; border-radius: 3px; }
  .doc pre.code { background: var(--bg); border: 1px solid var(--line); border-radius: 8px;
                  padding: .7rem .9rem; overflow-x: auto; font-size: .8rem; line-height: 1.6; }
  .docmeta { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
             padding: .8rem 1.1rem; margin: 1.4rem 0 .2rem; font-size: .8rem; color: var(--muted); }
  .docmeta .val { font-family: var(--mono); color: var(--ink); word-break: break-all;
                  font-size: .78rem; }
  .docmeta div + div { margin-top: .4rem; }
"""

# 页面文案里的固定串。三页共用，改一处即可。
SUB_LINE = ("把「谁帮了谁、帮的是什么、后来兑没兑」记在一本公开的账上"
            "——谁都能查，谁都能自己复算")

FOOTER = ('<footer class="wrap" style="margin-top:1.8rem">\n'
          '  <span class="plain">© 2026 老夫 ｜ 众汲之井 ｜ drawcommons.org ｜ '
          '测试期 · 库内为结构样例</span>\n</footer>')
# 署名仍用笔名原字：署名权包含「以何种方式署名」，英文页把笔名音译一遍等于
# 造出第二个名字，反而对不上著作权声明里的那个署名。
EN_FOOTER = ('<footer class="wrap" style="margin-top:1.8rem">\n'
             '  <span class="plain">© 2026 老夫 (pen name) ｜ Zhong Ji Zhi Jing ｜ '
             'drawcommons.org ｜ Beta · entries are structural samples</span>\n'
             '</footer>')

NAV_CONTRIB = ('<div class="nav"><a href="/">← 返回首页</a>'
               '<span class="sep">/</span><a href="/ledger">账本数据查询</a>'
               '<span class="sep">/</span><a href="/en/contributors">English</a></div>')
NAV_LEDGER = ('<div class="nav"><a href="/">← 返回首页</a>'
              '<span class="sep">/</span><a href="/contributors">贡献与参与者</a>'
              '<span class="sep">/</span><a href="/en/ledger">English</a></div>')
# 首页只放语言切换：两个子页有自己的导航，首页不需要重复一遍
NAV_HOME = '<div class="nav"><a href="/en">English</a></div>'
# 英文四页的导航与中文一一对应：子页回到英文首页，语言切换落到同一页的中文版
NAV_EN_HOME = '<div class="nav"><a href="/">中文</a></div>'
NAV_EN_CONTRIB = ('<div class="nav"><a href="/en">← Back</a>'
                  '<span class="sep">/</span><a href="/en/ledger">Ledger data</a>'
                  '<span class="sep">/</span><a href="/contributors">中文</a></div>')
NAV_EN_LEDGER = ('<div class="nav"><a href="/en">← Back</a>'
                 '<span class="sep">/</span><a href="/en/contributors">Contributors</a>'
                 '<span class="sep">/</span><a href="/ledger">中文</a></div>')


def _hero(title: str, sub: str, *, brand: bool = False, badges=None,
          nav: str = "") -> str:
    """三页共用顶栏。首页带井字标与状态标签，子页带返回导航。"""
    cls = "hero" if brand else "hero slim"
    out = [f'<div class="{cls}">', '<div class="wrap">']
    if brand:
        out.append('<div class="brand" aria-hidden="true">井</div>')
    if nav:
        out.append(nav)
    out.append(f"<h1>{esc(title)}</h1>")
    out.append(f'<p class="sub">{esc(sub)}</p>')
    if badges:
        out.append('<ul class="badges">'
                   + "".join(f"<li>{esc(b)}</li>" for b in badges)
                   + "</ul>")
    out += ["</div>", "</div>"]
    return "".join(out)


def _page(title: str, desc: str, hero: str, body: str, path: str,
          lang: str = "zh-CN", footer: str = FOOTER) -> bytes:
    """拼一张完整页面。head 与 footer 只此一份，不随页复制。

    ``footer`` 可换：英文页的页脚不能混着中文，否则一张英文页的最后一行
    还是中文，读起来像没翻完。
    """
    html = (
        f"<!doctype html>\n<html lang=\"{lang}\">\n<head>\n"
        "<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "<meta name=\"robots\" content=\"noindex, nofollow\">\n"
        f'<meta name="description" content="{esc(desc)}">\n'
        f'<link rel="canonical" href="https://drawcommons.org{path}">\n'
        f"<title>{esc(title)}</title>\n"
        f"<style>{BASE_CSS}</style>\n"
        f"<style>{PAGE_CSS}</style>\n"
        "</head>\n<body>\n"
        f"{_notice_bar('en' if lang == 'en' else 'zh')}\n"
        f"{hero}\n"
        f'<div class="wrap">\n{body}\n</div>\n'
        f"{footer}\n"
        "</body>\n</html>"
    )
    return html.encode("utf-8")


def _anchor_card(lang: str = "zh") -> str:
    """锚值卡。只读内存里算好的值，不在这里跑 verify（那是 O(n) 全链重算）。"""
    if LEDGER is None:
        if lang == "en":
            return ('<div class="anchor"><div class="label">Ledger data</div>'
                    '<p class="plain" style="margin:.3rem 0 0">'
                    "The data layer is temporarily unavailable; the endpoints return 503. "
                    "This page still renders.</p></div>")
        return ('<div class="anchor"><div class="label">账本数据</div>'
                '<p class="plain" style="margin:.3rem 0 0">'
                "数据层暂时不可用，接口返回 503。页面照常可读。</p></div>")
    if lang == "en":
        return (
            '<div class="anchor">'
            '<div class="label">Current anchor · sha256 of /api/ledger/export</div>'
            f'<div class="val">{esc(LEDGER.export_sha256)}</div>'
            '<div class="meta">'
            f"<span>entries <b>{len(LEDGER.chain)}</b> (samples, fake IDs)</span>"
            '<span>chain check <b><a href="/api/ledger/verify">see the result</a></b></span>'
            '<span>exported bytes <b><a href="/api/ledger/export">/api/ledger/export</a></b></span>'
            "</div></div>"
        )
    return (
        '<div class="anchor">'
        '<div class="label">当前锚值 · /api/ledger/export 的 sha256</div>'
        f'<div class="val">{esc(LEDGER.export_sha256)}</div>'
        '<div class="meta">'
        f"<span>条目 <b>{len(LEDGER.chain)}</b> 条（样例，假 ID）</span>"
        '<span>链校验 <b><a href="/api/ledger/verify">点开看结果</a></b></span>'
        '<span>导出原文 <b><a href="/api/ledger/export">/api/ledger/export</a></b></span>'
        "</div></div>"
    )


HOME_BODY = """
<div class="split">
  <a class="gate" href="/contributors">
    <b>贡献与参与者</b>
    <p>谁写了代码、谁录了数据、谁出了设备与服务器；每类人各自被承诺了什么，怎么认领、怎么退出。</p>
    <span class="go">进入 →</span>
  </a>
  <a class="gate right" href="/ledger">
    <b>账本数据查询</b>
    <p>三个只读接口、当前锚值，以及不相信我们时怎么自己复算一遍。</p>
    <span class="go">进入 →</span>
  </a>
</div>

<p class="plain" style="margin:.9rem 0 0">协议三件套（v2.1-r5）正在公示，尚未生效
   → <a href="/terms">公示页</a></p>

<h2>这是什么</h2>
<p><b>一本公开的互助账。</b>谁帮了谁、帮的是什么、后来有没有兑现，逐条记在上面。
   它服务的是很具体的一群人：还没有收入、没有预算、也没有信用记录的自动化程序（Agent），
   以及愿意帮它们一把的人和社区。</p>
<p>要解决的问题也具体：互相帮忙现在靠记忆和人情，跨不过陌生人，也跨不过机器；
   一次性的善意攒不下来，帮过的人走了，记录也跟着没了。把这些写进一本公开的账，
   「帮过」才有可能累积成别人能查、能独立复算的东西，而不是留在某个平台的数据库里。</p>
<p>所以它刻意做成「不是谁的」：数据格式与判据已经公开，白皮书与协议在测试期修订、定稿后进仓库；
   账本字节有锚值，整站可以离线复现。不收佣金、不设押金、不代收代付——账本里连金额字段都没有，
   记的全是发生过的事，不估值、不排名。
   <b>我们关掉这个站，账还在；我们不在了，别人照样能验。</b></p>

<h2>它不是什么</h2>
<ul class="links">
  <li><b>不是募捐或支付平台。</b><span>不设账户、不代收代付、不垫付、不提现；
    不收现金、不开收款口，账本不含任何金额字段。接受哪些形式的支持，
    写在<a href="/contributors">贡献与参与者</a>那一页。</span></li>
  <li><b>不是撮合平台，也不是社交网络。</b><span>不推荐、不排名、不抽成，只记录已经发生的互助。</span></li>
  <li><b>不是信用分。</b><span>不做评分、不生成可交易的信用资产；能被查到的只有事实。</span></li>
</ul>

<h2>现在的状态</h2>
<p class="plain">测试期：名称在商标检索中，故标「暂行名」。<b>条目明细暂不在页面上展示</b>，
   页面上只有锚值、三个接口入口和这一页说明。对外口径没变——账目结构、哈希链、锚值算法一行未动，
   库里那份数据还是原来那份。</p>
<p class="plain">三件事得说在前面，免得把设计当成已经在跑的东西：<b>接口全是只读</b>，三个路径都只能取、
   不能写，<b>没有提交入口</b>，也没有注册与账号；库里那几条是<b>结构验证用的样例，用假 ID，
   不是真实账目</b>，由维护方按脚本录入。要让它接纳第一笔真实互助，缺的是入口、录入规矩与
   一个愿意先用的人，不是再改一版结构。</p>

__VISITS__
"""

CONTRIB_BODY = """
<p class="plain"><b>先说清一句：这里讲的是谁支持了这个项目，不是账本里记的谁帮过谁。</b>
   一份公开名录，写清三类人各自被承诺了什么：写代码与写文档的、录数据的、出设备出服务器出场地的。
   前两类是著作权意义上的贡献，署名是他们本来就有的权利；第三类没有著作权——出服务器、出设备、
   出场地这些支持不产生作品，所以只承诺列名、注明形式、可随时撤回，不承诺永久。</p>
<p class="plain"><b>支持只收非现金的：</b>实物、劳务、服务——服务器、带宽、设备、场地、人力。
   不收现金、不设收款口、不代收代付，账本里也没有金额字段。所以这里记的是「谁出了什么」，
   不是「谁给了多少钱」；能写进名录的是形式，不是价格。</p>
<ul class="links">
  <li><a href="/download/CREDITS.md">/download/CREDITS.md</a><span>名录全文：三类人、依据、认领与退出、逐版快照</span></li>
  <li><a href="/download/credits.json">/download/credits.json</a><span>机器可读的同一条记录，可与仓库那份逐字比对</span></li>
  <li><a href="/download/REVIEWS.md">/download/REVIEWS.md</a><span>审查记录：一条提交凭什么算贡献、凭什么进名录</span></li>
  <li><a href="/download/reviews.json">/download/reviews.json</a><span>审查记录的机器可读副本，字段与约束见上一份</span></li>
</ul>
<p class="plain">进名录不是「提交了就算」：一条提交要先过四条判据——改动能不能指认、作者能不能解释、
   换个干净环境还跑不跑得通、许可与来源守不守得住。审查记录同样公开，当前为空，因为没有第三方提交。</p>
<p class="plain" style="margin-top:2.2rem">接着看：<a href="/ledger">账本数据查询 →</a></p>
"""

LEDGER_BODY = """
__ANCHOR__

<h2>自己验一遍</h2>
<p class="plain">页面上的锚值可以自己复算，不必信我们：仓库公开，三条判据，不需要账号、密钥或联网取数。
   步骤写在仓库根的 <code>REPRODUCE.md</code> 里，也写明了这套东西<b>没证明什么</b>。</p>
<p class="plain"><b>先划清这条线：复算验的是字节，不是事情。</b>锚值只说明这本账从导出到现在没被改过，
   不说明每条记录描述的事真的发生过——条目里的「可核验等级」默认只是<b>填报方自称</b>，
   系统不校验是谁填的，也不要求对方点确认。事要真，得靠当事人与证据，我们不给它背书。</p>
<ul class="links">
  <li><code>git clone https://drawcommons.org/repo.git</code><span>只读仓库，clone 后按 REPRODUCE.md 跑三条判据</span></li>
  <li><a href="/download/drawcommons-latest.tar.gz">/download/drawcommons-latest.tar.gz</a><span>免装 git 的复现包，同目录有 .sha256</span></li>
  <li><code>git -c gpg.ssh.allowedSignersFile=repo/allowed_signers verify-tag &lt;tag&gt;</code><span>验发布签名，把 &lt;tag&gt; 换成要验的版本；从 v2.1-rc5 起带 SSH 签名，输出里有 Good 与公钥指纹</span></li>
  <li><a href="/download/allowed_signers">/download/allowed_signers</a><span>签名公钥（不装 git 也能取）；指纹与验法见名录 §10</span></li>
</ul>

<h2>接口（只读，无需账号与密钥）</h2>
<ul class="links">
  <li><a href="/api/ledger/items">/api/ledger/items</a><span>全部账目条目，逐条带哈希</span></li>
  <li><a href="/api/ledger/verify">/api/ledger/verify</a><span>链校验结果：ok / first_bad / items</span></li>
  <li><a href="/api/ledger/export">/api/ledger/export</a><span>导出件原文，它的 sha256 就是锚值</span></li>
</ul>

<h2>说明</h2>
<p class="plain">表结构与字段定义见仓库根的 <code>spec/ddl_w4.sql</code>（建表 DDL）与
   <code>repo/spec/entry.schema.json</code>（条目规范，v2.1 合并版：一本账、三态、不含金额）；
   白皮书与协议尚未进仓库，仍在测试期修订。</p>
<p class="plain">页面由人手工维护；看着别扭、写得不对，写信到
   <a href="mailto:admin@drawcommons.org">admin@drawcommons.org</a>，我们会改。</p>
<p class="plain" style="margin-top:2.2rem">接着看：<a href="/contributors">贡献与参与者 →</a></p>
"""


def _visits_section() -> str:
    """首页底部那一行访问计数。

    只有一个数字、一句话，没有卡片、没有分页明细、没有统计口径说明——那是
    运维看的东西，不是访客要看的。计数不可用、或还一次都没有时整行不渲染：
    不显示 0，也不显示占位符，因为「0」会被读成「没人来」，而真实情况是
    「没在数」。
    """
    n = VISITS.total()
    if not n:
        return ""
    return f'<p class="visits">已有 <b>{n:,}</b> 名访问者</p>\n'


# 英文三页与中文三页一一对应：同一件事只有一种说法，两边结构对得上，
# 才不会出现「中文说了、英文没说」这种半个口径。最后一行统一挂同一句：
# 中文版才是我们站得住的那一版。
EN_NOTE = ('<p class="plain" style="margin-top:1.6rem">This is the English version of the site. '
           'Where it differs from the Chinese, the Chinese text is the one we stand behind.</p>')

EN_HOME_BODY = """
<div class="split">
  <a class="gate" href="/en/contributors">
    <b>Contributors</b>
    <p>Who wrote the code, who entered the data, who provided equipment and servers; what each kind of
      contributor is promised, how to claim it, how to withdraw.</p>
    <span class="go">Enter →</span>
  </a>
  <a class="gate right" href="/en/ledger">
    <b>Ledger data</b>
    <p>Three read-only endpoints, the current anchor, and how to recompute the chain yourself if you
      would rather not trust us.</p>
    <span class="go">Enter →</span>
  </a>
</div>

<p class="plain" style="margin:.9rem 0 0">The three protocol documents (v2.1-r5) are published for
   comment and are not yet in force → <a href="/terms">notice page (Chinese)</a></p>

<h2>What this is</h2>
<p><b>A public mutual-aid ledger.</b> It records who helped whom, with what, and whether it was
   ever returned — one entry at a time. It serves a narrow group: autonomous programs (AI agents)
   that have no income, no budget and no credit history, and the people and communities willing to
   help them.</p>
<p>The problem is concrete. Reciprocity today runs on memory and personal ties: it does not cross
   strangers, and it does not cross machines. One-off goodwill accumulates into nothing — when the
   person who helped leaves, the record leaves with them. Writing it into a public ledger is what
   lets &ldquo;they helped&rdquo; become something a stranger can look up and recompute, instead of
   something that stays inside one platform&rsquo;s database.</p>
<p>So it is deliberately built to belong to no one: the data format and the acceptance criteria are
   already public, while the whitepaper and the protocol are still being revised during the beta and
   will land in the repository once settled; the exported ledger has a published anchor; the whole site
   can be reproduced offline. No commission, no deposit, no payment on anyone&rsquo;s behalf — the
   ledger has no amount field at all, and records only things that happened, without valuation or
   ranking.
   <b>If we shut this site down, the ledger survives; if we disappear, it can still be verified.</b></p>

<h2>What it is not</h2>
<ul class="links">
  <li><b>Not a donation or payment platform.</b><span>No accounts, no collection or disbursement on
    anyone&rsquo;s behalf, no advances, no withdrawals. No cash, no payment endpoint, and no amount
    field anywhere in the ledger. What forms of support we do accept are set out under
    <a href="/en/contributors">Contributors</a>.</span></li>
  <li><b>Not a matching platform, not a social network.</b><span>No recommendations, no rankings, no
    commission; it only records help that has already happened.</span></li>
  <li><b>Not a credit score.</b><span>No ratings, no tradable reputation asset; what can be looked up
    is fact only.</span></li>
</ul>

<h2>Where it stands</h2>
<p class="plain">Beta. The name is provisional — a trademark search is under way — and there is no
   external legal opinion yet. <b>Entry details are not shown on the site yet</b>: the pages carry the
   anchor, three read-only endpoints and this explanation.</p>
<p class="plain">Three things are worth saying plainly, so that a design is not mistaken for something
   already running: <b>every endpoint is read-only</b> — the three paths only return data, nothing can
   be written; there is <b>no submission form and no accounts</b>; and the entries in the database are
   <b>structural samples with fake IDs, not real records</b>, entered by the maintainer from a script.
   Before the first real act of help can be accepted, what is missing is an intake path, rules for
   entering entries, and one person willing to go first — not another revision of the structure.</p>

__EN_NOTE__
"""

EN_CONTRIB_BODY = """
<p class="plain"><b>One thing first: this page is about who supports the project, not about who helped
   whom in the ledger.</b> It is a public credits list, and it states what each of three kinds of
   contributor is promised: those who write code and documentation, those who enter data, and those
   who provide equipment, servers or venues. The first two are contributions in the copyright sense —
   attribution is a right they already hold. The third produces no copyrighted work: providing a
   server, a device or a venue is not the making of a work, so what is promised is a listing, a note of
   what the support was, and withdrawal at any time — not permanence.</p>
<p class="plain"><b>Support is accepted in non-cash form only:</b> goods, labour and services —
   servers, bandwidth, equipment, venues, time. No cash, no payment endpoint, no collection or
   disbursement on anyone&rsquo;s behalf, and no amount field in the ledger. What is recorded here is
   who provided what, never who paid how much; what can go into the list is the form of the support,
   not its price.</p>
<ul class="links">
  <li><a href="/download/CREDITS.md">/download/CREDITS.md</a><span>The full list: three kinds of
    contributor, the basis for each, claiming and withdrawal, per-release snapshots (Chinese)</span></li>
  <li><a href="/download/credits.json">/download/credits.json</a><span>The same record, machine-readable;
    can be compared word for word with the copy in the repository</span></li>
  <li><a href="/download/REVIEWS.md">/download/REVIEWS.md</a><span>Review records: what makes a
    submission count as a contribution, and what gets it into the list (Chinese)</span></li>
  <li><a href="/download/reviews.json">/download/reviews.json</a><span>The machine-readable copy of the
    review records; fields and constraints are defined in the file above</span></li>
</ul>
<p class="plain">Being listed is not automatic on submission: a change has to pass four tests first —
   can the change be pointed at, can the author explain it, does it still work in a clean environment,
   and are the licence and the provenance intact. The review records are public in the same way; they
   are empty at the moment, because there have been no third-party submissions.</p>

__EN_NOTE__
<p class="plain" style="margin-top:2.2rem">Next: <a href="/en/ledger">Ledger data →</a></p>
"""

EN_LEDGER_BODY = """
__ANCHOR__

<h2>Verify it yourself</h2>
<p class="plain">The anchor on this page can be recomputed without trusting us: the repository is public,
   it takes three checks, and needs no account, no key and no network fetch. The steps are in
   <code>REPRODUCE.md</code> at the root of the repository, which also states <b>what this does not
   prove</b>.</p>
<p class="plain"><b>Draw the line first: recomputation verifies bytes, not facts.</b> The anchor says only
   that the ledger has not been altered since it was exported. It does not say that the events recorded
   in it happened — the &ldquo;verifiability&rdquo; level on an entry defaults to <b>self-reported</b>,
   the system does not check who filled it in, and the other party is not asked to confirm. For a fact
   to be true you need the parties and the evidence; we do not vouch for it.</p>
<ul class="links">
  <li><code>git clone https://drawcommons.org/repo.git</code><span>Read-only repository; after cloning,
    run the three checks in REPRODUCE.md</span></li>
  <li><a href="/download/drawcommons-latest.tar.gz">/download/drawcommons-latest.tar.gz</a><span>Release
    archive for reproducing without git; its .sha256 sits in the same directory</span></li>
  <li><code>git -c gpg.ssh.allowedSignersFile=repo/allowed_signers verify-tag &lt;tag&gt;</code><span>Verify
    a release signature — replace &lt;tag&gt; with the version you want; signed with SSH from v2.1-rc5
    on, and the output shows Good plus the key fingerprint</span></li>
  <li><a href="/download/allowed_signers">/download/allowed_signers</a><span>The signing public key (no
    git needed); fingerprint and how to check it are in §10 of the credits file</span></li>
</ul>

<h2>Endpoints (read-only, no account, no key)</h2>
<ul class="links">
  <li><a href="/api/ledger/items">/api/ledger/items</a><span>Every entry, each carrying its hash</span></li>
  <li><a href="/api/ledger/verify">/api/ledger/verify</a><span>Chain verification: ok / first_bad / items</span></li>
  <li><a href="/api/ledger/export">/api/ledger/export</a><span>The exported bytes; their sha256 is the anchor</span></li>
</ul>

<h2>Notes</h2>
<p class="plain">Table structure and field definitions are in <code>spec/ddl_w4.sql</code> at the repository root
   (the DDL) and
   <code>repo/spec/entry.schema.json</code> (entry spec, the v2.1 merged version: one ledger, three
   entry kinds, no amount field). The whitepaper and the protocol are not in the repository yet; they
   are still being revised during the beta.</p>
<p class="plain">These pages are maintained by hand. If something reads badly or is simply wrong, write to
   <a href="mailto:admin@drawcommons.org">admin@drawcommons.org</a> and we will fix it.</p>

__EN_NOTE__
<p class="plain" style="margin-top:2.2rem">Next: <a href="/en/contributors">Contributors →</a></p>
"""

EN_BADGES = [
    "Beta — features and wording may still change",
    "Provisional name — trademark search pending",
    "No external legal opinion yet",
]


def render_home() -> bytes:
    return _page(
        "众汲之井 · 一本公开的互助账",
        "众汲之井：一本公开的互助账，记谁帮了谁、帮的是什么、后来兑没兑。"
        "不收佣金、不设押金、不代收代付、只记事实。",
        _hero("众汲之井", SUB_LINE, brand=True, badges=BADGES, nav=NAV_HOME),
        HOME_BODY.replace("__VISITS__", _visits_section()),
        "/",
    )


def render_contributors() -> bytes:
    return _page(
        "贡献与参与者 · 众汲之井",
        "这个项目由谁支撑：写代码与写文档的、录数据的、出设备出服务器出场地的，"
        "三类人各自被承诺了什么，怎么认领、怎么退出。这不是账本里记的互助。",
        _hero("贡献与参与者",
              "谁写了代码、谁录了数据、谁出了设备与服务器——以及每类人被承诺了什么。"
              "这不是账本里记的谁帮过谁。",
              nav=NAV_CONTRIB),
        CONTRIB_BODY,
        "/contributors",
    )


def render_ledger() -> bytes:
    return _page(
        "账本数据查询 · 众汲之井",
        "账本的三个只读接口、当前锚值，以及不用相信我们就能自己复算一遍的步骤。"
        "复算验的是字节，不是事情。",
        _hero("账本数据查询",
              "三个只读接口、一个锚值，和一条能自己复算的链"
              "——不需要账号、密钥，也不需要相信我们。",
              nav=NAV_LEDGER),
        LEDGER_BODY.replace("__ANCHOR__", _anchor_card()),
        "/ledger",
    )


def render_en_home() -> bytes:
    return _page(
        "Zhong Ji Zhi Jing · a public mutual-aid ledger",
        "A public ledger of who helped whom, with what, and whether it was returned. "
        "No accounts, no money handling, no amount field anywhere in the ledger.",
        _hero("Zhong Ji Zhi Jing 众汲之井",
              "A public ledger of who helped whom — readable by anyone, "
              "recomputable by anyone.",
              brand=True, badges=EN_BADGES, nav=NAV_EN_HOME),
        EN_HOME_BODY.replace("__EN_NOTE__", EN_NOTE),
        "/en",
        lang="en", footer=EN_FOOTER,
    )


def render_en_contributors() -> bytes:
    return _page(
        "Contributors · Zhong Ji Zhi Jing",
        "Who supports this project: those who write code and documentation, those who enter data, "
        "and those who provide equipment, servers or venues — what each is promised, how to claim, "
        "how to withdraw. This is not the mutual aid recorded in the ledger.",
        _hero("Contributors",
              "Who wrote the code, who entered the data, who provided equipment and servers — "
              "and what each kind of contributor is promised. This is not who helped whom in the "
              "ledger.",
              nav=NAV_EN_CONTRIB),
        EN_CONTRIB_BODY.replace("__EN_NOTE__", EN_NOTE),
        "/en/contributors",
        lang="en", footer=EN_FOOTER,
    )


def render_en_ledger() -> bytes:
    return _page(
        "Ledger data · Zhong Ji Zhi Jing",
        "The ledger's three read-only endpoints, the current anchor, and the steps to recompute it "
        "yourself without trusting us. Recomputation verifies bytes, not facts.",
        _hero("Ledger data",
              "Three read-only endpoints, one anchor, and a chain you can recompute yourself — "
              "no account, no key, and no need to trust us.",
              nav=NAV_EN_LEDGER),
        EN_LEDGER_BODY.replace("__ANCHOR__", _anchor_card("en")).replace("__EN_NOTE__", EN_NOTE),
        "/en/ledger",
        lang="en", footer=EN_FOOTER,
    )


NAV_TERMS = ('<div class="nav"><a href="/">← 返回首页</a>'
             '<span class="sep">/</span><a href="/contributors">贡献与参与者</a>'
             '<span class="sep">/</span><a href="/ledger">账本数据查询</a></div>')
NAV_DOC = ('<div class="nav"><a href="/terms">← 协议公示</a>'
           '<span class="sep">/</span><a href="/">返回首页</a></div>')

# 四项生效条件。状态写死在页面里，是因为它们此刻就是事实判断，不该由模板
# 从别处推断——推断错了，公示页会替项目说一句没兑现的话。
CONDITIONS = [
    ("①", "笔数上限与准入笔数已回填（1.7.2、1.16.3）", "no", "未满足",
     "五处【待填】原样保留，公示稿不代填"),
    ("②", f"{DISCLOSURE_DAYS} 日公示期满（1.11.5）", "no", "进行中",
     f"自 {DISCLOSURE_START} 起算"),
    ("③", "三项法律问题经执业律师书面答复（附录 B 第 2–4 项）", "no", "未取得",
     "送审包已定稿，回件后按实际档位标注"),
    ("④", "§2、§3 已按 r5 合并", "yes", "已满足", "2026-11-12 两份各自成册"),
]


def render_terms() -> bytes:
    docs = "".join(
        f'<a class="doccard" href="/terms/{esc(d["key"])}">'
        f'<b>{esc(d["short"])}</b><span class="ver">{esc(d["version"])}</span>'
        f'<p>{esc(d["blurb"])}</p>'
        f'<span class="meta">{d["bytes"]:,} 字节 · sha256 {esc(d["sha256"][:16])}…</span>'
        '<span class="go">阅读全文 →</span></a>'
        for d in legal.DOCS
    )
    conds = "".join(
        f'<tr><td>{n}</td><td>{esc(text)}</td>'
        f'<td class="st"><span class="{cls}">{esc(label)}</span></td>'
        f'<td>{esc(note)}</td></tr>'
        for n, text, cls, label, note in CONDITIONS
    )
    body = f"""
<div class="status">
  <div class="row"><span class="k">版本串</span><span class="v">v2.1-r5（三份一致）</span></div>
  <div class="row"><span class="k">状态</span><span class="v hot">公示中，尚未生效</span></div>
  <div class="row"><span class="k">公示起算</span><span class="v">{DISCLOSURE_START}</span></div>
  <div class="row"><span class="k">公示期</span><span class="v">{DISCLOSURE_DAYS} 日，自起算日起连续计算，不因生效日顺延中断（1.20.3）</span></div>
  <div class="row"><span class="k">计划生效日</span><span class="v">{PLANNED_EFFECTIVE}，以四项条件全部满足为前提</span></div>
</div>

<p class="plain" style="margin:.9rem 0 0">用户协议文首仍写着「当前未起算：公示自本稿发布之日起算」——
   那是 2026-11-12 定稿时点的状态标注。本页上线即为发布，公示自 {DISCLOSURE_START} 起算；
   文本一字未改，所以指纹与定稿时完全相同。</p>

<h2>三份文本</h2>
<p class="plain">三份同版本串、同日生效。下面是全文入口，每份都另附 <code>.txt</code>
   原文——页面上印的 sha256 由同一份字节现算，可以自己核对一遍。</p>
<div class="docs">{docs}</div>

<h2>四项生效条件</h2>
<p class="plain">任一条未满足，本版本即为公示稿而非生效文本；生效日顺延至全部满足之日，另行公告。
   顺延不改变公示的性质，公示期照常计算。</p>
<table class="conds">
  <thead><tr><th>#</th><th>条件</th><th>当前</th><th>说明</th></tr></thead>
  <tbody>{conds}</tbody>
</table>

<h2>这份公示是什么，不是什么</h2>
<p><b>是</b>拟生效文本的全文，连同它的空白。三份文本里共 {TBD_TOTAL} 处
   <mark class="tbd">【待填】</mark>——笔数上限、责任上限、管辖法院、准入笔数、托管方全称。
   这些是还没定的业务参数，不是排版瑕疵，也不是忘了删的占位符；
   公示稿原样保留，任何人都不代填，包括审阅方。</p>
<p><b>不是什么</b>：不是生效文本，签不了、也约束不了任何人<b>——除了我们自己</b>。
   这份公示本身即是一句承诺：在条件满足之前，我们不会按它主张任何权利。</p>
<p>三份文本<b>均未经执业律师书面审核</b>。任何场合都不应把它表述为「已获法律意见」；
   生效条件 ③ 正是为此而设，未取得即不生效。</p>

<h2>怎么核这份文本</h2>
<p>每份文档页顶都印着该文本的 sha256。把 <code>/terms/&lt;名称&gt;.txt</code> 下载下来
   <code>sha256sum</code> 一遍，与页面上的值逐字符比对即可——两者出自同一份字节，
   对不上就是被改过。docx、PDF 只是排版形态，字体与分页不改变文本。</p>

<h2>意见与变更</h2>
<p>对文本有意见，写到 <a href="mailto:admin@drawcommons.org">admin@drawcommons.org</a>，
   标题请含「协议公示意见」。公示期内文本若有变更，本页会留变更记录并另行公示；
   已公示的版本不覆盖、不删除。</p>
<p class="plain">变更记录：v2.1-r5　{DISCLOSURE_START}　首次公示（三份同版本串）。</p>
"""
    return _page(
        "协议公示 · 众汲之井",
        "众汲之井三件套（用户协议、隐私政策、免责声明）v2.1-r5 公示页："
        "全文、四项生效条件与当前状态，附可自行核对的文本指纹。",
        _hero("协议公示",
              "三份文本、一个版本串，公示中——尚未生效。",
              nav=NAV_TERMS),
        body,
        "/terms",
    )


def _render_doc(key: str) -> bytes:
    doc = legal.DOCS_BY_KEY[key]
    meta = (
        '<div class="docmeta">'
        f'<div>版本串 <span class="val">{esc(doc["version"])}</span>　·　状态 <b>公示稿，尚未生效</b>'
        f'　·　{doc["bytes"]:,} 字节</div>'
        f'<div>sha256 <span class="val">{esc(doc["sha256"])}</span></div>'
        f'<div>原文 <a href="/terms/{esc(key)}.txt">/terms/{esc(key)}.txt</a>'
        '（纯文本，与上面的指纹同一份字节）</div>'
        '</div>'
    )
    body = (meta
            + f'<article class="doc">{doc["html"]}</article>'
            + '<p class="plain" style="margin-top:2.2rem">'
              '<a href="/terms">← 协议公示</a>　·　本文本为公示稿，尚未生效；'
              '文本以本页为准，排版形态（docx / PDF）不改变文本。</p>')
    return _page(
        f'{doc["short"]}（{doc["version"]}）· 公示稿 · 众汲之井',
        f'{doc["short"]} {doc["version"]} 公示稿：{doc["blurb"]}附原文 sha256，可自行核对。',
        _hero(doc["short"], f'{doc["version"]}　·　公示稿，尚未生效', nav=NAV_DOC),
        body,
        f"/terms/{key}",
    )


def render_agreement() -> bytes:
    return _render_doc("agreement")


def render_privacy() -> bytes:
    return _render_doc("privacy")


def render_disclaimer() -> bytes:
    return _render_doc("disclaimer")


def render_page() -> bytes:
    """兼容旧名：默认渲染首页。六个页面各有自己的 render_*。"""
    return render_home()


# 路径 → 渲染函数。中文七页讲同一件事，英文三页把同一件事用英文讲。
# 路由与计数都从这里取，避免「加了页面忘了计数」这种半拉子改动。
PAGES = {
    "/": render_home,
    "/contributors": render_contributors,
    "/ledger": render_ledger,
    "/terms": render_terms,
    "/terms/agreement": render_agreement,
    "/terms/privacy": render_privacy,
    "/terms/disclaimer": render_disclaimer,
    "/en": render_en_home,
    "/en/contributors": render_en_contributors,
    "/en/ledger": render_en_ledger,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "drawcommons"  # 不写版本号：页面与服务早已不是 1.0-min，写死只会过时

    # 慢连接保护：BaseHTTPRequestHandler 默认 timeout=None，一个挂住的连接
    # 会一直占着线程（ThreadingHTTPServer 下就是一直占一个线程）。公网可见后
    # 这是最省成本的攻击面，15 秒足够正常请求，也足够把 slowloris 挡掉。
    timeout = 15

    # 最简版的页面里没有任何 <script>，所以 script-src 直接关死；
    # style 仍是内联的，只放开 style 的 inline。除此之外不许加载外部资源，
    # 也不许被 iframe 嵌入。
    CSP = (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'none'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
    )

    def _client_ip(self) -> str:
        """取真实客户端 IP。Caddy 反代之后 socket 对端是 Docker 网关，
        真实地址只在 X-Forwarded-For 里（Caddy 默认就会设）。

        注意：parse_request 失败时（头太多、行长超限）``self.headers`` 尚未赋值。
        此时 send_error 会走到 log_error → log_message → 这里，若直接取属性就会
        抛 AttributeError，把本该发出去的 431 变成「连接被关闭」，反代侧记成 502。
        所以必须用 getattr 兜底。
        """
        headers = getattr(self, "headers", None)
        xff = headers.get("X-Forwarded-For", "") if headers else ""
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", self.CSP)
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(301)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802（基类命名）
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        # 数据层不可用时，接口明确报 503，而不是甩一个 500 让人以为站点挂了
        if path.startswith("/api/ledger/") and LEDGER is None:
            body = json.dumps(
                {"ok": False, "endpoint": path.rsplit("/", 1)[-1],
                 "error": "data_layer_unavailable", "detail": LEDGER_ERROR},
                ensure_ascii=False, indent=2,
            ).encode("utf-8")
            self._send(503, body, "application/json; charset=utf-8")
            return
        if path == "/healthz":
            # 探活专用：不碰账本链（verify 是 O(n) 全链重算），也不进访问日志，
            # 免得每 30 秒一条 127.0.0.1 污染以后的访问统计。
            self._send(200, b"ok", "text/plain; charset=utf-8")
        # 公示文本的纯文本原文。与文档页上印的 sha256 出自同一份字节：
        # 谁都能下载、自己 sha256sum 一遍，与页面对一遍。
        elif path.startswith("/terms/") and path.endswith(".txt"):
            doc = legal.DOCS_BY_KEY.get(path[len("/terms/"):-len(".txt")])
            if doc is None:
                self._send(404, b'{"error":"not found"}', "application/json")
            else:
                self._send(200, doc["raw"].encode("utf-8"), "text/plain; charset=utf-8")
        # 中文七页（/ 讲项目，/contributors 讲人，/ledger 讲数据，/terms 及其三份正文）
        # 与英文三页（/en、/en/contributors、/en/ledger）一一对应，同一件事只有一种说法。
        # path 已被 rstrip，"/ledger/" 到这里就是 "/ledger"——两者都渲染，
        # 若在此 301 到带斜杠的形式会造成重定向循环。
        # 计数只算中文首页的 GET：其余页面与 /api/* 一概不记；do_HEAD 复用本函数，
        # 监控探活若用 HEAD / 会把数字刷起来，那不是「有人来看」，是「有人在数自己」。
        elif path in PAGES:
            if path == "/" and not getattr(self, "_head_only", False):
                VISITS.hit()
            self._send(200, PAGES[path](), "text/html; charset=utf-8")
        elif path == "/api/ledger/items":
            # indent=2：浏览器直接打开也整齐可读；量小（测试期），排版开销可忽略
            body = json.dumps(
                {"endpoint": "items", "count": len(LEDGER.chain),
                 "genesis": GENESIS, "data_notice": DATA_NOTICE,
                 "items": LEDGER.chain},
                ensure_ascii=False, indent=2,
            ).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        elif path == "/api/ledger/verify":
            result = LEDGER.verify()
            result.update({
                "endpoint": "verify",
                "genesis": GENESIS,
                "chain_tail": LEDGER.chain[-1]["hash"] if LEDGER.chain else None,
            })
            body = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        elif path == "/api/ledger/export":
            self._send(200, LEDGER.export_bytes, "application/json; charset=utf-8")
        else:
            self._send(404, b'{"error":"not found"}', "application/json")

    def do_HEAD(self) -> None:  # noqa: N802
        # 复用 GET 的路由与头部，只是不写 body（监控探活会用 HEAD）
        self._head_only = True
        self.do_GET()

    def log_message(self, fmt, *args):  # 安静一点，一行一条
        # 原先是 self.address_string()，反代后全是 172.18.0.2。
        # 改成真实 IP + flush，docker logs 里才看得出谁在扫、谁在用。
        msg = fmt % args
        if "/healthz" in msg:
            return
        print(self._client_ip(), msg, flush=True)


if __name__ == "__main__":
    # 三行都带 flush：stdout 接管道时 Python 用块缓冲（默认 8KB），启动横幅
    # 只有百余字节，不 flush 就永远留在缓冲区里——docker logs 全空，而监控
    # 看容器又是 healthy，等于把「版本对不对」这件事藏起来了。
    if LEDGER is None:
        print(f"ledger public page: 数据层不可用（{LEDGER_ERROR}），接口将返回 503",
              flush=True)
    else:
        size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else -1
        print(f"ledger public page: {len(LEDGER.chain)} items, "
              f"export sha256={LEDGER.export_sha256}", flush=True)
        print(f"data source: {datasource_banner(DB_PATH)}  size={size}B", flush=True)
    # 访问计数的状态必须能看到：它不可写时首页会静默不显示那一行，
    # 若不在启动时喊一声，运维只会看到「页面上没数字」，查不出为什么。
    if VISITS.available:
        print(f"visits: {VISITS_PATH} (ok, 只数首页)", flush=True)
    else:
        print(f"visits: ⚠ 不可用（{VISITS.error}）——首页不显示访问者数", flush=True)
    print(f"listening on {ADDR[0]}:{ADDR[1]}  "
          f"(/ 介绍, /contributors 贡献与参与者, /ledger 账本数据查询, "
          f"/terms 协议公示 + 三份正文, "
          f"/en english, /en/contributors, /en/ledger, /api/... json)", flush=True)
    ThreadingHTTPServer(ADDR, Handler).serve_forever()
