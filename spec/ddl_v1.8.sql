-- SPDX-License-Identifier: CC0-1.0
-- Copyright 2026 老夫 <2379731846@qq.com>
-- 表结构增量 v1.8（SQLite）—— 必须运行在 spec/ddl_v1.7.sql（v1.7）之后
-- 版本 w4-ddl v1.8 / 2026-11-25
--
-- 本文件只做一件事：**把需求单状态行的签名证据留在库里**。
--
-- 为什么现在做。`/requests` 上那句「每一条都来自提交时签名的请求；签名证据在服务端」
-- 此前不成立——写入面验过签名，然后把签名丢了。**验过 ≠ 留证**：事后没有任何人能复核
-- 「这一行是那把钥发的」。这句话能在页面上站住，只能靠库里真的有那一段字节，
-- 而且任何人都能拿它独立验一遍（读口见 `GET /api/v1/requests/<id>/evidence`）。
--
-- ---------------------------------------------------------------------------
-- 存什么
-- ---------------------------------------------------------------------------
-- 存的是**那一次 HTTP 请求的信封**，四样：
--   `sig_payload`  逐字载荷（`drawcommons-ingest-v1\nPOST\n<path>\n<主体>\n
--                  <签发时间>\n<nonce>\n<请求体 sha256>\n`）
--   `sig`          SSHSIG 签名原文（armor）
--   `sig_key_fp`   签名者公钥指纹
--   `sig_ref`      派生行指向「哪一件事派生了我」，http 行为 NULL
--
-- 载荷两百字节上下，里面只有请求体的 **sha256**，没有请求体原文——所以这一版
-- **不复制邮箱、不复制需求描述**。这不是省空间，是「只增不删的表里不放第二份
-- 个人信息」。要复验也不需要原文：签名签的就是这段载荷，载荷自带摘要。
--
-- ---------------------------------------------------------------------------
-- 证明什么、不证明什么（这一段是边界，改之前先读）
-- ---------------------------------------------------------------------------
-- 能证明：主体 X 在时刻 T 用密钥 K 向 `<path>` 发了一次 POST，请求体的 sha256 是 D。
--         任何人拿 `sig_payload` + `sig` + `party.pubkey` 就能离线验过，不必信本服务。
--
-- 不能证明：库里这一行的每个字段逐字等于那次请求体。落库值经过服务端规整——
--         空串存 NULL、联系方式沿用上一行、`seq` 与 `created_at` 由服务端盖、
--         撤回行补齐交付字段。请求体原文不留存，所以「行 == 体」这件事没有证据，
--         只有「行是这次请求在那个事务里写下的」这一条服务端的断言。
--         **这句话必须同时出现在页面上**，否则存证会被读成「整行都被签了」。
--
-- 也不进哈希链：需求单是意图，不是账目；锚值只由三类账目算出（`request.md` §1）。
-- 存证 ≠ 上链。这一版不动任何哈希算法的输入。
--
-- ---------------------------------------------------------------------------
-- 三类行，必须分开——「谁签的」这件事只在第一类成立
-- ---------------------------------------------------------------------------
--   http     客户端签名请求直接写的行：open / claimed / delivered / withdrawn
--   derived  服务端从已发生的事实派生的行：
--              closed     由「受方确认了一条 give」派生（`close_after_confirm`），
--                         签名在那条确认上，`sig_ref` 指过去
--              expired    由时钟结算（`sweep_expired`），`sig_ref='clock'`
--            时钟没有钥。替时钟编一条签名，是这份表最不该有的东西，
--            所以下面第三条触发器**禁止**派生行带签名。
--   NULL     v1.8 之前的行，当时没存。**不补、不猜**——补一条不是当时留下的证据，
--            那是伪造。`trg_request_no_update` 本来也不许改旧行。
--
-- 为什么加列而不另起一张表：行与它的证据必须是**同一次插入**。分两张表就多一个
-- 「行在、证据不在」的中间态，而这张表只增不改，那个中间态没有任何人能修——
-- 与 11-25 那次「库停在 v1.4、代码到 v1.7」是同一类错：缺的东西不会报，
-- 只会在某天被人查出来。
--
-- 为什么**不重建** `v_request_current`：它是 `SELECT r.*`，而 SQLite 是**查询时**才展开
-- 星号的（不是建视图那一刻，见下面 §1 末的实测），所以这五列不重建也会自动出现在视图里。
-- 不重建的理由因此只剩一条：少一次 `DROP VIEW` / `CREATE VIEW`，就少一处能在线上库
-- 跑出半截状态的地方——v1.7 已经被 `ALTER TABLE … RENAME` 改写视图引用坑过一次。
-- 代价是写入面每读一次「上一行」会多读几百字节（载荷 + 签名），这个量级不值得为它
-- 动一次视图。要证据请查 `request` 表本身，`/r/<id>` 与读口都是这么做的。

-- ============================================================================
-- 1) 五列
-- ============================================================================
-- 长度上限与 `request_reject` / `request_reminder` 一致：这两张表存的是同一形状的证据，
-- 三处上限不同只会在某天让一条合法签名写不进去，而错误信息会指向「签名太长」。
ALTER TABLE request ADD COLUMN sig_kind TEXT
  CHECK (sig_kind IS NULL OR sig_kind IN ('http', 'derived'));

ALTER TABLE request ADD COLUMN sig_payload TEXT
  CHECK (sig_payload IS NULL OR length(sig_payload) BETWEEN 1 AND 4096);

ALTER TABLE request ADD COLUMN sig TEXT
  CHECK (sig IS NULL OR length(sig) BETWEEN 1 AND 8192);

ALTER TABLE request ADD COLUMN sig_key_fp TEXT
  CHECK (sig_key_fp IS NULL OR length(sig_key_fp) BETWEEN 1 AND 128);

ALTER TABLE request ADD COLUMN sig_ref TEXT
  CHECK (sig_ref IS NULL OR length(sig_ref) BETWEEN 1 AND 128);

-- 实测（2026-11-25，SQLite 3.53.1，`CREATE VIEW v AS SELECT * FROM t` 后 `ALTER TABLE t
-- ADD COLUMN b`）：
--   sqlite> SELECT * FROM v;   →  a, b
-- 即 `SELECT r.*` 在**查询时**展开，视图跟着基表长出新列。v1.7 §2 那句「视图在建的那一刻
-- 把 `r.*` 展开成列清单」在这个版本上不成立——当时按那句重建了 `v_request_current`，
-- 动作无害，但理由是错的。这里记一笔，免得下次有人照着那个理由去 `DROP VIEW` 一次。

-- ============================================================================
-- 2) 三条触发器：新行必须有归属，有归属就必须名副其实
-- ============================================================================
-- 一、每一条新行都要声明自己是哪一类。没有这一条，将来某条新代码路径少传一个参数，
--     库里会多出一行「谁写的不知道」的状态——而它看起来和别的行一模一样。
CREATE TRIGGER trg_request_sig_required BEFORE INSERT ON request
WHEN NEW.sig_kind IS NULL
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_040: new request row must declare sig_kind (http|derived)');
END;

-- 二、http 行必须带齐三样，且载荷的第一行必须是写入面的标签。
--     只查「非空」挡不住把一个确认层的载荷塞进状态行——那是同一把钥、另一个域，
--     验的时候会失败，而失败点离出错的地方很远。域检查放在写入口最省事。
CREATE TRIGGER trg_request_sig_shape BEFORE INSERT ON request
WHEN NEW.sig_kind = 'http'
 AND (
   COALESCE(length(NEW.sig_payload), 0) NOT BETWEEN 1 AND 4096
   OR COALESCE(length(NEW.sig), 0) NOT BETWEEN 1 AND 8192
   OR COALESCE(length(NEW.sig_key_fp), 0) NOT BETWEEN 1 AND 128
   OR substr(NEW.sig_payload, 1,
             COALESCE(NULLIF(instr(NEW.sig_payload, char(10)), 0), 1) - 1)
      <> 'drawcommons-ingest-v1'
 )
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_041: http row needs payload+sig+key_fp of drawcommons-ingest-v1');
END;

-- 三、派生行不许带签名，也不许带载荷。
--     `closed` 由确认派生、`expired` 由时钟结算，两者都没有自己的签名；给它们挂一段
--     借来的签名，读的人会以为「这一行被谁签过」。宁可空着，并在 `sig_ref` 里指向
--     真正被签的那件事。
CREATE TRIGGER trg_request_sig_no_forge BEFORE INSERT ON request
WHEN NEW.sig_kind = 'derived'
 AND (COALESCE(NEW.sig, '') <> ''
      OR COALESCE(NEW.sig_payload, '') <> ''
      OR COALESCE(NEW.sig_key_fp, '') <> '')
BEGIN
  SELECT RAISE(ABORT, 'DGB_LED_042: derived rows cannot carry a signature (the clock has no key)');
END;
