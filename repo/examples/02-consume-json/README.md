# 示例 2 · 把接口变成你自己的卡片

**它回答的问题**：拿到这批公开数据，我能做出什么？

**零依赖**：Node 18+（自带 `fetch`），不需要 `npm install`。

```bash
node summarize.mjs            # 写出 out.html
```

产出一段自包含 HTML：条目总数、链尾、按状态/类别/可核验程度的分布，底部署名行。
样式已内联，类名统一 `dc-` 前缀，嵌进任何页面都不会撞你自己的样式。

## 数据长什么样

`GET /api/ledger/items` 返回：

```json
{
  "endpoint": "items",
  "count": 4,
  "genesis": "0000…0000",
  "data_notice": "测试期数据：W4 结构验证样例（4 条，假 ID）。…",
  "items": [ { "type": "give", "entry_id": "g_1", …, "prev_hash": "0000…", "hash": "e8ed…" } ]
}
```

一条记录 19 个字段，分四组：

| 组 | 字段 | 说明 |
|---|---|---|
| 身份 | `type` `entry_id` `mutual_id` `from_agent_id` `to_agent_id` | `type` 只有 `give` / `receive` / `payback` 三态 |
| 内容 | `category` `quantity` `unit` `note` | **没有金额字段，永远不会有**——资金面整体不在本规范内 |
| 上下文 | `occurred_at` `scope` `scope_unresolved` `magnitude` `duration_hours` | `scope: mutual` 表示双边互助 |
| 可核验 | `verifiability` `window_expires_at` `rule_version` | `verifiability` 是**标签**：`self_reported` / `counterparty_confirmed` / `third_party`。它是申报者的说法，不是系统的判定 |
| 链 | `prev_hash` `hash` | 最后两个，用于示例 1 的本地重算 |

字段的权威定义在 [`spec/entry.schema.json`](../../spec/entry.schema.json)（CC0，随便用）。

## 两个容易做错的地方

**一、不要把不同单位的 `quantity` 相加。**
`2 hour` 与 `3 件` 加不到一起。本脚本按 `unit` 分组求和，就是为了不产生一个没有意义的数。
源头 schema 把 `quantity` 与 `unit` 拆成两个字段，也是这个原因。

**二、`verifiability` 不是可信度评分。**
`counterparty_confirmed` 只表示"对方确认过这条记录存在"，不表示"这件事有社会价值"，
更不表示"这个人可靠"。按它排序、打分、做排行榜，都是在用标签冒充判断——
而这批数据的设计前提恰恰是**不做评分、不做排名**。

## 署名

数据是 CC-BY-4.0。唯一条件是**保留署名**，商用、改作、再分发都不需要另行许可：

```
众汲之井 2.0 资源清单，来源：https://drawcommons.org/api/ledger/items，许可 CC-BY-4.0
```

放页脚、放数据集描述、放 API 响应的 `meta.source` 都行，不限定格式。
生成器已经把这行写进产物末尾——**删掉它，你的使用就不再合规**。

## 为什么不在这里重算哈希

跨语言重算有个坑，且坑在数字上：Python 的 `json.dumps(2.0)` 是 `"2.0"`，
JS 的 `JSON.stringify(2.0)` 是 `"2"`。同一份数据，两种语言算出两个哈希，
你会得到一个假的"校验失败"，然后开始怀疑数据——而数据是对的。

要验证完整性，用 [示例 1](../01-verify-chain/)（Python，与服务器同源）。
这个示例只做消费。

## 许可

代码 Apache-2.0；它处理的数据 CC-BY-4.0。两者不冲突：代码可以闭源改造，
但输出的数据仍带署名义务。
