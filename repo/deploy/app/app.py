# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""账本公开页 · 只读服务（C3，v1.0-min 最简版）。

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

import hashlib
import json
import os
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ledger_hash import GENESIS, build_chain, canonical, verify_chain

DB_PATH = os.environ.get("LEDGER_DB", "data/ledger.db")
ADDR = ("0.0.0.0", int(os.environ.get("PORT", "8000")))

DATA_NOTICE = (
    "测试期数据：W4 结构验证样例（4 条，假 ID）。beta 期替换为真实账目。"
)

BADGES = [
    "测试版（beta）——功能与口径均可能调整",
    "暂行名 · 名称待检索（商标申请在审）",
    "未获外部法律意见（外审进行中）",
]

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
        """已撮合数据统计（首页展示口径）。

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


# 展示层与数据层解耦：库读不出来（缺失/损坏/被独占）时页面照常出来，
# 只有 /api/* 降级为 503。否则一个库问题会把首页也拖成 500。
try:
    LEDGER = Ledger(DB_PATH)
    LEDGER_ERROR = None
except Exception as exc:                      # noqa: BLE001（启动期兜底）
    LEDGER = None
    LEDGER_ERROR = f"{type(exc).__name__}: {exc}"


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

MINIMAL_PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>众汲之井 · drawcommons</title>
<style>__CSS__</style>
<style>
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
</style>
</head>
<body>
<div class="hero">
  <div class="wrap">
    <div class="brand" aria-hidden="true">井</div>
    <h1>众汲之井</h1>
    <p class="sub">把「谁帮了谁、帮了多少、后来回报了没有」记在一本公开的账上</p>
    <ul class="badges">
      <li>__BADGE0__</li>
      <li>__BADGE1__</li>
      <li>__BADGE2__</li>
    </ul>
  </div>
</div>
<div class="wrap">
  <h2>当前是最简版</h2>
  <p>页面这会儿只留说明和接口入口，不显示账目数字。原因是账本库的存放方式正在调整，
     先把展示层摘下来——免得页面上的数字和库里的数据各说各话。</p>
  <p>调整完会恢复账目列表和校验状态。对外口径没有变：账目结构、哈希链、锚值的算法一行未动，
     库里那份数据也还是原来那份。</p>

  <h2>接口（只读，无需账号与密钥）</h2>
  <ul class="links">
    <li><a href="/api/ledger/items">/api/ledger/items</a><span>全部账目条目，逐条带哈希</span></li>
    <li><a href="/api/ledger/verify">/api/ledger/verify</a><span>链校验结果：ok / first_bad / items</span></li>
    <li><a href="/api/ledger/export">/api/ledger/export</a><span>导出件原文，它的 sha256 就是锚值</span></li>
  </ul>

  <h2>自己验一遍</h2>
  <p class="plain">页面上的锚值可以自己复算，不必信我们：仓库公开，两条命令，不需要账号、密钥或联网取数。
     步骤写在仓库根的 <code>REPRODUCE.md</code> 里，也写明了这套东西<b>没证明什么</b>。</p>
  <ul class="links">
    <li><code>git clone https://drawcommons.org/repo.git</code><span>只读仓库，clone 后按 REPRODUCE.md 跑两条判据</span></li>
    <li><a href="/download/drawcommons-latest.tar.gz">/download/drawcommons-latest.tar.gz</a><span>免装 git 的复现包，同目录有 .sha256</span></li>
  </ul>

  <h2>名录与署名</h2>
  <p class="plain">谁做过什么、凭什么记他、名字该写在哪，都在一份公开名录里，不在对话里。
     名录分三类，因为这三类人的依据不一样：写了东西的、录了数据的，署名是他们的权利，
     也是我们分发时躲不掉的义务；出钱、出服务器、出地方的，<b>没有著作权</b>——单纯给钱
     不产生作品，所以我们对他们只承诺列名、注明形式、随时可撤回，不承诺「署名权」。
     承诺了什么、不承诺什么，名录里逐条写着，包括不承诺永久。</p>
  <ul class="links">
    <li><a href="/download/CREDITS.md">/download/CREDITS.md</a><span>名录全文：三类人、登记依据、认领与退出、逐版快照</span></li>
    <li><a href="/download/credits.json">/download/credits.json</a><span>机器可读的同一条记录，可与仓库里的那份逐字比对</span></li>
  </ul>

  <h2>说明</h2>
  <p class="plain">测试期：名称、口径、界面都还可能改。名称在商标检索中，所以标着「暂行名」。
     表结构与字段定义见仓库的 <code>spec/ddl_w4.sql</code> 与 <code>repo/spec/</code> 下的 JSON Schema；
     测试期的白皮书与协议尚未进仓库。</p>
  <p class="plain">页面由人手工维护；看着别扭、写得不对，欢迎直接找我们。</p>
</div>
<footer class="wrap" style="margin-top:1.5rem">
  <span class="plain">© 2026 老夫 ｜ 众汲之井 ｜ drawcommons.org ｜ 最简版（展示层暂时下线）</span>
</footer>
</body>
</html>"""


def render_page() -> bytes:
    """最简版：页面不含任何来自账本的数据，替换的只有样式的三句标。
    数据层读不到库时，页面照样能出来——这是「展示层与数据层解耦」的意思。"""
    page = MINIMAL_PAGE
    for token, value in (
        ("__CSS__", BASE_CSS),
        ("__BADGE0__", esc(BADGES[0])),
        ("__BADGE1__", esc(BADGES[1])),
        ("__BADGE2__", esc(BADGES[2])),
    ):
        page = page.replace(token, value)
    return page.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "drawcommons-ledger/1.0min"

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
        elif path in ("/ledger", "/ledger/"):
            # 注意：path 已被 rstrip，"/ledger/" 到这里就是 "/ledger"——
            # 两者都渲染页面；若在此 301 到 "/ledger/" 会造成重定向循环。
            self._send(200, render_page(), "text/html; charset=utf-8")
        elif path == "/":
            # 与 /ledger/ 同一张最简页：两个地址都活着，但不各维护一份
            self._send(200, render_page(), "text/html; charset=utf-8")
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
        print(f"ledger public page v1.0-min: 数据层不可用（{LEDGER_ERROR}），接口将返回 503",
              flush=True)
    else:
        size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else -1
        print(f"ledger public page v1.0-min: {len(LEDGER.chain)} items, "
              f"export sha256={LEDGER.export_sha256}", flush=True)
        print(f"data source: {datasource_banner(DB_PATH)}  size={size}B", flush=True)
    print(f"listening on {ADDR[0]}:{ADDR[1]}  (/ 与 /ledger/ 同一张说明页, /api/... json)",
          flush=True)
    ThreadingHTTPServer(ADDR, Handler).serve_forever()
