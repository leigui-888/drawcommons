#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""regen_manifest.py —— 重算并校验 MANIFEST（0-snapshot 5 份 35 件 + 仓库根 1 份 16 件）。

判据（开工清单 §7 C0）：干净目录 clone 后两条命令即可复现：
  1) python3 evidence/build_ledger.py     -> exit 0（六次攻击全被拒）
  2) python3 evidence/regen_manifest.py   -> 0-snapshot 35/35、仓库根 16/16，exit 0

口径（沿用各 MANIFEST 头部，2026-11-08 按审查 P2-06 重排）：
  · 代码/数据取节点原始字节，全量入表，强制校验；
  · 文档单列于注释区，不参与 sha256 校验（导出件字节随编辑变化，纳入只会制造假失败）。
  本脚本只动强制校验行，注释区原样保留。

用法：
  python3 evidence/regen_manifest.py                # 离线：重算 + 校验（默认）
  python3 evidence/regen_manifest.py --check        # 只校验，不改写
  python3 evidence/regen_manifest.py --week W4      # 只处理 0-snapshot 的某一周
  python3 evidence/regen_manifest.py --no-root      # 不处理仓库根 MANIFEST
  python3 evidence/regen_manifest.py --fetch        # 先用本地资料库技能重新导出，再重算校验
  python3 evidence/regen_manifest.py --fetch --skill-dir "/path/to/skills/library"

--fetch 的边界：它调用的是**本机**的 library 技能（export_node.py），凭据留在本机技能里，
不进仓库、不读仓库内任何 token。独立复现者没有该技能也能跑默认模式——这正是判据所需要的。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

WEEKS = ("W3", "W4", "W5", "W6", "W7")
ENTRY_RE = re.compile(r"^([0-9a-f]{64}) \*(.+)$")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(REPO_ROOT, "0-snapshot")
NODES_TSV = os.path.join(REPO_ROOT, "evidence", "nodes.tsv")
DEFAULT_SKILL_DIR = os.environ.get("KS_SKILL_DIR", "")


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def read_manifest(path: str):
    """返回 (行列表, [(行号, 记录指纹, 相对路径)])。"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    entries = []
    for i, line in enumerate(lines):
        m = ENTRY_RE.match(line)
        if m:
            entries.append((i, m.group(1), m.group(2)))
    return lines, entries


def process(label: str, base: str, mpath: str, check_only: bool, rows: list):
    """重算并（非 check 时）改写一份 MANIFEST；把未通过项追加进 rows。返回 (ok, total)。"""
    lines, entries = read_manifest(mpath)
    ok = 0
    rewritten = 0
    for idx, want, rel in entries:
        p = os.path.join(base, rel)
        if not os.path.isfile(p):
            rows.append((label, rel, "缺文件", want[:12], "-"))
            continue
        got = sha256_of(p)
        if got == want:
            ok += 1
            continue
        rows.append((label, rel, "指纹不符", want[:12], got[:12]))
        if not check_only:
            lines[idx] = f"{got} *{rel}"
            rewritten += 1
    if rewritten:
        with open(mpath, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines))
        # 写回后按最终状态重新校验：exit code 必须反映磁盘上的真实结果
        lines, entries = read_manifest(mpath)
        rows[:] = [r for r in rows if r[0] != label]
        ok = 0
        for idx, want, rel in entries:
            p = os.path.join(base, rel)
            if not os.path.isfile(p):
                rows.append((label, rel, "缺文件", want[:12], "-"))
                continue
            got = sha256_of(p)
            if got == want:
                ok += 1
            else:
                rows.append((label, rel, "写回后仍不符", want[:12], got[:12]))
        print(f"  {label}: {ok}/{len(entries)}（已改写 {rewritten} 条指纹）")
    else:
        print(f"  {label}: {ok}/{len(entries)}")
    return ok, len(entries)


def fetch_one(node_id: str, skill_dir: str, dest: str) -> None:
    """用本地 library 技能导出单节点，落到 dest。"""
    script = os.path.join(skill_dir, "export", "export_node.py")
    if not os.path.isfile(script):
        raise SystemExit(f"找不到导出脚本：{script}\n用 --skill-dir 指定 library 技能目录，或设 KS_SKILL_DIR。")
    tmp = tempfile.mkdtemp(prefix="regen_")
    try:
        subprocess.run([sys.executable, script, "--node-id", node_id, "--out", tmp],
                       cwd=skill_dir, check=True, capture_output=True, text=True)
        produced = [os.path.join(tmp, n) for n in os.listdir(tmp)]
        if len(produced) != 1:
            raise RuntimeError(f"节点 {node_id} 导出得到 {len(produced)} 个文件，预期 1 个")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.move(produced[0], dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_nodes():
    """nodes.tsv: week<TAB>relpath<TAB>node_id[<TAB>备注]"""
    if not os.path.isfile(NODES_TSV):
        raise SystemExit(f"缺少 {NODES_TSV}，--fetch 需要它做路径→节点映射。")
    out = []
    with open(NODES_TSV, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                out.append((parts[0], parts[1], parts[2]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验，不改写 MANIFEST")
    ap.add_argument("--fetch", action="store_true", help="先用本地技能重新导出，再重算校验")
    ap.add_argument("--week", action="append", choices=WEEKS, help="限定周，可重复")
    ap.add_argument("--no-root", action="store_true", help="不处理仓库根 MANIFEST")
    ap.add_argument("--skill-dir", default=DEFAULT_SKILL_DIR, help="library 技能目录（--fetch 用）")
    args = ap.parse_args()

    weeks = tuple(args.week) if args.week else WEEKS

    if args.fetch:
        if not args.skill_dir:
            raise SystemExit("--fetch 需要 --skill-dir（或环境变量 KS_SKILL_DIR）指向 library 技能目录。")
        todo = [r for r in load_nodes() if r[0] in weeks]
        print(f"[fetch] 重新导出 {len(todo)} 件节点 …")
        for i, (week, rel, node_id) in enumerate(todo, 1):
            dest = os.path.join(SNAPSHOT, week, rel)
            fetch_one(node_id, args.skill_dir, dest)
            print(f"  [{i}/{len(todo)}] {week}/{rel}  <- {node_id}")

    rows: list = []
    snap_ok = snap_total = 0
    for week in weeks:
        mpath = os.path.join(SNAPSHOT, week, "MANIFEST")
        if not os.path.isfile(mpath):
            print(f"! {week}: 缺 MANIFEST（{mpath}）")
            return 2
        ok, total = process(f"  {week}", os.path.join(SNAPSHOT, week), mpath, args.check, rows)
        snap_ok += ok
        snap_total += total

    root_ok = root_total = 0
    root_mp = os.path.join(REPO_ROOT, "MANIFEST")
    if not args.no_root and os.path.isfile(root_mp):
        root_ok, root_total = process("repo/MANIFEST", REPO_ROOT, root_mp, args.check, rows)

    print()
    print(f"0-snapshot MANIFEST 校验：{snap_ok}/{snap_total} 通过")
    if root_total:
        print(f"仓库根 MANIFEST 校验：{root_ok}/{root_total} 通过")

    if rows:
        bad = len(rows)
        print(f"\n未通过 {bad} 项" + ("（--check 模式未改写；去掉 --check 会按本地字节重算）" if args.check else ""))
        print("\n未通过明细：")
        for label, rel, why, want, got in rows:
            print(f"  {label:14s} {rel:52s} {why:6s} 记录={want} 实测={got}")
        return 1

    print("\n复现判据：" + f"{snap_ok}/{snap_total}"
          + (f"（0-snapshot）+ {root_ok}/{root_total}（仓库根）" if root_total else "")
          + " —— 与 MANIFEST 记录完全一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
