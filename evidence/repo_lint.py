#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""仓库许可体检：G5′ 许可门的机器可验部分。

十六条规则，每条给一个数。规则不是为了"看起来严谨"，是为了回答一个具体问题：
**一个陌生人 clone 下来，能不能仅凭仓库里的文件判断"这个文件我能不能用"，以及
"谁做的、能不能找到他"。**

R1–R10 的视野是 `repo/`（授权树）。R11 补的是 `repo/` 之外那一层：根 `spec/`
与 `evidence/`。它们同样被 git 跟踪、同样随 clone 公开，却不在任何规则视野内——
R4 只遍历 `repo/`，所以这两个目录的文件此前从未被检查过是否可被判断许可。

R12/R13 换了个问题：许可说得清「能不能用」，说不清「这是谁做的」。署名承诺若只写在
CONTRIBUTING 里，就是一句没有对象的话——没有名录可查、没有依据可验、被删了也无人知道。
R12 把名录接回 git 记录（不漏记、不虚构、依据可查），R13 卡住名录的两份表示不许分叉。

R14 再进一步：名录说「谁做了它」，签名说「这个版本是谁发的」。二者都靠「同一事实写在
两处」来防单点改动——R14 比对公钥指纹与 CREDITS.md §10 的记载，并核对签发权（谁能签
v* tag）与名录双向对齐、一人一钥。它防不了「两份一起改」，那条只能靠仓库外的指纹分发
渠道，故规则输出里把这一点直接印出来，不假装覆盖了。

R15 是 R14 的下半截：tag 签名只覆盖「发布」这一个动作，覆盖不到里面每个提交。commit 的
author 字段是自由填写的，谁都能写别人的名字；一旦有人开始签名，就得查签名者是不是作者
本人——否则「Good signature」会替一次冒名作证。未签名的提交只统计不判红（补签要改写历史）。

R16 补的是中间那一层：不逐条签，但也不能「提交了就算贡献」。一条提交要先被审（REVIEWS.md
+ reviews.json），审出确实有贡献才进名录依据；作者不是有发布权的人，那条提交就必须有审查
记录。它查五件事：审阅人有没有发布权、依据的提交存不存在、有没有把基线之后再审一遍、
审过的人有没有真的进名录、记录的两份表示有没有分叉。**审查与署名之间那道焊缝由它焊死。**

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
    """git 的文件清单（含未跟踪、未被忽略的）；无 git 时退回文件系统遍历。

    2026-11-12 加 `--others --exclude-standard`：只查 `ls-files` 时，新建但未
    `git add` 的文件不在清单里，R3/R4/R5 会**静默漏检并报绿**——实测过：
    新增一份 schema 后 R4 从 9/9 变成 7/7，仍然全绿。覆盖率这件事不能只数
    「我记得要检查的那些」。
    """
    try:
        out = subprocess.run(
            ["git", "-C", root, "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True, text=True, check=True,
        ).stdout
        files = [l for l in out.splitlines() if l.strip()]
        if files:
            return files, "git ls-files（含未跟踪）"
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


# 每份许可的「完整正文」判据：必须同时命中下列全部条款特征，缺一条即不算全文。
# 取的是正文里的结构标题，只有一句 URL 的指针件不可能命中。
#
# 为什么不用长度阈值：CC0 的全文只有 7,048 字节，比 CC-BY 的指针说明件还短；
# 旧的「>12000 字节且含 legalcode」判据会把最完整的那份判成残缺，把只贴了
# 半页条款的假全文判成合格。长度是相关量，不是判据。
LICENSE_SIGNS = {
    "Apache-2.0": ([r"Apache License", r"TERMS AND CONDITIONS",
                    r"END OF TERMS AND CONDITIONS"], 8000),
    "CC-BY-4.0": ([r"Creative Commons Attribution 4\.0 International Public License",
                   r"Section 1 .{0,3} Definitions",
                   r"Section 8 .{0,3} Interpretation"], 12000),
    "CC-BY-SA-4.0": ([r"Creative Commons Attribution-ShareAlike 4\.0 International Public License",
                      r"Section 1 .{0,3} Definitions",
                      r"Section 3 .{0,3} License Conditions"], 12000),
    "CC0-1.0": ([r"CC0 1\.0 Universal", r"Statement of Purpose", r"2\. Waiver"], 6000),
}


def rule2(root):
    sec("R2 许可文本完整度（全文 vs 指针）")
    # 候选面：根目录的 LICENSE*，以及 licenses/ 下的全部文件（正文与说明分置两处）
    cands = []
    for d, only_prefix in ((root, "LICENSE"), (os.path.join(root, "licenses"), "")):
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d)):
            p = os.path.join(d, f)
            if not os.path.isfile(p) or (only_prefix and not f.startswith(only_prefix)):
                continue
            cands.append(os.path.relpath(p, root).replace(os.sep, "/"))

    texts = {}
    for rel in cands:
        try:
            texts[rel] = open(os.path.join(root, rel), encoding="utf-8", errors="ignore").read()
        except OSError:
            pass

    found = {}
    for spdx, (signs, min_bytes) in LICENSE_SIGNS.items():
        hit = None
        for rel, t in texts.items():
            if len(t.encode("utf-8")) < min_bytes:
                continue
            if all(re.search(s, t) for s in signs):
                hit = rel
                break
        found[spdx] = hit
        if hit:
            n = len(texts[hit].encode("utf-8"))
            print(f"  ✅ 全文  {spdx:14} ← {hit}（{n:,} 字节）")
        else:
            print(f"  ❌ 缺全文 {spdx:14} 无文件同时命中 {len(signs)} 条条款特征")

    # 指针自述：提到官方 legalcode，却既不附正文、也不指向本地全文
    stubs = []
    for rel, t in texts.items():
        if rel in found.values() or "legalcode" not in t or "licenses/" in t:
            continue
        stubs.append(rel)
    for s in stubs:
        print(f"  ⚠️ 指针  {s}（提到 legalcode，既无正文也未指向 licenses/）")

    miss = [k for k, v in found.items() if not v]
    ok = len(LICENSE_SIGNS) - len(miss)
    print(f"  结果：{len(LICENSE_SIGNS)} 份许可，全文 {ok}，缺 {len(miss)}，指针自述 {len(stubs)}")
    if miss:
        print("  说明：缺全文使「仓库自带完整条款」不成立——离线或链接失效时使用者拿不到原文。")
        print("        补齐动作为下载官方文本，非撰写；见 _ops/build_license_texts.py。")
    return not miss and not stubs


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
    ok = source.startswith("git ls-files")
    print(f"  {'✅' if ok else '⚠️'} "
          f"{'可被第三方用同一条命令复现（git ls-files --cached --others --exclude-standard）' if ok else '非 git 清单，外部无法逐字节复现'}")
    return ok


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
    md_rel = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 3:
            md.add((cells[0], cells[1], cells[2].lower()))
            md_rel[cells[0]] = len(cells) >= 4 and cells[3].lower() == "release"

    js = {(x.get("id", ""), x.get("name", ""), x.get("email", "").lower())
          for x in (data.get("people") or [])}
    js_rel = {x.get("id", ""): bool(x.get("can_release")) for x in (data.get("people") or [])}

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

    # 发布权（第 4 格写 release）也要两边一致：R14 拿 json 的 can_release 判签发权，
    # 若 md 写着「仅某人可发布」而 json 另授了人，对外承诺与机器判定就分叉了。
    rel_diff = sorted({k for k in set(md_rel) | set(js_rel) if md_rel.get(k) != js_rel.get(k)})
    for k in rel_diff:
        print(f"    ❌ 发布权两处不一致：{k}（md {'有' if md_rel.get(k) else '无'} / json {'有' if js_rel.get(k) else '无'}）")
    print(f"  {'✅' if not rel_diff else '❌'} 发布权记载一致：{len(js_rel) - len(rel_diff)}/{len(js_rel)}")

    return md == js and not rel_diff


def _ssh_fp(b64):
    """按 `ssh-keygen -l` 的算法算指纹：对 base64 解码后的公钥 blob 做 sha256。"""
    blob = base64.b64decode(b64)
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def rule14(root):
    """R14：签名公钥、签发权与它们的记载，三处不能分叉。

    换了密钥却忘了改文档，是这类机制最常见的失效方式：验签命令照着文档敲，
    报「Good signature」——签的是旧钥，而读者以为验的是当前发布。所以

      ① `allowed_signers` 里的 principal 必须是名录里的人（否则把签发权给了名录外的人）；
      ② 每行钥匙必须限定 `namespaces="git"`（不限定，同一把钥还能签 SSH 证书，
         签名语义从「这是发布」扩散成「这是我签的一切」）；
      ③ 公钥指纹必须与 `CREDITS.md` §10 写的指纹完全相同（两处记载，一处改一处没改即红）；
      ④ 签发权与名录双向对齐：`can_release` 为真的人必须有钥，有钥的人必须 `can_release`。
         只查 ① 的话，加一行钥就等于给了发布权，而名录里看不出来——签发权被悄悄扩大
         是这类机制最安静的失效；
      ⑤ 同一把公钥不得出现两次。两人共用一把钥，验签只能证明「钥的持有人之一」，
         分不出是谁签的，署名权在那一刻就落不到具体的人头上。

    第 ③ 条有个天然局限，必须说清：`allowed_signers` 在仓库里，能改仓库的人也能改它。
    本规则只能防「自己人改漏」，防不了「有人把两份一起改掉」。后者只能靠仓库外的
    指纹分发渠道（见 CREDITS.md §10.3）。

    第 ③ 条有个天然局限，必须说清：`allowed_signers` 在仓库里，能改仓库的人也能改它。
    本规则只能防「自己人改漏」，防不了「有人把两份一起改掉」。后者只能靠仓库外的
    指纹分发渠道（见 CREDITS.md §10.3）。
    """
    sec("R14 签名公钥与签发权")
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

    principals, fps, no_ns, pairs = [], [], [], []
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
        fp = None
        for i, tok in enumerate(parts):
            if tok.startswith(("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-", "sk-ssh-", "sk-ecdsa-")):
                fp = _ssh_fp(parts[i + 1])
                fps.append(fp)
                break
        pairs.append((principal, fp, ln))

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

    # ④ 签发权 ↔ 名录，双向对齐
    ok4 = True
    if data is None:
        print("  · 跳过签发权核对：名录无法解析（不计入分母）")
    else:
        by_email = {}
        releasers = []
        for p in data.get("people") or []:
            pid = p.get("id") or p.get("name", "?")
            if p.get("can_release"):
                releasers.append(pid)
            for e in _person_emails(p):
                by_email[e] = pid
        have_key = {by_email[p] for p, _, _ in pairs if p in by_email}
        no_key = [r for r in releasers if r not in have_key]
        for r in no_key:
            print(f"    ❌ 名录给了发布权、却没有签名钥：{r}（「能发布」成了一句空话）")
        print(f"  {'✅' if not no_key else '❌'} 有发布权的人都有钥：{len(releasers) - len(no_key)}/{len(releasers)}")

        overreach = sorted({p for p, _, _ in pairs if p in by_email and by_email[p] not in releasers})
        for p in overreach:
            print(f"    ❌ 有钥、名录未授予发布权：{p}（加一行钥就等于给了发布权，名录里看不出来）")
        print(f"  {'✅' if not overreach else '❌'} 有钥的人都列在发布权内：{len(pairs) - len(overreach)}/{len(pairs)}")
        ok4 = not no_key and not overreach

    # ⑤ 一把钥只能对应一个人
    seen = {}
    for p, fp, ln in pairs:
        if fp:
            seen.setdefault(fp, []).append(f"{p}(第{ln}行)")
    shared = {fp: who for fp, who in seen.items() if len(who) > 1}
    for fp, who in shared.items():
        print(f"    ❌ 同一把公钥出现 {len(who)} 次：{fp[:28]}… → {'、'.join(who)}")
        print("       共用钥无法区分谁签的；署名权在那一刻落不到具体的人头上。")
    print(f"  {'✅' if not shared else '❌'} 一钥一人：{len(seen) - len(shared)}/{len(seen)}")

    return (not outsider and not no_ns and bool(fps)
            and set(fps) == declared and ok4 and not shared)


def rule15(root):
    """R15：签了名的提交，签名者必须就是作者本人。

    签名 tag 只回答「这次发布是谁发的」，回答不了「每个提交是谁写的」——commit 的
    author 字段是自由填写的，谁都能写成别人的名字。所以一旦有人开始签名，就得查两件事：

      ① 签名本身验得过。坏签名比没签名糟得多，因为它看起来「有保障」；
      ② 签名者 principal 属于该作者登记过的邮箱。拿自己的钥去签别人的提交，验签会报
         「Good signature for 自己」——这正是要抓的冒名，也是这条规则存在的唯一理由。

    未签名的提交只统计、不判红：历史既成事实，补签要改写历史，代价大于收益（见
    CREDITS.md §10.4）。所以这条规则在新人加入后才真正开始起作用：他签一个，就锁一个。
    """
    sec("R15 提交签名与作者身份")
    top = os.path.dirname(root)
    if not os.path.isdir(os.path.join(top, ".git")):
        print("  · 不适用：repo/ 的上级不是 git 仓库（不计入分母）")
        return None

    data = _load_credits(root) or {}
    asf = os.path.join(root, "allowed_signers")
    if not os.path.exists(asf):
        print("  ❌ 无 allowed_signers：提交签名无从核对")
        return False

    # 邮箱 → 人。机器账号（accounts 段）按 attribution 里写的权利人折算。
    people = {p.get("id") or p.get("name", "?"): p for p in data.get("people") or []}
    by_email = {}
    for pid, p in people.items():
        for e in _person_emails(p):
            by_email[e] = pid
    for a in data.get("accounts") or []:
        e = (a.get("email") or "").lower()
        m = re.search(r"[\w.+-]+@[\w.-]+", a.get("attribution") or "")
        if e and m and m.group(0).lower() in by_email:
            by_email[e] = by_email[m.group(0).lower()]

    try:
        out = subprocess.run(
            ["git", "-C", top,
             "-c", "gpg.format=ssh",
             "-c", f"gpg.ssh.allowedSignersFile={asf}",
             "log", "--format=%H%x1f%ae%x1f%G?%x1f%GS"],
            capture_output=True, text=True, check=True).stdout
    except Exception:  # noqa: BLE001
        print("  ❌ git log 失败：无法核对提交签名")
        return False

    total = signed = 0
    bad, impostor = [], []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split("\x1f")
        if len(parts) < 4:
            continue
        sha, ae, st, signer = parts[0], parts[1].strip().lower(), parts[2].strip(), parts[3].strip().lower()
        total += 1
        if st == "N":
            continue
        signed += 1
        if st != "G":
            bad.append((sha[:7], st))
            continue
        pid = by_email.get(ae)
        if pid is None:
            continue  # 未登记作者由 R12 判，此处不重复计红
        if signer not in _person_emails(people.get(pid, {})):
            impostor.append((sha[:7], ae, pid, signer))

    for sha, st in bad[:10]:
        why = {"U": "签名完好但钥未登记（%G?=U）",
               "B": "签名损坏（%G?=B）",
               "E": "无法校验（%G?=E）",
               "X": "钥已过期（%G?=X）",
               "Y": "钥已过期（%G?=Y）",
               "R": "钥已吊销（%G?=R）"}.get(st, f"%G?={st}")
        print(f"    ❌ {why}：{sha}")
    print(f"  {'✅' if not bad else '❌'} 已签名提交验得过：{signed - len(bad)}/{signed}")

    for sha, ae, pid, signer in impostor[:10]:
        print(f"    ❌ 冒名：{sha} 作者 {ae}（名录 {pid}），却由 {signer} 的钥签发")
    print(f"  {'✅' if not impostor else '❌'} 签名者=作者：{signed - len(bad) - len(impostor)}/{max(signed - len(bad), 0)}")

    print(f"  · 提交总数 {total}，其中已签名 {signed}、未签名 {total - signed}")
    print("    未签名不判红：历史补签要改写提交，毁掉的是原有的可核验性。")
    return not bad and not impostor


def _email_pid(data):
    """邮箱 → 人名录 id。机器账号按 attribution 里写的权利人折算（与 R15 同口径）。"""
    by = {}
    for p in data.get("people") or []:
        pid = p.get("id") or p.get("name", "?")
        for e in _person_emails(p):
            by[e] = pid
    for a in data.get("accounts") or []:
        e = (a.get("email") or "").lower()
        m = re.search(r"[\w.+-]+@[\w.-]+", a.get("attribution") or "")
        if e and m and m.group(0).lower() in by:
            by[e] = by[m.group(0).lower()]
    return by


def rule16(root):
    """R16：审查记录 —— 谁凭什么被记进名录。

    不给每条提交签名，就要有另一层回答「凭什么算他的贡献」。这一层是审查记录，它防的是
    两种相反的错误，两种都真实发生过：

      ① **不审就记**：把提交一律算成贡献，名录变成提交列表。垃圾提交也能主张署名权，
         将来真要删掉一个，反而说不清「当初凭什么收的」。
      ② **审了不记**：口头说「这条算他的」，名录里没有，一年后查无此事。承诺没落纸就不是承诺。

    查六件事：审阅人有没有发布权（没发布权的人给别人的贡献作保，自己也还没被认过）；
    记录指向的提交存不存在、前缀唯不唯一；有没有把基线已覆盖的提交再审一遍（让基线形同虚设）；
    `accept` 的人有没有真的进名录依据（审查与署名之间的焊缝）；基线之后作者不是发布权人的
    提交有没有审查记录；`REVIEWS.md` 与 `reviews.json` 两份表示有没有分叉。
    """
    sec("R16 审查记录：谁凭什么被记进名录")
    top = os.path.dirname(root)
    if not os.path.isdir(os.path.join(top, ".git")):
        print("  · 不适用：repo/ 的上级不是 git 仓库（不计入分母）")
        return None

    jp = os.path.join(root, "reviews.json")
    mp = os.path.join(root, "REVIEWS.md")
    if not (os.path.exists(jp) and os.path.exists(mp)):
        print("  ❌ 缺 reviews.json 或 REVIEWS.md：审查记录无从核对")
        return False
    try:
        data = json.load(open(jp, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"  ❌ reviews.json 解析失败：{e}")
        return False

    credits = _load_credits(root) or {}
    people = {p.get("id") or p.get("name", "?"): p for p in credits.get("people") or []}
    releasers = {k for k, v in people.items() if v.get("can_release")}
    by_email = _email_pid(credits)

    try:
        allc = subprocess.run(["git", "-C", top, "rev-list", "--all"],
                              capture_output=True, text=True, check=True).stdout.split()
    except Exception:  # noqa: BLE001
        print("  ❌ git rev-list 失败：无法核对审查记录指向的提交")
        return False

    def resolve(prefix):
        p = (prefix or "").strip().lower()
        if len(p) < 7:
            return None, "前缀短于 7 位"
        hits = [c for c in allc if c.startswith(p)]
        if not hits:
            return None, "git 里没有这个提交"
        if len(hits) > 1:
            return None, f"前缀不唯一（{len(hits)} 个候选）"
        return hits[0], ""

    bad = []

    def fail(msg):
        """记一条失败并立刻打印。只汇总不指名，等于让人自己猜是哪条错了。

        函数名不能叫 err：下面 `sha, err = resolve(...)` 会把它覆盖成字符串，
        再调用就是 TypeError，而异常被 subprocess 的 stderr 吞掉，表现为
        「体检静默通过」。这个名字是踩过一次才改的。
        """
        bad.append(msg)
        print(f"    ❌ {msg}")

    # ① 基线：指向的提交存在、审阅人有发布权、声称的条数与 git 实际一致
    base = data.get("baseline") or {}
    bsha, berr = resolve(base.get("commits_up_to") or "")
    if berr:
        fail(f"基线 commits_up_to 无效（{base.get('commits_up_to')}）：{berr}")
    if (base.get("reviewer") or "") not in releasers:
        fail(f"基线审阅人「{base.get('reviewer')}」没有发布权（can_release）")
    if bsha:
        real = int(subprocess.run(["git", "-C", top, "rev-list", "--count", bsha],
                                  capture_output=True, text=True).stdout.strip() or 0)
        if base.get("count") != real:
            fail(f"基线声称 {base.get('count')} 条，git 实为 {real} 条")
    print(f"  {'✅' if not [b for b in bad if b.startswith('基线')] else '❌'} "
          f"基线 {(bsha or '?')[:7]}："
          f"{base.get('count')} 条提交，审阅人 {base.get('reviewer')}")

    # ② 逐条记录
    revs = data.get("reviews") or []
    seen, accepted = {}, []
    for i, r in enumerate(revs, 1):
        sha, err = resolve(r.get("sha") or "")
        who = r.get("author") or ""
        rv = r.get("reviewer") or ""
        vd = r.get("verdict") or ""
        tag = f"第 {i} 条（{(r.get('sha') or '?')[:7]}）"
        if err:
            fail(f"{tag} 提交无效：{err}")
            continue
        if vd not in ("accept", "reject"):
            fail(f"{tag} verdict 只能是 accept/reject，实为「{vd}」")
        if rv not in releasers:
            fail(f"{tag} 审阅人「{rv}」没有发布权")
        if who not in people:
            fail(f"{tag} 作者「{who}」不在名录里")
        if sha in seen:
            fail(f"{tag} 与第 {seen[sha]} 条指向同一提交：分不清以哪条为准")
        seen[sha] = i
        if bsha and subprocess.run(["git", "-C", top, "merge-base", "--is-ancestor", sha, bsha],
                                   capture_output=True).returncode == 0:
            fail(f"{tag} 已被基线覆盖，再审一遍会让基线失去意义")
        if vd == "accept":
            accepted.append(sha)
            ev = [c.lower() for c in ((people.get(who) or {}).get("evidence") or {}).get("commits") or []]
            if not any(sha.startswith(e) or e.startswith(sha[:7]) for e in ev):
                fail(f"{tag} 判了 accept，但 {who} 的 evidence.commits 里没有它——审了没进名录")
    print(f"  {'✅' if not [b for b in bad if b.startswith('第')] else '❌'} "
          f"记录条目：{len(revs)} 条，其中 accept {len(accepted)} 条")

    # ③ 基线之后：作者不是发布权人 → 必须有审查记录
    unreviewed = []
    if bsha:
        out = subprocess.run(["git", "-C", top, "log", "--format=%H%x1f%ae", f"{bsha}..HEAD"],
                             capture_output=True, text=True).stdout
        for line in out.splitlines():
            if not line.strip():
                continue
            sha, ae = (line.split("\x1f") + [""])[:2]
            pid = by_email.get(ae.strip().lower())
            if pid in releasers:
                continue          # 有发布权的人自己提交，不存在「谁审谁」的问题
            if sha not in seen:
                unreviewed.append((sha[:7], ae.strip(), pid or "未登记"))
    for sha, ae, pid in unreviewed:
        fail(f"未审提交：{sha} 作者 {ae}（名录 {pid}）")
    print(f"  {'✅' if not unreviewed else '❌'} 基线之后的外部提交均已审："
          f"{'—' if not unreviewed else f'{len(unreviewed)} 条未审'}")

    # ④ 两份表示不许分叉（与 R13 同一思路：同一事实写两处，只改一处即红）
    md_rows = []
    in_tbl = False
    try:
        lines = open(mp, encoding="utf-8").read().splitlines()
    except OSError:
        lines = []
    for ln in lines:
        if ln.startswith("## 7."):
            in_tbl = True
            continue
        if in_tbl and ln.startswith("## "):
            break
        if not (in_tbl and ln.strip().startswith("|")):
            continue
        cells = [c.strip().strip("`").strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) < 5 or cells[0] == "提交" or set(cells[0]) <= set("- "):
            continue
        if "基线" in cells[0]:
            continue                      # 基线用范围表达，不占条目
        md_rows.append((cells[0], cells[1], cells[2], cells[4]))
    js_rows = [((r.get("sha") or "").strip().lower(), r.get("author") or "",
                r.get("reviewer") or "", r.get("verdict") or "") for r in revs]
    print(f"  记录数：md {len(md_rows)} / json {len(js_rows)}")
    same = sorted(md_rows) == sorted(js_rows)
    if not same:
        only_md = [r for r in md_rows if r not in js_rows]
        only_js = [r for r in js_rows if r not in md_rows]
        for r in only_md[:5]:
            print(f"    ❌ 只在 REVIEWS.md 里：{r}")
        for r in only_js[:5]:
            print(f"    ❌ 只在 reviews.json 里：{r}")
        fail("REVIEWS.md 与 reviews.json 记录集分叉")
    print(f"  {'✅ 一致' if same else '❌ 已分叉'}")

    if bad:
        print("  说明：审查记录是「凭什么记他」的唯一答案。它一旦与 git 或与名录脱钩，")
        print("        名录里那句署名就退回成一句客气话。")
    return not bad


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
        ("R14 签名公钥与签发权", rule14(root)),
        ("R15 提交签名与作者身份", rule15(root)),
        ("R16 审查记录", rule16(root)),
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
