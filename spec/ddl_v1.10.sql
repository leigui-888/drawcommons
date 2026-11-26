-- SPDX-License-Identifier: CC0-1.0
-- Copyright 2026 老夫 <2379731846@qq.com>
-- v1.10 · 给条目加「入链次序」ord，链的顺序不再由条目内容决定
--
-- 为什么非改不可（2026-11-26 实测，不是推论）：
--
--   在此之前 `entries_from()` 把三表读出来后用 `entries.sort(key=canonical)` 排序，
--   `build_chain()` 再按这个顺序逐条算 prev_hash/hash。也就是说 **hash 不是写入时钉死的，
--   是每次导出时按当前排序重算的**。于是只要新条目的内容排在旧条目之前，它插进链中间，
--   后面每一条的 prev_hash 与 hash 全部重算——等于把「只追加」改写成了「可重排」。
--
--   那天的实际后果：链路自测单 `rq_linktest01` 的两条（id 以 `g-rq_linktest01` /
--   `r-rq_linktest01` 开头）按字典序落到了 `g-rq_reviewprivacy1` 之前，两条真实互助的
--   give 条目 hash 随之改变，而它们的受方确认签的是旧 hash。第三方跑 `verify-confirm.py`
--   得到「2 条确认验不过」——那不是篡改，却是同一个结论。
--
--   根子在「顺序由内容推出」：内容进哈希，顺序又由内容排，两者互相定义。修法是给每条
--   记录一个**不参与哈希**的入链序号 ord，排序只看它。
--
-- 三条约束，写在这里免得下一版又把 ord 塞进条目：
--   1. ord **不进条目内容**（`entries_from` 显式剔除）。进了内容就进 canonical、就进 hash，
--      那等于把「链上的位置」变成「条目自述的位置」，可被伪造；
--   2. ord **由服务端分配**（`append_entry` 取三表 max+1），不接受客户端指定。客户端能
--      指定序号，就能把自己塞进历史；
--   3. 唯一索引兜底：同一位置不能有两条。NULL 允许多个（SQLite 唯一索引不约束 NULL），
--      但应用层把 NULL 排在最后，正常库里不该出现。
--
-- 回填的依据：下面这 10 条的先后是**历史事实**（10 条都在 2026-11-26 之前入链，前 8 条
-- 的顺序见 11-25 的导出件，后 2 条是当天链路自测单）。历史事实不能用 canonical 重新
-- 推一遍——那正是这次的根因，所以逐条写死。清单外的行保持 NULL（排序时排最后），
-- 不猜。

-- 回填要 UPDATE，而三表都有 append-only 的 BEFORE UPDATE 触发器（DGB_LED_012）。
-- 所以迁移窗口内先摘掉 **no_update** 三条，回填完逐字重建。
-- **no_delete 一条都不动**：这次要的是「补一个不参与哈希的序号」，不是「改内容」；
-- 放开 DELETE 就等于给了一条删条目的路，那是不该在迁移里顺手打开的口子。
-- 触发器定义逐字照抄 spec/ddl_w4.sql:111–136，重建后应当与原来完全一致。
DROP TRIGGER trg_ledger_give_no_update;
DROP TRIGGER trg_ledger_receive_no_update;
DROP TRIGGER trg_ledger_payback_no_update;

ALTER TABLE ledger_give    ADD COLUMN ord INTEGER;
ALTER TABLE ledger_receive ADD COLUMN ord INTEGER;
ALTER TABLE ledger_payback ADD COLUMN ord INTEGER;

-- ── 回填：前 8 条（顺序与 2026-11-25 导出件逐条一致）────────────────────────
UPDATE ledger_give     SET ord = 1 WHERE give_id    = 'g_1';
UPDATE ledger_give     SET ord = 2 WHERE give_id    = 'g_2';
UPDATE ledger_give     SET ord = 3 WHERE give_id    = 'g-rq_reviewprivacy1';
UPDATE ledger_give     SET ord = 4 WHERE give_id    = 'g-rq_reviewprivacy2';
UPDATE ledger_payback  SET ord = 5 WHERE payback_id = 'p_1';
UPDATE ledger_receive  SET ord = 6 WHERE receive_id = 'r-rq_reviewprivacy1';
UPDATE ledger_receive  SET ord = 7 WHERE receive_id = 'r-rq_reviewprivacy2';
UPDATE ledger_receive  SET ord = 8 WHERE receive_id = 'r_1';

-- ── 回填：2026-11-26 链路自测单的两条（入链晚于上面 8 条，排在末尾）──────────
UPDATE ledger_give     SET ord = 9  WHERE give_id    = 'g-rq_linktest01';
UPDATE ledger_receive  SET ord = 10 WHERE receive_id = 'r-rq_linktest01';

-- ── 唯一性 ─────────────────────────────────────────────────────────────────
CREATE UNIQUE INDEX ux_give_ord    ON ledger_give(ord);
CREATE UNIQUE INDEX ux_receive_ord ON ledger_receive(ord);
CREATE UNIQUE INDEX ux_payback_ord ON ledger_payback(ord);

-- ── 把 append-only 的 UPDATE 闸门装回去（逐字同 ddl_w4.sql）──────────────────
CREATE TRIGGER trg_ledger_give_no_update BEFORE UPDATE ON ledger_give
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on ledger_give; post a reversal row');
END;
CREATE TRIGGER trg_ledger_receive_no_update BEFORE UPDATE ON ledger_receive
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on ledger_receive; post a reversal row');
END;
CREATE TRIGGER trg_ledger_payback_no_update BEFORE UPDATE ON ledger_payback
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on ledger_payback; post a reversal row');
END;

-- ── 自检（迁移后应当各返回 0）─────────────────────────────────────────────
-- 上面两张清单互相不重叠，且覆盖了 2026-11-26 之前的全部 10 条。跑完手工核一次：
--
--   SELECT 'give',    COUNT(*) FROM ledger_give    WHERE ord IS NULL
--   UNION ALL SELECT 'receive', COUNT(*) FROM ledger_receive WHERE ord IS NULL
--   UNION ALL SELECT 'payback', COUNT(*) FROM ledger_payback WHERE ord IS NULL;
--
-- 三行都是 0 才算回填完整。不为 0 说明库里有清单没预见到的行——先查清那是哪条，
-- 不要用「按 rowid 续尾」蒙过去（那会把一次判断错误固化成历史）。
