from datetime import datetime
from typing import List, Optional, Dict, Any

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import sessionmaker, declarative_base, relationship, Session

# 本地 SQLite（需要可改成你的正式连接串）
DATABASE_URL = "sqlite:///./data.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class CertRecord(Base):
    __tablename__ = "cert_records"
    id = Column(Integer, primary_key=True, index=True)
    cert_id = Column(String(255), unique=True, index=True, nullable=False)

    # 示例元数据字段（可按需替换成你的真实列）
    file_path = Column(Text, default="demo/path/to/file.pdf")
    sha256 = Column(String(128), default="demo_sha256")
    c2pa_claim = Column(String(255), default="demo_claim")
    tsa_url = Column(String(255), default="https://tsa.example.com/demo")
    sepolia_txhash = Column(String(255), default="0xsepolia_demo")

    receipts = relationship("Receipt", back_populates="cert", cascade="all, delete-orphan")

class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, index=True)
    cert_id = Column(String(255), ForeignKey("cert_records.cert_id"), index=True, nullable=False)
    provider = Column(String(64), nullable=False)   # "tsa" / "chain"
    status = Column(String(64), nullable=False)     # "success" / "pending" / "failed"
    txid = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    cert = relationship("CertRecord", back_populates="receipts")

# 组合索引：按证书+时间倒序查询
Index("idx_receipts_cert_time", Receipt.cert_id, Receipt.created_at.desc())

from sqlalchemy import inspect  # 放在文件顶部其它 import 附近（若已导入可忽略）

def init_db() -> None:
    """
    启动自检：如果发现 cert_records 表缺少我们需要的新列，就先 drop_all 再 create_all。
    只影响本地测试数据，不影响线上。
    """
    try:
        insp = inspect(engine)
        cols = [c["name"] for c in insp.get_columns("cert_records")]
    except Exception:
        cols = []

    required = {"file_path", "sha256", "c2pa_claim", "tsa_url", "sepolia_txhash"}
    if not required.issubset(set(cols)):
        # 表结构不完整：先全部丢弃再重建
        Base.metadata.drop_all(bind=engine)

    Base.metadata.create_all(bind=engine)


def get_db() -> Session:
    return SessionLocal()

def ensure_cert(db: Session, cert_id: str) -> CertRecord:
    inst = db.query(CertRecord).filter(CertRecord.cert_id == cert_id).first()
    if inst is None:
        inst = CertRecord(cert_id=cert_id)
        db.add(inst); db.commit(); db.refresh(inst)
    return inst

def add_receipt(db: Session, cert_id: str, provider: str, status: str, txid: Optional[str] = None) -> Receipt:
    ensure_cert(db, cert_id)
    r = Receipt(cert_id=cert_id, provider=provider, status=status, txid=txid)
    db.add(r); db.commit(); db.refresh(r)
    return r

def get_last_receipts(db: Session, cert_id: str, limit: int = 5) -> List[Receipt]:
    return (db.query(Receipt)
              .filter(Receipt.cert_id == cert_id)
              .order_by(Receipt.created_at.desc())
              .limit(limit)
              .all())

def get_last_status_txid(db: Session, cert_id: str) -> Dict[str, Optional[str]]:
    last = (db.query(Receipt)
              .filter(Receipt.cert_id == cert_id)
              .order_by(Receipt.created_at.desc())
              .first())
    return {
        "tsa_last_status": last.status if last else None,
        "tsa_last_txid": last.txid if last else None,
    }

def get_evidence(db: Session, cert_id: str) -> Dict[str, Any]:
    """页面展示需要的证据字段（示例）。"""
    cert = ensure_cert(db, cert_id)
    return {
        "file_path": cert.file_path,
        "sha256": cert.sha256,
        "c2pa_claim": cert.c2pa_claim,
        "tsa_url": cert.tsa_url,
        "sepolia_txhash": cert.sepolia_txhash,
    }
