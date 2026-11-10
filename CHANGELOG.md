# CHANGELOG

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
