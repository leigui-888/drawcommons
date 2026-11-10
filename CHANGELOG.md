# CHANGELOG

## 2026-11-11 · C2 · DDL v1.3

`spec/ddl_w4.sql` v1.2 → **v1.3**。这不是加一列，是补上账本一直缺的"主体选择如何被展示"这一层，发布闸门第 5 条（实名须显式绑定）从口号变成可攻击验证的结构。

| 产出 | 说明 |
| --- | --- |
| `party` 表 | `display_mode` 默认 `pseudonymous`，CHECK 限二值；`real_name_ref` 只存引用不存明文（库被整库拖走时实名原文不随库泄露）；`consent_withdrawn_at` / `updated_at` |
| `v_public_party` 视图 | **唯一对外口径**。仅当显式实名 + 未撤回 + 引用存在三者同时成立才输出 `real_name_ref`，否则回落 `party_id`；视图不含 `real_name_ref` 原列，查它直接报错 |
| `DGB_LED_015` | 撤回同意是终态：`consent_withdrawn_at` 一旦写入不可清空/回拨 |
| `DGB_LED_016` | 实名须显式绑定：`display_mode='real_name'` 而 `real_name_ref` 为空，INSERT / UPDATE 两路都拦（表级 CHECK 另有一道兜底） |

`evidence/build_ledger.py` 断言从 9 项扩到 **16 项**：默认假名、实名未绑定被拒、实名展示、撤回立即生效、撤回终态、视图双保险（`display_mode` 未改也不输出实名）、视图不泄露原列。`exit 0`。

对冻结基线零影响：`spec/` 与 `evidence/` 不在指纹集内，`regen_manifest.py --check` 复跑 35/35 + 16/16 照过。命名空间 `dgb.ledger.v1` 不动，错误码沿用 `DGB_LED_0xx` 序列（015/016 接在 014 之后）。

## 2026-11-10 · F1 + F2

### F1 · 2.0-final 冻结说明

新增 `FREEZE-2.0-final.md`：把「46 份文档指纹 / 35 件代码数据 / 5 份 MANIFEST」三层证据的关系写清，给出两条离线判据命令、五份 MANIFEST 自指纹、以及"什么时候允许动基线"的例外程序。核心一句：**2.1 的任何变更一律不进 `0-snapshot/`**。

### F2 · 版本串

| 产出 | 说明 |
| --- | --- |
| `VERSION.md` | 人读版：`v2.1-r5` 的组件对照、`protocol_ready: false` 的原因、三条版本纪律 |
| `version.json` | 机读版：接口与导出回显同一串，可 `curl` 取、可 diff |

对外唯一版本串定为 **`v2.1-r5`**。两处判断记在这里：

1. **版本串不含项目名**。名字可能换（11-27 商标回件后可能要换备名），承诺集不会换；串里带名字就等于把版本绑在名字上，与"版本号绑定承诺集范围"的纪律冲突。
2. **协议修订包以 v2.1 为准**。11-09 决策表写「r5（修订包 v2.2）」，但库里三处（W7-00 / W7-02 / W7-04）一律是 v2.1，且没有任何一份叫 v2.2 的文件。判定为笔误，不追认——**指向不存在的版本号，比写错版本号更糟**。

### 附带修掉一个复现缺陷

`evidence/build_ledger.py` 原先用 `os.remove()` 删库重来，在文件被占用或删除受限的环境里（Windows 常见）第二次执行直接失败。改为"删不掉就地清空（DROP 全部表与视图）"。原判据「clean clone 后跑两条命令」只在第一次成立，现在**可反复执行**：

```
run1=0  run2=0  regen=35/35 + 16/16
```


## 2026-11-10 · C0 + C1（同批提交）

### C0 · 复算能力进仓库

| 产出 | 说明 |
| --- | --- |
| `0-snapshot/W3…W7/` | 2.0-final 冻结基线：35 件文件 + 5 份 MANIFEST，按原相对路径逐字节镜像资料库 |
| `spec/ddl_w4.sql` | DDL 唯一源（现为 v1.2，sha256 `b093b685…`；v1.3 由 C2 产出） |
| `evidence/build_ledger.py` | 建库 + 六次攻击断言；相对冻结版仅改一处：DDL 优先读 `spec/ddl_w4.sql` |
| `evidence/regen_manifest.py` | 重算并校验 6 份 MANIFEST（0-snapshot 35 件 + 仓库根 16 件） |
| `evidence/nodes.tsv` | 0-snapshot 路径 → 资料库节点 ID 映射，供 `--fetch` |
| `.gitignore` | 忽略生成物 `evidence/ledger_w4.db`（`0-snapshot/W4/ledger_w4.db` 仍入库） |

判据（在剥离 `.git` 的干净副本中实测）：

```
python3 evidence/build_ledger.py     → exit 0，UPDATE/DELETE 六次攻击全被 DGB_LED_012/013 拒，
                                        scope CHECK 与归档只读（DGB_LED_014）均生效
python3 evidence/regen_manifest.py   → 0-snapshot 35/35，仓库根 16/16，exit 0
```

### C1 · 仓库改名

- 仓库名：`dgb2-w6` → **`drawcommons`**。与域名同源、不含「井」字；11-27 若判「不建议注册」须启用备名时，仓库名无需再改（与域名解耦同一逻辑）。
- 名称替换：「数字丐帮」→「众汲之井」，范围限于**标识面**：`NOTICE`、`README.md`、`TRADEMARK.md`、`spec/*.json` 的 `title`、`spec/*.license` 的 SPDX 版权行、`src/ledger_hash.py` 版权头、`LICENSE-CC-BY-4.0.md` 资源清单示例。
- `TRADEMARK.md` 按其 §7 执行：**条文不改**，只换名称与状态；新增「已执行记录」表，写明旧名留 90 日曾用名说明（至 2027-02-08）。
- `evidence/tm_class_check.py`：数据表换为 11-09 定名结果（主名 众汲之井；备名 器不私属；留档 百家同器 / 一尺同量），逻辑未改。复算结果与 11-09 六道关一致：主名 ⑥ 命中「之」（虚词，显著性由「众汲」「井」承担）、器不私属 6/6、反例「丐帮联盟」仍有牙。
- 仓库根 `MANIFEST`：7 条指纹按改名后字节重算，头部追加变更说明。

### 刻意未改（记录以免被当成漏改）

| 对象 | 原因 |
| --- | --- |
| `0-snapshot/` 全部 40 个文件 | 2.0-final 冻结基线；改名不回溯修改历史基线，故 35/35 不受影响 |
| 协议三件套正文、`baseline_w3.json` | 属协议修订范畴，随 W7-02 修订包 v2.1（r5）一并处理 |
| `scan_terms.py` 的 `丐帮` 扫描正则 | 改名后该规则正好用于拦旧名残留；语义未变，不改 |
| 资料库节点标题（43 处） | 按定名纪律不追改，只加「原代号：数字丐帮」一行 |
| `evidence/asset_decl_check.py` 的 docstring 示例路径 | 指向资料库真实文件名（`数字丐帮2.0·W6-05…`），标题不追改，示例仍有效 |

### 待对齐

`repo/` 与 `0-snapshot/W6/repo/` 自本版起**内容不同**：前者是 2.1 工作副本（已改名），后者是 2.0-final 冻结字节。这是 C0 定下的结构（基线 / 工作副本分离），不是漂移。资料库侧 W6-02（仓库落地包）、W6-03（商标与认证规则）仍为旧名版本，须在 `F4` 整篇覆盖时同步为 2.1，届时重跑四向一致性核对。

### 标签

- `v2.0-final` → commit `84cf110`（改名前的最后一个提交），作为 2.0-final 冻结点。
