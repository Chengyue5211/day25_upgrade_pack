# scripts/db_check.py
import os, sqlite3
p = 'data/verify_upgrade.db'
print('exists:', os.path.exists(p))
if not os.path.exists(p):
    raise SystemExit('db file not found')

conn = sqlite3.connect(p)
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('tables:', [t[0] for t in c.fetchall()])

def cnt(tbl):
    c.execute(f"SELECT count(*) FROM {tbl} WHERE cert_id=?", ('demo-cert',))
    return c.fetchone()[0]

try:
    print('receipts rows:', cnt('receipts'))
except Exception as e:
    print('receipts rows: ERROR ->', e)

try:
    print('evidence rows:', cnt('evidence'))
except Exception as e:
    print('evidence rows: ERROR ->', e)

conn.close()
