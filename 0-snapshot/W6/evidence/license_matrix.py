#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""许可矩阵：六类对象 × 九种候选许可，按四条硬约束打分。

为什么需要脚本：白皮书 §8.1 已经"定选型"，但定选型不等于定得住。
只要换一个对象、换一个候选许可，结论就会翻转——这种翻转必须能被别人重算，
否则矩阵只是一张喜好表。

四条硬约束（对每一类对象，"必须满足"的子集不同，见 OBJECTS[].hard）：
  C1 允许商用
  C2 允许改作（衍生作品）
  C3 无同类共享义务（无 SA / ODbL 传染）
  C4 无署名义务
  C5 含明示专利授权

输出：
  §1 完整打分矩阵（6 × 9）
  §2 每类对象的可行许可与不可行原因
  §3 单许可统一方案能覆盖几类（回答"能不能只放一个 LICENSE"）
  §4 AGPL 专项：它在五类对象上的净效果
"""

from __future__ import annotations

CRIT = ["C1 商用", "C2 改作", "C3 无传染", "C4 无署名", "C5 专利"]

# 候选许可及其五条属性。True = 满足
LICENSES = {
    "Apache-2.0":   dict(C1=1, C2=1, C3=1, C4=0, C5=1),   # §4 要求保留声明与 NOTICE
    "MIT":          dict(C1=1, C2=1, C3=1, C4=0, C5=0),   # 须保留版权声明；无明示专利授权
    "AGPL-3.0":     dict(C1=1, C2=1, C3=0, C4=1, C5=1),
    "GPL-3.0":      dict(C1=1, C2=1, C3=0, C4=1, C5=1),
    "CC0-1.0":      dict(C1=1, C2=1, C3=1, C4=1, C5=0),   # 明确不许可专利与商标
    "CC-BY-4.0":    dict(C1=1, C2=1, C3=1, C4=0, C5=0),
    "CC-BY-SA-4.0": dict(C1=1, C2=1, C3=0, C4=0, C5=0),
    "CC-BY-NC-4.0": dict(C1=0, C2=1, C3=1, C4=0, C5=0),
    "ODbL-1.0":     dict(C1=1, C2=1, C3=0, C4=0, C5=0),
}

# 六类对象。hard = 该类对象必须满足的约束；chosen = 实际选型
OBJECTS = [
    dict(
        name="代码（参考实现/脚本/部署配置）",
        hard=["C1 商用", "C2 改作", "C3 无传染", "C5 专利"],
        chosen="Apache-2.0",
        why="采纳面优先于控制力；专利授权是给下游企业的合规前提，缺它会被内网政策直接拦掉",
    ),
    dict(
        name="接口规范（OpenAPI/字段表/错误码表）",
        hard=["C1 商用", "C2 改作", "C3 无传染", "C4 无署名", "C5 专利"],
        chosen="CC0-1.0",
        why="规范要成为事实标准必须零摩擦；署名要求会制造'多数使用者都在违约'的状态",
    ),
    dict(
        name="数据（资源清单/统计）",
        hard=["C1 商用", "C2 改作", "C3 无传染"],
        chosen="CC-BY-4.0",
        why="允许转载与再加工，仅需署名；不用 ODbL 以免挡住商业撮合",
    ),
    dict(
        name="文档与白皮书",
        hard=["C1 商用", "C2 改作"],
        chosen="CC-BY-SA-4.0",
        why="文档的风险是'被删改后变成更权威的二手版'，SA 用来防闭源改写",
    ),
    dict(
        name="账本 schema",
        hard=["C1 商用", "C2 改作", "C3 无传染", "C4 无署名", "C5 专利"],
        chosen="CC0-1.0",
        why="同规范：别人要能用同一份 schema 实现同样的账本，否则无法互验",
    ),
    dict(
        name="商标与名称",
        hard=[],          # 许可不适用于名称；名称由商标规则管，不由著作权许可管
        chosen="—",
        why="名称不能用开放许可'放开'，只能用规则收住；见 TRADEMARK.md",
    ),
]


def sec(t):
    print()
    print(t)
    print("-" * len(t))


SHORT = {
    "Apache-2.0": "Apache",
    "MIT": "MIT",
    "AGPL-3.0": "AGPL",
    "GPL-3.0": "GPL",
    "CC0-1.0": "CC0",
    "CC-BY-4.0": "BY",
    "CC-BY-SA-4.0": "BY-SA",
    "CC-BY-NC-4.0": "NC",
    "ODbL-1.0": "ODbL",
}


def k(c: str) -> str:
    """'C1 商用' -> 'C1'"""
    return c.split()[0]


def part1():
    sec("§1 完整打分矩阵：6 类对象 × 9 种候选许可（单元格＝硬约束命中数）")
    print(f"{'对象':30}" + "".join(f"{SHORT[l]:>9}" for l in LICENSES))
    for o in OBJECTS:
        row = f"{o['name'][:28]:30}"
        if not o["hard"]:
            row += "".join(f"{'—':>9}" for _ in LICENSES)
        else:
            nh = len(o["hard"])
            for lic, attrs in LICENSES.items():
                hit = sum(attrs[k(c)] for c in o["hard"])
                mark = "✅" if hit == nh else "❌"
                row += f"{mark + f'{hit}/{nh}':>9}"
        print(row)
    print()
    print("图例：✅ 全部硬约束命中＝可行；❌ 有缺口；— 许可不适用于该类对象。")
    print("商标与名称一行为空：著作权许可不能用来'放开'名称，放开即等于放弃防冒充。")


def part2():
    sec("§2 每类对象的可行许可与剩余缺口")
    for o in OBJECTS:
        if not o["hard"]:
            print(f"\n{o['name']}")
            print("  可行许可：不适用（由商标规则约束，见 TRADEMARK.md §1 三档）")
            continue
        ok = [l for l, a in LICENSES.items() if all(a[k(c)] for c in o["hard"])]
        print(f"\n{o['name']}")
        print(f"  硬约束：{', '.join(o['hard'])}")
        print(f"  可行许可（{len(ok)}/{len(LICENSES)}）：{', '.join(ok) if ok else '无'}")
        print(f"  选型：{o['chosen']}")
        print(f"  理由：{o['why']}")
        attrs = LICENSES.get(o["chosen"], {})
        gap = [c for c in o["hard"] if not attrs.get(k(c))]
        if gap:
            print(f"  ⚠️ 选型未覆盖：{', '.join(gap)} → 须由许可之外的手段补（见 W6-01 §3）")
    gaps = []
    for o in OBJECTS:
        if not o["hard"]:
            continue
        a = LICENSES[o["chosen"]]
        for c in o["hard"]:
            if not a[k(c)]:
                gaps.append((o["name"], c))
    print(f"\n五类对象合计：选型未覆盖硬约束 {len(gaps)} 格")
    for name, c in gaps:
        print(f"  · {name} ／ {c}")
    print()
    print("这 %.0f 格全是同一个维度：专利。CC0 放弃著作权，但明文不许可专利。" % len(gaps))
    print("换许可补不上：Apache-2.0 有专利条款，却带署名与诉讼终止条件，规范用了就不再零摩擦；")
    print("所以规范的『零摩擦 + 专利安全』在标准许可里根本不存在组合——九种候选全部落空（§1 该行 0 个 ✅）。")
    print("现实中的做法都是两件套：CC0/BSD ＋ 单独的专利不主张承诺（W3C、OpenAPI 皆如此）。")
    print("本项目的补丁见 W6-01 §3 的《专利不主张承诺》，它不属于三条手段，是补丁。")


def part3():
    sec("§3 能不能只放一个 LICENSE：单许可统一方案的天花板")
    total = sum(1 for o in OBJECTS if o["hard"])
    rows = []
    for lic, a in LICENSES.items():
        cover = [o["name"] for o in OBJECTS if o["hard"] and all(a[k(c)] for c in o["hard"])]
        rows.append((len(cover), lic, cover))
    rows.sort(key=lambda r: (-r[0], r[1]))
    for n, lic, cover in rows:
        print(f"  {lic:14} 覆盖 {n}/{total} 类" + ("   ← 天花板" if n == rows[0][0] else ""))
    best_n, best_lic, best_cover = rows[0]
    print()
    print(f"单许可天花板：{best_lic} 覆盖 {best_n}/{total}（{best_n/total:.0%}）")
    missing = [o["name"] for o in OBJECTS if o["hard"] and o["name"] not in best_cover]
    print(f"它漏掉的是：{'、'.join(missing)}")
    print(f"分对象方案：{total}/{total}（100%）")
    print()
    print(f"结论：一张 LICENSE 管全部，天花板 {best_n}/{total}（{best_n/total:.0%}），差 {total - best_n} 类。")
    print("差的是规范与账本 schema 两类，而它们缺的不是'更强的许可'，是'许可买不到的零摩擦'：")
    print("Apache-2.0 能覆盖代码的专利，代价是每条实现都要保留声明与 NOTICE——")
    print("对一部 OpenAPI 文件，这意味着每个下游实现都要维护一份归因清单，多数会漏。")
    print("CC0 反过来：零摩擦，但没有专利条款。两者不可兼得，这不是排版的取舍，是条款结构的冲突。")


def part4():
    sec("§4 AGPL 专项：它在五类对象上是净负")
    a = LICENSES["AGPL-3.0"]
    usable, harmful = [], []
    for o in OBJECTS:
        if not o["hard"]:
            continue
        (usable if all(a[k(c)] for c in o["hard"]) else harmful).append(o["name"])
    print(f"  满足硬约束的对象：{len(usable)} 类")
    print(f"  不满足：{len(harmful)} 类 → {'、'.join(harmful)}")
    print()
    print("  对规范类对象，AGPL 的效果不是'更严格'，是'无的放矢'：")
    print("  AGPL 授予的是复制、修改、分发【程序】的权利。别人'按规范写一个新程序'")
    print("  既不是复制该文本，也不是修改该文本——恰恰是著作权本来就不管的行为。")
    print("  于是只有两种结果：")
    print("    ① 实现不被认定为改编 → AGPL 碰不到实现，防不住任何闭源；")
    print("    ② 实现被认定为改编（把规范文本抄进实现仓库即可能）→ 实现被拖入 AGPL，")
    print("       云市场与多数企业内网政策直接排除。")
    print("  没有第三种结果：用在规范上，要么无效，要么有害。")
    print()
    print("  对代码，AGPL 确实能防'云厂商拿去闭源提供'。这是它唯一有效场景，")
    print("  也是本项目的取舍点：防住 1 类闭源，代价是失去 5 类采纳。")
    print("  公共品的成功指标是'被多少系统采纳'，不是'防止被商业使用'，故弃用。")
    print()
    print("  补一句更狠的：R10 禁的是'把公共资产转为可排他'。AGPL 防的是'被闭源'，")
    print("  不是'被排他'——真正的排他路径是商标、私有方言、认证闸门，三条都不经版权。")
    print("  用版权工具防非版权路径，这是选型失败最常见的形式。")


def part5():
    sec("§5 版权许可对四条圈地路径的覆盖：0/4")
    paths = [
        ("① 开放核心（把功能切到闭源版）", "治理条款", "❌ 许可允许改作与商用，切开卖不违约"),
        ("② 私有方言（在标准上加必需扩展）", "许可+公开评审", "❌ 改作自由，加字段不违约"),
        ("③ 认证闸门（付费才能标兼容）", "商标规则", "❌ 商标与认证不由著作权许可管"),
        ("④ 专利主张（对实现收费或起诉）", "专利承诺", "❌ CC0 不许可专利；Apache 只覆盖代码"),
    ]
    print(f"{'圈地路径':30}{'真正的约束工具':14}{'版权许可本身'}")
    for p_, who, verdict in paths:
        print(f"{p_:30}{who:16}{verdict}")
    print()
    print("四条路径，版权许可一条也挡不住（0/4）。这不是许可选错了，是工具用错了：")
    print("许可管的是'复制'，圈地管的是'不复制也能排他'。")
    print()
    print("三条非版权手段的覆盖：")
    means = [
        ("A 规范 CC0 + 变更公开评审", {"②"}, "别人不必用你的文本，就无法用文本造方言；变更须公开评审，方言拿不到规范地位"),
        ("B 商标控制 + 认证规则", {"③"}, "标识只由公共主体发，条件公开、免费、不得拒绝；收费即失去合法性"),
        ("C 治理条款 R10 + 章程", {"①", "②", "④"}, "禁止把公共资产转排他；禁私有方言；专利承诺入章程（W5-04 第二十二条义务承接）"),
    ]
    allp = [p_ for p_, _, _ in paths]
    covered = set()
    for name, toks, why in means:
        hit = [p_ for p_ in allp if any(p_.startswith(t) for t in toks)]
        covered |= set(hit)
        print(f"  {name}")
        print(f"    覆盖：{'、'.join(t.split('（')[0] for t in hit)}")
        print(f"    机制：{why}")
    print()
    full = len(covered)
    missing = [p_.split("（")[0] for p_ in allp if p_ not in covered]
    print(f"三条手段合计覆盖 {full}/4 条路径。")
    print("但第 ④ 条的覆盖只是纸面的：它靠的是治理条款里的一句《专利不主张承诺》，")
    print("而承诺的签署人现在不存在——S0 没有主体，个人签署的承诺不约束未来的法人。")
    print(f"所以有效覆盖 {full - 1}/4；第 ④ 条要等 S2 主体成立并有能力签署时才算数。")
    print("这不是可以含糊过去的一格：专利主张恰恰是最不需要主体、最容易被个人行使的一条。")


def main():
    print("=" * 78)
    print("W6·许可矩阵：六类对象 × 九种候选许可")
    print("=" * 78)
    part1()
    part2()
    part3()
    part4()
    part5()
    print()
    total = sum(1 for o in OBJECTS if o["hard"])
    covered = []
    for lic, a in LICENSES.items():
        n = sum(1 for o in OBJECTS if o["hard"] and all(a[k(c)] for c in o["hard"]))
        covered.append((n, lic))
    covered.sort(reverse=True)
    # v1.1：汇总必须与 §2 的 gap 计数同源，不得打印与自身计算相反的结论
    gap_cells = []
    for o in OBJECTS:
        if not o["hard"]:
            continue
        a = LICENSES[o["chosen"]]
        for c in o["hard"]:
            if not a[k(c)]:
                gap_cells.append((o["name"], c))

    print(f"汇总：全约束可行性——规范/账本 schema 0/9（专利组合不存在）；")
    print(f"      选型 {total}/{total} 类均有结论，其中 {len(gap_cells)} 格硬约束未覆盖（全是专利）"
          f"→ 须以非版权手段补（W6-01 §3）；")
    for name, c in gap_cells:
        print(f"        · {name} ／ {c}")
    print(f"      非版权手段纸面 4/4、有效 3/4；单许可天花板 {covered[0][1]} {covered[0][0]}/{total}；AGPL 1/{total}。")


if __name__ == "__main__":
    main()
