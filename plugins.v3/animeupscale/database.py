from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """持久化超分任务队列"""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    input_path TEXT NOT NULL,
                    output_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    cq INTEGER NOT NULL DEFAULT 18,
                    model TEXT NOT NULL DEFAULT 'starsample_v2_lite',
                    progress REAL NOT NULL DEFAULT 0,
                    current_frame INTEGER NOT NULL DEFAULT 0,
                    total_frames INTEGER NOT NULL DEFAULT 0,
                    processing_fps REAL NOT NULL DEFAULT 0,
                    eta_seconds INTEGER,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS jobs_status_created "
                "ON jobs(status, created_at)"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS jobs_output_path_unique "
                "ON jobs(output_path)"
            )

    def recover_interrupted(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status='failed', finished_at=?,
                    error='MoviePilot 在任务运行期间停止，请重试任务'
                WHERE status='running'
                """,
                (now(),),
            )

    def create_many(
        self, paths: list[tuple[Path, Path]], cq: int, model: str
    ) -> list[dict[str, Any]]:
        rows = [
            (uuid.uuid4().hex[:12], str(source), str(target), cq, model, now())
            for source, target in paths
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                DELETE FROM jobs
                WHERE output_path=? AND status IN ('completed', 'failed', 'cancelled')
                """,
                [(str(target),) for _, target in paths],
            )
            connection.executemany(
                """
                INSERT INTO jobs (
                    id, input_path, output_path, status, cq, model, created_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?)
                """,
                rows,
            )
        return [job for row in rows if (job := self.get(row[0]))]

    def output_is_registered(self, output_path: Path) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM jobs
                WHERE output_path=? AND status IN ('queued', 'running') LIMIT 1
                """,
                (str(output_path),),
            ).fetchone()
        return row is not None

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, job_id: str) -> Optional[dict[str, Any]]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def has_queued(self) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM jobs WHERE status='queued' LIMIT 1"
            ).fetchone()
        return row is not None

    def claim_next(self) -> Optional[dict[str, Any]]:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not row:
                connection.commit()
                return None
            connection.execute(
                """
                UPDATE jobs SET status='running', started_at=?, finished_at=NULL,
                    error=NULL, cancel_requested=0
                WHERE id=? AND status='queued'
                """,
                (now(), row["id"]),
            )
            connection.commit()
        return self.get(row["id"])

    def update_progress(
        self,
        job_id: str,
        current_frame: int,
        total_frames: int,
        processing_fps: float,
        eta_seconds: Optional[int],
    ) -> None:
        progress = min(100.0, current_frame * 100.0 / total_frames) if total_frames else 0
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET progress=?, current_frame=?, total_frames=?,
                    processing_fps=?, eta_seconds=? WHERE id=?
                """,
                (
                    round(progress, 2), current_frame, total_frames,
                    round(processing_fps, 3), eta_seconds, job_id,
                ),
            )

    def finish(self, job_id: str, status: str, error: Optional[str] = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE jobs SET status=?,
                    progress=CASE WHEN ?='completed' THEN 100 ELSE progress END,
                    finished_at=?, error=?, eta_seconds=NULL WHERE id=?
                """,
                (status, status, now(), error, job_id),
            )

    def request_cancel(self, job_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row or row["status"] not in ("queued", "running"):
                return False
            if row["status"] == "queued":
                connection.execute(
                    "UPDATE jobs SET status='cancelled', finished_at=? WHERE id=?",
                    (now(), job_id),
                )
            else:
                connection.execute(
                    "UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,)
                )
        return True

    def retry(self, job_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT status FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row or row["status"] not in ("failed", "cancelled"):
                return False
            connection.execute(
                """
                UPDATE jobs SET status='queued', progress=0, current_frame=0,
                    total_frames=0, processing_fps=0, eta_seconds=NULL,
                    cancel_requested=0, error=NULL, started_at=NULL, finished_at=NULL
                WHERE id=?
                """,
                (job_id,),
            )
        return True
