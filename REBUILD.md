# 重建记录

本仓库于 2026-11-08 由资料库节点重建：原仓无 `.git`，历史不可复现。
重建依据：`数字丐帮2.0·W6/evidence/MANIFEST` 的代码/数据清单（16 条，sha256 全部通过）。
此前文本中出现的 commit `53f6cad` 与 `git ls-files 12` 无法复现，已在 W6-02 与 W7-06 中改述为"不可复现，以本 bundle 为准"。

## C0 · 复算入口（2026-11-10）

clone 后两条命令复现 W3–W7 的 35 件校验：

```bash
python3 evidence/build_ledger.py      # 建基线库 + 执行 DDL，六次攻击全被拒则 exit 0
python3 evidence/regen_manifest.py    # 重算并校验 35 件（0-snapshot）+ 29 件（仓库根），全一致则 exit 0
```

第三条（2026-11-11 起）：`python3 evidence/repo_lint.py repo` —— 十六条许可、署名、签名与审查规则。其中六条卡的是
"同一事实写在两处、只改一处"这类分叉：R10 比 `deploy/app/ledger_hash.py` 与 `src/ledger_hash.py`
是否逐字节相同（vendoring 的分叉不能被 `sha256sum -c` 发现，见 CHANGELOG 的 C3 条目）；R11 比
根 `spec/` 与 `evidence/` 的文件头 SPDX 值是否与目录约定一致（这两处不在 `repo/` 授权树内，
R4 的遍历到不了）；R12 比名录与 git 记录是否对得上（漏记、虚构、依据不可查都会红）；
R13 比 `CREDITS.md` 与 `credits.json` 的记录集、发布权记载是否相同；R14 比 `repo/allowed_signers`
的公钥指纹与 `CREDITS.md` §10 是否一致，并核对签发权（`can_release`）与名录双向对齐、一人一钥；
R15 比已签名提交的签名者与作者是否同一人（防「拿自己的钥签别人的提交」，那时验签会报 Good）；
R16 比审查记录与 git、与名录是否对得上（审阅人要有发布权、accept 的提交必须进名录依据、
基线之后的外部提交必须有记录、两份表示不许分叉）。当前 14/16，未过的 R2、R9 为既有缺口，
故本条属"附带体检"而非判据。

R12/R13 存在的理由很简单：**署名承诺如果不能被第三方核验，就不是承诺，是客气话。**
R14/R15 存在的原因是同一句话的下一半：**如果谁都能签、或者签了也看不出是谁，那签名只是装饰。**

### 目录口径

| 路径 | 性质 | 能否修改 |
| --- | --- | --- |
| `0-snapshot/W3…W7/` | 2.0-final 冻结基线：35 件文件 + 5 份 MANIFEST，按原相对路径逐字节镜像资料库 | **不可改**。改一个字节，35/35 即断 |
| `spec/ddl_w4.sql` | DDL 唯一源（现为 v1.2；v1.3 由 C2 产出） | 可改，改后须重算 W4 相关指纹并记变更 |
| `evidence/*.py` | 工作副本，可改 | 可改；`0-snapshot/` 内同名件始终保留冻结字节 |
| `evidence/nodes.tsv` | `0-snapshot` 路径 → 资料库节点 ID 映射 | 基准件增减时同步 |
| `repo/deploy/` | 线上账本服务的部署源（C3 起），与服务器 `/opt/drawcommons/` 一比一 | 可改；改后须重算根 MANIFEST 并推服务器，两者须逐字节相同 |

### `regen_manifest.py` 两条通道

- 默认（离线）：只读本地 `0-snapshot/`，重算并校验，不联网。独立复现者用这条即可满足判据。
- `--fetch`：按 `evidence/nodes.tsv` 调用**本机**的 library 技能重新导出后再重算。凭据留在本机技能里，不进仓库、不读仓库内任何 token；没有该技能也能跑默认模式。
- `--check` 只校验不改写；`--week W4` 限定单周。

注：`evidence/build_ledger.py` 相对 `0-snapshot/W4/build_ledger.py` 只改了一处——DDL 改为优先读 `spec/ddl_w4.sql`，找不到再回退同目录，以落实"DDL 唯一源在 spec/"。

## C1 · 仓库改名（2026-11-10）

仓库名由 `dgb2-w6` 改为 **`drawcommons`**，名称由「数字丐帮」改为「众汲之井」。

- 改名前的最后一个提交打标签 `v2.0-final`（`84cf110`），2.0-final 冻结基线以该 commit 为准。
- 改名只作用于`标识面`与工作副本；`0-snapshot/` 不动，35/35 不受影响。详见 `CHANGELOG.md`。
- 变更记录已写入仓库根 `MANIFEST` 头部（重算时点 2026-11-10）。

