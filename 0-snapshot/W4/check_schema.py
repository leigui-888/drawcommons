"""账本禁用字段检查器（v1.2）。

不变量：任何连续量字段不得承载"可累加、可打分"的语义。
v1.1 只查字段名，改名（points → magnitude_legacy）即可绕过；
v1.2 同时查三件事：
  1) 字段名（词表 + 后缀规则，含 _legacy 迁移残留）
  2) 主表是否仍存在旧积分列
  3) 主表旧积分列是否仍有非零值（值级检查，改名也躲不过）
用法：python check_schema.py ledger_w4.db
退出码：0 通过 / 1 命中
"""
import sqlite3
import re
import sys

# 词表：出现即视为承载金额或可累加语义
FORBIDDEN = [
    "amount", "price", "balance", "currency", "rate", "fee", "points",
    "commission", "settlement", "total", "sum_magnitude",
    "magnitude_legacy", "legacy_points", "legacy_score",
]
# 后缀规则：改名常用手段，单列一个规则兜住
FORBIDDEN_SUFFIX = ("_legacy", "_points", "_score", "_sum", "_total")
# 迁移残留列：存在即不通过（不等到写入才发现）
LEGACY_COLUMNS = ("magnitude_legacy", "legacy_points", "points")


def check(db):
    con = sqlite3.connect(db)
    bad = []
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'ledger_%'")]
    for t in tables:
        cols = [r[1] for r in con.execute("PRAGMA table_info(%s)" % t)]
        for col in cols:
            low = col.lower()
            for w in FORBIDDEN:
                if w in low:
                    bad.append((t, col, "word:%s" % w))
            for suf in FORBIDDEN_SUFFIX:
                if low.endswith(suf):
                    bad.append((t, col, "suffix:%s" % suf))
        for legacy in LEGACY_COLUMNS:
            if legacy in cols:
                n = con.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL AND %s <> 0" % (t, legacy, legacy)
                ).fetchone()[0]
                bad.append((t, legacy, "legacy_column_present(nonzero_rows=%d)" % n))
    return tables, bad


if __name__ == "__main__":
    t, b = check(sys.argv[1])
    print("tables:", t)
    print("forbidden hits:", b)
    print("结论:", "通过" if not b else "不通过（%d 处）" % len(b))
    sys.exit(1 if b else 0)
