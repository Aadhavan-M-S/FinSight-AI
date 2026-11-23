from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


def uid() -> str:
    return str(uuid4())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Base(DeclarativeBase):
    pass


data_dir = settings.finsight_data_dir.resolve()
data_dir.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{data_dir / 'finsight.sqlite3'}", connect_args={"timeout": 20})


@event.listens_for(engine, "connect")
def enable_sqlite_constraints(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA journal_mode=WAL")


Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction():
    with Session.begin() as db:
        yield db
