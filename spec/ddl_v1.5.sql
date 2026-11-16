-- SPDX-License-Identifier: CC0-1.0
-- Copyright 2026 老夫 <2379731846@qq.com>
-- 表结构增量 v1.5（SQLite）—— 必须运行在 spec/ddl_v1.4.sql（v1.4）之后
-- 版本 w4-ddl v1.5 / 2026-11-16
--
-- 本文件只做一件事：重建 `v_public_request`，让**未认领**的单子也会离开列表，
-- 并且让 `expired` 不再占着列表——两类单子一进来，列表就不再是坟场。
--
-- 为什么另起文件：`spec/ddl_v1.4.sql` 的字节已随 tag v2.1-rc20 冻结。原地改视图，同一个
-- 版本号下就会出现两份 v1.4——那比视图陈旧更糟。增量单独成文件，v1.4 的字节不动。
--
-- 只动视图，不动表：
--   `DROP VIEW` + `CREATE VIEW` 不改任何一行数据、不碰哈希链、不影响锚值（锚值只由三类
--   条目算出）。视图不是快照，是每次查询时求值的定义，所以这一条对**已经在跑的库**同样
--   立刻生效，不需要重算任何东西、不需要重跑 v1.3/v1.4。
--
-- 改了三处，都在 WHERE 里：
--
--   ① 未认领的单（`open`）分两支收窄：
--        a) 填了 `window_expires_at`：过了这个时刻即不再公开；
--        b) 没填（空串＝无期限）：自 `created_at` 起 90 天无人认领即不再公开。
--
--   ② `expired` 立即不收（v1.4 是「终态 90 天后」，这里把它单独拎出来）。
--      理由不是口味：v1.4 写这条时 `expired` 根本不会自动产生（当时没有触发者），
--      三类终态共用 90 天没暴露问题。v1.5 让写入面开始真的结算 `expired`
--      （`ledger_store.Writer.sweep_expired`），一旦共用 90 天，一张过期的单会**因为**
--      被结算成终态而重新出现在列表里，再等 90 天才走——正好把要清的东西又摆回来。
--      所以：`closed` / `withdrawn` 仍留 90 天（它们记的是真发生过的事，值得在架上
--      待一阵），`expired` 立即不公开（从来没发生过，列它没有信息量）。
--      `/r/<id>` 照旧永久可读——收窄的只有列表与发现口。
--
--   ③ a) 与 b) 的「不再公开」含义不同，必须分开说：
--      · a) 那一支同时有**真的终态**：截止过后写入面会写一行 `expired`，状态前进，
--        `/r/<id>` 显示「已过期」。视图这一支在 sweep 跑到之前兜底，两者不是重复。
--      · b) 那一支**只收窄、不写状态行**：`state` 仍是 `open`，`/r/<id>` 照旧显示「可接」，
--        知道 id 的人仍可认领。因为「空串＝无期限」是发布方选过的（request.md §3），
--        时钟不该替他改成「过期」。
--
--   90 是常量不是条款：改它不换版；改「是否保留」才换版（见 request.md §4②）。
--
-- 「取不到」不等于「验不过」：
--   `julianday()` 遇到解析不了的字符串返回 NULL，NULL 参与比较得 NULL，`NOT NULL` 还是
--   NULL，WHERE 视作不成立——那一行会被**藏掉**。方向反了。所以每个时间比较都套
--   `COALESCE(..., 0)`：格式坏的时间当成「没到期」处理，宁可多显示一条，也不误藏一条。
--   （v1.4 终态那句一并兜上，只改坏格式时的方向：从「藏」变成「显示」。）

DROP VIEW v_public_request;

CREATE VIEW v_public_request AS
SELECT request_id, state, category, need_desc, window_expires_at,
       requested_by, claim_agent_id, occurred_at, created_at, note
FROM v_request_current
WHERE state <> 'expired'
  AND NOT (state IN ('closed','withdrawn')
           AND COALESCE(julianday('now') - julianday(created_at) > 90, 0))
  AND NOT (
    state = 'open'
    AND (
      -- a) 有截止：过了截止时刻即不再公开（sweep 还没跑到时的兜底）
      (TRIM(COALESCE(window_expires_at, '')) <> ''
        AND COALESCE(julianday('now') > julianday(window_expires_at), 0))
      OR
      -- b) 无期限：自发布起 90 天无人认领即不再公开（状态不变）
      (TRIM(COALESCE(window_expires_at, '')) = ''
        AND COALESCE(julianday('now') - julianday(created_at) > 90, 0))
    )
  );
