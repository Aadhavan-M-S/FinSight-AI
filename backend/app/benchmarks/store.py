import json
import shutil
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from ..database import data_dir, now
from .catalog import MIB
from .schemas import Record

SCHEMA = """
CREATE TABLE IF NOT EXISTS installations (
  dataset_id TEXT NOT NULL, split TEXT NOT NULL, revision TEXT NOT NULL,
  record_count INTEGER NOT NULL, bytes INTEGER NOT NULL, artifacts TEXT NOT NULL, installed_at TEXT NOT NULL,
  PRIMARY KEY (dataset_id, split)
);
CREATE TABLE IF NOT EXISTS records (
  dataset_id TEXT NOT NULL, split TEXT NOT NULL, ordinal INTEGER NOT NULL, question_id TEXT NOT NULL,
  question TEXT NOT NULL, has_answer INTEGER NOT NULL, answer_type TEXT, payload TEXT NOT NULL,
  PRIMARY KEY (dataset_id, split, ordinal), UNIQUE (dataset_id, split, question_id),
  FOREIGN KEY (dataset_id, split) REFERENCES installations (dataset_id, split) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS install_jobs (
  dataset_id TEXT PRIMARY KEY, split TEXT NOT NULL, state TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
  message TEXT, downloaded INTEGER NOT NULL DEFAULT 0, expected INTEGER, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, split TEXT NOT NULL, revision TEXT NOT NULL, task TEXT NOT NULL,
  config TEXT NOT NULL, state TEXT NOT NULL, target INTEGER NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0,
  error TEXT, started_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS predictions (
  run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, ordinal INTEGER NOT NULL,
  question_id TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
  PRIMARY KEY (run_id, ordinal)
);
CREATE INDEX IF NOT EXISTS runs_scope ON runs (dataset_id, split, state);
"""
MAX_RECORD = 8 * MIB
MAX_NORMALIZED = 2 * 1024 * MIB
MAX_ROWS = 100000
ACTIVE_INSTALL = {"downloading", "processing"}
ACTIVE_RUN = {"queued", "running"}


class BenchmarkStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "workspace.sqlite3"

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=20)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db

    def initialize(self):
        self.root.mkdir(parents=True, exist_ok=True)
        new_database = not self.path.exists()
        with self.connect() as db:
            if new_database:
                db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            db.execute(
                """
                UPDATE install_jobs SET state='failed', message='Installation interrupted. Reinstall to retry.',
                    updated_at=? WHERE state IN ('downloading','processing')
            """,
                (now(),),
            )
            db.execute(
                """
                UPDATE runs SET state='interrupted', error='Service restarted during evaluation.', finished_at=?
                WHERE state IN ('queued','running')
            """,
                (now(),),
            )
        for pattern in (".manifest-*", ".filing-*", ".run-*", "*/.install-*", ".import-*"):
            for path in self.root.glob(pattern):
                if path.parent.resolve().is_relative_to(self.root.resolve()):
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path, ignore_errors=True)
                    elif path.is_file():
                        path.unlink(missing_ok=True)

    def job(self, dataset_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM install_jobs WHERE dataset_id=?", (dataset_id,)).fetchone()
        return dict(row) if row else None

    def set_job(self, dataset_id, split, state, progress=0, message=None, downloaded=0, expected=None):
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO install_jobs VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(dataset_id) DO UPDATE SET
                split=excluded.split,state=excluded.state,progress=excluded.progress,message=excluded.message,
                downloaded=excluded.downloaded,expected=excluded.expected,updated_at=excluded.updated_at
            """,
                (dataset_id, split, state, progress, message, downloaded, expected, now()),
            )

    def installed(self, dataset_id):
        with self.connect() as db:
            return [
                {**dict(row), "artifacts": json.loads(row["artifacts"])}
                for row in db.execute(
                    """
                SELECT split,revision,record_count,bytes,installed_at,artifacts FROM installations
                WHERE dataset_id=? ORDER BY split
            """,
                    (dataset_id,),
                )
            ]

    def installation(self, dataset_id, split):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM installations WHERE dataset_id=? AND split=?", (dataset_id, split)
            ).fetchone()
        return dict(row) if row else None

    def swap(self, staged, dataset_id, split, revision, count, artifacts):
        size = sum(item["bytes"] for item in artifacts)
        with self.connect() as db:
            db.execute("ATTACH DATABASE ? AS staged", (str(staged),))
            db.execute("DELETE FROM installations WHERE dataset_id=? AND split=?", (dataset_id, split))
            db.execute(
                "INSERT INTO installations VALUES (?,?,?,?,?,?,?)",
                (dataset_id, split, revision, count, size, json.dumps(artifacts), now()),
            )
            db.execute(
                """
                INSERT INTO records SELECT ?,?,ordinal,question_id,question,has_answer,answer_type,payload
                FROM staged.records
            """,
                (dataset_id, split),
            )
            db.execute(
                """
                UPDATE install_jobs SET state='ready',progress=1,message=NULL,downloaded=?,expected=?,updated_at=?
                WHERE dataset_id=? AND split=?
            """,
                (size, size, now(), dataset_id, split),
            )

    def remove(self, dataset_id, split=None):
        with self.connect() as db:
            if split is None:
                db.execute("DELETE FROM installations WHERE dataset_id=?", (dataset_id,))
                db.execute("DELETE FROM install_jobs WHERE dataset_id=?", (dataset_id,))
            else:
                db.execute("DELETE FROM installations WHERE dataset_id=? AND split=?", (dataset_id, split))
                db.execute("DELETE FROM install_jobs WHERE dataset_id=? AND split=?", (dataset_id, split))
        with self.connect() as db:
            db.execute("PRAGMA incremental_vacuum")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()

    def samples(self, dataset_id, split, search, limit, offset):
        with self.connect() as db:
            query = "FROM records WHERE dataset_id=? AND split=? AND instr(lower(question),lower(?)) > 0"
            criteria = (dataset_id, split, search)
            total = db.execute(f"SELECT count(*) {query}", criteria).fetchone()[0]
            rows = db.execute(
                f"SELECT question_id,question,has_answer,answer_type {query} ORDER BY ordinal LIMIT ? OFFSET ?",
                (*criteria, limit, offset),
            )
            return total, [dict(row) for row in rows]

    def sample(self, dataset_id, split, question_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM records WHERE dataset_id=? AND split=? AND question_id=?",
                (dataset_id, split, question_id),
            ).fetchone()
        return Record.model_validate_json(row[0]) if row else None

    def evaluation_ids(self, dataset_id, split, limit, task):
        with self.connect() as db:
            query = """
                SELECT question_id FROM records WHERE dataset_id=? AND split=?
                AND (? = 'retrieval' OR has_answer=1)
                AND (? != 'numerical' OR answer_type IN ('numeric','arithmetic','count'))
                ORDER BY ordinal LIMIT ?
            """
            return [row[0] for row in db.execute(query, (dataset_id, split, task, task, limit))]


def stage_records(staged: Path, records):
    with closing(sqlite3.connect(staged)) as db, db:
        db.execute("""
            CREATE TABLE records (
             ordinal INTEGER PRIMARY KEY,question_id TEXT UNIQUE,question TEXT,has_answer INTEGER,
             answer_type TEXT,payload TEXT
            )
        """)
        count, size, checked = 0, 0, 0
        for record in records:
            count += 1
            if count > MAX_ROWS:
                raise ValueError("The selected split exceeds the local record limit.")
            payload = record.model_dump_json()
            length = len(payload.encode())
            size += length
            if length > MAX_RECORD or size > MAX_NORMALIZED:
                raise ValueError("The normalized split exceeds the local storage limit.")
            if size - checked >= 16 * MIB:
                if shutil.disk_usage(staged.parent).free < 32 * MIB:
                    raise ValueError("The normalized split would exceed the available disk space.")
                checked = size
            db.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?)",
                (
                    count - 1,
                    record.question_id,
                    record.question,
                    record.gold_answer is not None,
                    record.answer_type,
                    payload,
                ),
            )
        if not count:
            raise ValueError("The selected split contains no usable records.")
    return count


store = BenchmarkStore(data_dir / "benchmarks")
