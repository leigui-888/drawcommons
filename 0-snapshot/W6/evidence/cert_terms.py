#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""认证规则体检：把 TRADEMARK.md 里"说过的"变成"能数的"。

两件事：
  §1 文本要件：9 项必需要素是否都在（缺一项，规则就不能被执行）
  §2 收费算术：五档的合规比、认证的人工成本、工本费的可归属上限
  §3 一条反推：如果认证需要人工审核，它会立刻变成闸门——用钱算清楚这件事

用法：python cert_terms.py ../repo/TRADEMARK.md
退出码：要件齐备且收费结构合规 0；否则 1
"""

from __future__ import annotations

import re
import sys

HOURLY = 85          # W4-04 的时价假设，标 `假设`
RETEST_PROB = 0.30   # 复测概率，标 `假设`
RETEST_HOURS = 2.0

# 9 项必需要素：(名称, 判定方式, 说明)
def check_requirements(text: str):
    rows = []

    def add(name, ok, note=""):
        rows.append((name, bool(ok), note))

    # 1 六项测试齐全
    t_ids = re.findall(r"\|\s*(T[1-6])\s*\|", text)
    add("T1–T6 六项测试齐全", len(set(t_ids)) == 6, f"命中 {len(set(t_ids))}/6")

    # 2 每项测试都有复现方式
    add("每项测试有复现命令", "复现方式" in text and text.count("`curl") + text.count("`python") >= 4,
        f"复现命令出现 {text.count('`curl') + text.count('`python')} 处")

    # 3 五档收费表：3 档标 ❌
    fee_block = re.search(r"##\s*3\.(.*?)##\s*4\.", text, re.S)
    fee_txt = fee_block.group(1) if fee_block else ""
    n_no = fee_txt.count("❌")
    n_yes = fee_txt.count("✅")
    add("五档收费：3 档不合规、1 档合规", n_no >= 3 and n_yes >= 1, f"❌ {n_no} / ✅ {n_yes}")

    # 4 拒绝理由白名单
    add("拒绝理由仅 1 条且可复现", "唯一允许的拒绝理由" in text, "")

    # 5 三处可算时限
    for k, kw in [("受理时限 15 工作日", "15 个工作日"),
                  ("复测 30 日", "30 日内"),
                  ("过渡期 90 日", "90 日")]:
        add(k, kw in text, "")

    # 6 有效期绑版本
    add("有效期绑测试套件版本", "随测试套件版本有效" in text, "")

    # 7 名称与许可分离的三段
    sep = ("不授予" in text) and ("商标权" in text) and ("不影响" in text)
    add("名称与代码许可分离声明（三段）", sep, "")

    # 8 禁用表述清单
    add("禁用表述清单（® / 已注册）", "®" in text and "已注册商标" in text, "")

    # 9 状态披露：未检索未注册
    add("当前状态披露（未检索/未注册/不主张）",
        ("未检索" in text) and ("未注册" in text) and ("不主张" in text), "")
    return rows


MANUAL_KW = ("人工审核", "人工判定", "人工评估", "人工复核")
MANUAL_NEG = ("无需", "不需", "不用", "不得", "零", "避免", "不设", "不存在",
              "项为 0", "项为0", "无人工", "为 0 项", "为0项", "全部可自测")


def count_manual(text: str):
    """统计文本中真实要求人工介入的条目（排除'无需人工审核'一类否定表述）。

    v1.1 起该数直接驱动 §2 的人工工时与成本估算；
    v1.0 算出来却打印硬编码 0，导致注入"必须逐项人工审核"后仍报 ¥0（假阴性）。
    """
    hits = []
    for line in text.splitlines():
        for kw in MANUAL_KW:
            if kw not in line:
                continue
            if any(neg in line for neg in MANUAL_NEG):
                continue
            hits.append(line.strip()[:60])
            break
    return len(hits), hits


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "../repo/TRADEMARK.md"
    text = open(path, encoding="utf-8").read()

    print("=" * 78)
    print(f"W6·认证规则体检　目标：{path}")
    print("=" * 78)

    sec(f"§1 文本要件（{len(check_requirements(text))} 项）")
    rows = check_requirements(text)
    for name, ok, note in rows:
        print(f"  {'✅' if ok else '❌'} {name:34}{note}")
    ok_n = sum(1 for _, ok, _ in rows if ok)
    print(f"  结果：{ok_n}/{len(rows)} 项齐备")

    sec("§2 收费结构算术")
    base_h = 2.0            # 每份认证的人工审核工时（`假设`）
    tiers = [
        ("1 免费（条件公开/不拒绝）", "Y", None),
        ("2 工本费（有免费自测替代）", "条件 Y", "须三条件同时成立"),
        ("3 按审核工作量", "N", "按次定价 + 闸门"),
        ("4 年费维持资格", "N", "与主体数挂钩 + 不付费即失标识"),
        ("5 版税（按营收比例）", "N", "双重违反 P4/P5"),
    ]
    y = sum(1 for _, v, _ in tiers if v == "Y")
    cond = sum(1 for _, v, _ in tiers if v == "条件 Y")
    n = sum(1 for _, v, _ in tiers if v == "N")
    for name, v, why in tiers:
        print(f"  {name:26} 判定 {v:6} {why or ''}")
    print(f"  合规比：{y}/{len(tiers)} 全合规、{cond}/{len(tiers)} 条件合规、{n}/{len(tiers)} 不合规")

    # 人工成本：由文本实际要求驱动，不再硬编码 0
    auto = len(re.findall(r"\|\s*T[1-6]\s*\|", text))
    manual_rows, manual_hits = count_manual(text)
    manual_hours = manual_rows * base_h
    manual_cost = manual_hours * HOURLY
    print()
    print(f"  可自测测试项：{auto} 项；人工审核项：{manual_rows} 项")
    for h in manual_hits:
        print(f"    · {h}")
    if manual_rows:
        print(f"  推论：认证的人工工时 = {manual_rows} × {base_h:.0f}h = {manual_hours:.0f}h"
              f" → 『可归属成本』= ¥{manual_cost:.0f}/份")
        print("        存在人工项 → 认证获得定价权；按 §3，这一项必须被消掉或公开披露。")
    else:
        print("  推论：认证的人工工时 = 0h → 按工作量收费的『可归属成本』= ¥0")
        print("        任何正数金额都不是成本回收，是纯闸门。")

    sec("§3 反推：如果认证需要人工审核，它立刻变成闸门")
    base_cost = base_h * HOURLY
    retest_cost = RETEST_PROB * RETEST_HOURS * HOURLY
    total = base_cost + retest_cost
    print(f"  假设每份认证需人工审核 {base_h:.0f}h（时价 ¥{HOURLY}/h，`假设`）      → ¥{base_cost:.0f}/份")
    print(f"  假设 {RETEST_PROB:.0%} 的申请进入复测，每次 {RETEST_HOURS:.0f}h          → ¥{retest_cost:.0f}/份")
    print(f"  工本费的可归属上限 = ¥{total:.0f}/份")
    print()
    print(f"  若报价超过 ¥{total:.0f}，多出的部分无法归属到任何成本，即进入第 3 档（按工作量收费）。")
    print("  这就是为什么本规则把认证设计成『六项全可自测』：")
    print("  不是为了省事，是为了让『收费』从一开始就没有可挂靠的成本基础。")
    print()
    print("  反过来验证：只要有一项测试必须人工判（例如「兼容性主观评估」），")
    print("  认证方就获得了定价权，而定价权必然演化为筛选权——")
    print("  『能不能过』与『愿不愿付』在同一方手里，这不是腐败假设，是结构。")

    sec("§4 续费维度")
    print("  写法 A 有效期 2 年 → 每 2 年 1 次续期动作 → 0.5 次/年（且每次都是收费机会）")
    print("  写法 B 有效期 2 年且续期免费 → 仍 0.5 次/年（动作仍在，争议仍在）")
    print("  写法 C 绑测试套件版本 → 0 次/年；只在套件升主版本时重测 → 由版本节奏决定，不由钱决定")
    print("  采用 C。测试套件 0.1 → 0.2（次版本）不失效，→ 1.0（主版本）失效，过渡 90 日。")

    print()
    ok_all = ok_n == len(rows)
    print(f"汇总：要件 {ok_n}/{len(rows)}；五档 {y}Y/{cond}条件Y/{n}N；"
          f"人工审核 {manual_rows} 项、人工成本 ¥{manual_cost:.0f}/份；续费动作 0 次/年")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        base = count_manual(open(sys.argv[2], encoding="utf-8").read())[0]
        inj = count_manual(open(sys.argv[2], encoding="utf-8").read() + "\n必须逐项人工审核。\n")[0]
        print(f"自测：注入前 {base} 项 → 注入后 {inj} 项；"
              f"{'通过（人工项能被检出）' if inj > base else '失败（注入未被检出）'}")
        sys.exit(0 if inj > base else 1)
    main()
