# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 老夫 <2379731846@qq.com>
"""重建基线库并执行 W4-02 DDL，输出结构级验证结果。

v1.2 起把"append-only 是否真的挡住了删改"纳入自测：
审查报告 P0-03 的六次攻击（3 表 × UPDATE/DELETE）必须全部被拒，否则退出码非 0。
v1.3 起把"主体展示与同意撤回"纳入自测：
发布闸门第 5 条（display_mode 默认 pseudonymous、实名须显式绑定、撤回立即生效、
公开视图不泄露 real_name_ref）必须全部经攻击验证，否则退出码非 0。
"""
import sqlite3, os, sys

DB = os.path.join(os.path.dirname(__file__), "ledger_w4.db")
# C0 起 DDL 唯一源为 spec/ddl_w4.sql；保留同目录回退，便于在 0-snapshot 内单独复跑冻结基线。
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANDS = [os.path.join(_HERE, "..", "spec", "ddl_w4.sql"), os.path.join(_HERE, "ddl_w4.sql")]
DDL_PATH = next((p for p in _CANDS if os.path.exists(p)), _CANDS[-1])
def _reset(db):
    """把库恢复到可重建状态。优先删文件；删不掉（占用/权限/安全策略）就地清空。

    为什么不在删除失败时直接退出：这条命令要能被反复执行。复现者跑第二遍就
    exit 1 的话，"三条判据复现 35/35"这个判据只在第一次成立。
    """
    try:
        os.remove(db)
        return
    except OSError:
        pass
    c = sqlite3.connect(db)
    objs = c.execute("SELECT type,name FROM sqlite_master "
                     "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%'").fetchall()
    for typ, name in objs:
        c.execute('DROP %s IF EXISTS "%s"' % ("TABLE" if typ == "table" else "VIEW", name))
    c.commit()
    c.close()

if os.path.exists(DB):
    _reset(DB)
con = sqlite3.connect(DB)
con.executescript("""
CREATE TABLE ledger_give(give_id TEXT PRIMARY KEY, mutual_id TEXT, from_agent_id TEXT, to_agent_id TEXT,
  category TEXT, quantity REAL, unit TEXT, points REAL DEFAULT 0, occurred_at TEXT, note TEXT);
CREATE TABLE ledger_receive(receive_id TEXT PRIMARY KEY, mutual_id TEXT, state TEXT, points REAL DEFAULT 0);
CREATE TABLE ledger_payback(payback_id TEXT PRIMARY KEY, mutual_id TEXT, points REAL DEFAULT 0);
INSERT INTO ledger_give(give_id,mutual_id,from_agent_id,to_agent_id,category,quantity,unit,points,occurred_at)
  VALUES('g_1','m1','a','b','compute',2,'hour',2,'2026-11-20T00:00:00Z');
INSERT INTO ledger_give(give_id,mutual_id,from_agent_id,to_agent_id,category,quantity,unit,points,occurred_at)
  VALUES('g_2',NULL,'a','c','docs',1,'hour',0,'2026-11-21T00:00:00Z');
INSERT INTO ledger_receive(receive_id,mutual_id,state,points) VALUES('r_1','m1','delivered',0);
INSERT INTO ledger_payback(payback_id,mutual_id,points) VALUES('p_1','m1',0);
""")
ddl = open(DDL_PATH, encoding="utf-8").read()
con.executescript(ddl)
con.commit()

rows = con.execute("SELECT give_id,scope,scope_unresolved,magnitude,verifiability,rule_version FROM ledger_give ORDER BY give_id").fetchall()
print("DDL OK; ledger_give:", rows)
print("归档行数:", con.execute("SELECT COUNT(*) FROM archive_magnitude_v1").fetchone()[0])
print("未判定 scope 行数:",
      sum(con.execute("SELECT COUNT(*) FROM %s WHERE scope IS NULL AND scope_unresolved=1" % t).fetchone()[0]
          for t in ("ledger_give", "ledger_receive", "ledger_payback")))

fail = 0
attacks = [
    ("UPDATE ledger_give",    "UPDATE ledger_give SET scope='external' WHERE give_id='g_1'"),
    ("UPDATE ledger_receive", "UPDATE ledger_receive SET state='void' WHERE receive_id='r_1'"),
    ("UPDATE ledger_payback", "UPDATE ledger_payback SET magnitude=9 WHERE payback_id='p_1'"),
    ("DELETE ledger_give",    "DELETE FROM ledger_give WHERE give_id='g_1'"),
    ("DELETE ledger_receive", "DELETE FROM ledger_receive WHERE receive_id='r_1'"),
    ("DELETE ledger_payback", "DELETE FROM ledger_payback WHERE payback_id='p_1'"),
]
for name, sql in attacks:
    try:
        con.execute(sql)
        print("append-only 失效 FAIL:", name)
        fail += 1
    except Exception as e:
        print("append-only OK:", name, "->", str(e)[:60])
con.rollback()

for bad in ("vendor", "PUBLIC"):
    try:
        con.execute("INSERT INTO ledger_receive(receive_id,scope) VALUES(?,?)", ("r_x", bad))
        print("CHECK 失效 FAIL", bad)
        fail += 1
    except Exception as e:
        print("scope CHECK OK:", bad, "->", str(e)[:50])

# 归档表只读
try:
    con.execute("UPDATE archive_magnitude_v1 SET legacy_value=0")
    print("归档只读失效 FAIL")
    fail += 1
except Exception as e:
    print("归档只读 OK ->", str(e)[:50])

# ---- v1.3：主体展示与同意撤回（发布闸门第 5 条）----
con.execute("INSERT INTO party(party_id, updated_at) VALUES('p_a','2026-11-11T02:00:00+08:00')")
shown_default = con.execute("SELECT shown_name FROM v_public_party WHERE party_id='p_a'").fetchone()[0]
if shown_default != "p_a":
    print("默认假名 FAIL: shown_name =", shown_default)
    fail += 1
else:
    print("默认假名 OK: 无 display_mode 时 shown_name = party_id")

try:
    con.execute("INSERT INTO party(party_id, display_mode, updated_at) VALUES('p_bad','real_name','2026-11-11T02:00:00+08:00')")
    print("实名绑定失效 FAIL: 无 real_name_ref 的实名 INSERT 被放行")
    fail += 1
except Exception as e:
    ok = "DGB_LED_016" in str(e)
    print("实名绑定 OK (INSERT 拦截, DGB_LED_016):" if ok else "实名绑定 FAIL(错误码缺失):", str(e)[:60])
    fail += 0 if ok else 1

con.execute("INSERT INTO party(party_id, display_mode, real_name_ref, updated_at) "
            "VALUES('p_b','real_name','REF::vault:0001','2026-11-11T02:00:00+08:00')")
shown_real = con.execute("SELECT shown_name FROM v_public_party WHERE party_id='p_b'").fetchone()[0]
if shown_real != "REF::vault:0001":
    print("实名展示 FAIL: shown_name =", shown_real)
    fail += 1
else:
    print("实名展示 OK: 显式绑定后视图输出 real_name_ref")

# 撤回必须立即在视图生效（不再输出实名），并成为终态
con.execute("UPDATE party SET consent_withdrawn_at='2026-11-11T02:05:00+08:00' WHERE party_id='p_b'")
shown_after = con.execute(
    "SELECT shown_name, consent_withdrawn FROM v_public_party WHERE party_id='p_b'").fetchone()
if shown_after != ("p_b", 1):
    print("撤回生效 FAIL:", shown_after)
    fail += 1
else:
    print("撤回生效 OK: 视图立即回落 party_id，consent_withdrawn=1")

try:
    con.execute("UPDATE party SET consent_withdrawn_at=NULL WHERE party_id='p_b'")
    print("撤回终态失效 FAIL: 撤回被清空")
    fail += 1
except Exception as e:
    ok = "DGB_LED_015" in str(e)
    print("撤回终态 OK (DGB_LED_015):" if ok else "撤回终态 FAIL(错误码缺失):", str(e)[:60])
    fail += 0 if ok else 1

# 撤回后即便 display_mode 仍为 real_name，视图也不得输出实名（双保险）
mode_row = con.execute("SELECT display_mode FROM party WHERE party_id='p_b'").fetchone()[0]
shown_guard = con.execute("SELECT shown_name FROM v_public_party WHERE party_id='p_b'").fetchone()[0]
if mode_row == "real_name" and shown_guard != "REF::vault:0001" and shown_guard == "p_b":
    print("视图双保险 OK: display_mode 未改、实名仍不输出")
else:
    print("视图双保险 WARN: mode=%s shown=%s" % (mode_row, shown_guard))

try:
    con.execute("SELECT real_name_ref FROM v_public_party")
    print("视图泄露 FAIL: real_name_ref 可从视图查询")
    fail += 1
except Exception as e:
    print("视图不泄露 OK: real_name_ref 不在 v_public_party 中 ->", str(e)[:45])

con.rollback()
sys.exit(1 if fail else 0)
