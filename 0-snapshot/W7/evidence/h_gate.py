# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 数字丐帮 2.0 贡献者
"""W7 合规门（G6′）的三道算术：状态、周转、预算

为什么要有这个脚本：
    G6′ 的判定标准只有两条：律师初审意见回执在手 / H1–H5 文本闭环。
    第一条要外部人签字，第二条自己能做完。所以判定当时注定只能满足一半——
    这个结论不需要脚本。脚本要算的是**另一半为什么在当时不可能满足**：

        §1 H1–H5 的十格状态（5 项 × 文本/外部）
        §2 排期算术：送审日与判定日之间还剩几个工作日、够不够律师周转
        §3 预算与页数：¥3,000–5,000 买得到"通读"，买不到"逐条意见"

    这三件事都能用日历和字数算出来，不需要判断。算出来之后，
    "G6′ 未通过"就不再是执行不力，而是**排期本身写错了**——
    这两种失败必须分开，因为处置完全不同：前者要加人，后者要改日期。

两套基线，同一个脚本：
    v2.1  判定当时用的排期（送审 12-20、判定 12-20、W8-R1 12-21）——W7-05 引用的输出由它复现；
    v2.4  重排后的排期（送审 11-13、G6′-b 判定 12-27、M2 起 11-16）。
    门的判定不重跑（v2.4 明文：不把"有条件"转"通过"），但算术必须跟着日历走，
    否则脚本会一直印一个已经被撤掉的结论。

用法：
    python h_gate.py                    # v2.4（默认）
    python h_gate.py --baseline v2.1    # 复现 11-07 的取证输出
"""

from __future__ import annotations

import os
import re
from argparse import ArgumentParser
from datetime import date, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def find_material(rel):
    """精确定位材料；精确路径不存在时，在同目录按编号做唯一匹配。

    资料库导出件的文件名带标题前缀（"数字丐帮2.0·W7-02 …"），
    与仓库内短名不一致。v2.1 之前此处的后果是：路径全部落空、静默 0 页、
    仍然照常打印判定结论。现在改为可定位则用、不可定位则明确报缺料。
    """
    path = os.path.join(ROOT, rel)
    if os.path.exists(path):
        return path
    folder, base = os.path.split(rel)
    d = os.path.join(ROOT, folder) if folder else ROOT
    if not os.path.isdir(d):
        return None
    stem = os.path.splitext(base)[0]
    m = re.search(r"(W\d-\d\d|\d{2}|[a-z]\d+_[a-z]+)", stem)
    if not m:
        return None
    key = m.group(1).upper()
    cands = [f for f in os.listdir(d) if f.lower().endswith(".md") and key in f.upper()]
    return os.path.join(d, cands[0]) if len(cands) == 1 else None

# H1–H5：文本落点（已闭环）与外部动作（未发生）
H_ITEMS = [
    ("H1", "名称与商标在先权益", "01 §0.4 / 07 §5.1 / 06 §4.4", "第 9/35/41/42/45 类检索（L4 未发出）"),
    ("H2", "公开募捐资格", "08 §3.1.1 / 05 §3.1 / 09 §1.3.7", "托管协议书面化与备案（无托管方）"),
    ("H3", "资产锁定三载体", "06 §5.5 / §5.4 / 章程 14 条", "三份文件归档（无主体可签）"),
    ("H4", "永不收费的效力边界", "09 §0.1.7 / §0.1.8 / 06 §4.5", "承接文件签署（须 S1/S2）"),
    ("H5", "双层关联交易", "06 §7.3 / 章程第 14 条", "台账与审计落地（S2 主体设立后）"),
]

# 送审材料（本仓库实有部分；三件套原文另计）
MATERIALS = [
    ("w7/数字丐帮2.0·W7-02 协议三件套修订包 v2.1（C2）.md", "协议修订包 v2.1"),
    ("w7/数字丐帮2.0·W7-01 实体与责任路径 v2.1（C1）.md", "实体路径 v2.1"),
    ("w7/数字丐帮2.0·W7-03 红线 R9–R12 落地与可判定化（C3）.md", "红线要件化 v1.0"),
    ("_src/06_g1.md", "治理与资产锁定 2.0"),
    ("_src/p1_criteria.md", "判据与红线 04"),
    ("_src/w1_12.md", "12 号复核意见"),
    ("w6/数字丐帮2.0·W6-01 许可矩阵（L1）.md", "许可矩阵"),
    ("w5/数字丐帮2.0·W5-04 章程要点 14 条（可交律师版）.md", "章程 14 条"),
]

BASELINES = {
    "v2.1": {
        "label": "v2.1（2026-11-07 判定当时）",
        "source": "02 v2.1 §5–§6",
        "c4_end": date(2026, 12, 20),      # 送审材料定稿发出
        "gate": date(2026, 12, 20),        # G6′ 判定日
        "next_start": date(2026, 12, 21),  # W8-R1 开工
        "next_label": "W8-R1（开源发布）",
    },
    "v2.4": {
        "label": "v2.4（2026-11-08 重排后）",
        "source": "02 v2.4 §1 / W8 并行推进方案",
        "c4_end": date(2026, 11, 13),      # M1 出口：送审发出
        "gate": date(2026, 12, 27),        # G6′-b 判定日
        "next_start": date(2026, 11, 16),  # M2 开工
        "next_label": "M2 发布（R1 收尾与投放）",
    },
}
DEFAULT_BASELINE = "v2.4"

TURNAROUND = (5, 10)            # 律师书面意见常规周转（工作日）
BUDGET = (3000, 5000)           # 律师咨询现金预算
RATE = (500, 800)               # 律师小时费率区间（元/小时）
CHARS_PER_PAGE = 700            # 中文一页约 700 字（含表格折损）
PAGES_PER_HOUR = (10, 20)       # 法律审阅速度：10（细读）–20（通读）页/小时


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def workdays(d, n):
    """从 d 起算 n 个工作日后（不含当天，跳过周六日）。"""
    cur, added = d, 0
    while added < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            added += 1
    return cur


def count_workdays(a, b):
    """a 到 b 之间的工作日数（不含 a、含 b）；b 早于 a 时返回负数。"""
    if b == a:
        return 0
    step = 1 if b > a else -1
    cur, n = a, 0
    while cur != b:
        cur += timedelta(days=step)
        if cur.weekday() < 5:
            n += step
    return n


def part1():
    sec("§1 H1–H5 十格状态")
    print(f"{'编号':5}{'发现':22}{'文本落点':32}{'外部动作'}")
    txt = ext = 0
    for code, name, where, external in H_ITEMS:
        txt += 1                       # 文本已闭环（W1-12 §0 与 W5/W6 均已核）
        print(f"{code:5}{name:22}{where:32}{external}")
    total = len(H_ITEMS) * 2
    print(f"  文本 5/5、外部 0/5 → 合计 {txt}/{total}")
    print()
    print("  十格里空了五格，空的全是'需要另一个主体签字'的动作：")
    print("  检索报告要有代理机构出、托管协议要有托管方签、承接文件要有承接人签。")
    print("  而这三件事的共同前提是：**得先有一个能被签字的主体**——即 C1 的 S1。")
    print()
    print("  这是连续第三周出现同一个形状：")
    print("    G4′（W5）：制度能约束自己 → 判的是文本，通过（范围限定）")
    print("    G5′（W6）：别人能合法复用 → 卡在检索委托未发出")
    print("    G6′（W7）：能合法接受资助 → 卡在律师回执未取得")
    print("  三道门都过了文本，都卡在签字。签字这件事不解决，后面的门只能一路带着")
    print("  '有条件'往下走——直到把'能否开工'与'能否宣称'拆成两条轨，见 §2 末。")


def part2(bl):
    sec("§2 排期算术：" + bl["label"])
    c4_end, gate, next_start = bl["c4_end"], bl["gate"], bl["next_start"]

    gap_days = (gate - c4_end).days
    gap_wd = count_workdays(c4_end, gate)
    print(f"  送审发出日       {c4_end}（{'一二三四五六日'[c4_end.weekday()]}）")
    print(f"  G6′ 判定日       {gate}（{'一二三四五六日'[gate.weekday()]}）")
    print(f"  两者间隔         {gap_days} 个日历日 = {gap_wd} 个工作日   〔{bl['source']}〕")
    print()
    print(f"  律师书面意见的常规周转：{TURNAROUND[0]}–{TURNAROUND[1]} 个工作日")
    e5 = workdays(c4_end, TURNAROUND[0])
    e10 = workdays(c4_end, TURNAROUND[1])
    print(f"  最早可能拿到回执：{e5}（+5 工作日）～ {e10}（+10 工作日）")
    print()

    # 送审日若落在周末，律师最早次一工作日才看到材料
    e5b = e5
    if c4_end.weekday() >= 5:
        e5b = workdays(c4_end + timedelta(days=1), TURNAROUND[0])
        print(f"  送审日是周{'六日'[c4_end.weekday() - 5]}，律师最早次一工作日才看到材料：")
        print(f"  按'次一工作日送出'算，最早回执 = {e5b}。")
        print()

    margin = (gate - e5b).days
    if margin < 0:
        over = -margin
        print(f"  → **倒挂**：最早回执日 {e5b} 晚于判定日 {gate}，差 {over} 天。")
        print("    G6′ 若严格按日期判，在送审材料定稿的那一刻就已经不可能通过——")
        print("    不是执行不力，是排期要求'当天送审、当天回执'。")
        print()
        lag = (next_start - e5b).days
        print("  连带的问题比这更麻烦：")
        print(f"    {bl['next_label']} 起于 {next_start}，早于最早回执日 {e5b} {abs(lag)} 天"
              f"（这就是 W7-05 记的'倒挂 {abs(lag)} 天'）。")
        print("    而 R1 的前置写明是 G6′。**门禁日期晚于被门禁任务的开工日**，")
        print("    这是排期倒挂：要么 R1 无门开工，要么 R1 顺延，两条都跟表不一样。")
        print()
        print("  两种处置，代价不同：")
        print(f"    A 改 G6′ 日期：把判定日移到 {e5b} 之后，R1 顺延 → 压缩或整体后移")
        print("    B 拆 G6′：文本闭环部分（H1–H5 文本 5/5）先判，回执部分单列为 G6′-b，后判")
        print("  推荐 B：它承认了一个事实——**文本能不能闭环由我们决定，回执什么时候到不由我们决定。**")
        print("  把两件控制权不同的事放进同一道门，这道门就永远只能在'有条件'和'不通过'之间摇摆。")
    else:
        print(f"  → 不倒挂：最早回执 {e5b}，判定日 {gate}，余量 {margin} 天"
              f"（{count_workdays(e5b, gate)} 个工作日）。")
        print("    这一格是拆门之后才成立的：送审从 12-20 提到 11-13，判定留在 12-27，")
        print("    中间 44 天足够跑完 5–10 个工作日的周转，还留出追件与补件的时间。")
        print()
        lag = (e5b - next_start).days
        if lag > 0:
            print("  但 M2 不等回执：")
            print(f"    {bl['next_label']} 起于 {next_start}，比最早回执日 {e5b} 早 {lag} 天。")
            print("    这不是倒挂，是**刻意并行**——M2 做的是技术发布（仓库公开、示例、索引页），")
            print("    不需要律师签字；需要签字的是'宣称合规'那一步。")
            print("    所以门拆成两半，判定也拆成两格：")
            print("      G6′-a 文本闭环（H1–H5 文本 5/5）        → 2026-11-07 已判：通过")
            print("      G6′-b 律师回执（外部动作 0/5 → ≥1）      → 2026-12-27 判")
            print("    G6′-b 到期未回只改这一格，不冻结 M2–M6。")
            print()
            print("  一句话：v2.1 的错不在'算错了天数'，在'把送审排在了收口那一周'。")


def part3():
    sec("§3 预算与页数：买得到通读，买不到逐条")
    total_chars = 0
    print(f"{'文件':46}{'字数':>8}")
    for rel, label in MATERIALS:
        path = find_material(rel)
        if not path:
            print(f"{label:46}{'缺失':>8}")
            continue
        n = len(open(path, encoding="utf-8").read())
        total_chars += n
        print(f"{label:46}{n:>8,}")
    pages = total_chars / CHARS_PER_PAGE
    print(f"{'合计（不含三件套原文）':46}{total_chars:>8,}")
    print(f"{'折合页数（700 字/页）':46}{pages:>8.0f} 页")
    print()
    lo_h, hi_h = pages / PAGES_PER_HOUR[1], pages / PAGES_PER_HOUR[0]
    print(f"  法律审阅速度 {PAGES_PER_HOUR[0]}–{PAGES_PER_HOUR[1]} 页/小时 → 通读需 {lo_h:.1f}–{hi_h:.1f} 小时")
    print(f"  书面意见通常按通读的 1.5–2 倍计 → 需 {lo_h*1.5:.1f}–{hi_h*2:.1f} 小时")
    print()
    aff_lo, aff_hi = BUDGET[0] / RATE[1], BUDGET[1] / RATE[0]
    print(f"  预算 {BUDGET[0]:,}–{BUDGET[1]:,} 元 ÷ 费率 {RATE[0]}–{RATE[1]} 元/小时 = 可买 {aff_lo:.1f}–{aff_hi:.1f} 小时")
    print()
    if aff_lo < lo_h:
        print(f"  {BUDGET[0]:,} 元档（{aff_lo:.1f}h）连通读都不够（需 {lo_h:.1f}h）——差 {lo_h-aff_lo:.1f}h。")
    print(f"  {BUDGET[1]:,} 元档（{aff_hi:.1f}h）够通读，不够逐条（需 {hi_h*2:.1f}h）。")
    print()
    print("  所以 G6′ 能拿到的回执，形态大概率是**风险提示函**，不是逐条法律意见：")
    print("  律师会把最明显的三五个问题指出来，不会对 27 条正文逐一表态。")
    print("  这必须在判定里说清楚——否则下一周会把'风险提示'当成'合规通过'，")
    print("  而两者的差别是：前者说'这里可能有问题'，后者说'这里没有问题'。")
    print()
    print("  买到逐条（{:.1f}h）需 ¥{:,.0f}–{:,.0f}，是单次预算上限的 {:.1f}–{:.1f} 倍。".format(
        hi_h * 2, hi_h * 2 * RATE[0], hi_h * 2 * RATE[1], hi_h * 2 * RATE[0] / BUDGET[1], hi_h * 2 * RATE[1] / BUDGET[1]))


def total_pages():
    total = 0
    for rel, _ in MATERIALS:
        p = find_material(rel)
        if p:
            total += len(open(p, encoding="utf-8").read())
    return total / CHARS_PER_PAGE


def main():
    ap = ArgumentParser(description="W7 合规门（G6′）算术")
    ap.add_argument("--baseline", choices=sorted(BASELINES), default=DEFAULT_BASELINE,
                    help=f"排期基线，默认 {DEFAULT_BASELINE}")
    ap.add_argument("--root", default=None,
                    help="材料根目录（应含 w7/ w6/ w5/ _src/）；默认脚本上两级")
    args = ap.parse_args()

    global ROOT
    if args.root:
        ROOT = os.path.abspath(args.root)
    miss = [(rel, label) for rel, label in MATERIALS if not find_material(rel)]
    if miss:
        print("材料不全，判定不成立：")
        for rel, label in miss:
            print(f"  · {label}（{rel}）")
        print(f"  {len(miss)}/{len(MATERIALS)} 份缺失。用 --root 指向含 w7/ w6/ w5/ _src/ 的目录后重跑。")
        print("  缺料时不再输出页数与判定结论——0 页不是'材料很短'，是'没读到'。")
        return 1

    bl = BASELINES[args.baseline]

    part1()
    part2(bl)
    part3()

    sec("§4 汇总")
    print("  H1–H5：文本 5/5、外部 0/5 → 10 格中 5 格")
    print("  G6′ 两条标准：1/2（文本闭环满足，回执未取得）")
    if args.baseline == "v2.1":
        print("  判定：未通过")
        print("  原因不是执行：周转 0 工作日、送审日还是周日；且回执最早 12-28，晚于 W8-R1 开工 7 天（排期倒挂）")
    else:
        print("  判定：G6′-a 通过（2026-11-07）；G6′-b 待判（2026-12-27）")
        print("  v2.1 的倒挂已消除：送审 11-13 → 最早回执 11-20，判定 12-27，余量 37 天")
        print("  真正的约束变成了外部等待：回执不到不影响 M2–M6 开工，只影响'能否宣称合规'")
    print(f"  预算 3,000–5,000 元只够通读 {total_pages():.0f} 页材料（不含三件套原文），意见形态只能是风险提示函")
    print()
    if args.baseline == "v2.1":
        print("  于是当时的真实产出不是'过了合规门'，是**把合规门拆成了两半**：")
        print("  能自己决定的那半（文本、要件、判定规则）做完了；")
        print("  要别人签字的那半（检索、律师、托管）一件也没发生——且这已经不是第一次。")
    else:
        print("  拆门之后的判定只有一个数需要盯：外部动作从 0/5 走到 1/5。")
        print("  那一天起，G6′-b 才有判'通过'的材料；在那之前，对外只能写'待法律复核'。")


if __name__ == "__main__":
    import sys
    sys.exit(main())
