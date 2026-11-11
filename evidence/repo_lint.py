#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""仓库许可体检：G5′ 许可门的机器可验部分。

十四条规则，每条给一个数。规则不是为了"看起来严谨"，是为了回答一个具体问题：
**一个陌生人 clone 下来，能不能仅凭仓库里的文件判断"这个文件我能不能用"，以及
"谁做的、能不能找到他"。**

R1–R10 的视野是 `repo/`（授权树）。R11 补的是 `repo/` 之外那一层：根 `spec/`
与 `evidence/`。它们同样被 git 跟踪、同样随 clone 公开，却不在任何规则视野内——
R4 只遍历 `repo/`，所以这两个目录的文件此前从未被检查过是否可被判断许可。

R12/R13 换了个问题：许可说得清「能不能用」，说不清「这是谁做的」。署名承诺若只写在
CONTRIBUTING 里，就是一句没有对象的话——没有名录可查、没有依据可验、被删了也无人知道。
R12 把名录接回 git 记录（不漏记、不虚构、依据可查），R13 卡住名录的两份表示不许分叉。

R14 再进一步：名录说「谁做了它」，签名说「这个版本是谁发的」。二者都靠「同一事实写在
两处」来防单点改动——R14 比对公钥指纹与 CREDITS.md §10 的记载。它防不了「两份一起改」，
那条只能靠仓库外的指纹分发渠道，故规则输出里把这一点直接印出来，不假装覆盖了。

用法：
    python repo_lint.py ../repo
    python repo_lint.py <任意目录>      # 基线对照，例如空目录或未经治理的目录

退出码：全部通过 0；任一失败 1。
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
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


def _load_credits(root):
    """读 repo/credits.json。解析失败当作「没有名录」——宁可红，不可静默跳过。"""
    p = os.path.join(root, "credits.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:  # noqa: BLE001
        print(f"  ❌ credits.json 解析失败：{e}")
        return None


def _git(top, *args):
    """在仓库根跑 git，返回 stdout；失败返回 None。"""
    try:
        return subprocess.run(["git", "-C", top, *args],
                              capture_output=True, text=True, check=True).stdout
    except Exception:  # noqa: BLE001
        return None


def _person_emails(p):
    """一个人可以有多个提交邮箱（换过机器、换过邮箱、用实名提交过）。
    只认 `email` 会把这些提交判成「未登记」，逼着维护者去编一个假条目——
    规则写错，比没有规则更坏，所以这里收全部已知邮箱。"""
    es = {p.get("email", "").lower()}
    for e in (p.get("emails") or []):
        es.add(str(e).lower())
    es.discard("")
    return es


def rule12(root):
    """R12：署名承诺有没有真的落地。

    三个问题，缺任一个，承诺就只是话：
      ① 写过代码的人，名录里有没有？（不漏记）
      ② 名录里的人，git 里有没有？（不虚构——给了署名却查不到贡献，是另一种伤害）
      ③ 每条依据的 commit 是否真的存在？（可核验）

    外加一条反向检查：文件头里还留着「某某版本贡献者」这类集体名没有。
    集体名是署名承诺失效的典型形态——名字写了，但指不到人。
    """
    sec("R12 署名落地：名录 ↔ git 记录 ↔ 文件头")
    data = _load_credits(root)
    if data is None:
        print("  ❌ 无（或无法解析）credits.json：署名承诺没有登记处")
        return False

    people = data.get("people") or []
    pending = data.get("pending") or []
    accounts = data.get("accounts") or []
    print(f"  名录：people {len(people)} / pending {len(pending)} / accounts {len(accounts)}")

    checks = []

    top = os.path.dirname(root)
    authors = None
    if os.path.isdir(os.path.join(top, ".git")):
        out = _git(top, "log", "--format=%ae")
        if out is not None:
            authors = {l.strip().lower() for l in out.splitlines() if l.strip()}

    if authors is None:
        print("  · 不适用：repo/ 的上级不是 git 仓库，跳过 ①②③（不计入分母）")
        return None

    known = set()
    for p in list(people) + list(pending):
        known |= _person_emails(p)
    known |= {a.get("email", "").lower() for a in accounts}
    known.discard("")

    # ① 漏记
    missing = sorted(authors - known)
    for m in missing:
        print(f"    ❌ git 里有提交、名录里没有：{m}")
    print(f"  {'✅' if not missing else '❌'} 未登记作者：{len(missing)}")
    checks.append(not missing)

    # ② 虚构（一个人任一邮箱在 git 里出现过即可，不要求主邮箱）
    ghost = sorted({p.get("id") or p.get("name", "?") for p in people
                    if not (_person_emails(p) & authors)})
    for g in ghost:
        print(f"    ❌ 名录里有、git 里没有任何提交：{g}")
    print(f"  {'✅' if not ghost else '❌'} 无法追溯的作者：{len(ghost)}")
    checks.append(not ghost)

    # ③ 依据可核验
    total = bad = 0
    for p in people:
        for sha in (p.get("evidence") or {}).get("commits") or []:
            total += 1
            if _git(top, "cat-file", "-e", f"{sha}^{{commit}}") is None:
                bad += 1
                print(f"    ❌ 依据指向不存在的提交：{p.get('id')} → {sha}")
    print(f"  {'✅' if not bad else '❌'} 依据可核验：{total - bad}/{total}"
          + ("" if total else "  ← 无名录依据，不判通过"))
    checks.append(bool(total) and not bad)

    # ④ 集体名残留（0-snapshot 是冻结基线，字节不可动，豁免）
    # 只认「版权声明的行首」——正文里讨论这件事的句子（本规则自身、CONTRIBUTING 的教学段）
    # 也会出现「贡献者」三个字，按子串抓会把它自己判成违规。
    pat = re.compile(r"^\s*(?:#+\s*)?(?:Copyright|SPDX-FileCopyrightText)[^\n]*贡献者")
    neg = ("不写", "此前写作", "不要写", "不再", "禁止")
    leftover = []
    for dirpath, dirnames, filenames in os.walk(top):
        dirnames[:] = [d for d in dirnames if d not in (".git", "0-snapshot", "__pycache__")]
        for f in filenames:
            if not f.endswith((".py", ".sh", ".md", ".json", ".yml", ".yaml", ".license", "NOTICE")):
                if f not in ("NOTICE", "DCO"):
                    continue
            fp = os.path.join(dirpath, f)
            try:
                with open(fp, encoding="utf-8", errors="ignore") as fh:
                    for ln, line in enumerate(fh, 1):
                        if pat.search(line) and not any(w in line for w in neg):
                            leftover.append(f"{os.path.relpath(fp, top)}:{ln}")
            except OSError:
                pass
    for l in leftover[:10]:
        print(f"    ❌ 集体名版权行：{l}")
    print(f"  {'✅' if not leftover else '❌'} 文件头集体名：{len(leftover)} 处")
    checks.append(not leftover)

    print(f"  结果：{sum(checks)}/{len(checks)} 项通过")
    return all(checks)


def rule13(root):
    """R13：CREDITS.md 与 credits.json 是同一份记录的两个表示。

    分叉的后果比「两份不一样」严重：名录是对外承诺，两份不一致时，
    主张的人会被告知「以另一份为准」——承诺就此落空。故与 R10 同构，
    逐条比对，不作容错。
    """
    sec("R13 名录两份源：CREDITS.md ↔ credits.json")
    data = _load_credits(root)
    if data is None:
        print("  ❌ 无（或无法解析）credits.json")
        return False
    p = os.path.join(root, "CREDITS.md")
    if not os.path.exists(p):
        print("  ❌ 无 CREDITS.md（人读的那份不见了）")
        return False

    text = open(p, encoding="utf-8").read()
    m = re.search(r"```credits\n(.*?)```", text, re.S)
    if not m:
        print("  ❌ CREDITS.md 中无 ```credits 清单块，无法比对")
        return False

    md = set()
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 3:
            md.add((cells[0], cells[1], cells[2].lower()))

    js = {(x.get("id", ""), x.get("name", ""), x.get("email", "").lower())
          for x in (data.get("people") or [])}

    only_md = sorted(md - js)
    only_js = sorted(js - md)
    for x in only_md:
        print(f"    ❌ 只在 CREDITS.md：{x[0]} / {x[1]}")
    for x in only_js:
        print(f"    ❌ 只在 credits.json：{x[0]} / {x[1]}")
    print(f"  记录数：md {len(md)} / json {len(js)}")
    print(f"  {'✅ 一致' if md == js else '❌ 已分叉'}")
    if md != js:
        print("  说明：名录对外是承诺，两份不一致时主张者会被指向另一份，承诺即落空。")
        print("        修法：以 CREDITS.md 表格为准补齐 credits.json（或反之），再跑体检。")
    return md == js


def _ssh_fp(b64):
    """按 `ssh-keygen -l` 的算法算指纹：对 base64 解码后的公钥 blob 做 sha256。"""
    blob = base64.b64decode(b64)
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def rule14(root):
    """R14：签名公钥与它的两处记载不能分叉。

    换了密钥却忘了改文档，是这类机制最常见的失效方式：验签命令照着文档敲，
    报「Good signature」——签的是旧钥，而读者以为验的是当前发布。所以三样必须对上：

      ① `allowed_signers` 里的 principal 必须是名录里的人（否则把签发权给了名录外的人）；
      ② 每行钥匙必须限定 `namespaces="git"`（不限定，同一把钥还能签 SSH 证书，
         签名语义从「这是发布」扩散成「这是我签的一切」）；
      ③ 公钥指纹必须与 `CREDITS.md` §10 写的指纹完全相同（两处记载，一处改一处没改即红）。

    第 ③ 条有个天然局限，必须说清：`allowed_signers` 在仓库里，能改仓库的人也能改它。
    本规则只能防「自己人改漏」，防不了「有人把两份一起改掉」。后者只能靠仓库外的
    指纹分发渠道（见 CREDITS.md §10.3）。
    """
    sec("R14 签名公钥")
    path = os.path.join(root, "allowed_signers")
    if not os.path.exists(path):
        print("  ❌ 无 allowed_signers：签名无从验证，等于没有签名")
        return False

    data = _load_credits(root)
    known = set()
    if data:
        for x in (data.get("people") or []) + (data.get("pending") or []):
            if x.get("email"):
                known.add(x["email"].lower())
            for e in x.get("emails") or []:
                known.add(e.lower())
    known.discard("")

    principals, fps, no_ns = [], [], []
    for ln, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 3:
            print(f"    ❌ 第 {ln} 行格式不认识：{line[:60]}")
            continue
        principal = parts[0].lower()
        principals.append(principal)
        if not any(p.startswith("namespaces=") and "git" in p for p in parts[1:-2]):
            no_ns.append(f"第 {ln} 行 {principal}")
        for i, tok in enumerate(parts):
            if tok.startswith(("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-", "sk-ssh-", "sk-ecdsa-")):
                fps.append(_ssh_fp(parts[i + 1]))
                break

    # ① principal 必须在名录内
    outsider = [p for p in principals if p not in known]
    for p in outsider:
        print(f"    ❌ principal 不在名录内：{p}（签发权给了名录外的人）")
    print(f"  {'✅' if not outsider else '❌'} principal 可追溯：{len(principals) - len(outsider)}/{len(principals)}")

    # ② 必须限定 namespaces="git"
    for x in no_ns:
        print(f"    ❌ 未限定 namespaces=\"git\"：{x}")
    print(f"  {'✅' if not no_ns else '❌'} namespace 限定：{len(principals) - len(no_ns)}/{len(principals)}")

    # ③ 指纹与 CREDITS.md 一致
    md = os.path.join(root, "CREDITS.md")
    text = open(md, encoding="utf-8").read() if os.path.exists(md) else ""
    declared = {m.group(0) for m in re.finditer(r"SHA256:[A-Za-z0-9+/]{40,44}={0,2}", text)}
    only_key = sorted(set(fps) - declared)
    only_doc = sorted(declared - set(fps))
    for f in only_key:
        print(f"    ❌ 公钥在 allowed_signers 里，CREDITS.md 未记：{f}")
    for f in only_doc:
        print(f"    ❌ CREDITS.md 记了，allowed_signers 里没有这把钥：{f}")
    print(f"  指纹：allowed_signers {len(set(fps))} 把 / CREDITS.md 记 {len(declared)} 把")
    print(f"  {'✅ 一致' if set(fps) == declared and fps else '❌ 已分叉'}")
    if set(fps) != declared:
        print("  说明：验签命令照着文档敲，会验到旧钥——「Good signature」反而成了误导。")

    return not outsider and not no_ns and bool(fps) and set(fps) == declared


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
        ("R12 署名落地", rule12(root)),
        ("R13 名录两源一致", rule13(root)),
        ("R14 签名公钥", rule14(root)),
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
