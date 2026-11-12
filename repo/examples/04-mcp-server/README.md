# 示例 4 · 接进 AI 客户端（MCP）

**它解决的事**：让模型自己在账本里取数、自己复算一遍，而不是由你把数字粘进对话。

三个只读接口被包成三个 MCP tool。装在 Claude Code / Claude Desktop / Cursor 里之后，
「这个账本最近有什么」这类问题，答案来自账本本身，且**可以在你机器上验一遍**。

**零依赖**：Python 3.8+，标准库。不装 `mcp` SDK，不装 httpx、pydantic。

```bash
python3 server.py                               # 直接跑（stdio，等客户端说话）
python3 selftest.py                             # 自检：握手 + 三个 tool 全过一遍
```

---

## 为什么不装官方 SDK

装 `mcp` 是最省事的写法，我们没这么写，三个理由：

1. **可审计。** 这个项目的全部资产是「你不用信我」。那么连工具本身也该能被一眼读完——
   `server.py` 一个文件，四百行，只有 GET。装了 SDK 之后，"它会不会写东西"就变成
   "你得相信它没写"，而这不是这个项目该让人做的让步。
2. **供应链。** SDK 拖着 pydantic 与 httpx。版本漂移的后果不是本地报错，而是**别人的
   客户端里**某天开始报错，而你在自己的机器上看不见。
3. **协议面很小。** stdio 传输就是「一行一条 JSON-RPC 消息」，需要的方法只有
   `initialize` / `tools/list` / `tools/call` / `ping`。为这四个方法拉十兆依赖，
   是把简单的事交出去维护。

代价写在明处：官方 SDK 会替你跟进协议演进（比如新的传输、新的能力协商）。我们只实现
2024-11-05 到 2025-06-18 这三个版本用得到的那一小块；协议大改时需要自己跟上。

---

## 装进客户端

把路径换成你机器上的**绝对路径**（`pwd` 那一下的输出）。

**Claude Code**（一条命令）

```bash
claude mcp add ledger -- python3 /绝对路径/examples/04-mcp-server/server.py
```

**Claude Desktop / Cursor**（JSON 配置，位置：macOS `~/Library/Application Support/Claude/claude_desktop_config.json`、
Cursor `~/.cursor/mcp.json`）

```json
{
  "mcpServers": {
    "ledger": {
      "command": "python3",
      "args": ["/绝对路径/examples/04-mcp-server/server.py"]
    }
  }
}
```

Windows 上命令写 `python`（或 `py`，参数加 `-3`），路径用正斜杠：
`"C:/Users/你/examples/04-mcp-server/server.py"`。

**连本地的服务**（改了代码先自己验一遍再加 `--base`）

```json
{"command": "python3", "args": ["/绝对路径/server.py", "--base", "http://127.0.0.1:8000"]}
```

---

## 三个 tool

| tool | 参数 | 返回 | 什么时候用 |
|---|---|---|---|
| `ledger_items` | `limit`（默认 20，上限 200）、`offset`、`type`（give/receive/payback） | 条目全文，带 `prev_hash` / `hash` | 要看具体记录 |
| `ledger_verify` | 无 | `verdict` + 服务端自述 + 本机重算 + 锚值 | 「这数据可不可信」 |
| `ledger_export` | `include_raw`（默认 false） | 导出件 sha256（**锚值**）、字节数；可选原文 | 要锚值，或要离线留存 |

`ledger_verify` 的 `verdict` 有三种：`agree`（两处对得上）、`chain_broken`（本机算出
断链，附首个失败序号）、`server_disagrees`（本机算通，但服务端自述的条数/链尾与它自己
给的条目对不上——这种不一致本身就是问题）。

### 它跟"把接口包一层"有什么不同

`ledger_verify` **不采信服务端的 `ok`**。它自己拉 `items`、自己拉 `export`，在本机
逐条重算 `sha256(prev_hash + "\n" + canonical(entry))`、查 `prev_hash` 是否接上一条、
对导出件算 sha256 当锚值，然后把「服务端说」与「本机算」并排放出来。

服务端说 ok 而本机算出断链时，这个 tool 报的是断链。**一个只会转述上游结论的 tool，
等于把上游的错误原样放大成"已验证"。**

### 一段别处没有的话

握手时 server 会给客户端一段 `instructions`，模型在会话开头读一次：

> 账本里现有 4 条结构验证样例，用假 ID，不是真实账目；引用数字时请说明这一点。
> 链校验只证明字节未变，不证明条目描述的事发生过。

这类前提写在 tool 描述里会随每次调用重复，写在 `instructions` 里只讲一遍——但它必须
存在，否则模型会把样例数字当真实数据转述出去，而这正是这个项目最不该出的错。

---

## 三条边界

**一、只读，且只连一个地址。** base URL 在启动时定死（`--base` 或环境变量
`LEDGER_BASE`），**tool 参数不能改它**。若允许调用方传 URL，这个 server 就成了一台开放
代理：它跑在别人机器上，能打到那台机器能打到的内网。三个 tool 都没有写路径，代码里也
没有第二个 HTTP 动词。

**二、验的是字节，不是事实。** 链完整只说明「你拿到的这份与入链时一致」。一条诚实地
记录了假事的条目，哈希链一样完整。别把 `verdict: agree` 读成「内容可信」。

**三、beta，输出结构会变。** 库里是 4 条假 ID 样例；字段增删随账本版本走。所以三个
tool 都**没有写 `outputSchema`**——写了就等于承诺字段不增不删，那是另一种说假话。
客户端拿 `structuredContent` 时请按字段名取值，别按位置。

---

## 自检

```bash
python3 selftest.py
```

```
握手
  ✅ 回协议版本　2025-06-18
  ✅ 声明 tools 能力
  ✅ 给了 instructions（beta 前提要开场讲清）
...
判据会报错吗（本地改一个字符）
  ✅ 原样通过　链尾 c8498a30cb61ea4e…
  ✅ 改一条就报错，且指到那一条　first_bad=1
  ✅ stdout 全是 JSON（没有半行日志混进来）

17 通过 / 0 失败
```

最后一项不是走形式：stdio 传输里多一行日志，客户端就会把整个 server 判成坏的，
而报错出现在**别人的**客户端里。自检里专门盯着 stdout 干不干净。

倒数第二项也不是：把线上条目改一个字符，`recompute()` 必须在那一条报错。**只会说
"通过"的判据不算判据**（同 `examples/01-verify-chain` 的 `--tamper`）。

退出码：`0` 全过、`1` 有失败、`2` 连不上。分得开，监控才不会把「网断了」记成「代码坏了」。

---

## 排错

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 客户端里看不到这三个 tool | server 启动失败，或 stdout 被别的东西污染 | 直接 `python3 server.py` 手动跑，**stderr 的错误在客户端日志里通常看不到** |
| `spawn python3 ENOENT` | PATH 里没有 python3 | 配置里改用绝对路径的解释器 |
| 中文变乱码 | Windows 控制台代码页 | 不会：这个 server 走 `stdout.buffer` 写 UTF-8，绕开了代码页 |
| tool 返回 `isError: true`「取不到数据」 | 网络或站点不可达 | 这不是校验失败。取不到数就说取不到，不当成通过 |
| 想改地址 | tool 参数里没有这个选项，故意的 | 启动时加 `--base`，或设 `LEDGER_BASE` |

---

## 要发到 MCP Registry 的话

Registry 只存元数据、不存代码，所以条目必须指向一个真实存在的包。本目录因此多了三样东西，
都是为发版准备的，读代码不需要它们：

| 文件 | 为什么在 |
| --- | --- |
| `pyproject.toml` | 打成 wheel，发到 PyPI。**源码仍只有 `server.py` 一份**，没有副本 |
| `README-pypi.md` | PyPI 长描述；第一行是 `mcp-name:` 标记，Registry 用它证明包是你的 |
| `server.json` | Registry 条目：`io.github.leigui-888/drawcommons-ledger`，pypi / stdio / `uvx` |

```bash
python3 -m pip wheel --no-deps -w dist .     # 出 wheel，不联网装依赖
python3 -m pip install --no-deps --target /tmp/x dist/*.whl   # 试装
```

三处版本号必须同值（`pyproject.toml` / `server.json` 的 `version` 与 `packages[0].version`），
改一处改三处。包的版本一旦发出去就不可撤回（PyPI 只能 yank，不能删），所以宁可慢一版。

**打包的代价写在明处**：wheel 里装的是顶层模块 `server`，不是 `drawcommons_ledger/` 包——
这是"不复制源码"换来的。真要当库用，得先重构成包目录。

### 想重建出一模一样的 wheel

默认构建**不可复现**：zip 条目里带构建时刻，同一份源码两次构建字节不同（实测过，
只差时间戳，大小一样）。那样记下来的 sha256 只是某一次构建的随机结果，没法用来核对。

固定时点即可复现：

```bash
cd repo/examples/04-mcp-server
SOURCE_DATE_EPOCH=1794499200 PYTHONHASHSEED=0 python3 -m pip wheel --no-deps -w dist .
sha256sum dist/*.whl
```

`1794499200` = 2026-11-13T00:00:00+08:00，是本版发布日的零点，不是随手取的值。
用这个值在同一份源码上重建，得到的字节与 PyPI 上那个文件逐字节相同；换任何时点都不会。

发布本身需要 PyPI 账号与 API token（只有持有者能做），步骤见 `_ops/R1-投放清单.md`。

---

## 许可

Apache-2.0（与 `src/` 同）。拿去改、拿去嵌进你自己的 agent，保留版权与许可声明即可。
接口返回的数据是 CC-BY-4.0，署名即可商用——但请保留「测试期样例、假 ID」这个前提，
别把它们当真实账目发布。
