# scripts/seed_demo.py
# -*- coding: utf-8 -*-
"""
向本地数据库写入一条 demo 证据与若干回执，便于在
/verify_upgrade/{cert_id} 页面看到非兜底的真实数据。
"""

from datetime import datetime
from contextlib import contextmanager
import os, sqlite3

# 可选：如果你的环境里本来就装了 SQLAlchemy，保留这个导入用于 SQLAlchemy 分支
try:
    from sqlalchemy import text as sqla_text  # type: ignore
except Exception:
    sqla_text = None  # 没装也没关系

DB_PATH = os.path.join("data", "verify_upgrade.db")

# 优先尝试复用项目里的 get_db；失败则回退到 sqlite3 本地文件
try:
    from app.main import get_db as project_get_db  # type: ignore
except Exception:
    project_get_db = None

@contextmanager
def get_db():
    # 1) 先试项目内的 get_db（若返回 None 或异常，则继续回退）
    if project_get_db is not None:
        try:
            with project_get_db() as db:
                if db is not None:
                    yield db
                    return
        except Exception:
            pass
    # 2) 回退到本地 SQLite
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()

def exec_sql(db, sql: str, params: dict | None = None):
    """先尝试用原始字符串执行（兼容 sqlite3），失败再回退到 SQLAlchemy text。"""
    params = params or {}
    # 1) 直接用字符串执行：sqlite3.Connection 支持命名占位符 :name
    try:
        return db.execute(sql, params)
    except Exception:
        # 2) 如果是 SQLAlchemy 的 Session/Connection，需要 text(sql)
        if sqla_text is not None:
            return db.execute(sqla_text(sql), params)
        # 3) 没装 SQLAlchemy，就把异常抛出去以便发现真实问题
        raise

CERT_ID = "demo-cert"  # 你也可以改成别的 cert_id 再试

DDL_RECEIPTS = """
CREATE TABLE IF NOT EXISTS receipts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  cert_id    TEXT NOT NULL,
  provider   TEXT,
  status     TEXT,
  txid       TEXT,
  created_at TEXT
);
"""

DDL_EVIDENCE = """
CREATE TABLE IF NOT EXISTS evidence (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  cert_id        TEXT UNIQUE,
  file_path      TEXT,
  sha256         TEXT,
  c2pa_claim     TEXT,
  tsa_url        TEXT,
  sepolia_txhash TEXT,
  title          TEXT,
  owner          TEXT,
  created_at     TEXT
);
"""

def ensure_tables(db):
    exec_sql(db, DDL_RECEIPTS)
    exec_sql(db, DDL_EVIDENCE)
    if hasattr(db, "commit"):
        db.commit()

def seed_evidence(db):
    # 若已存在则跳过
    exists = exec_sql(db, "SELECT 1 FROM evidence WHERE cert_id=:cid", {"cid": CERT_ID}).fetchone()
    if exists:
        return
    now = datetime.now().isoformat(timespec="seconds")
    exec_sql(db, """
      INSERT INTO evidence
      (cert_id, file_path, sha256, c2pa_claim, tsa_url, sepolia_txhash, title, owner, created_at)
      VALUES
      (:cert_id, :file_path, :sha256, :c2pa_claim, :tsa_url, :sepolia_txhash, :title, :owner, :created_at)
    """, {
        "cert_id": CERT_ID,
        "file_path": "samples/demo.png",
        "sha256":   "deadbeef" * 8,
        "c2pa_claim": "claim:demo",
        "tsa_url":    "http://127.0.0.1:8011/api/tsa/mock",
        "sepolia_txhash": "0xSEPOLIADEMO",
        "title": "Demo Evidence",
        "owner": "default",
        "created_at": now,
    })
    if hasattr(db, "commit"):
        db.commit()

def seed_receipts(db):
    now = datetime.now()
    rows = [
        ("tsa",   "ok",      "0xTX_TSA_OK",     now.replace(microsecond=0).isoformat()),
        ("chain", "pending", "0xTX_CHAIN_WAIT", now.replace(microsecond=0).isoformat()),
        ("tsa",   "ok",      "0xTX_TSA_OK_2",   now.replace(microsecond=0).isoformat()),
    ]
    for provider, status, txid, created_at in rows:
        exec_sql(db, """
          INSERT INTO receipts (cert_id, provider, status, txid, created_at)
          VALUES (:cert_id, :provider, :status, :txid, :created_at)
        """, {
            "cert_id": CERT_ID,
            "provider": provider,
            "status": status,
            "txid": txid,
            "created_at": created_at,
        })
    if hasattr(db, "commit"):
        db.commit()

def main():
    with get_db() as db:
        if db is None:
            print("数据库未就绪：get_db() 返回 None（但脚本已运行）。")
            return
        ensure_tables(db)
        seed_evidence(db)
        seed_receipts(db)
        print(f"✓ 已为 cert_id='{CERT_ID}' 写入 evidence 与 receipts。")

if __name__ == "__main__":
    main()
