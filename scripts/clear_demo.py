# scripts/clear_demo.py
# -*- coding: utf-8 -*-
"""
清理 cert_id='demo-cert' 的演示数据（receipts + evidence），不删除数据库文件。
"""

import os, sqlite3

DB_PATH = os.path.join("data", "verify_upgrade.db")
CERT_ID = "demo-cert"

def main():
    if not os.path.exists(DB_PATH):
        print("数据库不存在：", DB_PATH)
        return
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM receipts WHERE cert_id=?", (CERT_ID,))
        cur.execute("DELETE FROM evidence WHERE cert_id=?", (CERT_ID,))
        conn.commit()
        # 打印剩余行数，便于确认
        r = cur.execute("SELECT count(*) FROM receipts WHERE cert_id=?", (CERT_ID,)).fetchone()[0]
        e = cur.execute("SELECT count(*) FROM evidence WHERE cert_id=?", (CERT_ID,)).fetchone()[0]
        print(f"✓ 已清理 cert_id='{CERT_ID}'：receipts={r}, evidence={e}")
    finally:
        conn.close()

if __name__ == "__main__":
    main()
