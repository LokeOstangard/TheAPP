"""SQLAlchemy model and helpers for the daily_records table.

Uses only dialect-generic column types (Date, Float, Integer, Text) so the
same code runs unchanged against SQLite locally and Postgres in production --
switching backends is just pointing DATABASE_URL at a different connection
string. A Postgres driver (e.g. psycopg2-binary) will need to be added as a
dependency at that point; it isn't installed now since it isn't used yet.
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Optional

from sqlalchemy import Date, Float, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///theapp.db")


class Base(DeclarativeBase):
    pass


class DailyRecord(Base):
    __tablename__ = "daily_records"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    sleep_hours: Mapped[Optional[float]] = mapped_column(Float)
    hrv: Mapped[Optional[float]] = mapped_column(Float)
    resting_hr: Mapped[Optional[int]] = mapped_column(Integer)
    training_load: Mapped[Optional[float]] = mapped_column(Float)
    calendar_load: Mapped[Optional[float]] = mapped_column(Float)
    subjective_wellness: Mapped[Optional[int]] = mapped_column(Integer)
    recommendation: Mapped[Optional[str]] = mapped_column(Text)


engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    Base.metadata.create_all(engine)


def upsert_daily_record(session: Session, date: dt.date, **fields) -> DailyRecord:
    """Insert a row for `date` if none exists, else update only the given fields.

    Each data source (health, calendar, Strava, the Claude analysis step) only
    knows about its own columns, so this only touches the fields it's passed
    rather than requiring a full row every time. Safe to call repeatedly for
    the same date without creating duplicates.
    """
    record = session.get(DailyRecord, date)
    if record is None:
        record = DailyRecord(date=date)
        session.add(record)
    for key, value in fields.items():
        setattr(record, key, value)
    session.commit()
    return record


if __name__ == "__main__":
    init_db()
    print(f"Initialized daily_records table at {DATABASE_URL}")
