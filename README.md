[![CI](https://github.com/Chengyue5211/day25_upgrade_pack/actions/workflows/ci.yml/badge.svg)](https://github.com/Chengyue5211/day25_upgrade_pack/actions/workflows/ci.yml)
  
# Day 2.5 · Real C2PA + TSA（RFC3161）· Upgrade Pack

这是一套**可直接跑**的最小示例，把你之前的“本地内容凭证/锚定”升级为**真 C2PA**与**真 TSA 时间戳回执**，并附带一个简易核验页。
你可以单独跑这个 demo，也可以把 `app/upgrade25.py` 复制进你现有工程并 `include_router()`。

---

## 1) 快速开始（10 分钟）

**前置**（建议）：
- 安装 Python 3.10+；
- 安装依赖：`pip install -r requirements.txt`；
- 安装 `openssl`（一般系统自带；Windows 没有的话建议用 Git Bash 或 WSL）；
- 安装 `c2patool`（macOS: `brew install c2patool`；Windows/Linux 请到 C2PA 官方仓库下载 release）。

**启动服务（开发）**
```bash
uvicorn app.main:app --reload --port 8000
```
浏览器打开：<http://127.0.0.1:8000/verify_upgrade/demo-cert>

---

## 2) Day 2.5 的三件事

- **C2PA（内容凭证）：**用 `c2patool` 给图片/视频/PDF 写入 Content Credentials（带签名）。
- **TSA（RFC3161 时间戳）：**对任何文件生成 TSQ（请求），提交到 TSA 得到 TSR（回执），并保存/核验。
- **（可选）链锚定：**把当日 Merkle Root 或单个摘要上链（此包内提供 Sepolia stub）。

---

## 3) 开发者步骤（从零开始，一步步）

### A. 生成开发用签名证书（C2PA 签名）
> 如果你已有正式证书，直接用你的证书与私钥即可。

```bash
# 生成自签名证书（365 天），仅供开发测试
openssl req -newkey rsa:2048 -nodes -keyout signer.key -x509 -days 365 -out signer.crt -subj "/CN=LeapCraft Dev Signer"
```

### B. 准备要签名的文件
任取一张 PNG/JPG（建议 `samples/hello.png`）。没有图片？可复制任意 PNG。

### C. 执行 C2PA 写签（两种方式）
1）**直接命令行（验证 c2patool 可用）**
```bash
c2patool ./samples/hello.png --signcert signer.crt --signkey signer.key --out ./samples/hello-signed.png -m app/claims/example_claim.json
```

2）**通过 API（由本服务调用 c2patool）**
```bash
# 使用 HTTP 客户端（curl 或 Postman）
curl -X POST http://127.0.0.1:8000/v1/upgrade25/c2pa/embed   -H "Content-Type: application/json"   -d '{
    "file_path":"./samples/hello.png",
    "signer_cert_path":"./signer.crt",
    "signer_key_path":"./signer.key",
    "claim_json_path":"app/claims/example_claim.json",
    "out_path":"./samples/hello-signed.png"
  }'
```
成功后会返回 `out_path`，并把结果写入本地 SQLite。

### D. 申请 TSA 时间戳回执（RFC3161）

**D1. 先生成 TSQ（请求包）**
```bash
curl -X POST http://127.0.0.1:8000/v1/upgrade25/tsa/query   -H "Content-Type: application/json"   -d '{"file_path":"./samples/hello-signed.png","hash_algo":"sha256"}'   > tsq.json
```
返回的 `tsq.json` 内含 `tsq_b64`，这是二进制请求的 Base64。

**D2. 提交 TSQ 给 TSA（示例使用 FreeTSA 测试服务）**
```bash
# 保存 tsq 到文件
python - << 'PY'
import json, base64, sys
d=json.load(open("tsq.json","r",encoding="utf-8"))
open("request.tsq","wb").write(base64.b64decode(d["tsq_b64"]))
print("Wrote request.tsq")
PY

# 提交到 TSA（FreeTSA，测试用途）
curl -s -H "Content-Type: application/timestamp-query" --data-binary @request.tsq https://freetsa.org/tsr > response.tsr

# 把 TSR 转成 Base64（便于保存）
python - << 'PY'
import base64, sys, json
tsr_b64 = base64.b64encode(open("response.tsr","rb").read()).decode()
print(json.dumps({"tsr_b64": tsr_b64}))
PY > tsr.json

# 回填到本服务，持久化保存
curl -X POST http://127.0.0.1:8000/v1/upgrade25/tsa/submit   -H "Content-Type: application/json"   -d @tsr.json
```

> 生产环境请换为你的 TSA（如 DigiCert/Sectigo 等），并妥善保存其 CA 链证书，便于校验。

**D3. 校验 TSA 回执（可选，本地 openssl）**
```bash
# 需要 TSA 的证书/CA 链，示例以 FreeTSA 为例（请参考其官网获取最新证书）
# openssl ts -verify -in response.tsr -queryfile request.tsq -CAfile freetsa.pem -untrusted freetsa.cer
```

### E. 查看核验页
访问：<http://127.0.0.1:8000/verify_upgrade/demo-cert>  
（注意：`demo-cert` 只是示意。真实项目应以你的 CERT_ID 作为主键并在 DB 中建立关联。）

---

## 4) API 一览（新加的）

- `POST /v1/upgrade25/c2pa/embed` → 用 c2patool 给文件写入 C2PA 签名（支持 claim.json）。
- `POST /v1/upgrade25/tsa/query` → 生成 RFC3161 `TSQ`（Base64）。
- `POST /v1/upgrade25/tsa/submit` → 接收 `TSR`（Base64），持久化保存。
- `POST /v1/upgrade25/anchor/sepolia` → （可选）上链锚定 Stub。

---

## 5) 与现有工程集成

- 把 `app/upgrade25.py` 与 `app/db.py` 复制到你的工程；
- 在你的 `main.py`（或等效入口）里：
```python
from app.upgrade25 import router as upgrade25_router
app.include_router(upgrade25_router, prefix="/v1/upgrade25")
```
- 把 `app/claims/example_claim.json` 放到合适位置（或用你自己的 claim）;
- 在你的核验页模板中，参考 `app/templates/verify_upgrade.html` 的展示逻辑，增加 C2PA/TSA 状态栏位。

---

## 6) 注意事项 / 常见问题

- **c2patool 未安装**：API 会返回可读错误；请先本地用命令行成功跑一遍；
- **TSA 校验**：不同 TSA 的 CA 链配置不同。生产请向 TSA 提供商索取并在你的校验流程中固定；
- **链锚定**：建议“日根上链”（合并当日批次 Merkle Root），避免成本暴涨；
- **证书与密钥**：示例中的自签证书仅用于开发；生产请替换为正式签名证书；
- **Windows**：若 `openssl` 无法使用，请在 PowerShell 中启用 WSL 或安装 Git Bash。

---

## 7) 下一步（Day 3 预告）

- 把核验页加上**二维码**（页面内纯 JS 生成）、
- 把持久化从 SQLite 升级到 Postgres，并与“多签/邀请表”打通，
- 加入“日根 Merkle 计算 + 双栈锚定（联盟链 + 公链测试网）”。

祝贺！你已完成 Day 2.5 的“真 C2PA + 真 TSA”升级最小闭环。

> Update: add CI badge and minor doc tweaks.

