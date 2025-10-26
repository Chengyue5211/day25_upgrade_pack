# 强制从仓库文件路径加载 app，避免 CI 环境导到别的同名包导致 404
import pathlib, importlib.util
ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN_PY = ROOT / "app" / "main.py"

spec = importlib.util.spec_from_file_location("app_main", MAIN_PY)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader, f"Cannot load {MAIN_PY}"
spec.loader.exec_module(mod)        # 执行 app/main.py
app = mod.app                       # 取出 FastAPI 实例

from fastapi.testclient import TestClient
client = TestClient(app)


def test_health_ok():
    # 调试：打印当前 app 的路由列表
    paths = [getattr(r, "path", None) for r in app.routes]
    print("ROUTES:", paths)

    r = client.get("/health")
    j = r.json()
    assert r.status_code == 200
    assert j.get("ok") is True
    # 兼容两种格式：
    # A) 新版：{"ok":true,"db":{"db":"ok",...}}
    # B) 旧版/简版：{"ok":true,"service":"verify-upgrade",...}
    assert (("db" in j and str(j["db"].get("db")).lower() in ("ok", "true"))
            or ("service" in j))


def test_tsa_config():
    assert client.get("/api/tsa/config").status_code == 200


def test_export_and_clear():
    cert = "demo-cert"
    for _ in range(5):
        client.get(f"/api/tsa/mock?cert_id={cert}")
        client.get(f"/api/chain/mock?cert_id={cert}")
    r = client.get(f"/api/receipts/export?cert_id={cert}")
    assert r.status_code == 200 and "text/csv" in r.headers.get("content-type", "")
    j = client.post(f"/api/receipts/clear?cert_id={cert}").json()
    assert j.get("ok") and j.get("cleared", 0) >= 1
