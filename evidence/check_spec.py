#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""check_spec.py —— 拿 repo/spec/entry.schema.json 校验账本里的每一条。

为什么要有这个脚本：2026-11-12 把两份 schema 合成一份时，如果只有文字声明
「规范与实现一致」，那就是又制造了一处「文档说 A、代码做 B」——上一轮审计
刚抓出来的那类错。所以让判据落在一个能跑、能失败、能指出第一条不合规字段的
脚本上，而不是落在措辞上。

用法：
  python3 evidence/check_spec.py                # 校验 evidence/ledger_w4.db
  python3 evidence/check_spec.py <db 路径>       # 校验指定库

退出码：0 全部合规；1 有不符条目；2 环境或文件问题。

实现的限度（写在头部是为了让使用者能自己判断可信度，而不是相信输出）：
  · 只实现 draft 2020-12 的一个子集：type / required / properties /
    patternProperties / additionalProperties / enum / const / pattern /
    minLength / minimum / maximum / allOf / anyOf / not / if-then-else / $ref。
  · **不校验 format**：date-time 只作标注，不解析。
  · 不做跨条目语义检查（链的连续性由 ledger_hash.verify_chain 负责，
    它比本脚本严格，两者都要跑）。
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHEMA = os.path.join(ROOT, "repo", "spec", "entry.schema.json")
DEFAULT_DB = os.path.join(HERE, "ledger_w4.db")


def _is_type(inst, want: str) -> bool:
    if want == "object":
        return isinstance(inst, dict)
    if want == "array":
        return isinstance(inst, list)
    if want == "string":
        return isinstance(inst, str)
    if want == "boolean":
        return isinstance(inst, bool)
    if want == "null":
        return inst is None
    if want in ("number", "integer"):
        # bool 在 Python 里是 int 的子类：不排掉会把 true 当成 1 通过
        if isinstance(inst, bool) or not isinstance(inst, (int, float)):
            return False
        return True if want == "number" else float(inst).is_integer()
    return True


def _same(a, b) -> bool:
    """枚举比较要区分 1 与 true：JSON 里它们是两个值。"""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    return a == b


def _resolve(schema, root):
    """只支持本地 #/$defs/... 形式的 $ref；指到别处直接报错，不静默放过。"""
    ref = schema["$ref"]
    if not ref.startswith("#/"):
        raise ValueError(f"仅支持本地 $ref，遇到 {ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(inst, schema, root, path="$", errs=None):
    """返回错误列表 [(路径, 说明)]。空列表 = 合规。"""
    if errs is None:
        errs = []
    if schema is True or schema == {}:
        return errs
    if "$ref" in schema:
        return validate(inst, _resolve(schema, root), root, path, errs)

    if "type" in schema:
        want = schema["type"]
        wants = want if isinstance(want, list) else [want]
        if not any(_is_type(inst, w) for w in wants):
            errs.append((path, f"类型应为 {want}，实际是 {type(inst).__name__}"))
            return errs  # 类型已经不对，后续关键字检查没有意义

    if "const" in schema and not _same(inst, schema["const"]):
        errs.append((path, f"应为常量 {schema['const']!r}，实际 {inst!r}"))

    if "enum" in schema and not any(_same(inst, v) for v in schema["enum"]):
        errs.append((path, f"应为 {schema['enum']} 之一，实际 {inst!r}"))

    if isinstance(inst, str):
        if "pattern" in schema and not re.search(schema["pattern"], inst):
            errs.append((path, f"不匹配 {schema['pattern']}：{inst!r}"))
        if "minLength" in schema and len(inst) < schema["minLength"]:
            errs.append((path, f"长度 {len(inst)} 小于 {schema['minLength']}"))

    if isinstance(inst, (int, float)) and not isinstance(inst, bool):
        if "minimum" in schema and inst < schema["minimum"]:
            errs.append((path, f"{inst} 小于最小值 {schema['minimum']}"))
        if "maximum" in schema and inst > schema["maximum"]:
            errs.append((path, f"{inst} 大于最大值 {schema['maximum']}"))

    if isinstance(inst, dict):
        for key in schema.get("required", []):
            if key not in inst:
                errs.append((path, f"缺必填字段 {key}"))
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for key, value in inst.items():
            if key in props:
                validate(value, props[key], root, f"{path}.{key}", errs)
                continue
            matched = False
            for pat, sub in patterns.items():
                if re.search(pat, key):
                    validate(value, sub, root, f"{path}.{key}", errs)
                    matched = True
            if matched:
                continue
            extra = schema.get("additionalProperties", True)
            if extra is False:
                errs.append((path, f"不允许的字段 {key}（既不在 properties，也不匹配 x- 前缀）"))
            elif isinstance(extra, dict):
                validate(value, extra, root, f"{path}.{key}", errs)

    for sub in schema.get("allOf", []):
        validate(inst, sub, root, path, errs)

    if "anyOf" in schema:
        # anyOf 判「至少一项通过」；上一版把条件写反，导致
        # 「receive 混入 give 字段」这类本该被拒的条目静默通过——反向用例抓出来的。
        for sub in schema["anyOf"]:
            if not validate(inst, sub, root, path, []):
                break
        else:
            errs.append((path, "不满足 anyOf 的任一项"))

    if "not" in schema:
        if not validate(inst, schema["not"], root, path, []):
            errs.append((path, "命中了规范禁止的形态（not 分支：如带金额、或 receive/payback 混入 give 字段）"))

    if "if" in schema:
        if not validate(inst, schema["if"], root, path, []):
            if "then" in schema:
                validate(inst, schema["then"], root, path, errs)
        elif "else" in schema:
            validate(inst, schema["else"], root, path, errs)

    return errs


def load_chain(db_path: str) -> list[dict]:
    """复用公开服务的那套载入 + 建链逻辑：校验的对象就是线上输出的那一条条。"""
    sys.path.insert(0, os.path.join(ROOT, "repo", "deploy", "app"))
    os.environ["LEDGER_DB"] = db_path
    import app  # noqa: E402  （必须等 sys.path / 环境变量就位）
    return app.Ledger(db_path).chain


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB
    if not os.path.exists(SCHEMA):
        print(f"FAIL 找不到规范文件 {SCHEMA}", file=sys.stderr)
        return 2
    if not os.path.exists(db):
        print(f"FAIL 找不到账本库 {db}；先跑 python3 evidence/build_ledger.py", file=sys.stderr)
        return 2
    with open(SCHEMA, encoding="utf-8") as fh:
        schema = json.load(fh)

    chain = load_chain(db)
    bad = 0
    for i, entry in enumerate(chain):
        errs = validate(entry, schema, schema)
        if errs:
            bad += 1
            print(f"FAIL 第 {i} 条 {entry.get('type')}:{entry.get('entry_id')} —— {len(errs)} 处不合规")
            for path, msg in errs[:3]:
                print(f"     {path}: {msg}")
    if bad:
        print(f"\n{bad}/{len(chain)} 条不合规；规范 = {os.path.relpath(SCHEMA, ROOT)}")
        return 1

    print(f"check_spec OK: {len(chain)} 条全部符合 repo/spec/entry.schema.json"
          f"（x-spec-version {schema.get('x-spec-version')}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
