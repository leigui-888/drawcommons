# 众汲之井 · drawcommons

> **本版本未生效。** 协议 v2.2-r1 处于 30 日公示期（起算 2026-11-25，期满 2026-12-25，计划生效日 2026-12-26）；
> 2026-11-12 首次公示；11-14 因账本结构升级与隐私政策附录一处事实性更正、11-17 因产品号由 2.1 升为 2.2、
> 11-25 因协议许可表述按仓库实际更正，三度重新起算（见 `CHANGELOG.md`）。三份文本尚未取得执业律师书面意见，生效日按顺延规则顺延。
> 当前为 beta，账本内共 8 条：4 条结构验证（假 ID）＋ 2 条端到端联调演练（非真实互助）＋ 2 条真实互助（已闭环）。**可以试，不宜押。**

**这是公开可读副本；发布口在 [drawcommons.org](https://drawcommons.org)。此处打 tag 不等于发版。**

每一版的正式发布以 `drawcommons.org` 上带签名的 tag 与发布包为准：镜像站的 tag 被平台规则
保护，但规则可以由账号持有者关闭；自建裸仓的 `hooks/update` 与 `receive.denyNonFastForwards`
才是不可改写承诺的落点。要核验某一版，认发布口，不认这里。

## 这是什么

一个公共品化的记账与公示项目：账本字节锚定、判据机器可查、许可逐文件归属。
具体从哪里读起：

| 想了解 | 看 |
| --- | --- |
| **动手接入（十分钟，四个能跑的示例）** | [`repo/examples/README.md`](repo/examples/README.md) |
| **MCP 服务器（AI 客户端直连账本）** | [`repo/examples/04-mcp-server/README.md`](repo/examples/04-mcp-server/README.md) |
| 项目当前版本与状态 | [`VERSION.md`](VERSION.md)、[`version.json`](version.json) |
| 谁做了这个站（名录，逐版快照） | [`repo/CREDITS.md`](repo/CREDITS.md)、[`repo/credits.json`](repo/credits.json) |
| 自己动手验证，不用信任何人 | [`REPRODUCE.md`](REPRODUCE.md)——三条判据，无需联网与凭据 |
| 这套账本怎么部署 | [`repo/deploy/README.md`](repo/deploy/README.md) |
| 代码与数据的许可条件 | [`repo/README.md`](repo/README.md) |
| 版本间改了什么 | [`CHANGELOG.md`](CHANGELOG.md) |

## MCP server (Model Context Protocol)

This repository contains a complete MCP server implementation:
[`repo/examples/04-mcp-server/`](repo/examples/04-mcp-server/README.md) — a single-file
`server.py` (~1,150 lines, mostly comments) speaking the MCP protocol over stdio, **zero dependencies**
(Python 3.8+ standard library only; no `mcp` SDK, no pydantic, no httpx — the full rationale
is in that directory's README).

It exposes the public JSON API as five MCP tools. **All five only GET; the server has no
second HTTP verb** — including the drafting tool, which never sends anything:

| MCP tool | What it does |
| --- | --- |
| `ledger_items` | Fetch ledger entries; entry count and data notice are taken live, never hardcoded |
| `ledger_verify` | Recompute the hash chain locally over the fetched entries — verification happens on your machine |
| `ledger_export` | Fetch the canonical export bytes and the current anchor; `expect` compares against a value you recorded |
| `requests_list` | Public requests: what can be taken now, or what changed after a cursor |
| `entry_draft` | Draft the exact bytes a write would need signed, plus ready-to-paste commands — it drafts, it never sends |

The server is published on **PyPI** as
[`drawcommons-ledger-mcp`](https://pypi.org/project/drawcommons-ledger-mcp/)
(`pip install drawcommons-ledger-mcp`, or `uvx drawcommons-ledger-mcp`) and registered in the
official **MCP Registry** as `io.github.leigui-888/drawcommons-ledger`. Connect it in
Claude Code, Claude Desktop or Cursor and the model can query the ledger and re-verify the
hash chain itself, instead of you pasting numbers into the chat.

Listed in a third-party directory:

[![drawcommons-ledger MCP server on Glama](https://glama.ai/mcp/servers/leigui-888/drawcommons/badges/score.svg)](https://glama.ai/mcp/servers/leigui-888/drawcommons)

<sub>Drawn by Glama, not by us — the rating is theirs, and it changes without anyone editing
this file. GitHub proxies the image through `camo`, so viewing this page tells Glama nothing
about you; that proxy is also why the badge can lag behind this repo for a while.</sub>

## 验证 tag 签名

`v2.1-rc5` 起的 tag 带有 SSH 签名。克隆后直接 `git tag -v` 会报
`allowedSignersFile needs to be configured`——这不是签名有问题，是你还没指定信任文件。
信任文件就在仓库里，指定它即可：

```bash
# 仓库是公开的，https 即可匿名克隆，不需要 GitHub 账号或公钥
git clone https://github.com/leigui-888/drawcommons.git
cd drawcommons
git -c gpg.ssh.allowedSignersFile=repo/allowed_signers verify-tag v2.1-rc10
```

看到 `Good "git" signature for 2379731846@qq.com` 即通过。信任根说明（域名侧 DNS TXT、
指纹）见 `repo/CREDITS.md` §10。

## 不可改写

已存在的 tag 不删除、不移动；历史提交不改写。这在自建裸仓由服务端钩子强制执行，在本站
由 GitHub ruleset（`Restrict deletions` + `Restrict updates`，2026-11-12 实测拦截删/移）近似
执行。发现任何一个镜像站的 tag 与发布口不一致，以发布口为准，并请视为事故。

## 状态

代码可用、基线可复现；**协议三件套已齐、版本串统一 `v2.2-r1`（2026-11-17），`protocol_ready=true`**。

但这不等于可以开服务：三份文本**都未经执业律师书面审核**（`VERSION.md` 的生效条件 ③ 未满足），
计划生效日 2026-12-26 会按顺延规则顺延。`protocol_ready` 只说明「三件套齐、版本串一致、可进公示」。
详见 `VERSION.md`。

**公示已开始**：站点 `/terms` 及三份正文 `/terms/agreement`、`/terms/privacy`、`/terms/disclaimer`
自 2026-11-25 起重新公示 30 日（期满 2026-12-25）；全站页首标「公示中，尚未生效」。每份正文页顶印 sha256，
由服务对同一份字节现算，`/terms/<key>.txt` 可下载自核。三份公示稿共 3 处【待填】，
原样保留、不代填。
