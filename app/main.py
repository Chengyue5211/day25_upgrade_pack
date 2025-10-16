
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
    return templates.TemplateResponse("verify_upgrade.html", {"request": request, "ev": ev, "cert_id": cert_id})
