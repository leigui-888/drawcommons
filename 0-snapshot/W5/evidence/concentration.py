#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
concentration.py — W5-G3 反俘获：集中度口径测算（D-1 / D-2 的证据）

用途：证明"单一资助方年度占比 ≤25%"这句话，在分母未写死时有三种都算"合规"的解法；
      并给出关联方合并、人力捐赠折算、回避算术三处的实测差额。

数据来源：W4-04（年成本 61,300；三档削减后成本 32,800 / 15,500 / 12,500）、06 §6、白皮书 §6.3、R12。
运行：python concentration.py
"""

ANNUAL_COST = 61300          # W4-04 §2，单人最低形态年运营成本
COST_AFTER_CUT = 32800       # W4-04 §5.2，中性档三件削减后
CAP_RATE = 0.25              # 06 §6.1 / R12 / 白皮书 §6.3 共用数值
BUFFER = 1.2                 # 冻结口径里的 20% 缓冲（理由见 W5-02 §2.2）

DENOMS = [
    ("D-A 申请方自报总预算（200,000）", 200000, "被约束者自己定分母"),
    ("D-B 上一年度审计确认年成本（61,300）", ANNUAL_COST, "低报即锁死额度，但会被指为不可执行"),
    ("D-C 审计年成本 × 1.2（73,560）", round(ANNUAL_COST * BUFFER), "W5 冻结口径"),
]

GIFTS = [("单一资助方现金 45,000", 45000)]

MERGE = [("A 单独", [("A", 12000)]),
         ("A + 关联方 B 合并", [("A", 12000), ("B", 7000)])]

STAFF = {"人数": 2, "周工时": 40, "周数": 13, "时价": 85}


def pct(x, d):
    return x / d * 100


def sec(title):
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def part1():
    sec("§1 同一个 45,000，三种分母，三种结论（D-1 的核心）")
    print(f"{'分母口径':44} {'上限':>10} {'占比':>8} {'判定':>6} {'搁置':>10}")
    for name, den, note in DENOMS:
        cap = den * CAP_RATE
        for gname, g in GIFTS:
            take = pct(g, den)
            ok = "合规" if take <= CAP_RATE * 100 else "超限"
            hold = max(0, g - cap)
            print(f"{name:44} {cap:10,.0f} {take:7.1f}% {ok:>6} {hold:10,.0f}")
            print(f"{'':44} {'':10} {'':8} {'':6}  ← {note}")
    print()
    print("读法：同一笔 45,000 在 D-A 下是 22.5%（合规、全额入账），在 D-B 下是 73.4%（超限 2.9 倍）。")
    print("      '不超过 25%' 这句话本身不构成约束，约束的是分母。")


def part2():
    sec("§2 关联方合并：分开算都合规，合并算超限（D-2 前半）")
    den = round(ANNUAL_COST * BUFFER)
    cap = den * CAP_RATE
    print(f"冻结分母 D-C = {den:,}，年度上限 = {cap:,.0f}")
    print()
    print(f"{'口径':24} {'主张金额':>10} {'占比':>8} {'判定':>6} {'超出上限':>10}")
    for label, items in MERGE:
        total = sum(v for _, v in items)
        take = pct(total, den)
        ok = "合规" if take <= 25.0 else "超限"
        over = max(0, total - cap)
        print(f"{label:24} {total:10,.0f} {take:7.1f}% {ok:>6} {over:10,.0f}")
    print()
    a = MERGE[0][1][0][1]
    print(f"A 单独 {a:,} = {pct(a, den):.1f}%，B 单独 7,000 = {pct(7000, den):.1f}%，两项各自看不出问题；")
    print(f"合并后 {a + 7000:,} = {pct(a + 7000, den):.1f}%，超限 {a + 7000 - cap:,.0f}。")
    print("结论：合并计算必须写进条款，否则'拆成两笔'就是标准绕法。")


def part3():
    sec("§3 人力捐赠折算：不花现金的一项，单独就击穿上限（06 §6.2 的量化）")
    hours = STAFF["人数"] * STAFF["周工时"] * STAFF["周数"]
    value = hours * STAFF["时价"]
    den = round(ANNUAL_COST * BUFFER)
    cap = den * CAP_RATE
    print(f"{STAFF['人数']} 人 × {STAFF['周工时']}h/周 × {STAFF['周数']} 周 = {hours:,} 小时，按 ¥{STAFF['时价']}/h = ¥{value:,}")
    print(f"折算后占比 {pct(value, den):.1f}%，上限 {cap:,.0f}，超限 {value - cap:,.0f}")
    print()
    print("注意口径冲突：W4-04 §1 明确'不含人力捐赠（时间）折算'——那是缺口测算（现金口径）。")
    print("集中度必须用含人力折算的口径，否则'派人来干活'是零成本绕过 25% 的唯一通道。")
    print("两个口径都合法，但必须分别命名：'现金覆盖率'（W4-04）与'资助集中度'（W5-G3）。")


def part4():
    sec("§4 回避算术：75% 门槛在分母缩小后反而更容易跨过（D-2 后半）")

    def need(denom):
        import math
        return math.ceil(denom * 0.75)

    members, related = 100, 40
    n1, n2 = need(members - related), need(members)
    print(f"{'分母随回避缩小（错误写法）':32} 分母 {members - related:3} → 需 {n1:3} 票")
    print(f"{'分母固定为回避前总数（W5 冻结）':32} 分母 {members:3} → 需 {n2:3} 票")
    print()
    print(f"差额：{n1} 票 vs {n2} 票 = {n2 - n1} 票。")
    print("这 30 票不是小数目——它等于把 40 位关联成员全部'声明回避'掉所省下的门槛。")
    print("即：资助方可以用'让关联成员回避'来降低修法门槛。回避只剔分子、不缩分母，否则是反效果。")
    print("同时补一条：未回避成员须过半数参与（100-40=60 人里至少 31 人到场），防止'没人来'变成'自动通过'。")


def part5():
    sec("§5 三个数字与一条纪律")
    den = round(ANNUAL_COST * BUFFER)
    print(f"1. 冻结分母 {den:,}（年成本 {ANNUAL_COST:,} × 1.2），年度上限 {den * 0.25:,.0f}。")
    print(f"2. 现金口径年成本 {ANNUAL_COST:,}；中性档削减后 {COST_AFTER_CUT:,}；两者都可作 20% 成本回收上限的分母，但须写明用哪一个。")
    print("3. 单一资助方上限与成本回收上限是两个不同的数（25% / 20%），分母也不同，不可互相引用。")
    print()
    print("纪律：任何人提出'这次特殊，先收下'时，判定问句是——这笔钱让谁获得了对路线图的一次发言权？")
    print("      答不出'没有'，即触发 §4 的实质变更审查，不走理事会表决。")


if __name__ == "__main__":
    part1()
    part2()
    part3()
    part4()
    part5()
