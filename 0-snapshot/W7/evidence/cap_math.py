# -*- coding: utf-8 -*-
"""W7 集中度上限的四个数（R12 落地时补分母句的依据）

为什么要有这个脚本：
    04 §4 写"单一资助方年度占比 ≤25%"，06 §6.1 写"超出部分入搁置账户"，
    W5-04 章程第十五条写"上一年度经审计运营成本"。
    三处都写了上限，但只有第三处写了分母；而分母在 S0/S1 阶段不存在（没有主体，没有审计）。
    一条算不出来的上限，在能用的阶段是空的，在存在的阶段用不上——
    这是 W7-C3 必须补的一句，不是措辞问题。

本脚本算四件事：
    §1 四个分母口径下，同一笔钱是合规还是超限（含 S0/S1/S2 分母可用性）
    §2 上限与储备门槛是否咬合（18,390 能买下几个月的安全）
    §3 25% 的真实含义：最少几个资助方，以及合并规则是不是唯一防线
    §4 人力折算：第一个志愿者会不会让条款失效
"""

from math import ceil

COST = 61300          # 年运营成本（W4-04 实数）
AUDIT_MULT = 1.2      # W5-02 §2.2 冻结的缓冲系数
BASE = COST * AUDIT_MULT          # 73,560
NOMINAL_CAP = BASE * 0.25         # 18,390：25% 单口径（未与储备门槛取小）
RESERVE_3M = COST / 12 * 3        # 15,325：3 个月运营成本
CAP = min(NOMINAL_CAP, RESERVE_3M)  # 15,325：W7-02 §0.1.9.4 采纳值，全脚本统一使用


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def part1():
    sec("§1 四个分母，同一笔 45,000")
    amount = 45000
    rows = [
        ("自报总预算 200,000", 200000, "S0 可算", "把'明年想花多少'当分母"),
        ("本年实际支出 61,300", COST, "S1 可算", "未审计，但至少是实数"),
        ("审计成本 × 1.2 = 73,560", BASE, "S1/S2 可算", "W5-02 冻结口径"),
        ("上年审计成本（章程原文）", COST, "S2 才有", "S0/S1 无审计 → 分母为空"),
    ]
    print(f"{'分母口径':28}{'分母':>9}{'占比':>9}{'判定':>8}   可用阶段")
    for name, d, stage, note in rows:
        pct = amount / d
        verdict = "超限" if pct > 0.25 else "合规"
        print(f"{name:28}{d:>9,}{pct:>8.1%}{verdict:>8}   {stage}")
    print()
    print(f"同一笔 {amount:,}：最松的口径 22.5% 合规，最严的 73.4% 超限 2.9 倍。")
    print("差别不在金额，在分母。**分母不写死，上限就是不存在的。**")

    print()
    print("分母在三个阶段的存在性：")
    stage = [
        ("S0 非法人", "无", "个人账户，无审计，无'上年运营成本'这一事实"),
        ("S1 托管", "有（托管方审计）", "托管方出具收支报告，可作分母，但需协议约定"),
        ("S2 非营利", "有（法定审计）", "章程原文即按此写"),
    ]
    print(f"  {'阶段':12}{'分母':20}说明")
    for a, b, c in stage:
        print(f"  {a:12}{b:20}{c}")
    print()
    print("所以章程第十五条在 S0/S1 的实际效力是：**无法计算 → 无法执行 → 等于没有上限**。")
    print("而 S0/S1 恰恰是这家机构最容易被一笔钱买走的阶段。")


def part2():
    sec("§2 上限与储备门槛是否咬合")
    monthly = COST / 12
    reserve3 = monthly * 3
    reserve6 = monthly * 6
    print(f"  月运营成本        {monthly:>10,.0f}")
    print(f"  3 个月运营成本    {reserve3:>10,.0f}   ← 06 §4.4 极端情形的判据")
    print(f"  6 个月储备目标    {reserve6:>10,.0f}   ← W4-04 的首年现金需求口径")
    print(f"  单一资助方名义上限 {NOMINAL_CAP:>9,.0f}   ← 25% 单口径（下文论证的对象）")
    print()
    print(f"  名义上限 / 3 个月成本 = {NOMINAL_CAP/reserve3:.2f} 倍")
    print(f"  名义上限 / 6 个月储备 = {NOMINAL_CAP/reserve6:.2f} 倍")
    print()
    print("  一个资助方给满上限，就等于给了 3.6 个月的运营成本——")
    print("  它单枪匹马就能把项目从'低于 3 个月'的极端情形里拉出来，")
    print("  也能在撤资当天把项目推回去。")
    print()
    print("  这不是上限设错了，是**上限与储备门槛用了两套单位**：")
    print("  上限按'年成本的比例'算，储备门槛按'月数'算，两者从未对齐。")
    print("  处置建议：把 25% 同时写成'且不超过 3 个月运营成本'，取小者——")
    print(f"  即实际单一上限 = min({NOMINAL_CAP:,.0f}, {reserve3:,.0f}) = {min(NOMINAL_CAP, reserve3):,.0f}。")
    print(f"  这一句会让单一资助方上限从 {NOMINAL_CAP:,.0f} 降到 {min(NOMINAL_CAP, reserve3):,.0f}，降幅 {1-min(NOMINAL_CAP, reserve3)/NOMINAL_CAP:.1%}。")
    print(f"  （W7-02 §0.1.9.4 已采纳取小值；本脚本此后一律使用 CAP = {CAP:,.0f}，上方倍数是对名义值 {NOMINAL_CAP:,.0f} 的论证。）")


def part3():
    sec("§3 25% 的真实含义：最少几个资助方")
    n = ceil(1 / 0.25)
    print(f"  1 / 25% = {1/0.25:.0f} → 至少 {n} 个资助方才能填满预算")
    print("  也就是说，'单一资助方 ≤25%'等价于'至少 4 个来源'。")
    print("  条款没有这么说，但这是它唯一的意思——应该写进条款，而不是让读者自己推。")
    print()
    print("  绕过检验（4 家各 24%）：")
    each = BASE * 0.24
    print(f"    每家 {each:,.0f}（24.0%）→ 单方全部合规")
    print(f"    合计 {each*4:,.0f}（96.0%）→ 预算几乎由 4 家填满")
    print()
    print("  若 4 家为同一实控人：合并后被 96% 卡住 → 合并规则有效（W5-03 §2.2）。")
    print("  若 4 家真无关联：单方合规、合计 96% → 俘获风险低，但**断供风险极高**。")
    print()
    print("  所以 25% 测的是'俘获'，不是'韧性'。两件事需要两个指标：")
    print("    俘获：单一 + 合并关联方 ≤25%   （红线，R12）")
    print("    韧性：前 3 大来源合计 ≤70%，且来源数 ≥6（警戒线，不进红线）")
    top3 = BASE * 0.70
    print(f"  按此，前 3 大合计上限 = {top3:,.0f}，来源数下限 = 6。")
    print("  把韧性写成红线会犯一个错：**穷的时候没有资格挑资助方**。")
    print("  所以它是警戒线——触发时要公开说明依赖结构，不是拒收。")


def part4():
    sec("§4 人力折算：25% 在人力维度上根本算不出来")
    rate = 85                     # 公开时价（W4-04）
    own_h = 25 * 48               # 单人 25h/周 × 48 周（02 §产能假设）
    own_val = own_h * rate
    own_cost = COST * 0.734       # W4-04：人力占比 73.4%
    implied = own_cost / own_h    # 实际人力单价

    print(f"  自有维护者：{own_h:,} 小时 × ¥{rate}/h = {own_val:,} 元"
          f"（{own_val/BASE:.1%} of {BASE:,.0f}）")
    print(f"  但账上人力成本只有 {own_cost:,.0f} 元 → 隐含单价 ¥{implied:.1f}/h")
    print(f"  时价与实际成本差 {rate/implied:.2f} 倍")
    print()
    print(f"  按公开时价折算，**核心维护者一个人的工时就已超 25% 上限 {own_val/BASE/0.25:.1f} 倍**。")
    print(f"  按实际成本折算，{own_cost/BASE:.1%}，仍超上限 {own_cost/BASE/0.25:.1f} 倍。")
    print("  两种口径都超——所以 25% 不可能包含自有维护者的人力：")
    print("  它会让这个项目从成立第一天起就永久违规，违规者是那个不领钱写代码的人。")
    print()
    print("  那外部捐赠人力呢？")
    people, hours, weeks = 2, 40, 13
    h = people * hours * weeks
    val = h * rate
    # 用采纳后的实际上限（取小值 15,325），不是 18,390
    cap_h = min(BASE * 0.25, COST / 12 * 3) / rate
    print(f"    {people} 人 × {hours}h × {weeks} 周 = {h:,} 小时 = {val:,} 元"
          f"（{val/BASE:.1%}）→ 超限 {val/BASE/0.25:.1f} 倍")
    print(f"    上限折成工时只有 {cap_h:.0f} 小时 ≈ 1 人 × {cap_h/54:.1f}h/周 × 54 周")
    print()
    print(f"  也就是说：一份「每周来 {cap_h/54:.1f} 小时」的志愿投入就到顶了。")
    print("  任何真来帮忙一个季度的人，都会被条款判为'俘获'。")
    print()
    print("  结论：人力不能与现金共用 25%。处置是分类，不是调阈值：")
    rows = [
        ("现金与实物", "min(25% × 73,560, 3 个月成本) = 15,325", "取小值（W7-02 §0.1.9.4 已采纳）"),
        ("自有维护者人力", "不计入（属成本，不是资助）", "按实际支出记账；按市价折算只作披露"),
        ("外部捐赠人力", "≤ 自有维护者工时的 50%", f"= {own_h*0.5:,.0f} 小时 ≈ 11.5h/周，一家出不起这么多人"),
    ]
    print(f"    {'类别':16}{'上限':34}说明")
    for a, b, c in rows:
        print(f"    {a:16}{b:34}{c}")
    print()
    print("  为什么用'自有工时的比例'而不是'运营成本的比例'：")
    print("  外部人力真正的风险不是'值多少钱'，是'人多过自家人'——")
    print("  当外部人力的总量超过核心团队，议程就会跟着会议室里的人走，")
    print("  而这与钱多少无关。用人数与工时比，才测得到这件事。")


def numbers():
    """给 main 用的汇总数（避免在 main 里重算或引用局部变量）。"""
    rate = 85
    own_h = 25 * 48
    own_val = own_h * rate
    people, hours, weeks = 2, 40, 13
    ext_val = people * hours * weeks * rate
    return dict(own_val=own_val, own_pct=own_val / BASE, ext_val=ext_val,
                ext_pct=ext_val / BASE, cap_h=min(BASE * 0.25, COST / 12 * 3) / rate)


def main():
    part1()
    part2()
    part3()
    part4()
    print()
    print("汇总：")
    n = numbers()
    print(f"  同一笔 45,000 按四个分母：22.5% / 73.4% / 61.2% / 73.4% → 判定从合规翻到超限 2.9 倍")
    print(f"  S0/S1 无审计 → 章程第十五条在这两个阶段算不出来（空格）")
    print(f"  名义上限 {NOMINAL_CAP:,.0f} = 3.6 个月成本，与'3 个月'判据未咬合 → 采纳取小值 CAP = {CAP:,.0f}")
    print(f"  25% 等价于'至少 4 个来源'；4×24% 可填满 96%，合并规则是唯一防线")
    print(f"  自有维护者 {n['own_val']:,.0f}（{n['own_pct']:.0%}）、外部 2 人 1 季度 "
          f"{n['ext_val']:,.0f}（{n['ext_pct']:.0%}）→ 人力必须与现金分类，不能共用 25%")


if __name__ == "__main__":
    main()
