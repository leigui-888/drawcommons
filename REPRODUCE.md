# 复现说明

本仓库对外发布的目的是：**让任何人不必相信我们，也能自己算出同一个锚值**。

这里的每一句话都可以用命令验证。若你跑出来的结果与本文不一致，那是我们的问题，不是你的——请按第 5 节告诉我们。

## 1. 你需要什么

| 项 | 要求 | 说明 |
| --- | --- | --- |
| Python | 3.10+（实测 3.12.16 与 3.13.12） | **纯标准库，无第三方依赖**，不需要 `pip install` |
| SQLite | 任意现代版本（实测 3.46.1） | Python 自带 `sqlite3` 即可。`spec/ddl_w4.sql` 只用 `CREATE TABLE/VIEW/TRIGGER` 与 `RAISE`，未用 `STRICT`、生成列、窗口函数等新特性 |
| 操作系统 | 不限 | Windows 与 Linux（Debian 13 容器）已实测；macOS 未实测，但代码无平台相关分支 |
| 磁盘 | 10 MB | 仓库 52 KiB，加上重建的库不到 1 MB |

不需要联网、不需要任何凭据、不需要我们提供的任何服务。第 2 节起的命令在断网机器上同样成立。

## 1.1 这个仓库长什么样

clone 下来会看到两个层次，别混淆：

| 路径 | 是什么 | 校验口径 |
| --- | --- | --- |
| `MANIFEST`、`evidence/`、`0-snapshot/`、`spec/` | 整包：证据脚本、35 件 2.0-final 冻结文档、DDL | `MANIFEST` 25 条强制校验 + `0-snapshot/*/MANIFEST` 35 条冻结校验 |
| `repo/` | **对外授权的那一棵树**（代码、接口 schema、部署源、许可文本）。它自己的 `repo/README.md` 里有一张机器可读的逐文件许可表，表里的路径相对 `repo/` | `evidence/repo_lint.py repo` 逐件检查 |

运行服务的那份代码在 `repo/deploy/`，与 <https://drawcommons.org> 线上逐字节相同。

## 2. 两条判据（都以 exit 0 结束）

```bash
git clone https://drawcommons.org/repo.git drawcommons
cd drawcommons

python3 evidence/build_ledger.py      # ① 建基线库 + 执行 DDL + 十一次应当被拒的操作
python3 evidence/regen_manifest.py    # ② 重算并校验 35 件（0-snapshot）+ 23 件（仓库根）
```

这两条是邀请的全部内容。**任一条非 0，就是我们错了**，按第 5 节告诉我们。

## 3. 期望输出

**① `build_ledger.py`** — 打印 **19 行**：两行计数（`归档行数` / `未判定 scope 行数`），其余 **17 行都含 `OK`**（形如 `append-only OK: …`）。任何一行不含 `OK` 即失败。

```
DDL OK; ledger_give: [('g_1', 'mutual', 0, 2.0, 'self_reported', 'pr_v1.1.0'), ...]
归档行数: 1
未判定 scope 行数: 1
append-only OK: UPDATE ledger_give -> DGB_LED_012: append-only: UPDATE forbidden on ledger_give; p
append-only OK: UPDATE ledger_receive -> …
append-only OK: UPDATE ledger_payback -> …
append-only OK: DELETE ledger_give -> DGB_LED_013: append-only: DELETE forbidden on ledger_give
append-only OK: DELETE ledger_receive -> …
append-only OK: DELETE ledger_payback -> …
scope CHECK OK: vendor -> CHECK constraint failed: scope IN ('public','mutua…
scope CHECK OK: PUBLIC -> CHECK constraint failed: scope IN ('public','mutua…
归档只读 OK -> DGB_LED_014: archive_magnitude_v1 is read-only
默认假名 OK: 无 display_mode 时 shown_name = party_id
实名绑定 OK (INSERT 拦截, DGB_LED_016): DGB_LED_016: real-name display requires explicit real_name_r…
实名展示 OK: 显式绑定后视图输出 real_name_ref
撤回生效 OK: 视图立即回落 party_id，consent_withdrawn=1
撤回终态 OK (DGB_LED_015): DGB_LED_015: consent withdrawal is final; cannot un-withdraw
视图双保险 OK: display_mode 未改、实名仍不输出
视图不泄露 OK: real_name_ref 不在 v_public_party 中 -> no such column: real_name_ref
```

它做两件事：**十一处应当被拦下的写入**（三张表的 UPDATE/DELETE 各一 = 6，`scope` 非法值 2，归档表只读 1，未绑定的实名展示 1，撤回后再撤回 1）必须全被拒绝；**五处应当成立的展示口径**（假名回落、实名显式绑定、撤回即时生效、双保险、视图不泄露）必须全部成立。任何一条不成立，脚本以非 0 退出。

**② `regen_manifest.py`**

```
    W3: 4/4
    W4: 6/6
    W5: 4/4
    W6: 16/16
    W7: 5/5
  repo/MANIFEST: 25/25

0-snapshot MANIFEST 校验：35/35 通过
仓库根 MANIFEST 校验：25/25 通过

复现判据：35/35（0-snapshot）+ 25/25（仓库根） —— 与 MANIFEST 记录完全一致。
```

它按 `MANIFEST` 里记录的 sha256 逐件重算本地字节。注意 `35/35` 是**冻结基线**（2.0-final，改一个字节即断），`25/25` 是**可改的工作副本**（含 `deploy/` 与名录）。两者口径不同，别混着看。

## 4. 附带的体检（**exit 1 是预期的**）

```bash
python3 evidence/repo_lint.py repo
```

```
==============================================================================
  ✅ R1 四件套
  ❌ R2 全文完整度
  ✅ R3 归属覆盖率
  ✅ R4 逐文件声明
  ✅ R5 spec 必须 CC0
  ✅ R6 无禁用许可
  ✅ R7 NOTICE 无矛盾
  ✅ R8 清单可复验
  ❌ R9 MANIFEST 路径一致
  ✅ R10 deploy 副本一致
  ✅ R11 根受管文件声明
  ✅ R12 署名落地
  ✅ R13 名录两源一致
  合计：11/13 条通过
==============================================================================
```

**11/13，exit code 1。这不是你跑错了。** 两条缺口已知且未修：

- **R2**：许可文本 4 份里只有 `LICENSE`（Apache-2.0，11,357 字节）是全文，`LICENSE-CC-BY-4.0.md`（814 B）、`LICENSE-CC-BY-SA-4.0.md`（832 B）、`LICENSE-CC0-1.0.md`（1,079 B）都是**指针件**——正文只有指向 creativecommons.org 的链接。离线环境下使用者拿不到 CC 条款原文。登记为 D-06，G7′ 前补齐。
- **R9**：本仓库的校验清单叫 `MANIFEST`（供 `sha256sum -c MANIFEST` 用），而 R9 找的是 `MANIFEST.sha256`。历史命名口径问题，规则与文件没对齐。

**R11 是 2026-11-11 新加的**，补的是 `repo/` 之外那一层：根 `spec/ddl_w4.sql` 与 `evidence/*.py`。它们同样被 git 跟踪、同样随 clone 公开，但 R4 只遍历 `repo/`，此前从未被任何规则看过「许可能不能判断」。R11 逐文件核对 SPDX 头且比对值：根 `spec/` 必须 `CC0-1.0`、`evidence/` 必须 `Apache-2.0`。值写错与缺失都会报红（两种都实测过）。

**R12、R13 也是 2026-11-11 新加的，问的是另一个问题**：许可说得清「能不能用」，
说不清「这是谁做的」。署名承诺只写在 `CONTRIBUTING.md` 里，是一句没有对象的话——
没有名录可查、没有依据可验、被删了也无人知道。所以：

- **R12** 把名录接回 git 记录，查四件事：git 里有提交的人，名录里有没有（**不漏记**）；
  名录里的人，git 里有没有提交（**不虚构**——给一个查不到贡献的人发署名，
  和漏记一样是伤害）；每条依据的 commit 是否真存在（**可核验**）；
  文件头还有没有「某某版本贡献者」这类集体名（**指不到人**）。
- **R13** 卡住名录的两份表示不许分叉：`CREDITS.md` 给人读，`credits.json` 给机器读，
  不一致时主张的人会被告知「以另一份为准」，承诺就此落空。

这两条是**实测过能抓错**的，不是摆设：临时往 `credits.json` 塞一个查不到提交的贡献者，
R12 报「无法追溯的作者 1」+「依据可核验 2/3」，R13 报「已分叉」；把 `pending` 里那条
7 次提交的记录删掉，R12 立刻报「git 里有提交、名录里没有：noreply@drawcommons.org」；
只改 `CREDITS.md` 的名字不改 json，R13 双向报差异。三次注入做完均已复原字节。

这样做是为了让署名承诺**可被第三方核验**，而不是靠维护者自觉：名录里每个名字都指得到
具体提交，谁删了一条，旧版本里的快照哈希对不上（见 `CREDITS.md` §8）。

我们选择让 R2、R9 留在红色，而不是改规则让它变绿——一个会把不合格项藏起来的检查器，比没有检查器更坏。**如果你用 `set -e` 跑脚本，请把这一条放在判据之外。**

## 5. 锚值

跑完第 2 节，你可以自己算出线上服务展示的那个锚值：

```bash
LEDGER_DB=evidence/ledger_w4.db python3 repo/deploy/app/app.py &
curl -s http://127.0.0.1:8000/api/ledger/export | sha256sum
```

> **必须先跑第 2 节的 ①。** `evidence/ledger_w4.db` **不在仓库里**——它是 `build_ledger.py`
> 的构建产物，被 `.gitignore` 排除。跳过 ① 直接跑这段，服务会因为读不到库而返回 503。
> 这也是本仓库的一条设计：库不是"存进来的一份文件"，而是"用脚本算出来的结果"，
> 任何人都能重算出同一份（构建是字节确定的，跑完哈希不变）。

期望：

```
cdec34e5bb85018a9a0d905307ee2103fa1ee7a9f046290987cc1a801efe30a9
```

这个值与 <https://drawcommons.org/> 页面上的锚值、以及线上 `/api/ledger/export` 的字节完全一致。线上首页另有 `verify` 端点，它每次都现场重跑整条哈希链，不读缓存。

## 6. 如果你跑不通

请把这三样贴给我们（缺一样我们就无法定位）：

1. `python3 --version` 与 `python3 -c "import sqlite3;print(sqlite3.sqlite_version)"`；
2. 失败那一步的**完整输出**，包括 traceback 的全部行；
3. 你 clone 下来的 commit：`git rev-parse HEAD`。

通道：<admin@drawcommons.org>。我们会回；**如果确认是仓库的问题，会记进 `CHANGELOG.md` 并公开修正**——包括"我们的判据本身写错了"这种情况。

## 7. 这套东西证明了什么，没证明什么

**证明了**：

- 账本的哈希链自洽：每条记录的 `prev_hash` 与它前一条咬合，改任何一个字节都会在 `verify` 处断开；
- 数据库层面十一类非法写入（改历史、删条目、跳同意书做实名绑定、撤回后再撤回等）被 DDL 与触发器拒绝；
- 仓库里每份代码、数据、文档的字节与 `MANIFEST` 声称的一致（35 条冻结 + 25 条工作副本）；
- 线上服务与仓库 `deploy/` 逐字节相同——算出锚值的那段代码，你看得到。

**没有证明**（请务必按这个口径理解）：

- **账目的真实性**。样例库 `evidence/ledger_w4.db` 只有 4 条记录（`ledger_give` 2、`ledger_receive` 1、`ledger_payback` 1），且都是假 ID。链自洽只说明"记录之间没被动过"，不说明"记录描述的事真的发生过"。
- **规模**。4 条的链与 4 万条的链在算法上是同一件事，在工程上是两件事。后者我们还没跑过。
- **独立性**。这份代码是我们自己写的，我们复核自己不算独立复核——这正是这份邀请存在的原因。

## 8. 许可

- 代码（`src/`、`deploy/`）：Apache-2.0，保留版权与许可声明、NOTICE；
- 接口与 schema（`spec/`）：CC0-1.0，随便用，不用署名；
- 数据（`data/`、`evidence/*.db`）：CC-BY-4.0，署名即可；
- 文档（`repo/` 与 `0-snapshot/`）：CC-BY-SA-4.0，署名 + 改编同样开放。

逐文件归属见 `repo/README.md` 的机器可读表——`repo_lint.py` 的 R3 就是照它逐件检查的。本文件（仓库根 `REPRODUCE.md`）同为 CC-BY-SA-4.0。
