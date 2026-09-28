"""Small durable queue, confined to one worker on a local filesystem."""
import json
import sqlite3
import time
from pathlib import Path


class Queue:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=WAL")
        self.db.execute("""create table if not exists jobs(
            id text primary key,payload text not null,state text not null default 'pending',
            attempts integer not null default 0,next_at real not null default 0,
            result text)""")
        # Called only after taking the process lock.
        self.db.execute("update jobs set state='pending' where state='running'")
        self.db.commit()

    def add(self, job: dict):
        self.db.execute("insert or ignore into jobs(id,payload) values(?,?)",
                        (job["ai_request_id"], json.dumps(job)))
        self.db.commit()

    def take(self):
        row = self.db.execute(
            "select * from jobs where state='pending' and next_at<=? order by rowid limit 1",
            (time.time(),)).fetchone()
        if row:
            self.db.execute("update jobs set state='running',attempts=attempts+1 where id=?",
                            (row["id"],))
            self.db.commit()
            return dict(row)
        return None

    def result(self, id: str, value: dict):
        self.db.execute("update jobs set result=? where id=?", (json.dumps(value), id))
        self.db.commit()

    def finish(self, id: str):
        # Drop vectors/transcripts from operational history after acknowledged sync.
        self.db.execute("update jobs set state='done',result=null,payload='{}' where id=?", (id,))
        self.db.commit()

    def retry(self, id: str, attempts: int):
        self.db.execute("update jobs set state='pending',next_at=? where id=?",
                        (time.time() + min(3600, 10 * 2**min(attempts, 8)), id))
        self.db.commit()
