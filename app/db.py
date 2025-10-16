
import sqlite3, os, json, time
from pathlib import Path

DB_PATH = os.environ.get("UPG25_DB", "upgrade25.sqlite3")

def _conn():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cert_id TEXT,
        file_path TEXT,
        sha256 TEXT,
        c2pa_out TEXT,
        c2pa_status TEXT,
        c2pa_signed_by TEXT,
        tsa_url TEXT,
        tsq_b64 TEXT,
        tsr_b64 TEXT,
        tsa_verified INTEGER,
        sepolia_txhash TEXT,
        created_at INTEGER
    )
    """)
    return conn

def insert_evidence(cert_id: str, file_path: str, sha256: str):
    conn = _conn()
    with conn:
        conn.execute(
            "INSERT INTO evidence(cert_id,file_path,sha256,created_at) VALUES(?,?,?,?)",
            (cert_id, file_path, sha256, int(time.time()))
        )

def update_evidence(cert_id: str, **kwargs):
    if not kwargs: return
    conn = _conn()
    fields = ",".join([f"{k}=?" for k in kwargs.keys()])
    params = list(kwargs.values()) + [cert_id]
    with conn:
        conn.execute(f"UPDATE evidence SET {fields} WHERE cert_id=?", params)

def get_evidence(cert_id: str):
    conn = _conn()
    c = conn.cursor()
    c.execute("SELECT cert_id,file_path,sha256,c2pa_out,c2pa_status,c2pa_signed_by,tsa_url,tsq_b64,tsr_b64,tsa_verified,sepolia_txhash,created_at FROM evidence WHERE cert_id=?", (cert_id,))
    row = c.fetchone()
    if not row:
        return None
    keys = ["cert_id","file_path","sha256","c2pa_out","c2pa_status","c2pa_signed_by","tsa_url","tsq_b64","tsr_b64","tsa_verified","sepolia_txhash","created_at"]
    return dict(zip(keys,row))
