# README

# 众汲之井 2.0 · 仓库许可归属

> **本 README 只回答一个问题：这个仓库里的东西，你能不能合法用、按什么条件用。** 十分钟接入的 README 是 M2-R1 的产物，本文件不承担那个职责——现在还没有可接入的东西。

## 1. 你要的东西在哪

| 你想做什么 | 看哪个目录 | 许可 | 你需要做什么 |
| --- | --- | --- | --- |
| 用代码起一套服务 | `src/` | Apache-2.0 | 保留版权与许可声明、NOTICE |
| 照原样部署线上那套账本服务 | `deploy/` | Apache-2.0 | 保留版权与许可声明、NOTICE |
| 实现本项目的接口/schema | `spec/` | **CC0-1.0** | **什么都不用做** |
| 拿资源清单做自己的应用 | `data/` | CC-BY-4.0 | 署名 |
| **不信我们，自己验一遍** | `../REPRODUCE.md`（仓库根） | — | 两条命令，无需联网与凭据 |
| 转载或改写文档 | `docs/` | CC-BY-SA-4.0 | 署名 + 改编同样开放 |
| 说"我们兼容众汲之井" | — | 见 `TRADEMARK.md` | 遵守认证条件（免费、公开、不拒绝合规申请） |

## 2. 许可归属表（逐文件，机器可读）

第一列是路径模式，按**从上到下第一个匹配**生效。新增目录必须在此表登记，否则 CI 判"无许可归属"。

```licenses
LICENSE*                        NOASSERTION
DCO                             CC-BY-SA-4.0
NOTICE                          CC-BY-SA-4.0
CONTRIBUTING.md                 CC-BY-SA-4.0
CREDITS.md                      CC-BY-SA-4.0
credits.json*                   CC-BY-SA-4.0
README.md                       CC-BY-SA-4.0
TRADEMARK.md                    CC-BY-SA-4.0
src/**                          Apache-2.0
scripts/**                      Apache-2.0
deploy/app/data/**              CC-BY-4.0
deploy/**                       Apache-2.0
spec/**                         CC0-1.0
data/**                         CC-BY-4.0
docs/**                         CC-BY-SA-4.0
```

三个约定：

1. `LICENSE*`** 判 **`NOASSERTION`：许可文本本身不是被许可的作品，不该被自己的条款覆盖。
2. **规范目录一律 CC0**，不接受例外。若某个 `spec/` 文件需要 CC-BY-SA，它就不该放在 `spec/`。
3. **不允许 **`CC-BY-NC`**、**`CC-BY-ND`**、**`GPL`**、**`AGPL`** 出现在任何一格**。出现即视为许可缺陷，
按 `CONTRIBUTING.md` §5 处理。

> **本表只覆盖 `repo/` 这棵授权树。** 仓库根下的 `spec/ddl_w4.sql` 与 `evidence/*.py`
> 不在表内（它们位于授权树之外），其许可由**文件头 SPDX 声明**给出：根 `spec/` 为
> `CC0-1.0`、`evidence/` 为 `Apache-2.0`。`repo_lint.py` 的 R11 逐文件核对这两处的头，
> 值不符与缺失都会报红。改这两处的许可等于改许可决定，须同步本表、`NOTICE` 与 R11 的
> `TOP_DIRS`。

## 3. 文件头规则

| 文件类型 | 要求 | 示例 |
| --- | --- | --- |
| `.py` `.sh` `.yaml` | 前 3 行内 `SPDX-License-Identifier:` + 版权行 | `src/ledger_hash.py` |
| `.json` 等无法写注释的格式 | 同名 `.license` 伴生文件 | `spec/ledger-entry.schema.json.license` |
| `.md` | 以归属表为准，不强制头 | — |

JSON 不能写注释，这不是可以通融的技术细节：**没有伴生文件，一个 .json 文件就没有许可归属**，而"没有归属"在法律上等于"保留所有权利"。本仓库用 2 个伴生文件解决这个问题：ledger-entry.schema.json.license 与 contribution-entry.schema.json.license，一个 schema 一个，缺一即有文件没有归属。

## 4. 名称与许可分离

**代码/规范/数据的许可，不包含名称与商标的使用权。** 这是两套规则，写在两处：

|   | 覆盖什么 | 由谁管 | 文件 |
| --- | --- | --- | --- |
| 著作权许可 | 复制、修改、分发、商用 | Apache-2.0 / CC0 / CC-BY / CC-BY-SA | 本文件 §2 |
| 名称与标识 | 能否自称"众汲之井"、能否使用兼容性标识 | 商标规则 | `TRADEMARK.md` |

分离的原因：许可越开放，越需要名称受控。代码 CC0 之后，**唯一还能阻止"别人拿你的代码冒充你"
****的东西就是名称**。把名称放进许可里，要么污染许可（加限制即不再是开源），
要么放弃防冒充（许可不限制即无法阻止）。

## 5. 当前状态（2026-11-11）

| 项 | 状态 |
| --- | --- |
| 归属表 | ✅ 13 条规则，覆盖全部已跟踪文件；`credits.json` 与伴生文件由 `credits.json*` 一条覆盖 |
| 四份许可文件 | ✅ 4/4 存在；其中全文仅 1 份（Apache-2.0），3 份为指针（见 D-06） |
| 文件头/伴生文件 | ✅ 代码 1/1、JSON 3/3（两份 schema + `credits.json` 各带同名 `.license`） |
| 名录 | ✅ `CREDITS.md` + `credits.json`，由 R12/R13 双向校验（见下） |
| 第三方内容 | 无（NOTICE 已声明） |
| 名称 | ⚠️ 未检索、未注册，不得对外声称已获商标保护 |
| 仓库托管与公开 | ✅ 只读裸仓公开：`https://drawcommons.org/repo.git` |

> **名录不是「致谢页」。** `CREDITS.md` 登记三类人（著作权贡献者 / 数据贡献者 / 支持者），
> 因为这三类的法律基础和救济方式完全不同——支持者没有著作权，只有约定。把三者混成一张
> 感谢名单，是对支持者承诺了法律上不存在的东西。
