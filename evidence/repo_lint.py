#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""仓库许可体检：G5′ 许可门的机器可验部分。

十一条规则，每条给一个数。规则不是为了"看起来严谨"，是为了回答一个具体问题：
**一个陌生人 clone 下来，能不能仅凭仓库里的文件判断"这个文件我能不能用"。**

R1–R10 的视野是 `repo/`（授权树）。R11 补的是 `repo/` 之外那一层：根 `spec/`
与 `evidence/`。它们同样被 git 跟踪、同样随 clone 公开，却不在任何规则视野内——
R4 只遍历 `repo/`，所以这两个目录的文件此前从未被检查过是否可被判断许可。

用法：
    python repo_lint.py ../repo
    python repo_lint.py <任意目录>      # 基线对照，例如空目录或未经治理的目录

退出码：全部通过 0；任一失败 1。
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import subprocess
import sys

REQUIRED = ["LICENSE", "NOTICE", "CONTRIBUTING.md", "DCO"]

# 需要逐文件声明许可的扩展名（代码与规范）
NEED_HEADER = (".py", ".sh", ".yaml", ".yml", ".json")

# R11：仓库根下、repo/ 之外的受管目录 → 该目录应声明的 SPDX 标识。
# 这些目录不在 repo/README.md 的归属表内（那张表只管授权树），所以只能在此硬编码，
# 改这里等于改许可决定，须同步 repo/README.md 与 NOTICE。
TOP_DIRS = {"spec/": "CC0-1.0", "evidence/": "Apache-2.0"}
TOP_EXT = (".py", ".sql")
TOP_SKIP = ("0-snapshot/",)        # 2.0 冻结基线，字节不可动，其许可已由冻结件自身记录
BANNED = ["CC-BY-NC", "CC-BY-ND", "GPL", "AGPL"]      # 子串匹配，注意 Apache 不含 GPL


def sec(t):
    print()
    print(t)
    print("-" * len(t))


def tracked_files(root):
    """优先用 git 的文件清单；无 git 时退回文件系统遍历。返回 (路径列表, 来源)。"""
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files"],
            capture_output=True, text=True, check=True,
        ).stdout
        files = [l for l in out.splitlines() if l.strip()]
        if files:
            return files, "git ls-files"
    except Exception:
        pass
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), root).replace("\\", "/")
            files.append(rel)
    return sorted(files), "os.walk"


def parse_matrix(root):
    """从 README.md 的 ```licenses 代码块读出归属表，返回 [(glob, spdx)]（顺序即优先级）。"""
    p = os.path.join(root, "README.md")
    if not os.path.exists(p):
        return []
    text = open(p, encoding="utf-8").read()
    m = re.search(r"```licenses\n(.*?)```", text, re.S)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def rule1(root):
    sec("R1 根目录四件套（LICENSE / NOTICE / CONTRIBUTING / DCO）")
    ok = 0
    for f in REQUIRED:
        exist = os.path.exists(os.path.join(root, f))
        size = os.path.getsize(os.path.join(root, f)) if exist else 0
        print(f"  {'✅' if exist else '❌'} {f:18} {'存在' if exist else '缺失':6} {size:>7} 字节")
        ok += 1 if exist else 0
    print(f"  结果：{ok}/{len(REQUIRED)}")
    return ok == len(REQUIRED)


def rule2(root):
    sec("R2 许可文本完整度（全文 vs 指针）")
    files = [f for f in os.listdir(root) if f.startswith("LICENSE")] if os.path.isdir(root) else []
    full, pointer, miss = [], [], []
    for f in sorted(files):
        p = os.path.join(root, f)
        t = open(p, encoding="utf-8", errors="ignore").read()
        n = len(t)
        is_full = (
            ("Apache License" in t and "Version 2.0" in t and n > 8000)
            or (("legalcode" in t) and n > 12000)      # CC 全文 legalcode 远长于指针件
        )
        if is_full:
            full.append(f)
            print(f"  ✅ 全文  {f:26} {n:>7} 字节")
        else:
            pointer.append(f)
            print(f"  ⚠️ 指针  {f:26} {n:>7} 字节  （法律文本指向外部 URL）")
    if not files:
        print("  ❌ 无任何许可文件")
        miss.append("(none)")
    print(f"  结果：存在 {len(files)} 份，全文 {len(full)} / 指针 {len(pointer)}")
    if pointer:
        print("  说明：指针件在法理上可用（CC 官方允许链接），但它使'仓库自带完整条款'不成立；")
        print("        离线环境或链接失效时，使用者拿不到条款原文。计入 D-06，G7′ 前补齐。")
    return len(full) == len(files) and bool(files)


def rule3(root, files, matrix):
    sec("R3 逐文件许可归属覆盖率")
    if not matrix:
        print("  ❌ README.md 中无 ```licenses 归属表，无法判定")
        return False
    uncovered, covered = [], 0
    for f in files:
        hit = None
        for glob, spdx in matrix:
            if fnmatch.fnmatch(f, glob):
                hit = spdx
                break
        if hit:
            covered += 1
        else:
            uncovered.append(f)
    print(f"  归属表规则 {len(matrix)} 条；已跟踪文件 {len(files)} 个（来源见 R8）")
    print(f"  结果：{covered}/{len(files)} 个文件有明确许可归属")
    if uncovered:
        for f in uncovered:
            print(f"  ❌ 无归属：{f}")
    return not uncovered and covered > 0


def rule4(root, files):
    sec("R4 逐文件许可声明（代码/规范需 SPDX 头或 .license 伴生）")
    targets = [f for f in files if f.endswith(NEED_HEADER) and not f.startswith("LICENSE")]
    ok = 0
    for f in targets:
        p = os.path.join(root, f)
        side = p + ".license"
        head = ""
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                head = "".join(fh.readline() for _ in range(3))
        except OSError:
            pass
        has_head = "SPDX-License-Identifier:" in head
        has_side = os.path.exists(side)
        good = has_head or has_side
        how = "头声明" if has_head else ("伴生文件" if has_side else "无")
        print(f"  {'✅' if good else '❌'} {f:42} {how}")
        ok += 1 if good else 0
    print(f"  结果：{ok}/{len(targets)}" + ("" if targets else "  ← 无可检查对象，不计为通过"))
    if targets and ok < len(targets):
        print("  说明：无许可归属的文件在法律上等于'保留所有权利'，比没有仓库更糟——")
        print("        因为它让使用者以为自己在用开源软件。")
    return bool(targets) and ok == len(targets)


def rule5(root, files, matrix):
    sec("R5 spec/ 必须 CC0（P4 形态②的硬要求）")
    specs = [f for f in files if f.startswith("spec/")]
    ok = 0
    for f in specs:
        spdx = None
        for glob, s in matrix:
            if fnmatch.fnmatch(f, glob):
                spdx = s
                break
        good = spdx == "CC0-1.0"
        print(f"  {'✅' if good else '❌'} {f:42} 归属={spdx}")
        ok += 1 if good else 0
    print(f"  结果：{ok}/{len(specs)}")
    return specs and ok == len(specs)


def rule6(matrix):
    sec("R6 禁用许可（NC / ND / GPL / AGPL）")
    bad = [(g, s) for g, s in matrix if any(b in s for b in BANNED)]
    for g, s in bad:
        print(f"  ❌ {g:30} {s}")
    print(f"  结果：违规 {len(bad)} 处 / 规则 {len(matrix)} 条" + ("" if matrix else "  ← 无归属表，不计为通过"))
    return bool(matrix) and not bad


def rule7(root):
    sec("R7 NOTICE 与许可不得互相矛盾")
    p = os.path.join(root, "NOTICE")
    if not os.path.exists(p):
        print("  ❌ 无 NOTICE")
        return False
    t = open(p, encoding="utf-8", errors="ignore").read()
    # 只有在"没有否定词"的行里命中才算违规：
    # 本规则自己就要求 NOTICE 写"本仓库不含'保留所有权利'声明"，朴素匹配会把这个句子判成违规。
    neg = ("不含", "无任何", "不得", "不得出现", "禁止", "未声明")
    bad = []
    for line in t.splitlines():
        if re.search(r"(?i)all rights reserved|保留所有权利", line):
            if not any(w in line for w in neg):
                bad.append(line.strip())
    print(f"  {'✅' if not bad else '❌'} 命中'保留所有权利'类表述：{len(bad)} 处（已排除否定句）")
    has_split = ("不授予" in t) and ("商标" in t)
    print(f"  {'✅' if has_split else '⚠️'} 名称与许可分离声明：{'有' if has_split else '无'}")
    return not bad


def rule8(files, source):
    sec("R8 文件清单来源（可复验性）")
    print(f"  清单来源：{source}；文件数 {len(files)}")
    print(f"  {'✅' if source == 'git ls-files' else '⚠️'} "
          f"{'可被第三方用同一条命令复现' if source == 'git ls-files' else '非 git 清单，外部无法逐字节复现'}")
    return source == "git ls-files"


def read_manifest(root):
    """读 MANIFEST.sha256，返回 [(sha256, 路径)]；忽略注释与空行。"""
    p = os.path.join(root, "MANIFEST.sha256")
    if not os.path.exists(p):
        return None
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        out.append((parts[0], parts[1].lstrip("*")))
    return out


def rule9(root, files):
    sec("R9 MANIFEST 路径 ↔ 实际文件一致性")
    entries = read_manifest(root)
    if entries is None:
        print("  ❌ 无 MANIFEST.sha256")
        return False
    missing = [path for _, path in entries if not os.path.exists(os.path.join(root, path))]
    listed = {path for _, path in entries}
    unlisted = [f for f in files if f not in listed and f != "MANIFEST.sha256"]

    print(f"  清单条目 {len(entries)}；路径缺失 {len(missing)}；仓库内未覆盖 {len(unlisted)}")
    for m in missing:
        print(f"    ❌ 清单指向不存在的文件：{m}")
    for u in unlisted[:12]:
        print(f"    · 未纳入清单（不在校验范围）：{u}")
    if len(unlisted) > 12:
        print(f"    · ……另有 {len(unlisted) - 12} 个")

    # 目录树里存在同名但扩展名错位的情况（.schema.json 与 .license 互换）也要报出来
    stems = {}
    for f in files:
        stems.setdefault(f.replace(".json", "").replace(".license", ""), []).append(f)
    swapped = [(k, v) for k, v in stems.items() if len(v) > 1
               and any(x.endswith(".license") for x in v) and any(x.endswith(".json") for x in v)]
    for k, v in swapped:
        print(f"    ⚠️ 同名多件（检查扩展名是否错位）：{k} → {', '.join(sorted(v))}")

    print(f"  {'✅' if not missing else '❌'} 清单路径全部可定位")
    return not missing


def rule10(root):
    """R10：deploy/ 里的算法副本必须与 src/ 逐字节相同。

    为什么单独一条：`deploy/app/ledger_hash.py` 是为了让部署目录自含（build context
    里必须有它），属于 vendoring。vendoring 的经典失败方式不是"写了错代码"，而是
    "两份都对，但不一样"——哈希算法一变，线上算出的锚值与仓库里声称的就不是一回事，
    而各自的 MANIFEST 行都能自证清白。sha256sum -c 抓不到跨文件分叉，所以在这里抓。
    """
    sec("R10 deploy/ 的 ledger_hash.py 与 src/ 逐字节相同")
    a = os.path.join(root, "src", "ledger_hash.py")
    b = os.path.join(root, "deploy", "app", "ledger_hash.py")
    if not os.path.exists(b):
        print("  · 不适用：无 deploy/app/ledger_hash.py（未含部署目录）")
        return True
    if not os.path.exists(a):
        print("  ❌ 存在部署副本，但缺 src/ledger_hash.py（唯一源不见了）")
        return False

    def sh(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()

    ha, hb = sh(a), sh(b)
    print(f"  src/      {ha[:16]}…  {os.path.getsize(a):>6} 字节")
    print(f"  deploy/   {hb[:16]}…  {os.path.getsize(b):>6} 字节")
    same = ha == hb
    print(f"  {'✅ 一致' if same else '❌ 已分叉'}")
    if not same:
        print("  说明：两份 hash 各自都能通过自己那条 MANIFEST 校验，分叉不会被 sha256sum -c 发现。")
        print("        修法：以 src/ 为准覆盖 deploy/，再跑 regen_manifest.py 重算。")
    return same


def rule11(root):
    """R11：repo/ 之外的受管文件也要能判断许可（根 spec/ 与 evidence/）。

    root 参数是 repo/，本条需上跳一层取仓库根。找不到 .git 时返回 None 表示
    "不适用"（例如把 repo/ 单独拷出去做基线对照），不计入分母也不判失败。
    """
    sec("R11 仓库根受管文件（repo/ 之外）的许可声明")
    top = os.path.dirname(root)
    if not os.path.isdir(os.path.join(top, ".git")):
        print("  · 不适用：repo/ 的上级不是 git 仓库根，跳过（不计入分母）")
        return None
    try:
        out = subprocess.run(["git", "-C", top, "ls-files"],
                             capture_output=True, text=True, check=True).stdout
    except Exception:
        print("  · 不适用：仓库根无法执行 git ls-files，跳过（不计入分母）")
        return None

    targets = []
    for f in (l.strip() for l in out.splitlines()):
        if not f or f.startswith("repo/") or f.startswith(TOP_SKIP):
            continue
        for d, lic in TOP_DIRS.items():
            if f.startswith(d) and f.endswith(TOP_EXT):
                targets.append((f, lic))
                break

    ok = 0
    for f, lic in targets:
        head = ""
        try:
            with open(os.path.join(top, f), encoding="utf-8", errors="ignore") as fh:
                head = "".join(fh.readline() for _ in range(5))
        except OSError:
            pass
        m = re.search(r"SPDX-License-Identifier:\s*(\S+)", head)
        got = m.group(1) if m else "无声明"
        good = got == lic
        print(f"  {'✅' if good else '❌'} {f:36} {got}" + ("" if good else f"  ← 应为 {lic}"))
        ok += 1 if good else 0
    print(f"  结果：{ok}/{len(targets)}" + ("" if targets else "  ← 无可检查对象，不计为通过"))
    if targets and ok < len(targets):
        print("  说明：这些文件不在 repo/README.md 的归属表内（那张表只管 repo/），")
        print("        所以许可只能靠文件头声明。缺头即等于『保留所有权利』。")
    return bool(targets) and ok == len(targets)


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    root = os.path.abspath(root)
    print("=" * 78)
    print(f"W6·仓库许可体检　目标：{root}")
    print("=" * 78)

    files, source = tracked_files(root)
    matrix = parse_matrix(root)

    results = [
        ("R1 四件套", rule1(root)),
        ("R2 全文完整度", rule2(root)),
        ("R3 归属覆盖率", rule3(root, files, matrix)),
        ("R4 逐文件声明", rule4(root, files)),
        ("R5 spec 必须 CC0", rule5(root, files, matrix)),
        ("R6 无禁用许可", rule6(matrix)),
        ("R7 NOTICE 无矛盾", rule7(root)),
        ("R8 清单可复验", rule8(files, source)),
        ("R9 MANIFEST 路径一致", rule9(root, files)),
        ("R10 deploy 副本一致", rule10(root)),
        ("R11 根受管文件声明", rule11(root)),
    ]

    print()
    print("=" * 78)
    scored = [(n, v) for n, v in results if v is not None]
    ok = sum(1 for _, v in scored if v)
    for name, v in results:
        mark = "—" if v is None else ("✅" if v else "❌")
        print(f"  {mark} {name}")
    skipped = len(results) - len(scored)
    print(f"  合计：{ok}/{len(scored)} 条通过" + (f"（{skipped} 条不适用，未计入）" if skipped else ""))
    print("=" * 78)
    sys.exit(0 if ok == len(scored) else 1)


if __name__ == "__main__":
    main()
