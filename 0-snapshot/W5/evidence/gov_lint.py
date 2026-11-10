#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gov_lint.py — W5-G4：章程 14 条"可判定性"校验（D-5 的证据）

判据：一条章程条款要能被判定，必须有三样东西——
      判定输入（谁在什么时候拿什么数据来判）、判尺（阈值或条件）、失败动作（不满足时发生什么）。
      只有"应当/必须/不得"而没有这三样的，是宣示，不是条款。

用法：
  python gov_lint.py <markdown 文件> [--header-keyword 条款]
输出：逐条 PASS/FAIL + 缺失要素；末行汇总 n/N。
退出码：全部完备 0；有缺项 1。
"""

import re
import sys

REQUIRED = ["判定输入", "判尺", "失败动作"]
EMPTY = {"", "-", "—", "–", "无", "n/a", "N/A"}


def split_row(line):
    line = line.strip()
    if not line.startswith("|"):
        return None
    cells = [c.strip() for c in line.strip("|").split("|")]
    return cells


def find_table(lines, keyword, start_marker=None):
    """返回 (header, rows, start_index)；取第一个表头含 keyword 的表格。
    给了 start_marker 时，只在该标记行之后找（同一文件里可能有多个含 keyword 的表）。"""
    begin = 0
    if start_marker:
        for i, line in enumerate(lines):
            if start_marker in line:
                begin = i
                break
    for i in range(begin, len(lines)):
        line = lines[i]
        cells = split_row(line)
        if not cells:
            continue
        if keyword in "".join(cells) and i + 1 < len(lines):
            sep = split_row(lines[i + 1])
            if sep and all(re.fullmatch(r":?-{2,}:?", c) for c in sep if c):
                header = cells
                rows = []
                j = i + 2
                while j < len(lines):
                    r = split_row(lines[j])
                    if not r:
                        break
                    rows.append(r)
                    j += 1
                return header, rows, i
    return None, None, None


def col_index(header, keyword):
    for idx, h in enumerate(header):
        if keyword in h:
            return idx
    return None


def has_number(text):
    return bool(re.search(r"\d", text))


def main():
    if len(sys.argv) < 2:
        print("usage: python gov_lint.py <file.md> [--header-keyword 条款]")
        return 2
    path = sys.argv[1]
    keyword = "条款"
    if "--header-keyword" in sys.argv:
        keyword = sys.argv[sys.argv.index("--header-keyword") + 1]
    marker = None
    if "--start-marker" in sys.argv:
        marker = sys.argv[sys.argv.index("--start-marker") + 1]

    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    header, rows, _ = find_table(lines, keyword, marker)
    print("=" * 76)
    print(f"文件：{path}")
    if header is None:
        print(f"结果：未找到表头含「{keyword}」的表格 → 0/0，视为不完备")
        return 1
    print(f"表头：{ ' | '.join(header) }")
    print(f"行数：{len(rows)}")
    print("=" * 76)

    idx = {k: col_index(header, k) for k in REQUIRED}
    missing_cols = [k for k, v in idx.items() if v is None]
    if missing_cols:
        print(f"缺列：{'、'.join(missing_cols)}")
        print("说明：缺列意味着这一列所代表的判定要素在整张表里都不存在，不是个别条款漏写。")
        print()

    ok = 0
    for n, row in enumerate(rows, 1):
        title = row[0] if row else f"第 {n} 行"
        label = row[1] if len(row) > 1 else title
        lacks = []
        for k in REQUIRED:
            i = idx[k]
            if i is None:
                lacks.append(k + "(列缺失)")
                continue
            if i >= len(row) or row[i].strip() in EMPTY:
                lacks.append(k + "(空白)")
                continue
            if k == "判尺" and not has_number(row[i]):
                lacks.append("判尺(无数值/条件)")
        if lacks:
            print(f"[FAIL] {n:2}. {label[:34]:36} 缺：{'；'.join(lacks)}")
        else:
            ok += 1
            print(f"[PASS] {n:2}. {label[:34]:36}")

    print()
    print(f"汇总：{ok}/{len(rows)} 条三要素齐备。")
    if ok < len(rows):
        print("未齐备的条款不得作为 G4′ 的交付依据——它们在争议发生时无法被援引。")
        return 1
    print("全部齐备：每条都能回答「谁、拿什么数据、按什么阈值、判出什么后果」。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
