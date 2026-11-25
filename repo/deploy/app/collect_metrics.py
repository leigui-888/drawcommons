#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""collect_metrics.py —— 把「能测的事实」算成一份 JSON，供 `/api/metrics` 读。

为什么要单独一个进程，而不是写在 app.py 里
------------------------------------------
因为数据源不在 app 手里：访问日志由 Caddy 写出，落在 `/opt/drawcommons/data/`
（caddy 容器的 /data），**没有挂给 app**；而且日志里有 IP。让公开读口去碰原始
日志，等于顺手给了它一条读到访客 IP 的路径。所以分工是：

    Caddy 写日志  →  本脚本（宿主机，cron）  算好、聚好、去掉自测
                  →  app/data/metrics.json
                  →  app 的 /api/metrics 只读这一份 JSON

本脚本**只做聚合**：输出里不出现任何一条 IP，只出现计数。这不是谨慎，是口径——
页面要回答「多少人从外面读过」，不需要知道是谁。

口径（与 `_ops/指标口径与数据可得性（2026-11-25）.md` 一致）
---------------------------------------------------------
1. 「读口」= `/api/*` 的 2xx，加 `/llms.txt` `/agent.md` `/audit.md` 三个文本件。
   人类页面不算——那是「有人来看站」，不是「有人来用协议」。
2. 请求分三类，**页面主数只取第三类**：
   - `self`：UA 以 `drawcommons-` 开头（巡检探针），**或**该 IP 曾发过这类探针。
     后一条是关键：判据探针有时候是裸 `curl`，只按 UA 认会把自己算成外部。
   - `crawler`：UA 命中常见爬虫。它们读的是索引，不是协议。
   - `external`：其余。**这是上界**——里面仍可能有我们手工敲的 curl，
     只是换了台机器、用了普通 UA。页面必须写明这一点，不许写成「非成员读取」。
3. 复用：fork / star 走 GitHub API，下载量走 pypistats（包名 `dgb`，不是 `drawcommons`）。
   拿不到就写 `null` 并在 `notes` 里写原因——**不写 0**。0 是「测了，是零」，
   null 是「没测到」，两者对读者意义相反。
4. 「独立部署数」「存活 ≥90 天比例」**不采集**：没有上报入口、没有遥测，也不该
   为了指标偷偷加。它们固定为 null，原因写在 `not_measurable` 里，由页面原样展示。

用法
----
    python3 collect_metrics.py \
        --log /opt/drawcommons/data/access.log \
        --out /opt/drawcommons/app/data/metrics.json \
        --db  /opt/drawcommons/app/data/ledger.db \
        --days 7

    python3 collect_metrics.py --log /tmp/dc-access.log --out /tmp/m.json --no-net

`--no-net` 跳过 GitHub 与 PyPI：离线复算日志时用，免得把网络抖动当成口径变化。
退出码：写成功 0；日志或输出不可写 1。**网络失败不算失败**（那些格子写 null）。
"""
from __future__ import annotations

import argparse
import glob
import gzip
import io
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))

# 巡检探针的 UA 前缀。见 `_ops/check_routes.py` / `check_assets.py` 里的 UA 常量，
# 以及 `w0/anchor_refs.py` 的 `drawcommons-anchor-*`。改了那边要回来改这里。
PROBE_UA_PREFIX = "drawcommons-"

# 爬虫：只认「读来建索引」的那一类。刻意不去猜通用脚本（python-requests、curl），
# 因为在没有身份的情况下，猜错的方向总是「把自己洗白」，那比不猜更糟。
BOT_RE = re.compile(
    r"(bot\b|crawler|spider|slurp|externalhit|facebookexternalhit|"
    r"googlebot|bingbot|yandex|baiduspider|bytespider|gptbot|claudebot|"
    r"petalbot|semrush|ahrefs|mj12|dotbot)",
    re.I,
)

# 读口。改这里等于改「什么算读取协议」，页面上的数字会整段变，先读口径文件。
READ_PATHS_EXACT = ("/llms.txt", "/agent.md", "/audit.md")
READ_PREFIX = ("/api/",)

# 看着像读口、其实不是：`/api/visits` 是主页那个数字在数自己（POST），
# 不是谁来读了协议。把它算进「外部读取」等于让页脚的计数器给指标充值。
EXCLUDE_EXACT = ("/api/visits",)

NOT_MEASURABLE = [
    {
        "name": "非成员受益率 · 比例",
        "why": "读口全程匿名、不认证、不建会话，日志里只有 IP 与 UA，没有任何身份字段；"
               "项目也不记录主体 IP。因此「这个读取者是不是已登记主体」不可判定。",
        "needs": "读口支持可选身份（`?as=` 或签名头）。那是协议级改动，要走公示。",
    },
    {
        "name": "复用广度 · 独立部署 / 集成实例数",
        "why": "没有公开 registry、没有上报入口、没有遥测，也不该为了指标悄悄加上报。",
        "needs": "部署方自愿上报，或做镜像拉取统计。两者都需要一个新的信任安排。",
    },
    {
        "name": "复用广度 · 存活 ≥90 天比例",
        "why": "同上，且还要求每个实例有上线时间与心跳。",
        "needs": "先有实例清单，才谈得上存活率。",
    },
]


def log(msg: str) -> None:
    sys.stderr.write("[metrics] %s\n" % msg)


# ─────────────────────────── 读日志 ───────────────────────────

def open_log(path: str):
    """打开日志；`.gz` 直接解压读。Caddy 轮转出来的旧文件也一并读。"""
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    return io.open(path, encoding="utf-8", errors="replace")


def expand_logs(patterns):
    out = []
    for p in patterns:
        hits = sorted(glob.glob(p))
        if not hits and os.path.exists(p):
            hits = [p]
        out.extend(h for h in hits if os.path.isfile(h))
    # 去重但保序
    seen, uniq = set(), []
    for p in out:
        rp = os.path.realpath(p)
        if rp not in seen:
            seen.add(rp)
            uniq.append(p)
    return uniq


def ua_of(req: dict) -> str:
    h = req.get("headers") or {}
    v = h.get("User-Agent") or h.get("user-agent") or ""
    if isinstance(v, list):
        v = v[0] if v else ""
    return v or ""


def ip_of(req: dict) -> str:
    for k in ("client_ip", "remote_ip", "X-Forwarded-For"):
        v = req.get(k)
        if isinstance(v, list):
            v = v[0] if v else ""
        if v:
            return str(v).split(",")[0].strip()
    return ""


def is_read_path(uri: str) -> bool:
    if not uri:
        return False
    p = uri.split("?", 1)[0]
    if p in EXCLUDE_EXACT:
        return False
    return p.startswith(READ_PREFIX) or p in READ_PATHS_EXACT


def scan(log_paths, days: int):
    """两遍扫：第一遍认「自己是谁」，第二遍分类计数。

    为什么必须两遍：判据探针有一半是裸 `curl`（见 `check.sh` 里那几条），
    只看 UA 会把它们算成外部读者。而它们与探针发自同一台机器，所以
    「这个 IP 曾经发过 drawcommons- 探针」就是一个可靠的自我标记。
    """
    lines = 0
    bad = 0
    self_ips = set()
    first_ts = None
    last_ts = None

    for path in log_paths:
        with open_log(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                lines += 1
                try:
                    d = json.loads(line)
                except Exception:
                    bad += 1
                    continue
                req = d.get("request") or {}
                if (ua_of(req) or "").startswith(PROBE_UA_PREFIX):
                    ip = ip_of(req)
                    if ip:
                        self_ips.add(ip)
                ts = d.get("ts")
                if isinstance(ts, (int, float)):
                    first_ts = ts if first_ts is None else min(first_ts, ts)
                    last_ts = ts if last_ts is None else max(last_ts, ts)

    cutoff = time.time() - days * 86400
    counts = {"external": 0, "self": 0, "crawler": 0}
    total_2xx = 0
    per_day = {}
    ext_ips = set()
    ext_paths = {}
    ext_paths_total = 0

    for path in log_paths:
        with open_log(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                req = d.get("request") or {}
                # `status` 在**顶层**，不在 `request` 里（Caddy 的 JSON 结构，
                # 2026-11-25 实测）。写成 `request.status` 的后果是全部 403/404
                # 都被当成「没有状态」跳过——数字恒为零，而且看起来像「没人用」。
                status = d.get("status", req.get("status"))
                if not isinstance(status, int) or not (200 <= status < 300):
                    continue
                uri = req.get("uri") or ""
                if not is_read_path(uri):
                    continue
                ts = d.get("ts")
                if not isinstance(ts, (int, float)) or ts < cutoff:
                    continue
                total_2xx += 1

                ua = ua_of(req)
                ip = ip_of(req)
                if ua.startswith(PROBE_UA_PREFIX) or (ip and ip in self_ips):
                    kind = "self"
                elif BOT_RE.search(ua):
                    kind = "crawler"
                else:
                    kind = "external"
                counts[kind] += 1

                day = datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d")
                row = per_day.setdefault(day, {"external": 0, "self": 0, "crawler": 0})
                row[kind] += 1

                if kind == "external":
                    if ip:
                        ext_ips.add(ip)
                    p = uri.split("?", 1)[0]
                    ext_paths[p] = ext_paths.get(p, 0) + 1
                    ext_paths_total += 1

    top = sorted(ext_paths.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    daily = [dict(date=k, **per_day[k]) for k in sorted(per_day)]
    return {
        "lines": lines,
        "unparsable": bad,
        "self_ips": len(self_ips),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "counts": counts,
        "total_2xx": total_2xx,
        "daily": daily,
        "external_unique_ips": len(ext_ips),
        "top_paths": [{"path": p, "n": n} for p, n in top],
        "external": ext_paths_total,
    }


# ─────────────────────────── 账本 ───────────────────────────

def ledger_stats(db_path: str):
    """账本侧的三个数：条目、主体、需求单当前状态分布。

    条目按三张链表求和（give / receive / payback）。用 `mode=ro` 打开：
    这个脚本**只有读权限**，写库的是 ingest，不是 cron。
    """
    if not db_path or not os.path.exists(db_path):
        return None, "库不存在：%s" % db_path
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True, timeout=5)
    except Exception as e:  # pragma: no cover
        return None, "打不开库：%s" % e
    try:
        items = 0
        for t in ("ledger_give", "ledger_receive", "ledger_payback"):
            items += con.execute("select count(*) from %s" % t).fetchone()[0]
        parties = con.execute("select count(*) from party").fetchone()[0]
        states = {}
        try:
            for st, n in con.execute("select state, count(*) from v_request_current group by state"):
                states[str(st)] = int(n)
        except Exception:
            states = {}
        return {"items": items, "parties": parties, "requests": states}, None
    except Exception as e:
        return None, "查库失败：%s" % e
    finally:
        con.close()


# ─────────────────────────── 复用（网络） ───────────────────────────

def http_json(url: str, timeout: int = 8):
    req = urllib.request.Request(url, headers={
        "User-Agent": "drawcommons-metrics/1.0 (+https://drawcommons.org/numbers)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def github_stats(repo: str):
    try:
        d = http_json("https://api.github.com/repos/%s" % repo)
        return {
            "repo": repo,
            "forks": d.get("forks_count"),
            "stars": d.get("stargazers_count"),
            "watchers": d.get("subscribers_count"),
            "pushed_at": d.get("pushed_at"),
            "ok": True,
        }, None
    except Exception as e:
        return {"repo": repo, "forks": None, "stars": None, "watchers": None,
                "pushed_at": None, "ok": False}, "GitHub API：%s" % e


def pypi_stats(pkg: str):
    out = {"package": pkg, "version": None, "downloads_last_month": None,
           "downloads_last_week": None, "ok": False}
    note = None
    try:
        d = http_json("https://pypi.org/pypi/%s/json" % pkg)
        out["version"] = (d.get("info") or {}).get("version")
    except Exception as e:
        note = "PyPI：%s" % e
    try:
        d = http_json("https://pypistats.org/api/packages/%s/recent" % pkg)
        data = d.get("data") or {}
        out["downloads_last_month"] = data.get("last_month")
        out["downloads_last_week"] = data.get("last_week")
        out["ok"] = True
    except Exception as e:
        note = (note + "；" if note else "") + "pypistats：%s" % e
    return out, note


# ─────────────────────────── 组装 ───────────────────────────

def build(args):
    log_paths = expand_logs(args.log)
    if not log_paths:
        log("找不到日志：%s" % " ".join(args.log))
        return None
    scan_all = scan(log_paths, args.days)
    c = scan_all["counts"]
    days_with_data = max(1, len(scan_all["daily"]))
    ledger, ledger_note = ledger_stats(args.db)

    reuse = {"github": None, "pypi": None}
    notes = []
    if args.no_net:
        notes.append("本次跑加了 --no-net，复用两项未取（null 表示没测，不是 0）")
    else:
        gh, gh_note = github_stats(args.repo)
        py, py_note = pypi_stats(args.pkg)
        reuse["github"], reuse["pypi"] = gh, py
        for n in (gh_note, py_note):
            if n:
                notes.append(n)
    if ledger_note:
        notes.append(ledger_note)

    # 给页面的「多久以前」由 app 现算，这里只留时间戳：同一份 JSON 被缓存、
    # 被镜像、被谁拷走，都不会让「数据生成于」这句话跟着变。
    now = datetime.now(CST)
    body = {
        "ok": True,
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_ts": int(now.timestamp()),
        "generator": "repo/deploy/app/collect_metrics.py",
        "window_days": args.days,
        "log": {
            "files": [os.path.basename(p) for p in log_paths],
            "lines": scan_all["lines"],
            "unparsable": scan_all["unparsable"],
            "from": (datetime.fromtimestamp(scan_all["first_ts"], CST).isoformat(timespec="seconds")
                     if scan_all["first_ts"] else None),
            "to": (datetime.fromtimestamp(scan_all["last_ts"], CST).isoformat(timespec="seconds")
                   if scan_all["last_ts"] else None),
        },
        "reads": {
            "external": c["external"],
            "external_per_day": round(c["external"] / days_with_data, 1),
            "external_unique_ips": scan_all["external_unique_ips"],
            "self_probe": c["self"],
            "crawler": c["crawler"],
            "total_2xx": scan_all["total_2xx"],
            "self_ips": scan_all["self_ips"],
        },
        "daily": scan_all["daily"],
        "top_paths": scan_all["top_paths"],
        "ledger": ledger,
        "reuse": reuse,
        "not_measurable": NOT_MEASURABLE,
        "notes": notes,
    }
    return body


def main(argv=None):
    ap = argparse.ArgumentParser(description="聚合公共品指标，写一份 JSON")
    ap.add_argument("--log", action="append", default=None,
                    help="访问日志路径，可重复；支持通配。默认 <data>/access.log*")
    ap.add_argument("--out", default="/opt/drawcommons/app/data/metrics.json")
    ap.add_argument("--db", default="/opt/drawcommons/app/data/ledger.db")
    ap.add_argument("--days", type=int, default=7, help="统计窗口（天），对齐页面上的「近 N 天」")
    ap.add_argument("--repo", default="leigui-888/drawcommons")
    ap.add_argument("--pkg", default="dgb", help="PyPI 包名。注意是 dgb，不是 drawcommons")
    ap.add_argument("--no-net", action="store_true", help="不访问 GitHub / PyPI（离线复算日志）")
    ap.add_argument("--print", dest="print_only", action="store_true", help="只打印，不写文件")
    args = ap.parse_args(argv)
    if not args.log:
        args.log = ["/opt/drawcommons/data/access.log*"]

    body = build(args)
    if body is None:
        return 1
    text = json.dumps(body, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if args.print_only:
        sys.stdout.write(text)
        return 0
    tmp = args.out + ".tmp"
    try:
        with io.open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, args.out)
        # 644：app 容器以 uid 999 只读挂这份目录，读不到就等于没这一页。
        os.chmod(args.out, 0o644)
    except Exception as e:
        log("写不进 %s：%s" % (args.out, e))
        return 1
    log("已写 %s（%d 字节）" % (args.out, len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
