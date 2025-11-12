# -*- coding: utf-8 -*-
"""
CSV 导出最小单测：
- 基础可用性
- 引号、逗号、换行的正确转义
运行：
  py -3 -m pytest -q tests/test_csv.py
"""
import csv, io, pathlib, importlib.util
from datetime import datetime, timezone
from fastapi.testclient import TestClient

def _load_app_main():
    root = pathlib.Path(__file__).resolve().parents[1]
    main_py = root / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("app_main", main_py)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod

def _csv_rows(text: str):
    f = io.StringIO(text)
    reader = csv.reader(f)
    return list(reader)

def test_export_csv_basic():
    app_main = _load_app_main()
    client = TestClient(app_main.app)

    cert_id = "csv-smoke"
    client.get(f"/api/tsa/mock?cert_id={cert_id}")  # 生成至少一条数据

    r = client.get(f"/api/receipts/export?cert_id={cert_id}")
    assert r.status_code == 200
    assert "text/csv" in (r.headers.get("content-type") or "").lower()

    rows = _csv_rows(r.text)
    assert len(rows) >= 2, "应至少有表头 + 1 条记录"
    assert len(rows[0]) >= 3, "表头至少包含若干列"

def test_csv_escaping_quotes_commas_newlines():
    app_main = _load_app_main()
    client = TestClient(app_main.app)

    cert_id = "csv-escapes"
    client.get(f"/api/tsa/mock?cert_id={cert_id}")  # 保底先有数据

    message = '他说："Hello, \"world\""，然后停了一下，\n接着继续。'
    extra = '逗号, 引号" 和换行\n第二行'
    tx = "0xESCAPE"

    item = {
        "txid": tx,
        "provider": "test",
        "kind": "note",
        "message": message,
        "extra": extra,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if hasattr(app_main, "_append_receipt"):
        app_main._append_receipt(app_main.app, cert_id, item)  # type: ignore[attr-defined]
    else:
        app = app_main.app
        if not hasattr(app.state, "receipts"):
            app.state.receipts = {}
        app.state.receipts.setdefault(cert_id, []).append(item)

    r = client.get(f"/api/receipts/export?cert_id={cert_id}")
    assert r.status_code == 200

    rows = _csv_rows(r.text)
    header = rows[0]
    data = [dict(zip(header, row)) for row in rows[1:]]

    rec = next((d for d in data if d.get("txid") == tx or d.get("message") == message), None)
    assert rec is not None, f"未找到注入的记录；表头：{header}"

    if "message" in rec:
        assert rec["message"] == message
    if "extra" in rec:
        assert rec["extra"] == extra
