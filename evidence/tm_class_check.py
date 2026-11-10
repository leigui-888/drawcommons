#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""商标检索任务书与备名预检：能在电脑上算的先算完，剩下的才交给人。

为什么先自算：检索委托要花钱、要等回执。委托之前能排掉的候选，就不该花钱去检索。
能排掉的三类：① 文学/作品指涉  ② 与主名音形过近  ③ 含通用词或禁用字
排不掉的一类：在先注册与在先申请 —— 这一条只能由检索回答，本脚本不假装能算。

用法：python tm_class_check.py
退出码：0（本脚本不判"能不能注册"，只出体检结果）
"""

from __future__ import annotations

import sys

# ---- 1. 五个类别的商品/服务项（检索委托的最小范围） ----
CLASSES = {
    "第 9 类": {
        "name": "科学仪器/软件",
        "items": [
            "可下载的计算机程序", "计算机软件（已录制）", "数据处理设备",
            "计算机软件平台", "应用程序接口（API）软件", "可下载的电子出版物",
        ],
    },
    "第 35 类": {
        "name": "广告/商业经营",
        "items": [
            "商业信息", "商业中介服务", "商业数据分析",
            "市场营销咨询", "为买卖双方提供在线市场", "商业调查",
        ],
    },
    "第 41 类": {
        "name": "教育/出版",
        "items": [
            "培训", "组织学术会议", "在线电子出版物（非下载）",
            "出版服务", "教育信息", "组织竞赛（教育或娱乐）",
        ],
    },
    "第 42 类": {
        "name": "技术服务/软件设计",
        "items": [
            "计算机软件设计", "计算机编程", "软件即服务（SaaS）",
            "平台即服务（PaaS）", "计算机技术咨询", "电子数据存储",
        ],
    },
    "第 45 类": {
        "name": "法律/安全/社交",
        "items": [
            "知识产权许可", "知识产权咨询", "版权管理",
            "法律服务", "在线社交网络服务", "安全咨询",
        ],
    },
}

# 主名与备名。`core` 用于拼音距离比较；四字短语无通用前缀可去，故取全名。
MAIN = {"name": "众汲之井", "core": "众汲之井", "label": "主名"}
CANDIDATES = [
    {"name": "器不私属", "label": "备名（送检）", "rationale": "器物不归私人专用——语义贴合公共品，与主名零共用汉字"},
    {"name": "百家同器", "label": "留档（不送检）", "rationale": "「百家同器」语义贴合，留档备选"},
    {"name": "一尺同量", "label": "留档（不送检）", "rationale": "「一尺同量」语义贴合，留档备选"},
]
NEGATIVE = [
    {"name": "丐帮联盟", "label": "反例（旧名组合，用于验证体检有牙）"},
]

# ---- 2. 三道可自算的关 ----
# 文学/作品专名表（武侠、古典小说、民间传说中的组织与人物名）
LITERARY = {
    "丐帮", "少林", "武当", "峨眉", "华山派", "桃花岛", "明教", "天地会",
    "红花会", "雪山派", "星宿派", "逍遥派", "全真教", "古墓派", "日月神教",
    "梁山", "水浒", "西游记", "红楼梦", "三国", "封神",
}
# 通用词与描述性词（作为商标显著性弱）；「之」为虚词，按 2026-11-09 六道关复算口径计为不贡献显著性
GENERIC = {
    "帮", "会", "联盟", "平台", "网络", "数据", "系统", "软件", "科技",
    "乞丐", "乞讨", "救济", "慈善", "公益", "公共", "共享", "之",
}
BANNED_CHARS = set("丐帮")

# 仅覆盖本项目候选名用字的最小拼音表（不是通用拼音库；用途单一，故不引依赖）
PINYIN = {
    "数": "shu", "字": "zi", "丐": "gai", "帮": "bang",
    "众": "zhong", "汲": "ji", "之": "zhi", "井": "jing",
    "器": "qi", "不": "bu", "私": "si", "属": "shu",
    "百": "bai", "家": "jia", "同": "tong",
    "一": "yi", "尺": "chi", "量": "liang",
    "公": "gong", "擎": "qing",
    "联": "lian", "盟": "meng", "合": "he", "济": "ji",
    "簿": "bu", "拾": "shi", "薪": "xin",
}


def pinyin(s: str) -> str:
    return "".join(PINYIN.get(c, "?") for c in s)


def lev(a: str, b: str) -> int:
    """编辑距离：用于拼音近似判断（音近则形近，形近则易判混淆）。"""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def check_name(cand: dict, is_main: bool = False) -> list[tuple[str, bool, str]]:
    n = cand["name"]
    py = pinyin(n)
    main_core_py = pinyin(MAIN["core"])
    out = []

    hit_lit = sorted({w for w in LITERARY if w in n})
    out.append(("① 无文学/作品专名指涉", not hit_lit, f"命中：{'、'.join(hit_lit) if hit_lit else '无'}"))

    if is_main:
        out.append(("② 与主名核心拼音距离 ≥3", True, "— 主名自身，不适用"))
        out.append(("③ 与主名无共用汉字", True, "— 主名自身，不适用"))
    else:
        d = lev(py, main_core_py)
        out.append(("② 与主名核心拼音距离 ≥3", d >= 3, f"{py} vs {main_core_py}，距离 {d}"))
        inter = sorted(set(n) & set(MAIN["core"]))
        out.append(("③ 与主名无共用汉字", not inter, f"共用：{'、'.join(inter) if inter else '无'}"))

    bad = sorted(set(n) & BANNED_CHARS)
    out.append(("④ 不含 丐/帮", not bad, f"含：{'、'.join(bad) if bad else '无'}"))

    out.append(("⑤ 字数 2–4", 2 <= len(n) <= 4, f"{len(n)} 字"))

    gen = sorted({w for w in GENERIC if w in n})
    out.append(("⑥ 不含通用/描述性词", not gen, f"命中：{'、'.join(gen) if gen else '无'}"))
    return out


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def main():
    print("=" * 78)
    print("W6·商标检索任务书与备名预检（可自算部分）")
    print("=" * 78)

    sec("§1 检索范围：5 类 × 6 项 = 30 个商品/服务项")
    total_items = 0
    for k, v in CLASSES.items():
        n = len(v["items"])
        total_items += n
        flag = "✅" if n >= 6 else "❌"
        print(f"  {flag} {k} {v['name']:12} {n} 项")
        for it in v["items"]:
            print(f"       · {it}")
    print(f"  合计：{len(CLASSES)} 类 / {total_items} 项" +
          ("（每类 ≥6 项，满足检索委托的最低分辨率）" if total_items >= 30 else ""))

    sec("§2 为什么是这 5 类：按实际使用场景数排序，不按'全类注册'的直觉")
    usage = {
        "第 9 类": ["软件下载页", "应用商店名"],
        "第 42 类": ["SaaS 服务名", "API 文档标题", "托管服务说明"],
        "第 35 类": ["撮合平台名"],
        "第 41 类": ["培训与会议"],
        "第 45 类": ["知识产权许可（自身业务即在此类）"],
    }
    for k, scenes in sorted(usage.items(), key=lambda kv: -len(kv[1])):
        print(f"  {k}：{len(scenes)} 个场景 → {'、'.join(scenes)}")
    print()
    print("  排序结论：9 / 42 优先（各 2–3 个场景），35 次之，41 / 45 最后。")
    print("  但检索必须五类全做：检索是判断'有没有人已经占了'，不是'我要不要用'。")
    print("  只检索计划注册的类别，等于只查自己想查的地方——那叫确认，不叫检索。")

    sec("§3 备名预检：六道关，全部可在本机算完")
    for cand in [MAIN] + CANDIDATES + NEGATIVE:
        rows = check_name(cand, is_main=(cand is MAIN))
        ok = sum(1 for _, v, note in rows if v and not note.startswith("—"))
        tag = cand["label"]
        print(f"\n  【{tag}】{cand['name']}　{ok}/6 通过")
        if "rationale" in cand:
            print(f"    定位：{cand['rationale']}")
        for name, v, note in rows:
            print(f"    {'✅' if v else '❌'} {name:22}{note}")

    print()
    good = [c for c in CANDIDATES if all(v for _, v, _ in check_name(c))]
    main_rows = check_name(MAIN, is_main=True)
    main_ok = sum(1 for _, v, note in main_rows if v and not note.startswith("—"))
    print(f"  主名通过 {main_ok}/4（适用 4 关）；备名通过 {len(good)}/{len(CANDIDATES)}（每个 6/6）")
    print()
    print("  主名失守的那一关，恰好解释了为什么必须有备名：")
    print("    · 「众汲之井」四字里「之」是虚词，不计显著性，显著性只能由「众汲」与「井」承担，")
    print("      整句读起来像一句描述（众人共汲的那口井）——在商品/服务上属描述性表达，第十一条风险；")
    print("    · 「井」是日常名词，单独看显著性更弱；四字组合能过，靠的是组合而非单字；")
    print("    · 旧名「丐帮」的武侠组织指涉与不良影响风险，已随 2026-11-10 改名一并解除，")
    print("      本条不再是主名的问题，仅作为反例保留（见 NEGATIVE）。")
    print("  这些不需要检索就能看出——它们是语义问题，不是注册问题。")

    sec("§4 本脚本算不出的那一关（也是唯一真正需要花钱的一关）")
    print("  ① 在先注册/在先申请的相同或近似商标 —— 需要商标数据库检索（付费）；")
    print("  ② 在先权益（商号、著作权、姓名、作品名称的商品化权益）—— 需要检索 + 法律判断；")
    print("  ③ 是否构成'不良影响' —— 审查员裁量，须执业律师出意见。")
    print()
    print("  六道关能排掉'明显不该提交'的候选，排不掉'已经有人注册'的候选。")
    print("  所以备名的正确用法是：先把六道关全过的名字准备好，检索结论一到就能立刻提交，")
    print("  而不是等结论出来再开会想名字——那时候会议只有一个议题：赶时间。")

    print()
    print(f"汇总：检索范围 {len(CLASSES)} 类 {total_items} 项；备名 {len(good)}/{len(CANDIDATES)} 过六关；"
          f"主名 {main_ok}/4；可自算 6 关、需付费 3 项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
