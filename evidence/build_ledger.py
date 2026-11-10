"""重建基线库并执行 W4-02 DDL，输出结构级验证结果。

v1.2 起把"append-only 是否真的挡住了删改"纳入自测：
审查报告 P0-03 的六次攻击（3 表 × UPDATE/DELETE）必须全部被拒，否则退出码非 0。
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
    exit 1 的话，"两条命令复现 35/35"这个判据只在第一次成立。
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

sys.exit(1 if fail else 0)
