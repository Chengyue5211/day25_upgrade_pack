from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from traceback import format_exc
from app.db import (
    init_db, get_db, get_evidence,
    add_receipt, get_last_receipts, get_last_status_txid,
)

app = FastAPI(title="Verify Upgrade · Minimal")
templates = Jinja2Templates(directory="app/templates")

# 初始化 DB
init_db()


class CallbackIn(BaseModel):
    cert_id: str = Field(..., examples=["demo-cert"])
    provider: str = Field(..., examples=["tsa", "chain"])
    status: str = Field(..., examples=["success", "failed", "pending"])
    txid: str | None = Field(None, examples=["0xabc123"])


@app.get("/verify_upgrade/{cert_id}", response_class=HTMLResponse)
def verify_upgrade(cert_id: str, request: Request, db: Session = Depends(get_db)):
    evidence = get_evidence(db, cert_id)
    last = get_last_status_txid(db, cert_id)
    history = get_last_receipts(db, cert_id, limit=5)

    context = {
        "request": request,
        "cert_id": cert_id,
        "evidence": evidence,
        "tsa_last_status": last.get("tsa_last_status"),
        "tsa_last_txid": last.get("tsa_last_txid"),
        "history": history,
    }
    return templates.TemplateResponse("verify_upgrade.html", context)


@app.post("/api/tsa/callback")
def tsa_callback(payload: CallbackIn, db: Session = Depends(get_db)):
    provider = "tsa"
    try:
        add_receipt(
            db,
            cert_id=payload.cert_id,
            provider=provider,
            status=payload.status,
            txid=payload.txid,
        )
        return JSONResponse({"ok": True, "provider": provider})
    except Exception:
        # 把详细错误直接返回给前端，便于排查
        return HTMLResponse(f"<pre>{format_exc()}</pre>", status_code=500)


@app.post("/api/chain/callback")
def chain_callback(payload: CallbackIn, db: Session = Depends(get_db)):
    provider = "chain"
    try:
        add_receipt(
            db,
            cert_id=payload.cert_id,
            provider=provider,
            status=payload.status,
            txid=payload.txid,
        )
        return JSONResponse({"ok": True, "provider": provider})
    except Exception:
        return HTMLResponse(f"<pre>{format_exc()}</pre>", status_code=500)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return HTMLResponse("<h3>Verify Upgrade Backend</h3><p>Try: /verify_upgrade/demo-cert</p>")
