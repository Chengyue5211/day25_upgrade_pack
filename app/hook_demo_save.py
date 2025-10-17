# app/hook_demo_save.py
from __future__ import annotations
from app.patch_certify_verify import save_certificate, load_certificate

def after_certify_demo(cert_id: str, meta: dict):
    # meta = {title, author, verify_url, manifest_hash, anchors{kind,txid,tsa,sig}}
    save_certificate(
        cert_id=cert_id,
        title=meta.get('title'),
        author=meta.get('author'),
        verify_url=meta.get('verify_url'),
        manifest_hash=meta.get('manifest_hash'),
        anchors=meta.get('anchors'),
        attestation_type=meta.get('attestation_type', 'demo'),
        status=meta.get('status', 'ok'),
        tenant_id=meta.get('tenant_id', 'default'),
    )

def query_cert_demo(cert_id: str):
    return load_certificate(cert_id)
