#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
asset_lock_check.py — W5-G2：资产锁定"三载体"咬合度校验（D-3 的证据）

口径（06 §5.5）：中国法下没有 asset lock 登记制度，锁定靠三样东西：章程宗旨+修改限制、
资助协议用途限制、清算条款。三样缺一不可，且失效条件必须互相咬合。
W5 补一条判定维度：每个载体还要能回答"谁、在什么时候、拿什么数据判它还成立"。

用法：python asset_lock_check.py <markdown 文件>
      （脚本会找表头含「载体」的表格，检查六列是否齐、三行是否都填满）
退出码：齐备 0；有缺口 1。
"""

import re
import sys

REQUIRED_COLS = ["条款", "失效条件", "判定输入", "判定时点", "责任人", "核验频次"]
EMPTY = {"", "-", "—", "–", "无", "n/a", "N/A"}


def split_row(line):
    line = line.strip()
    if not line.startswith("|"):
        return None
    return [c.strip() for c in line.strip("|").split("|")]


def find_table(lines, keyword):
    for i, line in enumerate(lines):
        cells = split_row(line)
        if not cells or keyword not in "".join(cells):
            continue
        sep = split_row(lines[i + 1]) if i + 1 < len(lines) else None
        if sep and all(re.fullmatch(r":?-{2,}:?", c) for c in sep if c):
            rows = []
            j = i + 2
            while j < len(lines):
                r = split_row(lines[j])
                if not r:
                    break
                rows.append(r)
                j += 1
            return cells, rows
    return None, None


def col_index(header, keyword):
    for idx, h in enumerate(header):
        if keyword in h:
            return idx
    return None


def main():
    if len(sys.argv) < 2:
        print("usage: python asset_lock_check.py <file.md>")
        return 2
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    header, rows = find_table(lines, "载体")
    print("=" * 78)
    print(f"文件：{path}")
    if header is None:
        print("结果：未找到表头含「载体」的表格 → 0 个载体，视为锁定不成立")
        return 1
    print(f"表头：{ ' | '.join(header) }")
    print(f"载体数：{len(rows)}")
    print("=" * 78)

    idx = {c: col_index(header, c) for c in REQUIRED_COLS}
    print()
    print("§1 列完备性（6 列 = 6 个判定维度）")
    present = []
    for c in REQUIRED_COLS:
        if idx[c] is None:
            print(f"  [缺] {c}")
        else:
            print(f"  [有] {c}（第 {idx[c] + 1} 列）")
            present.append(c)
    print(f"  列覆盖：{len(present)}/{len(REQUIRED_COLS)}")

    print()
    print("§2 逐载体完整性")
    full = 0
    for n, row in enumerate(rows, 1):
        name = row[0] if row else f"载体{n}"
        lacks = []
        for c in REQUIRED_COLS:
            i = idx[c]
            if i is None:
                lacks.append(c + "(列缺失)")
                continue
            if i >= len(row) or row[i].strip() in EMPTY:
                lacks.append(c)
        if lacks:
            print(f"  [不完整] {name[:30]:32} 缺：{'、'.join(lacks)}")
        else:
            full += 1
            print(f"  [完整]   {name[:30]:32}")

    total_dims = len(rows) * len(REQUIRED_COLS)
    have_dims = sum(
        1
        for r in rows
        for c in REQUIRED_COLS
        if idx[c] is not None and idx[c] < len(r) and r[idx[c]].strip() not in EMPTY
    )
    print()
    print(f"§3 咬合度：{have_dims}/{total_dims} 个判定单元（{len(rows)} 载体 × {len(REQUIRED_COLS)} 维）")
    print(f"    完整载体：{full}/{len(rows)}")
    print()
    if have_dims < total_dims:
        print("结论：锁定不成立。缺的不是措辞，是「谁在何时拿什么数据判」——")
        print("      只有条款与失效条件时，锁定只在争议发生后才能被援引，不能事前被检查。")
        return 1
    print("结论：三载体 × 六维全部咬合，可在年度审计中逐格核验。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
