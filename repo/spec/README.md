<!-- SPDX-License-Identifier: CC0-1.0 -->
<!-- Copyright 2026 老夫 <2379731846@qq.com> -->

# spec/ · 一份条目规范，一份表结构

| 文件 | 是什么 | 管什么 |
| --- | --- | --- |
| `entry.schema.json` | **条目规范**（`x-spec-version` 2.1.0，2026-11-12 合并版） | 一条账目长什么样：`give` / `receive` / `payback` 三态、同一条哈希链、**不含任何金额字段** |
| `../ddl_w4.sql` | **表结构**（SQLite，w4-ddl v1.3） | 库里怎么落地：三张 append-only 表、`party` 主体表、`v_public_party` 公开视图、触发器与错误码 |

两份文件说的是同一件事的两层：schema 管**一条记录合不合格**，DDL 管**它怎么存**。
改一处必须同步另一处，`evidence/check_spec.py` 就是用来抓这种不同步的。

## 一、2026-11-12 合并了什么

合并前是两份 schema：`ledger-entry.schema.json` 记资金（`amount_fen` **必填**），
`contribution-entry.schema.json` 记交付（明令禁止 `amount_fen`）。两份都写着「最小 schema」，
读者必须先猜自己该用哪一份——而线上只存在一套结构（三张表、三态、无金额）。
**同一份规范里并存两种必填集，本身就是缺陷**，所以合成一份。

三处取舍，写在这里，不藏在字段里：

1. **资金面整体不进本规范。** S0 阶段不启资金账，只接受实物支持（服务器、带宽、设备、场地、人力）。
   带金额的条目不是「暂未使用」，而是**校验必然失败**：`not: {required: ["amount_fen"]}`
   再加 `additionalProperties: false`，任何带 `amount_fen` 的条目都不是本规范的实例。
   这不是洁癖——如果规范允许金额，实现者就会按它做出一个带金额的账本，
   与公开页写的「账本里连金额字段都没有」直接相反。
2. **原资金设计件没有删掉，只是没并进来。** 它在 `0-snapshot/W6/repo/spec/ledger-entry.schema.json`
   （2.0-final 冻结基线）与 git 历史里，连同 `donation` / `expense` / 采购 / 配捐那一套 `kind`
   与资助集中度字段。将来要启用，那是**协议换版**：增补字段、重定锚值算法、改公开口径，
   不是在本文件里悄悄加一列。
3. **交付面的三个字段，两个没有落点。** 旧 `contribution-entry` 有 `quantity` /
   `deliverable_uri` / `evidence_uri`。`quantity` 落进了 `give` 的 `quantity` + `unit`；
   `deliverable_uri` 与 `evidence_uri` 在现行链上**没有对应列**——这是**已知缺口**，
   计划 v2.2 补，本版不假装有。所以「通过 T2 校验」的含义只有一句：
   **字段结构与实现一致**；它不代表证据可核验，也不代表东西真的交到了。

## 二、三句话说完这份规范

1. **一条链只装一种东西**：已经发生的给 — 受 — 还。金额一旦混进来，链就变成流水账，
   「账能对上」这件事随之失去意义。
2. **用 `type` 分支，不拆成三份 schema**：三态共享 10 个必填字段，拆开之后
   「哪一份才是全量」永远说不清，而合并只需要五个 `if/then`。
3. **结构约束优先于说明文字**：`scope_unresolved=1` 时 `scope` 必须为 `null`，
   由 `allOf` 强制，不靠实现自觉——让「不知道」可被审计看见，而不是被默认值藏起来。

## 三、自己验一遍

```bash
python3 evidence/build_ledger.py    # 先建库（库不在仓库里）
python3 evidence/check_spec.py      # 再用本规范校验库里每一条
```

`check_spec.py` 只用标准库，逐条报出**第一条不合规**的字段与原因，全过则打印条数并 exit 0。
它实现的是 draft 2020-12 的一个子集（`type` / `required` / `properties` /
`patternProperties` / `additionalProperties` / `enum` / `const` / `pattern` /
`minimum` / `allOf` / `anyOf` / `not` / `if-then`），**不校验 `format`**——
`date-time` 只作标注。这个限度写在脚本头部，不靠使用者猜。

## 四、许可

本目录全部 `CC0-1.0`（见 `../README.md` 的机器可读归属表；`repo_lint` 的 R5 强制 `spec/` 只能是 CC0）。
本文件同样 CC0，可任意复制、改写、商用，不需要署名。
