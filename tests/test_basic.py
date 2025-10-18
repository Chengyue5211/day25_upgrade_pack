from fastapi.testclient import TestClient
from app.main import app

def test_verify_page():
    c = TestClient(app)
    r = c.get("/verify_upgrade/demo-cert")
    assert r.status_code == 200
