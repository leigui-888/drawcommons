#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 老夫 <2379731846@qq.com>
/**
 * 示例 2 · 把公开接口变成一张你自己的卡片
 *
 * 做的事：拉 /api/ledger/items → 统计 → 生成一个自包含的 HTML 片段。
 * 零依赖：Node 18+ 自带 fetch，不需要 npm install。
 *
 *     node summarize.mjs                    # 输出到 out.html
 *     node summarize.mjs --out card.html
 *     node summarize.mjs --base https://drawcommons.org
 *
 * 为什么示例 1 重算哈希、这里却不重算：跨语言重算有坑，坑在浮点序列化。
 * Python 的 json.dumps(2.0) 是 "2.0"，JS 的 JSON.stringify(2.0) 是 "2"。
 * 同一份数据算出两个哈希，你会得到假的"校验失败"。要验哈希，用示例 1。
 * 这里只做数据消费——而消费数据不需要重算哈希，只需要把来源与许可标清楚。
 */

import { writeFileSync } from "node:fs";
import { argv, exit } from "node:process";

const args = argv.slice(2);
const opt = (name, dflt) => {
  const i = args.indexOf(name);
  return i >= 0 && args[i + 1] ? args[i + 1] : dflt;
};

const BASE = opt("--base", "https://drawcommons.org").replace(/\/+$/, "");
const OUT = opt("--out", "out.html");

/** 转义：数据来自网络，进 HTML 前一律当不可信处理。
 *  示例代码尤其不能教出注入漏洞——接入者会照抄。 */
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const TYPE_LABEL = { give: "给出", receive: "受领", payback: "回报" };
const VER_LABEL = {
  self_reported: "自称",
  counterparty_confirmed: "对方确认",
  third_party: "第三方",
};

function tally(items, key) {
  const m = new Map();
  for (const it of items) m.set(it[key], (m.get(it[key]) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
}

function table(title, rows, head = ["值", "条数"]) {
  if (!rows.length) return "";
  const body = rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
  return `<h3>${esc(title)}</h3>
<table><thead><tr><th>${esc(head[0])}</th><th>${esc(head[1])}</th></tr></thead>
<tbody>${body}</tbody></table>`;
}

async function main() {
  let payload;
  try {
    const res = await fetch(`${BASE}/api/ledger/items`, {
      headers: { "user-agent": "consume-json/1.0" },
      signal: AbortSignal.timeout(20000),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    payload = await res.json();
  } catch (e) {
    console.error(`取数失败：${e.message}`);
    return 2;                       // 取不到就是取不到，不返回 0
  }

  const items = payload.items ?? [];
  const tail = items.length ? items[items.length - 1].hash : "0".repeat(64);

  // 按单位分组求和：小时与「件」不是同一种量，加在一起是个没有意义的数。
  // 这不是洁癖——源头 spec 就为了「不把不同量纲相加」才把 quantity 与 unit 拆开。
  const byUnit = new Map();
  for (const i of items) {
    if (i.type !== "give") continue;
    const u = i.unit || "(无单位)";
    byUnit.set(u, (byUnit.get(u) ?? 0) + (Number(i.quantity) || 0));
  }
  const giveText = [...byUnit].map(([u, n]) => `${n} ${u}`).join("　+　") || "0";

  const STYLE = `<style>
  .dc-card{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:46rem;
    padding:1.2rem 1.4rem;border:1px solid #d8d8d8;border-radius:10px;color:#1a1a1a;
    background:#fff;line-height:1.6}
  .dc-card h2{margin:0 0 .4rem;font-size:1.1rem}
  .dc-card h3{margin:1.1rem 0 .4rem;font-size:.9rem;color:#555}
  .dc-card .dc-sub{margin:0 0 .2rem;color:#333;font-size:.9rem}
  .dc-card code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.85em}
  .dc-card table{border-collapse:collapse;width:100%;font-size:.88rem}
  .dc-card th,.dc-card td{border-bottom:1px solid #eee;padding:.32rem .5rem;text-align:left}
  .dc-card th{color:#666;font-weight:600;font-size:.8rem}
  .dc-card .dc-note{margin:1rem 0 0;color:#666;font-size:.8rem}
  .dc-card .dc-credit{margin:.6rem 0 0;padding-top:.6rem;border-top:1px dashed #ddd;
    color:#777;font-size:.76rem}
  .dc-card .dc-credit a{color:#666}
</style>`;

  const html = `<!-- 由 examples/02-consume-json/summarize.mjs 生成，勿手改 -->
${STYLE}
<section class="dc-card" lang="zh-CN">
  <h2>众汲之井 · 账目概要</h2>
  <p class="dc-sub">共 <b>${items.length}</b> 条记录，链尾 <code>${esc(tail.slice(0, 16))}…</code>
     ，其中「给出」合计 <b>${esc(giveText)}</b>（按单位分列，不跨量纲相加）。</p>
  ${table("按状态", tally(items, "type").map(([k, v]) => [TYPE_LABEL[k] ?? k, v]))}
  ${table("按类别", tally(items, "category"))}
  ${table("可核验程度", tally(items, "verifiability").map(([k, v]) => [VER_LABEL[k] ?? k, v]))}
  <p class="dc-note">${esc(payload.data_notice ?? "")}</p>
  <p class="dc-credit">众汲之井 2.0 资源清单，来源：<a href="${esc(BASE)}/api/ledger/items">${esc(BASE)}</a>，许可 CC-BY-4.0</p>
</section>`;

  writeFileSync(OUT, html, "utf8");
  console.log(`${items.length} 条 → ${OUT}`);
  console.log("提示：样式已内联在片段里（类名统一 dc- 前缀，不会撞你自己的样式），");
  console.log("     可直接嵌进任何页面；但别删掉最后那行署名——CC-BY-4.0 的唯一条件就是它。");
  return 0;
}

exit(await main());
