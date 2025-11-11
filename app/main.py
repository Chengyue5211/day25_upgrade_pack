# -*- coding: utf-8 -*-
import datetime
from pathlib import Path

from fastapi import FastAPI, Request, Depends, Query
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse

import io, csv, secrets
import os, hashlib, sqlite3
import httpx
import json
import time
import logging
import math
logger = logging.getLogger("verify-upgrade")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

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
# --- 放在 app = FastAPI(...) 之后的任意位置（与其它路由相邻） ---
from fastapi import Query
from typing import List

def _ensure_state(app):
    if not hasattr(app.state, "receipts"):
        app.state.receipts = {}

def _match_query(item: dict, q: str) -> bool:
    # 支持 provider:xxx status:xxx 以及任意子串匹配
    if not q: 
        return True
    terms = q.split()
    for t in terms:
        if ":" in t:
            k, v = t.split(":", 1)
            if (item.get(k) or "").lower() != v.lower():
                return False
        else:
            blob = " ".join([str(item.get(k,"")) for k in ("cert_id","provider","status","txid")])
            if t.lower() not in blob.lower():
                return False
    return True

@app.get("/api/receipts/count")
def receipts_count(
    cert_id: str = Query(..., min_length=1),
    q: str = Query("", description="provider:tsa status:pending 等语法")
):
    _ensure_state(app)
    rows: List[dict] = app.state.receipts.get(cert_id, [])
    matched = [r for r in rows if _match_query(r, q)]
    return {"ok": True, "count": len(matched)}
# —— end ensure ——

from datetime import datetime
from pathlib import Path
import os

import math  # 顶部如无就加
# ---- 安全加载 Vault 列表（内存 receipts → 统一成 provider/status/txid/created_at）----
def _load_rows(app, cert_id: str = "", q: str = "") -> list:
    _ensure_state(app)
    # 1) 取内存里的收据
    raw = []
    if cert_id:
        raw = app.state.receipts.get(cert_id, []) or []
    else:
        for v in (app.state.receipts or {}).values():
            raw.extend(v or [])

    # 2) 统一字段，映射 time -> created_at，并带上 cert_id 便于搜索
    rows = []
    for r in raw:
        rows.append({
            "cert_id": cert_id or "",
            "provider": r.get("provider"),
            "status": r.get("status"),
            "txid": r.get("txid"),
            "created_at": r.get("time"),
        })

    # 3) 关键词过滤（复用你已有的 _match_query）
    if q:
        rows = [item for item in rows if _match_query(item, q)]
    return rows


@app.get("/vault")
def vault(
    request: Request,
    cert_id: str = Query(""),
    q: str = Query("", alias="q"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=5, le=200),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
):
    # 载入数据：内存优先，空则回退 SQLite
    rows = _load_rows(request.app, cert_id=cert_id, q=q) or []
    if not isinstance(rows, list):
        rows = list(rows)

    # 统一获取值（兼容 dict 或对象属性）
    def getval(r, key):
        if isinstance(r, dict):
            return r.get(key)
        try:
            return getattr(r, key)
        except Exception:
            return None

    # 合法排序字段（与你当前模板列一致）
    allowed = {"created_at", "txid", "provider", "status"}
    if sort not in allowed:
        sort = "created_at"
    reverse = (order.lower() != "asc")

    try:
        rows = sorted(rows, key=lambda r: (getval(r, sort) or ""), reverse=reverse)
    except Exception:
        pass

    # 分页
    total = len(rows)
    pages = max(1, math.ceil(total / size))
    page = max(1, min(page, pages))
    start = (page - 1) * size
    end = start + size
    page_rows = rows[start:end]

    return templates.TemplateResponse(
        "vault.html",
        {
            "request": request,
            "cert_id": cert_id,
            "q": q,
            "rows": page_rows,
            "total": total,
            "page": page,
            "pages": pages,
            "size": size,
            "sort": sort,
            "order": "asc" if not reverse else "desc",
        },
    )

@app.get("/api/receipts/preview")
def receipts_preview(
    cert_id: str = Query(..., min_length=1),
    q: str = Query("", description="provider:tsa status:pending 等语法"),
    limit: int = Query(20, ge=1, le=200)
):
    _ensure_state(app)
    rows = app.state.receipts.get(cert_id, [])
    rows = [r for r in rows if _match_query(r, q)]
    # 统一输出 created_at 字段名，便于前端展示
    view = [
        {
            "cert_id": cert_id,
            "provider": r.get("provider"),
            "status": r.get("status"),
            "txid": r.get("txid"),
            "created_at": r.get("time"),
        }
        for r in rows[:limit]
    ]
    return {"ok": True, "total": len(rows), "limit": limit, "rows": view}


@app.get("/health")
def health(cert_id: str = Query(None)):
    base = Path(__file__).resolve().parent
    sqlite_exists = (base / "db.sqlite").exists() or (base.parent / "db.sqlite").exists()
    receipts = getattr(app.state, "receipts", {}) or {}
    if isinstance(receipts, dict):
        receipts_count = len(receipts.get(cert_id, [])) if cert_id else sum(len(v) for v in receipts.values())
    else:
        receipts_count = 0
    return {
        "ok": True,
        "service": "verify-upgrade",
        "time": datetime.utcnow().isoformat() + "Z",
        "port": 8011,
        "db": {"sqlite_exists": sqlite_exists, "receipts_count": receipts_count},
        "config": {"tsa_endpoint": os.getenv("TSA_ENDPOINT", "")},
    }
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

                # 统一把 created_at 转成字符串，模板不再调用 strftime()
                safe_hist = []
                for r in rows:
                    raw = r[3]  # 可能是字符串或 None
                    nice = str(raw) if raw is not None else None
                    try:
                        nice = datetime.datetime.fromisoformat(str(raw)).strftime("%Y-%m-%d %H:%M:%S")
                    except Exception:
                        pass
                    safe_hist.append({
                        "provider": r[0],
                        "status":   r[1],
                        "txid":     r[2],
                        "created_at": nice,
                    })
                if safe_hist:
                    ctx["history"] = safe_hist

                # evidence
                cur = conn.execute(
                    "SELECT file_path,sha256,c2pa_claim,tsa_url,sepolia_txhash,title,owner,created_at "
                    "FROM evidence WHERE cert_id=? LIMIT 1",
                    (cert_id,)
                )
                ev = cur.fetchone()
                if ev:
                    ctx["evidence"] = {
                        "file_path": ev[0],
                        "sha256": ev[1],
                        "c2pa_claim": ev[2],
                        "tsa_url": ev[3],
                        "sepolia_txhash": ev[4],
                        "title": ev[5],
                        "owner": ev[6],
                        "created_at": ev[7],
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

    return templates.TemplateResponse("verify_upgrade.html", ctx)

@app.get("/api/tsa/config")
def ci_tsa_config():
    ep = os.getenv("TSA_ENDPOINT", "http://127.0.0.1:8011/api/tsa/mock")
    return {"effective": {"endpoint": ep}}

# --- TSA ping with fallbacks (dev-safe) ---
from urllib.parse import urlparse  # 若顶部已导入，可忽略此行

@app.get("/api/tsa/ping")
def api_tsa_ping():
    endpoint = os.getenv("TSA_ENDPOINT", "http://127.0.0.1:8011/api/tsa/mock")
    base = endpoint.rstrip("/")

    candidates = [endpoint]
    if not base.endswith("/health"):
        candidates.append(base + "/health")
    u = urlparse(endpoint)
    if u.scheme and u.netloc:
        candidates.append(f"{u.scheme}://{u.netloc}/health")

    tried = []
    for url in dict.fromkeys(candidates):  # 去重保序
        tried.append(url)
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code in (200, 204):
                return {"ok": True, "endpoint": endpoint, "url": url, "status": r.status_code}
        except Exception:
            pass

    return JSONResponse({"ok": False, "endpoint": endpoint, "tried": tried}, status_code=502)

# ……（上面是你的其它代码，比如 /health、verify_upgrade_page 等）

# ===== 工具函数（放在四个端点之前）=====
def _now_str():
    import datetime, time
    try:
        return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

def _maybe_write_sqlite(cert_id: str, item: dict):
    """若 data/verify_upgrade.db 存在，则将回执补写入 receipts 表；失败不抛错"""
    import os, sqlite3
    db_path = os.path.join("data", "verify_upgrade.db")
    if not os.path.exists(db_path):
        return
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO receipts (cert_id, provider, status, txid, created_at) VALUES (?,?,?,?,?)",
                (cert_id, item.get("provider"), item.get("status"), item.get("txid"), item.get("time")),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
# ===== 工具函数结束 =====

# ===== 端点从这里开始 =====
 
@app.get("/api/tsa/mock")
def ci_tsa_mock(cert_id: str = Query("demo-cert")):
    item = {
        "provider": "tsa",
        "status":   "ok",
        "txid":     _gen_txid("0xTX_TSA_OK_"),
        "time":     _now_str(),
    }
    _append_receipt(app, cert_id, item)   # 写入内存
    _maybe_write_sqlite(cert_id, item)    # 如有 data/verify_upgrade.db 就补写
    return {"ok": True, "cert_id": cert_id, "tx": item["txid"]}

@app.get("/api/chain/mock")
def ci_chain_mock(cert_id: str = Query("demo-cert")):
    item = {
        "provider": "chain",
        "status":   "pending",
        "txid":     _gen_txid("0xTX_CHAIN_WAIT_"),
        "time":     _now_str(),
    }
    _append_receipt(app, cert_id, item)   # 写入内存 app.state.receipts
    _maybe_write_sqlite(cert_id, item)    # 若 data/verify_upgrade.db 存在则补写 sqlite
    return {"ok": True, "cert_id": cert_id, "tx": item["txid"]}

@app.get("/api/receipts/export")
def ci_export_csv(cert_id: str = Query("demo-cert"), q: str = Query("", description="同 preview/count 语法")):
    _ensure_state(app)
    rows = app.state.receipts.get(cert_id, [])
    rows = [r for r in rows if _match_query(r, q)]
    logger.info("export_csv requested cert_id=%s q=%s rows=%d", cert_id, q, len(rows))

    def gen():
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["cert_id", "provider", "status", "txid", "created_at"])
        for r in rows:
            w.writerow([cert_id, r.get("provider"), r.get("status"), r.get("txid"), r.get("time")])
        yield "\ufeff" + out.getvalue()  # UTF-8 BOM，Excel 友好

    resp = StreamingResponse(gen(), media_type="text/csv; charset=utf-8")
    resp.headers["Content-Disposition"] = f'attachment; filename="receipts_{cert_id}.csv"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

@app.post("/api/receipts/clear")
def ci_clear(cert_id: str = Query(None)):
    _ensure_state(app)
    r = app.state.receipts
    cleared = 0
    if isinstance(r, dict):
        if cert_id:
            cleared = len(r.get(cert_id, []))
            r[cert_id] = []
        else:
            cleared = sum(len(v) for v in r.values())
            app.state.receipts = {}
    return {"ok": True, "cleared": cleared}
# ===== end CI fallback =====


 

