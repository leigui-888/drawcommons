# -*- coding: utf-8 -*-
"""W7 红线 R9–R12 可判定化检查器

为什么要有这个脚本：
    04 §4 的四条红线（R9 资金隔离 / R10 禁圈地 / R11 禁数据商用 / R12 禁附条件资助）
    每条都有"触发信号"和"失败动作"，读起来很清楚。
    但"读起来清楚"和"能判定"是两件事：W5 已经吃过一次亏——
    06 的章程 14 条，可判定性 0/14，因为每一条都能被两种方式读懂。

    本脚本把每条红线拆成"要件"（3–5 个），每个要件用一个正则表达它在文本里长什么样。
    要件全在 = 这条红线在这份文件里可判定；缺一个 = 这条红线在这份文件里是空的。

    用法：
        python redline_lint.py <文件>          # 检查 17 个要件
        python redline_lint.py <文件> -v       # 列出每个要件的命中证据

    注意：这是**文本可判定性**检查，不是"是否遵守"检查。
    一份文件 17/17，只说明它把该说的都说清了，不说明它做到了。
"""

import re
import sys

# 每条红线：要件 = (编号, 名称, 正则, 说明)
REDLINES = [
    ("R9", "资金隔离", [
        ("R9-1", "条款存在", r"资金隔离|不得混同|不得与.{0,6}混同",
         "必须有一句把'隔离'写成义务，而不是原则"),
        ("R9-2", "隔离对象", r"成员[^。\n]{0,12}(交易|资金)|成员间交易",
         "隔离的是哪一笔钱，必须点名"),
        ("R9-3", "分账与审计", r"两套账|单独核算|分别审计|单列",
         "混同的判定靠账，不靠承诺"),
        ("R9-4", "失败动作", r"账户结构重建|逐笔还原|混同[^。\n]{0,12}还原",
         # 首版写作 "重建|逐笔还原|追溯"，把 09 的"追溯性奖励"判成命中——
         # 检查工具假阳性比漏报更危险，收紧到只能匹配"处置混同"的动宾结构

         "已经混同了怎么办，必须写"),
    ]),
    ("R10", "禁止圈地", [
        ("R10-1", "条款存在", r"禁止圈地|不得[^。\n]{0,10}排他|不可圈地",
         "'不圈地'要成为一条禁令，不是一种气质"),
        ("R10-2", "付费优先/排名/认证收费", r"优先接入|排名加权|付费认证|认证收费",
         "圈地最常见的三种形态，必须点名禁止"),
        ("R10-3", "私有方言", r"私有方言|必需[^。\n]{0,8}扩展|x- ?扩展",
         "在标准上加必需字段，是圈地的技术形态"),
        ("R10-4", "失败动作", r"直接否决|不走表决|援引",
         "违反 R10 不走表决——这是它与 R1–R8 的区别"),
    ]),
    ("R11", "禁止数据商用", [
        ("R11-1", "条款存在", r"不[^。\n]{0,6}(出售|商用)|不得[^。\n]{0,6}商用",
         "数据不商用要写成禁令"),
        ("R11-2", "模型训练", r"模型训练|训练[^。\n]{0,6}数据",
         "2026 年最容易被绕开的一条，必须单列"),
        ("R11-3", "第三方与脱敏", r"脱敏|第三方",
         "'脱敏后提供'是绕开限制的常用通道"),
        ("R11-4", "失败动作", r"立即停止|删除已流出|公告",
         "数据一旦流出，动作必须是删除与公告，不是整改"),
    ]),
    ("R12", "禁止附条件资助", [
        ("R12-1", "条款存在", r"附条件资助|附带[^。\n]{0,10}(治理权|排他权)",
         "'附条件'本身要成为被拒的对象"),
        ("R12-2", "四类权利列举", r"治理权|排他权|数据访问权|路线图",
         "四类权利必须逐个列出，否则'条件'可被解释得很窄"),
        ("R12-3", "25% 数值", r"25\s*%|百分之二十五",
         "只有原则没有数值，等于没有上限"),
        ("R12-4", "分母定义", r"审计[^。\n]{0,10}成本|运营成本[^。\n]{0,6}1\.2|73,?560|61,?300",
         "**数值没有分母就不是上限**——W5 实测：同一笔钱 22.5% 与 73.4%"),
        ("R12-5", "失败动作", r"拒收|搁置账户|当年度不得使用",
         "S0/S1 只能拒收（无账户可搁置），S2 起可搁置"),
    ]),
]

NEG = ("不", "禁", "无", "永不", "不得", "未", "拒")

# 语义冲突规则（v1.1 新增，P1-13）：
# 要件靠正则"存在"就判通过，会产生假阳性——文本一边写"禁止商用"，
# 一边在许可条款里写"任何人可依该许可商用"。后者是许可授予的权利，
# 一旦授予就收不回，前者只能约束平台自身。两者同时出现且 R11 未限定主语，
# 就是语义冲突，必须转人工，不得由脚本判通过。
PERMISSIVE_USE = r"可依该许可商用|任何人可.{0,8}商用|允许商用|可商用|得商用"
SELF_LIMITED = (
    r"(?:平台|本平台|本组织|项目方|运营方)[^\n]{0,12}自身[^\n]{0,48}(?:不|不得|不会)[^\n]{0,48}"
    r"(?:商用|出售|出租|交换|训练)"
    r"|(?:平台|本平台|本组织|项目方|运营方)[^\n]{0,24}(?:不|不得|不会)[^\n]{0,24}(?:商用|出售|出租|交换|训练)"
)


def _paragraphs(text):
    """把 markdown 切成段落；引用块内的每一行各算一段（否则整块共用一个主语）。"""
    out = []
    for block in re.split(r"\n\s*\n", text):
        plain = []
        for line in block.split("\n"):
            s = line.strip()
            if s.startswith(">"):
                s = s.lstrip(">").strip()
                if s:
                    out.append(s)
            else:
                plain.append(s)
        if any(plain):
            out.append("\n".join(plain))
    return out


def semantic_conflicts(text):
    """按段判定：禁令段是否把主语限定为平台自身。

    全文级匹配太粗——只要文档里任意一处写了"平台自身不商用"，就豁免了全部授权表述。
    改为逐段检查：凡出现"不得…出售/商用"的段落，若该段没有主语限定，
    而全文又有"可依该许可商用"一类授权，即判语义冲突。
    """
    out = []
    if not re.search(PERMISSIVE_USE, text):
        return out
    ban = re.compile(r"(?:不得|禁止|不会|不)[^\n]{0,24}(?:出售|商用|出租|交换)")
    for para in _paragraphs(text):
        # 只看讲数据/账本的段落：排除资金隔离、表格、修订清单一类误命中
        if para.lstrip().startswith("|"):
            continue
        if not re.search(r"数据|账本", para):
            continue
        if ban.search(para) and not re.search(SELF_LIMITED, para):
            out.append(("R11",
                        "同文出现「可依该许可商用」一类授权表述，而本段禁令未把主语限定为平台自身；"
                        "许可授予的权利无法被下游政策收回 → 要件存在，结论不成立，转人工"))
            break
    return out


def load(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def check(text):
    out = []
    for rid, name, reqs in REDLINES:
        rows = []
        for code, rname, pat, why in reqs:
            m = re.search(pat, text)
            rows.append((code, rname, bool(m), m.group(0) if m else "", why))
        out.append((rid, name, rows))
    return out


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def main():
    if len(sys.argv) < 2:
        print("用法：python redline_lint.py <文件> [-v]")
        return 2
    path = sys.argv[1]
    verbose = "-v" in sys.argv
    text = load(path)

    sec(f"§1 要件清单（{sum(len(r[2]) for r in REDLINES)} 个）")
    for rid, name, reqs in REDLINES:
        print(f"  {rid} {name}（{len(reqs)} 个要件）")
        for code, rname, _, why in reqs:
            print(f"    {code:6}{rname:20}{why}")

    res = check(text)
    conf = semantic_conflicts(text)
    conf_rid = {c[0] for c in conf}
    sec(f"§2 扫描结果：{path}")
    total = hit = 0
    for rid, name, rows in res:
        ok = sum(1 for _, _, h, _, _ in rows if h)
        total += len(rows)
        hit += ok
        mark = "　⚠️ 语义冲突，转人工" if rid in conf_rid else ""
        print(f"\n  {rid} {name}：要件存在 {ok}/{len(rows)}{mark}")
        for code, rname, h, ev, why in rows:
            mark = "✅" if h else "❌"
            print(f"    {mark} {code:6}{rname:20}" + (f"命中「{ev[:28]}」" if h and verbose else ""))
            if not h:
                print(f"       缺：{why}")

    sec("§3 判定")
    print(f"  要件存在 {hit}/{total}　（存在 ≠ 成立：只说明文本里写了这句话）")
    full = [rid for rid, name, rows in res if all(h for _, _, h, _, _ in rows)]
    part = [rid for rid, name, rows in res if any(h for _, _, h, _, _ in rows)
            and not all(h for _, _, h, _, _ in rows)]
    empty = [rid for rid, name, rows in res if not any(h for _, _, h, _, _ in rows)]
    valid = [rid for rid in full if rid not in conf_rid]
    print(f"  要件成立且无冲突 {len(valid)}/4 条：{'、'.join(valid) if valid else '无'}")
    print(f"  要件存在但语义冲突 {len(conf_rid)}/4 条：{'、'.join(sorted(conf_rid)) if conf_rid else '无'}")
    print(f"  部分存在 {len(part)}/4 条：{'、'.join(part) if part else '无'}")
    print(f"  完全空缺 {len(empty)}/4 条：{'、'.join(empty) if empty else '无'}")
    for rid, msg in conf:
        print(f"  ⚠️ {rid}：{msg}")
    print()
    if len(valid) < 4:
        if len(full) == 4:
            print("  四个要件都在，但存在语义冲突：脚本不判通过，须人工复核（区分'写了'与'成立'）。")
            print("  这类冲突不能靠改写措辞消掉——要么限定 R11 的主语为平台自身，要么更换许可。")
        else:
            print("  缺口不是'措辞不够严'，是**这条红线在这份文件里不存在**。")
        print("  一份没有 R12 数值的协议，对外承诺'不接受附条件资助'，")
        print("  实际执行时唯一的判据是签字人的判断——这就是 W5 说的'要判断的只是协议'。")
    else:
        print("  四条红线全部可判定：每个要件都能被第三方按字面复核，不需要问作者。")

    return 0 if len(valid) == 4 else 1


if __name__ == "__main__":
    sys.exit(main())
