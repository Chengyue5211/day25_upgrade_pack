# app/upgrade25.py —— 最小可运行版（先让服务起来）
from fastapi import APIRouter

router = APIRouter()

@router.post("/run")
def run_upgrade25():
    # TODO: 这里先返回一个固定结果，等服务跑通后再补真实逻辑
    return {"ok": True}
