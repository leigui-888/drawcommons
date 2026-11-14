-- SPDX-License-Identifier: CC0-1.0
-- Copyright 2026 老夫 <2379731846@qq.com>
-- 表结构增量 v1.4（SQLite）—— 必须运行在 spec/ddl_w4.sql（v1.3）之后
-- 版本 w4-ddl v1.4 / 2026-11-13
--
-- 本文件做四件事，都是「结构」而不是「行为」：
--   1) 主体多一把公钥 —— 双签验签的公钥来源
--   2) 需求单 request —— append-only 的状态行，不进哈希链（理由见 spec/request.md）
--   3) 账本侧补时间与证据列，并让 mutual_id 可溯源自证、可判重
--   4) 写入面的重放闸门 ingest_nonce —— 运营状态，不是账本内容
--
-- 为什么另起文件而不往 ddl_w4.sql 里追加：
--   v1.3 已随 rc19 发布，字节被 tag 固定。原地追加就会出现「同一个版本号下有两份
--   ddl_w4.sql」——这正是本项目最不能接受的事。增量单独成文件，v1.3 的字节不动，
--   v1.4 的字节也是确定的；旧库要升级就跑这一个文件。
--
-- 迁移性质：全部是 ADD COLUMN 与 CREATE，没有重建表、没有 UPDATE 数据。
--   SQLite 的 ADD COLUMN 只改元数据，所以旧库升级是 O(1)，不改写任何已有行、
--   不改任何已有列的值。
--
-- **但条目哈希会变，这一点必须说清而不是藏起来。**
--   load_entries 是 SELECT *，新列以 NULL 出现在条目里，于是每条 receive / payback
--   的 hash 都变（give 不受影响：occurred_at 本来就有，也没有新增列）。
--   这是「条目 = 它此刻的全部字段」这条既有规则的必然结果，不是本次引入的特殊行为。
--   与之配套的三条事实写在第 02 步的完成记录里：
--     · 迁移前后，12 个既有字段的值逐条相同（有脚本比对，不是口头保证）；
--     · 链按新列集重算后自洽（verify_chain 通过）；
--     · 锚值必然改变，在第 08 步与 DATA_NOTICE、版本串一起换一次，不单独换。
--
-- 错误码（本文件新增；001–016 见 ddl_w4.sql，020–025 见 request 段）：
--   DGB_LED_017  party.pubkey 格式非法（须为单行 ssh-ed25519）
--   DGB_LED_018  party.pubkey 登记后不可更换
--   DGB_LED_019  引用的主体未在 party 登记
--   DGB_LED_027  新写入的 mutual_id 不是 m-rq_<request_id>
--   DGB_LED_030  确认指向的条目不存在
--   DGB_LED_031  只有受方 can confirm 该 give
--   DGB_LED_032  一次互助只允许一条 give / 一条 receive
--   DGB_LED_033  give 的给方与受方不得是同一主体

-- ============================================================================
-- 1) 主体公钥（party）
-- ============================================================================
-- 为什么要存在 party 表而不是单独的 keys 表：主体与密钥是一对一，换钥就是换人。
-- 把换钥做成「加一行」会让旧记录仍然指向旧钥、而主体标识不变——那等于允许
-- 一个人用新钥替旧钥背书，历史与身份就此脱钩。宁可要求新 party_id。
ALTER TABLE party ADD COLUMN pubkey TEXT;
ALTER TABLE party ADD COLUMN pubkey_added_at TEXT;

-- 一把公钥只能属于一个主体：否则同一个签名可以同时冒充两个人
CREATE UNIQUE INDEX idx_party_pubkey ON party(pubkey)
  WHERE pubkey IS NOT NULL AND TRIM(pubkey) <> '';

CREATE TRIGGER trg_party_pubkey_format_ins BEFORE INSERT ON party
WHEN NEW.pubkey IS NOT NULL AND TRIM(NEW.pubkey) <> ''
 AND (NEW.pubkey NOT GLOB 'ssh-ed25519 *' OR length(NEW.pubkey) > 512)
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_017: pubkey must be a single ssh-ed25519 authorized_keys line');
END;

CREATE TRIGGER trg_party_pubkey_format_upd BEFORE UPDATE OF pubkey ON party
WHEN NEW.pubkey IS NOT NULL AND TRIM(NEW.pubkey) <> ''
 AND (NEW.pubkey NOT GLOB 'ssh-ed25519 *' OR length(NEW.pubkey) > 512)
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_017: pubkey must be a single ssh-ed25519 authorized_keys line');
END;

-- 先允许 NULL → 有值（登记），此后不允许改成别的钥
CREATE TRIGGER trg_party_pubkey_immutable BEFORE UPDATE OF pubkey ON party
WHEN OLD.pubkey IS NOT NULL AND NEW.pubkey IS NOT OLD.pubkey
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_018: pubkey is immutable once registered; register a new party_id');
END;

-- ============================================================================
-- 2) 需求单（request）—— append-only 状态行，不入哈希链
-- ============================================================================
-- 一单 = 多行，行号 seq 从 1 连续；当前状态 = 该组最大 seq。
-- 这样「历史不可改」与「状态可前进」同时成立：状态前进是加行，不是改行。
CREATE TABLE request(
  request_id        TEXT NOT NULL CHECK (request_id GLOB 'rq_*' AND length(request_id) BETWEEN 11 AND 35),
  seq               INTEGER NOT NULL CHECK (seq >= 1),
  state             TEXT NOT NULL CHECK (state IN
                      ('open','claimed','delivered','closed','withdrawn','expired')),
  category          TEXT NOT NULL CHECK (length(TRIM(category)) BETWEEN 1 AND 64),
  need_desc         TEXT NOT NULL CHECK (length(need_desc) BETWEEN 1 AND 2000),
  window_expires_at TEXT NOT NULL DEFAULT '',
  requested_by      TEXT NOT NULL,
  claim_agent_id    TEXT,
  evidence_uri      TEXT,
  occurred_at       TEXT,
  created_at        TEXT NOT NULL,
  note              TEXT,
  PRIMARY KEY (request_id, seq)
);

CREATE INDEX idx_request_state ON request(state, request_id, seq);

-- 当前状态（每组最大 seq）
CREATE VIEW v_request_current AS
SELECT r.* FROM request r
JOIN (SELECT request_id, MAX(seq) AS mx FROM request GROUP BY request_id) m
  ON r.request_id = m.request_id AND r.seq = m.mx;

-- 公开列表：只收窄可见性，不删行。
-- 90 是常量不是条款：改它不换版；改「是否保留」才换版（见 request.md §4②）。
CREATE VIEW v_public_request AS
SELECT request_id, state, category, need_desc, window_expires_at,
       requested_by, claim_agent_id, occurred_at, created_at, note
FROM v_request_current
WHERE NOT (state IN ('closed','withdrawn','expired')
           AND julianday('now') - julianday(created_at) > 90);

-- append-only：与账本三表同一原则，更正用新行
CREATE TRIGGER trg_request_no_update BEFORE UPDATE ON request
BEGIN SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on request; post a new seq'); END;
CREATE TRIGGER trg_request_no_delete BEFORE DELETE ON request
BEGIN SELECT RAISE(ABORT, 'DGB_LED_013: append-only: DELETE forbidden on request'); END;

-- seq 连续（DGB_LED_021）
CREATE TRIGGER trg_request_seq_ins BEFORE INSERT ON request
WHEN NEW.seq <> (SELECT COALESCE(MAX(seq),0) + 1 FROM request WHERE request_id = NEW.request_id)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_021: request seq must be contiguous from 1'); END;

-- 状态迁移合法（DGB_LED_020）
-- 前半句「seq 必须等于 max+1」是刻意的：SQLite 对同表多个 BEFORE INSERT 触发器
-- 不保证执行顺序，若两条都满足 WHEN，报哪个码不确定。让跳号只由 seq 触发器负责，
-- 错误码才是确定的。
CREATE TRIGGER trg_request_transition BEFORE INSERT ON request
WHEN NEW.seq > 1
 AND NEW.seq = (SELECT COALESCE(MAX(seq),0) + 1 FROM request WHERE request_id = NEW.request_id)
 AND NOT EXISTS (
  SELECT 1 FROM request p
  WHERE p.request_id = NEW.request_id AND p.seq = NEW.seq - 1
    AND (
      (p.state = 'open'      AND NEW.state IN ('claimed','withdrawn','expired')) OR
      (p.state = 'claimed'   AND NEW.state IN ('delivered','withdrawn'))         OR
      (p.state = 'delivered' AND NEW.state = 'closed')
    )
)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_020: illegal request transition'); END;

-- open 与第 1 行互为充要：open 只能是第 1 行，第 1 行也只能是 open
CREATE TRIGGER trg_request_open_only_first BEFORE INSERT ON request
WHEN (NEW.state = 'open' AND NEW.seq <> 1)
  OR (NEW.seq = 1 AND NEW.state <> 'open')
BEGIN SELECT RAISE(ABORT, 'DGB_LED_020: open must be the first row, and the first row must be open'); END;

-- requested_by 一单一个（DGB_LED_025）
CREATE TRIGGER trg_request_publisher_immutable BEFORE INSERT ON request
WHEN NEW.seq > 1
 AND NEW.seq = (SELECT COALESCE(MAX(seq),0) + 1 FROM request WHERE request_id = NEW.request_id)
 AND NEW.requested_by <> (
  SELECT requested_by FROM request WHERE request_id = NEW.request_id AND seq = 1)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_025: requested_by is immutable per request'); END;

-- 认领与交付字段（DGB_LED_023 / 024）
CREATE TRIGGER trg_request_claim_ins BEFORE INSERT ON request
WHEN NEW.state IN ('claimed','delivered','closed')
     AND (NEW.claim_agent_id IS NULL OR TRIM(NEW.claim_agent_id) = '')
BEGIN SELECT RAISE(ABORT, 'DGB_LED_023: claimed requires claim_agent_id'); END;

CREATE TRIGGER trg_request_delivery_ins BEFORE INSERT ON request
WHEN NEW.state IN ('delivered','closed')
     AND (NEW.occurred_at IS NULL OR NEW.evidence_uri IS NULL OR TRIM(NEW.evidence_uri) = '')
BEGIN SELECT RAISE(ABORT, 'DGB_LED_024: delivered requires occurred_at and evidence_uri'); END;

-- 主体必须先登记（DGB_LED_019）
-- 需求可以匿名展示，但不能没有主体：认领之后要双签，签名主体必须是登记过的 party。
CREATE TRIGGER trg_request_party_known BEFORE INSERT ON request
WHEN NOT EXISTS (SELECT 1 FROM party WHERE party_id = NEW.requested_by)
  OR (NEW.claim_agent_id IS NOT NULL AND TRIM(NEW.claim_agent_id) <> ''
      AND NOT EXISTS (SELECT 1 FROM party WHERE party_id = NEW.claim_agent_id))
BEGIN SELECT RAISE(ABORT, 'DGB_LED_019: requested_by / claim_agent_id must be a registered party'); END;

-- ============================================================================
-- 3) 账本侧补列
-- ============================================================================
-- give 本来就有 occurred_at；这里补齐另外两张表，让「三类条目都有发生时间」
-- 从承诺变成列。evidence_uri 只加在 receive：受方的交付凭据是 r6 需要的，
-- give 与 payback 的凭据目前没有消费者，不加没有消费者的列。
ALTER TABLE ledger_receive ADD COLUMN occurred_at TEXT;
ALTER TABLE ledger_receive ADD COLUMN evidence_uri TEXT;
ALTER TABLE ledger_payback  ADD COLUMN occurred_at TEXT;

-- ============================================================================
-- 4) mutual_id：可溯源 + 可判重
-- ============================================================================
-- 为什么不是 SQL 外键：mutual_id 是派生值（'m-' + request_id），等值外键表达不了
-- 「去掉前缀后指向另一张表的主键」。所以用触发器做等价约束，并在文档里写明
-- 「这是触发器，不是 FOREIGN KEY」——不把两件事混为一谈。
--
-- 只对新写入生效：历史值是 m-<任意>（样例库里的 m1 就是），触发器不回头拦旧行。
-- 追改旧行就是重写历史，比格式不统一严重得多。

CREATE TRIGGER trg_ledger_give_mutual_format BEFORE INSERT ON ledger_give
WHEN NEW.mutual_id IS NOT NULL AND TRIM(NEW.mutual_id) <> ''
 AND NEW.mutual_id NOT GLOB 'm-rq_*'
BEGIN SELECT RAISE(ABORT, 'DGB_LED_027: mutual_id must be m-rq_<request_id> for new entries'); END;

CREATE TRIGGER trg_ledger_receive_mutual_format BEFORE INSERT ON ledger_receive
WHEN NEW.mutual_id IS NOT NULL AND TRIM(NEW.mutual_id) <> ''
 AND NEW.mutual_id NOT GLOB 'm-rq_*'
BEGIN SELECT RAISE(ABORT, 'DGB_LED_027: mutual_id must be m-rq_<request_id> for new entries'); END;

CREATE TRIGGER trg_ledger_payback_mutual_format BEFORE INSERT ON ledger_payback
WHEN NEW.mutual_id IS NOT NULL AND TRIM(NEW.mutual_id) <> ''
 AND NEW.mutual_id NOT GLOB 'm-rq_*'
BEGIN SELECT RAISE(ABORT, 'DGB_LED_027: mutual_id must be m-rq_<request_id> for new entries'); END;

-- 溯源（DGB_LED_028）：指向的需求必须**当前**处于 delivered / closed。
-- 用 v_request_current 而不是 request 全表：一单可能先 delivered 后被 closed，
-- 但绝不会「曾经 delivered 而现在不是」——除非有人绕过状态机，那就该抓出来。
CREATE TRIGGER trg_ledger_give_mutual_provenance BEFORE INSERT ON ledger_give
WHEN NEW.mutual_id GLOB 'm-rq_*'
 AND NOT EXISTS (SELECT 1 FROM v_request_current
                 WHERE request_id = substr(NEW.mutual_id, 3)
                   AND state IN ('delivered','closed'))
BEGIN SELECT RAISE(ABORT, 'DGB_LED_028: mutual_id must derive from a delivered request'); END;

CREATE TRIGGER trg_ledger_receive_mutual_provenance BEFORE INSERT ON ledger_receive
WHEN NEW.mutual_id GLOB 'm-rq_*'
 AND NOT EXISTS (SELECT 1 FROM v_request_current
                 WHERE request_id = substr(NEW.mutual_id, 3)
                   AND state IN ('delivered','closed'))
BEGIN SELECT RAISE(ABORT, 'DGB_LED_028: mutual_id must derive from a delivered request'); END;

CREATE TRIGGER trg_ledger_payback_mutual_provenance BEFORE INSERT ON ledger_payback
WHEN NEW.mutual_id GLOB 'm-rq_*'
 AND NOT EXISTS (SELECT 1 FROM v_request_current
                 WHERE request_id = substr(NEW.mutual_id, 3)
                   AND state IN ('delivered','closed'))
BEGIN SELECT RAISE(ABORT, 'DGB_LED_028: mutual_id must derive from a delivered request'); END;

-- 一次互助一条 give、一条 receive（DGB_LED_032）。
-- payback 不限条数：回报可以是分批的，这个区别是刻意的。
CREATE TRIGGER trg_ledger_give_mutual_unique BEFORE INSERT ON ledger_give
WHEN NEW.mutual_id GLOB 'm-rq_*'
 AND EXISTS (SELECT 1 FROM ledger_give WHERE mutual_id = NEW.mutual_id)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_032: one give per mutual'); END;

CREATE TRIGGER trg_ledger_receive_mutual_unique BEFORE INSERT ON ledger_receive
WHEN NEW.mutual_id GLOB 'm-rq_*'
 AND EXISTS (SELECT 1 FROM ledger_receive WHERE mutual_id = NEW.mutual_id)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_032: one receive per mutual'); END;

-- give 的给方与受方不得同一（DGB_LED_033）：否则「受方确认」等于自签
CREATE TRIGGER trg_ledger_give_not_self BEFORE INSERT ON ledger_give
WHEN NEW.from_agent_id = NEW.to_agent_id
BEGIN SELECT RAISE(ABORT, 'DGB_LED_033: from_agent_id and to_agent_id must differ'); END;

CREATE INDEX idx_give_mutual ON ledger_give(mutual_id) WHERE mutual_id GLOB 'm-rq_*';
CREATE INDEX idx_receive_mutual ON ledger_receive(mutual_id) WHERE mutual_id GLOB 'm-rq_*';

-- ============================================================================
-- 5) 对收方确认（entry_confirm）
-- ============================================================================
-- 确认是「关于条目的一条断言」，不是条目内容：签名签的是条目 hash，
-- 把签名放进条目本身就成了循环（hash 覆盖签名、签名覆盖 hash）。所以单开一张表。
-- 副作用是好的：条目哈希因此完全不受确认动作影响，确认可以被拒绝、可以被撤回
-- 讨论，而账目本身一动不动。
CREATE TABLE entry_confirm(
  kind        TEXT NOT NULL CHECK (kind IN ('give','receive')),
  entry_id    TEXT NOT NULL,
  party_id    TEXT NOT NULL,
  key_fp      TEXT NOT NULL CHECK (length(key_fp) BETWEEN 1 AND 128),
  payload     TEXT NOT NULL CHECK (length(payload) BETWEEN 1 AND 4096),
  sig         TEXT NOT NULL CHECK (length(sig) BETWEEN 1 AND 8192),
  signed_at   TEXT NOT NULL,
  PRIMARY KEY (kind, entry_id)
);

CREATE TRIGGER trg_entry_confirm_no_update BEFORE UPDATE ON entry_confirm
BEGIN SELECT RAISE(ABORT, 'DGB_LED_012: append-only: UPDATE forbidden on entry_confirm; post a new record'); END;
CREATE TRIGGER trg_entry_confirm_no_delete BEFORE DELETE ON entry_confirm
BEGIN SELECT RAISE(ABORT, 'DGB_LED_013: append-only: DELETE forbidden on entry_confirm'); END;

-- 指向的条目必须存在（DGB_LED_030）
CREATE TRIGGER trg_entry_confirm_target BEFORE INSERT ON entry_confirm
WHEN NOT EXISTS (SELECT 1 FROM ledger_give    WHERE NEW.kind = 'give'    AND give_id    = NEW.entry_id)
 AND NOT EXISTS (SELECT 1 FROM ledger_receive WHERE NEW.kind = 'receive' AND receive_id = NEW.entry_id)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_030: confirmation targets an entry that does not exist'); END;

-- 确认人必须是登记主体（DGB_LED_019）
-- 前置「条目存在」是刻意的：SQLite 对同表多个 BEFORE INSERT 触发器不保证顺序，
-- 条目不存在时两条都成立、报哪个码看运气。让「条目不存在」只由上面那条负责，
-- 这一条只管「条目在、人不在」，错误码才确定。
CREATE TRIGGER trg_entry_confirm_party BEFORE INSERT ON entry_confirm
WHEN NOT EXISTS (SELECT 1 FROM party WHERE party_id = NEW.party_id)
 AND (EXISTS (SELECT 1 FROM ledger_give    WHERE NEW.kind = 'give'    AND give_id    = NEW.entry_id)
      OR EXISTS (SELECT 1 FROM ledger_receive WHERE NEW.kind = 'receive' AND receive_id = NEW.entry_id))
BEGIN SELECT RAISE(ABORT, 'DGB_LED_019: confirmer must be a registered party'); END;

-- 只有受方可以确认这条 give（DGB_LED_031）
-- 给方自签不叫「对方确认」；第三方签也不是——那属于 third_party_anchored，
-- 是另一档，不借这个入口进来。
-- 同样加了「确认人已登记」前置，避免与 DGB_LED_019 撞码。
CREATE TRIGGER trg_entry_confirm_is_receiver BEFORE INSERT ON entry_confirm
WHEN NEW.kind = 'give'
 AND EXISTS (SELECT 1 FROM party WHERE party_id = NEW.party_id)
 AND NEW.party_id <> (SELECT to_agent_id FROM ledger_give WHERE give_id = NEW.entry_id)
BEGIN SELECT RAISE(ABORT, 'DGB_LED_031: only the receiving party can confirm a give'); END;

-- ============================================================================
-- 6) 写入面的重放闸门（ingest_nonce）
-- ============================================================================
-- 这张表**不是账本**：不进哈希链、不进导出件、不影响锚值（锚值只由三类条目算出，
-- 已由 v1.4 的探针验过——建了这张表，导出字节与前一步逐字节相同）。
-- 它记的只有一条运维事实：「这个 nonce 已经被用掉」。用途也只有一条：让重放失败。
--
-- 为什么放在账本库里，而不是像访问计数那样另开一个文件：
--   nonce 的提交与业务的提交必须落在**同一个事务**里。分两个库就有中间态：
--     · nonce 落了、条目没落 → 一次失败的写被记成「用过了」，客户端换个 nonce 重签即可，只是白签一次；
--     · 条目落了、nonce 没落 → 同一份签名可以再刷一次，重放闸门形同不存在。
--   同库同事务，两个方向都不会留下。这一条比「账本库只装账本」更硬，所以选前者。
--
-- 保留期不是「永远」：写入时顺手清掉 1 小时前的行（时间窗 15 分钟的两倍以上）。
-- 因此这张表是「最近一小时的 nonce」，不是历史日志，也不会随使用无限长大。
CREATE TABLE ingest_nonce(
  nonce     TEXT PRIMARY KEY CHECK (length(nonce) BETWEEN 22 AND 64),
  party_id  TEXT NOT NULL,
  seen_at   TEXT NOT NULL
);

CREATE INDEX idx_ingest_nonce_seen ON ingest_nonce(seen_at);

