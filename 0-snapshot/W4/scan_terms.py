"""W4 抽租类表述扫描：六组（W2-P2 §4）+ 一组（W4 双向枚举新增）。

用法：python scan_terms.py <目录 或 .md/.txt 文件...>
输出：每组命中数与逐文件分布；末行给总命中。D 类须人工逐处标注后判定。
"""
import re
import sys
import os

GROUPS = {
    "G1 收费类": r"抽成|分成|佣金|企业版|付费版|优先接入|付费认证",
    "G2 账本类": r"金额|余额|汇率|结算",
    "G3 分数类": r"信用分|评分|排名|扣分",
    "G4 时代类": r"基建期|打工期|循环期",
    "G5 名称类": r"丐帮|施粥|乞讨|传功|分舵",
    "G6 募捐类": r"公开募捐|善款|募捐收入|年度捐赠人|个人小额捐赠|捐赠收入|接受社会捐赠",
    "G7 计量同义": r"扣减|积分|点数|分值",
}


def files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _, fs in os.walk(p):
                for f in fs:
                    if f.lower().endswith((".md", ".txt")):
                        yield os.path.join(root, f)
        elif os.path.isfile(p):
            yield p


def main():
    targets = sorted(set(files(sys.argv[1:])))
    if not targets:
        print("用法：python scan_terms.py <目录 或 .md/.txt 文件...>")
        return 2
    total = 0
    for g, pat in GROUPS.items():
        per = {}
        for f in targets:
            with open(f, encoding="utf-8", errors="ignore") as fh:
                n = len(re.findall(pat, fh.read()))
            if n:
                per[os.path.basename(f)] = n
        print(f"{g}: {sum(per.values())} 处 {per}")
        total += sum(per.values())
    print(f"总命中 {total} 处，覆盖 {len(targets)} 份文本；D 类须人工逐处标注后判定")
    return 0


if __name__ == "__main__":
    sys.exit(main())
