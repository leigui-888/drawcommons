<!-- SPDX-License-Identifier: CC0-1.0 -->
<!-- Copyright 2026 老夫 <2379731846@qq.com> -->

# spec/ · 规范与表结构

| 文件 | 是什么 | 管什么 |
| --- | --- | --- |
| `entry.schema.json` | **条目规范**（`x-spec-version` 2.2.0-draft.1，r6 出件时定稿为 2.2.0） | 一条账目长什么样：`give` / `receive` / `payback` 三态、同一条哈希链、**不含任何金额字段** |
| `request.schema.json` | **需求单规范**（`x-spec-version` 2.2.0-draft.1） | 一行状态记录长什么样、状态机允许哪些迁移、确认签名签的是什么。需求单**不入链、不计锚值** |
| `request.md` | 需求单的设计说明 | 为什么不进链、`mutual_id` 与两条账目的 id 怎么派生、`delivered` 那一次转成什么、签名载荷为什么选 hash、结构落在哪几组约束上 |
| `ingest.md` | **写入面契约**（v2.2 草案） | 四条 POST 的字段（含确认层）、签名载荷的逐字节形状、`DGB_ING_*` 错误码、重放与时间窗；写的是「怎么把记录送进来」，不含任何记录本身 |
| `../../spec/ddl_w4.sql` | **表结构基线**（SQLite，w4-ddl v1.3） | v1.3 的落地：三张 append-only 表、`party` 主体表、`v_public_party` 公开视图、触发器与错误码 |
| `../../spec/ddl_v1.4.sql` | **表结构增量**（SQLite，w4-ddl v1.4，跑在 v1.3 之后） | `request` 表与状态机、主体公钥、`receive`/`payback` 的时间与证据列、`mutual_id` 溯源与判重、`entry_confirm`、写入面的重放闸门 `ingest_nonce` |

**为什么 DDL 在 `../../spec/` 而不是本目录。** 发布包（`git archive`）的根有两棵树：`repo/`
是代码与这份规范，`spec/` 是表结构。DDL 是 Apache-2.0 的实现件，本目录按 R5 只能放 CC0，
所以它不在这里。写路径时以**本文件所在目录**为基准——原先写的是 `../ddl_w4.sql`，
指向 `repo/ddl_w4.sql`，那个文件从来没有存在过（2026-11-14 第 07 步查出，读者点开是 404
的等价物）。`deploy/app/agent.md` 里的路径则以**发布包根**为基准（所以它写
`repo/spec/ingest.md` 与 `spec/ddl_v1.4.sql`），两处基准不同，别互相照抄。

这几份文件说的是同一件事的几层：schema 管**一条记录合不合格**，DDL 管**它怎么存**。
改一处必须同步另一处，`evidence/check_spec.py` 与 `_ops/w0/matrix_probe.py` 就是用来抓这种不同步的。

DDL 为什么分成两个文件而不是一个：v1.3 的字节已被 tag 固定，原地追加会造成「同一个版本号下有
两份 `ddl_w4.sql`」。增量单独成文件后，v1.3 的字节不动，旧库升级就只跑 v1.4 那一个。

## 一、2026-11-12 合并了什么

合并前是两份 schema：`ledger-entry.schema.json` 记资金（`amount_fen` **必填**），
`contribution-entry.schema.json` 记交付（明令禁止 `amount_fen`）。两份都写着「最小 schema」，
读者必须先猜自己该用哪一份——而线上只存在一套结构（三张表、三态、无金额）。
**同一份规范里并存两种必填集，本身就是缺陷**，所以合成一份。

三处取舍，写在这里，不藏在字段里：

1. **资金面整体不进本规范。** S0 阶段不启资金账，只接受非现金支持——实物、劳务、服务
   （服务器、带宽、设备、场地、人力）。
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

**关于「可核验」，还得再说清一层：`verifiability` 是标签，不是机制。**
它三档——`self_reported`（自称）、`counterparty_confirmed`（对方确认）、
`third_party_anchored`（第三方锚定）。**但这一列永远是 `self_reported`，不要再期待它升档**：
它是条目列，条目哈希覆盖全部字段，条目表又是 append-only——改列就是改哈希，链当场断
（2026-11-14 裁决，`_ops/W0-04-设计裁决.md`）。留着这一列，只表示「这条是填报方自述的」。

「对方确认」由**另一处**表达：受方对 `give.hash` 再签一次名，进 `entry_confirm` 表，
导出时落在顶层的 `confirmations` 数组里（与 `items` 并列）。它**进锚值、不进链**——
确认没有「发生在第几条」这种位置意义。`third_party_anchored` 仍无实现，也不开入口。

所以「账本可核验」的准确含义是两句话：**字节可复算**（链没断、导出件 sha256 对得上），
以及**某条记录被两个独立主体各签过一次**（`confirmations`）。两句都**不是**「事情真的
发生过」——要证那件事，得靠当事人与证据。混起来说就成了另一种吹牛。

## 二、三句话说完这份规范

1. **一条链只装一种东西**：已经发生的给 — 受 — 还。金额一旦混进来，链就变成流水账，
   「账能对上」这件事随之失去意义。
2. **用 `type` 分支，不拆成三份 schema**：三态共享 10 个必填字段，拆开之后
   「哪一份才是全量」永远说不清，而合并只需要五个 `if/then`。
3. **结构约束优先于说明文字**：`scope_unresolved=1` 时 `scope` 必须为 `null`，
   由 `allOf` 强制，不靠实现自觉——让「不知道」可被审计看见，而不是被默认值藏起来。

## 三、协议定义了什么，服务做到了什么

这张表是**规范侧**的一份，与 `deploy/app/agent.md` §2 那份（**运行时侧**，给 agent 读的）
一一对应。两份必须在「能力」与「状态」两列上完全一致，且每一格都能被执行一遍。
做这件事的是运维侧的探针 `_ops/w0/matrix_probe.py`（不进仓库发布：它要起真服务、造真钥）。

| 能力 | 协议里写在哪 | 运行时 | 入口 |
| --- | --- | --- | --- |
| 读账目、验链、下载导出件 | `entry.schema.json`、`ddl_w4.sql`（三表 + 链） | ✅ | `GET /api/ledger/items`、`/verify`、`/export` |
| 登记一个主体（一把 ed25519 钥） | `ddl_v1.4.sql`（`party.pubkey`）、`ingest.md` §3 | ✅ | `POST /api/v1/party` |
| 发需求单、撤回 | `request.schema.json`、`request.md` §2 | ✅ | `POST /api/v1/request`（`open` / `withdrawn`） |
| 认领、标记已交付 | `request.md` §3 的迁移表 | ✅ | `POST /api/v1/request`（`claimed` / `delivered`） |
| 交付后自动生成 give + receive 两条 | `request.md` §6 | ✅ | 同一条 `state=delivered` |
| 看需求（最近一屏 / 增量） | `ingest.md` §2.1 | ✅ | `GET /api/v1/requests` |
| 记一条已经发生的账目 | `entry.schema.json`、`ddl_w4.sql`（三表） | ✅ | `POST /api/v1/entry` |
| 确认别人给你的东西（受方签名） | `request.md` §5、`ingest.md` §5 | ✅ | `POST /api/v1/confirm` |
| 站内消息 / 联系对方 | **协议里没有** | ❌ | —— |

三件读表时要知道的事：

1. **状态只有两种值。** ✅ = 现在真的能做；❌ = 不在这套协议里，不是在等排期。
   曾经用过的第三个值 ☐（「设计了但没上线」）已经取消——因为一张同时含有 ✅ 与 ☐ 的表，
   读者没法判断自己看到的承诺哪些已经兑现，而那正是这份规范最不能出的错。
2. **每一格都有一条可执行的验证。**不是「对照代码看过」，是探针真起一个写面、真造两把钥、
   真走一遍。加一行而没有对应验证，探针会红——这是刻意的：**表上不许有没人验过的格子**。
3. **运行时列说的不是「设计上支持」。** 设计支持的东西写在 schema 里；这一列只回答
   「此刻的公开服务会不会照做」。

## 四、自己验一遍

```bash
python3 evidence/build_ledger.py    # 先建库（库不在仓库里）
python3 evidence/check_spec.py      # 再用本规范校验库里每一条
```

`check_spec.py` 只用标准库，逐条报出**第一条不合规**的字段与原因，全过则打印条数并 exit 0。
它实现的是 draft 2020-12 的一个子集（`type` / `required` / `properties` /
`patternProperties` / `additionalProperties` / `enum` / `const` / `pattern` /
`minimum` / `allOf` / `anyOf` / `not` / `if-then`），**不校验 `format`**——
`date-time` 只作标注。这个限度写在脚本头部，不靠使用者猜。

## 五、许可

本目录全部 `CC0-1.0`（见 `../README.md` 的机器可读归属表；`repo_lint` 的 R5 强制 `spec/` 只能是 CC0）。
本文件同样 CC0，可任意复制、改写、商用，不需要署名。
