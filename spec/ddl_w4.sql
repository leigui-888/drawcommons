-- W4-02 账本口径增补：DDL（SQLite）
-- 版本 w4-ddl v1.3 / 2026-11-11
-- v1.3 变更（C2）：
--   新增主体表 party：display_mode 默认 'pseudonymous'（发布闸门第 5 条：实名须显式绑定）
--   real_name_ref 只存引用（脱敏串/外部指针），账本库不承载实名原文
--   新增公开视图 v_public_party：唯一对外口径，按 display_mode 与撤回状态输出 shown_name
--   触发器：DGB_LED_015 撤回同意是终态 / DGB_LED_016 实名须显式绑定（INSERT 与 UPDATE 两路都拦）
-- v1.2 变更（对应审查报告 P0-03 / P0-04 / P2-01 / P2-02）：
--   P0-03  append-only：三表 BEFORE UPDATE / BEFORE DELETE 一律 ABORT（DGB_LED_012 / DGB_LED_013）
--   P0-04  旧积分列迁出主表：magnitude_legacy → archive_magnitude_v1，主表不再留可写连续量
--   P2-01  删除 magnitude_hint，计量列三表同构
--   P2-02  scope 不再以 DEFAULT 兜底：mutual_id 可判定者回填 mutual，其余留 NULL 并标 scope_unresolved

-- 1) 旧列改名（迁移中转态，第 6 段随迁出）
ALTER TABLE ledger_give    RENAME COLUMN points TO magnitude_legacy;
ALTER TABLE ledger_receive RENAME COLUMN points TO magnitude_legacy;
ALTER TABLE ledger_payback RENAME COLUMN points TO magnitude_legacy;

-- 2) 三域 scope（不设默认值：历史记录必须显式判定，禁止静默归类）
ALTER TABLE ledger_give    ADD COLUMN scope TEXT CHECK (scope IN ('public','mutual','external'));
ALTER TABLE ledger_receive ADD COLUMN scope TEXT CHECK (scope IN ('public','mutual','external'));
ALTER TABLE ledger_payback ADD COLUMN scope TEXT CHECK (scope IN ('public','mutual','external'));

-- 2b) 未判定标记：NULL scope 的行必须能被审计看见，而不是被默认值藏起来
ALTER TABLE ledger_give    ADD COLUMN scope_unresolved INTEGER NOT NULL DEFAULT 0 CHECK (scope_unresolved IN (0,1));
ALTER TABLE ledger_receive ADD COLUMN scope_unresolved INTEGER NOT NULL DEFAULT 0 CHECK (scope_unresolved IN (0,1));
ALTER TABLE ledger_payback ADD COLUMN scope_unresolved INTEGER NOT NULL DEFAULT 0 CHECK (scope_unresolved IN (0,1));

-- 2c) 回填：有 mutual_id 者可判定为 mutual；无 mutual_id 者不猜（可能是 public 或 external）
UPDATE ledger_give    SET scope='mutual', scope_unresolved=0 WHERE mutual_id IS NOT NULL AND TRIM(mutual_id) <> '';
UPDATE ledger_receive SET scope='mutual', scope_unresolved=0 WHERE mutual_id IS NOT NULL AND TRIM(mutual_id) <> '';
UPDATE ledger_payback SET scope='mutual', scope_unresolved=0 WHERE mutual_id IS NOT NULL AND TRIM(mutual_id) <> '';
UPDATE ledger_give    SET scope_unresolved=1 WHERE scope IS NULL;
UPDATE ledger_receive SET scope_unresolved=1 WHERE scope IS NULL;
UPDATE ledger_payback SET scope_unresolved=1 WHERE scope IS NULL;

-- 3) 计量刻度（删除 magnitude_hint：三表同构，见 P2-01）
ALTER TABLE ledger_give    ADD COLUMN magnitude REAL NOT NULL DEFAULT 0 CHECK (magnitude >= 0);
ALTER TABLE ledger_receive ADD COLUMN magnitude REAL NOT NULL DEFAULT 0 CHECK (magnitude >= 0);
ALTER TABLE ledger_payback ADD COLUMN magnitude REAL NOT NULL DEFAULT 0 CHECK (magnitude >= 0);

-- 3b) 由旧值一次性回填计量刻度（此后该列只随新增行写入）
UPDATE ledger_give    SET magnitude = magnitude_legacy WHERE magnitude = 0 AND magnitude_legacy > 0;
UPDATE ledger_receive SET magnitude = magnitude_legacy WHERE magnitude = 0 AND magnitude_legacy > 0;
UPDATE ledger_payback SET magnitude = magnitude_legacy WHERE magnitude = 0 AND magnitude_legacy > 0;

-- 4) 三表同构：时长 / 可验证性 / 窗口
ALTER TABLE ledger_give    ADD COLUMN duration_hours REAL NOT NULL DEFAULT 0 CHECK (duration_hours >= 0);
ALTER TABLE ledger_receive ADD COLUMN duration_hours REAL NOT NULL DEFAULT 0 CHECK (duration_hours >= 0);
ALTER TABLE ledger_payback ADD COLUMN duration_hours REAL NOT NULL DEFAULT 0 CHECK (duration_hours >= 0);
ALTER TABLE ledger_give    ADD COLUMN verifiability TEXT NOT NULL DEFAULT 'self_reported' CHECK (verifiability IN ('self_reported','counterparty_confirmed','third_party_anchored'));
ALTER TABLE ledger_receive ADD COLUMN verifiability TEXT NOT NULL DEFAULT 'self_reported' CHECK (verifiability IN ('self_reported','counterparty_confirmed','third_party_anchored'));
ALTER TABLE ledger_payback ADD COLUMN verifiability TEXT NOT NULL DEFAULT 'self_reported' CHECK (verifiability IN ('self_reported','counterparty_confirmed','third_party_anchored'));
ALTER TABLE ledger_give    ADD COLUMN window_expires_at TEXT NOT NULL DEFAULT '';
ALTER TABLE ledger_receive ADD COLUMN window_expires_at TEXT NOT NULL DEFAULT '';
ALTER TABLE ledger_payback ADD COLUMN window_expires_at TEXT NOT NULL DEFAULT '';

-- 5) 版本绑定
ALTER TABLE ledger_give    ADD COLUMN rule_version TEXT NOT NULL DEFAULT 'pr_v1.1.0';
ALTER TABLE ledger_receive ADD COLUMN rule_version TEXT NOT NULL DEFAULT 'pr_v1.1.0';
ALTER TABLE ledger_payback ADD COLUMN rule_version TEXT NOT NULL DEFAULT 'pr_v1.1.0';

-- 6) 旧积分值迁出主表（P0-04 的语义修法）
--    词表只能禁"字段名"，禁不了"可累加的量"。所以把旧值搬离主表：
--    主表不再有任何承载贡献打分数值的列，归档表只读、不参与任何计算。
CREATE TABLE archive_magnitude_v1(
  src_table    TEXT NOT NULL,
  src_row_id   TEXT NOT NULL,
  legacy_value REAL,
  archived_at  TEXT NOT NULL,
  reason       TEXT NOT NULL,
  PRIMARY KEY (src_table, src_row_id)
);
INSERT INTO archive_magnitude_v1
  SELECT 'ledger_give', give_id, magnitude_legacy, '2026-11-08',
         'W4-02 points 改名遗留；仅存档，不参与任何计算' FROM ledger_give  WHERE magnitude_legacy IS NOT NULL AND magnitude_legacy <> 0;
INSERT INTO archive_magnitude_v1
  SELECT 'ledger_receive', receive_id, magnitude_legacy, '2026-11-08',
         'W4-02 points 改名遗留；仅存档，不参与任何计算' FROM ledger_receive WHERE magnitude_legacy IS NOT NULL AND magnitude_legacy <> 0;
INSERT INTO archive_magnitude_v1
  SELECT 'ledger_payback', payback_id, magnitude_legacy, '2026-11-08',
         'W4-02 points 改名遗留；仅存档，不参与任何计算' FROM ledger_payback WHERE magnitude_legacy IS NOT NULL AND magnitude_legacy <> 0;

ALTER TABLE ledger_give    DROP COLUMN magnitude_legacy;
ALTER TABLE ledger_receive DROP COLUMN magnitude_legacy;
ALTER TABLE ledger_payback DROP COLUMN magnitude_legacy;

CREATE TRIGGER trg_archive_no_update BEFORE UPDATE ON archive_magnitude_v1
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_014: archive_magnitude_v1 is read-only');
END;
CREATE TRIGGER trg_archive_no_delete BEFORE DELETE ON archive_magnitude_v1
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_014: archive_magnitude_v1 is read-only');
END;

-- 7) append-only（P0-03）：三表禁止 UPDATE 与 DELETE
--    更正一律以"冲正记录"新增行表达，物理删除一律禁止。
--    scope 不可变由本段全表触发器统一覆盖，原 DGB_LED_011 不再单独抛出；
--    旧测试若断言 011，应改为断言 012。
DROP TRIGGER IF EXISTS trg_scope_immutable_give;

CREATE TRIGGER trg_ledger_give_no_update BEFORE UPDATE ON ledger_give
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on ledger_give; post a reversal row');
END;
CREATE TRIGGER trg_ledger_give_no_delete BEFORE DELETE ON ledger_give
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_013: append-only: DELETE forbidden on ledger_give');
END;

CREATE TRIGGER trg_ledger_receive_no_update BEFORE UPDATE ON ledger_receive
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on ledger_receive; post a reversal row');
END;
CREATE TRIGGER trg_ledger_receive_no_delete BEFORE DELETE ON ledger_receive
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_013: append-only: DELETE forbidden on ledger_receive');
END;

CREATE TRIGGER trg_ledger_payback_no_update BEFORE UPDATE ON ledger_payback
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on ledger_payback; post a reversal row');
END;
CREATE TRIGGER trg_ledger_payback_no_delete BEFORE DELETE ON ledger_payback
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_013: append-only: DELETE forbidden on ledger_payback');
END;

-- 8) 主体表与公开视图（v1.3，C2）
--    背景：账本三表只有主体标识列，没有"主体选择如何被展示"的状态。
--    实名展示是显式同意事项：默认假名；撤回同意后必须立即不再输出实名——
--    这一隔离不靠应用层自觉，靠表结构 + 视图实现。
--
--    party 表是可变状态表（与账本三表的 append-only 性质不同）：
--    display_mode / consent_withdrawn_at 本来就要随主体意愿更新。
--    不可变的是"撤回"这个动作本身：一旦撤回，不可撤销（DGB_LED_015）。
--
--    real_name_ref 存"引用"而非明文：脱敏串或外部加密存储的指针。
--    账本库被整库拖走时，实名原文不随库泄露（对应白皮书 §11.7.4 静态加密的库里落点）。
CREATE TABLE party(
  party_id             TEXT PRIMARY KEY,
  display_mode         TEXT NOT NULL DEFAULT 'pseudonymous'
                         CHECK (display_mode IN ('pseudonymous','real_name')),
  real_name_ref        TEXT,
  consent_withdrawn_at TEXT,
  updated_at           TEXT NOT NULL,
  -- 表级 CHECK 兜底：实名模式必须有引用。触发器（下）给出可审计的错误码。
  CHECK (display_mode <> 'real_name' OR real_name_ref IS NOT NULL)
);

-- DGB_LED_015：撤回同意是终态。清空/回拨撤回时间一律拒绝。
CREATE TRIGGER trg_party_consent_final BEFORE UPDATE ON party
WHEN OLD.consent_withdrawn_at IS NOT NULL AND NEW.consent_withdrawn_at IS NULL
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_015: consent withdrawal is final; cannot un-withdraw');
END;

-- DGB_LED_016：实名须显式绑定。display_mode='real_name' 而 real_name_ref 为空，INSERT/UPDATE 两路都拦。
CREATE TRIGGER trg_party_realname_bind_ins BEFORE INSERT ON party
WHEN NEW.display_mode = 'real_name'
     AND (NEW.real_name_ref IS NULL OR TRIM(NEW.real_name_ref) = '')
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_016: real-name display requires explicit real_name_ref');
END;
CREATE TRIGGER trg_party_realname_bind_upd BEFORE UPDATE ON party
WHEN NEW.display_mode = 'real_name'
     AND (NEW.real_name_ref IS NULL OR TRIM(NEW.real_name_ref) = '')
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_016: real-name display requires explicit real_name_ref');
END;

-- 公开视图：公开页与公开 API 只许查这里，不许查 party 表。
-- 输出规则：仅当【显式选择实名】且【未撤回】且【引用存在】三者同时成立才输出 real_name_ref；
-- 否则一律回落 party_id。视图不暴露 real_name_ref 原列，查询它直接报 no such column。
CREATE VIEW v_public_party AS
SELECT
  party_id,
  CASE
    WHEN display_mode = 'real_name'
         AND consent_withdrawn_at IS NULL
         AND real_name_ref IS NOT NULL
      THEN real_name_ref
    ELSE party_id
  END AS shown_name,
  display_mode AS declared_mode,
  CASE WHEN consent_withdrawn_at IS NULL THEN 0 ELSE 1 END AS consent_withdrawn
FROM party;
