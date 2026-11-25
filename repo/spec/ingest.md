<!-- SPDX-License-Identifier: CC0-1.0 -->
<!-- Copyright 2026 老夫 <2379731846@qq.com> -->

# 写入面（ingest）· v2.2 草案

> 状态：**草案（随 r6 出件升 `2.2.0`）**。
> 配套：`request.schema.json`（需求单）、`entry.schema.json`（账目条目）、
> `../ddl_v1.4.sql`（表结构）、`../deploy/app/{ingest,signing}.py`（实现）。

## 0. 一句话

四条 POST，请求体自签。**不建会话、不发 token、不存 cookie**——主体就是那把钥，
服务端不记得「你是谁」，每次重新验。

## 1. 为什么是另一个进程

公开页（`app.py`）以只读方式挂账本卷，这一点写在部署口径里，也是「公开页攻击面
少一整类」的全部依据。同一个进程里加 `do_POST`，就得把那个卷改成读写——那条承诺
当场退化成一句注释。

所以写入面是独立容器：卷只对它读写，对 `app` 仍只读。**读面与写面共用的只有
`ledger_store.py` 里的那套「三表 → 条目 → 建链」**，因为两份实现分叉的失败方式
不是报错，而是「写进去的 hash 与读出来的链对不上」，且只在第三方复算时暴露。

## 2. 端点

| 方法 | 路径 | 做什么 | 谁能写 |
| --- | --- | --- | --- |
| POST | `/api/v1/party` | 登记主体公钥 | 持有该私钥的人（签名即证明） |
| POST | `/api/v1/request` | 追加一行需求状态；`delivered` 那一次**同时产出两条账目** | 发布方（open / withdrawn）或认领方（claimed / delivered / 回退 open） |
| POST | `/api/v1/entry` | 追加一条账目 | 给方本人（`from_agent_id` 必须就是签名主体） |
| POST | `/api/v1/confirm` | 受方确认一条 `give`；若这一单因此齐了条件，顺手落 `closed` | 受方（`to_agent_id`）本人 |
| POST | `/api/v1/reject` | 受方拒收某一次交付（v1.6）。**不改需求单状态** | 发布方（`requested_by`）本人 |
| POST | `/api/v1/remind` | 认领方催一次尚未确认的交付（v1.7）。**不改状态**，24 小时一次 | 当前认领方（`claim_agent_id`）本人 |
| GET | `/api/v1/request/contact` | 取这条单双方的联系方式（v1.7）。**要签名** | 这条单的发布方或当前认领方 |

另有 `GET /healthz`（探活，不碰库）。其余路径 404、其余方法 405。

`GET /api/v1/request/contact` 是本进程里唯一的**读**端点，放在这里而不是读面，原因不是性能：
联系方式只在「双方认领之后」可见，而读面是匿名的（`/r/<id>` 谁都能打开、站点禁脚本）。
验签才能回答「问的人是谁」，读面回答不了。它走同一套信封签名，`method` 是 `GET`、`body` 为空
（摘要为空串的 sha256），查询串不参与签名（与 `?dry_run=1` 同一条规矩）。

`receive` / `payback` **不接受直写**：它俩没有主体列，只能通过 `mutual_id` 追到需求单
上的认领方；而在 r6 的流程里它们由 `delivered` 那一次转换当场生成（§4.5）。
现在开个直写口，等于先承认「没有主体也能进账」，之后再关掉就是改协议。

`closed` 与 `expired` 同样不接受直写：前者是**可判定的事实**（两条账目在链上 + 受方签过
`give`），由那次确认顺手写；后者由窗口到期触发——具体是写入面自己顺带结算
（`Writer.sweep_expired`：进程启动一次、每次真写前一次），它只认库里那两列，没有调用方
能指名哪一单。**API 不能宣布一件系统还没挣到的事，也不该让人去宣布一件已经挣到的事**
——这两种请求在接口上分不出。

### 2.1 读口不在这里：`GET /api/v1/requests`

需求单的发现口是**读**，落在公开页进程（`app.py`），不落在写入面：

| 方法 | 路径 | 落在哪 | 为什么 |
| --- | --- | --- | --- |
| GET | `/api/v1/requests` | `app`（卷只读挂入） | 不写库、不验签、读的是需求单而不是账目 |

放进写入面在代码上没有任何区别，但会让「ingest 只做写」这条部署口径变模糊——而
那条口径正是「公开页物理上不能写」的另一半。所以宁可让 Caddy 多一条精确路由。

参数三个，各管一件事：

| 参数 | 取值 | 作用 |
| --- | --- | --- |
| `since` | `c1.<created_at>~<request_id>` | 增量。不带则给「最近一屏」 |
| `state` | `open` / `claimed` / `delivered` / `closed` / `withdrawn` / `expired` | 过滤**当前状态**。`expired` 自 v1.5 起不再进视图，查它永远是空集——要知道某一单为什么过期，去 `/r/<id>` |
| `limit` | 1–200，默认 20 | 页大小 |

```json
{"ok": true, "endpoint": "requests", "contract": "v1",
 "since": "c1.2026-11-14T00:00:00Z~rq_abc12345", "state": "open", "limit": 20,
 "items": [], "count": 0, "has_more": false,
 "next_cursor": "c1.2026-11-14T00:00:00Z~rq_abc12345"}
```

四条约定：

1. **不带 `since` 给「最近的」**：倒序取 `limit` 条后翻正。新来的 agent 要的是「现在
   有什么可接的」，不是三年前的第一条。
2. **带 `since` 给「之后追加的」**：正序。一单变状态时当前行的时间会变新，所以它会
   再出现一次——那是通知，不是重复。
3. **`next_cursor` 原样退回**：没有新行时等于请求里那个 `since`，不会跳过空窗。
4. **坏游标回 `400 bad_cursor`**，不静默从头开始。后者会让调用方以为在拿增量、其实
   每次都在重放全量，而且永远不会知道——这是游标接口最坏的失败方式。

读的是 `v_public_request`，与公开页同一口径（一单一行当前状态；`closed` / `withdrawn`
按 90 天收窄、`expired` 立即不收，未认领的单按截止时刻或发布满 90 天收窄——
见 request.md §4②）。填了截止的那些，
在收窄之前就已经被写成 `expired`（`Writer.sweep_expired`，进程启动一次、每次真写前一次）；
空串那些只收窄、状态不动。
游标用 `(created_at, request_id)` 而不是 `seq`：视图里一个 `request_id` 只有一行，
二元组已唯一；也不用 offset——offset 在 append-only 表上遇到并发插入会漏行，而漏掉
的需求单不会报错，只会「谁都没看见」。

错误码不在 `DGB_ING_*` 体系里：读口是公开面，出错只回 `bad_limit` / `bad_state` /
`bad_cursor` 三个字符串，与既有 `/api/ledger/*` 的 `data_layer_unavailable` 同一形状。
给读口编一套新码，只会让人以为它和写入面是同一类东西。

## 3. 签名载荷（逐字节）

请求头四件套：

| 头 | 值 |
| --- | --- |
| `X-DG-Party` | 主体标识 |
| `X-DG-Issued` | `YYYY-MM-DDTHH:MM:SSZ`（UTC，秒级，必须带 `Z`） |
| `X-DG-Nonce` | 22–64 位 `[A-Za-z0-9_-]`，每次请求新生成 |
| `X-DG-Sig` | SSHSIG armor 的 base64（标准字母表，保留填充） |

被签的是下面这段（UTF-8、LF、无 BOM、末行有换行）：

```
drawcommons-ingest-v1\n
POST\n
<路径>\n
<party>\n
<issued>\n
<nonce>\n
<请求体原始字节的 sha256，64 位小写十六进制>\n
```

三条不能省的约定：

1. **签的是请求体原始字节的摘要，不是规范化 JSON。** 规范化就要双方对同一份对象算出
   同样的字节，`json.dumps` 少写一个 `separators` 就差一个空格（第 01 步实测：规范化
   序列化能验过、默认序列化立刻验不过）。客户端发什么字节，服务端就哈希什么字节，
   中间不存在第二套序列化。
2. **路径在载荷里。** 否则一份签给 `/api/v1/party` 的请求体可以被原样送到
   `/api/v1/entry`——签名对、语义错，是最难发现的那类重放。
3. **读口也用同一段载荷格式**（v1.7）：`method` 写 `GET`，`<请求体原始字节的 sha256>` 是空串的
   摘要（`e3b0c442…`）。读口没有自己的载荷格式——多一套就多一处会漂的地方。
4. **namespace 是 `drawcommons-ingest`。** 与 tag 签名、条目确认（`drawcommons-confirm`）
   同一套 SSHSIG 工具链。namespace 由容器校验：拿 git 的签名来当写入面凭证会被
   直接拒绝（实测 `namespace does not match`），域隔离不靠人记得。

签名命令与验签命令（与仓库 tag 同一套工具）：

```bash
ssh-keygen -Y sign   -f <私钥> -n drawcommons-ingest -   < payload > sig
ssh-keygen -Y verify -f allowed_signers -I <party> -n drawcommons-ingest -s sig < payload
```

## 4. 三个端点的字段

### 4.1 `POST /api/v1/party`

```json
{"party_id": "pt_alice", "pubkey": "ssh-ed25519 AAAA…", "display_mode": "pseudonymous"}
```

- 第一次登记时库里还没有这把钥，所以**验签用的是请求体里自带的那把**——这正是
  「持有私钥」的证明。签名主体必须等于 `party_id`。
- 只接受 `ssh-ed25519`（blob 51 字节、前缀固定，本地即可判完，不调用外部进程）。
- `display_mode` 只接受 `pseudonymous`。实名展示需要 `real_name_ref`（脱敏串或外部
  指针），那个值从公网接口走进来就会留痕，留在运维侧写库。
- 已登记同一把钥 → 200 幂等，**不改任何字节**（连 `updated_at` 都不动：重试不该把
  「主体何时更新过」这条信息填满噪声）。已登记另一把钥 → `DGB_LED_018`，换钥 = 换
  `party_id`。
- **主体标识是先到先得的自选假名。** 没有中心分配、没有账号体系，所以谁先登记谁得。
  这不是疏忽，是没有账号体系时要付的代价；能查到的只有「这把钥在某个时刻登记了这个
  名字」，而这个名字本来就只是个假名。真要防占用，就得引入注册与身份核验，那是另一
  件东西（见 §7 出界）。

### 4.2 `POST /api/v1/request`

字段与 `request.schema.json` 同一套，去掉服务端自己算的三样：

| 客户端带 | 服务端算 |
| --- | --- |
| `request_id`、`state`、`category`、`need_desc`、`window_expires_at`、`requested_by`、`claim_agent_id`、`evidence_uri`、`occurred_at`、`note` | `seq`（= 当前最大 + 1）、`created_at`（本行落库时间）、`state` 的合法性 |

- `seq` 与 `created_at` 不接受客户端自带。`created_at` 记的是**本行**的时间而不是首行
  时间，公开视图的 90 天规则作用在 `closed` / `withdrawn` 行上，「之后 90 天从列表隐藏」才成立。
- 谁能推进哪一步：`withdrawn` 只能由 `requested_by` 提交；`claimed` / `delivered` 只能由
  `claim_agent_id` 提交（且必须带）。`open` 分两种：第 1 行（发布）只能由 `requested_by`；
  非第 1 行（**回退**，v1.6）由 `requested_by` 或**当前** `claim_agent_id` 提交。
  不是「有钥就能写」。
- **推进状态的每一条路都不能改条款**（v1.6）。共四处：
  ① `claimed → open` 回退时，`category` / `need_desc` / `window_expires_at` / `note`
  一律沿用上一行，请求体里夹带的新值**不采信**（静默沿用）；`claim_agent_id` 置空。
  ② `open → claimed`、`claimed → delivered` 若请求体里带了这四个字段之一且与上一行不等，
  **直接拒**（`DGB_LED_037`）——静默改写比拒绝更坏，人以为自己的修改生效了。
  只比「带了的键」：脚本按最小字段提交时不该被「你没带 note」判成改了 note。
  ③ 交付的 `claim_agent_id` 必须与认领时一致，否则等于绕过先到先得把单子转手（`037`）。
  ④ 发布时 `window_expires_at` 若不填，按发布 + `MAX_WINDOW_DAYS`（90）天到期；填了则
  不得晚于那个时刻（`DGB_ING_009`）。**窗口最长 90 天**，与「不填按 90 天算」是同一个数。
  比较用的是**日期**不是时刻（`date(?) <= date('now','+90 days')`）：页面上的日期框给的是
  当地的一天，按时刻比会让 UTC+8 的人选「第 90 天」时被多出的 8 小时顶出去。
- `state=withdrawn` 的行**沿用上一行的 `claim_agent_id` / `evidence_uri` / `occurred_at`**
  （v1.6）：撤掉的可能是已经被接过的单，当前视图若看不到认领方，等于抹掉了「撤掉的是谁接的」。
- `state=delivered` 是一个**转换**，不是一行状态：它在同一事务里产出 `give` + `receive`
  两条账目（§4.5）。响应因此比别的状态多一个 `entries` 数组。

### 4.3 `POST /api/v1/entry`

```json
{"kind": "give", "give_id": "g_…", "from_agent_id": "pt_alice", "to_agent_id": "pt_bob",
 "category": "compute", "quantity": 2, "unit": "hour", "occurred_at": "2026-11-14T00:00:00Z",
 "mutual_id": null, "note": "…"}
```

- `from_agent_id` 必须就是签名主体：替别人记「他给过东西」不是本协议的动作。
- `occurred_at` 必填（三类条目都有时间列，r6 的承诺）；`rule_version` 可选，只接受
  已知取值（当前只有 `pr_v1.1.0`）。新的规则版本串属第 07/08 步的版本串批，届时只改
  一处常量；在此之前，经本接口写入的条目一律标 `pr_v1.1.0`，而 `occurred_at` 仍必填——
  **接口比 schema 严**，这不算矛盾：schema 管「什么算合格」，接口管「我这扇门收什么」。
- `scope` 不由客户端指定，由 `mutual_id` 是否可判定推出，与 `ddl_w4.sql` v1.2 的
  一次性回填同一条规则。
- 响应带 `hash` 与 `prev_hash`，**在同一事务里算**：哈希依赖排序后的前一条，提交之后
  再算，中间插进来一条会让返回的哈希作废，而客户端拿它去签名（第 04 步双签）就会签在
  一个已经不存在的链位置上。

### 4.4 `POST /api/v1/confirm`

```json
{"kind": "give", "entry_id": "g_…", "sig": "-----BEGIN SSH SIGNATURE-----\n…"}
```

**两个签名，两件事。** 请求头那套（§3）证明「这个请求是这把钥发的」；`sig` 字段证明
「这个人认可这条已经发生的事」。前者签请求体摘要，后者签条目本身——互相顶替不了。

内层签的是下面这段（UTF-8、LF、末行有换行），namespace 是 **`drawcommons-confirm`**：

```
drawcommons-confirm-v1\n
<entry_id>\n
<该条目在当前链上的 hash>\n
```

三行各拦一种伪造：第一行拦「把写入面签名挪来当确认」（实测 `namespace does not match`）；
第二行拦「把 A 条目的确认挪到 B 条目」；第三行拦「条目被换掉」——hash 变了，重建的载荷
就不同。少任何一行，都有一种挪过去照样验得过的伪造。

- **`hash` 由服务端从库里重算**（`build_chain` 的那套口径），客户端给的一律不采信。
  采信客户端就等于让签名去保护客户端自己写的那句话：攻击者签一句「我认可 `g_x` +
  我自己编的 hash」就能造出一条确认。
- **`payload` 可选，只用于自检**：带上就与重算值逐字节比，差一个字节 → `DGB_LED_034`；
  不带则服务端自己拼。**库里存的永远是重算值**，不是客户端交上来的那段。
- 确认人是签名主体：`party_id` / `key_fp` / `signed_at` 都不接受客户端自带（带了 → `DGB_ING_018`）。
  `key_fp` 由 `party.pubkey` 算，`signed_at` 由服务端盖章。
- 只有 `give` 可确认。`receive` 没有第二档：它由 `delivered` 那一次推出来，而那次提交
  本身已经由认领方签过——两个主体各签了一次，再签一遍只是同一句话多一个可以撒谎的副本。
- 只有**受方**能确认（`DGB_LED_031`）。给方自签不叫「两个人各确认了一次」，是「一个人
  说了两遍」；第三方签属于 `third_party_anchored`，是另一档，不从这个口进来。
- **一条目一确认，不覆盖、不可撤**（`DGB_LED_035`；`UPDATE`/`DELETE` 被 `DGB_LED_012/013` 拦）。
  要做第二次确认，那就不是确认，是另一件事。
- 确认**不进条目、不改任何条目的 hash**，也不动 `verifiability` 列。它单独进
  `entry_confirm` 表，导出时进顶层的 `confirmations` 数组——与 `items` 并列，因此进锚值
  但不进链（第 05b 步上线后对外可见）。

响应：

```json
{"ok": true, "endpoint": "confirm", "party": "pt_bob",
 "kind": "give", "entry_id": "g_…", "key_fp": "SHA256:…",
 "entry_hash": "…", "payload": "drawcommons-confirm-v1\ng_…\n…\n"}
```

**签之前别让任何一层替你转换换行。** `subprocess(text=True)` 在 Windows 上会把 stdin 的
`\n` 写成 `\r\n`；HTTP 库、序列化层、文本模式同理。本机实测踩过：其余 15 项全绿，唯独
「正确导出件验签」失败，报文是 `incorrect signature`——差的就是一个字节。

### 4.5 `delivered` 的转换：一次交付，两条账目

`state=delivered` 的请求体与别的一样，只是它落库时**多产出两条账目**，同一个事务：

```json
{"request_id": "rq_abc12345", "state": "delivered", "category": "compute",
 "need_desc": "…", "requested_by": "pt_alice", "claim_agent_id": "pt_bob",
 "evidence_uri": "ipfs://…/handover.txt", "occurred_at": "2026-11-14T09:00:00Z"}
```

```json
{"ok": true, "endpoint": "request", "party": "pt_bob", "request_id": "rq_abc12345",
 "seq": 3, "mutual_id": "m-rq_abc12345",
 "entries": [{"entry_id": "g-rq_abc12345", "index": 7, "hash": "…", "prev_hash": "…"},
             {"entry_id": "r-rq_abc12345", "index": 8, "hash": "…", "prev_hash": "…"}]}
```

四条必须知道的：

- **两条都不是你提交的，是从那条已签的行推出来的。** `give` 的给方是 `claim_agent_id`、
  受方是 `requested_by`；`receive` 带 `evidence_uri` 与 `occurred_at`，`state='delivered'`。
  `quantity`/`unit` 留 null——需求单没有数量字段，编一个数就是造假。
- **id 是派生的**：第一轮是 `g-<request_id>` 与 `r-<request_id>`；第二轮起带 `-d<n>`
  （`n` = 该单第几条 `delivered` 行，v1.7）。所以受方不必问你，也能算出该确认哪一条，
  并从 `/api/ledger/items` 取到它的 hash。第一轮不加后缀，是因为历史条目就叫那个名字——
  改格式等于让链上的 id 变。
- **重发同一次交付是幂等的**：字段全一致 → `200` 且 `already: true`，附上上次那两条的
  位置与 hash，不再写一个字节。字段有一处不一致 → `422 DGB_LED_029`——那不是重试，
  是想改已入账的凭据，凭据以第一次为准。
- **`entries` 里的 hash 是那一刻的**。后面再有人记账，这两个 hash 可能变（排序决定
  `prev_hash`，不由插入顺序决定），所以确认之前请重新从链上取一次——服务端也是这么做的
  （§4.4）。

**受方确认之后单子会自己关掉。** `POST /api/v1/confirm` 成功时，如果这条 `give` 的
`mutual_id` 指向一张 `delivered` 的需求单，服务端追加一行 `closed`（完整复制上一行、
只换 `state`），响应里多一个 `"closed_request": "rq_abc12345"`。没有单独的「关闭」接口：
`closed` 是「双签齐 + 两条账目在链上」这件事的名字，那件事一发生它就成立。

### 4.6 `POST /api/v1/remind`

```json
{"request_id": "rq_abc12345", "seq": 3, "sig": "-----BEGIN SSH SIGNATURE-----\n…"}
```

`seq` 指向当前那条 `delivered` 行；`sig` 是对下面这段的 SSHSIG（`drawcommons-remind` 域，
与拒收分开）：

```
drawcommons-remind-v1\n
<request_id>\n
<seq>\n
```

- **只有当前认领方能签**（`DGB_LED_039`）：发布方催自己没有意义，第三方催不是他的事。
- **24 小时一次**（`DGB_LED_038`）：用服务端盖章的 `signed_at` 判，不采信客户端时间——
  否则填成昨天就绕过去了。冷却写在触发器里，应用层那道只是为了让错误信息能说「还差几小时」。
- **不改状态、不改条款**：单子仍停在 `delivered`，下一步仍只有发布方能走（确认或拒收）。
- 重发同一份不会产生第二条（同一秒撞主键、跨秒撞冷却），它本来也不该被当成「又催了一次」。

### 4.7 `GET /api/v1/request/contact`

```
GET /api/v1/request/contact?id=rq_abc12345
X-DG-Party: pt_bob
X-DG-Issued: 2026-11-17T02:00:00Z
X-DG-Nonce: 32 位随机串
X-DG-Sig: <对 GET 载荷的签名>
```

```json
{"ok": true, "request_id": "rq_abc12345", "state": "delivered",
 "requested_by": "pt_alice", "claim_agent_id": "pt_bob",
 "poster_email": "alice@example.org", "claimer_email": "bob@example.org",
 "party": "pt_bob", "key_fp": "SHA256:…"}
```

- **只给这条单的两方**，且只在 `claimed` / `delivered` / `closed` 时给。没认领、不是当事人、
  单不存在——三种一律 `404 not_found`，不区分。区分它们就成了一个探测接口。
- 两方拿到的是同一个结构，包括自己那一格：本人本来就知道自己的地址，遮掉只会让客户端
  多一个特判。
- 这两列**不在任何公开视图里**，也不在 `/r/<id>` 的渲染数据里（`load_request_detail` 会把
  它们剥掉）——单页是匿名可读的，渲染上去就是公开。

## 5. 错误码

传输与鉴权层用 `DGB_ING_*`；数据库约束仍然用 `DGB_LED_*`（原样透传，不翻译）。

**下表是全集：44 条，等于「代码里会抛的」∪「已装触发器会抛的」。** 2026-11-15 之前它
只列了 ING 那 20 条，剩下的 22 条散在散文与两张 Python 字典里——三者各说各话过一次
（见本节末的 `022`）。现在由 `_ops/w0/error_codes_check.py` 守着：码表、状态表、
代码、触发器四处必须一一对上，多一条少一条都红。

| 码 | HTTP | 含义 |
| --- | --- | --- |
| `DGB_ING_001` | 401 | 缺签名材料，或四件套形状不对 |
| `DGB_ING_002` | 401 | 验签失败（签名/请求体/路径/主体任一不符） |
| `DGB_ING_003` | 401 | 主体尚未登记公钥 |
| `DGB_ING_004` | 401 | `issued_at` 在时间窗之外 |
| `DGB_ING_005` | 409 | nonce 已用过（重放） |
| `DGB_ING_006` | 400 | 请求体不是 JSON 对象 |
| `DGB_ING_007` | 404 | 未知端点 |
| `DGB_ING_008` | 400 | 公钥形状非法（非 ed25519 / 非单行 / 超长） |
| `DGB_ING_009` | 400 | 字段缺失或形状不对 |
| `DGB_ING_010` | 400 | 不支持的 `display_mode` |
| `DGB_ING_011` | 403 | 该状态或该类型不接受直写，或不是你的动作 |
| `DGB_ING_012` | 409 | 该公钥已登记在另一个主体名下 |
| `DGB_ING_014` | 409 | `request_id` 已存在且 `seq` 撞车（并发兜底；常态由 `DGB_LED_020` 拦） |
| `DGB_ING_015` | 429 | 一分钟内写得太多（每主体 30 次，内存计数，重启即清空） |
| `DGB_ING_016` | 422 | 库拒绝但没给出可识别的码（兜底，出现即为缺陷） |
| `DGB_ING_017` | 409 | 主键冲突：该 ID 已被使用 |
| `DGB_ING_018` | 400 | 不认识的字段 |
| `DGB_ING_019` | 400 | 未知 `rule_version` |
| `DGB_ING_020` | 413 | 请求体超过 64 KiB |
| `DGB_ING_021` | 411 | 缺 `Content-Length` |
| `DGB_ING_022` | 400 | 发布方认领自己发的单（一单的发布方与认领方必须是两个主体） |
| `DGB_LED_012` | 403 | 对 `request` / 三张账目表 / 归档表的 `UPDATE` 被拒（账本只追加） |
| `DGB_LED_013` | 403 | 对同一批表的 `DELETE` 被拒（账本只追加） |
| `DGB_LED_014` | 422 | `archive_magnitude_v1` 是只读归档表 |
| `DGB_LED_015` | 422 | 撤回同意是终态，不可撤销、不可改回 |
| `DGB_LED_016` | 422 | 实名展示须显式绑定 `real_name_ref`（本端点不收实名） |
| `DGB_LED_017` | 422 | `party.pubkey` 格式非法（须为单行 ssh-ed25519） |
| `DGB_LED_018` | 409 | `party.pubkey` 登记后不可更换 |
| `DGB_LED_019` | 422 | 引用的主体未在 `party` 登记 |
| `DGB_LED_020` | 422 | 需求状态迁移非法（含「终态不得再有后继行」） |
| `DGB_LED_021` | 422 | `seq` 必须从 1 起连续，不能跳号 |
| `DGB_LED_023` | 422 | `claimed` 必须带 `claim_agent_id` |
| `DGB_LED_024` | 422 | `delivered` / `closed` 必须带 `occurred_at` 与 `evidence_uri` |
| `DGB_LED_025` | 422 | 一单的 `requested_by` 不可变 |
| `DGB_LED_027` | 422 | `mutual_id` 必须是 `m-rq_<request_id>` |
| `DGB_LED_028` | 422 | `mutual_id` 指向的需求当前必须处于 `delivered` / `closed` |
| `DGB_LED_029` | 422 | 交付已定局、字段与它不一致；或这一单没有可转换的交付 |
| `DGB_LED_030` | 422 | 确认指向的条目不存在 |
| `DGB_LED_031` | 422 | 只有受方可以确认该 `give` |
| `DGB_LED_032` | 422 | `give` / `receive` 的条数不得超过该单的交付次数（v1.7：多轮交付各成一对） |
| `DGB_LED_033` | 422 | `give` 的给方与受方不得是同一主体 |
| `DGB_LED_034` | 400 | `payload` 与服务端重算值不等，或确认签名验不过 |
| `DGB_LED_035` | 409 | 该条目已有确认（不可覆盖、不可重复） |
| `DGB_LED_036` | 403 | 拒收只能由发布方签（认领方与第三方不能拒别人的交付） |
| `DGB_LED_037` | 422 | 认领或交付时改了需求条款（这版没有编辑功能），或交付的认领方与认领时不一致 |
| `DGB_LED_038` | 409 | 同一张单 24 小时内已经催过一次（同一个认领方） |
| `DGB_LED_039` | 403 | 催告只能由当前认领方对 `delivered` 的单签 |

`DGB_ING_013` 留空（避开 `DGB_LED_013` 的删除码，免得日志里看串）。

**每个码还带一句 `hint`（下一步做什么）**，放在错误体里，与 `error` / `detail` 并列：

```json
{"ok": false, "error": "DGB_ING_009", "detail": "缺少字段：pubkey",
 "endpoint": "party", "hint": "按 detail 点名的字段补齐；请求体形状见 /agent.md §4 的示例"}
```

`hint` 的正文只存在一处（`ingest.py` 的 `CODE_HINTS`），本文件不复制它——两处都写，
迟早一处过期而另一处还在被人照着做。这里只保证「每个码都有一句」，以及它确实出现在
真实响应里（判据会打一条坏请求验一遍）。

**状态码只有一处映射**：`signing.py` 与 `ledger_store.py` 只带码，不带 HTTP 状态。

`029` 为什么不是 409：409 的语义是「撞了，换个键再来」，而这里换任何一个字段都只有一个
答案——凭据以第一次为准。把它报成冲突，会教客户端去重试一件永远不会成功的事。

`034` 与 `035` 在应用层判，不在触发器里：前者是「验签」这件事，触发器报不出来；后者
是复合主键冲突，触发器也不经手。`019` / `030` / `031` 仍由 DDL 给，且前置条件已排成
互不重叠，所以错误码是确定的，不看运气。

`029` 也在应用层判，而且**故意不走库**：重试与「改凭据」的差别是字段比对的差别，
库里没有一条约束能表达「与上一次提交逐字段相同」。它进了 `LED_STATUS`，与别的码同一条
映射路径——只是判断放在 `delivery_replay` 里。

一句话记住分界：**401 是「你不是你」，403 是「是你不该」，422 是「规矩不让」，409 是「撞了」。**

## 6. 重放与时间窗

两道闸，分工不同：

- **时间窗 15 分钟**（`issued_at` 偏离此刻超过 900 秒即拒，超前 60 秒内仍收）。它只是把
  攻击面收窄，不是重放防线——抓到一个签名之后慢慢重放，靠它拦不住。
- **nonce 表**（`ingest_nonce`）才是防线。**nonce 的提交与业务的提交在同一个事务里**：
  分两个库就有中间态，而「条目落了、nonce 没落」正是重放成立的那个方向。表里只留
  最近一小时的行，写入时顺手清。
- `X-DG-Sig` 之外的三个头（party / issued / nonce）都在载荷里，改任何一个都验不过。

### 6.1 演练（`dry_run`）

四条端点都接受 `?dry_run=1`（或请求头 `X-DG-Dry-Run: 1`）：**校验全跑、事务回滚**。
返回体里多一个 `"dry_run": true` 与一句说明；库、锚值、nonce 三样都不变。

- **为什么不另写一条「校验接口」**：那等于把校验逻辑复制一份到事务之外，两份迟早不一
  致，而演练的全部价值就是「和真写走同一条路」。实现是一行：`BEGIN IMMEDIATE` 之后
  `ROLLBACK` 而不是 `COMMIT`。
- **nonce 因此不被消耗**：同一个 nonce 可以演练多次再真写。这不是漏洞——nonce 防的是
  重放**已提交**的请求，而演练没有提交任何东西。反过来，如果演练也吃 nonce，没人会为了
  试一次而烧掉一个序号。
- **查询串不参与签名**（`build_payload` 用的是去掉 `?` 之后的 path），所以加 `dry_run`
  不需要重新签一次。这是刻意的：要重签才叫没人会用。
- **失败照样失败**：演练会把 400/409/422 原样报出来。它证明的是「这份请求能过」，
  而不是「服务端心情好」。

## 7. 出界（明确不做）

账号体系、口令、会话、OAuth、API Key、找回密码、写入额度售卖、批量导入、删除与更正
接口、撮合与推荐、评分。**更正靠追加新条目**（append-only），不靠改旧行——`UPDATE` /
`DELETE` 在库里有触发器拦着（`DGB_LED_012` / `013`）。

限速（每主体 30 次/分钟）**不是安全边界**，只是一道刹车：没有它，一把合法的钥就能把
需求表刷成一片噪声，而清理噪声要人工。它放在进程内存里，故意不落库——一个能被自己
刷满的计数器，落库只会变成第二种攻击面。

## 8. 自己验

```bash
python3 repo/deploy/app/selftest.py     # 99 项：未签 / 改一字节 / 重放 / 共用实现 / 确认层 / 入账转换
```

判据是四条主业，都能在这个脚本里看到：未签 → 4xx；改一字节 → 4xx；重放被拒；四条端点
共用同一验签实现（AST 扫描 + 把唯一实现换掉后四条端点同时失效）。另有两整节：§7 跑
确认层（受方确认 200、给方自签 422、重复确认 409、自造 hash / 换域 / payload 不符各 400、
条目不存在 422，以及「确认前后每一条条目的 hash 逐字未变」）；§9 跑入账转换（一次交付
恰好 +2 条、两条同 `mutual_id`、重发幂等、换凭据 422、自己给自己交付整体回滚、确认之后
单子自动关掉且关闭行保留凭据）。
