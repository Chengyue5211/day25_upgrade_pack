import os, sqlite3
os.makedirs("data", exist_ok=True)
db="data/verify_upgrade.db"
conn=sqlite3.connect(db)
conn.execute("""CREATE TABLE IF NOT EXISTS receipts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  cert_id TEXT, provider TEXT, status TEXT, txid TEXT, created_at TEXT
)""")
conn.commit(); conn.close()
print("ok:", db)
