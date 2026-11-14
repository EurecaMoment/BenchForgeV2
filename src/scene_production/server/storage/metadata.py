"""Persistent BenchForge runs, work items, and events."""

from contextlib import contextmanager
from datetime import datetime
from datetime import timezone

from sqlalchemy import JSON
from sqlalchemy import Column
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import create_engine
from sqlalchemy import select


# Keep the deployed SQL table and column names so existing runs remain readable.
schema = MetaData()
runs = Table(
    "runs", schema,
    Column("id", String, primary_key=True),
    Column("state", String, nullable=False),
    Column("plan", JSON, nullable=False),
    Column("created_at", String),
    Column("code_revision", String),
)
tasks = Table(
    "work_items", schema,
    Column("id", String, primary_key=True),
    Column("run_id", String, nullable=False, index=True),
    Column("task_id", String),
    Column("unit", JSON),
    Column("state", String),
    Column("attempt", Integer),
    Column("lease_owner", String),
    Column("lease_expires_at", Float),
    Column("ready_at", Float),
    Column("result", JSON),
    Column("artifact", JSON),
    Column("failure", JSON),
)
events = Table(
    "events", schema,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, index=True),
    Column("work_item_id", String),
    Column("event", String),
    Column("at", String),
    Column("payload", JSON),
)


class Repository:
    def __init__(self, url: str):
        if not url.startswith(("sqlite:", "postgresql+psycopg:")):
            raise ValueError("Use PostgreSQL with psycopg, or SQLite for local tests")
        self.engine = create_engine(
            url,
            connect_args={"timeout": 30} if url.startswith("sqlite:") else {},
            hide_parameters=True,
        )
        with self.transaction() as conn:
            self.lock_queue(conn)
            schema.create_all(conn)

    def lock_queue(self, conn):
        """Serialize queue changes on PostgreSQL. SQLite holds its write lock."""
        if self.engine.dialect.name == "postgresql":
            conn.exec_driver_sql("SELECT pg_advisory_xact_lock(7420391)")

    @contextmanager
    def transaction(self):
        with self.engine.connect() as conn:
            if self.engine.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                conn.begin()
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    @staticmethod
    def event(conn, run_id, task_id, event, payload=None):
        conn.execute(events.insert().values(
            run_id=run_id,
            work_item_id=task_id,
            event=event,
            at=datetime.now(timezone.utc).isoformat(),
            payload=payload or {},
        ))

    def status(self, run_id):
        with self.engine.connect() as conn:
            run = conn.execute(select(runs).where(runs.c.id == run_id)).mappings().first()
            if run is None:
                raise FileNotFoundError(f"Unknown run: {run_id}")
            work = conn.execute(
                select(tasks).where(tasks.c.run_id == run_id).order_by(tasks.c.id)
            ).mappings()
            return {**dict(run), "tasks": [dict(row) for row in work]}
