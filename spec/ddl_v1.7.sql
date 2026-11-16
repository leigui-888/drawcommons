-- SPDX-License-Identifier: CC0-1.0
-- Copyright 2026 老夫 <2379731846@qq.com>
-- 表结构增量 v1.7（SQLite）—— 必须运行在 spec/ddl_v1.6.sql（v1.6）之后
-- 版本 w4-ddl v1.7 / 2026-11-17
--
-- 本文件补五件事，全部来自「页面已经做出来、服务端还接不住」的五处：
--
--   ① **联系方式两列**（`poster_email` / `claimer_email`）。
--      页面上一句「双方认领后才可见」要成立，前提是这两格真的存得下东西。此前
--      `party` 表没有邮箱、`request` 行也没有，页面上那两行只能靠演示数据撑。
--      放进 `request` 行而不是 `party`：这是**这一单**的联系方式，不是一个人的
--      主联系方式；放 `party` 会让每一次发单都被迫共用一个地址，也让公开主体
--      多出一列可被枚举的隐私。
--      **两列都不进任何公开视图。** `v_public_request` 的列是显式写的，天然不带；
--      `v_request_current` 是 `SELECT r.*`，本文件重建它才会带上——那是给写入面与
--      鉴权读口用的，不是给匿名读者用的。
--
--   ② **`delivered → delivered`**：被拒收之后可以再交一次。
--      v1.6 把拒收做成了一句签名的否认，却没给人下一步：拒收是终态之外的一条
--      断言，而单子仍停在 delivered，唯一出口是 closed。拒收一个不合要求的交付，
--      等于把这张单钉死。允许再交，条件写死为「上一行确实被拒收过」——没有拒收
--      的 delivered 再交一次不是「再交」，是同一件事说两遍（那条路仍归 029）。
--
--   ③ **`request_reject` 一单一条 → 一次交付一条**。
--      多次交付就要能多次拒收，否则第二轮交付被拒时写不进去。主键从
--      `(request_id)` 改为 `(request_id, seq)`：seq 指向被拒的那条 delivered 行，
--      行不可改，所以「哪一次被拒」永久可指。
--
--   ④ **`DGB_LED_032` 从「一互助一条」放宽为「give 数不超过交付数」**。
--      原来那条是为「一次交付 = 一对账目」设的，多轮交付后它会把第二对挡在门外。
--      放宽的不是「可以重复入账」，而是「重复入账的上限由交付次数决定」：give 数
--      永远 ≤ 该单 `delivered` 行数，多出来的那一对仍然写不进去。
--
--   ⑤ **催告层 `request_reminder`**。
--      催告不改状态、不改条款，只是认领方留下一条「我催过」的签名。它是断言层，
--      与 `entry_confirm` / `request_reject` 同一个位置。24 小时冷却写在触发器里：
--      这是「同一件事别刷屏」，不是业务判断，放在应用层就会被脚本绕过。
--
-- 不做的两件（写在这里，免得下次当成漏项）：
--
--   · **不给 `claimed` 加单独的交付期限列。** 到期口径沿用 `window_expires_at`，
--     空串按「认领时刻 + 90 天」。多一列就要多一套「没填时按什么算」的规则，
--     而那一套规则与 `open` 的默认期限必然长得不一样，两套迟早打架。
--   · **不让时钟写 `withdrawn`。** 逾期由写入面结算成 `expired`（作废），不是
--     `withdrawn`（撤回）。撤回是发布方签名的动作，时钟没有签名；替人写「他撤回
--     了」就是伪造一条意思表示。作废与撤回在页面上都叫「不能接了」，但在账上是
--     两件事：一件有人认，一件没人认。

-- ============================================================================
-- 1) 联系方式两列
-- ============================================================================
-- 形状只做最小约束：长度、必须有一个 @ 与一个点、不含空格。完整的 RFC 5322 有
-- 几十条边角，判得越细越容易把合法地址挡在门外，而这里要防的只是「把一段话
-- 糊进邮箱栏」。空串一律存 NULL：`''` 与「没填」在页面上是同一件事，存两种值
-- 只会让读端多一个分支。
ALTER TABLE request ADD COLUMN poster_email TEXT
  CHECK (poster_email IS NULL OR (
    length(poster_email) BETWEEN 5 AND 254
    AND poster_email GLOB '*@*.*'
    AND poster_email NOT GLOB '* *'
  ));

ALTER TABLE request ADD COLUMN claimer_email TEXT
  CHECK (claimer_email IS NULL OR (
    length(claimer_email) BETWEEN 5 AND 254
    AND claimer_email GLOB '*@*.*'
    AND claimer_email NOT GLOB '* *'
  ));

-- ============================================================================
-- 2) 重建 v_request_current：让它选得到新列
-- ============================================================================
-- SQLite 的视图在**建的那一刻**把 `r.*` 展开成列清单，之后给基表加列不会自动
-- 出现在视图里。不重建的话，写入面读上一行的邮箱永远是「没有这一列」。
-- 条件一个字没改，只多两列。
--
-- `v_public_request` 不用重建：它的列是显式写的（v1.6），从本视图取哪些列由它
-- 自己列，多出来的两列不会漏到匿名读者那边。这一条是「邮箱不公开」的实现方式，
-- 不是顺手——重建它等于把隐私摆到列表接口上。
DROP VIEW v_request_current;

CREATE VIEW v_request_current AS
SELECT r.* FROM request r
JOIN (SELECT request_id, MAX(seq) AS mx FROM request GROUP BY request_id) m
  ON r.request_id = m.request_id AND r.seq = m.mx;

-- ============================================================================
-- 3) 拒收层：一单一条 → 一次交付一条
-- ============================================================================
-- SQLite 不能改主键，只能重建。重建前先拆掉挂在旧表上的两条 append-only 触发器
-- 与两条主体校验触发器：`ALTER TABLE ... RENAME` 会把触发器一起带过去，随后
-- `DROP TABLE` 再把它们删掉——不先拆，重建后的表会缺触发器，而缺的那几条正是
-- 拒收层唯一的不变量。
DROP TRIGGER trg_request_reject_no_update;
DROP TRIGGER trg_request_reject_no_delete;
DROP TRIGGER trg_request_reject_party;
DROP TRIGGER trg_request_reject_is_publisher;

ALTER TABLE request_reject RENAME TO request_reject_v16;

CREATE TABLE request_reject(
  request_id  TEXT NOT NULL,
  seq         INTEGER NOT NULL CHECK (seq >= 1),
  party_id    TEXT NOT NULL,
  key_fp      TEXT NOT NULL CHECK (length(key_fp) BETWEEN 1 AND 128),
  payload     TEXT NOT NULL CHECK (length(payload) BETWEEN 1 AND 4096),
  sig         TEXT NOT NULL CHECK (length(sig) BETWEEN 1 AND 8192),
  reason      TEXT CHECK (reason IS NULL OR length(reason) BETWEEN 1 AND 500),
  signed_at   TEXT NOT NULL,
  -- 一次交付最多被拒一次。同一张单的第 2 次交付被拒时，seq 不同，写得进去。
  PRIMARY KEY (request_id, seq)
);

INSERT INTO request_reject(request_id, seq, party_id, key_fp, payload, sig, reason, signed_at)
  SELECT request_id, seq, party_id, key_fp, payload, sig, reason, signed_at
  FROM request_reject_v16;

DROP TABLE request_reject_v16;

CREATE INDEX idx_request_reject_party ON request_reject(party_id);

CREATE TRIGGER trg_request_reject_no_update BEFORE UPDATE ON request_reject
BEGIN SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on request_reject; post a new record'); END;
CREATE TRIGGER trg_request_reject_no_delete BEFORE DELETE ON request_reject
BEGIN SELECT RAISE(ABORT, 'DGB_LED_013: append-only: DELETE forbidden on request_reject'); END;

-- 拒收人必须是登记主体（DGB_LED_019），条件与 v1.6 一致
CREATE TRIGGER trg_request_reject_party BEFORE INSERT ON request_reject
WHEN NOT EXISTS (SELECT 1 FROM party WHERE party_id = NEW.party_id)
 AND EXISTS (SELECT 1 FROM request WHERE request_id = NEW.request_id)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_019: rejecting party must be a registered party'); END;

-- 只有发布方能拒收（DGB_LED_036），条件与 v1.6 一致
CREATE TRIGGER trg_request_reject_is_publisher BEFORE INSERT ON request_reject
WHEN EXISTS (SELECT 1 FROM party WHERE party_id = NEW.party_id)
 AND EXISTS (SELECT 1 FROM request WHERE request_id = NEW.request_id)
 AND NEW.party_id <> (SELECT requested_by FROM request
                       WHERE request_id = NEW.request_id AND seq = 1)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_036: only the publisher can reject a delivery'); END;

-- ============================================================================
-- 4) RENAME 的副作用：视图里的子查询被改写，必须重建
-- ============================================================================
-- `ALTER TABLE ... RENAME` 不只改表名，它会把**所有引用这张表**的触发器与视图
-- 定义一起改写成新名字。这里把 `request_reject` 改名成 `request_reject_v16`，
-- 于是 v1.6 的 `v_public_request` 里那条
--   (SELECT COUNT(*) FROM request_reject j WHERE ...)
-- 被悄悄改成 `FROM request_reject_v16 j`——而那张表马上就 DROP 了。视图不会因此
-- 报错，它只是从下一刻起每次被查询都抛 `no such table`。列表页、读口、判据三处
-- 全挂，而报错信息指向一张谁都没听说过的表。
--
-- 所以重建。定义与 v1.6 **逐字一致**：本版没有改公开视图的任何条件，重建只是
-- 修复 RENAME 留下的坏引用。若哪天要加列，改的是这里而不是 v1.6 那份。
DROP VIEW v_public_request;

CREATE VIEW v_public_request AS
SELECT r.request_id, r.state, r.category, r.need_desc, r.window_expires_at,
       r.requested_by, r.claim_agent_id, r.occurred_at, r.created_at, r.note,
       CASE WHEN r.state = 'delivered'
            THEN CAST(COALESCE(julianday('now') - julianday(r.created_at), 0) AS INTEGER)
            ELSE NULL END AS unconfirmed_days,
       (SELECT COUNT(*) FROM request_reject j WHERE j.request_id = r.request_id) AS rejected
FROM v_request_current r
WHERE r.state <> 'expired'
  AND NOT (r.state IN ('closed','withdrawn')
           AND COALESCE(julianday('now') - julianday(r.created_at) > 90, 0))
  AND NOT (
    r.state = 'open'
    AND (
      (TRIM(COALESCE(r.window_expires_at, '')) <> ''
        AND COALESCE(julianday('now') > julianday(r.window_expires_at), 0))
      OR
      (TRIM(COALESCE(r.window_expires_at, '')) = ''
        AND COALESCE(julianday('now') - julianday(r.created_at) > 90, 0))
    )
  );

-- ============================================================================
-- 5) 状态机：被拒收之后允许再交一次
-- ============================================================================
-- 与 v1.6 的唯一差别是 delivered 分支多了一种落点：`delivered → delivered`，
-- 且必须指向前一行确实被拒收过。
--
-- **为什么要「确实被拒收」这个条件。** 没有它，「再交一次」就等于「同一状态可以
-- 无限追加」——交付凭据能被悄悄换掉，而 `delivery_replay` 的 029 正是为了不让
-- 凭据被换。有了它，第二行是一次**有对象的重交**：有人明说「这条我不认」，才有
-- 下一次。拒绝是重交的通行证，不是重交的障碍。
DROP TRIGGER trg_request_transition;

CREATE TRIGGER trg_request_transition BEFORE INSERT ON request
WHEN NEW.seq > 1
 AND NEW.seq = (SELECT COALESCE(MAX(seq),0) + 1 FROM request WHERE request_id = NEW.request_id)
 AND NOT EXISTS (
  SELECT 1 FROM request p
  WHERE p.request_id = NEW.request_id AND p.seq = NEW.seq - 1
    AND (
      (p.state = 'open'      AND NEW.state IN ('claimed','withdrawn','expired')) OR
      -- v1.7：claimed 也会被时钟结算。截止只约束「还没人接」那一段的说法到此为止：
      -- 认领方接了不交，时钟到点把它作废，单子不再永久占着，发布方也不必等一个
      -- 永远不会来的交付。这一支与 open 那支的到期口径完全一致（见 sweep_expired）。
      (p.state = 'claimed'   AND NEW.state IN ('delivered','withdrawn','open','expired'))  OR
      (p.state = 'delivered' AND NEW.state = 'closed') OR
      -- v1.7：被拒收的那次交付，可以再来一次
      (p.state = 'delivered' AND NEW.state = 'delivered'
        AND EXISTS (SELECT 1 FROM request_reject j
                    WHERE j.request_id = NEW.request_id AND j.seq = p.seq))
    )
)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_020: illegal request transition'); END;

-- ============================================================================
-- 6) 入口计数：give 数不得超过交付数（改写 DGB_LED_032）
-- ============================================================================
-- 原来两条是「同一 mutual 只许一条 give / 一条 receive」。多轮交付后，第二对会被
-- 它们挡在门外，而那一对是完全正当的：另一次交付，另两条账目。
--
-- 换成一个上限而不是取消约束：`give 数 < 交付行数` 才放行。第一次交付 0 < 1，
-- 第二次 1 < 2，第三次 2 < 3；而「同一行交付重复入账」永远是 1 = 1，写不进去。
-- 约束没有变松，只是把「一次」换成了「一次一对」。
--
-- `receive` 用同一个上限：它与 give 在 `convert_delivery` 里同进同退，若只放宽
-- 一边，那对账目会以「give 进去了、receive 没进去」的形式半截落库——这正是
-- v1.6 想避免的那种中间态。
DROP TRIGGER trg_ledger_give_mutual_unique;
DROP TRIGGER trg_ledger_receive_mutual_unique;

CREATE TRIGGER trg_ledger_give_mutual_rounds BEFORE INSERT ON ledger_give
WHEN NEW.mutual_id GLOB 'm-rq_*'
 AND (SELECT COUNT(*) FROM ledger_give WHERE mutual_id = NEW.mutual_id)
     >= (SELECT COUNT(*) FROM request
         WHERE request_id = substr(NEW.mutual_id, 3) AND state = 'delivered')
BEGIN SELECT RAISE(ABORT, 'DGB_LED_032: more gives than deliveries'); END;

CREATE TRIGGER trg_ledger_receive_mutual_rounds BEFORE INSERT ON ledger_receive
WHEN NEW.mutual_id GLOB 'm-rq_*'
 AND (SELECT COUNT(*) FROM ledger_receive WHERE mutual_id = NEW.mutual_id)
     >= (SELECT COUNT(*) FROM request
         WHERE request_id = substr(NEW.mutual_id, 3) AND state = 'delivered')
BEGIN SELECT RAISE(ABORT, 'DGB_LED_032: more receives than deliveries'); END;

-- ============================================================================
-- 7) 催告层（request_reminder）
-- ============================================================================
-- 形状与 `request_reject` 对齐：签名、指纹、被签载荷、时间，一样不少。
--
-- 载荷（由服务端按库里那一行重算）：
--   drawcommons-remind-v1\n<request_id>\n<seq>\n
-- seq 指向当前那条 delivered 行。**不绑时间**：催告的对象是「这次交付还没被确认」
-- 这件事，不是「我在几点催的」；绑时间会让同一次催告在重发时变成一条新记录，
-- 而重发应当是幂等的。
--
-- 为什么单独一张表而不复用 `request_reject`：两者都是断言，但一个是「不认」，
-- 一个是「请你看一眼」。合成一张表就要加一个 kind 列，之后每个查询都要带
-- `WHERE kind=...`，漏一处就把催告当成拒收——那种错不会报，只会静静歪掉。
CREATE TABLE request_reminder(
  request_id  TEXT NOT NULL,
  seq         INTEGER NOT NULL CHECK (seq >= 1),
  party_id    TEXT NOT NULL,
  key_fp      TEXT NOT NULL CHECK (length(key_fp) BETWEEN 1 AND 128),
  payload     TEXT NOT NULL CHECK (length(payload) BETWEEN 1 AND 4096),
  sig         TEXT NOT NULL CHECK (length(sig) BETWEEN 1 AND 8192),
  signed_at   TEXT NOT NULL,
  -- 同一秒内同一人不可能催两次（冷却在下面），加进主键只是让重复提交撞主键
  PRIMARY KEY (request_id, seq, signed_at)
);

CREATE INDEX idx_request_reminder_request ON request_reminder(request_id, seq);

CREATE TRIGGER trg_request_reminder_no_update BEFORE UPDATE ON request_reminder
BEGIN SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on request_reminder; post a new record'); END;
CREATE TRIGGER trg_request_reminder_no_delete BEFORE DELETE ON request_reminder
BEGIN SELECT RAISE(ABORT, 'DGB_LED_013: append-only: DELETE forbidden on request_reminder'); END;

-- 只有当前认领方能催，且只能催 `delivered` 的单（DGB_LED_039）
-- 发布方催自己没意义；第三方催不是他的事。与 `DGB_LED_036` 同一类判断：
-- 这不是「你格式错了」，是「这不是你的单」。
CREATE TRIGGER trg_request_reminder_is_claimer BEFORE INSERT ON request_reminder
WHEN NOT EXISTS (
  SELECT 1 FROM v_request_current v
  WHERE v.request_id = NEW.request_id
    AND v.state = 'delivered'
    AND v.claim_agent_id = NEW.party_id
)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_039: only the claimer can remind on a delivered request'); END;

-- 24 小时冷却（DGB_LED_038）
-- 用 `signed_at` 而不是客户端带的时间：后者可以填成昨天，冷却就形同虚设。
-- 比较套 COALESCE(...,0)：时间解析不了时按「不足 24 小时」处理——宁可多挡一次
-- （客户端再等一天重发即可），也不让一条格式坏的行成为绕过冷却的缺口。
CREATE TRIGGER trg_request_reminder_cooldown BEFORE INSERT ON request_reminder
WHEN EXISTS (
  SELECT 1 FROM request_reminder r
  WHERE r.request_id = NEW.request_id
    AND r.party_id = NEW.party_id
    AND COALESCE(julianday(NEW.signed_at) - julianday(r.signed_at) < 1.0, 1)
)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_038: remind cooldown: one per request per 24h'); END;
