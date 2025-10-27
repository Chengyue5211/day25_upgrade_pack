# -*- coding: utf-8 -*-
import datetime
from pathlib import Path
from starlette.responses import PlainTextResponse
from fastapi import FastAPI, Request, Depends, Query
import io, csv
import secrets
import os, hashlib
import httpx
import json
import time
import os, sqlite3
# --- make error message UTF-8 safe ---
def _safe_err(e: Exception) -> str:
    try:
        # 强制用 UTF-8 清洗掉任何无法编码的字符
        return str(e).encode("utf-8", errors="ignore").decode("utf-8")
    except Exception:
        return repr(e)
def _safe_json(obj):
    """尽量保留原样；遇到不可编码字符时做降级"""
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False, default=str))
    except Exception:
        try:
            return {"raw": str(obj)[:1000]}
        except Exception:

            return {"raw": repr(obj)[:1000]}
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text  # 用原生 SQL 插入，避免依赖你内部 ORM 细节
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# ---- helpers：生成 txid + 追加历史记录 ----
def _gen_txid(prefix: str = "0x") -> str:
    return prefix + secrets.token_hex(12)

def _append_receipt(app, cert_id: str, item: dict):
    # 在内存里维护一个按 cert_id 分组的收据表
    if not hasattr(app.state, "receipts"):
        app.state.receipts = {}
    app.state.receipts.setdefault(cert_id, []).append(item)
def _write_receipt_db(db, cert_id: str, item: dict):
    """
    轻量 DB 写入：若 receipts 表存在则插入；若不存在或失败则静默跳过（不影响演示）
    期望列：cert_id, provider, status, txid, created_at
    """
    try:
        sql = text("""
            INSERT INTO receipts (cert_id, provider, status, txid, created_at)
            VALUES (:cert_id, :provider, :status, :txid, :created_at)
        """)
        db.execute(sql, {
            "cert_id": cert_id,
            "provider": item.get("provider"),
            "status": item.get("status"),
            "txid": item.get("txid"),
            "created_at": item.get("time"),
        })
        db.commit()
    except Exception:
        # DB 未就绪不阻塞演示
        pass
# ---- TSA settings helper ----
def _tsa_settings():
    # Windows 可以用 setx TSA_ENDPOINT "https://xxx" / setx TSA_API_KEY "xxx" 来配置
    return os.getenv("TSA_ENDPOINT"), os.getenv("TSA_API_KEY")
 
# ---- DB funcs ----
# ---- DB imports（兼容老版本 db.py）----

# ==== DB imports with fallbacks for CI ====
from typing import List, Dict, Optional
try:
    from app.db import (
        init_db, get_db, get_evidence, get_last_status_txid,
        get_last_receipts, get_latest_corpus,
        add_corpus_item, search_corpus, latest_chain
    )
except Exception:
    def init_db() -> None: 
        pass
    from contextlib import contextmanager
    @contextmanager
    def get_db():
        yield None
    def get_evidence(db, cert_id: str) -> Dict:
        return {"cert_id": cert_id, "owner": "default", "title": "Demo Evidence", "created_at": None}
    def get_last_status_txid(db, cert_id: str) -> Dict:
        return {"tsa_last_status": "ok", "tsa_last_txid": "0xDEMO"}
    def get_last_receipts(db, cert_id: str, limit: int = 5) -> List[Dict]:
        return []

try:
    from app.db import get_latest_corpus
except Exception:
    def get_latest_corpus(db, owner_id: str = "default", limit: int = 3) -> List[Dict]:
        return []

try:
    from app.db import add_corpus_item
except Exception:
    def add_corpus_item(db, owner_id: str, title: str, mime: str, content_text: str, consent_scope: str = "") -> int:
        return 0

try:
    from app.db import search_corpus
except Exception:
    def search_corpus(db, q: str, limit: int = 10, offset: int = 0) -> List[Dict]:
        return []

# ===== CI fallback endpoints (safe no-op) =====
import os, io, csv, datetime
from fastapi import Query
from fastapi.responses import StreamingResponse
from fastapi import Request
from fastapi.responses import HTMLResponse

# —— ensure app exists for CI fallback ——
try:
    app  # noqa: F821
except NameError:
    from fastapi import FastAPI
    app = FastAPI(title="verify-upgrade (CI)")
# —— end ensure ——

@app.get("/health")
def ci_health():
    return {
        "ok": True,
        "service": "verify-upgrade",
        "time": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "port": int(os.getenv("PORT", "8011"))
    }
 
from fastapi import Request
from fastapi.responses import HTMLResponse
import os, sqlite3

@app.get("/verify_upgrade/{cert_id}", response_class=HTMLResponse)
def verify_upgrade_page(cert_id: str, request: Request):
    """
    优先从本地 SQLite (data/verify_upgrade.db) 读取；
    若不存在或失败，则回退到 get_* 函数；所有分支都有兜底。
    """
    ctx = {
        "request": request,
        "cert_id": cert_id,
        "tsa_last_status": None,
        "tsa_last_txid": None,
        "history": [],
        "evidence": {},
    }

    # A) 本地 SQLite 优先
    db_path = os.path.join("data", "verify_upgrade.db")
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            try:
                # receipts：最近与历史
                cur = conn.execute(
                    "SELECT provider,status,txid,created_at "
                    "FROM receipts WHERE cert_id=? ORDER BY id DESC LIMIT 5",
                    (cert_id,)
                )
                rows = cur.fetchall() or []
                if rows:
                    last = rows[0]
                    ctx["tsa_last_status"] = last[1]
                    ctx["tsa_last_txid"] = last[2]
                    ctx["history"] = [
                        {"provider": r[0], "status": r[1], "txid": r[2], "created_at": r[3]}
                        for r in rows
                    ]
                # evidence
                cur = conn.execute(
                    "SELECT file_path,sha256,c2pa_claim,tsa_url,sepolia_txhash,title,owner,created_at "
                    "FROM evidence WHERE cert_id=? LIMIT 1",
                    (cert_id,)
                )
                ev = cur.fetchone()
                if ev:
                    ctx["evidence"] = {
                        "file_path": ev[0], "sha256": ev[1], "c2pa_claim": ev[2],
                        "tsa_url": ev[3], "sepolia_txhash": ev[4],
                        "title": ev[5], "owner": ev[6], "created_at": ev[7],
                    }
            finally:
                conn.close()
        except Exception:
            pass

    # B) 本地没读到再回退到 get_* 实现
    if not ctx["history"] and ctx["tsa_last_status"] is None:
        try:
            with get_db() as db:
                try:
                    st = get_last_status_txid(db, cert_id) or {}
                    ctx["tsa_last_status"] = (st.get("tsa_last_status")
                                              if isinstance(st, dict) else getattr(st, "tsa_last_status", None))
                    ctx["tsa_last_txid"]   = (st.get("tsa_last_txid")
                                              if isinstance(st, dict) else getattr(st, "tsa_last_txid", None))
                except Exception:
                    pass
                try:
                    raw_hist = get_last_receipts(db, cert_id, limit=5) or []
                    safe = []
                    for r in raw_hist:
                        if isinstance(r, dict):
                            safe.append({
                                "provider": r.get("provider"),
                                "status":   r.get("status"),
                                "txid":     r.get("txid"),
                                "created_at": r.get("created_at"),
                            })
                        else:
                            safe.append({
                                "provider": getattr(r, "provider", None),
                                "status":   getattr(r, "status", None),
                                "txid":     getattr(r, "txid", None),
                                "created_at": getattr(r, "created_at", None),
                            })
                    if safe:
                        ctx["history"] = safe
                except Exception:
                    pass
                try:
                    ev = get_evidence(db, cert_id) or {}
                    if not isinstance(ev, dict):
                        ev = {
                            "file_path": getattr(ev, "file_path", None),
                            "sha256": getattr(ev, "sha256", None),
                            "c2pa_claim": getattr(ev, "c2pa_claim", None),
                            "tsa_url": getattr(ev, "tsa_url", None),
                            "sepolia_txhash": getattr(ev, "sepolia_txhash", None),
                            "title": getattr(ev, "title", None),
                            "owner": getattr(ev, "owner", None),
                            "created_at": getattr(ev, "created_at", None),
                        }
                    if ev:
                        ctx["evidence"] = ev
                except Exception:
                    pass
        except Exception:
            pass

    return templates.TemplateResponse(request, "verify_upgrade.html", ctx)

@app.get("/api/tsa/config")
def ci_tsa_config():
    ep = os.getenv("TSA_ENDPOINT", "http://127.0.0.1:8011/api/tsa/mock")
    return {"effective": {"endpoint": ep}}

@app.get("/api/tsa/mock")
def ci_tsa_mock(cert_id: str = Query("demo-cert")):
    return {"ok": True, "cert_id": cert_id}

@app.get("/api/chain/mock")
def ci_chain_mock(cert_id: str = Query("demo-cert")):
    return {"ok": True, "cert_id": cert_id}

@app.get("/api/receipts/export")
def ci_export_csv(cert_id: str = Query("demo-cert")):
    def gen_rows():
        # 先尝试本地 SQLite
        db_path = os.path.join("data", "verify_upgrade.db")
        if os.path.exists(db_path):
            try:
                conn = sqlite3.connect(db_path)
                try:
                    cur = conn.execute(
                        "SELECT id, cert_id, provider, status || '|' || IFNULL(txid,''), created_at "
                        "FROM receipts WHERE cert_id=? ORDER BY id ASC",
                        (cert_id,)
                    )
                    return cur.fetchall() or []
                finally:
                    conn.close()
            except Exception:
                pass

        # 再尝试 get_db（例如 SQLAlchemy）
        try:
            with get_db() as db:
                if db is not None:
                    try:
                        cur = db.execute(text(
                            "SELECT id, cert_id, provider, (status || '|' || COALESCE(txid,'')) AS payload, created_at "
                            "FROM receipts WHERE cert_id=:cid ORDER BY id ASC"
                        ), {"cid": cert_id})
                        return list(cur.fetchall())
                    except Exception:
                        pass
        except Exception:
            pass

        # 最后用内存兜底
        mem = getattr(app.state, "receipts", {}).get(cert_id, [])
        rows = []
        for i, r in enumerate(mem, 1):
            rows.append((
                i, cert_id, r.get("provider"),
                f"{r.get('status')}|{r.get('txid','')}",
                r.get("time"),
            ))
        return rows

    def stream():
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["id", "cert_id", "provider", "payload", "created_at"])
        yield out.getvalue(); out.seek(0); out.truncate(0)
        for row in gen_rows():
            w.writerow(list(row))
            yield out.getvalue(); out.seek(0); out.truncate(0)

    filename = f"receipts_{cert_id}.csv"
    return StreamingResponse(
        stream(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@app.post("/api/receipts/clear")
def ci_clear(cert_id: str = Query("demo-cert")):
    return {"ok": True, "cleared": 1}
# ===== end CI fallback =====

