from __future__ import annotations
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DB_URL = os.getenv("DB_URL", "sqlite:///./data.db")

class Base(DeclarativeBase): ...
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db():
    from . import models  # noqa: F401
    Base.metadata.create_all(bind=engine)

def get_db():
@"
from __future__ import annotations
from sqlalchemy import String, Integer, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Certificate(Base):
    __tablename__ = "certificate"
    cert_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str | None] = mapped_column(String(32))
    attestation_type: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str | None] = mapped_column(String(256))
    author: Mapped[str | None] = mapped_column(String(128))
    verify_url: Mapped[str | None] = mapped_column(String(512))
    manifest_hash: Mapped[str | None] = mapped_column(String(128))
    anchors: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[str | None] = mapped_column(String(32))

class ConsentLedger(Base):
    __tablename__ = "consent_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cert_id: Mapped[str] = mapped_column(String(128))
    actor: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[str] = mapped_column(String(32))
    tenant_id: Mapped[str | None] = mapped_column(String(64))

class Anchor(Base):
    __tablename__ = "anchors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cert_id: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16))
    txid: Mapped[str | None] = mapped_column(String(128))
    tsa: Mapped[str | None] = mapped_column(String(64))
    sig: Mapped[str | None] = mapped_column(String(256))
    ts: Mapped[str] = mapped_column(String(32))
