#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
W3-B2 四向一致性核对器（可复跑）
用法：
  python check_consistency.py <目标目录> [--json out.json]

四项检查（对应排期表 W3-B2「全库 grep + 逐处判定」）：
  D1 抽成表述   : 抽成|分成|佣金|企业版|收费
  D2 金额字段   : 金额|余额|汇率|结算
  D3 信用分     : 信用分|评分|排名
  D4 旧阶段名   : 基建期|打工期

命中按《W2-P2》§4 的四分类标注（与 W2-06 同口径，脚本内变量名沿用旧称）：
  A 否定／禁止   同句含 不/无/零/永不/免/未/拒（脚本内 R1）
  B 引用 v1.x    同句或所在表格表头含 v1.x/原文/旧称/已废/对照/维度（脚本内 R2）
  C 词表与元文档 禁止清单、正则示例、修订记录/核对报告/任务清单/索引、附录 C（脚本内 R3+R4）
  D 真残留       以上都不沾（脚本内 R0）——只有 D 类计入违规

设计取舍：本脚本只做"检索 + 粗分类"，不做最终判定。
理由：判定要看语境（同一句"抽成"在这里是禁止项、在那里是引述），
把判定塞进正则，等于用规则代替判断，正是这个项目最反对的做法。
所以 R0 是"给人看的清单"，不是"机器给的结论"。判定结论写在 B2 报告 §3。
"""
import json
import os
import re
import sys

CHECKS = {
    "D1": ("抽成表述", r"抽成|分成|佣金|企业版|收费"),
    "D2": ("金额字段", r"金额|余额|汇率|结算"),
    "D3": ("信用分", r"信用分|评分|排名"),
    "D4": ("旧阶段名", r"基建期|打工期"),
}

R3 = re.compile(r"禁止|不得|取消|删除|一律拒绝|反例|摧毁|不列入|不作")
R1 = re.compile(r"不|无|零|永不|免|未|拒|非")
R2 = re.compile(r"v1\.x|v1\.1|v1\.4|原文|原\*\*|原：|旧称|已废|改为|对照|差异|引述|维度")

# 表头上下文里出现的“豁免信号”
HDR_R2 = re.compile(r"v1\.x 原文|原文|对照|维度|改前|改后")
HDR_R3 = re.compile(r"禁止|反例|理由|为什么不兼容")
# 元文档：本身就在记录“旧措辞”这件事
META_FILE = re.compile(r"核对报告|任务清单|周索引|修订记录|自检|证据|README")

# D2 只对账本/契约类文档生效（排期表原文：“在账本相关文档中”）
D2_SCOPE = re.compile(r"账本|ledger|契约|openapi|协议|条款|terms|表|字段")


def classify(line, header, fname, in_appendix_c):
    if META_FILE.search(fname) or in_appendix_c:
        return "R4"
    if HDR_R3.search(header) or R3.search(line):
        return "R3"
    if HDR_R2.search(header) or R2.search(line):
        return "R2"
    if R1.search(line):
        return "R1"
    return "R0"


def scan(root):
    rows = []
    # 支持单文件（W3 的对外物料只有白皮书）或整目录（W2 起对外物料集合）
    if os.path.isfile(root):
        targets = [os.path.dirname(root) or ".", [os.path.basename(root)]]
    else:
        targets = [root, [n for n in sorted(os.listdir(root)) if n.endswith(".md")]]
    base, names = targets
    for name in names:
        if not name.endswith(".md"):
            continue
        lines = open(os.path.join(base, name), encoding="utf-8").read().splitlines()
        in_c = False
        for i, line in enumerate(lines, 1):
            if re.match(r"^## 附录 C", line):
                in_c = True
            elif re.match(r"^## ", line) and not line.startswith("## 附录 C"):
                in_c = False
            header = " ".join(lines[max(0, i - 12):i])[-600:]
            for cid, (label, pat) in CHECKS.items():
                for m in re.finditer(pat, line):
                    rows.append({
                        "file": name, "line": i, "check": cid, "check_label": label,
                        "word": m.group(),
                        "cls": classify(line, header, name, in_c),
                        "text": line.strip()[:160],
                    })
    return rows


def main():
    root = sys.argv[1]
    rows = scan(root)
    # A/B/C/D 四分类（W2-P2 §4）；C 类由脚本内的 R3（禁止清单）与 R4（元文档）合并
    def cls4(r):
        return {"R1": "A", "R2": "B", "R3": "C", "R4": "C", "R0": "D"}[r["cls"]]

    for r in rows:
        r["cls4"] = cls4(r)
    keys = ["D", "A", "B", "C"]

    print("| 检查项 | 命中 | D 真残留 | A 否定/禁止 | B 引用 v1.x | C 词表/元文档 |")
    print("|---|---|---|---|---|---|")
    tot = {k: 0 for k in keys}
    for cid, (label, _) in CHECKS.items():
        sub = [r for r in rows if r["check"] == cid]
        c = {k: sum(1 for r in sub if r["cls4"] == k) for k in keys}
        for k in keys:
            tot[k] += c[k]
        print("| %s %s | %d | **%d** | %d | %d | %d |"
              % (cid, label, len(sub), c["D"], c["A"], c["B"], c["C"]))
    print("| **合计** | %d | **%d** | %d | %d | %d |"
          % (len(rows), tot["D"], tot["A"], tot["B"], tot["C"]))

    for k in ["D", "B"]:
        sub = [r for r in rows if r["cls4"] == k]
        title = "D 真残留（待人工裁定）" if k == "D" else "B 引用 v1.x 原文（需确认标记）"
        print("\n### %s（%d 条）" % (title, len(sub)))
        for r in sub:
            print("- %s:%d [%s] %s" % (r["file"], r["line"], r["check"], r["text"]))

    if "--json" in sys.argv:
        dst = sys.argv[sys.argv.index("--json") + 1]
        json.dump(rows, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n[json] -> %s" % dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
