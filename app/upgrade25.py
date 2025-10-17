
import os, base64, hashlib, subprocess, tempfile, shutil, json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
from .db import insert_evidence, update_evidence

router = APIRouter()

def sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def _check_cmd(cmd: str) -> bool:
    return shutil.which(cmd) is not None

# --------- Models ---------
class C2PAEmbedRequest(BaseModel):
    file_path: str = Field(..., description="要写入 C2PA 的文件路径（PNG/JPG/PDF/MP4 等）")
    signer_cert_path: str = Field(..., description="PEM 证书路径")
    signer_key_path: str = Field(..., description="PEM 私钥路径")
    claim_json_path: Optional[str] = Field(None, description="C2PA claim JSON（可选，不填则使用默认）")
    out_path: Optional[str] = Field(None, description="输出文件路径，默认在源文件名后加 -signed")

class TSAQueryRequest(BaseModel):
    file_path: str = Field(..., description="要生成 TSQ 的文件")
    hash_algo: str = Field("sha256", description="散列算法（sha256/sha512）")
    cert_id: Optional[str] = Field("demo-cert", description="用于持久化的 CERT_ID（可与多签证书关联）")

class TSASubmitRequest(BaseModel):
    tsr_b64: str = Field(..., description="RFC3161 TSR（Base64）")
    tsa_url: Optional[str] = Field(None, description="可记录 TSA URL 以便核验")
    cert_id: Optional[str] = Field("demo-cert", description="与之前 TSQ/文件关联")

class SepoliaAnchorRequest(BaseModel):
    digest_hex: str = Field(..., description="要上链的摘要（一般为 sha256）")
    rpc_url: Optional[str] = None
    private_key: Optional[str] = None

# --------- Endpoints ---------

@router.post("/c2pa/embed")
def c2pa_embed(req: C2PAEmbedRequest):
    if not _check_cmd("c2patool"):
        raise HTTPException(status_code=400, detail="未找到 c2patool，请先安装（macOS 可 `brew install c2patool`）")
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"未找到文件：{req.file_path}")
    if not os.path.exists(req.signer_cert_path) or not os.path.exists(req.signer_key_path):
        raise HTTPException(status_code=404, detail="签名证书或私钥不存在")

    out_path = req.out_path or _derive_out_path(req.file_path)
    claim_path = req.claim_json_path or _write_default_claim()

    cmd = [
        "c2patool", req.file_path,
        "--signcert", req.signer_cert_path,
        "--signkey", req.signer_key_path,
        "--out", out_path,
        "-m", claim_path
    ]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"c2patool 失败：{e.stderr or e.stdout}")

    # 记录 DB（以 file sha256 作为主键之一，示例用 cert_id=demo-cert）
    digest = sha256_of_file(out_path)
    insert_evidence("demo-cert", out_path, digest)
    update_evidence("demo-cert", c2pa_out=out_path, c2pa_status="signed", c2pa_signed_by=os.path.basename(req.signer_cert_path))

    # —— save to DB (demo hook) ——
from app.hook_demo_save import after_certify_demo
after_certify_demo("demo-cert", {
    "title": locals().get("title"),
    "author": locals().get("author"),
    "verify_url": out_path,          # 没有专门核验页就先用生成文件路径
    "manifest_hash": digest,         # 刚算出来的 sha256
    "anchors": {"kind": "c2pa"},     # 先放占位，后续接 TSA/链回执再补 txid/tsa/sig
    "attestation_type": "demo",
    "status": "ok",
    "tenant_id": "default",
})
# —— end of hook ——
return {"ok": True, "out_path": out_path, "sha256": digest, "log": r.stdout}

def _derive_out_path(path: str) -> str:
    root, ext = os.path.splitext(path)
    return root + "-signed" + ext

def _write_default_claim() -> str:
    # 写临时默认 claim（也可让用户上传自己的 claim）
    content = {
        "claim_generator": "LeapCraft/Upgrade25 Demo",
        "format": "image/png",
        "assertions": [
            {"label":"stds.schema-org.CreativeWork","data":{"author":"LeapCraft Demo","about":"Evidence Upgrade 2.5"}},
            {"label":"stds.iptc.photo-metadata","data":{"title":"Upgrade 2.5","caption":"Signed via c2patool"}}
        ]
    }
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    return path

@router.post("/tsa/query")
def tsa_query(req: TSAQueryRequest):
    if not os.path.exists(req.file_path):
        raise HTTPException(status_code=404, detail=f"未找到文件：{req.file_path}")
    if not _check_cmd("openssl"):
        raise HTTPException(status_code=400, detail="未找到 openssl，请安装或在 WSL/Git Bash 里运行")

    # 生成 TSQ（二进制）
    with tempfile.TemporaryDirectory() as td:
        tsq_path = os.path.join(td, "request.tsq")
        algo = req.hash_algo.lower()
        if algo not in ("sha256","sha512"):
            raise HTTPException(status_code=400, detail="hash_algo 仅支持 sha256/sha512")
        cmd = ["openssl","ts","-query","-data", req.file_path, f"-{algo}","-cert","-out", tsq_path]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"生成 TSQ 失败：{e.stderr.decode() if e.stderr else e.stdout.decode()}")

        tsq_b64 = base64.b64encode(open(tsq_path,"rb").read()).decode()
        # 也把文件摘要入库，便于核验页显示
        digest = sha256_of_file(req.file_path)
        insert_evidence(req.cert_id, req.file_path, digest)
        update_evidence(req.cert_id, tsq_b64=tsq_b64)

    return {"ok": True, "tsq_b64": tsq_b64}

@router.post("/tsa/submit")
def tsa_submit(req: TSASubmitRequest):
    # 简化：仅存储 TSR；（可扩展：同时存 TSA URL、证书链）
    update_evidence(req.cert_id, tsr_b64=req.tsr_b64, tsa_url=(req.tsa_url or ""))
    return {"ok": True}

@router.post("/anchor/sepolia")
def anchor_sepolia(req: SepoliaAnchorRequest):
    try:
        from web3 import Web3
    except Exception:
        # 未安装 web3，则作为 stub 返回
        return {"ok": False, "hint": "未安装 web3。若要启用上链，请：pip install web3 并设置 RPC_URL/PRIVATE_KEY 环境变量。"}

    rpc = req.rpc_url or os.environ.get("RPC_URL")
    pk = req.private_key or os.environ.get("PRIVATE_KEY")
    if not rpc or not pk:
        return {"ok": False, "hint": "缺少 RPC_URL 或 PRIVATE_KEY"}

    w3 = Web3(Web3.HTTPProvider(rpc))
    account = w3.eth.account.from_key(pk)

    # 直接发一笔 data = digest 的 0 ETH 交易（测试网）
    tx = {
        "from": account.address,
        "to": account.address,  # 自发自收，记录 data 即可
        "value": 0,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 21000 + 30000,  # 略加余量
        "gasPrice": w3.eth.gas_price,
        "data": bytes.fromhex(req.digest_hex)
    }
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.rawTransaction).hex()

    # 持久化
    update_evidence("demo-cert", sepolia_txhash=tx_hash)
    return {"ok": True, "tx_hash": tx_hash}
