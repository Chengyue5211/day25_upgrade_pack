
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .upgrade25 import router as upgrade25_router
from .db import get_evidence

app = FastAPI(title="Upgrade 2.5 Demo")
app.include_router(upgrade25_router, prefix="/v1/upgrade25")

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

@app.get("/verify_upgrade/{cert_id}", response_class=HTMLResponse)
def verify_upgrade(request: Request, cert_id: str):
    ev = get_evidence(cert_id)
   # —— load from DB (demo hook) ——
try:
    from app.hook_demo_save import query_cert_demo
    db_row = query_cert_demo("demo-cert")   # 先用 demo-cert；有真实 cert_id 就替换掉
    if isinstance(db_row, dict):
        # 例：把 DB 的字段带进响应，便于在核验页显示
        locals().update({
            "db_title": db_row.get("title"),
            "db_created_at": db_row.get("created_at"),
            "db_verify_url": db_row.get("verify_url"),
            "db_manifest_hash": db_row.get("manifest_hash"),
        })
except Exception as e:
    print("query_certificate(hook) failed:", e)
# —— end of hook ——
 return templates.TemplateResponse("verify_upgrade.html", {"request": request, "ev": ev, "cert_id": cert_id})
