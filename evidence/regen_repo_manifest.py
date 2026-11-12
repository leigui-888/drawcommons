# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
"""生成 / 校验 `repo/MANIFEST.sha256`。

为什么需要它
------------
R9 一直是失败的：仓库里没有 MANIFEST，第三方拿到仓库后**没有任何办法**
确认「我手上这份和作者发布的那份是不是同一份」。sha256sum 清单是最低成本的
答案——它不解释内容，只固定字节。

口径
----
- 文件集合取 `git ls-files --cached --others --exclude-standard`，与
  `evidence/repo_lint.py` 的 `tracked_files()` 同一口径：已跟踪 + 新建未忽略。
  两边用不同口径，会出现「清单里有的不在检查面、检查面有的不在清单里」，
  那种不一致比没有清单更坏。
- 排除 `MANIFEST.sha256` 自身（自指会让它永远对不上自己）。
- 按路径排序，输出 sha256sum 兼容格式：`<hash><两个空格><path>`，
  于是 `sha256sum -c MANIFEST.sha256` 可直接用，不必写解析器。

用法
----
    cd repo
    python ../evidence/regen_repo_manifest.py            # 生成
    python ../evidence/regen_repo_manifest.py --check    # 只校验，不一致返回 1
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys

NAME = "MANIFEST.sha256"


def tracked(root: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=True,
        ).stdout
        files = [l.strip() for l in out.splitlines() if l.strip()]
        if files:
            return sorted(files)
    except Exception:
        pass
    acc = []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d != ".git"]
        for f in fns:
            p = os.path.join(dp, f)
            acc.append(os.path.relpath(p, root).replace(os.sep, "/"))
    return sorted(acc)


def digest(root: str, rel: str) -> str:
    h = hashlib.sha256()
    with open(os.path.join(root, rel), "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(root: str, when: str) -> tuple[str, list[tuple[str, str]]]:
    files = [f for f in tracked(root) if f != NAME]
    rows = [(digest(root, f), f) for f in files]
    head = [
        f"# {NAME} —— 逐文件 SHA-256，供第三方复现",
        "# 生成：cd repo && python ../evidence/regen_repo_manifest.py",
        "# 校验：sha256sum -c MANIFEST.sha256",
        "# 口径：git ls-files --cached --others --exclude-standard（与 repo_lint 的 tracked_files 同源）",
        f"# 生成时点：{when}　条目：{len(rows)}",
        "#",
        "# 本清单只固定字节，不解释内容；条款与规范的含义以各文件正文为准。",
    ]
    body = [f"{h}  {p}" for h, p in rows]
    return "\n".join(head + body) + "\n", rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    ap.add_argument("--when", default="2026-11-12")
    a = ap.parse_args()
    root = os.path.abspath(a.root)
    text, rows = build(root, a.when)
    dst = os.path.join(root, NAME)

    if a.check:
        if not os.path.exists(dst):
            print(f"❌ 无 {NAME}", file=sys.stderr)
            return 1
        want = {}
        for line in open(dst, encoding="utf-8"):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            h, p = line.split(None, 1)
            want[p.lstrip("*")] = h
        bad = []
        for h, p in rows:
            if p not in want:
                bad.append(("未列入清单", p))
            elif want[p] != h:
                bad.append(("内容已变", p))
        for p in sorted(set(want) - {p for _, p in rows}):
            bad.append(("清单指向不存在的文件", p))
        print(f"清单 {len(want)} 条，实际 {len(rows)} 个文件，问题 {len(bad)}")
        for why, p in bad[:20]:
            print(f"  ❌ {why}：{p}")
        if len(bad) > 20:
            print(f"  ……另有 {len(bad) - 20} 条")
        print("结论：", "一致" if not bad else "不一致——改了文件就重跑生成，别手改清单")
        return 0 if not bad else 1

    with open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    total = sum(os.path.getsize(os.path.join(root, p)) for _, p in rows)
    print(f"已写 {NAME}：{len(rows)} 个文件，合计 {total:,} 字节，清单 {len(text.encode()):,} 字节")
    for h, p in rows[:5]:
        print(f"  {h[:12]}…  {p}")
    if len(rows) > 5:
        print(f"  …… 另有 {len(rows) - 5} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
