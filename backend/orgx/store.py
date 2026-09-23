import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

def canonical(value) -> str:
    if hasattr(value, 'model_dump'):
        value = value.model_dump(mode='json')
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS artifacts (key TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, audit_id TEXT NOT NULL,
                    finding_id TEXT NOT NULL, status TEXT NOT NULL, actor TEXT NOT NULL,
                    note TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key):
        with self.connect() as db:
            row=db.execute('SELECT body FROM artifacts WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?)',(key,canonical(value)))
        return self.get(key)

    def review(self, audit_id, finding_id, status, actor, note):
        with self.connect() as db:
            db.execute('INSERT INTO reviews (audit_id,finding_id,status,actor,note,created_at) VALUES (?,?,?,?,?,?)',
                       (audit_id,finding_id,status,actor,note,datetime.now(timezone.utc).isoformat()))
        return self.reviews(audit_id)

    def reviews(self, audit_id):
        with self.connect() as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute('SELECT * FROM reviews WHERE audit_id=? ORDER BY id',(audit_id,))]
