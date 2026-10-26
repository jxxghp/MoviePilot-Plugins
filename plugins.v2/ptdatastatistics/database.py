"""MoviePilot V2 插件数据目录中的独立 SQLite 句柄。"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import PTSiteHourlySnapshot


class LocalDatabaseHandle:
    """提供与 V3 插件数据库句柄一致的最小会话接口。"""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.engine: Engine = create_engine(
            f"sqlite+pysqlite:///{self.path.as_posix()}",
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(connection, _record) -> None:
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
            finally:
                cursor.close()

        self._factory = sessionmaker(self.engine, expire_on_commit=False)
        PTSiteHourlySnapshot.__table__.create(self.engine, checkfirst=True)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """返回调用级会话；事务提交与回滚仍由仓储层显式控制。"""

        with self._lock:
            session = self._factory()
            try:
                yield session
            finally:
                session.close()

    def close(self) -> None:
        """释放 SQLite 连接池，允许插件安全重载。"""

        with self._lock:
            self.engine.dispose()
