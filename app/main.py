
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .upgrade25 import router as upgrade25_router
from .db import get_evidence
from .db import SessionLocal, Receipt

app = FastAPI(title="Upgrade 2.5 Demo")
app.include_router(upgrade25_router, prefix="/v1/upgrade25")

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
 
@app.get("/verify_upgrade/{cert_id}", response_class=HTMLResponse)
def verify_upgrade(request: Request, cert_id: str):
    ev = get_evidence(cert_id)  # —— load from DB (demo hook) ——

    try:
        from app.hook_demo_save import query_cert_demo
        db_row = query_cert_demo("demo-cert")  # 先用 demo-cert；有真实 cert_id 就替换
        if isinstance(db_row, dict):
            # 把 DB 的字段并到 ev，模板里更好显示
            ev.update({
                "db_title": db_row.get("title"),
                "db_created_at": db_row.get("created_at"),
                "db_verify_url": db_row.get("verify_url"),
                "db_manifest_hash": db_row.get("manifest_hash"),
            })
    except Exception as e:
        print("query_certificate(hook) failed:", e)
     context = {
"request": request,
"ev": ev,
"cert_id": cert_id,
"db_title": ev.get("title"),
"db_created_at": ev.get("created_at"),
"db_verify_url": ev.get("verify_url"),
"db_manifest_hash": ev.get("manifest_hash"),
}
    # 最近一条 TSA 回执（可选）
    try:
        with SessionLocal() as db:
            last = (
                db.query(Receipt)
                  .filter(Receipt.cert_id == cert_id)
                  .order_by(Receipt.created_at.desc())
                  .first()
            )
        if last:
            context.update({
                "tsa_last_status": last.status,
                "tsa_last_txid": last.txid or "-",
            })
    except Exception:
        pass

    return templates.TemplateResponse("verify_upgrade.html", context)

from fastapi import APIRouter, Request, HTTPException
@app.post("/api/tsa/callback")
async def tsa_callback(request: Request):
    body = await request.json()
    cert_id = body.get("cert_id")
    if not cert_id:
        raise HTTPException(status_code=400, detail="cert_id required")

    # 写入 receipts
    with SessionLocal() as db:
        rec = Receipt(
            cert_id=cert_id,
            provider=body.get("provider") or "tsa",
            status=body.get("status") or "success",
            txid=body.get("txid"),
            payload=body,
        )
        db.add(rec)
        db.commit()
    return {"ok": True}



