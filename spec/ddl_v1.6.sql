-- SPDX-License-Identifier: CC0-1.0
-- Copyright 2026 老夫 <2379731846@qq.com>
-- 表结构增量 v1.6（SQLite）—— 必须运行在 spec/ddl_v1.5.sql（v1.5）之后
-- 版本 w4-ddl v1.6 / 2026-11-16
--
-- 本文件补四件事，都来自同一张图上的四个卡点（发布→认领→交付→结单的七种落点）：
--
--   ① `claimed → open`：认领人能把单子放回池子，不必等发布方同意。
--      此前 claimed 只有一个出口（delivered）和一个别人给的出口（发布方 withdrawn），
--      认领人接了之后没有任何退路——他没有能力兑现时，这张单会永久占着。
--
--   ② `open` 不再是「只能第一行」：回退必然产生一行非首行的 open。第 1 行仍必须是
--      open（发布这个动作没变），放松的只是「open 只能出现在第 1 行」这一半。
--
--   ③ 无期限不再等于永不过期：空串的 `window_expires_at` 按 `created_at + 90 天` 计算
--      到期。**这是语义变更，不是视图微调**：以前「不填＝不限时间」，现在「不填＝默认
--      90 天」。写入面的 `sweep_expired` 会照此写 `expired`，与填了截止的单走同一条路。
--      视图里那条「空串满 90 天不再公开」保留，但它从「唯一处置」退化成「sweep 跑到
--      之前的兜底」。
--
--   ④ `request_reject`：受方对一次交付说「不认」的记录。**它不是新状态**，是并列的
--      断言层——和 `entry_confirm` 同一个位置。为什么不加 `disputed` 状态：交付那一刻
--      give 与 receive 已经入链，账本 append-only 撤不回来；给单子一个「有争议」的
--      状态会让它看起来像能撤销已发生的事。拒收能做的只有一件事：把「沉默」变成
--      「有签名、有理由、可查询的拒绝」，状态仍停在 delivered。
--
--   ①② 改触发器，③ 只改写入面（本文件不含它的代码），④ 加表。
--   视图 v_public_request 一并重建，加两列：`unconfirmed_days`、`rejected`。
--
-- 为什么另起文件而不原地改 v1.5：v1.5 的注释已经把「可见性收窄」讲完了，把状态机与
-- 拒收层塞进去会让那一份说不清自己管什么。v1.5 的字节不动，本文件只做增量。
--
-- 「取不到」不等于「验不过」的规矩照旧：所有显式时间比较都套 COALESCE(...,0)，
-- 解析失败当作「没到期」，宁可多留一条，也不误判成终态（expired 没有回头路）。

-- ============================================================================
-- 1) 状态迁移：claimed 多一个回到 open 的出口
-- ============================================================================
-- 重建而不是新建：SQLite 的触发器不能 ALTER，只能 DROP 再 CREATE。
-- 与 v1.4 那条的唯一差别是 claimed 分支多了 'open'。其余一个字符没动。
DROP TRIGGER trg_request_transition;

CREATE TRIGGER trg_request_transition BEFORE INSERT ON request
WHEN NEW.seq > 1
 AND NEW.seq = (SELECT COALESCE(MAX(seq),0) + 1 FROM request WHERE request_id = NEW.request_id)
 AND NOT EXISTS (
  SELECT 1 FROM request p
  WHERE p.request_id = NEW.request_id AND p.seq = NEW.seq - 1
    AND (
      (p.state = 'open'      AND NEW.state IN ('claimed','withdrawn','expired')) OR
      (p.state = 'claimed'   AND NEW.state IN ('delivered','withdrawn','open'))  OR
      (p.state = 'delivered' AND NEW.state = 'closed')
    )
)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_020: illegal request transition'); END;

-- ============================================================================
-- 2) 第 1 行仍必须是 open；open 不再限定只能是第 1 行
-- ============================================================================
-- 原来这条是「open 只能是第 1 行」与「第 1 行必须是 open」互为充要。回退要成立，
-- 前半句必须去掉。保留后半句：一张单的起点永远是「发布」，不会从 claimed 开始。
-- 放松的代价写在 request.md §2：seq 只能增，但 state 可以回退，回退本身留一行痕。
DROP TRIGGER trg_request_open_only_first;

CREATE TRIGGER trg_request_open_only_first BEFORE INSERT ON request
WHEN NEW.seq = 1 AND NEW.state <> 'open'
BEGIN SELECT RAISE(ABORT, 'DGB_LED_020: the first row of a request must be open'); END;

-- ============================================================================
-- 3) 拒收层（request_reject）
-- ============================================================================
-- 形状与 entry_confirm 对齐：签名、公钥指纹、被签载荷、时间，一样不少；签名签的是
-- 「哪一单的哪一行」，不是「这条拒收记录自己」——否则签的是一句自述，不是一项事实。
--
-- 载荷（由服务端按库里那一行重算，客户端交上来的只用于核对）：
--   drawcommons-reject-v1\n<request_id>\n<seq>\n
-- seq 指向被拒的那条 delivered 行。用 seq 而不是「当前状态」：单子将来若再追加行，
-- 拒收仍然指明它拒的是哪一次交付，不会漂到别的事件上。
--
-- reason 允许为空（拒收本身就是态度），但一旦给了就有长度上下限——空串与 NULL 都
-- 按「没写理由」处理，不逼人编一句。
CREATE TABLE request_reject(
  request_id  TEXT NOT NULL,
  seq         INTEGER NOT NULL CHECK (seq >= 1),
  party_id    TEXT NOT NULL,
  key_fp      TEXT NOT NULL CHECK (length(key_fp) BETWEEN 1 AND 128),
  payload     TEXT NOT NULL CHECK (length(payload) BETWEEN 1 AND 4096),
  sig         TEXT NOT NULL CHECK (length(sig) BETWEEN 1 AND 8192),
  reason      TEXT CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 500),
  signed_at   TEXT NOT NULL,
  PRIMARY KEY (request_id)
);

CREATE INDEX idx_request_reject_party ON request_reject(party_id);

CREATE TRIGGER trg_request_reject_no_update BEFORE UPDATE ON request_reject
BEGIN SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on request_reject; post a new record'); END;
CREATE TRIGGER trg_request_reject_no_delete BEFORE DELETE ON request_reject
BEGIN SELECT RAISE(ABORT, 'DGB_LED_013: append-only: DELETE forbidden on request_reject'); END;

-- 拒收人必须是登记主体（DGB_LED_019）
-- 与 entry_confirm 同样的写法：先让「单子存在」由别的触发器负责，这一条只管「人在不在」，
-- 避免两条同时成立时报哪个码看运气。
CREATE TRIGGER trg_request_reject_party BEFORE INSERT ON request_reject
WHEN NOT EXISTS (SELECT 1 FROM party WHERE party_id = NEW.party_id)
 AND EXISTS (SELECT 1 FROM request WHERE request_id = NEW.request_id)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_019: rejecting party must be a registered party'); END;

-- 只有发布方（受方）能拒收（DGB_LED_036）
-- 认领方拒收自己的交付没有意义；第三方拒收不是他的事——那属于第三方见证，另一档。
CREATE TRIGGER trg_request_reject_is_publisher BEFORE INSERT ON request_reject
WHEN EXISTS (SELECT 1 FROM party WHERE party_id = NEW.party_id)
 AND EXISTS (SELECT 1 FROM request WHERE request_id = NEW.request_id)
 AND NEW.party_id <> (SELECT requested_by FROM request
                       WHERE request_id = NEW.request_id AND seq = 1)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_036: only the publisher can reject a delivery'); END;

-- ============================================================================
-- 4) 公开视图：加两列，条件与 v1.5 完全一致
-- ============================================================================
-- 只加列，不改任何 WHERE——v1.5 的收窄口径（未认领两支、expired 立即、其余终态 90 天）
-- 一个字不动。视图列变了，但列的**顺序**只在末尾追加，v1.5 之前的读者按名字取列不受影响。
DROP VIEW v_public_request;

CREATE VIEW v_public_request AS
SELECT r.request_id, r.state, r.category, r.need_desc, r.window_expires_at,
       r.requested_by, r.claim_agent_id, r.occurred_at, r.created_at, r.note,
       -- 交付之后过了多少天还没被确认。只对 delivered 有值：其他状态问「几天没确认」
       -- 没有意义，填 0 会被读成「当天确认了」。NULL 才是诚实的空。
       -- 取整用 CAST 而不是 ROUND：第 0.9 天不该显示成「1 天」，四舍五入会把
       -- 「刚交付」说成「已等一天」。
       CASE WHEN r.state = 'delivered'
            THEN CAST(COALESCE(julianday('now') - julianday(r.created_at), 0) AS INTEGER)
            ELSE NULL END AS unconfirmed_days,
       -- 0/1 而不是理由：列表页只需要知道「这单有争议」，理由在单页与 API 详情里。
       -- 把长文本塞进每行的列表响应，会让一屏 50 条的负载翻几倍。
       (SELECT COUNT(*) FROM request_reject j WHERE j.request_id = r.request_id) AS rejected
FROM v_request_current r
WHERE r.state <> 'expired'
  AND NOT (r.state IN ('closed','withdrawn')
           AND COALESCE(julianday('now') - julianday(r.created_at) > 90, 0))
  AND NOT (
    r.state = 'open'
    AND (
      -- a) 有截止：过了截止时刻即不再公开（sweep 跑到之前的兜底）
      (TRIM(COALESCE(r.window_expires_at, '')) <> ''
        AND COALESCE(julianday('now') > julianday(r.window_expires_at), 0))
      OR
      -- b) 无截止：空串按 created_at + 90 天算（v1.6 起这是「默认截止」，不再是「无期限」）
      (TRIM(COALESCE(r.window_expires_at, '')) = ''
        AND COALESCE(julianday('now') - julianday(r.created_at) > 90, 0))
    )
  );
