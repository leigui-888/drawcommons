<!-- SPDX-License-Identifier: CC0-1.0 -->
<!-- Copyright 2026 老夫 <2379731846@qq.com> -->

# 众汲之井 · 审计任务（给 agent）

> 这是一份可以直接执行的任务说明：**不用注册、不用私钥、不写账本**。
> 你只读、只算、只报告。全程对服务端零信任——它说的每一句，都要能被你手里的字节推翻。

站点：`https://drawcommons.org`　本文件：`https://drawcommons.org/audit.md`

---

## 1. 你要检验的那一句话

> 站点上写的数字、接口返回的数字、导出件字节算出来的数字，是**同一套事实**。

只要一个反例就能推翻它。做完下面的脚本，你手里会有一份可以贴给任何人的结论。

## 2. 三件事，脚本一次跑完

| 步 | 你算的东西 | 它推翻什么 |
| --- | --- | --- |
| A | `sha256(导出件原始字节)` 与页面上印的锚值是否逐字符相等 | 「锚值是装饰」——不等，说明页面上的值不是这份字节的哈希 |
| B | `count`、`len(items)`、`verify.items`、`/llms.txt` 的条数是否同一个数 | 「各页各说各话」——复盘时真抓到过：文档写 4、实际 6 |
| C | `verify.ok` 是否为 `true`，`chain_tail` 是否等于最后一条的 `hash` | 「链断了却还在说 ok」 |

**依赖只有 python3（标准库）。** 没有 pip、没有 jq、没有本仓库的代码——
如果你要装点什么才能验，那就不叫「自行复算」了。

## 3. 整段可跑

<!-- probe:begin -->
```bash
DG_BASE="${DG_BASE:-https://drawcommons.org}" python3 - <<'PY'
import hashlib, json, os, re, sys, urllib.request

BASE = os.environ.get("DG_BASE", "https://drawcommons.org").rstrip("/")
PASS = FAIL = 0

def get(path: str) -> bytes:
    with urllib.request.urlopen(BASE + path, timeout=20) as r:
        return r.read()

def ok(msg):   global PASS; PASS += 1; print("PASS  " + msg)
def bad(msg):  global FAIL; FAIL += 1; print("FAIL  " + msg)

# ── A. 锚值 ────────────────────────────────────────────────────────────────
raw = get("/api/ledger/export")                     # 原始字节，不解码
calc = hashlib.sha256(raw).hexdigest()
page = re.search(r"[0-9a-f]{64}", get("/ledger").decode("utf-8"))
llms = re.search(r"[0-9a-f]{64}", get("/llms.txt").decode("utf-8"))

ok(f"A1 导出件长度 {len(raw)} 字节，sha256={calc}")
if page and calc == page.group(0):
    ok("A2 页面印的锚值 = 你算的")
else:
    bad(f"A2 页面印的是 {page.group(0) if page else '（找不到）'}，实算 {calc}")
if llms and calc == llms.group(0):
    ok("A3 llms.txt 的锚值 = 你算的")
else:
    bad(f"A3 llms.txt 写的是 {llms.group(0) if llms else '（找不到）'}，实算 {calc}")

# ── B. 条数：四个来源必须同一个数 ──────────────────────────────────────────
items  = json.loads(get("/api/ledger/items"))
verify = json.loads(get("/api/ledger/verify"))
n_count, n_len, n_ver = items["count"], len(items["items"]), verify.get("items")
m = re.search(r"条目数：(\d+)", get("/llms.txt").decode("utf-8"))
n_llms = int(m.group(1)) if m else None

if n_count == n_len:
    ok(f"B1 count={n_count} = 数组长度")
else:
    bad(f"B1 count={n_count}，数组长度={n_len}")
if n_count == n_ver:
    ok(f"B2 count={n_count} = verify.items")
else:
    bad(f"B2 count={n_count}，verify.items={n_ver}")
if n_count == n_llms:
    ok(f"B3 llms.txt 的条数={n_llms} = count")
else:
    bad(f"B3 llms.txt 写 {n_llms}，count={n_count}")

# ── C. 链 ─────────────────────────────────────────────────────────────────
tail = items["items"][-1]["hash"] if items["items"] else None
if verify.get("ok") is True:
    ok("C1 verify.ok 为 true")
else:
    bad(f"C1 verify.ok={verify.get('ok')}，first_bad={verify.get('first_bad')}")
if tail and tail == verify.get("chain_tail"):
    ok("C2 chain_tail = 最后一条的 hash")
else:
    bad(f"C2 chain_tail={verify.get('chain_tail')}，最后一条={tail}")

# ── 结论 ──────────────────────────────────────────────────────────────────
print(f"\n合计：{PASS} 项通过 / {FAIL} 项未过")
if FAIL == 0:
    print(f"结论：截至本次执行，页面、接口、导出件三者一致；锚值 {calc}")
sys.exit(1 if FAIL else 0)
PY
```
<!-- probe:end -->

期望输出最后两行：

```
合计：8 项通过 / 0 项未过
结论：截至本次执行，页面、接口、导出件三者一致；锚值 <64 位十六进制>
```

> **任何一项 FAIL 都是真问题。** 把它连同命令、时间、原始输出一起报出来。

想手工只看锚值（30 秒版）：

```bash
curl -s https://drawcommons.org/api/ledger/export | sha256sum
# 再打开 https://drawcommons.org/ledger 对照页面上印的那串
```

## 4. 怎么报

- 邮件 `2379731846@qq.com`，主题以 `audit:` 开头
- 或开 issue：`https://github.com/leigui-888/drawcommons/issues`
- 必须带三样：**你跑的命令**、**原始输出**、**你算出的哈希**。缺一样就无法复现，也就无法修。

## 5. 已知的不一致（别重复报，但可以核）

导出件里的 `data_notice` 写着「W4 结构验证样例（4 条，假 ID）」，实际条目数是 6。
那是**冻结的措辞**：改它就要重算锚值，而重锚排在 v2.2 与第一批真实账目一起做。
所以**以 `/api/ledger/items` 的 `count` 为准**，不要以那句话里的数字为准。

除此之外，你发现任何一处对不上，都是没人见过的——报出来。

## 6. 边界

- 全程只读：不要 `POST`，不要带私钥，不要试图改任何字节。
- 不要为了让数字好看而改命令。审计的价值在于**命令能被别人原样重跑**。
- 这份文件里没有一个写死的数字：锚值与条数都是脚本现算的。写死的那天，它就开始过期。
