#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reserve_path.py — W5-G2：储备金"第 24 个月达标"这句话能不能成立（L-10 闭合）

数据来源：W4-04（年成本 61,300；6 个月储备 30,650；三档可用资金 15,000 / 45,000 / 90,000；
         中性档三件削减后成本 32,800；悲观档削减后 12,500）。
口径：储备金 = 未指定用途的现金；只能用年度结余积累，不得用资助款直接充抵（W4-04 §1）。
运行：python reserve_path.py
"""

ANNUAL_COST = 61300
RESERVE_MONTHS = 6
TARGET = ANNUAL_COST / 12 * RESERVE_MONTHS   # 30,650

# (标签, 年可用资金, 削减后年成本, 说明)
CASES = [
    ("乐观", 90000, 61300, "人力 10h/周 + 1 名兼职，成本不动"),
    ("中性·缩编", 45000, 32800, "人力减半 + 法务只做协议复核 + 评议改公开征集"),
    ("中性·不缩编", 45000, 61300, "维持原形态"),
    ("悲观·三件削减", 15000, 12500, "取消人力 + 降配 + 评议改征集"),
]

LIMIT_MONTH = 24


def months_to_target(surplus_per_year):
    if surplus_per_year <= 0:
        return None
    return TARGET / surplus_per_year * 12


def fmt(m):
    if m is None:
        return "永不达标"
    return f"{m:.1f} 个月（第 {int(m) + 1} 个月望见）"


def main():
    print("=" * 78)
    print("§1 达标所需月数（储备目标 30,650 = 年成本 61,300 ÷ 12 × 6）")
    print("=" * 78)
    print(f"{'情景':16} {'年可用':>9} {'年成本':>9} {'年结余':>9} {'达标时点':>24}")
    rows = []
    for label, avail, cost, note in CASES:
        surplus = avail - cost
        m = months_to_target(surplus)
        rows.append((label, avail, cost, surplus, m, note))
        print(f"{label:16} {avail:9,.0f} {cost:9,.0f} {surplus:9,.0f} {fmt(m):>24}")

    print()
    print("=" * 78)
    print("§2 第 24 个月末的储备余额（判定'24 个月内达标'这句话）")
    print("=" * 78)
    print(f"{'情景':16} {'24 个月累计结余':>16} {'占目标':>9} {'判定':>12}")
    verdicts = []
    for label, avail, cost, surplus, m, note in rows:
        acc = surplus * 2
        share = acc / TARGET * 100
        if m is None:
            v = "永不成立"
        elif m <= LIMIT_MONTH:
            v = "成立"
        else:
            v = f"不成立（差 {TARGET - acc:,.0f}）"
        verdicts.append((label, v))
        print(f"{label:16} {acc:16,.0f} {share:8.1f}% {v:>12}")

    print()
    print("=" * 78)
    print("§3 逐半年轨迹（只有乐观档在第 24 个月越过目标）")
    print("=" * 78)
    marks = [6, 12, 18, 24, 30, 36]
    header = "情景".ljust(16) + "".join(f"{str(k) + '月':>12}" for k in marks)
    print(header)
    for label, avail, cost, surplus, m, note in rows:
        line = label.ljust(16)
        for k in marks:
            acc = surplus * k / 12
            line += f"{acc:12,.0f}"
        print(line)
    print(f"\n目标线：{TARGET:,.0f}（6 个月运营成本）")

    print()
    print("=" * 78)
    print("§4 结论")
    print("=" * 78)
    good = [l for l, v in verdicts if v == "成立"]
    mid = [l for l, v in verdicts if v.startswith("不成立")]
    never = [l for l, v in verdicts if v == "永不成立"]
    print(f"24 个月内成立：{('、'.join(good)) or '无'}")
    print(f"24 个月内不成立：{('、'.join(mid)) or '无'}")
    print(f"永不成立：{('、'.join(never)) or '无'}")
    print()
    m_mid = [x[4] for x in rows if x[0] == "中性·缩编"][0]
    print(f"最可能的一档是中性·缩编（可用 45,000），它需要 {m_mid:.1f} 个月——比 24 个月多 "
          f"{m_mid - 24:.1f} 个月。")
    print("所以章程若写'设立后第 24 个月内达标 6 个月储备'，对最可能档是一句写在纸上的违约。")
    print()
    print("W5 冻结写法（见 W5-02 §2.3）：")
    print("  目标：6 个月运营成本；判定口径：连续 12 个月滚动结余 ≥ 目标；")
    print("  未达标：触发披露义务（年度报告单列），不构成违约、不触发清算、不改变性质。")
    print("  理由：把'期限'换成'口径'，条款才既可执行又不说谎。")


if __name__ == "__main__":
    main()
