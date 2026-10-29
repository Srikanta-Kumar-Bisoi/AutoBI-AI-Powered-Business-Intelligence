import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from sqlalchemy import JSON, DateTime, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class Base(DeclarativeBase):
    pass


class DatasetAnalysis(Base):
    __tablename__ = "dataset_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    records: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_values: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    column_summary: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


database_url = os.getenv("DATABASE_URL")
engine: Engine | None = (
    create_engine(database_url, pool_pre_ping=True) if database_url else None
)
_tables_initialized = False
_initialization_lock = Lock()
_session_factory = sessionmaker(bind=engine) if engine is not None else None


def persist_analysis(result: dict) -> bool:
    global _tables_initialized
    if engine is None or _session_factory is None:
        return False

    if not _tables_initialized:
        with _initialization_lock:
            if not _tables_initialized:
                Base.metadata.create_all(engine)
                _tables_initialized = True

    record = DatasetAnalysis(
        filename=result["filename"],
        records=result["records"],
        column_count=result["column_count"],
        missing_values=result["missing_values"],
        duplicate_rows=result["duplicate_rows"],
        column_summary=result["columns"],
        created_at=datetime.now(timezone.utc),
    )
    with _session_factory() as session:
        session.add(record)
        session.commit()
    return True
