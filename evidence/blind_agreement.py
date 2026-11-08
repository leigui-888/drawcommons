#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""判据卡 v2.4 盲测一致性计算器（L-11 的验收工具）。

验收规则来自 `W2-P1` §4（v2.3 定稿时的强制盲测规程），本脚本不改规则，只执行：
  R1 评审人 ≥2 位（建议 3）
  R2 样本 8 个，每人 8 个全填
  R3 结论一致 ≥7/8（按"整样本三判据全对"计）
  R4 每条判据在 ≥5 个样本上被"使用"（即被明确填了 Y/N，而非全填 ?）
  R5 无 Y/N 相反用法（0 处）

没有结果文件或结果为空时，本脚本**不会**给出"通过"——它输出"未执行"并以退出码 2 结束。
这是故意的：一个在缺数据时默认通过的验收工具，是这整套东西里最危险的一件。

用法：
    python blind_agreement.py                 # 读 blind/key.csv + blind/results.csv
    python blind_agreement.py --results x.csv
退出码：通过 0；不通过 1；未执行 2
"""

from __future__ import annotations

import csv
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
KEY = os.path.join(BASE, "blind", "key.csv")
RESULTS = os.path.join(BASE, "blind", "results.csv")
# 平台限制：资料库把 .csv 落成「表格节点」，不能作为文件节点下载，
# 因此同一份数据另存 JSON 镜像；CSV 在则读 CSV，不在则读 JSON，两者都不在才算缺件。
KEY_JSON = os.path.join(BASE, "blind", "key.json")
RESULTS_JSON = os.path.join(BASE, "blind", "results.json")
CRITERIA = ["P1", "P4", "P5"]
MIN_REVIEWERS = 2
MIN_AGREE = 7
MIN_USE = 5
SAMPLES = 8


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def _rows_from_json(path):
    """把 {"columns": [...], "rows": [[...]]} 还原成 DictReader 那样的字典列表。"""
    import json

    with open(path, encoding="utf-8") as f:
        obj = json.load(f)
    cols = obj["columns"]
    return [dict(zip(cols, row)) for row in obj["rows"]]


def _load(path, json_path):
    if os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f)), "csv"
    if os.path.exists(json_path):
        return _rows_from_json(json_path), "json"
    return [], "missing"


def load_key():
    rows, src = _load(KEY, KEY_JSON)
    if src == "missing":
        print("缺 key：blind/key.csv 与 blind/key.json 都不存在，判定不成立。")
        sys.exit(2)
    print(f"  key 来源：blind/key.{src}")
    return {r["sample"].strip(): r for r in rows}


def load_results(path):
    if not os.path.exists(path):
        if path == RESULTS and os.path.exists(RESULTS_JSON):
            rows, src = _rows_from_json(RESULTS_JSON), "json"
            print(f"  results 来源：blind/results.{src}")
            return [r for r in rows if (r.get("reviewer") or "").strip() and (r.get("sample") or "").strip()]
        return []
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
        return [r for r in rows if (r.get("reviewer") or "").strip() and (r.get("sample") or "").strip()]


def main():
    path = RESULTS
    if "--results" in sys.argv:
        path = sys.argv[sys.argv.index("--results") + 1]

    print("=" * 78)
    print("W6·判据卡 v2.4 盲测一致性（L-11）")
    print("=" * 78)

    key = load_key()
    rows = load_results(path)

    sec("§1 数据状况")
    print(f"  样本数（key）：{len(key)} 个")
    reviewers = sorted({r["reviewer"].strip() for r in rows})
    shown = path if os.path.exists(path) else RESULTS_JSON
    print(f"  结果文件：{os.path.relpath(shown, BASE)}　记录 {len(rows)} 条")
    print(f"  评审人：{len(reviewers)} 位" + (f"（{'、'.join(reviewers)}）" if reviewers else "（无）"))

    if not rows:
        sec("§2 判定")
        print("  ❌ 未执行：结果文件为空")
        print()
        print("  缺的是什么，缺在谁身上：")
        print(f"    · 需 ≥{MIN_REVIEWERS} 位**未参与本项目**的评审人（建议 3 位）")
        print(f"    · 每人独立完成 {SAMPLES} 个样本 × {len(CRITERIA)} 条判据")
        print("    · 只发 blind/samples.md，不发 blind/key.csv")
        print()
        print("  这不是'可以跳过'的一项。v2.3 的第一轮盲测就是"
              "「文本看起来没问题、6 个样本里判错 2 个」才被推翻的；")
        print("  v2.4 改的正是那两处判错的地方——没有盲测，就无法排除"
              "「改完之后仍然会被同一批人判错」。")
        print()
        print(f"  汇总：评审人 0/{MIN_REVIEWERS}；样本 0/{SAMPLES}；一致率 —；判定：未执行")
        sys.exit(2)

    sec("§2 逐人一致率与相反用法")
    ok_all = True
    per_reviewer = {}
    for rv in reviewers:
        mine = {r["sample"]: r for r in rows if r["reviewer"] == rv}
        agree = 0
        oppose = []
        for s, k in key.items():
            m = mine.get(s)
            if not m:
                continue
            same = all((m.get(c) or "").strip().upper() == k[c] for c in CRITERIA)
            if same:
                agree += 1
            for c in CRITERIA:
                g = (m.get(c) or "").strip().upper()
                truth = k[c]
                if {g, truth} == {"Y", "N"}:
                    oppose.append(f"{s}.{c}（判 {g}，基准 {truth}）")
        per_reviewer[rv] = (agree, oppose)
        flag = "✅" if agree >= MIN_AGREE and not oppose else "❌"
        print(f"  {flag} {rv:12} 一致 {agree}/{len(key)}　相反用法 {len(oppose)} 处")
        for o in oppose:
            print(f"        · 相反：{o}")
        ok_all = ok_all and agree >= MIN_AGREE and not oppose

    sec("§3 每条判据被使用的样本数")
    used = {c: 0 for c in CRITERIA}
    for r in rows:
        for c in CRITERIA:
            if (r.get(c) or "").strip().upper() in ("Y", "N"):
                used[c] += 1
    for c, n in used.items():
        print(f"  {'✅' if n >= MIN_USE else '❌'} {c}：{n} 次（阈值 {MIN_USE}）")
    ok_use = all(n >= MIN_USE for n in used.values())

    sec("§4 判定")
    checks = [
        (f"R1 评审人 ≥{MIN_REVIEWERS} 位", len(reviewers) >= MIN_REVIEWERS),
        (f"R2 每人 {SAMPLES} 个样本全填",
         all(len({r['sample'] for r in rows if r['reviewer'] == rv}) >= SAMPLES for rv in reviewers)),
        (f"R3 一致 ≥{MIN_AGREE}/{SAMPLES}", ok_all),
        (f"R4 每判据使用 ≥{MIN_USE} 样本", ok_use),
        ("R5 无 Y/N 相反用法 0 处", all(not v[1] for v in per_reviewer.values())),
    ]
    for name, v in checks:
        print(f"  {'✅' if v else '❌'} {name}")
    passed = all(v for _, v in checks)
    print()
    print(f"  判定：{'通过（L-11 可闭合）' if passed else '不通过（v2.4 仍为 L1 文本，不得对外发布）'}")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
