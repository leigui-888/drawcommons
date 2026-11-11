# CHANGELOG

## 2026-11-11 · C3 · 部署源入库 `deploy/` + 根 MANIFEST 16 → 22

线上那套只读账本服务（`drawcommons.org`）此前**不在任何版本控制里**：只有本机一个目录、服务器一份文件，回滚靠手工归档 `.py`。一个对外提供账本验证的公开品，服务端代码不进仓库，等于"锚值可验、但算出锚值的那段代码不可验"。本次收进 `repo/deploy/`，随 `repo/` 一起对外发布。

**路径选型**：`repo/deploy/`（而不是仓库根另开目录），理由是它要跟 `src/`、`spec/` 一样受 `repo/README.md` 的机器可读许可表治理——放进 `repo/` 就自动被 `repo_lint.py` 的 R3/R4 逐文件检查；放在仓库根则游离在许可门之外。

| 本仓库 | 服务器 `/opt/drawcommons/` | 入 MANIFEST |
| --- | --- | --- |
| `deploy/app/{Dockerfile,app.py,ledger_hash.py}` | `app/` | 是（3 条） |
| `deploy/{compose.yml,Caddyfile,daily.sh}` | 根目录 / `backup/` | 是（3 条） |
| `deploy/README.md`、`deploy/app/data/README.md` | — | 否（文档，进注释区） |

**没有把 `ledger.db` 复制进来。** 样例库在仓库里只有一份 `evidence/ledger_w4.db`（sha256 `31445fa5…`）。再复制一份到 `deploy/app/data/` 会得到两个都"看起来权威"的库——线上锚值该信哪个将失去唯一答案，这正是同日修掉的 P0（库由镜像 COPY、与宿主备份源静默分叉）的同一类错误。镜像要自含数据时 `cp evidence/ledger_w4.db deploy/app/data/ledger.db` 再 build，`deploy/README.md` 第 2 节写明了。

**`deploy/app/ledger_hash.py` 是 vendoring，加了 R10 兜底。** build context 里必须有这个文件，所以只能有副本。但 vendoring 的失败方式不是"写错代码"，而是"两份都对、却不一样"：哈希算法一变，线上锚值与仓库声称的就不是一回事，而两条 MANIFEST 行各自都能自证清白——`sha256sum -c` 抓不到跨文件分叉。故 `repo_lint.py` 增至十条规则，R10 直接比字节。实测两处均为 `2c29eb8d…`；本轮 `repo_lint` 8/10，未过的两条是既有项（R2 有 5 份许可为指针件，D-06；R9 无 `MANIFEST.sha256`，历史口径），非本次引入。

**许可表增两行**（顺序即优先级）：`deploy/app/data/** CC-BY-4.0` 在 `deploy/** Apache-2.0` 之前，这样将来若把样例库放进部署目录，它是数据不是代码。

**线上同步**：四个文件补 SPDX 头（`Dockerfile`、`Caddyfile`、`compose.yml`、`daily.sh`）后重推，服务器侧六个指纹与仓库逐字节相同；`docker compose build`（Dockerfile 仅注释变更，层全命中，容器未重建）、`caddy reload` 热重载（未重启，Up 保持 20 小时）。复核：六端点全 200、`verify ok=true/4`、导出件 sha256 仍为 `cdec34e5…`、挂载 `RW=false`、横幅 `(bind mount ✓)`。

**判据从两条变三条**：

```bash
python3 evidence/build_ledger.py      # exit 0
python3 evidence/regen_manifest.py    # 35/35 + 22/22，exit 0
python3 evidence/repo_lint.py repo    # R10 必须 ✅（其余两条既有缺口不因本次变化）
```

## 2026-11-11 · F 尾 · 错误码前缀定稿 + W2/W7-02 回写

三件事同批做完，都不动代码：

1. **错误码前缀定稿**：六个码由 `GAIBANG_E_*` 改为中性前缀 **`LEDGER_E_*`**（用户 2026-11-11 确认）。理由只在时点——beta 未发布、无外部接入方，此刻更名成本为零，发布之后即为破坏性变更。协议 r5 §1.23.1 记定稿并把回退通道写死（再改须按 1.23.2 走程序）；`W7-02` §4 六行同步改齐并加一段前缀说明。
2. **W7-02 文档指纹重测**：18,702 B / `f565bd1f…` → **19,093 B / `aa4ac5b0…`**（导出件实测）。`0-snapshot/W7/MANIFEST` 只改注释区一行 + 头部加「F3 补充变更」注，强制校验行零改动；五份 MANIFEST 复验 **35/35 全 OK**，`W7` 自指纹变为 `6a8aeb90…`。
3. **W2 全 11 份整篇覆盖回资料库**：每份只在文档头部 meta 区加一行「原代号：数字丐帮（2026-11-10 起产品名「众汲之井」…）」，正文历史记录一字未动；两份「盲测发放物」按历史原件保持原样、不覆盖——它们是发给第三方的原物，改了就不再是证据。

**通道已知行为**：文档导出时反斜杠会被二次转义（`ddl\_w4` → `ddl\\\_w4`），F4 覆盖的 W4-02 导出同样如此，属导出器行为、非存储损坏；比对正文时以本地源为准。

## 2026-11-11 · F3 · MANIFEST 重算 + verify

F4 把 W4-02 / W6-02 整篇覆盖回资料库后，两份文档的导出指纹已漂移。F3 做三件事：

1. **正式 verify**：`regen_manifest.py --check` 全绿——0-snapshot **35/35** + 仓库根 **16/16**，exit 0（改动前、改动后各跑一次）。
2. **重测两份文档指纹**：从资料库重导出，连续导出 2 次同值（复现性成立）：
   - W4-02：18,329 B / `7a5f9341…`（2026-11-09）→ **31,055 B / `035761b1…`**
   - W6-02：11,515 B / `556333b5…`（2026-11-09）→ **12,824 B / `6f3f27bb…`**
3. **注释区更新 + 变更记录**：只改 `0-snapshot/W4/MANIFEST`、`0-snapshot/W6/MANIFEST` 的文档注释区各 1 行，头部按 C1 先例追加「F3 变更」注释；**强制校验行零改动**。

**纪律说明**：改注释区 = 改 MANIFEST 字节 = 自指纹变化。FREEZE-2.0-final.md 已补 F3 变更块：冻结值（`1f4d77ea…` / `d16caf5d…`）保留为 2026-11-10 冻结记录，F3 后为 `W4 a248ad69…`、`W6 fbeac0fa…`（W3/W5/W7 不变）。其余 44 份文档的指纹行维持 2026-11-09 口径——2.1 期本地修订尚未回写资料库的文档，在其各自回写时再重测，不提前追。

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
