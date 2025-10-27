from fastapi.testclient import TestClient
from app.main import app
client = TestClient(app)

def test_health_ok():
    r = client.get("/health")
    j = r.json()
    assert r.status_code == 200
    assert j.get("ok") is True
    # 兼容两种格式：
    # A) 新版：{"ok":true,"db":{"db":"ok",...}}
    # B) 旧版/简版：{"ok":true,"service":"verify-upgrade",...}
    assert (
        ("db" in j and str(j["db"].get("db")).lower() in ("ok", "true"))
        or ("service" in j)
    )

def test_tsa_config():
    assert client.get("/api/tsa/config").status_code == 200

def test_export_and_clear():
    cert="demo-cert"
    for _ in range(5):
        client.get(f"/api/tsa/mock?cert_id={cert}")
        client.get(f"/api/chain/mock?cert_id={cert}")
    r = client.get(f"/api/receipts/export?cert_id={cert}")
    assert r.status_code==200 and "text/csv" in r.headers.get("content-type","")
    j = client.post(f"/api/receipts/clear?cert_id={cert}").json()
    assert j.get("ok") and j.get("cleared",0)>=1
def test_tsa_config_env_override(monkeypatch):
    # 覆盖环境变量，接口应读取到它
    monkeypatch.setenv("TSA_ENDPOINT", "http://test.local/api/tsa/mock")
    r = client.get("/api/tsa/config")  # 用上面的全局 client
    assert r.status_code == 200
    data = r.json()
    assert data["effective"]["endpoint"] == "http://test.local/api/tsa/mock"

