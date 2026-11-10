# -*- coding: utf-8 -*-
"""W7 收款判定器：把"能不能收"拆成两个问题

为什么要有这个脚本：
    排期表把"能合法接受资助"写成 C1–C4 四件事，四件都产文本。
    但真正会出错的地方不在文本，在**一个具体的人拿着钱走过来**的时候。

    而 08 自己在两张表里给了两个答案：
        §3     S0「不得对外收款、不得开对公账户」
        §3.1.1 S0「能收：企业赞助、个人定向赠与、服务采购款」
    白皮书 §7.5 与 W5-03 §3 又说 S0/S1 只能拒收。三处不能同时成立。

    矛盾的根源是把两个问题混成了一个：
        问题一（应否）：这笔钱的性质与条件，允不允许我们收？——法律 + 定位，与阶段无关
        问题二（能否）：现在有没有一个合法落点把它接住？——主体 + 账户，与钱无关
    一笔钱可以"应该收但现在收不了"（S0 的一切款项），也可以"现在能收但不该收"（无资格公开募捐）。
    合成一个问题问，就只能得到一张自相矛盾的表。

用法：
    python gate_check.py            # 跑 12 个场景
    python gate_check.py -v         # 附每个场景的逐闸理由

口径来源：
    - 三阶段边界：08 §3.1.1，但 S0 一列按 W5-03 §3 裁定（只能拒收）
    - 25% 上限：W5-03 §2.1（分母 73,560 = 61,300 × 1.2；上限 18,390）
    - R9–R12：04 §4，W7-03 增补要件与分母
"""

import sys

CAP = 15325          # 单一资助方年度上限 = min(25% × 73,560 = 18,390, 3 个月运营成本 15,325)
# W7-02 §0.1.9.4 采纳取小值；沿用 18,390 会让"上限"等于 3.6 个月成本（cap_math §2）
BASE = 73560         # 分母：上年审计运营成本 61,300 × 1.2
EXCLUSIVE = ("曝光", "排名", "优先", "认证")   # 排他性回报 → R10

# public  : 是否面向不特定公众发出给钱邀约
# consid  : 对价（None = 非交换性）
# cond    : 附加条件
# in_kind : 实物/人力（无需账户即可接收）
SCENARIOS = [
    dict(id="S01", name="个人读者定向赠与 ¥200，无任何回报", stage="S0",
         public=False, consid=None, cond=[], amount=200, in_kind=False),
    dict(id="S02", name="README 挂「赞助我们」按钮 + 收款码", stage="S0",
         public=True, consid=None, cond=[], amount=0, in_kind=False),
    dict(id="S03", name="企业赞助 ¥45,000，要求首页 logo 与季度品牌露出", stage="S0",
         public=False, consid="曝光", cond=[], amount=45000, in_kind=False),
    dict(id="S04", name="企业无回报赞助 ¥12,000", stage="S0",
         public=False, consid=None, cond=[], amount=12000, in_kind=False),
    dict(id="S05", name="基金会 ¥50,000，要求进入指导委员会", stage="S0",
         public=False, consid=None, cond=["治理权"], amount=50000, in_kind=False),
    dict(id="S06", name="云厂商赠算力，公开市价 ¥20,000", stage="S0",
         public=False, consid=None, cond=[], amount=20000, in_kind=True),
    dict(id="S07", name="委托开发 ¥30,000，交付代码", stage="S0",
         public=False, consid="开发交付", cond=[], amount=30000, in_kind=False),
    dict(id="S08", name="平台激励 ¥5,000，无附加条件", stage="S0",
         public=False, consid=None, cond=[], amount=5000, in_kind=False),
    dict(id="S09", name="托管方发起公开募捐，本项目为执行方", stage="S1",
         public=True, consid=None, cond=[], amount=0, in_kind=False),
    dict(id="S10", name="公众号文末打赏累计 ¥3,000", stage="S0",
         public=True, consid=None, cond=[], amount=3000, in_kind=False),
    dict(id="S11", name="企业 ¥18,000，要求独家冠名", stage="S0",
         public=False, consid=None, cond=["排他"], amount=18000, in_kind=False),
    dict(id="S12", name="匿名赞助 ¥18,390（超新上限 15,325）", stage="S0",
         public=False, consid=None, cond=[], amount=18390, in_kind=False),
]


# ------------------------------------------------ 问题一：应否（法律 + 定位）
def should(s):
    """返回 (结论, 原因)。结论 ∈ {True, "cap", False}"""
    if s["public"] and s["stage"] != "S1":
        return False, "面向不特定公众且无资格 → 慈善法禁止"
    c = s["consid"]
    if c in EXCLUSIVE:
        return False, f"对价为「{c}」→ 排他性回报（R10），且不在 0.1.4 收入白名单"
    if c == "开发交付":
        return "invoice", "服务采购款：白名单内，但须开票"
    if s["cond"]:
        return False, f"附条件：{'、'.join(s['cond'])} → R12 直接拒收"
    if s["amount"] > CAP:
        return "cap", f"{s['amount']:,} > 上限 {CAP:,}（{s['amount']/BASE:.1%}）"
    return True, f"非交换、无条件、{s['amount']:,} ≤ {CAP:,}"


# ------------------------------------------------ 问题二：能否（落点）
def can_now(s):
    """返回 (结论, 原因)。S0 无账户 → 一切款项不可收，实物与人力除外。"""
    if s["stage"] == "S0":
        if s["in_kind"]:
            return True, "实物/人力：无需账户，S0 可收"
        return False, "S0 无主体无账户 → 任何款项只能拒收并记录（W5-03 §3）"
    if s["stage"] == "S1":
        return True, "托管方代收代管"
    return True, "S2 自有账户"


def verdict(s):
    sh, r_sh = should(s)
    cn, r_cn = can_now(s)
    if sh is False:
        kind = "资格" if s["public"] else ("性质" if s["consid"] else "条件")
        return f"拒收（{kind}）", "书面拒收 + 公开记录（W5-03 §3 格式）", (sh, cn), (r_sh, r_cn)
    if not cn:
        if sh == "cap":
            return "待落点（须限额）", f"记入待落点清单；S1 后只收 {CAP:,}", (sh, cn), (r_sh, r_cn)
        return "待落点", "记入待落点清单，S1 后按条款收", (sh, cn), (r_sh, r_cn)
    if sh == "invoice":
        return "可收（须开票）", "由托管方开票", (sh, cn), (r_sh, r_cn)
    if sh == "cap":
        return "限额后可收", f"只收 {CAP:,}，超出拒收或转捐", (sh, cn), (r_sh, r_cn)
    return "可收", "按边界入账", (sh, cn), (r_sh, r_cn)


def sym(v):
    if v is True:
        return "✓"
    if v is False:
        return "✗"
    return "△"


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def main():
    verbose = "-v" in sys.argv

    sec("§1 两个问题，不能合成一个")
    print("问题一 应否：性质与条件允不允许收？  法律（H2）+ 定位（R10/R12），与阶段无关")
    print("问题二 能否：现在有没有合法落点？    主体 + 账户，与钱无关")
    print()
    print(f"上限 CAP = {CAP:,}（= 25% × {BASE:,}）")
    print("✓ 通过   ✗ 不过   △ 有条件（须开票 / 须限额）")

    sec("§2 逐场景判定")
    print(f"{'编号':4}{'场景':40}{'阶段':5}{'应否':5}{'能否':5}{'结论':16}")
    results = []
    for s in SCENARIOS:
        v, act, marks, reasons = verdict(s)
        results.append((s, v, act, marks, reasons))
        print(f"{s['id']:4}{s['name'][:38]:40}{s['stage']:5}"
              f"{sym(marks[0]):5}{sym(marks[1]):5}{v:16}")

    sec("§3 两个问题的分布")
    from collections import Counter
    c = Counter(v for _, v, _, _, _ in results)
    total = len(results)
    for k in ["可收", "可收（须开票）", "限额后可收", "待落点", "待落点（须限额）", "拒收（资格）", "拒收（性质）", "拒收（条件）"]:
        if c.get(k):
            print(f"  {k:16}{c[k]:2} 个")
    print(f"  {'合计':16}{total:2} 个")
    print()
    allow = sum(1 for s in SCENARIOS if should(s)[0] is True or should(s)[0] in ("cap", "invoice"))
    now_ok = sum(1 for s in SCENARIOS if can_now(s)[0])
    print(f"  问题一「应否」允许的：{allow} 笔")
    print(f"  问题二「能否」现在能接住的：{now_ok} 笔")
    print()
    print(f"  中间那 {allow - now_ok} 笔是本周最该被看见的部分：**应该收，但现在收不了。**")
    print("  它们的共同原因不是钱的性质，是 S0 没有账户——")
    print("  而解决这件事不在 C1–C4 四件任务里，在 C1 的 T1 触发条件上。")

    sec("§4 对照：如果只看金额")
    def bucket(v):
        return "收" if v.startswith(("可收", "限额")) else "不收"
    wrong = []
    for s, v, act, marks, reasons in results:
        naive = "收" if s["amount"] <= CAP else "不收"
        if naive != bucket(v):
            wrong.append((s, v, naive))
    print(f"  判错 {len(wrong)}/{total}（{len(wrong)/total:.0%}）")
    for s, v, naive in wrong:
        print(f"    {s['id']} {s['name'][:34]:36} 只看金额→{naive:2} 实际→{v}")
    print()
    print("  只看金额错在两个方向：")
    print("  ① 金额小的都放行 —— S02/S10 是公开募捐（金额 0 与 3,000，最该拦的两笔）")
    print("  ② 金额大的都拒收 —— S06 只是超限，限额后可以收，不是不能收")
    print("  金额是四个判据里最不重要的一个：它只决定'收多少'，不决定'收不收'。")

    sec("§5 三个最容易被答错的场景")
    for s, v, act, marks, reasons in results:
        if s["id"] not in ("S03", "S06", "S10"):
            continue
        print(f"\n{s['id']} {s['name']}")
        print(f"  应否 {sym(marks[0])} {reasons[0]}")
        print(f"  能否 {sym(marks[1])} {reasons[1]}")
        print(f"  结论：{v} → {act}")
    print()
    print("S03「4.5 万不算多，收下不花就行」：挂 logo 使它对价化（是广告，不是资助），金额又超限 2.4 倍。")
    print("S06「算力不是钱，不用计入」：实物按市价折算 27.2%，超限——不收钱的项目一样可以被一家公司养起来。")
    print("S10「打赏是读者自愿，不算募捐」：判据是'面向不特定公众'，不是'是否强制'。文末打赏面向所有人。")

    sec("§6 汇总")
    print(f"12 个场景：可收 {c.get('可收', 0)}、须开票 {c.get('可收（须开票）', 0)}、"
          f"限额 {c.get('限额后可收', 0)}、待落点 {c.get('待落点', 0) + c.get('待落点（须限额）', 0)}、"
          f"拒收 {sum(v for k, v in c.items() if k.startswith('拒收'))}")
    print(f"应否允许 {allow} 笔，现在能接住 {now_ok} 笔，差 {allow - now_ok} 笔卡在'没有账户'。")
    print(f"以金额为唯一判据，{len(wrong)}/12 判错（{len(wrong)/total:.0%}）。")
    print()
    print("把「应否」与「能否」分开之后，08 那处矛盾自己消失了：")
    print("  §3 的「S0 不得收款」讲的是能否（没有落点）——对的；")
    print("  §3.1.1 的「S0 能收企业赞助」讲的是应否（性质允许）——也对。")
    print("  错的是把它们写进同一张表的同一列，让读者以为两者是同一件事。")


if __name__ == "__main__":
    main()
