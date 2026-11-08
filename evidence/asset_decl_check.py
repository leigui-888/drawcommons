#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""资产权属声明体检（L-14 的验收工具）。

三类资产的声明（数据库权利 / 名称 / 域名），每份必须回答 6 个字段。
缺任一字段，这份声明在争议时都无法使用——因为"谁的权利、凭什么、到哪、怎么证明、能不能卖、谁签的"
六件事里少一件，对方只需要攻那一件。

用法：
    python asset_decl_check.py ../数字丐帮2.0·W6-05*.md
    python asset_decl_check.py ../../_src/06_g1.md        # 基线对照
退出码：18/18 时 0，否则 1
"""

from __future__ import annotations

import re
import sys

SECTIONS = ["D1", "D2", "D3"]
LABELS = {"D1": "数据库权利", "D2": "名称", "D3": "域名"}

FIELDS = [
    "权利人称谓",
    "权利依据",
    "覆盖范围",
    "取得凭证",
    "处置限制",
    "签署与版本",
]

EMPTY = ("", "未定", "待定", "TBD", "无", "—", "-")


def split_row(line: str):
    s = line.strip()
    if not s.startswith("|"):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    return cells


def parse_section(text: str, tag: str):
    """取 ### D1 之后、下一个 ### 之前的内容。"""
    m = re.search(rf"^#+\s*{tag}\b.*?$(.*?)(?=^#+\s*D[0-9]\b|\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


def check_section(body: str, tag: str):
    """返回 [(字段, 是否合格, 实际内容)]"""
    rows = {}
    for line in body.splitlines():
        cells = split_row(line)
        if not cells or len(cells) < 2:
            continue
        key = cells[0].strip("* ")
        if key in FIELDS and key not in rows:
            rows[key] = cells[1].strip()
    out = []
    for f in FIELDS:
        val = rows.get(f, "").strip()
        # 判定标准是"这一栏有没有回答问题"，不是"有没有以'无'开头"。
        # 首版按前缀判，把 D3 的"无（尚未取得）；取得方式为…"误判为空——
        # 而那句话恰恰是本件最重要的一句。改为按长度与占位词判定。
        ok = len(val) >= 8 and val not in EMPTY
        out.append((f, ok, val or "（缺）"))
    return out


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else ""
    if not path:
        print("用法：python asset_decl_check.py <声明文件.md>")
        sys.exit(2)
    text = open(path, encoding="utf-8").read()

    print("=" * 78)
    print(f"W6·资产权属声明体检（L-14）　目标：{path}")
    print("=" * 78)

    total_ok = 0
    total = 0
    for tag in SECTIONS:
        body = parse_section(text, tag)
        sec(f"{tag} {LABELS[tag]}：6 个字段")
        if not body:
            print(f"  ❌ 未找到 {tag} 章节")
            total += len(FIELDS)
            continue
        rows = check_section(body, tag)
        for f, ok, val in rows:
            show = val if len(val) <= 46 else val[:44] + "…"
            print(f"  {'✅' if ok else '❌'} {f:8} {show}")
            total_ok += 1 if ok else 0
            total += 1

    print()
    print(f"汇总：{total_ok}/{total} 字段合格" +
          ("（三类资产均完成权属声明）" if total_ok == total else "（存在空字段，声明不可用）"))
    if total_ok < total:
        print()
        print("空字段不是'暂时没填'，是'这一栏在争议时会变成对方的论据'：")
        print("  · 缺权利人称谓 → 无法证明谁是权利人，任何人可主张自己才是；")
        print("  · 缺取得凭证 → 无法证明权利何时产生，而'谁先'决定归属；")
        print("  · 缺处置限制 → 声明人可随时把资产转给任意第三方，锁定形同虚设。")
    sys.exit(0 if total_ok == total else 1)


if __name__ == "__main__":
    main()
