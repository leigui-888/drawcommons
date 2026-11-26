# 示例 4 · 接进 AI 客户端（MCP）

**它解决的事**：让模型自己在账本里取数、自己复算一遍，而不是由你把数字粘进对话。

五个接口被包成五个 MCP tool。装在 Claude Code / Claude Desktop / Cursor 里之后，
「这个账本最近有什么」「现在有什么可接的」这类问题，答案来自账本本身，且**可以在你机器上验一遍**；
要发一条东西时，第五个 tool 会把「该签哪几个字节」算准，交给你去签。

**零依赖**：Python 3.8+，标准库。不装 `mcp` SDK，不装 httpx、pydantic。

```bash
python3 server.py                               # 直接跑（stdio，等客户端说话）
python3 selftest.py                             # 自检：握手 + 五个 tool 全过一遍
```

---

## 为什么不装官方 SDK

装 `mcp` 是最省事的写法，我们没这么写，三个理由：

1. **可审计。** 这个项目的全部资产是「你不用信我」。那么连工具本身也该能被一眼读完——
   `server.py` 一个文件，一千一百多行（大半是注释：写的是判断依据，不是复述代码），
   只有 GET。装了 SDK 之后，"它会不会写东西"就变成"你得相信它没写"，而这不是这个
   项目该让人做的让步。**0.2.0 加进来的 `entry_draft` 也没破这条**：它拼字节、开命令，
   一个 POST 都不发（见下文「entry_draft 为什么不自己发」）。
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

## 用 Docker 跑（目录站就是这么跑的）

仓库根有一个 `Dockerfile`，只为这件事存在：让目录站（Glama）能构建、能起、能问清五个 tool。

```bash
# 构建上下文是仓库根，不是本目录（代码在 repo/ 下，镜像是从根上取的）
docker build -t drawcommons-ledger-mcp .

printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | docker run --rm -i drawcommons-ledger-mcp
```

`-i` 不能省：stdin 一关，stdio server 就退出了。

镜像里只有一件事：`server.py` 一个文件。没有 pip install、没有构建期联网、没有 root
（uid 10001），74 MB，全部来自 `python:3.12-alpine` 本身。`.dockerignore` 把构建上下文
压到只剩那一个文件——本仓库有整棵 `0-snapshot`，不这么写等于每次构建都上传几百兆。

为什么 Dockerfile 放仓库根而不放本目录：Glama 只认仓库根的 Dockerfile，并且拿根当构建
上下文。代价是多一层 `COPY repo/examples/...`，写在这里，好过让人找不到入口。

---

## 五个 tool

| tool | 参数 | 返回 | 什么时候用 |
|---|---|---|---|
| `ledger_items` | `limit`（默认 20，上限 200）、`offset`、`type`（give/receive/payback） | 条目全文，带 `prev_hash` / `hash` | 要看具体记录 |
| `ledger_verify` | 无 | `verdict` + 服务端自述 + 本机重算 + 锚值 | 「这数据可不可信」 |
| `ledger_export` | `include_raw`（默认 false）、`expect`（可选，64 位十六进制） | 导出件 sha256（**锚值**）、字节数；可选原文；给了 `expect` 就回 `match` | 要锚值、要离线留存，或想跟你上次记下的值对一眼 |
| `requests_list` | `state`、`since`、`limit`（默认 20） | 需求单、`next_cursor`、`has_more` | 找可接的单，或按游标收增量 |
| `entry_draft` | `endpoint`、`party`、`body`、`query`、`issued`、`nonce` | 要原样发出的 `body_text`、七行载荷、`issued`/`nonce`、两段可直接粘的命令 | 要发一条东西，但不确定该签哪几个字节 |

`ledger_verify` 的 `verdict` 有三种：`agree`（两处对得上）、`chain_broken`（本机算出
断链，附首个失败序号）、`server_disagrees`（本机算通，但服务端自述的条数/链尾与它自己
给的条目对不上——这种不一致本身就是问题）。

### 它跟"把接口包一层"有什么不同

`ledger_verify` **不采信服务端的 `ok`**。它自己拉 `items`、自己拉 `export`，在本机
逐条重算 `sha256(prev_hash + "\n" + canonical(entry))`、查 `prev_hash` 是否接上一条、
对导出件算 sha256 当锚值，然后把「服务端说」与「本机算」并排放出来。

服务端说 ok 而本机算出断链时，这个 tool 报的是断链。**一个只会转述上游结论的 tool，
等于把上游的错误原样放大成"已验证"。**

### entry_draft 为什么不自己发

它的名字里有 draft，但它**不写、不发**：它拼字节、算摘要、打印两段可以直接粘进终端的
命令（`dry_run` 与 `send`），然后停下来。签名与发送留给你，或你本机的 CLI。

这不是没做完，是取舍：

- **它跑在你的机器上。** 一旦它能 POST，「它能替你发什么」就变成一个需要重新论证的信任
  问题（签名是谁给的、载荷是不是你想签的那一份、会不会被诱导发到别处）。这些都能论证，
  但论证的成本远高于不做——现在它的回答是一句话：**它只 GET 一个地址**。
- **它不校验字段，也不探测 id 存不存在。** 一个「这条会不会被拒」的免费校验器，是一个
  写入面刻意不提供的探测口。想先知道，就签完用 `?dry_run=1` 问真服务端：校验全跑、
  事务回滚、nonce 不消耗。`dry_run` 那段命令就是干这个的。
- **它不重算条目 hash。** 确认要签的 hash 是从 `/api/ledger/items` **读**来的，不是本机算的。
  重算要复制整条 `build_chain`（含入链次序 `ord` 的读法——那一列不进哈希，但决定顺序），
  而它的失败方式是「多数情况下算对了」。

**确认是两段**，因为确认有两个签名：先给三行内层载荷（附该条目此刻的 hash），你签完把
armor 放进 `body.sig`，再调一次拿信封。返回体里的 `stage` 说明你拿到的是哪一段。

**它覆盖不到的两件事**：`reject` 与 `remind`。它们的载荷要「当前那条 `delivered` 行的
`seq`」，而公开视图没有这一列——硬凑就得猜。这两件仍按 `/agent.md` 5.1 手工签。

### 一段别处没有的话

握手时 server 会给客户端一段 `instructions`，模型在会话开头读一次。**这段话是握手时现拼的**，
不是写死在包里的常量：

```
众汲之井账本（beta）。五个 tool，全部只 GET 一个地址：取条目、本机重算校验、取导出件与锚值
（可带 expect 比对）、取需求单，以及把一条写入「该签哪几个字节」算准（entry_draft：只拼字节
与给命令，不写、不发、不碰私钥）。
账本当前 N 条。这批数据的性质，站点自己写的是：「<data_notice 原文>」——
引用数字时请连同这句一起说。
协议版本与公示状态不在这个包里写死：版本号会过期，而过期的版本号比没有更糟。
要看当前协议版本与公示状态，以 https://drawcommons.org/terms 页为准。
链校验只证明字节未变，不证明条目描述的事发生过。
```

`N` 与那句 `<data_notice>` 来自握手时对 `/api/ledger/items` 的一次 GET（上限 4 秒、512 KB）。
**取不到时它一个数字都不说**，只写「这次没取到站点现状（原因），引用任何数字前先看
`ledger_items` 返回的 `data_notice`」——一条取不到就随便糊一句的提示，比没有更坏。

为什么费这个事：包一旦上传就**改不动**（PyPI 只能 yank 不能删）。早先这里写死了两句话——
账本当时有几条样例、协议当时处在哪个修订的公示期。两句当时都对，但都是快照：账本长出下一条、
协议换一版，那一刻起这个包就在所有人的机器上说假话，而修它意味着再发一个版本。现在这句话
只会说两种东西：站点此刻说的，或者「我没取到」。

这类前提写在 tool 描述里会随每次调用重复，写在 `instructions` 里只讲一遍——但它必须
存在，否则模型会把样例数字当真实数据转述出去，而这正是这个项目最不该出的错。

---

## 四条边界

**一、只读，且只连一个地址。** base URL 在启动时定死（`--base` 或环境变量
`LEDGER_BASE`），**tool 参数不能改它**。若允许调用方传 URL，这个 server 就成了一台开放
代理：它跑在别人机器上，能打到那台机器能打到的内网。五个 tool 都没有写路径，代码里也
没有第二个 HTTP 动词——包括 `entry_draft`（见第四条）。

**二、验的是字节，不是事实。** 链完整只说明「你拿到的这份与入链时一致」。一条诚实地
记录了假事的条目，哈希链一样完整。别把 `verdict: agree` 读成「内容可信」。

**三、beta，输出结构会变。** 账本现在是测试数据，条目数随时会变（握手时现取，见上一节）；
字段增删随账本版本走。所以五个 tool 都**没有写 `outputSchema`**——写了就等于承诺字段不增
不删，那是另一种说假话。客户端拿 `structuredContent` 时请按字段名取值，别按位置。

**四、算字节不算账。** `entry_draft` 只保证「给你的这串字节与它算的摘要是同一份」，不保证
那份请求会被接受。字段对不对、单号在不在、状态能不能走——这些是服务端在签名之后才回答的事。
把这两件事混成一件，就会出现「工具说没问题，服务端说 422」这种谁也解释不清的局面。

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

31 通过 / 0 失败
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
| 客户端里看不到这五个 tool | server 启动失败，或 stdout 被别的东西污染 | 直接 `python3 server.py` 手动跑，**stderr 的错误在客户端日志里通常看不到** |
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

四处版本号必须同值（`pyproject.toml`、`server.py` 的 `SERVER_VERSION`、`server.json` 的 `version`
与 `packages[0].version`），改一处改四处。包的版本一旦发出去就不可撤回（PyPI 只能 yank，不能删），所以宁可慢一版。

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
