from __future__ import annotations
import datetime as dt
from typing import Optional
from sqlalchemy import select
from .db import SessionLocal
from .models import Certificate, Anchor

ISO = '%Y-%m-%dT%H:%M:%S'

def save_certificate(
    cert_id: str,
    title: Optional[str] = None,
    author: Optional[str] = None,
    verify_url: Optional[str] = None,
    manifest_hash: Optional[str] = None,
    anchors: Optional[dict] = None,
    tenant_id: str = 'default',
    status: str = 'ok',
    attestation_type: str = 'demo',
):
    now = dt.datetime.utcnow().strftime(ISO)
    with SessionLocal() as db:
        obj = db.get(Certificate, cert_id) or Certificate(cert_id=cert_id)
        obj.title = title or obj.title
        obj.author = author or obj.author
        obj.verify_url = verify_url or obj.verify_url
        obj.manifest_hash = manifest_hash or obj.manifest_hash
        obj.anchors = anchors or obj.anchors
        obj.tenant_id = tenant_id
        obj.status = status
        obj.attestation_type = attestation_type
        obj.created_at = obj.created_at or now
        db.add(obj)
        if anchors:
            db.add(Anchor(cert_id=cert_id, kind=anchors.get('kind','tsa'),
                          txid=anchors.get('txid'), tsa=anchors.get('tsa'),
                          sig=anchors.get('sig'), ts=now))
        db.commit()

def load_certificate(cert_id: str) -> Optional[dict]:
    with SessionLocal() as db:
        obj = db.execute(select(Certificate).where(Certificate.cert_id==cert_id)).scalar_one_or_none()
        if not obj:
            return None
        return {
            'cert_id': obj.cert_id,
            'title': obj.title,
            'author': obj.author,
            'verify_url': obj.verify_url,
            'manifest_hash': obj.manifest_hash,
            'anchors': obj.anchors,
            'created_at': obj.created_at,
            'tenant_id': obj.tenant_id,
            'status': obj.status,
            'attestation_type': obj.attestation_type,
        }
